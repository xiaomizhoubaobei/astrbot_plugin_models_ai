"""共享测试桩件：导入垫片 + astrbot 宿主替身 + 通用假对象.

为什么单独抽一层
----------------
仓库里已有三份测试各自维护一套 ``astrbot`` 桩件与假事件对象，新增用例时
若继续复制，会出现「同一契约在三处各写一遍」的漂移。本模块把这些**公共
前置条件**收口到一处：

1. **导入垫片**：复用 ``_coverage_support``，让源码以顶层包名
   ``astrbot_plugin_models_ai`` 可导入（覆盖率工具据此统计真实行号）。
2. **宿主替身**：安装最小 ``astrbot`` 包（``api.event.filter`` /
   ``api.message_components`` / ``api.star``），使插件模块在无宿主环境下
   可导入；**仅在宿主缺失时**兜底，已装宿主时不覆盖。
3. **通用假对象**：``FakeResult`` / ``FakeEvent`` 等，供命令层用例复用。

用法：用例文件顶部 ``from _plugin_harness import ensure_host, ...`` 即可，
不需要再写任何 sys.path / 桩件样板。
"""

import asyncio
import sys
import types
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

_REPO_ROOT = _TESTS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT.parent))

# 覆盖率导入垫片（同时把临时包视图注入 sys.path）
from _coverage_support import ensure_package_view  # noqa: E402

ensure_package_view()

# 宿主缺失时才安装桩件的白名单：精确到「宿主包本身或其预期子模块」
_HOST_PACKAGE_MODULES = frozenset({"astrbot", "astrbot.api.event.filter"})


def _set(mod: types.ModuleType, name: str, value: object) -> None:
    """动态挂载属性，避免静态检查报 attr-defined."""
    setattr(mod, name, value)


class _NullLogger:
    """吞掉所有日志调用，避免测试输出噪音."""

    def __getattr__(self, _k):
        return lambda *a, **kw: None


class FakeResult:
    """模拟 ``MessageEventResult``，记录文本并支持链式调用."""

    def __init__(self) -> None:
        """初始化空结果（默认 plain，无链式组件）."""
        self.text = ""
        self.kind = "plain"
        self.chain: list = []

    def file_image(self, _path: str) -> "FakeResult":
        """模拟 ``file_image``：标记为图片结果并返回自身以支持链式调用."""
        self.kind = "image"
        return self

    def message(self, text: str) -> "FakeResult":
        """模拟 ``message``：记录文本并返回自身以支持链式调用."""
        self.text = text
        return self


class FakeImage:
    """最小 ``Image`` 桩件，``fromFileSystem`` 返回自身."""

    # 显式声明：``fromFileSystem`` 会写入该属性，便于命令层测试断言
    path: str

    def __init__(self, *args, **kwargs) -> None:
        """记录构造参数，便于断言组件被如何创建."""
        self.args = args
        self.kwargs = kwargs

    @classmethod
    def fromFileSystem(cls, path: str, **_kw) -> "FakeImage":  # noqa: N802
        """模拟 ``Image.fromFileSystem``，返回带 path 的桩件实例."""
        inst = cls(path)
        inst.path = path
        return inst


class FakePlain(FakeImage):
    """最小 ``Plain`` 桩件."""


class _FakeContext:
    """最小 Star Context 桩件."""


class _FakeStar:
    """最小 ``Star`` 基类桩件."""

    def __init__(self, *a, **k) -> None:
        pass


class _FakeStarTools:
    """最小 ``StarTools`` 桩件：数据目录可注入，默认落到临时目录."""

    _data_dir = "/tmp/astrbot-test"

    @classmethod
    def get_data_dir(cls, *_a, **_k):
        return Path(cls._data_dir)


def _noop(*_a, **_k):
    def deco(func):
        return func

    return deco


class _CommandGroup:
    """指令组桩件：同时可被调用（``@filter.command_group("x")``）且带装饰器属性.

    ``command_group`` 的用法是「先当函数调用拿到组对象，再用组对象的
    ``command`` 装饰方法」，所以这里既要支持 ``_CommandGroup(*args)``，
    又要让实例上的任意属性（``command`` / ``group``）都是直通装饰器。
    """

    def __init__(self, *a, **k) -> None:
        pass

    def __getattr__(self, _k):
        return _noop


class _FakeFilter:
    """最小 ``filter`` 门面：装饰器原样返回函数."""

    llm_tool = staticmethod(_noop)
    command_group = staticmethod(lambda *a, **k: _CommandGroup)
    command = staticmethod(_noop)


# 兼容 ``from astrbot.api.event import filter as filter_cmd`` 后
# 既用 ``filter.llm_tool`` 又用 ``filter_cmd.command_group`` 的写法：
# 把同一门面同时挂到 filter 模块属性上（模块属性即 filter 对象本身）。
setattr(_FakeFilter, "filter", _FakeFilter)


def ensure_host() -> None:
    """确保 ``astrbot`` 宿主包可导入（幂等，仅缺失时安装桩件）.

    判定缺失必须精确到 ``ModuleNotFoundError.name``：只有宿主包本身或其
    预期子模块缺失才安装桩件；其余缺失（宿主已装但内部依赖不全）原样抛出，
    避免测试退化到「跑在假环境上」。
    """
    try:
        import astrbot.api.event.filter  # noqa: F401

        return
    except ModuleNotFoundError as exc:
        if exc.name not in _HOST_PACKAGE_MODULES:
            raise

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

    class _FakeEvent:
        def get_sender_id(self):
            return "user-1"

        @staticmethod
        def plain_result(text):
            r = FakeResult()
            r.text = text
            return r

    _set(mod_filter, "filter", _FakeFilter)
    # attach module-level decorators used as ``filter_cmd.xxx``
    _set(mod_filter, "command_group", _FakeFilter.command_group)
    _set(mod_filter, "llm_tool", _FakeFilter.llm_tool)
    _set(pkg_api, "logger", _NullLogger())
    _set(mod_event, "AstrMessageEvent", _FakeEvent)
    _set(mod_msg, "Image", FakeImage)
    _set(mod_msg, "Plain", FakePlain)
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


def run(coro):
    """在独立事件循环中跑完协程，结束后关闭循环释放资源."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
