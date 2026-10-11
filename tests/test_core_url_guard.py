"""出站取图主机白名单校验测试.

覆盖 ``core/url_guard.py`` 与两处取图入口的接线：

- 白名单匹配（精确 / 子域 / 大小写 / IPv6 括号归一化）
- 协议限制（仅 http/https）
- 内网地址识别与拒绝提示
- ``allow_any`` 逃逸开关
- ``ImageManager.download_image`` 在下载前即拒绝越界主机（不发请求）
- ``command_utils.download_image`` 的消息图片 URL 白名单校验

背景：``SECURITY.md`` 承诺「仅向服务商端点出站」，但取图实际会触达用户消息
URL 与服务商 CDN，故以本项目新增的白名单收敛，本测试锁住该契约。
"""

import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.core.url_guard import (  # noqa: E402
    build_allowed_hosts,
    check_image_url,
    extract_host,
    is_private_host,
)


def test_extract_host_normalizes():
    """主机提取需小写、剥 IPv6 括号、去尾点."""
    assert extract_host("HTTPS://AI.Gitee.COM/v1/x") == "ai.gitee.com"
    assert extract_host("https://[2001:db8::1]/a") == "2001:db8::1"
    assert extract_host("https://example.com./a") == "example.com"
    # 非法 URL 不应抛异常
    assert extract_host("http://[") == ""


def test_build_allowed_hosts_merges_and_normalizes():
    """白名单合并服务商主机与用户追加项，并归一化."""
    allowed = build_allowed_hosts(
        provider_hosts=["AI.Gitee.COM"],
        extra_hosts=["cdn.example.com", "", "  ", "ai.gitee.com"],
    )
    assert "ai.gitee.com" in allowed
    assert "cdn.example.com" in allowed
    assert "" not in allowed


def test_check_allows_provider_and_subdomain():
    """端点主机与其子域应在白名单内放行."""
    allowed = build_allowed_hosts(provider_hosts=["ai.gitee.com"])
    ok, reason = check_image_url("https://ai.gitee.com/a.png", allowed)
    assert ok and reason == ""
    ok, _ = check_image_url("https://cdn.ai.gitee.com/a.png", allowed)
    assert ok


def test_check_rejects_unlisted_host():
    """未收录主机默认拒绝，并提示配置入口."""
    allowed = build_allowed_hosts(provider_hosts=["ai.gitee.com"])
    ok, reason = check_image_url("https://evil.example.net/a.png", allowed)
    assert not ok
    assert "白名单" in reason
    assert "allowed_image_hosts" in reason


def test_check_rejects_private_ip_with_hint():
    """内网 IP 被拒时应额外标注内网."""
    allowed = build_allowed_hosts(provider_hosts=["ai.gitee.com"])
    ok, reason = check_image_url("http://127.0.0.1/a.png", allowed)
    assert not ok
    assert "内网" in reason
    ok, reason = check_image_url("http://192.168.1.10/a.png", allowed)
    assert not ok and "内网" in reason


def test_check_rejects_non_http_scheme():
    """非 http/https 协议一律拒绝（防触碰本地文件）."""
    allowed = build_allowed_hosts(provider_hosts=["ai.gitee.com"])
    ok, reason = check_image_url("file:///etc/passwd", allowed)
    assert not ok
    assert "http" in reason


def test_check_allow_any_escapes_whitelist():
    """allow_any 开关应跳过白名单（显式配置才生效）."""
    allowed = build_allowed_hosts(provider_hosts=["ai.gitee.com"])
    ok, _ = check_image_url("https://anywhere.example/a.png", allowed, allow_any=True)
    assert ok


def test_is_private_host_detects_loopback_and_localhost():
    """回环 / localhost 应被识别为内网."""
    assert is_private_host("127.0.0.1")
    assert is_private_host("localhost")
    assert is_private_host("10.0.0.1")
    assert not is_private_host("ai.gitee.com")
    assert not is_private_host("8.8.8.8")


def test_image_manager_rejects_before_any_request(tmp_path, monkeypatch):
    """越界主机必须在发起请求前被拒（会话不应被调用）."""
    from astrbot_plugin_models_ai.core import image_manager as im_mod
    from astrbot_plugin_models_ai.core.image_manager import ImageManager

    monkeypatch.setattr(
        im_mod.StarTools, "get_data_dir", staticmethod(lambda *_a, **_k: tmp_path)
    )

    class ExplodingSession:
        def get(self, *a, **k):  # pragma: no cover - 命中即说明校验漏了
            raise AssertionError("越界主机不应发起请求")

    mgr = ImageManager(
        allowed_image_hosts=[],
        provider_base_url="https://ai.gitee.com/v1",
    )
    with pytest.raises(RuntimeError, match="白名单"):
        run(mgr.download_image("https://evil.example.net/a.png", ExplodingSession()))


def test_image_manager_allows_provider_host(tmp_path, monkeypatch):
    """端点主机应放行并可正常落盘."""
    from astrbot_plugin_models_ai.core import image_manager as im_mod
    from astrbot_plugin_models_ai.core.image_manager import ImageManager

    monkeypatch.setattr(
        im_mod.StarTools, "get_data_dir", staticmethod(lambda *_a, **_k: tmp_path)
    )

    class Resp:
        status = 200
        headers = {"Content-Type": "image/png"}

        async def read(self):
            return b"ok"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Session:
        def get(self, url, **kw):
            return Resp()

    mgr = ImageManager(provider_base_url="https://ai.gitee.com/v1")
    path = run(mgr.download_image("https://ai.gitee.com/r.png", Session()))
    assert path.endswith(".png")


def test_command_utils_download_rejects_unlisted(monkeypatch):
    """命令层消息取图：白名单外的主机应直接返回 None，且不发起请求."""
    from astrbot_plugin_models_ai.core import command_utils as cu

    called = {"n": 0}

    class _Session:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, *a, **k):  # pragma: no cover - 命中即说明白名单漏判
            called["n"] += 1
            raise AssertionError("越界主机不应发起请求")

    monkeypatch.setattr(cu.aiohttp, "ClientSession", _Session)
    allowed = build_allowed_hosts(provider_hosts=["ai.gitee.com"])
    result = run(cu.download_image("https://evil.example.net/a.png", allowed))
    assert result is None
    assert called["n"] == 0


def test_resolve_image_component_rejects_unlisted_url(monkeypatch):
    """消息组件兜底解析路径同样受白名单约束."""
    from astrbot_plugin_models_ai.core import command_utils as cu

    class _Component:
        url = "http://169.254.169.254/latest/meta-data/"
        path = ""
        file = ""

    allowed = build_allowed_hosts(provider_hosts=["ai.gitee.com"])
    result = run(
        cu._resolve_image_component(_Component(), allowed, allow_any_host=False)
    )
    assert result is None
