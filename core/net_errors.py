"""网络错误分类、脱敏与重试策略模块.

上游服务商（Gitee AI / 千问云）的调用链路会经过 DNS 解析、TCP 建连、
TLS 握手、读写等多个阶段，任何一段出问题，用户此前看到的都只是
``API调用失败: <原始异常>`` 这一句无法区分因由的提示，排障只能靠猜。

本模块把这三件事收口到一处，供所有服务商客户端复用：

1. **分类**：把底层异常按「DNS 解析 / 连接超时 / 读取超时 / TLS 失败 /
   连接重置 / 代理异常 / 通用网络异常」分开，各自映射为可操作的中文提示。
2. **脱敏**：错误文本回给用户之前，抹掉 API Key、Bearer token、
   URL query 与常见签名参数，避免把凭证泄露到聊天窗口与日志。
3. **重试判定**：区分「值得重试的瞬时故障」（连接类异常）与
   「重试也没用的确定性失败」（证书校验、HTTP 状态错误），
   让调用方按 1s / 2s / 4s 指数退避重试。

设计约束：本模块只依赖标准库与 ``httpx`` / ``aiohttp``（可选），
不反向依赖任何服务商客户端，避免循环导入。
"""

import asyncio
import re
import secrets
import socket
import ssl
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import aiohttp
import httpx

# aiohttp 的异常类型在个别环境的 c 扩展里可能缺符号，缺失时以空元组回落，
# 使 isinstance 判断退化为「恒 False」而非导入期崩溃。
# 注意：这里必须显式包成元组——aiohttp 暴露的是异常「类」而非元组，
# 直接赋给元组注解会让后续 `+` 拼接在运行期抛 TypeError。
_AiohttpCertError: tuple[type[BaseException], ...] = (
    aiohttp.ClientConnectorCertificateError,
)
_AiohttpDisconnected: tuple[type[BaseException], ...] = (
    aiohttp.ServerDisconnectedError,
)
_AiohttpConnectorError: tuple[type[BaseException], ...] = (
    aiohttp.ClientConnectorError,
)

T = TypeVar("T")

# ===== 重试策略常量 =====
# 退避基数：1s / 2s / 4s（第 1 次重试前等 1s，第 2 次等 2s，第 3 次等 4s）
RETRY_BACKOFF_BASE = 1.0
# 退避上限，防止后续调整重试次数时退避时间失控
RETRY_BACKOFF_MAX = 8.0
# 默认最大重试次数（不含首次请求）
DEFAULT_MAX_RETRIES = 3
# httpx 传输层自带重试次数：仅对连接类错误（建连/握手）生效，故取 2 次，
# 与上层退避重试形成互补而非叠加，避免同一请求被放大成 3×3 次。
HTTPX_TRANSPORT_RETRIES = 2

# ===== 超时策略常量 =====
# 连接超时：DNS 解析 + TCP 建连 + TLS 握手的总预算
CONNECT_TIMEOUT = 10.0
# 读取超时：单次响应体的等待上限（生图轮询场景下不应长于一次轮询间隔量级）
READ_TIMEOUT = 65.0

# ===== 脱敏规则 =====
# 说明：宁可多抹一点，也不能把 Key / 签名放进聊天窗口。
MASK = "***"

# 「Bearer xxx」「api_key=xxx」等形式的凭证
_CREDENTIAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization: Bearer sk-xxxx
    (re.compile(r"(?i)(bearer\s+)[\w\-\.=+/]{8,}"), rf"\1{MASK}"),
    # JSON / 查询串 / 表单里的凭证：api_key=xxx、api_key":"xxx"、"api_key": "xxx"
    # 注意引号可选，否则 {"api_key":"sk-xxx"} 这类 JSON 片段会漏网。
    (
        re.compile(
            r"(?i)([\"']?\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
            r"api[_-]?secret|token|secret|signature|sig|password|passwd)\b[\"']?)"
            r"(\s*[=:]\s*[\"']?)([\w\-\.=+/]{6,})"
        ),
        rf"\1\2{MASK}",
    ),
    # URL query 整体抹除（保留 path，便于定位是哪个端点出的问题）
    (re.compile(r"\?[^\s'\"<>)]*"), "?" + MASK),
    # 高熵长串兜底：疑似 Key 的裸串（长度 32+ 且含大小写与数字）
    (re.compile(r"\b(?=[A-Za-z0-9]{32,})(?=[^A-Za-z0-9]*[A-Za-z])[\w\-]{32,}\b"), MASK),
)


def _safe_text(text: str, limit: int = 240) -> str | None:
    """对错误文本做脱敏并截断.

    Args:
        text: 原始错误文本（可能含 URL、凭证、堆栈摘要）
        limit: 保留的最大字符数，超出部分截断并补省略号

    Returns:
        脱敏后的文本；输入为空或全为空白时返回 ``None``
    """
    if not text:
        return None

    safe = text
    for pattern, repl in _CREDENTIAL_PATTERNS:
        safe = pattern.sub(repl, safe)

    safe = safe.strip()
    if not safe:
        return None
    if len(safe) > limit:
        return safe[:limit] + "..."
    return safe


def _unwrap(exc: BaseException) -> BaseException:
    """剥掉外层包装，取出真正表达故障原因的内层异常.

    各家 SDK 常把底层异常塞进 ``__cause__`` / ``__context__``，
    只看最外层类型会把「TLS 失败」误判成「通用异常」。

    Args:
        exc: 待处理的异常

    Returns:
        内层的根因异常；若不存在嵌套则返回原异常
    """
    seen: set[int] = set()
    current: BaseException = exc
    while id(current) not in seen:
        seen.add(id(current))
        candidate = current.__cause__ or current.__context__
        if not isinstance(candidate, BaseException):
            break
        # 只在存在更具体的内层异常时下钻，避免在同层死循环
        if candidate is current:
            break
        current = candidate
    return current


def _search_chain(exc: BaseException, types: tuple[type[BaseException], ...]) -> bool:
    """在整条异常链（含包装层）中查找是否存在指定类型.

    Args:
        exc: 最外层异常
        types: 目标异常类型元组

    Returns:
        链上任一层命中即返回 ``True``
    """
    if not types:
        return False
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, types):
            return True
        nxt = current.__cause__ or current.__context__
        current = nxt if isinstance(nxt, BaseException) and nxt is not current else None
    return False


def classify_network_error(exc: BaseException) -> str:
    """把网络异常分类为面向用户的中文提示（已脱敏）.

    分类优先级从「最具体」到「最泛化」：TLS → DNS → 连接超时 →
    读取超时 → 连接重置 → 代理 → 通用超时 → 通用网络异常。

    Args:
        exc: 捕获到的异常，可以是任意服务商 SDK 抛出的包装异常

    Returns:
        可直接回包给用户的中文提示，形如
        ``DNS 解析失败：无法解析服务商域名，请检查 DNS 配置或域名拼写（原因：xxx）``
    """
    if not isinstance(exc, BaseException):  # pragma: no cover - 防御式编程
        return "网络请求异常，请稍后重试。"

    root = _unwrap(exc)

    # 1) TLS / 证书：重试无意义，必须单独报出来，否则用户会一直重试
    # 注意：httpx 会把证书校验失败包进 ConnectError，故这里同时看类型与文本
    if (
        _search_chain(exc, (ssl.SSLCertVerificationError, ssl.SSLError))
        or _search_chain(exc, _AiohttpCertError)
        or _has_text(exc, ("certificate verify failed", "sslcertverificationerror"))
    ):
        detail = _safe_text(str(root))
        reason = f"（原因：{detail}）" if detail else ""
        return (
            "TLS/证书校验失败：无法与上游建立安全连接，"
            "请检查系统时间、根证书或代理是否做了证书替换" + reason
        )

    # 2) DNS 解析失败
    if _search_chain(exc, (socket.gaierror,)) or _has_text(
        exc,
        (
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "getaddrinfo",
        ),
    ):
        detail = _safe_text(str(root))
        reason = f"（原因：{detail}）" if detail else ""
        return (
            "DNS 解析失败：无法解析上游域名，请检查 DNS 配置、网络或域名是否可访问"
            + reason
        )

    # 3) 连接超时（建连 / 握手阶段）
    if isinstance(root, (httpx.ConnectTimeout, asyncio.TimeoutError)) and _has_text(
        exc, ("connect",)
    ):
        return "连接上游超时：TCP 建连或 TLS 握手未在限定时间内完成，请检查网络连通性或代理"
    if isinstance(root, aiohttp.ServerTimeoutError) and _has_text(exc, ("connect",)):
        return "连接上游超时：TCP 建连或 TLS 握手未在限定时间内完成，请检查网络连通性或代理"
    if _has_text(
        exc, ("connect timeout", "connection timed out", "timed out connecting")
    ):
        return "连接上游超时：TCP 建连或 TLS 握手未在限定时间内完成，请检查网络连通性或代理"

    # 4) 读取超时（已建连，等响应体超时）
    if _search_chain(exc, (httpx.ReadTimeout,)) or _has_text(
        exc, ("read timeout", "readtimeout")
    ):
        return "等待上游响应超时：服务商处理时间过长，请稍后重试或降低分辨率"
    if _search_chain(exc, (aiohttp.ServerTimeoutError,)) and _has_text(
        exc, ("sock_read", "read")
    ):
        return "等待上游响应超时：服务商处理时间过长，请稍后重试或降低分辨率"

    # 5) 连接被重置 / 中断（长任务轮询时最常见）
    if _search_chain(
        exc, (ConnectionResetError, ConnectionAbortedError) + _AiohttpDisconnected
    ) or _has_text(
        exc,
        (
            "connection reset",
            "connection aborted",
            "server disconnected",
            "remoteprotocolerror",
            "connection broken",
        ),
    ):
        return "连接被上游中断：可重试，若持续出现请检查代理或降低请求频率"

    # 6) 无法建连（端口不通 / 拒绝 / 网络不可达）
    if _search_chain(
        exc, (httpx.ConnectError, aiohttp.ClientConnectorError)
    ) or _has_text(
        exc,
        ("connection refused", "network is unreachable", "no route to host"),
    ):
        return "无法连接上游服务：域名可能不通或对端拒绝连接，请检查网络、代理与端口"

    # 7) 代理异常
    if _search_chain(exc, (httpx.ProxyError,)) or _has_text(
        exc, ("proxy", "tunnel connection failed")
    ):
        return "代理连接失败：请检查代理配置、认证信息与网络出口"

    # 8) 通用超时（无法细分阶段）
    if isinstance(
        root, (httpx.TimeoutException, asyncio.TimeoutError, aiohttp.ServerTimeoutError)
    ) or _has_text(exc, ("timeout", "timed out")):
        return "请求上游超时：网络或服务商响应较慢，请稍后重试"

    # 9) 其余归为通用网络异常，保留脱敏后的原因用于排障
    detail = _safe_text(str(root))
    reason = f"（原因：{detail}）" if detail else ""
    return "网络请求异常：与上游通信失败，请检查网络后重试" + reason


def _has_text(exc: BaseException, keywords: tuple[str, ...]) -> bool:
    """判断异常链上任一层的文本是否包含指定关键字.

    用于兜底那些被第三方 SDK 二次包装、类型信息已丢失的异常。

    Args:
        exc: 最外层异常
        keywords: 待匹配的关键字（小写）

    Returns:
        命中任一关键字即返回 ``True``
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = f"{type(current).__name__}: {current}".lower()
        if any(k in text for k in keywords):
            return True
        nxt = current.__cause__ or current.__context__
        current = nxt if isinstance(nxt, BaseException) and nxt is not current else None
    return False


# 确定性失败：重试不会有任何收益，直接快速失败
NON_RETRYABLE: tuple[type[BaseException], ...] = (
    ssl.SSLCertVerificationError,
    httpx.InvalidURL,
    httpx.UnsupportedProtocol,
)

# 瞬时故障：值得按指数退避重试
RETRYABLE: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    httpx.ProxyError,
    ConnectionResetError,
    ConnectionAbortedError,
    # 目标端口关闭时 stdlib 抛 ConnectionRefusedError；aiohttp 会把它包进
    # ClientConnectorError，而该异常不在 httpx 类型体系内，故此处显式列出，
    # 避免只依赖 "connection refused" 文本匹配（随 aiohttp / c-ares 版本漂移）。
    ConnectionRefusedError,
    asyncio.TimeoutError,
    socket.gaierror,
)


def is_retryable(exc: BaseException) -> bool:
    """判断异常是否值得重试.

    规则：证书校验失败等确定性错误一律不重试；连接类瞬时空故障重试；
    其余（含 HTTP 状态类错误）交由调用方决定，默认不重试，
    避免把「提示词超限」这类业务失败重放三遍。

    Args:
        exc: 捕获到的异常

    Returns:
        值得重试返回 ``True``
    """
    if not isinstance(exc, BaseException):  # pragma: no cover
        return False

    if _search_chain(exc, NON_RETRYABLE):
        return False

    if _search_chain(exc, RETRYABLE):
        return True

    if _search_chain(exc, _AiohttpCertError):
        return False

    # 兜底：文本命中连接类关键字时也允许重试
    return _has_text(
        exc,
        (
            "connection reset",
            "server disconnected",
            "connection aborted",
            "temporarily unavailable",
            "connection refused",
        ),
    )


def is_safe_to_replay(exc: BaseException) -> bool:
    """判断异常是否发生在「请求尚未送达上游之前」——即重放是否安全.

    对**非幂等**的「创建任务」类 POST（如 Gitee 图片编辑、千问云任务提交），
    盲目重试会造成上游作业数量倍增：若请求已到达服务端、任务已创建，只是
    响应在回程丢失，重试就会生成**孤立的重复任务**。

    因此这里把可重试范围收窄到「**确定没有送达**」的连接建立阶段故障：

    - DNS 解析失败、TCP 建连超时/被拒、TLS 握手失败：请求根本没发出去，重放安全；
    - 连接重置 / 读取超时 / 服务端断开：请求**可能已送达**，结果不确定，**不重试**；
    - 其余（含 HTTP 状态类错误）：交由调用方判定，这里默认不重试。

    Args:
        exc: 捕获到的异常

    Returns:
        可安全重放返回 ``True``
    """
    if not isinstance(exc, BaseException):  # pragma: no cover
        return False

    # 证书类确定性失败：重试无意义，且不属「未送达」
    if _search_chain(exc, NON_RETRYABLE) or _search_chain(exc, _AiohttpCertError):
        return False

    # 建连阶段失败：请求未送达，可安全重放
    if _search_chain(
        exc,
        (
            socket.gaierror,
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ProxyError,
        ),
    ):
        return True

    if _has_text(
        exc,
        (
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "getaddrinfo",
            "connection refused",
            "network is unreachable",
            "no route to host",
            "connect timeout",
            "connection timed out",
            "timed out connecting",
            "certificate verify failed",
        ),
    ):
        # 「connection refused / 不可达」属连接建立失败，未送达；证书失败则排除
        return not _has_text(exc, ("certificate verify failed",))

    return False


def new_idempotency_key(prefix: str = "cnb") -> str:
    """生成一次性幂等键，供「创建任务」类非幂等请求去重.

    同一次逻辑提交（含其全部重试）应复用**同一个**键，这样即便上游支持
    ``Idempotency-Key`` 头，重复提交也只会命中同一个作业；上游若不识别该头，
    也仅是普通请求头，无副作用。

    Args:
        prefix: 键前缀，便于在上游日志中识别来源（如 ``cnb-gitee-edit``）

    Returns:
        形如 ``<prefix>-<32 位十六进制>`` 的幂等键
    """
    # secrets.token_hex 使用系统级随机源，避免多实例并发下 id 碰撞
    return f"{prefix}-{secrets.token_hex(16)}"


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    label: str = "请求",
    on_retry: Callable[[int, float, BaseException], None] | None = None,
    should_retry: Callable[[BaseException], bool] = is_retryable,
) -> T:
    """以指数退避方式执行异步操作.

    退避序列为 ``1s / 2s / 4s``（``RETRY_BACKOFF_BASE * 2 ** (attempt - 1)``），
    上限 ``RETRY_BACKOFF_MAX``。仅对 ``should_retry`` 判定为瞬时故障的异常重试，
    其余异常立即抛出，避免无谓等待与「业务错误被重放」。

    Args:
        operation: 无参异步可调用对象，每次重试都会重新调用（须可安全重放）
        max_retries: 最大重试次数（不含首次请求），0 表示不重试
        label: 操作名称，仅用于回调与日志描述
        on_retry: 重试回调，签名 ``(第几次重试, 退避秒数, 异常)``
        should_retry: 重试判定函数，默认使用 ``is_retryable``

    Returns:
        ``operation`` 的返回值

    Raises:
        BaseException: 最后一次尝试抛出的原始异常（不包装，交由调用方分类）
    """
    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as e:
            attempt += 1
            if attempt > max_retries or not should_retry(e):
                raise
            delay = min(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)), RETRY_BACKOFF_MAX)
            if on_retry is not None:
                on_retry(attempt, delay, e)
            await asyncio.sleep(delay)


def build_timeout() -> aiohttp.ClientTimeout:
    """构建 aiohttp ClientTimeout（区分连接与读取阶段）.

    Returns:
        带 total / connect / sock_read 三段配置的超时对象，便于上层在
        分类错误时区分「连不上」与「等不到响应」。
    """
    return aiohttp.ClientTimeout(
        total=READ_TIMEOUT,
        connect=CONNECT_TIMEOUT,
        sock_read=READ_TIMEOUT,
    )


def describe_http_status(status: int, body: str = "") -> str:
    """把非 2xx 响应转成脱敏后的中文提示.

    Args:
        status: HTTP 状态码
        body: 响应体片段（可选，会被脱敏与截断）

    Returns:
        中文提示文案
    """
    detail = _safe_text(body)
    suffix = f"（响应：{detail}）" if detail else ""

    if status in (401, 403):
        return (
            "上游拒绝访问：API Key 无效、已过期或无权调用该模型，请检查配置。" + suffix
        )
    if status == 404:
        return "上游接口不存在：请确认服务地址与模型端点是否正确。" + suffix
    if status == 429:
        return "上游限流：调用次数超限或并发过高，请稍后再试。" + suffix
    if 500 <= status < 600:
        return "上游服务器内部错误：服务商侧异常，请稍后再试。" + suffix
    return f"上游返回异常状态 {status}。" + suffix


def http_error(exc: BaseException) -> str | None:
    """从 httpx 异常中提取 HTTP 状态错误提示.

    Args:
        exc: 捕获到的异常

    Returns:
        命中 ``httpx.HTTPStatusError`` 时返回中文提示，否则返回 ``None``
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code if current.response else 0
            body = ""
            if current.response is not None:
                try:
                    body = current.response.text[:200]
                except Exception:  # pragma: no cover - 响应体解码失败不影响主流程
                    body = ""
            return describe_http_status(status, body)
        nxt = current.__cause__ or current.__context__
        current = nxt if isinstance(nxt, BaseException) and nxt is not current else None
    return None


def to_user_message(exc: BaseException, fallback: str = "网络请求异常") -> str:
    """把任意异常统一转换为面向用户的中文提示（已脱敏）.

    先尝试 HTTP 状态类错误，再走网络分类，最后回落到通用文案。

    Args:
        exc: 捕获到的异常
        fallback: 分类不出具体原因时的兜底前缀

    Returns:
        可直接回包的中文提示
    """
    status_msg = http_error(exc)
    if status_msg:
        return status_msg
    classified = classify_network_error(exc)
    if classified:
        return classified
    detail = _safe_text(str(exc))  # pragma: no cover - classify 始终返回非空
    return f"{fallback}: {detail}" if detail else fallback


def mask_text(text: Any, limit: int = 240) -> str:
    """对外暴露的脱敏工具，供调用方自行处理日志或异常文本.

    Args:
        text: 任意待脱敏内容
        limit: 保留的最大字符数

    Returns:
        脱敏并截断后的字符串（无有效内容时返回空串）
    """
    return _safe_text(str(text), limit=limit) or ""
