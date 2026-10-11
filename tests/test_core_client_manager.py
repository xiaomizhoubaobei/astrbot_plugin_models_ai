"""客户端管理器单元测试.

覆盖 ``core/client_manager.py`` 的复用与释放契约：
- 同一 API Key 的 OpenAI 客户端应被缓存复用，不同 Key 各自独立；
- 所有 OpenAI 客户端共享同一个 httpx.AsyncClient（省连接）；
- aiohttp Session 复用、关闭后再取应重建；
- ``close`` 后资源被置空。
"""

import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.core import client_manager as cm  # noqa: E402
from astrbot_plugin_models_ai.core.client_manager import ClientManager  # noqa: E402


def test_get_openai_client_caches_per_key() -> None:
    """同一 Key 复用、不同 Key 独立."""
    m = ClientManager("https://example.invalid/v1")
    c1 = m.get_openai_client("key-1")
    c2 = m.get_openai_client("key-1")
    c3 = m.get_openai_client("key-2")
    assert c1 is c2
    assert c1 is not c3
    run(m.close())


def test_get_openai_client_shares_httpx() -> None:
    """多个 OpenAI 客户端共享同一个 httpx.AsyncClient."""
    m = ClientManager("https://example.invalid/v1")
    m.get_openai_client("k1")
    shared = m._httpx_client
    m.get_openai_client("k2")
    assert m._httpx_client is shared
    assert shared is not None
    run(m.close())


def test_get_openai_client_empty_key_raises() -> None:
    """空 Key 直接报错，不创建无效客户端."""
    m = ClientManager("https://example.invalid/v1")
    with pytest.raises(ValueError, match="API Key 不能为空"):
        m.get_openai_client("")


def test_http_session_created_and_reused() -> None:
    """首次取建 Session，之后复用同一个."""
    m = ClientManager("https://example.invalid/v1")

    async def _drive():
        s1 = await m.get_http_session()
        s2 = await m.get_http_session()
        assert s1 is s2
        await m.close()

    run(_drive())


def test_http_session_recreated_after_close() -> None:
    """Session 被关闭后再取应重建（而不是返回已关闭对象）."""
    m = ClientManager("https://example.invalid/v1")

    async def _drive():
        s1 = await m.get_http_session()
        await s1.close()
        s2 = await m.get_http_session()
        assert s2 is not s1
        assert not s2.closed
        await m.close()

    run(_drive())


def test_close_clears_resources() -> None:
    """close 应关闭并置空 Session 与 httpx 客户端，并清空 OpenAI 缓存."""
    m = ClientManager("https://example.invalid/v1")

    async def _drive():
        await m.get_http_session()
        m.get_openai_client("k1")
        await m.close()
        assert m._http_session is None
        assert m._httpx_client is None
        assert m._openai_clients == {}

    run(_drive())


def test_close_is_idempotent() -> None:
    """重复 close 不应报错."""
    m = ClientManager("https://example.invalid/v1")
    run(m.close())
    run(m.close())


def test_debug_log_branch() -> None:
    """debug 模式日志分支可执行."""
    m = ClientManager("https://example.invalid/v1", debug_mode=True)
    m.debug_log("hello")


# ===== 安全回归：调试日志不得回显 API Key 内容 =====


class _CaptureLogger:
    """捕获日志文本，供断言密钥未泄露."""

    def __init__(self) -> None:
        """初始化空日志缓冲."""
        self.messages: list[str] = []

    def __getattr__(self, _k):
        """把任意日志级别方法收敛为「记录参数文本」."""

        def _record(*args, **_kw):
            self.messages.extend(str(a) for a in args)

        return _record

    def text(self) -> str:
        """返回拼接后的全量日志文本."""
        return "\n".join(self.messages)


def test_debug_log_never_echoes_api_key(monkeypatch) -> None:
    """创建 / 复用客户端日志不得回显 API Key 内容."""
    secret = "sk-supersecret-abcdef0123456789"
    m = ClientManager("https://example.invalid/v1", debug_mode=True)
    cap = _CaptureLogger()
    monkeypatch.setattr(cm, "logger", cap)
    m.get_openai_client(secret)  # 创建分支
    m.get_openai_client(secret)  # 复用分支
    assert secret not in cap.text()
    assert secret[:10] not in cap.text()
    run(m.close())
