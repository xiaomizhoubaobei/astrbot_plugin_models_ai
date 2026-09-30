"""回归测试：图片编辑的远程取图分支必须复用统一下载/重试链路.

背景（PR #60 review）：
``edit_image`` 的 ``download_urls=True`` 分支原先就地手写了一段
``session.get`` 取图逻辑，存在三类问题：

1. **响应未关闭**：``await session.get(...)`` 拿到的是「已进入响应体读取
   阶段」的上下文管理器，必须显式 ``async with`` / ``release()`` 才会把
   连接还给连接池；裸用会让共享 Session 的连接被长期占住。
2. **不可重试**：瞬时 DNS / 连接抖动直接抛出，用户白等一次编辑。
3. **文案不脱敏**：``raise_for_status()``/裸异常可能把 URL、query 带进回包。

修复方式：改为复用 ``_download_remote_image``（统一超时 + 指数退避重试 +
中文分类脱敏）。本测试用本地 HTTP 服务与假 session 夹住这三条契约。
"""

import asyncio
import sys
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))


class _FakeResponse:
    """最小化 aiohttp 响应替身，支持 ``async with`` 与 ``release``."""

    def __init__(self, body: bytes, status: int = 200, content_type: str = "image/png"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    async def read(self) -> bytes:
        return self._body

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None,  # type: ignore[arg-type]
                history=(),
                status=self.status,
                message=f"HTTP {self.status}",
            )

    def release(self) -> None:  # pragma: no cover - 供 async with 路径调用
        pass

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc_info) -> None:
        self.release()


class _FakeSession:
    """记录 ``get`` 调用与响应释放次数的 Session 替身."""

    def __init__(self, tracker: dict, response: _FakeResponse, fail_times: int = 0):
        self.tracker = tracker
        self.response = response
        self.fail_times = fail_times

    def get(self, *args, **kwargs):
        self.tracker["calls"] += 1
        self.tracker["kwargs"].append(kwargs)
        if self.tracker["calls"] <= self.fail_times:
            raise aiohttp.ClientConnectionError("connection reset by peer")
        return _AsyncCtx(self.response, self.tracker)


class _AsyncCtx:
    """把替身响应包装成「可直接 await，也可 async with」的对象."""

    def __init__(self, response: _FakeResponse, tracker: dict):
        self._response = response
        self._tracker = tracker

    def __await__(self):
        async def _inner():
            self._tracker["awaited"] += 1
            return self._response

        return _inner().__await__()

    async def __aenter__(self) -> _FakeResponse:
        self._tracker["entered"] += 1
        return self._response

    async def __aexit__(self, *exc_info) -> None:
        self._tracker["exited"] += 1
        self._response.release()


@pytest.fixture()
def client():
    """构造一个绕开 AstrBot 依赖的 GiteeAIClient（仅测取图分支）."""
    from astrbot_plugin_models_ai.gitee.api_client import GiteeAIClient

    return GiteeAIClient(
        api_keys=["sk-test-placeholder"],
        model="test-model",
        default_size="1024x1024",
        num_inference_steps=4,
        negative_prompt="",
        base_url="https://example.invalid/v1",
    )


def test_remote_fetch_uses_async_with_and_retries(client):
    """远程取图必须走 ``async with``（响应被释放）且瞬时故障可重试."""
    tracker = {"calls": 0, "awaited": 0, "entered": 0, "exited": 0, "kwargs": []}
    session = _FakeSession(tracker, _FakeResponse(b"png-bytes"), fail_times=1)

    content, mime = asyncio.run(
        client._download_remote_image("http://x/1.png", session)
    )

    assert content == b"png-bytes"
    assert mime == "image/png"
    assert tracker["calls"] == 2, "首次瞬时空故障应触发一次重试"
    assert tracker["exited"] == 1, "响应必须被关闭（async with 退出）"
    assert tracker["kwargs"], "取图必须显式传入统一超时"

    from astrbot_plugin_models_ai.core.net_errors import build_timeout

    timeout = tracker["kwargs"][-1].get("timeout")
    assert isinstance(timeout, aiohttp.ClientTimeout)
    assert timeout.connect == build_timeout().connect
    assert timeout.total is not None and timeout.total >= build_timeout().connect


def test_remote_fetch_non_2xx_fails_fast_without_retry(client):
    """非 2xx 属确定性失败：不重试，且回包是脱敏中文."""
    tracker = {"calls": 0, "awaited": 0, "entered": 0, "exited": 0, "kwargs": []}
    session = _FakeSession(tracker, _FakeResponse(b"", status=403))

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(
            client._download_remote_image("http://x/secret.png?token=abc", session)
        )

    assert tracker["calls"] == 1, "4xx 不应重试"
    assert tracker["exited"] == 1, "失败路径同样必须关闭响应"
    message = str(excinfo.value)
    assert "abc" not in message, "回包不得泄露 URL query 中的凭证"
    assert "API Key" in message or "拒绝" in message


def test_shared_session_connection_not_leaked(client):
    """端到端：把连接池限制为 1，验证取图后连接可用（旧写法会卡死）."""

    async def scenario() -> None:
        async def handler(request):
            return web.Response(body=b"ok" * 10, content_type="image/png")

        app = web.Application()
        app.router.add_get("/img", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        connector = aiohttp.TCPConnector(limit=1)
        async with aiohttp.ClientSession(
            connector=connector, timeout=aiohttp.ClientTimeout(total=5)
        ) as session:
            url = f"http://127.0.0.1:{port}/img"
            await client._download_remote_image(url, session)
            # 连接若未归还，这里会等待到超时
            async with session.get(url) as resp:
                assert resp.status == 200

        await runner.cleanup()

    asyncio.run(scenario())
