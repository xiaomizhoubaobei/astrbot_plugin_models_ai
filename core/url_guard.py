"""图片下载出站主机白名单校验模块.

背景（PR 安全审查）：``SECURITY.md`` 声明「插件仅向已配置的服务商 API 端点
发起出站请求」，但源码里实际存在三类会越出该边界的取图行为：

1. **用户消息里的图片 URL**：``command_utils.download_image`` 会直接抓取
   消息组件携带的任意 http(s) URL（图生图 / 图片编辑场景），主机由消息
   发送方控制，理论上可指向内网地址（SSRF 面）。
2. **服务商返回的图片结果 URL**：``ImageManager.download_image`` 会抓取上游
   响应里给出的地址，虽由服务商生成，但可能是其 CDN / 第三方对象存储，
   并不等于「配置的 API 端点主机」。
3. **宿主解析链路**：``convert_to_file_path()`` 由 AstrBot 宿主内部完成下载，
   不在本插件可控范围内。

本模块把这批「辅助取图」的出站目标收敛为一份可审计的**主机白名单**：

- 默认放行**服务商 API 端点主机**（由调用方按当前 provider 的 base_url 传入）；
- 允许通过插件配置 ``allowed_image_hosts`` 追加额外可信主机（如私有图床、
  服务商 CDN 域名）；
- 其余主机一律拒绝，并给出可操作的中文提示，避免用户在白屏报错里猜原因。

设计取舍：**默认拒绝未知主机**，而不是默认放行——文档承诺了「仅向服务商
端点出站」，那么越界就必须是显式配置的结果，而非静默行为。若部署方确需
宽松策略，可显式打开 ``allow_any_image_host``，代价是放弃 SSRF 防护。
"""

import ipaddress
from typing import Iterable, Optional
from urllib.parse import urlparse

# 允许取图的 URL 协议：仅 http(s)。其余（file://、ftp:// 等）一律不接受，
# 避免经由此路径触碰本地文件系统。
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# 主机白名单匹配时统一小写，并对「裸域名」自动兼容其子域
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _normalize_host(host: str) -> str:
    """归一化主机名：小写、去首尾点、剥 IPv6 方括号.

    Args:
        host: 原始主机名

    Returns:
        归一化后的主机名（无法解析时返回空串）
    """
    if not host:
        return ""
    candidate = host.strip().lower().rstrip(".")
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    return candidate


def _host_matches(candidate: str, pattern: str) -> bool:
    """判断主机是否命中白名单条目（支持精确与子域匹配）.

    Args:
        candidate: 待校验主机（已归一化）
        pattern: 白名单条目（原始形态，内部会归一化）

    Returns:
        命中返回 ``True``
    """
    normalized = _normalize_host(pattern)
    if not normalized or not candidate:
        return False
    if candidate == normalized:
        return True
    # 白名单写裸域名时，兼容其子域：example.com 命中 cdn.example.com
    return candidate.endswith("." + normalized)


def is_private_host(host: str) -> bool:
    """粗略判断主机是否指向内网 / 回环地址（用于日志告警）.

    仅在主机本身是 IP 字面量时做判定；域名形态（如 ``localhost`` 或
    内网 DNS 名）无法在纯字符串层面识别，故不在此处拦截，交由白名单裁决。

    Args:
        host: 主机名

    Returns:
        属于回环 / 私有 / 链路本地地址时返回 ``True``
    """
    normalized = _normalize_host(host)
    if not normalized:
        return False
    if normalized == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
    )


def extract_host(url: str) -> str:
    """从 URL 中提取归一化主机名.

    Args:
        url: 待解析 URL

    Returns:
        归一化主机名；URL 非法或缺主机时返回空串
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return _normalize_host(parsed.hostname or "")


def build_allowed_hosts(
    provider_hosts: Optional[Iterable[str]] = None,
    extra_hosts: Optional[Iterable[str]] = None,
) -> frozenset[str]:
    """构建本次运行的主机白名单集合.

    Args:
        provider_hosts: 服务商端点主机（自动纳入，如 ``ai.gitee.com``）
        extra_hosts: 用户在配置中追加的可信主机

    Returns:
        归一化后的白名单集合
    """
    allowed: set[str] = set()
    for group in (provider_hosts, extra_hosts):
        if not group:
            continue
        for host in group:
            normalized = _normalize_host(host)
            if normalized:
                allowed.add(normalized)
    return frozenset(allowed)


def check_image_url(
    url: str,
    allowed_hosts: Iterable[str],
    *,
    allow_any: bool = False,
) -> tuple[bool, str]:
    """校验一个图片 URL 是否允许出站下载.

    Args:
        url: 待校验的图片 URL
        allowed_hosts: 白名单主机集合（由 :func:`build_allowed_hosts` 构建）
        allow_any: 是否跳过白名单（对应配置 ``allow_any_image_host``）

    Returns:
        ``(allowed, reason)`` 二元组：允许时 ``reason`` 为空串；
        拒绝时 ``reason`` 为可直接回给用户的中文说明。
    """
    if not url or not isinstance(url, str):
        return False, "图片地址为空，无法下载"

    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "图片地址格式非法，无法下载"

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return False, f"仅支持 http/https 取图，收到协议：{scheme or '未知'}"

    host = _normalize_host(parsed.hostname or "")
    if not host:
        return False, "图片地址缺少主机名，无法下载"

    if allow_any:
        return True, ""

    for pattern in allowed_hosts:
        if _host_matches(host, pattern):
            return True, ""

    hint = "，且该地址指向内网" if is_private_host(host) else ""
    return False, (
        f"图片主机不在出站白名单内：{host}{hint}。"
        f"若确需从该主机取图，请在插件配置的 allowed_image_hosts 中追加该域名。"
    )
