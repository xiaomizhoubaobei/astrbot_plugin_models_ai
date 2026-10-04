"""网络错误分类、脱敏与重试策略单元测试.

覆盖 ``core/net_errors.py`` 的三块核心能力：
- **脱敏**：API Key / Bearer / URL query 一律不得出现在回包文本中；
- **分类**：DNS / TLS / 连接超时 / 读取超时 / 连接重置 / 代理 / 通用，
  以及 HTTP 状态码到中文提示的映射；
- **重试判定**：``is_retryable``（可重试）与 ``is_safe_to_replay``（重放安全，
  仅建连阶段故障）的边界，以及 ``with_retry`` 的退避与终止行为。
"""

import asyncio

import httpx
import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.core import net_errors as ne  # noqa: E402

# ===== 脱敏 =====


def test_mask_text_bearer() -> None:
    """Bearer token 应被抹除."""
    out = ne.mask_text("Authorization: Bearer sk-abcdef1234567890")
    assert "sk-abcdef1234567890" not in out
    assert ne.MASK in out


def test_mask_text_apikey_forms() -> None:
    """api_key 的多种写法都要抹除（含 JSON 片段）."""
    for raw in [
        "api_key=sk-abcdef1234567890",
        '{"api_key":"sk-abcdef1234567890"}',
        "apikey: sk-abcdef1234567890",
    ]:
        out = ne.mask_text(raw)
        assert "sk-abcdef1234567890" not in out, raw


def test_mask_text_url_query() -> None:
    """URL query 整体抹除，但保留 path 便于定位端点."""
    out = ne.mask_text("GET https://api.example.com/v1/images?token=secret123&x=1")
    assert "secret123" not in out
    assert "/v1/images" in out


def test_mask_text_high_entropy_token() -> None:
    """高熵长串（疑似裸 Key）兜底抹除."""
    token = "AbCdEf0123456789AbCdEf0123456789"
    out = ne.mask_text(f"failed with {token}")
    assert token not in out


def test_mask_text_empty_and_types() -> None:
    """空值与任意类型输入都不抛异常（非字符串先 str 化再脱敏）."""
    assert ne.mask_text("") == ""
    assert ne.mask_text(123) == "123"
    # None 经 str() 后为 "None"，不构成敏感信息，原样保留
    assert ne.mask_text(None) == "None"


def test_mask_text_truncates() -> None:
    """超长文本按 limit 截断."""
    out = ne.mask_text("a" * 1000, limit=50)
    assert len(out) <= 50


# ===== 分类 =====


def test_classify_dns_error() -> None:
    """DNS 解析失败给出对应提示."""
    import socket

    msg = ne.classify_network_error(socket.gaierror("name or service not known"))
    assert "DNS" in msg


def test_classify_tls_error() -> None:
    """证书校验失败给出 TLS 提示（且强调重试无意义）."""
    import ssl

    exc = ssl.SSLCertVerificationError("certificate verify failed")
    msg = ne.classify_network_error(exc)
    assert "TLS" in msg or "证书" in msg


def test_classify_read_timeout() -> None:
    """httpx 读取超时归为「等待上游响应超时」."""
    msg = ne.classify_network_error(httpx.ReadTimeout("read timeout"))
    assert "响应超时" in msg or "超时" in msg


def test_classify_connect_timeout() -> None:
    """建连超时归为「连接上游超时」."""
    msg = ne.classify_network_error(httpx.ConnectTimeout("connect timeout"))
    assert "连接上游超时" in msg or "超时" in msg


def test_classify_connection_reset() -> None:
    """连接重置提示可重试."""
    msg = ne.classify_network_error(ConnectionResetError("connection reset"))
    assert "中断" in msg or "重置" in msg


def test_classify_connect_error() -> None:
    """无法建连（拒绝/不可达）给出检查网络提示."""
    msg = ne.classify_network_error(httpx.ConnectError("connection refused"))
    assert "连接" in msg


def test_classify_proxy_error() -> None:
    """代理异常给出代理提示."""
    msg = ne.classify_network_error(httpx.ProxyError("tunnel connection failed"))
    assert "代理" in msg


def test_classify_generic_timeout() -> None:
    """无法细分的超时归为通用超时."""
    msg = ne.classify_network_error(asyncio.TimeoutError("timed out"))
    assert "超时" in msg


def test_classify_generic_error() -> None:
    """未命中任何类别的异常回溯到通用网络异常."""
    msg = ne.classify_network_error(ValueError("nonsense"))
    assert "网络" in msg


def test_classify_non_exception_defensive() -> None:
    """传入非异常时走防御分支，不抛错."""
    msg = ne.classify_network_error("not-exception")  # type: ignore[arg-type]
    assert "网络" in msg


# ===== HTTP 状态 =====


@pytest.mark.parametrize(
    "status,keyword",
    [
        (401, "API Key"),
        (403, "API Key"),
        (404, "不存在"),
        (429, "限流"),
        (500, "服务器内部错误"),
        (503, "服务器内部错误"),
        (418, "异常状态"),
    ],
)
def test_describe_http_status(status, keyword) -> None:
    """状态码应映射到可操作的中文提示."""
    assert keyword in ne.describe_http_status(status)


def test_describe_http_status_masks_body() -> None:
    """响应体片段脱敏后才拼接进提示."""
    out = ne.describe_http_status(400, "token=sk-abcdef1234567890")
    assert "sk-abcdef1234567890" not in out


def test_http_error_extracts_status() -> None:
    """从 httpx.HTTPStatusError 中提取状态并给出中文提示."""
    request = httpx.Request("GET", "https://x/y")
    response = httpx.Response(429, request=request, text="too many")
    exc = httpx.HTTPStatusError("429", request=request, response=response)
    msg = ne.http_error(exc)
    assert msg and "限流" in msg


def test_http_error_returns_none_for_other() -> None:
    """非 HTTPStatusError 返回 None."""
    assert ne.http_error(ValueError("x")) is None


def test_to_user_message_prefers_status() -> None:
    """to_user_message 优先 HTTP 状态，其次网络分类."""
    request = httpx.Request("GET", "https://x/y")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("503", request=request, response=response)

    class Wrapper(Exception):
        pass

    wrapped = Wrapper("failed")
    wrapped.__cause__ = exc
    assert "服务器内部错误" in ne.to_user_message(wrapped)


def test_to_user_message_network_fallback() -> None:
    """无状态时回落网络分类，给出可操作的中文提示."""
    assert "中断" in ne.to_user_message(ConnectionResetError("connection reset"))


# ===== 重试判定 =====


def test_is_retryable_transient() -> None:
    """连接类瞬时故障可重试."""
    assert ne.is_retryable(ConnectionResetError("connection reset")) is True
    assert ne.is_retryable(httpx.ConnectTimeout("connect timeout")) is True


def test_is_retryable_cert_not_retryable() -> None:
    """证书确定性失败不重试."""
    import ssl

    exc = ssl.SSLCertVerificationError("certificate verify failed")
    assert ne.is_retryable(exc) is False


def test_is_retryable_business_error() -> None:
    """普通业务异常默认不重试."""
    assert ne.is_retryable(ValueError("bad prompt")) is False


def test_is_retryable_non_exception() -> None:
    """非异常输入返回 False."""
    assert ne.is_retryable("x") is False  # type: ignore[arg-type]


def test_is_safe_to_replay_connect_phase() -> None:
    """建连阶段故障（未送达）可安全重放."""
    import socket

    assert ne.is_safe_to_replay(socket.gaierror("getaddrinfo failed")) is True
    assert ne.is_safe_to_replay(httpx.ConnectError("connection refused")) is True


def test_is_safe_to_replay_reset_not_safe() -> None:
    """连接重置可能已送达，不重放."""
    assert ne.is_safe_to_replay(ConnectionResetError("connection reset")) is False


def test_is_safe_to_replay_cert_not_safe() -> None:
    """证书失败不重放."""
    import ssl

    exc = ssl.SSLCertVerificationError("certificate verify failed")
    assert ne.is_safe_to_replay(exc) is False


def test_new_idempotency_key_format_and_uniqueness() -> None:
    """幂等键带前缀且高熵唯一."""
    k1 = ne.new_idempotency_key("cnb-test")
    k2 = ne.new_idempotency_key("cnb-test")
    assert k1.startswith("cnb-test-")
    assert k1 != k2
    assert len(k1) > len("cnb-test-") + 16


# ===== with_retry =====


def test_with_retry_success_first_try() -> None:
    """首次成功不重试."""
    calls = {"n": 0}

    async def _op():
        calls["n"] += 1
        return "ok"

    assert run(ne.with_retry(_op, max_retries=3)) == "ok"
    assert calls["n"] == 1


def test_with_retry_eventually_succeeds(monkeypatch) -> None:
    """瞬时故障重试后成功，并触发回调."""

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(ne.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}
    retries: list[int] = []

    async def _op():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionResetError("connection reset")
        return "done"

    result = run(
        ne.with_retry(
            _op,
            max_retries=3,
            on_retry=lambda attempt, delay, exc: retries.append(attempt),
        )
    )
    assert result == "done"
    assert calls["n"] == 3
    assert retries == [1, 2]


def test_with_retry_exhausts_and_raises(monkeypatch) -> None:
    """重试耗尽后抛出最后一次异常."""

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(ne.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    async def _op():
        calls["n"] += 1
        raise ConnectionResetError("connection reset")

    with pytest.raises(ConnectionResetError):
        run(ne.with_retry(_op, max_retries=2))
    assert calls["n"] == 3  # 首次 + 2 次重试


def test_with_retry_non_retryable_immediate(monkeypatch) -> None:
    """不可重试异常立即抛出，不做退避等待."""

    async def _fail_sleep(_s):  # pragma: no cover - 不应被调用
        raise AssertionError("不应重试")

    monkeypatch.setattr(ne.asyncio, "sleep", _fail_sleep)

    async def _op():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        run(ne.with_retry(_op, max_retries=3))


def test_with_retry_custom_should_retry(monkeypatch) -> None:
    """自定义 should_retry 生效（只重放未送达故障）."""

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(ne.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    async def _op():
        calls["n"] += 1
        raise ConnectionResetError("connection reset")

    with pytest.raises(ConnectionResetError):
        run(ne.with_retry(_op, max_retries=3, should_retry=ne.is_safe_to_replay))
    # ConnectionReset 不属"未送达"，一次即止
    assert calls["n"] == 1


def test_build_timeout_fields() -> None:
    """超时对象应区分 connect 与 sock_read 两段."""
    t = ne.build_timeout()
    assert t.connect == ne.CONNECT_TIMEOUT
    assert t.sock_read == ne.READ_TIMEOUT
    assert t.total == ne.READ_TIMEOUT
