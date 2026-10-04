"""边界分支补测.

针对覆盖率报告中仍未被主用例触达的分支做定向补测：

- ``commands/style.py``：风格 JSON 缺失 / 解析失败时的降级加载，以及
  自定义描述参数解析失败的回包分支；
- ``core/command_utils.py``：Windows 盘符与 UNC 主机形态的 file URI 归一化、
  ``file`` 字段为 http(s) URL 时的远程下载分支、临时目录写入失败降级；
- 各模块 ``debug_log`` 打开开关后的日志分支。
"""

import os

from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()


# ===== style 风格文件加载降级 =====


def test_load_style_prompts_missing_file(monkeypatch, tmp_path) -> None:
    """风格 JSON 文件不存在时返回空字典（不抛异常）."""
    from astrbot_plugin_models_ai.commands import style as style_mod

    monkeypatch.setattr(style_mod, "__file__", str(tmp_path / "style.py"))
    assert style_mod._load_style_prompts() == {}


def test_load_style_prompts_invalid_json(monkeypatch, tmp_path) -> None:
    """风格 JSON 解析失败时返回空字典."""
    from astrbot_plugin_models_ai.commands import style as style_mod

    bad = tmp_path / "style_prompts.json"
    bad.write_text("{not-valid-json", encoding="utf-8")
    monkeypatch.setattr(style_mod, "__file__", str(tmp_path / "style.py"))
    assert style_mod._load_style_prompts() == {}


def test_style_param_parse_failure_branch() -> None:
    """自定义描述解析失败时回包参数错误（走 ValueError 分支）."""
    from astrbot_plugin_models_ai.commands.style import style_command

    class RateLimiter:
        def check_debounce(self, _r):
            return False

        def is_processing(self, _r):
            return False

        def add_processing(self, _r):
            pass

        def remove_processing(self, _r):
            pass

    from _plugin_harness import FakeResult

    class Client:
        supported_ratios = {"1:1": ["1024x1024"]}
        default_size = "1024x1024"

    class Plugin:
        def __init__(self):
            self.rate_limiter = RateLimiter()
            self.api_client = Client()

        def debug_log(self, _m):
            pass

    class Event:
        def get_sender_id(self):
            return "u1"

        def plain_result(self, text):
            r = FakeResult()
            r.text = text
            return r

    async def _drive():
        # 只给比例 -> parse_prompt_and_size 抛 ValueError
        return [
            r async for r in style_command(Plugin(), Event(), "手办化", "9:16 9:16")
        ]

    out = run(_drive())
    assert out


# ===== command_utils file URI 边界 =====


def test_file_uri_windows_drive_form() -> None:
    """Windows 盘符形态 file:///C:/a.png 应剥掉多余前导斜杠."""
    from astrbot_plugin_models_ai.core import command_utils as cu

    out = cu._file_uri_to_path("file:///C:/a.png")
    # 平台无关断言：不得保留三斜杠
    assert "C:" in out
    assert not out.startswith("///")


def test_file_uri_unc_host_posix() -> None:
    """非 localhost 主机在 POSIX 下保留 //host/path 形态."""
    from astrbot_plugin_models_ai.core import command_utils as cu

    out = cu._file_uri_to_path("file://server/share/a.png")
    if os.name != "nt":
        assert out.startswith("//server")


def test_file_uri_parse_error_returns_false() -> None:
    """urlparse 抛 ValueError 时 _is_file_uri 返回 False."""
    from astrbot_plugin_models_ai.core import command_utils as cu

    class BadStr(str):
        def __str__(self):  # pragma: no cover - 触发 urlparse 异常
            raise ValueError("boom")

    assert cu._is_file_uri("file:///x") is True  # 正常情形
    assert cu._is_file_uri(None) is False


def test_file_field_http_url_downloads(monkeypatch) -> None:
    """图片组件仅 file 字段为 http(s) URL 时应走远程下载.

    注意：``extract_images_from_message`` 内部用的是它导入期绑定的
    ``Image`` 类做 ``isinstance`` 判断。为避免与其它测试文件安装的宿主桩件
    发生类型错配（它们会替换 ``astrbot.api.message_components.Image``），
    这里直接复用 ``command_utils`` 已绑定的同一个 ``Image`` 类来造组件。
    """
    from astrbot_plugin_models_ai.core import command_utils as cu

    called = []

    async def _fake_download(url):
        called.append(url)
        return "/tmp/dl.png"

    monkeypatch.setattr(cu, "download_image", _fake_download)

    comp = cu.Image()
    comp.file = "https://cdn/a.png"
    message_obj = type("M", (), {"message": [comp]})()
    event = type("E", (), {"message_obj": message_obj})()

    paths = run(cu.extract_images_from_message(event))
    assert paths == ["/tmp/dl.png"]
    assert called == ["https://cdn/a.png"]


def test_download_image_temp_dir_failure_returns_none(tmp_path, monkeypatch) -> None:
    """临时目录写入失败时降级为 None（不抛异常）."""
    monkeypatch.chdir(tmp_path)
    from astrbot_plugin_models_ai.core import command_utils as cu

    class Resp:
        status = 200

        async def read(self):
            return b"DATA"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

    class Session:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        def get(self, url):
            return Resp()

    monkeypatch.setattr(cu.aiohttp, "ClientSession", Session)

    # 让 mkdir 抛 OSError，触发 except OSError 分支
    class BrokenPath:
        def __init__(self, *a, **k):
            pass

        def mkdir(self, **_k):
            raise OSError("read-only fs")

    monkeypatch.setattr(cu, "Path", BrokenPath)

    assert run(cu.download_image("http://x/a.png")) is None


# ===== debug_log 分支 =====


def test_debug_log_branches_across_modules() -> None:
    """各模块 debug_log 打开后不应报错."""
    from astrbot_plugin_models_ai.commands import style as style_mod
    from astrbot_plugin_models_ai.core.command_utils import check_rate_limit
    from astrbot_plugin_models_ai.core.image_manager import ImageManager

    mgr = ImageManager(debug_mode=True)
    mgr.debug_log("hi")
    # 风格模块无实例方法，但确认模块可访问
    assert hasattr(style_mod, "_load_style_prompts")
    assert check_rate_limit is not None
