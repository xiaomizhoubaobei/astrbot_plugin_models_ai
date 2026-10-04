"""命令工具单元测试.

覆盖 ``core/command_utils.py`` 的公共辅助：
- ``check_rate_limit``：防抖 / 并发拦截与放行；
- ``parse_prompt_and_size``：比例解析、默认尺寸与空提示词校验；
- ``_file_uri_to_path``：file:// URI 归一化（不依赖解释器版本的 url2pathname）；
- ``extract_images_from_message``：多种图片组件形态的路径解析；
- ``download_image``：远程取图的成功 / 非 200 / 异常降级。
"""

import os

import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.core import command_utils as cu  # noqa: E402


class StubRateLimiter:
    """可编程的限流器替身."""

    def __init__(self, debounce=False, processing=False):
        self._debounce = debounce
        self._processing = processing
        self.added = []
        self.removed = []

    def check_debounce(self, _rid):
        return self._debounce

    def is_processing(self, _rid):
        return self._processing

    def add_processing(self, rid):
        self.added.append(rid)

    def remove_processing(self, rid):
        self.removed.append(rid)


class StubClient:
    """带 supported_ratios / default_size 的客户端替身."""

    def __init__(self, default_size="1024x1024"):
        self.supported_ratios = {
            "1:1": ["256x256", "1024x1024"],
            "9:16": ["576x1024", "1152x2048"],
            "16:9": ["1024x576"],
        }
        self.default_size = default_size


class StubPlugin:
    def __init__(self, rate_limiter=None, client=None):
        self.rate_limiter = rate_limiter or StubRateLimiter()
        self.api_client = client or StubClient()
        self.logs = []

    def debug_log(self, msg):
        self.logs.append(msg)


class StubEvent:
    def __init__(self, sender="u1", message_obj=None):
        self._sender = sender
        self.message_obj = message_obj

    def get_sender_id(self):
        return self._sender

    def plain_result(self, text):
        return ("plain", text)


# ===== check_rate_limit =====


def test_check_rate_limit_passes_and_marks_processing() -> None:
    """正常请求应放行并登记为处理中."""
    plugin = StubPlugin()
    event = StubEvent()

    async def _drive():
        return [r async for r in cu.check_rate_limit(plugin, event, "cmd", "u1")]

    out = run(_drive())
    assert out == []
    assert plugin.rate_limiter.added == ["u1"]


def test_check_rate_limit_debounced() -> None:
    """防抖命中时给出拒绝文案，且不登记处理中."""
    plugin = StubPlugin(rate_limiter=StubRateLimiter(debounce=True))
    event = StubEvent()

    async def _drive():
        return [r async for r in cu.check_rate_limit(plugin, event, "cmd", "u1")]

    out = run(_drive())
    assert out and "太快" in out[0][1]
    assert plugin.rate_limiter.added == []


def test_check_rate_limit_processing() -> None:
    """已有任务在处理中时拒绝并发."""
    plugin = StubPlugin(rate_limiter=StubRateLimiter(processing=True))
    event = StubEvent()

    async def _drive():
        return [r async for r in cu.check_rate_limit(plugin, event, "cmd", "u1")]

    out = run(_drive())
    assert out and "正在进行" in out[0][1]
    assert plugin.rate_limiter.added == []


# ===== parse_prompt_and_size =====


def test_parse_prompt_with_ratio() -> None:
    """提示词末尾的合法比例被提取，并映射到对应尺寸."""
    plugin = StubPlugin()
    prompt, size = cu.parse_prompt_and_size(plugin, "一个女孩 9:16")
    assert prompt == "一个女孩"
    assert size == "576x1024"


def test_parse_prompt_default_ratio() -> None:
    """未指定比例时按 1:1 取默认尺寸."""
    plugin = StubPlugin()
    prompt, size = cu.parse_prompt_and_size(plugin, "一只猫")
    assert prompt == "一只猫"
    assert size == "1024x1024"


def test_parse_prompt_default_size_used_when_in_ratio_list() -> None:
    """1:1 且默认尺寸已在 1:1 列表内时，沿用默认尺寸（不覆写为列表首项）."""
    plugin = StubPlugin(client=StubClient(default_size="1024x1024"))
    _prompt, size = cu.parse_prompt_and_size(plugin, "一只猫")
    assert size == "1024x1024"


def test_parse_prompt_empty_raises() -> None:
    """空提示词抛 ValueError."""
    plugin = StubPlugin()
    with pytest.raises(ValueError, match="不能为空"):
        cu.parse_prompt_and_size(plugin, "   ")


def test_parse_prompt_ratio_then_ratio_keeps_left_as_prompt() -> None:
    """两个比例连续出现时，左侧比例会被当作提示词内容（rsplit 语义）."""
    plugin = StubPlugin()
    prompt, size = cu.parse_prompt_and_size(plugin, "9:16 9:16")
    assert prompt == "9:16"
    assert size == "576x1024"


def test_parse_prompt_non_ratio_suffix_kept() -> None:
    """末尾不是合法比例时视为提示词的一部分."""
    plugin = StubPlugin()
    prompt, size = cu.parse_prompt_and_size(plugin, "一只猫 5:6")
    assert prompt == "一只猫 5:6"
    assert size == "1024x1024"


# ===== file URI 归一化 =====


def test_is_file_uri() -> None:
    assert cu._is_file_uri("file:///tmp/a.png") is True
    assert cu._is_file_uri("FILE:///tmp/a.png") is True
    assert cu._is_file_uri("/tmp/a.png") is False
    assert cu._is_file_uri("http://x/a.png") is False
    assert cu._is_file_uri(123) is False


def test_file_uri_plain_path() -> None:
    """基本 file:/// 形态归一化为本地路径."""
    assert cu._file_uri_to_path("file:///tmp/a.png") == "/tmp/a.png"


def test_file_uri_four_slashes() -> None:
    """旧 AstrBot 的 file:////abs 形态在 POSIX 下归一为单斜杠绝对路径."""
    if os.name != "nt":
        assert cu._file_uri_to_path("file:////tmp/a.png") == "/tmp/a.png"


def test_file_uri_localhost_host_dropped() -> None:
    """localhost 主机被丢弃，只取路径."""
    assert cu._file_uri_to_path("file://localhost/tmp/a.png") == "/tmp/a.png"


def test_file_uri_percent_decoded() -> None:
    """百分号转义应被还原（含中文多字节路径）."""
    out = cu._file_uri_to_path("file:///tmp/%E4%B8%AD%E6%96%87.png")
    assert "中文" in out


def test_file_uri_non_uri_unchanged() -> None:
    """非 file URI 原样返回."""
    assert cu._file_uri_to_path("/tmp/a.png") == "/tmp/a.png"
    assert cu._file_uri_to_path("http://x/a.png") == "http://x/a.png"


# ===== extract_images_from_message =====


class FakeImageComponent:
    """图片组件替身：可配置 convert_to_file_path / url / path / file."""

    def __init__(self, convert=None, url="", path="", file=""):
        if convert is not None:
            self.convert_to_file_path = convert
        self.url = url
        self.path = path
        self.file = file


class FakeMessageObj:
    def __init__(self, message):
        self.message = message


def _image_type():
    from astrbot.api.message_components import Image

    return Image


def test_extract_images_prefers_convert_method() -> None:
    """优先走官方 convert_to_file_path."""
    Image = _image_type()

    async def _convert():
        return "/tmp/converted.png"

    comp = Image()
    comp.convert_to_file_path = _convert
    event = StubEvent(message_obj=FakeMessageObj([comp]))

    paths = run(cu.extract_images_from_message(event))
    assert paths == ["/tmp/converted.png"]


def test_extract_images_convert_failure_falls_back_to_path() -> None:
    """convert 抛异常时回退字段解析."""
    Image = _image_type()

    async def _boom():
        raise RuntimeError("convert failed")

    comp = Image()
    comp.convert_to_file_path = _boom
    comp.path = "/tmp/fallback.png"
    event = StubEvent(message_obj=FakeMessageObj([comp]))

    paths = run(cu.extract_images_from_message(event))
    assert paths == ["/tmp/fallback.png"]


def test_extract_images_path_takes_precedence_over_file() -> None:
    """path 优先于可能是 file:// URI 的 file 字段."""
    Image = _image_type()
    comp = Image()
    comp.path = "/tmp/real.png"
    comp.file = "file:///tmp/uri.png"
    event = StubEvent(message_obj=FakeMessageObj([comp]))

    assert run(cu.extract_images_from_message(event)) == ["/tmp/real.png"]


def test_extract_images_file_uri_normalized() -> None:
    """仅有 file 字段且为 file:// URI 时应归一化."""
    Image = _image_type()
    comp = Image()
    comp.file = "file:///tmp/from_file.png"
    event = StubEvent(message_obj=FakeMessageObj([comp]))

    assert run(cu.extract_images_from_message(event)) == ["/tmp/from_file.png"]


def test_extract_images_skips_non_image_components() -> None:
    """非图片组件被跳过."""
    event = StubEvent(message_obj=FakeMessageObj([object(), "text"]))

    assert run(cu.extract_images_from_message(event)) == []


def test_extract_images_empty_message() -> None:
    """空消息返回空列表."""
    assert run(cu.extract_images_from_message(StubEvent(message_obj=None))) == []
    assert (
        run(cu.extract_images_from_message(StubEvent(message_obj=FakeMessageObj([]))))
        == []
    )


def test_extract_images_no_resolvable_field_skipped() -> None:
    """组件无任何可取字段时被跳过（返回 None -> 不计入）."""
    Image = _image_type()
    comp = Image()  # 无 url/path/file
    event = StubEvent(message_obj=FakeMessageObj([comp]))
    assert run(cu.extract_images_from_message(event)) == []


# ===== download_image =====


def test_download_image_success(tmp_path, monkeypatch) -> None:
    """下载成功应落盘到临时目录并返回路径."""
    monkeypatch.chdir(tmp_path)

    class Resp:
        status = 200

        async def read(self):
            return b"IMGDATA"

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

    path = run(cu.download_image("http://x/a.png"))
    assert path is not None
    with open(path, "rb") as f:
        assert f.read() == b"IMGDATA"


def test_download_image_non_200_returns_none(tmp_path, monkeypatch) -> None:
    """非 200 降级为 None（辅助请求不阻断主流程）."""
    monkeypatch.chdir(tmp_path)

    class Resp:
        status = 404

        async def read(self):
            return b""

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

    assert run(cu.download_image("http://x/a.png")) is None


def test_download_image_exception_returns_none(tmp_path, monkeypatch) -> None:
    """网络异常被分类记录后降级为 None."""
    monkeypatch.chdir(tmp_path)

    class Session:
        def __init__(self, *a, **k):
            raise ConnectionResetError("connection reset")

    monkeypatch.setattr(cu.aiohttp, "ClientSession", Session)

    assert run(cu.download_image("http://x/a.png")) is None
