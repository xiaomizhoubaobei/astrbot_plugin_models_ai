"""千问云模型能力表单元测试.

覆盖 ``qianwen/model_config.py`` 的纯逻辑：字段口径、尺寸校验与降级、
提示词截断、未登记模型的兜底，以及各查询函数。

这些函数是「跨模型差异」的唯一收口点：一旦尺寸/端点判定出错，表现为
线上「某个模型必报错」而不是代码异常，因此用测试把口径钉死。
"""

import pytest
from _plugin_harness import ensure_host  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.qianwen import model_config as mc  # noqa: E402


def test_endpoint_constants_match_official_docs() -> None:
    """端点常量必须与官方文档逐字一致，避免拼写漂移."""
    assert mc.ENDPOINT_MULTIMODAL.startswith("/services/aigc/multimodal-generation")
    assert mc.ENDPOINT_TEXT2IMAGE.startswith("/services/aigc/text2image")
    assert mc.ENDPOINT_TASK == "/tasks/{task_id}"


def test_supported_size_for_range_model() -> None:
    """范围型模型：单边同时落在 [min_side, max_side] 内才接受."""
    spec = mc.get_model_spec("z-image-turbo")
    assert spec.supports_size("1024*1024") is True
    assert spec.supports_size("512*512") is True
    assert spec.supports_size("2048*2048") is True
    # 越界
    assert spec.supports_size("256*256") is False
    assert spec.supports_size("4096*4096") is False
    # 单边越界
    assert spec.supports_size("512*4096") is False


def test_supports_size_rejects_malformed() -> None:
    """非「宽*高」形式一律判否，且不得抛异常."""
    spec = mc.get_model_spec("z-image-turbo")
    for bad in ["", "1024", "1024*", "*1024", "1024x1024", "1024*abc", "a*b"]:
        assert spec.supports_size(bad) is False, bad


def test_supports_size_for_fixed_model() -> None:
    """固定档模型：必须精确命中预设分辨率."""
    spec = mc.QianwenModelSpec(
        endpoint=mc.ENDPOINT_TEXT2IMAGE,
        call_mode="async",
        response_format="results",
        default_size="1024*1024",
        min_side=0,
        max_side=0,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        fixed_sizes=("1024*1024", "1280*1280"),
    )
    assert spec.supports_size("1024*1024") is True
    assert spec.supports_size("1280*1280") is True
    # 落在范围内但不在固定档 -> 否
    assert spec.supports_size("1152*1152") is False


def test_resolve_size_falls_back_to_default() -> None:
    """越界尺寸应降级为默认尺寸，而不是直接失败（避免比例参数不合规就整单失败）."""
    spec = mc.get_model_spec("z-image-turbo")
    assert spec.resolve_size("1024*1024") == "1024*1024"
    assert spec.resolve_size("4096*4096") == spec.default_size
    assert spec.resolve_size("") == spec.default_size


def test_resolve_prompt_truncates_over_limit() -> None:
    """超过 max_prompt_length 时按上限截断；未超时原样返回."""
    spec = mc.get_model_spec("z-image-turbo")  # 上限 800
    long_prompt = "字" * 1000
    assert len(spec.resolve_prompt(long_prompt)) == 800
    short = "一个女孩"
    assert spec.resolve_prompt(short) == short


def test_resolve_prompt_no_limit_when_zero() -> None:
    """max_prompt_length=0 表示不限制，不得截断."""
    spec = mc.QianwenModelSpec(
        endpoint=mc.ENDPOINT_TEXT2IMAGE,
        call_mode="async",
        response_format="results",
        default_size="1024*1024",
        min_side=512,
        max_side=1440,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=0,
    )
    long_prompt = "字" * 5000
    assert spec.resolve_prompt(long_prompt) == long_prompt


def test_model_spec_is_frozen() -> None:
    """能力描述应为不可变对象，防止运行期被意外改写."""
    spec = mc.get_model_spec("z-image-turbo")
    with pytest.raises(Exception):
        spec.default_size = "2048*2048"  # type: ignore[misc]


def test_get_model_spec_unknown_returns_fallback() -> None:
    """未登记模型返回保守兜底，而不是抛 KeyError."""
    spec = mc.get_model_spec("不存在的模型")
    assert spec.call_mode == "async"
    assert spec.response_format == "results"
    assert spec.endpoint == mc.ENDPOINT_TEXT2IMAGE
    # 兜底采用区间下限，确保不会误报「支持」超出范围的分辨率
    assert spec.min_side == 512
    assert spec.max_side == 1440


def test_is_supported_model() -> None:
    """只把能力表里登记过的模型判为支持."""
    assert mc.is_supported_model("z-image-turbo") is True
    assert mc.is_supported_model("wan2.6-t2i") is True
    assert mc.is_supported_model("flux-schnell") is False


def test_is_async_model() -> None:
    """同步/异步链路由 call_mode 决定."""
    assert mc.is_async_model("z-image-turbo") is False  # sync
    assert mc.is_async_model("wan2.6-t2i") is True
    assert mc.is_async_model("wan2.5-t2i-preview") is True
    # 未登记模型走兜底（async）
    assert mc.is_async_model("unknown-model") is True


def test_list_supported_models_contains_known_names() -> None:
    """列表应覆盖文档列出的全部模型，且顺序稳定可复现."""
    models = mc.list_supported_models()
    for expect in [
        "z-image-turbo",
        "wan2.6-t2i",
        "wan2.5-t2i-preview",
        "wan2.2-t2i-plus",
        "wan2.1-t2i-turbo",
        "wanx2.0-t2i-turbo",
    ]:
        assert expect in models
    # 返回值是副本，改动它不应污染原始能力表
    models.append("injected")
    assert "injected" not in mc.list_supported_models()


def test_new_models_use_multimodal_endpoint() -> None:
    """万相 2.6 与 z-image 走 messages 端点，旧模型走 prompt 端点."""
    assert mc.get_model_spec("wan2.6-t2i").endpoint == mc.ENDPOINT_MULTIMODAL
    assert mc.get_model_spec("wan2.6-t2i").response_format == "choices"
    assert mc.get_model_spec("wan2.5-t2i-preview").endpoint == mc.ENDPOINT_TEXT2IMAGE
    assert mc.get_model_spec("wan2.5-t2i-preview").response_format == "results"
