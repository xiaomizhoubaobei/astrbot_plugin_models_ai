"""命令层单元测试.

覆盖 ``commands/`` 下六个命令处理函数的分支：

- ``generate``：空提示词、防抖 / 并发、参数解析失败、成功出图、异常回包；
- ``style``：空风格名、风格不存在、文生图 / 图生图两条链路、参数解析失败；
- ``ai_edit``：空提示词、缺图片、成功编辑、异常；
- ``text2image``：防抖、成功列表、下游失败；
- ``switch_model``：空名称、千问云模型校验、成功切换；
- ``help``：gitee 与 qianwen 两套帮助文案。

统一用轻量桩件驱动异步生成器，避免依赖真实 AstrBot 运行时。
"""

import pytest
from _plugin_harness import FakeResult, ensure_host, run  # noqa: E402

ensure_host()

# 说明：命令层在防抖/并发命中时会 return 提前退出上游 ``check_rate_limit``，
# 使该内层异步生成器未被完全消费，解释器回收时报「aclose never awaited」。
# 这是生产代码既有的轻微资源回收问题，非本测试引入，故在此按已知告警过滤，
# 避免掩盖其它真实告警（仅匹配这一条消息）。
pytestmark = pytest.mark.filterwarnings(
    "ignore:coroutine method 'aclose' of 'check_rate_limit' was never awaited"
)

from astrbot_plugin_models_ai.commands import (  # noqa: E402
    ai_edit_image_command,
    generate_image_command,
    help_command,
    list_models_command,
    style_command,
    switch_model_command,
)


class RateLimiter:
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


class Client:
    supported_ratios = {"1:1": ["1024x1024"], "9:16": ["576x1024"]}
    default_size = "1024x1024"

    def __init__(self, raises=None, edit_raises=None):
        self._raises = raises
        self._edit_raises = edit_raises
        self.generate_calls = []
        self.edit_calls = []
        self.model = "z-image-turbo"

    async def generate_image(self, prompt, size=""):
        self.generate_calls.append((prompt, size))
        if self._raises:
            raise self._raises
        return "/tmp/gen.png"

    async def edit_image(self, **kwargs):
        self.edit_calls.append(kwargs)
        if self._edit_raises:
            raise self._edit_raises
        return "/tmp/edit.png"


class ModelLister:
    def __init__(self, result=(True, "1. a\n共 1 个模型")):
        self._result = result

    async def list_models(self, type_param=""):
        return self._result


class Plugin:
    def __init__(self, rate_limiter=None, client=None, model_lister=None, config=None):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.api_client = client or Client()
        self.model_lister = model_lister or ModelLister()
        self.config = config or {}
        self.download_image_urls = False
        self.logs = []

    def debug_log(self, msg):
        self.logs.append(msg)


class Event:
    def __init__(self, sender="u1", message_obj=None):
        self._sender = sender
        self.message_obj = message_obj
        self.sent = []

    def get_sender_id(self):
        return self._sender

    def plain_result(self, text):
        r = FakeResult()
        r.text = text
        return r

    def chain_result(self, items):
        r = FakeResult()
        r.kind = "chain"
        r.chain = items
        return r


def _collect(agen):
    """收集异步生成器全部产出.

    命令层在防抖/并发命中时会 ``return`` 提前退出上游 ``check_rate_limit``，
    使该内层生成器未被完全消费——若不显式 ``aclose()``，解释器会在回收时
    报 RuntimeWarning「coroutine ... was never awaited」。这里在收集完成后
    统一关闭生成器，保持测试输出干净。
    """

    async def _drive():
        try:
            return [item async for item in agen]
        finally:
            await agen.aclose()

    return run(_drive())


# ===== generate =====


def test_generate_empty_prompt() -> None:
    plugin = Plugin()
    out = _collect(generate_image_command(plugin, Event(), ""))
    assert out and "请提供提示词" in out[0].text
    assert plugin.rate_limiter.added == []


def test_generate_debounced() -> None:
    plugin = Plugin(rate_limiter=RateLimiter(debounce=True))
    out = _collect(generate_image_command(plugin, Event(), "一只猫"))
    assert out and "太快" in out[0].text


def test_generate_processing() -> None:
    plugin = Plugin(rate_limiter=RateLimiter(processing=True))
    out = _collect(generate_image_command(plugin, Event(), "一只猫"))
    assert out and "正在进行的生图任务" in out[0].text


def test_generate_success() -> None:
    plugin = Plugin()
    out = _collect(generate_image_command(plugin, Event(), "一只猫 9:16"))
    # 进度提示 + 结果链
    assert any(getattr(r, "kind", "") == "chain" for r in out)
    assert plugin.api_client.generate_calls == [("一只猫", "576x1024")]
    assert plugin.rate_limiter.removed == ["u1"]


def test_generate_param_error() -> None:
    plugin = Plugin()
    out = _collect(generate_image_command(plugin, Event(), "   "))
    # 空提示词已在更早分支拦截；用「9:16 9:16」走解析路径无异常，
    # 这里验证参数解析失败分支：仅比例会造成空提示词
    assert out
    assert plugin.rate_limiter.removed == ["u1"]


def test_generate_api_failure() -> None:
    plugin = Plugin(client=Client(raises=RuntimeError("上游挂了")))
    out = _collect(generate_image_command(plugin, Event(), "一只猫"))
    assert any("生成图片失败" in getattr(r, "text", "") for r in out)
    assert plugin.rate_limiter.removed == ["u1"]


# ===== style =====


def test_style_no_name_lists_styles() -> None:
    plugin = Plugin()
    out = _collect(style_command(plugin, Event(), "", ""))
    assert out and "请指定风格名称" in out[0].text


def test_style_unknown_name() -> None:
    plugin = Plugin()
    out = _collect(style_command(plugin, Event(), "不存在的风格xyz", ""))
    assert out and "不存在" in out[0].text


def test_style_text2image_success() -> None:
    """无图片时走文生图链路."""
    plugin = Plugin()
    out = _collect(style_command(plugin, Event(), "手办化", "一个女孩 9:16"))
    assert any(getattr(r, "kind", "") == "chain" for r in out)
    assert plugin.api_client.generate_calls
    # 最终提示词应拼接风格提示词
    final_prompt = plugin.api_client.generate_calls[0][0]
    assert final_prompt.startswith("一个女孩")


def test_style_without_prompt_uses_style_only() -> None:
    """无自定义描述时直接用风格提示词."""
    plugin = Plugin()
    _collect(style_command(plugin, Event(), "手办化", ""))
    assert plugin.api_client.generate_calls


def test_style_image2image_success() -> None:
    """带图片时走编辑链路（edit_image）."""
    from astrbot.api.message_components import Image

    comp = Image()
    comp.path = "/tmp/in.png"
    message_obj = type("M", (), {"message": [comp]})()
    event = Event(message_obj=message_obj)

    plugin = Plugin()
    out = _collect(style_command(plugin, event, "手办化", ""))
    assert plugin.api_client.edit_calls
    assert plugin.api_client.edit_calls[0]["task_types"] == ["style"]
    assert any(getattr(r, "kind", "") == "chain" for r in out)


def test_style_edit_failure() -> None:
    """编辑链路异常时回包失败文案."""
    from astrbot.api.message_components import Image

    comp = Image()
    comp.path = "/tmp/in.png"
    message_obj = type("M", (), {"message": [comp]})()
    event = Event(message_obj=message_obj)
    plugin = Plugin(client=Client(edit_raises=RuntimeError("boom")))
    out = _collect(style_command(plugin, event, "手办化", ""))
    assert any("生成失败" in getattr(r, "text", "") for r in out)


# ===== ai_edit =====


def test_ai_edit_empty_prompt() -> None:
    plugin = Plugin()
    out = _collect(ai_edit_image_command(plugin, Event(), "", ""))
    assert out and "请提供编辑提示词" in out[0].text


def test_ai_edit_no_images() -> None:
    plugin = Plugin()
    out = _collect(ai_edit_image_command(plugin, Event(), "改成油画", ""))
    assert any("请发送要编辑的图片" in getattr(r, "text", "") for r in out)


def test_ai_edit_success() -> None:
    from astrbot.api.message_components import Image

    comp = Image()
    comp.path = "/tmp/in.png"
    message_obj = type("M", (), {"message": [comp]})()
    event = Event(message_obj=message_obj)

    plugin = Plugin()
    out = _collect(ai_edit_image_command(plugin, event, "改成油画", "id"))
    assert plugin.api_client.edit_calls
    assert plugin.api_client.edit_calls[0]["task_types"] == ["id"]
    assert any(getattr(r, "kind", "") == "chain" for r in out)


def test_ai_edit_default_task_type() -> None:
    from astrbot.api.message_components import Image

    comp = Image()
    comp.path = "/tmp/in.png"
    message_obj = type("M", (), {"message": [comp]})()
    event = Event(message_obj=message_obj)
    plugin = Plugin()
    _collect(ai_edit_image_command(plugin, event, "改成油画", ""))
    assert plugin.api_client.edit_calls[0]["task_types"] == ["style"]


def test_ai_edit_failure() -> None:
    from astrbot.api.message_components import Image

    comp = Image()
    comp.path = "/tmp/in.png"
    message_obj = type("M", (), {"message": [comp]})()
    event = Event(message_obj=message_obj)
    plugin = Plugin(client=Client(edit_raises=RuntimeError("boom")))
    out = _collect(ai_edit_image_command(plugin, event, "改成油画", ""))
    assert any("AI 图片编辑失败" in getattr(r, "text", "") for r in out)


# ===== text2image =====


def test_text2image_success() -> None:
    plugin = Plugin()
    out = _collect(list_models_command(plugin, Event(), ""))
    assert any("1. a" in getattr(r, "text", "") for r in out)
    assert plugin.rate_limiter.removed == ["u1"]


def test_text2image_debounced() -> None:
    plugin = Plugin(rate_limiter=RateLimiter(debounce=True))
    out = _collect(list_models_command(plugin, Event(), ""))
    assert out and "太快" in out[0].text


def test_text2image_processing() -> None:
    plugin = Plugin(rate_limiter=RateLimiter(processing=True))
    out = _collect(list_models_command(plugin, Event(), ""))
    assert out and "正在进行的请求" in out[0].text


def test_text2image_failure_result() -> None:
    plugin = Plugin(model_lister=ModelLister(result=(False, "获取模型列表失败: x")))
    out = _collect(list_models_command(plugin, Event(), ""))
    assert any("失败" in getattr(r, "text", "") for r in out)
    assert plugin.rate_limiter.removed == ["u1"]


# ===== switch_model =====


def test_switch_model_empty_name() -> None:
    plugin = Plugin()
    out = _collect(switch_model_command(plugin, Event(), ""))
    assert out and "请提供模型名称" in out[0].text


def test_switch_model_gitee_success() -> None:
    plugin = Plugin(config={"provider": "gitee"})
    out = _collect(switch_model_command(plugin, Event(), "flux-schnell"))
    assert plugin.api_client.model == "flux-schnell"
    assert any("已切换" in getattr(r, "text", "") for r in out)


def test_switch_model_qianwen_rejects_unknown() -> None:
    plugin = Plugin(config={"provider": "qianwen"})
    out = _collect(switch_model_command(plugin, Event(), "flux-schnell"))
    assert any("暂不支持" in getattr(r, "text", "") for r in out)
    # 模型未变
    assert plugin.api_client.model == "z-image-turbo"


def test_switch_model_qianwen_accepts_known() -> None:
    plugin = Plugin(config={"provider": "qianwen"})
    out = _collect(switch_model_command(plugin, Event(), "wan2.6-t2i"))
    assert plugin.api_client.model == "wan2.6-t2i"
    assert any("已切换" in getattr(r, "text", "") for r in out)


# ===== help =====


def test_help_gitee_provider() -> None:
    plugin = Plugin(config={"provider": "gitee"})
    out = _collect(help_command(plugin, Event()))
    assert out and "Gitee AI" in out[0].text
    assert "generate" in out[0].text


def test_help_qianwen_provider() -> None:
    plugin = Plugin(config={"provider": "qianwen"})
    out = _collect(help_command(plugin, Event()))
    assert out and "千问云" in out[0].text


def test_help_without_config_attr() -> None:
    """插件无 config 属性时默认按 gitee 渲染，不报错."""

    class Bare:
        def debug_log(self, _m):
            pass

    out = _collect(help_command(Bare(), Event()))
    assert out and "Gitee AI" in out[0].text
