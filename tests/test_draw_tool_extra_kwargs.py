"""回归测试：LLM 生图工具必须容忍未声明的多余参数.

背景（Issue #65 报错）：
AstrBot 依据 ``@filter_cmd.llm_tool`` 处理函数的 docstring ``Args`` 生成工具
参数 schema（本工具仅声明 ``prompt``）。但 LLM 仍可能"脑补"出 schema 之外
的参数，例如 ``use_refs``。实测报错：

    TypeError: AIImage.draw() got an unexpected keyword argument 'use_refs'

后果：整次工具调用直接崩掉，用户收不到任何图片。

修复方式：处理函数（``AIImage.draw``）与实现函数（``draw_image_tool``）均用
``**extra_kwargs`` 兜底吸收未知参数，仅记录忽略，不中断生图主流程。

本测试用最小桩件夹住两条契约：
1. 传入未声明的 ``use_refs`` 时不再抛 TypeError，而是照常走到生图链路；
2. 提示词为非字符串（None）时被安全归一化为字符串，不因切片崩溃。
"""

import asyncio
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))


def _install_astrbot_stubs() -> None:
    """安装最小 ``astrbot`` 桩件，使插件模块可在无宿主环境导入.

    宿主 / CI 已提供完整 astrbot 时直接返回；仅在其缺失时兜底安装，
    避免因环境差异导致本回归测试无法运行。
    """
    try:
        import astrbot.api.event.filter  # noqa: F401

        return
    except Exception:
        pass

    def _set(mod: types.ModuleType, name: str, value: object) -> None:
        # 用 setattr 动态挂属性，避免静态检查报 attr-defined
        setattr(mod, name, value)

    class _Logger:
        def __getattr__(self, _k):
            return lambda *a, **kw: None

    class _FakeEvent:
        def get_sender_id(self):
            return "user-1"

        @staticmethod
        def plain_result(text):
            return ("plain", text)

    class _FakeImage:
        def __init__(self, *a, **k):
            pass

    class _FakePlain(_FakeImage):
        pass

    class _FakeContext:
        pass

    class _FakeStar:
        def __init__(self, *a, **k):
            pass

    class _FakeStarTools:
        @staticmethod
        def get_data_dir(*a, **k):
            return "/tmp"

    def _noop(*_a, **_k):
        def deco(func):
            return func

        return deco

    class _Group:
        def __getattr__(self, _k):
            return _noop

    class _FakeFilter:
        llm_tool = staticmethod(_noop)
        command_group = staticmethod(lambda *a, **k: _Group())

    pkg_astrbot = types.ModuleType("astrbot")
    _set(pkg_astrbot, "__path__", [])
    pkg_api = types.ModuleType("astrbot.api")
    _set(pkg_api, "__path__", [])
    mod_event = types.ModuleType("astrbot.api.event")
    _set(mod_event, "__path__", [])
    mod_filter = types.ModuleType("astrbot.api.event.filter")
    _set(mod_filter, "__path__", [])
    mod_msg = types.ModuleType("astrbot.api.message_components")
    mod_star = types.ModuleType("astrbot.api.star")
    _set(mod_star, "__path__", [])

    _set(mod_filter, "filter", _FakeFilter)
    _set(pkg_api, "logger", _Logger())
    _set(mod_event, "AstrMessageEvent", _FakeEvent)
    _set(mod_msg, "Image", _FakeImage)
    _set(mod_msg, "Plain", _FakePlain)
    _set(mod_star, "Context", _FakeContext)
    _set(mod_star, "Star", _FakeStar)
    _set(mod_star, "StarTools", _FakeStarTools)
    _set(pkg_api, "event", mod_event)
    _set(pkg_api, "message_components", mod_msg)
    _set(pkg_api, "star", mod_star)
    _set(pkg_astrbot, "api", pkg_api)

    for _name, _mod in {
        "astrbot": pkg_astrbot,
        "astrbot.api": pkg_api,
        "astrbot.api.event": mod_event,
        "astrbot.api.event.filter": mod_filter,
        "astrbot.api.message_components": mod_msg,
        "astrbot.api.star": mod_star,
    }.items():
        sys.modules[_name] = _mod


_install_astrbot_stubs()


class _FakeRateLimiter:
    """简化限流器：永远放行，仅记录调用."""

    def __init__(self) -> None:
        self.added = False
        self.removed = False

    def check_debounce(self, _rid: str) -> bool:
        return False

    def is_processing(self, _rid: str) -> bool:
        return False

    def add_processing(self, _rid: str) -> None:
        self.added = True

    def remove_processing(self, _rid: str) -> None:
        self.removed = True


class _FakeResult:
    """模拟 ``MessageEventResult``，记录直发文本."""

    def __init__(self) -> None:
        self.text = ""

    def file_image(self, _path: str) -> "_FakeResult":
        return self

    def message(self, text: str) -> "_FakeResult":
        self.text = text
        return self


class _FakeEventObj:
    """最小消息事件桩件."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def get_sender_id(self) -> str:
        return "user-1"

    def plain_result(self, text: str) -> _FakeResult:
        r = _FakeResult()
        r.text = text
        return r

    def make_result(self) -> _FakeResult:
        return _FakeResult()

    async def send(self, _result) -> None:
        self.sent.append("progress")


class _FakeApiClient:
    """记录收到的提示词与尺寸，返回固定假路径."""

    # parse_prompt_and_size 会读取这两个属性来解析比例与默认尺寸
    supported_ratios = {
        "1:1": ["1024x1024"],
        "9:16": ["1152x2048"],
    }
    default_size = "1024x1024"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def generate_image(self, prompt: str, size: str = "") -> str:
        self.calls.append((prompt, size))
        return "/tmp/fake.png"


class _FakePlugin:
    """最小插件桩件，聚合上面几个替身."""

    def __init__(self) -> None:
        self.rate_limiter = _FakeRateLimiter()
        self.api_client = _FakeApiClient()
        self.logs: list[str] = []

    def debug_log(self, msg: str) -> None:
        self.logs.append(msg)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_unexpected_kwarg_is_tolerated() -> None:
    """核心回归：传入未声明的 use_refs 不应再抛 TypeError."""
    from astrbot_plugin_models_ai.llm_tools.draw import draw_image_tool

    plugin = _FakePlugin()
    event = _FakeEventObj()

    async def _collect():
        return [
            item
            async for item in draw_image_tool(
                plugin, event, "一个女孩 9:16", use_refs=True
            )
        ]

    # 修复前这里会 TypeError；修复后应正常完成并产出图片结果
    results = _run(_collect())

    assert plugin.api_client.calls, "应调用生图客户端"
    assert results, "应产出至少一条结果（图片消息）"
    # 未声明参数被记录忽略
    assert any("忽略未声明参数" in m for m in plugin.logs)


def test_non_string_prompt_is_normalized() -> None:
    """提示词为 None 时应安全归一化为空串而非切片崩溃."""
    from astrbot_plugin_models_ai.llm_tools.draw import draw_image_tool

    plugin = _FakePlugin()
    event = _FakeEventObj()

    async def _collect():
        return [item async for item in draw_image_tool(plugin, event, None)]

    # None 会被 parse_prompt_and_size 判定为空并回传参数错误，不应抛异常
    results = _run(_collect())
    assert results, "应产出一条参数错误提示"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
