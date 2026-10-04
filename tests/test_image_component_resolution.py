"""回归测试：消息图片组件必须被解析为「可直接 open 的本地路径」.

背景（上游兼容）：
AstrBot v4 的 ``Image.fromFileSystem(path)`` 会把 ``file`` 字段写成
``file://`` URI（如 ``file:///tmp/a.png``），真实本地路径放在 ``path``。
本插件旧的 ``extract_images_from_message`` 按 ``url -> file -> path`` 顺序
取值，于是把 ``file://`` URI 当成文件路径返回，最终在
``GiteeAIClient.edit_image`` 里 ``open(filepath, "rb")`` 直接
``FileNotFoundError``，图生图 / 图片编辑全部失效。

修复方式：
优先走上游官方的 ``component.convert_to_file_path()``（内部 MediaResolver，
统一支持本地路径 / file:// / http(s) / base64），并在其缺失时回退到字段解析，
且把 ``file://`` URI 归一化为本地路径、让真实 ``path`` 优先于 ``file``。

本测试夹住三条契约：
1. 组件带 ``convert_to_file_path`` 时走官方通道，拿到可读路径；
2. 无该异步方法（旧宿主 / 桩件）时，``file://`` URI 被归一化为本地路径；
3. 真实 ``path`` 优先于 ``file``，且 URL 组件仍走下载分支。
"""

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))
# 让 tests 目录本身也在搜索路径上，以便按顶层模块名导入同目录测试模块，
# 避免用 ``tests.xxx`` 包前缀触发 mypy 的 "duplicate module name" 报错
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 复用生图工具测试里已铺设的最小 astrbot 桩件，保证可在无宿主环境导入
from test_draw_tool_extra_kwargs import (  # type: ignore[import-not-found]  # noqa: E402
    _install_astrbot_stubs,
)

_install_astrbot_stubs()

# 以宿主真实（或桩件的）Image 为基类，确保 isinstance 判定通过
from astrbot.api.message_components import Image as _Image  # noqa: E402


class _ComponentWithConvert(_Image):
    """带官方 ``convert_to_file_path`` 的组件替身（模拟新宿主）."""

    def __init__(self, resolved: str) -> None:
        super().__init__(file="")
        self._resolved = resolved
        self.convert_calls = 0
        # 故意给一个会是「坑」的 file:// URI，验证不会误用它
        self.file = "file:///should/not/be/used.png"
        self.url = ""
        self.path = ""

    async def convert_to_file_path(self) -> str:
        self.convert_calls += 1
        return self._resolved


class _ComponentLegacyFileUri(_Image):
    """无 ``convert_to_file_path`` 的旧宿主组件：只有 file:// URI."""

    def __init__(self) -> None:
        super().__init__(file="")
        # 显式赋字段：桩件的 __init__ 会忽略入参
        self.file = "file:///tmp/legacy.png"
        self.url = ""
        self.path = ""

    def convert_to_file_path(self):  # pragma: no cover
        # 模拟旧宿主无该异步方法（getattr 结果为不可用）
        raise AttributeError("legacy host has no convert_to_file_path")


class _ComponentWithPathAndFile(_Image):
    """同时含 file:// URI 与真实 path，验证 path 优先级更高."""

    def __init__(self) -> None:
        super().__init__(file="")
        self.file = "file:///tmp/same.png"
        self.url = ""
        self.path = "/tmp/same.png"

    def convert_to_file_path(self):  # pragma: no cover
        raise AttributeError("force field fallback")


class _ComponentUrlOnly(_Image):
    """仅含远程 URL 的组件."""

    def __init__(self) -> None:
        super().__init__(file="")
        self.file = ""
        self.url = "https://example.invalid/x.png"
        self.path = ""

    def convert_to_file_path(self):  # pragma: no cover
        raise AttributeError("force url branch")


class _Event:
    def __init__(self, components) -> None:
        class _Msg:
            message = components

        self.message_obj = _Msg()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_prefers_official_convert_to_file_path():
    """有官方方法时优先调用它，并返回其结果."""
    from astrbot_plugin_models_ai.core.command_utils import (
        extract_images_from_message,
    )

    comp = _ComponentWithConvert("/tmp/official.png")
    paths = _run(extract_images_from_message(_Event([comp])))

    assert paths == ["/tmp/official.png"]
    assert comp.convert_calls == 1, "应优先走官方 convert_to_file_path"


def test_legacy_file_uri_is_normalized_to_path():
    """无官方方法时，file:// URI 必须被归一化为可 open 的本地路径."""
    from astrbot_plugin_models_ai.core.command_utils import (
        extract_images_from_message,
    )

    paths = _run(extract_images_from_message(_Event([_ComponentLegacyFileUri()])))

    assert paths == ["/tmp/legacy.png"], "file:// URI 应被归一化为本地路径"
    assert not paths[0].startswith("file://")


def test_real_path_takes_precedence_over_file_field():
    """真实 path 应优先于可能是 URI 的 file 字段."""
    from astrbot_plugin_models_ai.core.command_utils import (
        extract_images_from_message,
    )

    paths = _run(extract_images_from_message(_Event([_ComponentWithPathAndFile()])))

    assert paths == ["/tmp/same.png"]


def test_url_component_still_downloads(monkeypatch):
    """URL 组件仍走下载分支（此处用桩替换下载函数，只验证路由）."""
    import astrbot_plugin_models_ai.core.command_utils as cu

    async def _fake_download(url: str):
        return f"/tmp/downloaded-{url.rsplit('/', 1)[-1]}"

    monkeypatch.setattr(cu, "download_image", _fake_download)

    paths = _run(cu.extract_images_from_message(_Event([_ComponentUrlOnly()])))

    assert paths == ["/tmp/downloaded-x.png"]


def test_legacy_four_slash_file_uri_is_normalized():
    """兼容旧 AstrBot 生成的 ``file:////abs/path``（POSIX 绝对路径）."""
    from astrbot_plugin_models_ai.core.command_utils import _file_uri_to_path

    assert _file_uri_to_path("file:////tmp/legacy.png") == "/tmp/legacy.png"


def test_localhost_file_uri_is_normalized():  # DevSkim: ignore DS162092
    """``file://<本地主机名>/path`` 也应解析为本地路径.

    本用例的 <本地主机名> 是被测输入本身：file URI 的空主机字段（RFC 8089
    允许 ``file://localhost/path``），语义等价于省略主机，全程不经网络、
    也非回环调试地址，故内联抑制 DevSkim DS162092 误报。

    覆盖 ``core/command_utils._file_uri_to_path`` 里带 DevSkim 抑制注释的
    分支：该处 host 字段同属 file URI 空主机形态，按「空主机」处理即可，
    不能误判成 ``file://host/path`` 而去掉前导斜杠。
    """
    from astrbot_plugin_models_ai.core.command_utils import _file_uri_to_path

    # 断言字面量里的 host 同样是 file URI 字段，非调试地址
    assert (
        _file_uri_to_path("file://localhost/tmp/a.png") == "/tmp/a.png"
    )  # DevSkim: ignore DS162092
    # 大小写不敏感，且抑制分支不得把 netloc 拼进路径
    assert (
        _file_uri_to_path("file://LOCALHOST/tmp/b.png") == "/tmp/b.png"
    )  # DevSkim: ignore DS162092


def test_real_host_file_uri_keeps_unc_prefix():
    """非本地主机的 host 仍需保留 UNC 前缀（与空主机分支区分开）."""
    from astrbot_plugin_models_ai.core.command_utils import _file_uri_to_path

    assert _file_uri_to_path("file://server/share/a.png") == "//server/share/a.png"


def test_plain_path_and_url_are_returned_unchanged():
    """非 file: 引用（普通路径、URL）应原样返回，不被误改."""
    from astrbot_plugin_models_ai.core.command_utils import _file_uri_to_path

    assert _file_uri_to_path("/tmp/plain.png") == "/tmp/plain.png"
    assert (
        _file_uri_to_path("https://example.invalid/x.png")
        == "https://example.invalid/x.png"
    )


def test_non_image_components_are_skipped():
    """非图片组件应被跳过，不产生路径."""
    from astrbot_plugin_models_ai.core.command_utils import (
        extract_images_from_message,
    )

    paths = _run(extract_images_from_message(_Event(["not-an-image", object()])))
    assert paths == []


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
