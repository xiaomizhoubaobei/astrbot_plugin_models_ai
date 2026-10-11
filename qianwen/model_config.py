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

Qwen-Image 同步接口（本仓库 :data:`ENDPOINT_MULTIMODAL` 对应的那份文档）另有三条硬口径，
已逐一收进本表，避免"以旧版印象写死参数"：

- **提示词按 token 计**：3.0 系列与 2.1-pro 推荐不超过 4500 token；2.0 系列上限 1300 token；
  其余（max / plus / 基础版 / z-image）为 800 token。三档均由 ``prompt_limit_mode``
  取 ``PROMPT_LIMIT_TOKENS`` 表达。
- **negative_prompt 上限 500 字符**，且 **qwen-image-2.1-pro 不支持该参数**（传了会 400）。
- **尺寸**：3.0 系列 / 2.1-pro 为 512*512 ~ 2048*2048 且宽高比 1:8 ~ 8:1（不传则由模型推荐）；
  2.0 系列为 512*512 ~ 2048*2048，默认 2048*2048；max / plus / 基础版仅接受固定预设档。
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

# negative_prompt 上限（官方：最多 500 个字符，超出部分自动截断）
MAX_NEGATIVE_PROMPT_LENGTH = 500

# Qwen-Image 3.0 系列 / 2.1-pro 的宽高比约束：1:8 ~ 8:1
MIN_ASPECT_RATIO = 1 / 8
MAX_ASPECT_RATIO = 8


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
        supports_aspect_ratio: 是否施加宽高比约束（1:8 ~ 8:1）。
            官方仅对 qwen-image-3.0 系列与 2.1-pro 给出该约束，其余模型不校验。
        supports_prompt_extend_mode: 是否支持 ``prompt_extend_mode``（DPE / APE）。
            官方仅对 qwen-image-3.0 系列与 2.1-pro 开放，其余模型传了会 400。
        supports_enable_thinking: 是否支持 ``enable_thinking``（思考模式）。
            同样仅 3.0 系列与 2.1-pro 支持，且需在 prompt_extend=true 时生效。
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
    # 宽高比约束：仅 qwen-image-3.0 系列与 2.1-pro 由官方明确限定 1:8 ~ 8:1
    supports_aspect_ratio: bool = False
    # 提示词改写方式（prompt_extend_mode）与思考模式（enable_thinking）：
    # 官方文档明确「仅 qwen-image-3.0 系列与 2.1-pro 支持」，其余模型不得下发
    supports_prompt_extend_mode: bool = False
    supports_enable_thinking: bool = False

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
        if not (
            self.min_side <= width <= self.max_side
            and self.min_side <= height <= self.max_side
        ):
            return False

        # 官方对 3.0 系列 / 2.1-pro 额外限定宽高比 1:8 ~ 8:1，
        # 极端长条（如 2048*100）虽然两边都没越界，上游仍会直接 400。
        if self.supports_aspect_ratio:
            ratio = width / height
            if not (MIN_ASPECT_RATIO <= ratio <= MAX_ASPECT_RATIO):
                return False

        return True

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

    def resolve_negative_prompt(self, negative_prompt: str) -> str:
        """按官方 500 字符上限截断负面提示词.

        官方明确 negative_prompt「最多 500 个字符，超出部分自动截断」，
        本地先截一遍可避免把明显超长的配置整段发出去（上游静默截断后
        用户无从得知实际生效了什么）。

        Args:
            negative_prompt: 原始负面提示词

        Returns:
            未超上限时原样返回，超限时截断到 500 字符
        """
        if len(negative_prompt) > MAX_NEGATIVE_PROMPT_LENGTH:
            return negative_prompt[:MAX_NEGATIVE_PROMPT_LENGTH]
        return negative_prompt


# 官方提示词上限（按 token 计）：3.0 系列 / 2.1-pro、2.0 系列、其余各一档
_QWEN_3X_PROMPT_TOKENS = 4500
_QWEN_2X_PROMPT_TOKENS = 1300
_QWEN_BASE_PROMPT_TOKENS = 800

# max / plus / 基础版共用的固定预设分辨率（官方图像模型表：最大 1664×928，共 5 档）
_QWEN_FIXED_SIZES: tuple[str, ...] = (
    "1664*928",
    "1472*1104",
    "1328*1328",
    "1104*1472",
    "928*1664",
)


def _qwen_range_spec(
    *,
    supports_negative_prompt: bool = True,
    max_prompt_length: int,
    supports_aspect_ratio: bool = False,
    supports_prompt_extend_mode: bool = False,
    supports_enable_thinking: bool = False,
) -> QianwenModelSpec:
    """构造「范围型尺寸」Qwen-Image 的能力描述（3.0 系列 / 2.1 / 2.0 共用骨架）.

    官方同步接口对这几个型号的尺寸口径一致（512*512 ~ 2048*2048），
    差异只在提示词 token 上限、是否支持 negative_prompt、
    以及 3.0 系列 / 2.1-pro 独有的宽高比约束与两个附加参数上，
    因此用工厂函数收口，避免同一份骨架被抄十几遍后各自漂移。

    Args:
        supports_negative_prompt: 是否支持负面提示词（2.1-pro 为 False）
        max_prompt_length: 提示词 token 上限
        supports_aspect_ratio: 是否施加宽高比 1:8 ~ 8:1 约束
        supports_prompt_extend_mode: 是否支持 prompt_extend_mode（DPE / APE）
        supports_enable_thinking: 是否支持 enable_thinking（思考模式）

    Returns:
        构造好的能力描述
    """
    return QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="2048*2048",
        min_side=512,
        max_side=2048,
        supports_negative_prompt=supports_negative_prompt,
        supports_prompt_extend=True,
        max_prompt_length=max_prompt_length,
        prompt_limit_mode=PROMPT_LIMIT_TOKENS,
        supports_aspect_ratio=supports_aspect_ratio,
        supports_prompt_extend_mode=supports_prompt_extend_mode,
        supports_enable_thinking=supports_enable_thinking,
    )


def _qwen_fixed_spec() -> QianwenModelSpec:
    """构造「固定档尺寸」Qwen-Image 的能力描述（max / plus / 基础版 / 2.0-max 共用）.

    官方图像模型表把这几个型号同列：仅接受 5 档预设分辨率、最大输出数 1、
    提示词上限 800 token。

    Returns:
        构造好的能力描述
    """
    return QianwenModelSpec(
        endpoint=ENDPOINT_MULTIMODAL,
        call_mode="sync",
        response_format="choices",
        default_size="1664*928",
        min_side=0,
        max_side=0,
        supports_negative_prompt=True,
        supports_prompt_extend=True,
        fixed_sizes=_QWEN_FIXED_SIZES,
        max_prompt_length=_QWEN_BASE_PROMPT_TOKENS,
        prompt_limit_mode=PROMPT_LIMIT_TOKENS,
    )


# 各模型能力表：字段口径来自官方文档的「支持的模型 / 参数说明」章节
QIANWEN_MODEL_SPECS: dict[str, QianwenModelSpec] = {
    # --- 3.0 系列：4500 token + 宽高比 1:8~8:1 + DPE/思考模式 ---
    "qwen-image-3.0-pro": _qwen_range_spec(
        max_prompt_length=_QWEN_3X_PROMPT_TOKENS,
        supports_aspect_ratio=True,
        supports_prompt_extend_mode=True,
        supports_enable_thinking=True,
    ),
    "qwen-image-3.0": _qwen_range_spec(
        max_prompt_length=_QWEN_3X_PROMPT_TOKENS,
        supports_aspect_ratio=True,
        supports_prompt_extend_mode=True,
        supports_enable_thinking=True,
    ),
    # --- 2.1-pro：与 3.0 同档能力（4500 token / 宽高比 / DPE / 思考模式），
    #     但官方明确「不支持 negative_prompt」，传了会被上游拒绝 ---
    "qwen-image-2.1-pro": _qwen_range_spec(
        supports_negative_prompt=False,
        max_prompt_length=_QWEN_3X_PROMPT_TOKENS,
        supports_aspect_ratio=True,
        supports_prompt_extend_mode=True,
        supports_enable_thinking=True,
    ),
    # --- 2.1-turbo：官方同步接口列出的可选模型，尺寸口径与 2.x 同区间 ---
    "qwen-image-2.1-turbo": _qwen_range_spec(max_prompt_length=_QWEN_2X_PROMPT_TOKENS),
    # --- 2.0 系列（含官方列出的三个日期快照）：1300 token，无宽高比约束 ---
    "qwen-image-2.0-pro": _qwen_range_spec(max_prompt_length=_QWEN_2X_PROMPT_TOKENS),
    "qwen-image-2.0-pro-2026-06-22": _qwen_range_spec(
        max_prompt_length=_QWEN_2X_PROMPT_TOKENS
    ),
    "qwen-image-2.0-pro-2026-04-22": _qwen_range_spec(
        max_prompt_length=_QWEN_2X_PROMPT_TOKENS
    ),
    "qwen-image-2.0-pro-2026-03-03": _qwen_range_spec(
        max_prompt_length=_QWEN_2X_PROMPT_TOKENS
    ),
    "qwen-image-2.0": _qwen_range_spec(max_prompt_length=_QWEN_2X_PROMPT_TOKENS),
    "qwen-image-2.0-2026-03-03": _qwen_range_spec(
        max_prompt_length=_QWEN_2X_PROMPT_TOKENS
    ),
    # --- max / plus / 基础版：仅接受固定预设分辨率，n 仅支持 1 ---
    "qwen-image-max": _qwen_fixed_spec(),
    "qwen-image-plus": _qwen_fixed_spec(),
    "qwen-image": _qwen_fixed_spec(),
    # 兼容别名：历史配置里的 qwen-image-2.0-max 指向同一档固定分辨率
    "qwen-image-2.0-max": _qwen_fixed_spec(),
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
