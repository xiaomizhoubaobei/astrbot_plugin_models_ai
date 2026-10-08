"""千问云（万相 / Qwen-Image / Z-Image）文生图模型能力配置模块.

集中声明每个模型的调用方式与支持的参数范围，避免在业务代码里散落大量 if 分支。

官方文档（本表字段口径均取自线上文档，2026-01 核对）：

- 万相 V2 创建任务：
  https://platform.qianwenai.com/docs/api-reference/image-generation/wan-text-to-image-v2/create-task
- 万相 V2 查询结果（含轮询策略与响应格式差异）：
  https://platform.qianwenai.com/docs/api-reference/image-generation/wan-text-to-image-v2/query-result
- 万相 V2 同步调用：
  https://platform.qianwenai.com/docs/api-reference/image-generation/wan-text-to-image-v2/synchronous
- Z-Image（轻量快速图像生成）：
  https://platform.qianwenai.com/docs/api-reference/image-generation/z-image
- 文生图总览（Qwen-Image / Wan 的端点、参数与尺寸口径）：
  https://platform.qianwenai.com/docs/developer-guides/image-generation/text-to-image
- Qwen-Image 同步调用（multimodal-generation 端点 + choices 结果格式）：
  https://platform.qianwenai.com/docs/api-reference/image-generation/qwen-text-to-image

接口形态上有两个易错点，本表用 ``endpoint`` 与 ``response_format`` 显式区分：

1. **端点不同**：万相 2.6 与 Z-Image 走 ``multimodal-generation/generation``（messages
   数组传提示词）；万相 2.5 及更早版本走 ``text2image/image-synthesis``（prompt 字符串）。
   若统一用一个端点提交，老模型一定报错。
2. **结果格式不同**：万相 2.6 的结果在 ``output.choices[].message.content[].image``；
   万相 2.5 及更早版本的结果在 ``output.results[].url``。轮询时两种都要能解析。
"""

from dataclasses import dataclass

# 端点常量：与官方文档给出的路径逐字一致，避免拼写漂移
ENDPOINT_MULTIMODAL = "/services/aigc/multimodal-generation/generation"
ENDPOINT_TEXT2IMAGE = "/services/aigc/text2image/image-synthesis"
ENDPOINT_TASK = "/tasks/{task_id}"


@dataclass(frozen=True)
class QianwenModelSpec:
    """千问云文生图模型的调用能力描述.

    Attributes:
        endpoint: 提交任务使用的路径，取值见 ``ENDPOINT_MULTIMODAL`` / ``ENDPOINT_TEXT2IMAGE``
        call_mode: 调用模式，"sync" 表示一次请求直接返回图片，
            "async" 表示需要提交任务后轮询 ``ENDPOINT_TASK``
        response_format: 成功响应的结果格式，"choices" 表示
            ``output.choices[].message.content[].image``，
            "results" 表示 ``output.results[].url``
        default_size: 该模型的默认尺寸，格式为「宽*高」
        min_side: 单边最小像素值；固定档模型填 0
        max_side: 单边最大像素值；固定档模型填 0
        fixed_sizes: 仅接受这些固定档分辨率；为 None 时表示支持范围内任意尺寸
        supports_negative_prompt: 是否支持负面提示词
        supports_prompt_extend: 是否支持提示词自动改写
        max_prompt_length: 提示词最大字符数，超长时截断（0 表示不限制）
    """

    endpoint: str
    call_mode: str
    response_format: str
    default_size: str
    min_side: int
    max_side: int
    supports_negative_prompt: bool
    supports_prompt_extend: bool
    fixed_sizes: tuple[str, ...] | None = None
    max_prompt_length: int = 0

    def supports_size(self, size: str) -> bool:
        """判断给定尺寸是否被该模型接受.

        Args:
            size: 待检查的尺寸字符串，格式为「宽*高」

        Returns:
            True 表示可以直接使用该尺寸
        """
        parts = size.split("*")
        if len(parts) != 2:
            return False
        width_str, height_str = parts
        if not (width_str.isdigit() and height_str.isdigit()):
            return False
        width, height = int(width_str), int(height_str)

        # 固定档模型必须精确命中预设分辨率
        if self.fixed_sizes is not None:
            return size in self.fixed_sizes

        # 范围型模型需同时满足单边上下限
        return (
            self.min_side <= width <= self.max_side
            and self.min_side <= height <= self.max_side
        )

    def resolve_size(self, size: str) -> str:
        """将请求尺寸收敛到模型可接受的尺寸.

        当尺寸越界或不在固定档内时，降级为该模型的默认尺寸，
        避免仅因比例参数不合规就导致整次生图失败。

        Args:
            size: 期望的尺寸字符串，格式为「宽*高」

        Returns:
            可直接下发给模型的尺寸字符串
        """
        if size and self.supports_size(size):
            return size
        return self.default_size

    def resolve_prompt(self, prompt: str) -> str:
        """按模型限制截断提示词.

        Args:
            prompt: 原始提示词

        Returns:
            未超过上限时原样返回，超长时按 max_prompt_length 截断
        """
        if self.max_prompt_length and len(prompt) > self.max_prompt_length:
            return prompt[: self.max_prompt_length]
        return prompt


# 各模型能力表：字段口径来自官方文档的「支持的模型 / 参数说明」章节
QIANWEN_MODEL_SPECS: dict[str, QianwenModelSpec] = {
    # ===== Qwen-Image：同步调用，messages 传参，choices 结果格式 =====
    # 官方口径（文生图总览 → 设置输出图像分辨率 / 设置生成图片数量）：
    # - 3.0 系列与 2.1-pro：自定义 512*512 ~ 2048*2048，默认由模型按提示词推荐，
    #   宽高比 1:8 ~ 8:1，n 上限 6，支持 negative_prompt / prompt_extend
    # - 2.0 系列：同为 512*512 ~ 2048*2048，默认 2048*2048(1:1)，n 上限 6
    # - max / plus / 基础版 qwen-image：仅接受固定预设分辨率（1664*928 等 5 档），
    #   n 仅支持 1，默认 1664*928(16:9)（官方图像模型表：最大分辨率 1664×928、最大输出数 1）
    # 注意：3.0 系列与 2.1-pro 无独立「默认尺寸」概念（由模型按提示词推荐），这里取 2K 方图为默认值。
    "qwen-image-3.0-pro": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=2000,
    ),
    "qwen-image-3.0": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=2000,
    ),
    "qwen-image-2.1-pro": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=2000,
    ),
    "qwen-image-2.0-pro": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=2000,
    ),
    "qwen-image-2.0": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=2000,
    ),
    # max / plus：仅支持固定预设分辨率，尺寸越界一律降级为 16:9 默认档
    "qwen-image-max": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="1664*928",
        min_side=0,
        max_side=0,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        fixed_sizes=(
            "1664*928",
            "1472*1104",
            "1328*1328",
            "1104*1472",
            "928*1664",
        ),
        max_prompt_length=2000,
    ),
    "qwen-image-plus": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="1664*928",
        min_side=0,
        max_side=0,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        fixed_sizes=(
            "1664*928",
            "1472*1104",
            "1328*1328",
            "1104*1472",
            "928*1664",
        ),
        max_prompt_length=2000,
    ),
    # 基础版 qwen-image：与 max / plus 同档，仅支持固定预设分辨率，n 仅支持 1
    "qwen-image": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="1664*928",
        min_side=0,
        max_side=0,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        fixed_sizes=(
            "1664*928",
            "1472*1104",
            "1328*1328",
            "1104*1472",
            "928*1664",
        ),
        max_prompt_length=2000,
    ),
    # ===== Z-Image：轻量快速，同步调用，messages 传参 =====
    # 文档：分辨率范围 512x512 ~ 2048x2048，推荐 1024x1024 ~ 1536x1536，提示词上限 800
    "z-image-turbo": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="1024*1024",
        min_side=512,
        max_side=2048,
        supports_negative_prompt=False,
        supports_prompt_extend=True,
        max_prompt_length=800,
    ),
    # ===== 万相 2.6：支持同步与异步两种链路，此处选异步（更稳、可控超时） =====
    # 文档：1280x1280 ~ 1440x1440，宽高比 1:4 ~ 4:1，提示词上限 2100，默认 n=4
    "wan2.6-t2i": QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="async",
        response_format="choices",
        default_size="1280*1280",
        min_side=1280,
        max_side=1440,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=2100,
    ),
    # ===== 万相 2.5：旧端点 + 旧结果格式，提示词走 prompt 字符串 =====
    # 文档：1280x1280 ~ 1440x1440，宽高比 1:4 ~ 4:1，提示词上限 2000
    "wan2.5-t2i-preview": QianwenModelSpec(
        endpoint=ENDPOINT_TEXT2IMAGE,
        call_mode="async",
        response_format="results",
        default_size="1280*1280",
        min_side=1280,
        max_side=1440,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=2000,
    ),
    # ===== 万相 2.2 / 2.1 / wanx2.0：每边 512~1440，最大 1440*1440 =====
    "wan2.2-t2i-plus": QianwenModelSpec(
        endpoint=ENDPOINT_TEXT2IMAGE,
        call_mode="async",
        response_format="results",
        default_size="1024*1024",
        min_side=512,
        max_side=1440,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=500,
    ),
    "wan2.2-t2i-flash": QianwenModelSpec(
        endpoint=ENDPOINT_TEXT2IMAGE,
        call_mode="async",
        response_format="results",
        default_size="1024*1024",
        min_side=512,
        max_side=1440,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=500,
    ),
    "wan2.1-t2i-plus": QianwenModelSpec(
        endpoint=ENDPOINT_TEXT2IMAGE,
        call_mode="async",
        response_format="results",
        default_size="1024*1024",
        min_side=512,
        max_side=1440,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=500,
    ),
    "wan2.1-t2i-turbo": QianwenModelSpec(
        endpoint=ENDPOINT_TEXT2IMAGE,
        call_mode="async",
        response_format="results",
        default_size="1024*1024",
        min_side=512,
        max_side=1440,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=500,
    ),
    "wanx2.0-t2i-turbo": QianwenModelSpec(
        endpoint=ENDPOINT_TEXT2IMAGE,
        call_mode="async",
        response_format="results",
        default_size="1024*1024",
        min_side=512,
        max_side=1440,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        max_prompt_length=800,
    ),
}

# 未登记模型的保守兜底能力：按异步 + 旧端点处理，取最低的安全范围，
# 确保将来线上新增模型名时不会直接崩溃，而是安全降级并给出可诊断的报错。
_FALLBACK_SPEC = QianwenModelSpec(
    endpoint=ENDPOINT_TEXT2IMAGE,
    call_mode="async",
    response_format="results",
    default_size="1024*1024",
    min_side=512,
    max_side=1440,
    supports_negative_prompt=True,
    supports_prompt_extend=True,
    max_prompt_length=500,
)


def get_model_spec(model: str) -> QianwenModelSpec:
    """获取指定模型的能力描述.

    Args:
        model: 模型名称

    Returns:
        对应的能力描述；未登记的模型返回保守的兜底配置
    """
    return QIANWEN_MODEL_SPECS.get(model, _FALLBACK_SPEC)


def is_supported_model(model: str) -> bool:
    """判断模型是否已在能力表中登记.

    Args:
        model: 模型名称

    Returns:
        True 表示已登记（可直接使用）
    """
    return model in QIANWEN_MODEL_SPECS


def is_async_model(model: str) -> bool:
    """判断该模型是否需要走异步任务链路.

    Args:
        model: 模型名称

    Returns:
        True 表示需要提交任务并轮询结果
    """
    return get_model_spec(model).call_mode == "async"


def list_supported_models() -> list[str]:
    """列出所有已登记模型名称.

    Returns:
        已登记模型名称列表
    """
    return list(QIANWEN_MODEL_SPECS.keys())
