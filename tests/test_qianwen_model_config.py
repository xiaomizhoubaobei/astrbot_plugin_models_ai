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
    """字符口径模型：超过 max_prompt_length 时按字符精确截断；未超时原样返回."""
    spec = mc.get_model_spec("wan2.6-t2i")  # 字符口径，上限 2100
    assert spec.prompt_limit_mode == mc.PROMPT_LIMIT_CHARS
    long_prompt = "字" * 2500
    assert len(spec.resolve_prompt(long_prompt)) == 2100
    short = "一个女孩"
    assert spec.resolve_prompt(short) == short


def test_prompt_limit_mode_is_declared_per_model() -> None:
    """上限计法必须按模型分别声明，不得全表一个数字了事.

    官方两代模型口径不同：3.0 系列 / 2.1-pro 与万相按「字符」计，
    2.0 系列 / max / plus / 基础版 / z-image 按「token」计。
    """
    char_models = {
        "wan2.6-t2i": 2100,
        "wan2.5-t2i-preview": 2000,
        "wan2.2-t2i-plus": 500,
        "wan2.1-t2i-turbo": 500,
        "wanx2.0-t2i-turbo": 800,
    }
    # 官方同步接口按 token 计并分三档：3.0 系列/2.1-pro 4500、2.0 系列 1300、其余 800
    token_models = {
        "qwen-image-3.0-pro": 4500,
        "qwen-image-3.0": 4500,
        "qwen-image-2.1-pro": 4500,
        "qwen-image-2.1-turbo": 1300,
        "qwen-image-2.0-pro": 1300,
        "qwen-image-2.0": 1300,
        "qwen-image-2.0-pro-2026-06-22": 1300,
        "qwen-image-2.0-pro-2026-04-22": 1300,
        "qwen-image-2.0-pro-2026-03-03": 1300,
        "qwen-image-2.0-2026-03-03": 1300,
        "qwen-image-max": 800,
        "qwen-image-plus": 800,
        "qwen-image": 800,
        "z-image-turbo": 800,
    }
    for name, limit in char_models.items():
        spec = mc.get_model_spec(name)
        assert spec.prompt_limit_mode == mc.PROMPT_LIMIT_CHARS, name
        assert spec.max_prompt_length == limit, name
    for name, limit in token_models.items():
        spec = mc.get_model_spec(name)
        assert spec.prompt_limit_mode == mc.PROMPT_LIMIT_TOKENS, name
        assert spec.max_prompt_length == limit, name
    # 兜底同样声明计法，且取最严口径
    fallback = mc.get_model_spec("不存在的模型")
    assert fallback.prompt_limit_mode == mc.PROMPT_LIMIT_CHARS
    assert fallback.max_prompt_length == 500


def test_estimate_prompt_tokens_is_conservative() -> None:
    """token 估算：CJK 按 1 字 1 token，其余按 4 字符 1 token 向上取整."""
    spec = mc.get_model_spec("z-image-turbo")
    assert spec.estimate_prompt_tokens("") == 0
    # 4 个中文字 -> 4 token
    assert spec.estimate_prompt_tokens("一二三四") == 4
    # 8 个西文字符 -> 2 token
    assert spec.estimate_prompt_tokens("abcdefgh") == 2
    # 5 个西文字符 -> 向上取整为 2 token（宁可高估，避免触发上游 400）
    assert spec.estimate_prompt_tokens("abcde") == 2
    # 中英混排：2 个中文 + 4 个西文 = 2 + 1 = 3
    assert spec.estimate_prompt_tokens("中文abcd") == 3


def test_resolve_prompt_token_mode_truncates_by_estimate() -> None:
    """token 口径模型：按估算 token 截断，且截断后估算值必须不超上限."""
    spec = mc.get_model_spec("z-image-turbo")  # token 口径，上限 800
    assert spec.prompt_limit_mode == mc.PROMPT_LIMIT_TOKENS

    long_prompt = "字" * 2000  # 约 2000 token，远超 800
    trimmed = spec.resolve_prompt(long_prompt)
    assert spec.estimate_prompt_tokens(trimmed) <= 800
    assert len(trimmed) == 800  # 中文 1 字 1 token，正好截到 800 字

    # 未超限则原样返回，不得无故截断
    short = "一只在草地上奔跑的柯基犬"
    assert spec.resolve_prompt(short) == short

    # 同一模型下，纯西文能容纳的字符数远多于中文（这正是不能用字符口径卡 token 模型的证据）
    english = "a" * 4000  # 约 1000 token，超过 800
    trimmed_en = spec.resolve_prompt(english)
    assert spec.estimate_prompt_tokens(trimmed_en) <= 800
    assert len(trimmed_en) > 800


def test_resolve_prompt_no_limit_when_zero() -> None:
    """max_prompt_length=0 表示不限制，无论哪种计法都不得截断."""
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
    assert mc.is_supported_model("qwen-image-3.0-pro") is True
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
        "qwen-image-3.0-pro",
        "qwen-image-3.0",
        "qwen-image-2.1-pro",
        "qwen-image-2.1-turbo",
        "qwen-image-2.0-pro",
        "qwen-image-2.0",
        "qwen-image-2.0-pro-2026-06-22",
        "qwen-image-2.0-pro-2026-04-22",
        "qwen-image-2.0-pro-2026-03-03",
        "qwen-image-2.0-2026-03-03",
        "qwen-image-max",
        "qwen-image-plus",
        "qwen-image",
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
    """Qwen-Image / 万相 2.6 / z-image 走 messages 端点，旧模型走 prompt 端点."""
    for name in ("qwen-image-3.0-pro", "qwen-image-2.0", "qwen-image"):
        assert mc.get_model_spec(name).endpoint == mc.ENDPOINT_MULTIMODAL, name
        assert mc.get_model_spec(name).response_format == "choices", name
    assert mc.get_model_spec("wan2.6-t2i").endpoint == mc.ENDPOINT_MULTIMODAL
    assert mc.get_model_spec("wan2.6-t2i").response_format == "choices"
    assert mc.get_model_spec("wan2.5-t2i-preview").endpoint == mc.ENDPOINT_TEXT2IMAGE
    assert mc.get_model_spec("wan2.5-t2i-preview").response_format == "results"


def test_qwen_image_range_models_support_sync_and_size() -> None:
    """Qwen-Image 范围型（3.0 / 2.1-pro / 2.0）应同步、512~2048、支持双参数."""
    for name in (
        "qwen-image-3.0-pro",
        "qwen-image-3.0",
        "qwen-image-2.1-pro",
        "qwen-image-2.1-turbo",
        "qwen-image-2.0-pro",
        "qwen-image-2.0",
        "qwen-image-2.0-pro-2026-06-22",
        "qwen-image-2.0-pro-2026-04-22",
        "qwen-image-2.0-pro-2026-03-03",
        "qwen-image-2.0-2026-03-03",
    ):
        spec = mc.get_model_spec(name)
        assert spec.call_mode == "sync", name
        assert spec.endpoint == mc.ENDPOINT_MULTIMODAL, name
        assert spec.response_format == "choices", name
        assert spec.min_side == 512 and spec.max_side == 2048, name
        assert spec.supports_prompt_extend is True, name
        assert spec.supports_size("512*512") is True, name
        assert spec.supports_size("2048*2048") is True, name
        assert spec.supports_size("256*256") is False, name
        assert spec.supports_size("4096*4096") is False, name
    # 官方明确 qwen-image-2.1-pro 不支持 negative_prompt，其余范围型模型支持
    for name in (
        "qwen-image-3.0-pro",
        "qwen-image-3.0",
        "qwen-image-2.0-pro",
        "qwen-image-2.0",
    ):
        assert mc.get_model_spec(name).supports_negative_prompt is True, name
    assert mc.get_model_spec("qwen-image-2.1-pro").supports_negative_prompt is False


def test_qwen_image_max_plus_use_fixed_sizes() -> None:
    """max / plus / 基础版 qwen-image 仅接受固定预设分辨率，越界一律降级为 16:9 默认档.

    官方图像模型表将基础版 qwen-image 与 max / plus 同列（最大分辨率 1664×928、
    最大输出数 1），故三者尺寸口径必须一致，不能登记为 512~2048 区间档。
    """
    for name in ("qwen-image-max", "qwen-image-plus", "qwen-image"):
        spec = mc.get_model_spec(name)
        assert spec.call_mode == "sync", name
        assert spec.fixed_sizes is not None, name
        for preset in (
            "1664*928",
            "1472*1104",
            "1328*1328",
            "1104*1472",
            "928*1664",
        ):
            assert spec.supports_size(preset) is True, (name, preset)
        # 范围内但不在固定档 -> 否，并降级为默认 1664*928
        assert spec.supports_size("1024*1024") is False, name
        assert spec.resolve_size("1024*1024") == "1664*928", name
        assert spec.default_size == "1664*928", name


def test_qwen_31_models_enforce_aspect_ratio_and_extras() -> None:
    """官方同步接口：3.0 系列与 2.1-pro 额外限定宽高比 1:8~8:1，并支持 DPE / 思考模式."""
    for name in ("qwen-image-3.0-pro", "qwen-image-3.0", "qwen-image-2.1-pro"):
        spec = mc.get_model_spec(name)
        assert spec.supports_aspect_ratio is True, name
        assert spec.supports_prompt_extend_mode is True, name
        assert spec.supports_enable_thinking is True, name
        # 单边都在范围内，但比例越界（>8:1）仍应判否
        assert spec.supports_size("2048*128") is False, name
        # 8:1 与短边下限 512 同时满足才放行（512*4096 超出长边上限故仍判否）
        assert spec.supports_size("1536*192") is False, name
        assert spec.supports_size("2048*512") is True, name
    # 2.0 系列不施加宽高比约束，只按单边范围判定：
    # 2048*512 两边都在 [512, 2048] 内，比例 4:1 也合法，两代模型同样放行
    spec2 = mc.get_model_spec("qwen-image-2.0")
    assert spec2.supports_aspect_ratio is False
    assert spec2.supports_prompt_extend_mode is False
    assert spec2.supports_enable_thinking is False
    assert spec2.supports_size("2048*512") is True


def test_aspect_ratio_violation_returns_false() -> None:
    """宽高比越界必须走「比例判否」分支，且该分支确实可达.

    官方对 3.0 系列与 2.1-pro 限定宽高比 1:8 ~ 8:1。单边区间 512~2048
    取值时最大比值仅 4:1，永远落不到该分支，所以这里直接改小
    ``max_side``，构造「两边都在区间内、但比值 16:1 越界」的输入，
    确保这条 return 不是摆设（改小上限只影响本用例的局部替身，
    不污染线上能力表）。
    """
    base = mc.get_model_spec("qwen-image-3.0-pro")
    assert base.supports_aspect_ratio is True
    # 两边都 <= 2048，但 2048/128 = 16:1 超出 8:1，只有比例校验能拦住
    spec = mc.QianwenModelSpec(
        endpoint=base.endpoint,
        call_mode=base.call_mode,
        response_format=base.response_format,
        default_size=base.default_size,
        min_side=128,
        max_side=2048,
        supports_negative_prompt=base.supports_negative_prompt,
        supports_prompt_extend=base.supports_prompt_extend,
        supports_aspect_ratio=True,
    )
    assert spec.supports_size("2048*128") is False
    # 对称方向（128:2048 即 1:16）同样判否
    assert spec.supports_size("128*2048") is False
    # 边界内侧（256*2048 = 8:1）仍应放行，确保判否不是「一律拒绝」
    assert spec.supports_size("2048*256") is True
    assert spec.supports_size("256*2048") is True


def test_resolve_negative_prompt_truncates_at_500() -> None:
    """官方限制 negative_prompt 最多 500 字符，本地先截断再下发."""
    spec = mc.get_model_spec("qwen-image-3.0-pro")
    assert mc.MAX_NEGATIVE_PROMPT_LENGTH == 500
    long_prompt = "低" * 900
    assert len(spec.resolve_negative_prompt(long_prompt)) == 500
    short = "低质量, 模糊"
    assert spec.resolve_negative_prompt(short) == short


def test_new_qwen_snapshot_models_are_registered() -> None:
    """官方同步接口列出的日期快照与 2.1-turbo 必须登记，否则会被回退成默认模型."""
    for name in (
        "qwen-image-2.1-turbo",
        "qwen-image-2.0-pro-2026-06-22",
        "qwen-image-2.0-pro-2026-04-22",
        "qwen-image-2.0-pro-2026-03-03",
        "qwen-image-2.0-2026-03-03",
    ):
        assert mc.is_supported_model(name) is True, name
        spec = mc.get_model_spec(name)
        assert spec.endpoint == mc.ENDPOINT_MULTIMODAL, name
        assert spec.call_mode == "sync", name
        assert spec.response_format == "choices", name
