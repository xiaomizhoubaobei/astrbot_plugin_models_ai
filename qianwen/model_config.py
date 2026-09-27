"""千问云文生图模型能力配置模块.

集中声明每个模型的调用方式与支持的参数范围，避免在业务代码里散落大量 if 分支。

官方文档：https://platform.qianwenai.com/docs/developer-guides/image-generation/text-to-image
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class QianwenModelSpec:
    """千问文生图模型的调用能力描述.

    Attributes:
        call_mode: 调用模式，"sync" 表示一次请求直接返回图片，
            "async" 表示需要提交任务后轮询 task_status
        default_size: 该模型的默认尺寸，格式为「宽*高」
        min_side: 单边最小像素值，固定档模型填 0
        max_side: 单边最大像素值，固定档模型填 0
        max_n: 单次请求允许的最大生成数量
        supports_negative_prompt: 是否支持负面提示词
            （官方文档：wan2.7-image-pro / wan2.7-image 不支持）
        supports_prompt_extend: 是否支持提示词自动改写
            （官方文档：wan2.7-image-pro / wan2.7-image 不支持）
        prompt_field: 提示词传入位置，"messages" 表示走 input.messages，
            "prompt" 表示走 input.prompt（Wan 2.5 及更早版本）
        fixed_sizes: 仅接受这些固定档分辨率；为 None 时表示支持范围内任意尺寸
    """

    call_mode: str
    default_size: str
    min_side: int
    max_side: int
    max_n: int
    supports_negative_prompt: bool
    supports_prompt_extend: bool
    prompt_field: str = "messages"
    fixed_sizes: tuple[str, ...] | None = None

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
        避免因比例参数导致整次生图失败。

        Args:
            size: 期望的尺寸字符串，格式为「宽*高」

        Returns:
            可直接下发给模型的尺寸字符串
        """
        if size and self.supports_size(size):
            return size
        return self.default_size


# 各模型的详细能力，字段口径均来自官方文档「设置输出图像分辨率 / 设置生成图片数量」
QIANWEN_MODEL_SPECS: dict[str, QianwenModelSpec] = {
    # ===== Qwen-Image 系列：同步调用 =====
    "qwen-image-3.0-pro": QianwenModelSpec(
        call_mode="sync",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        max_n=6,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
    ),
    "qwen-image-3.0": QianwenModelSpec(
        call_mode="sync",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        max_n=6,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
    ),
    "qwen-image-2.0-pro": QianwenModelSpec(
        call_mode="sync",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        max_n=6,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
    ),
    "qwen-image-2.0": QianwenModelSpec(
        call_mode="sync",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        max_n=6,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
    ),
    # plus / max 仅支持固定档分辨率，且单次只能生成 1 张
    "qwen-image-plus": QianwenModelSpec(
        call_mode="sync",
        default_size="1664*928",
        min_side=0,
        max_side=0,
        max_n=1,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        fixed_sizes=(
            "1664*928",
            "1472*1104",
            "1328*1328",
            "1104*1472",
            "928*1664",
        ),
    ),
    "qwen-image-max": QianwenModelSpec(
        call_mode="sync",
        default_size="1664*928",
        min_side=0,
        max_side=0,
        max_n=1,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        fixed_sizes=(
            "1664*928",
            "1472*1104",
            "1328*1328",
            "1104*1472",
            "928*1664",
        ),
    ),
    "qwen-image": QianwenModelSpec(
        call_mode="sync",
        default_size="1328*1328",
        min_side=512,
        max_side=2048,
        max_n=4,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        fixed_sizes=(
            "1664*928",
            "1472*1104",
            "1328*1328",
            "1104*1472",
            "928*1664",
        ),
    ),
    # ===== Wan 系列：异步调用 =====
    # 官方文档：wan2.7-image-pro / wan2.7-image 不支持 negative_prompt 与 prompt_extend
    "wan2.7-image-pro": QianwenModelSpec(
        call_mode="async",
        default_size="2048*2048",
        min_side=768,
        max_side=4096,
        max_n=4,
        supports_negative_prompt=False,
        supports_prompt_extend=False,
    ),
    "wan2.7-image": QianwenModelSpec(
        call_mode="async",
        default_size="2048*2048",
        min_side=768,
        max_side=2048,
        max_n=4,
        supports_negative_prompt=False,
        supports_prompt_extend=False,
    ),
    "wan2.6-image": QianwenModelSpec(
        call_mode="async",
        default_size="1024*1024",
        min_side=768,
        max_side=1280,
        max_n=4,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
    ),
    "wan2.6-t2i": QianwenModelSpec(
        call_mode="async",
        default_size="1280*1280",
        min_side=1280,
        max_side=1440,
        max_n=4,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
    ),
    # Wan 2.5 及更早版本使用 input.prompt 传入提示词
    "wan2.5-t2i-preview": QianwenModelSpec(
        call_mode="async",
        default_size="1280*1280",
        min_side=1280,
        max_side=1440,
        max_n=4,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        prompt_field="prompt",
    ),
    "wan2.2-t2i": QianwenModelSpec(
        call_mode="async",
        default_size="1024*1024",
        min_side=512,
        max_side=1440,
        max_n=4,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        prompt_field="prompt",
    ),
}

# 未登记模型的保守兜底能力：按同步调用处理，取最低的安全范围，
# 确保将来新增模型名不会直接崩溃，而是安全降级。
_FALLBACK_SPEC = QianwenModelSpec(
    call_mode="sync",
    default_size="1024*1024",
    min_side=512,
    max_side=2048,
    max_n=1,
    supports_negative_prompt=True,
    supports_prompt_extend=True,
)


def get_model_spec(model: str) -> QianwenModelSpec:
    """获取指定模型的能力描述.

    Args:
        model: 模型名称

    Returns:
        对应的能力描述；未登记的模型返回保守的兜底配置
    """
    return QIANWEN_MODEL_SPECS.get(model, _FALLBACK_SPEC)


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
