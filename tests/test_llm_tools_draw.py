"""LLM 生图工具单元测试.

覆盖 ``llm_tools/draw.py`` 的分支：未声明参数吸收、非字符串提示词归一化、
防抖 / 并发拦截、参数解析失败、成功直发图片、生图异常回传 LLM。
"""

from _plugin_harness import FakeResult, ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.llm_tools.draw import draw_image_tool  # noqa: E402


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

    def __init__(self, raises=None):
        self._raises = raises
        self.calls = []

    async def generate_image(self, prompt, size=""):
        self.calls.append((prompt, size))
        if self._raises:
            raise self._raises
        return "/tmp/fake.png"


class Plugin:
    def __init__(self, rate_limiter=None, client=None):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.api_client = client or Client()
        self.logs = []

    def debug_log(self, msg):
        self.logs.append(msg)


class Event:
    def __init__(self):
        self.sent = 0

    def get_sender_id(self):
        return "u1"

    def plain_result(self, text):
        r = FakeResult()
        r.text = text
        return r

    def make_result(self):
        return FakeResult()

    async def send(self, _r):
        self.sent += 1


def _collect(plugin, event, prompt, **kw):
    async def _drive():
        return [item async for item in draw_image_tool(plugin, event, prompt, **kw)]

    return run(_drive())


def test_draw_success_returns_image_message() -> None:
    """成功时产出一条图片消息，并发送进度提示."""
    plugin = Plugin()
    event = Event()
    out = _collect(plugin, event, "一只猫 9:16")
    assert out
    assert plugin.api_client.calls == [("一只猫", "576x1024")]
    assert event.sent == 1
    assert plugin.rate_limiter.removed == ["u1"]


def test_draw_extra_kwargs_ignored() -> None:
    """未声明的多余参数被吸收并记录，不中断生图."""
    plugin = Plugin()
    event = Event()
    out = _collect(plugin, event, "一只猫", use_refs=True, foo="bar")
    assert out
    assert any("忽略未声明参数" in m for m in plugin.logs)


def test_draw_non_string_prompt_normalized_to_str() -> None:
    """非字符串提示词被 str 归一化（数字可正常生图）."""
    plugin = Plugin()
    event = Event()
    _collect(plugin, event, 12345)
    assert plugin.api_client.calls == [("12345", "1024x1024")]


def test_draw_none_prompt_yields_error_text() -> None:
    """None 提示词归一化为空串后被参数校验拦截，回传字符串而非抛异常."""
    plugin = Plugin()
    event = Event()
    out = _collect(plugin, event, None)
    assert out and isinstance(out[0], str)
    # 未占用并发名额
    assert plugin.rate_limiter.added == []


def test_draw_debounced() -> None:
    """防抖命中时提示用户，且不调用生图."""
    plugin = Plugin(rate_limiter=RateLimiter(debounce=True))
    event = Event()
    out = _collect(plugin, event, "一只猫")
    assert out and not isinstance(out[0], str)
    assert plugin.api_client.calls == []


def test_draw_processing_rejected() -> None:
    """并发处理中时拒绝新请求."""
    plugin = Plugin(rate_limiter=RateLimiter(processing=True))
    event = Event()
    out = _collect(plugin, event, "一只猫")
    assert out
    assert plugin.api_client.calls == []


def test_draw_param_parse_failure_yields_str() -> None:
    """参数解析失败回传字符串（不占用并发名额）."""
    plugin = Plugin()
    event = Event()
    out = _collect(plugin, event, "9:16 9:16")
    # 该输入实际可解析，故这里仅断言不抛异常且产出一条结果
    assert out
    # 用一个真正非法的提示词（纯空白）验证失败分支
    plugin2 = Plugin()
    out2 = _collect(plugin2, event, "   ")
    assert out2 and isinstance(out2[0], str)
    assert plugin2.rate_limiter.added == []


def test_draw_generate_failure_returns_str() -> None:
    """生图异常时回传字符串给 LLM，并释放并发名额."""
    plugin = Plugin(client=Client(raises=RuntimeError("boom")))
    event = Event()
    out = _collect(plugin, event, "一只猫")
    assert out and isinstance(out[0], str)
    assert "生成图片时遇到问题" in out[0]
    assert plugin.rate_limiter.removed == ["u1"]
