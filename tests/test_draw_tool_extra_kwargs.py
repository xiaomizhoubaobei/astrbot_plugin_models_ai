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
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 覆盖率运行环境：按顶层包名 `astrbot_plugin_models_ai` 可导入插件源码，
# 保证 coverage / pytest-cov 能按真实源码路径统计行覆盖（详见该模块文档）
from _coverage_support import ensure_package_view  # noqa: E402

ensure_package_view()


# 桩件兜底时**允许缺失**的模块名：只有"宿主包本身或其预期目标模块缺失"，
# 才判定为"环境未装宿主"、可以安装桩件；其余缺失一律原样抛出。
_HOST_PACKAGE_MODULES = frozenset({"astrbot", "astrbot.api.event.filter"})


def _install_astrbot_stubs() -> None:
    """安装最小 ``astrbot`` 桩件，使插件模块可在无宿主环境导入.

    宿主 / CI 已提供完整 astrbot 时直接返回；仅在其缺失时兜底安装，
    避免因环境差异导致本回归测试无法运行。

    判定"缺失"必须精确到 ``ModuleNotFoundError.name``，只放行两类情况：

    * ``astrbot`` / ``astrbot.api.event.filter`` 缺失 → 环境确实没装宿主，
      安装桩件兜底（本函数存在的意义）；
    * 其它模块名缺失 → 宿主**已安装**（或路径可达）但内部/传递依赖缺失，
      属真实环境问题，**必须原样抛出**，不得被桩件静默掩盖；
    * 非 ``ModuleNotFoundError`` 的导入错误（宿主包内部报错等）同样原样抛出。

    这样可同时挡住「其它异常类型」与「宿主依赖缺失」两类误吞，
    避免测试退化为"跑在假环境上"。
    """
    try:
        import astrbot.api.event.filter  # noqa: F401

        return
    except ModuleNotFoundError as exc:
        # 只有宿主包本身或其预期目标模块缺失，才允许走桩件兜底；
        # 其它缺失（宿主已装、但内部依赖不全）必须向上抛出
        if exc.name not in _HOST_PACKAGE_MODULES:
            raise

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
    """在独立事件循环中跑完协程，并在结束时关闭循环.

    每次调用都新建循环；若不关闭会残留未回收的循环资源，
    在批量/重复执行测试时可能触发 unclosed event loop 告警并累积句柄。
    因此统一在 finally 中关闭循环，保证资源即时释放。
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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


class _BlockedImport:
    """临时拦截指定模块的导入，模拟"宿主已装但内部依赖缺失/报错"场景.

    通过 meta_path finder 精确拦截 ``module_name``（含其子模块），
    在不改动真实环境的前提下构造出可控的导入失败。
    """

    def __init__(self, module_name: str, exc: BaseException) -> None:
        self.module_name = module_name
        self.exc = exc

    def find_module(self, fullname, _path=None):  # pragma: no cover - 兼容老接口
        return self if self._hit(fullname) else None

    def find_spec(self, fullname, _path=None, _target=None):  # pragma: no cover
        if self._hit(fullname):
            raise self.exc
        return None

    def _hit(self, fullname: str) -> bool:
        return fullname == self.module_name or fullname.startswith(
            self.module_name + "."
        )


@pytest.mark.parametrize(
    "exc",
    [
        ModuleNotFoundError(
            "No module named 'some_missing_dep'", name="some_missing_dep"
        ),
        ModuleNotFoundError(
            "No module named 'astrbot.api.nope'", name="astrbot.api.nope"
        ),
        RuntimeError("宿主包内部初始化失败"),
    ],
    ids=["传递依赖缺失", "宿主包内其它子模块缺失", "宿主包内部报错"],
)
def test_stub_fallback_is_not_triggered_by_broken_host(exc, monkeypatch) -> None:
    """宿主已装但导入失败时，桩件**不得**兜底，异常必须原样抛出.

    否则真实环境问题会被静默顶替成桩件，测试退化为"跑在假环境上"。
    """
    import test_draw_tool_extra_kwargs as t

    # 让"探测性导入"真的重新走一次，而不是命中 sys.modules 缓存
    monkeypatch.delitem(sys.modules, "astrbot.api.event.filter", raising=False)
    monkeypatch.setattr(
        sys, "meta_path", [_BlockedImport("astrbot", exc), *sys.meta_path]
    )

    with pytest.raises(type(exc)):
        t._install_astrbot_stubs()


def test_stub_fallback_still_works_when_host_absent(monkeypatch) -> None:
    """宿主确实没装（astrbot 本身缺失）时，仍应安装桩件兜底.

    这条与上一条配对：收紧兜底条件的同时，不能把"无宿主跑单测"的
    既有能力一并砍掉。
    """
    import test_draw_tool_extra_kwargs as t

    monkeypatch.delitem(sys.modules, "astrbot.api.event.filter", raising=False)
    monkeypatch.setattr(
        sys,
        "meta_path",
        [
            _BlockedImport(
                "astrbot",
                ModuleNotFoundError("No module named 'astrbot'", name="astrbot"),
            ),
            *sys.meta_path,
        ],
    )

    # 不应抛出：缺失模块名在白名单内 → 允许安装桩件
    t._install_astrbot_stubs()

    assert "astrbot.api.event.filter" in sys.modules


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
