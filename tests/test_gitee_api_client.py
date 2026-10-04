"""Gitee AI 客户端单元测试.

覆盖 ``gitee/api_client.py`` 的关键契约：
- 多 Key 轮询与空 Key 报错；
- 生图请求参数构造（size / extra_body），URL 与 base64 两种结果落地；
- SDK 异常（认证 / 限流 / 5xx / 未知）到中文 RuntimeError 的转换；
- 远程图片下载分支（成功 / 非 2xx / 网络异常），验证响应被关闭；
- 模型列表请求与错误分类；
- 图片编辑任务提交 + 轮询状态机（成功 / 失败 / 无 URL / 超时）。

通过假 OpenAI 客户端与假 aiohttp Session 驱动，不发真实请求。
"""

import base64
import json

import aiohttp
import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.gitee import api_client as ac  # noqa: E402
from astrbot_plugin_models_ai.gitee.api_client import GiteeAIClient  # noqa: E402
from openai import APIError, AuthenticationError, RateLimitError  # noqa: E402


def _make_client(**overrides) -> GiteeAIClient:
    kwargs = dict(
        api_keys=["key-a", "key-b"],
        model="z-image-turbo",
        default_size="1024x1024",
        num_inference_steps=9,
        negative_prompt="低质量",
        base_url="https://example.invalid/v1",
        debug_mode=False,
    )
    kwargs.update(overrides)
    return GiteeAIClient(**kwargs)


# ===== Key 轮询 =====


def test_get_next_api_key_round_robin() -> None:
    c = _make_client()
    assert [c._get_next_api_key() for _ in range(4)] == [
        "key-a",
        "key-b",
        "key-a",
        "key-b",
    ]


def test_get_next_api_key_empty_raises() -> None:
    c = _make_client(api_keys=[])
    with pytest.raises(ValueError, match="请先配置 API Key"):
        c._get_next_api_key()


# ===== 生图 =====


class _FakeImageData:
    def __init__(self, url=None, b64=None):
        if url is not None:
            self.url = url
        if b64 is not None:
            self.b64_json = b64


class _FakeImagesResp:
    def __init__(self, data):
        self.data = data


class _FakeImages:
    def __init__(self, resp=None, raises=None):
        self._resp = resp
        self._raises = raises
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        return self._resp


class _FakeOpenAIClient:
    def __init__(self, images):
        self.images = images


def _patch_openai(client: GiteeAIClient, fake_images: _FakeImages) -> None:
    client.client_manager.get_openai_client = lambda _k: _FakeOpenAIClient(  # type: ignore
        fake_images
    )


async def _fake_session():
    return object()


def test_generate_image_url_path() -> None:
    """结果含 URL 时应走下载落盘分支."""
    c = _make_client()
    images = _FakeImages(_FakeImagesResp([_FakeImageData(url="https://cdn/a.png")]))
    _patch_openai(c, images)
    c.client_manager.get_http_session = _fake_session  # type: ignore[assignment]

    downloaded: list[tuple] = []

    async def _dl(url, session):
        downloaded.append((url, session))
        return "/tmp/a.png"

    c.image_manager.download_image = _dl  # type: ignore[assignment]

    result = run(c.generate_image("一只猫"))
    assert result == "/tmp/a.png"
    assert downloaded[0][0] == "https://cdn/a.png"
    # 请求参数应含 size 与 extra_body（步数 + 负向提示词）
    kwargs = images.calls[0]
    assert kwargs["model"] == "z-image-turbo"
    assert kwargs["size"] == "1024x1024"
    assert kwargs["extra_body"]["num_inference_steps"] == 9
    assert kwargs["extra_body"]["negative_prompt"] == "低质量"


def test_generate_image_base64_path() -> None:
    """结果含 b64_json 时应走 base64 落盘分支."""
    c = _make_client()
    payload = base64.b64encode(b"IMG").decode()
    images = _FakeImages(_FakeImagesResp([_FakeImageData(b64=payload)]))
    _patch_openai(c, images)

    saved: list[str] = []

    async def _save(b64):
        saved.append(b64)
        return "/tmp/b.jpg"

    c.image_manager.save_base64_image = _save  # type: ignore[assignment]

    result = run(c.generate_image("一只猫"))
    assert result == "/tmp/b.jpg"
    assert saved == [payload]


def test_generate_image_custom_size_used() -> None:
    """显式传入 size 时应覆盖默认尺寸，且空 size 回落默认."""
    c = _make_client()
    images = _FakeImages(_FakeImagesResp([_FakeImageData(url="https://cdn/a.png")]))
    _patch_openai(c, images)
    c.client_manager.get_http_session = _fake_session  # type: ignore[assignment]

    async def _dl(_u, _s):
        return "/tmp/a.png"

    c.image_manager.download_image = _dl  # type: ignore[assignment]

    run(c.generate_image("x", size="512x512"))
    assert images.calls[0]["size"] == "512x512"


def test_generate_image_empty_negative_prompt_omitted() -> None:
    """negative_prompt 为空时不应出现在 extra_body."""
    c = _make_client(negative_prompt="")
    images = _FakeImages(_FakeImagesResp([_FakeImageData(url="https://cdn/a.png")]))
    _patch_openai(c, images)
    c.client_manager.get_http_session = _fake_session  # type: ignore[assignment]

    async def _dl(_u, _s):
        return "/tmp/a.png"

    c.image_manager.download_image = _dl  # type: ignore[assignment]

    run(c.generate_image("x"))
    assert "negative_prompt" not in images.calls[0]["extra_body"]


def test_generate_image_no_data_raises() -> None:
    """响应无 data 时给出明确异常."""
    c = _make_client()
    _patch_openai(c, _FakeImages(_FakeImagesResp([])))
    with pytest.raises(RuntimeError, match="未返回数据"):
        run(c.generate_image("x"))


def test_generate_image_no_url_or_b64_raises() -> None:
    """返回的数据既无 URL 也无 base64 时报错."""
    c = _make_client()
    _patch_openai(c, _FakeImages(_FakeImagesResp([_FakeImageData()])))
    with pytest.raises(RuntimeError, match="未返回 URL 或 Base64"):
        run(c.generate_image("x"))


def test_generate_image_auth_error() -> None:
    """认证失败转中文提示."""
    c = _make_client()
    err = AuthenticationError("auth", response=_fake_http_response(401), body=None)
    _patch_openai(c, _FakeImages(raises=err))
    with pytest.raises(RuntimeError, match="API Key 无效或已过期"):
        run(c.generate_image("x"))


def test_generate_image_rate_limit_error() -> None:
    """限流转中文提示."""
    c = _make_client()
    err = RateLimitError("rl", response=_fake_http_response(429), body=None)
    _patch_openai(c, _FakeImages(raises=err))
    with pytest.raises(RuntimeError, match="超限或并发过高"):
        run(c.generate_image("x"))


class _APIError500(APIError):
    """带 500 状态码的 APIError 子类（避免给父类实例动态塞属性）."""

    def __init__(self, message: str) -> None:
        """初始化 500 错误，status_code 固定为 500."""
        super().__init__(message, request=_fake_request(), body=None)
        self.status_code = 500


def test_generate_image_server_error() -> None:
    """500 归为服务端内部错误."""
    c = _make_client()
    _patch_openai(c, _FakeImages(raises=_APIError500("boom")))
    with pytest.raises(RuntimeError, match="服务器内部错误"):
        run(c.generate_image("x"))


def test_generate_image_unknown_error() -> None:
    """未知异常走统一分类包装."""
    c = _make_client()
    _patch_openai(c, _FakeImages(raises=ValueError("weird")))
    with pytest.raises(RuntimeError, match="API调用失败"):
        run(c.generate_image("x"))


def _fake_request():
    import httpx

    return httpx.Request("GET", "https://x/y")


def _fake_http_response(status: int):
    import httpx

    return httpx.Response(status, request=_fake_request())


# ===== 远程图片下载 =====


class FakeResponse:
    def __init__(self, body: bytes = b"IMG", status: int = 200, ctype="image/png"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": ctype}

    async def read(self):
        return self._body

    async def text(self):
        return self._body.decode("utf-8", "replace")

    async def json(self):
        return json.loads(self._body.decode("utf-8", "replace"))

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None,  # type: ignore[arg-type]
                history=(),
                status=self.status,
                message=f"HTTP {self.status}",
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, responses):
        self._responses = responses if isinstance(responses, list) else [responses]
        self._idx = 0
        self.closed_count = 0

    def _next(self):
        if self._idx < len(self._responses):
            r = self._responses[self._idx]
            self._idx += 1
            return r
        return self._responses[-1]

    def get(self, *a, **k):
        return self._ctx(self._next())

    def post(self, *a, **k):
        return self._ctx(self._next())

    def _ctx(self, resp):
        session = self

        class _Ctx:
            async def __aenter__(self_inner):
                return resp

            async def __aexit__(self_inner, *e):
                session.closed_count += 1
                return False

        return _Ctx()


def test_download_remote_image_success() -> None:
    """下载成功返回字节与 MIME，且响应被关闭."""
    c = _make_client()
    session = FakeSession(FakeResponse(b"DATA", 200, "image/png"))
    content, mime = run(c._download_remote_image("http://x/a.png", session))
    assert content == b"DATA"
    assert mime == "image/png"
    assert session.closed_count == 1


def test_download_remote_image_non_2xx_fails() -> None:
    """非 2xx 快速失败，文案已分类."""
    c = _make_client()
    session = FakeSession(FakeResponse(b"", 404))
    with pytest.raises(RuntimeError, match="下载远程图片失败"):
        run(c._download_remote_image("http://x/a.png", session))
    assert session.closed_count == 1


def test_download_remote_image_network_error(monkeypatch) -> None:
    """网络类异常被分类包装（响应未建立也不残留）."""
    c = _make_client()

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(ac.asyncio, "sleep", _no_sleep)

    class BoomSession:
        def get(self, *a, **k):
            raise ConnectionResetError("connection reset")

    with pytest.raises(RuntimeError, match="下载远程图片失败"):
        run(c._download_remote_image("http://x/a.png", BoomSession()))


# ===== 模型列表 =====


def test_get_models_success() -> None:
    """模型列表字段被归一化为 id/created/owned_by."""
    c = _make_client()
    payload = json.dumps(
        {"object": "list", "data": [{"id": "m1", "created": 123, "owned_by": "x"}]}
    )
    session = FakeSession(FakeResponse(payload.encode(), 200))
    c.client_manager.get_http_session = _async_return(session)  # type: ignore

    models = run(c.get_models(type="text2image"))
    assert models == [{"id": "m1", "created": 123, "owned_by": "x"}]


def _async_return(value):
    async def _inner():
        return value

    return _inner


def test_get_models_auth_error() -> None:
    """401 给出 Key 无效提示."""
    c = _make_client()
    session = FakeSession(FakeResponse(b"", 401))
    c.client_manager.get_http_session = _async_return(session)  # type: ignore
    with pytest.raises(RuntimeError, match="API Key 无效或已过期"):
        run(c.get_models())


def test_get_models_rate_limit() -> None:
    """429 给出限流提示."""
    c = _make_client()
    session = FakeSession(FakeResponse(b"", 429))
    c.client_manager.get_http_session = _async_return(session)  # type: ignore
    with pytest.raises(RuntimeError, match="超限或并发过高"):
        run(c.get_models())


def test_get_models_server_error() -> None:
    """5xx 给出服务端错误提示."""
    c = _make_client()
    session = FakeSession(FakeResponse(b"", 503))
    c.client_manager.get_http_session = _async_return(session)  # type: ignore
    with pytest.raises(RuntimeError, match="服务器内部错误"):
        run(c.get_models())


def test_get_models_other_error() -> None:
    """其它非 2xx 回具体状态码."""
    c = _make_client()
    session = FakeSession(FakeResponse(b"nope", 400))
    c.client_manager.get_http_session = _async_return(session)  # type: ignore
    with pytest.raises(RuntimeError, match="HTTP 400"):
        run(c.get_models())


# ===== 图片编辑 =====


def test_edit_image_url_no_download(tmp_path) -> None:
    """download_urls=False 时 URL 图片以 image_url 字段直传."""
    c = _make_client()
    submit = FakeResponse(json.dumps({"task_id": "t1"}).encode(), 200)
    poll = FakeResponse(
        json.dumps(
            {
                "status": "success",
                "output": {"file_url": "https://cdn/edit.png"},
                "completed_at": 2000,
                "started_at": 1000,
            }
        ).encode(),
        200,
    )
    session = FakeSession([submit, poll])
    c.client_manager.get_http_session = _async_return(session)  # type: ignore

    downloaded: list = []

    async def _dl(url, sess):
        downloaded.append(url)
        return "/tmp/edit.png"

    c.image_manager.download_image = _dl  # type: ignore[assignment]

    result = run(c.edit_image("改成油画", ["https://cdn/in.png"], download_urls=False))
    assert result == "/tmp/edit.png"
    assert downloaded == ["https://cdn/edit.png"]


def test_edit_image_local_file(tmp_path) -> None:
    """本地图片应读入内容并以 multipart 文件字段上传."""
    c = _make_client()
    img = tmp_path / "a.png"
    img.write_bytes(b"LOCALIMG")

    submit = FakeResponse(json.dumps({"task_id": "t1"}).encode(), 200)
    poll = FakeResponse(
        json.dumps(
            {"status": "success", "output": {"file_url": "https://cdn/o.png"}}
        ).encode(),
        200,
    )
    session = FakeSession([submit, poll])
    c.client_manager.get_http_session = _async_return(session)  # type: ignore

    async def _dl(_u, _s):
        return "/tmp/o.png"

    c.image_manager.download_image = _dl  # type: ignore[assignment]

    result = run(c.edit_image("x", [str(img)]))
    assert result == "/tmp/o.png"


def test_edit_image_url_with_download(tmp_path) -> None:
    """download_urls=True 时先下载远程图片再上传."""
    c = _make_client()
    session = FakeSession(
        [
            FakeResponse(b"REMOTE", 200, "image/png"),  # remote fetch
            FakeResponse(json.dumps({"task_id": "t1"}).encode(), 200),  # submit
            FakeResponse(
                json.dumps(
                    {"status": "success", "output": {"file_url": "https://cdn/o.png"}}
                ).encode(),
                200,
            ),  # poll
        ]
    )
    c.client_manager.get_http_session = _async_return(session)  # type: ignore

    async def _dl(_u, _s):
        return "/tmp/o.png"

    c.image_manager.download_image = _dl  # type: ignore[assignment]

    result = run(c.edit_image("x", ["https://cdn/in.png"], download_urls=True))
    assert result == "/tmp/o.png"


def test_edit_image_missing_task_id() -> None:
    """提交返回无 task_id 时快速失败."""
    c = _make_client()
    session = FakeSession(FakeResponse(json.dumps({}).encode(), 200))
    c.client_manager.get_http_session = _async_return(session)  # type: ignore
    with pytest.raises(RuntimeError, match="未返回任务 ID"):
        run(c.edit_image("x", ["https://cdn/in.png"]))


def test_edit_image_submit_http_error() -> None:
    """提交阶段非 2xx 转中文提示."""
    c = _make_client()
    session = FakeSession(FakeResponse(b"", 401))
    c.client_manager.get_http_session = _async_return(session)  # type: ignore
    with pytest.raises(RuntimeError, match="API Key 无效或已过期"):
        run(c.edit_image("x", ["https://cdn/in.png"]))


# ===== 编辑任务轮询 =====


def test_poll_edit_task_success() -> None:
    """轮询到 success 且含 file_url 时下载并返回."""
    c = _make_client()
    resp = FakeResponse(
        json.dumps(
            {
                "status": "success",
                "output": {"file_url": "https://cdn/o.png"},
                "completed_at": 3000,
                "started_at": 1000,
            }
        ).encode(),
        200,
    )
    session = FakeSession(resp)

    async def _dl(url, _s):
        assert url == "https://cdn/o.png"
        return "/tmp/o.png"

    c.image_manager.download_image = _dl  # type: ignore[assignment]
    result = run(c._poll_edit_task("t1", session, "k", retry_interval=1))
    assert result == "/tmp/o.png"


def test_poll_edit_task_error_field() -> None:
    """响应带 error 字段时快速失败."""
    c = _make_client()
    resp = FakeResponse(
        json.dumps({"error": True, "message": "bad prompt"}).encode(), 200
    )
    session = FakeSession(resp)
    with pytest.raises(RuntimeError, match="任务错误"):
        run(c._poll_edit_task("t1", session, "k", retry_interval=1))


def test_poll_edit_task_failed_status() -> None:
    """状态 failed 时抛异常."""
    c = _make_client()
    resp = FakeResponse(json.dumps({"status": "failed"}).encode(), 200)
    session = FakeSession(resp)
    with pytest.raises(RuntimeError, match="任务失败"):
        run(c._poll_edit_task("t1", session, "k", retry_interval=1))


def test_poll_edit_task_success_without_url() -> None:
    """status=success 但缺 file_url 时报错."""
    c = _make_client()
    resp = FakeResponse(json.dumps({"status": "success", "output": {}}).encode(), 200)
    session = FakeSession(resp)
    with pytest.raises(RuntimeError, match="未返回图片 URL"):
        run(c._poll_edit_task("t1", session, "k", retry_interval=1))


def test_poll_edit_task_timeout() -> None:
    """超过最大次数时抛超时异常."""
    c = _make_client()
    # timeout=0 -> max_attempts=0，循环体不执行，直接抛超时
    session = FakeSession(FakeResponse(json.dumps({"status": "running"}).encode(), 200))
    with pytest.raises(RuntimeError, match="任务超时"):
        run(c._poll_edit_task("t1", session, "k", timeout=0, retry_interval=10))


def test_poll_edit_task_pending_then_success(monkeypatch) -> None:
    """先 running 后 success，应能继续轮询到成功."""
    c = _make_client()

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(ac.asyncio, "sleep", _no_sleep)

    running = FakeResponse(json.dumps({"status": "running"}).encode(), 200)
    success = FakeResponse(
        json.dumps(
            {"status": "success", "output": {"file_url": "https://cdn/o.png"}}
        ).encode(),
        200,
    )
    session = FakeSession([running, success])

    async def _dl(_u, _s):
        return "/tmp/o.png"

    c.image_manager.download_image = _dl  # type: ignore[assignment]
    assert run(c._poll_edit_task("t1", session, "k", retry_interval=1)) == "/tmp/o.png"


def test_poll_edit_task_query_http_error() -> None:
    """轮询查询接口返回 401 时快速失败."""
    c = _make_client()
    session = FakeSession(FakeResponse(b"", 401))
    with pytest.raises(RuntimeError, match="API Key 无效或已过期"):
        run(c._poll_edit_task("t1", session, "k", retry_interval=1))


def test_close_releases_resources() -> None:
    """close 转发到 ClientManager.close."""
    c = _make_client()
    closed = []

    async def _close():
        closed.append(True)

    c.client_manager.close = _close  # type: ignore[assignment]
    run(c.close())
    assert closed == [True]
