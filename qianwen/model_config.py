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

提示词上限是第三个易错点：官方对「按字符计」与「按 token 计」两代模型分别给出上限，
本表用 ``prompt_limit_mode`` + ``max_prompt_length`` 两个字段共同表达，
禁止再用一个统一的字符数字覆盖所有模型。
"""

from dataclasses import dataclass

# 端点常量：与官方文档给出的路径逐字一致，避免拼写漂移
ENDPOINT_MULTIMODAL = "/services/aigc/multimodal-generation/generation"
ENDPOINT_TEXT2IMAGE = "/services/aigc/text2image/image-synthesis"
ENDPOINT_TASK = "/tasks/{task_id}"

# 提示词上限计法：官方两代模型口径不同，必须按模型分别声明
PROMPT_LIMIT_CHARS = "chars"  # 按「字符」计：可直接用 len() 精确截断
PROMPT_LIMIT_TOKENS = "tokens"  # 按「token」计：本地仅能做保守估算
PROMPT_LIMIT_NONE = "none"  # 无上限


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
        max_prompt_length: 提示词长度上限（0 表示不限制）；计法由
            ``prompt_limit_mode`` 决定
        prompt_limit_mode: 上限计法，取值见 ``PROMPT_LIMIT_CHARS`` /
            ``PROMPT_LIMIT_TOKENS`` / ``PROMPT_LIMIT_NONE``。**必须是三选一**：
            官方对两代模型分别采用「字符」与「token」两种口径，用同一个数字
            套到所有模型上必然错一边（要么误截合法提示词，要么漏放超限提示词）。
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
    # 上限计法：官方对 qwen-image-3.0 系列/2.1-pro 与万相 2.x 按字符计，
    # 对 qwen-image-2.0 系列/max/plus/基础版按 token 计，二者不可混用。
    prompt_limit_mode: str = PROMPT_LIMIT_CHARS

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

    def estimate_prompt_tokens(self, prompt: str) -> int:
        """保守估算提示词对应的 token 数.

        官方对部分模型按 token 而非字符计上限，而本地没有分词器可用，
        因此采用「偏保守」的估算规则，宁可少放几个字符也不触发上游 400：

        - CJK（中日韩）字符：中文字符通常 1 字 ≈ 1 token，按 **1 字/token** 计；
        - 其余字符：英文等常见为 1 token ≈ 4 字符，按 **每 4 字符 1 token** 向上取整。

        两者相加得到估算值，用于 ``resolve_prompt`` 在 token 口径下的截断判定。

        Args:
            prompt: 待估算的提示词

        Returns:
            估算出的 token 数（非精确值，偏保守）
        """
        cjk = 0
        other = 0
        for char in prompt:
            # 覆盖常用 CJK 区间（含中文、日文假名、韩文），按 1 字 1 token 计
            if "\u3040" <= char <= "\u30ff" or "\u3400" <= char <= "\u9fff":
                cjk += 1
            else:
                other += 1
        # 非 CJK 字符按 4 字符 1 token 向上取整，避免低估导致超限
        return cjk + (other + 3) // 4

    def resolve_prompt(self, prompt: str) -> str:
        """按模型限制截断提示词.

        上限计法由 ``prompt_limit_mode`` 决定：``chars`` 按字符精确截断；
        ``tokens`` 按估算 token 数截断（就地二分到估算值不超限的最长前缀）；
        其余（``none`` 或 0 上限）不截断。

        Args:
            prompt: 原始提示词

        Returns:
            未超上限时原样返回，超限时按上限截断
        """
        limit = self.max_prompt_length
        if not limit:
            return prompt

        if self.prompt_limit_mode == PROMPT_LIMIT_TOKENS:
            # token 口径：估算值未超限则原样放行；超限则二分找最长合法前缀
            if self.estimate_prompt_tokens(prompt) <= limit:
                return prompt
            low, high = 0, len(prompt)
            while low < high:
                mid = (low + high + 1) // 2
                if self.estimate_prompt_tokens(prompt[:mid]) <= limit:
                    low = mid
                else:
                    high = mid - 1
            return prompt[:low]

        # 字符口径（含未声明计法时的默认行为）：直接按字符截断
        if len(prompt) > limit:
            return prompt[:limit]
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
    #
    # 提示词上限不是「一个数字套所有模型」——官方对两代模型分两种口径：
    # - 3.0 系列 / 2.1-pro：按「字符」计，2000 字符（CJK 与西文同权，直接数长度）；
    # - 2.0 系列 / max / plus / 基础版：按「token」计（中文约 1 字 1 token，西文约 4 字 1 token），
    #   故同样的「2000」在中文下约合 2000 token、在西文下则远不到 —— 用字符口径去卡会误截合法提示词。
    # 两种口径由 prompt_limit_mode 显式区分，禁止再用统一字符上限。
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
        prompt_limit_mode=PROMPT_LIMIT_TOKENS,
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
        prompt_limit_mode=PROMPT_LIMIT_TOKENS,
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
        prompt_limit_mode=PROMPT_LIMIT_TOKENS,
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
        prompt_limit_mode=PROMPT_LIMIT_TOKENS,
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
        prompt_limit_mode=PROMPT_LIMIT_TOKENS,
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
        prompt_limit_mode=PROMPT_LIMIT_TOKENS,
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
    ),
    # ===== 万相 2.2 / 2.1 / wanx2.0：每边 512~1440，最大 1440*1440 =====
    # 提示词上限：万相 2.2/2.1 系列为 500 字符，wanx2.0 为 800 字符（按「字符」计）
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
        prompt_limit_mode=PROMPT_LIMIT_CHARS,
    ),
}

# 未登记模型的保守兜底能力：按异步 + 旧端点处理，取最低的安全范围，
# 确保将来线上新增模型名时不会直接崩溃，而是安全降级并给出可诊断的报错。
# 提示词上限取「最严的 500 字符 + 字符口径」：宁多截几个字，也不放行一个可能超限的请求。
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
    prompt_limit_mode=PROMPT_LIMIT_CHARS,
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
