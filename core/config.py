"""配置管理模块.

负责配置常量定义、配置解析和验证。
"""

from typing import Any

# 插件配置
PLUGIN_NAME = "astrbot_plugin_models_ai"

# 配置常量
DEFAULT_BASE_URL = "https://ai.gitee.com/v1"
DEFAULT_MODEL = "z-image-turbo"
DEFAULT_SIZE = "1024x1024"
DEFAULT_INFERENCE_STEPS = 9
DEFAULT_NEGATIVE_PROMPT = (
    "low quality, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, worst quality, normal quality, "
    "jpeg artifacts, signature, watermark, username, blurry"
)

# 防抖和清理配置
DEBOUNCE_SECONDS = 10.0
MAX_CACHED_IMAGES = 20
OPERATION_CACHE_TTL = 300  # 5分钟清理一次过期操作记录
CLEANUP_INTERVAL = 10  # 每 N 次生成执行一次清理

# Gitee AI 支持的图片比例
SUPPORTED_RATIOS: dict[str, list[str]] = {
    "1:1": ["256x256", "512x512", "1024x1024", "2048x2048"],
    "4:3": ["1152x896", "2048x1536"],
    "3:4": ["768x1024", "1536x2048"],
    "3:2": ["2048x1360"],
    "2:3": ["1360x2048"],
    "16:9": ["1024x576", "2048x1152"],
    "9:16": ["576x1024", "1152x2048"],
}

# ===== 千问云（Qwen / DashScope）配置 =====
# 千问文生图为 DashScope 原生接口，不支持 OpenAI 兼容模式，故走原生 REST。
DEFAULT_QIANWEN_BASE_URL = "https://maas.qianwenaiapi.com/api/v1"
DEFAULT_QIANWEN_MODEL = "qwen-image-plus"
# 注意：千问的尺寸分隔符是星号「宽*高」，与 Gitee 的字母 x 不同，不可混用
DEFAULT_QIANWEN_SIZE = "1328*1328"

# 千问云支持的图片比例（尺寸按官方文档推荐分辨率，格式为 宽*高）
# 说明：qwen-image-plus/max 仅接受固定档；此处取 1K 档作为通用默认值，
# 具体每个模型的可接受范围由 qianwen/model_config.py 的能力表做二次校验与降级。
QIANWEN_SUPPORTED_RATIOS: dict[str, list[str]] = {
    # 首项会被当作该比例的默认推荐值；把插件通用默认值 1024*1024 放在首位，
    # 使用户未显式指定比例时不会偏离自己的配置（各具体型号的可接受范围由能力表二次校验）
    "1:1": ["1024*1024", "1280*1280", "1328*1328", "2048*2048"],
    "4:3": ["1472*1104", "2368*1728"],
    "3:4": ["1104*1472", "1728*2368"],
    "3:2": ["1248*832", "2496*1664"],
    "2:3": ["832*1248", "1664*2496"],
    "16:9": ["1696*960", "2688*1536"],
    "9:16": ["960*1696", "1536*2688"],
}

# 千问异步任务（Wan 系列）轮询策略，对齐官方建议：
# 前 QIANWEN_POLL_FAST_WINDOW 秒内每 QIANWEN_POLL_INITIAL_INTERVAL 秒轮询一次，
# 之后逐步退避到 QIANWEN_POLL_MAX_INTERVAL 秒，总时长超过 QIANWEN_POLL_TIMEOUT 判定失败。
QIANWEN_POLL_INITIAL_INTERVAL = 3
QIANWEN_POLL_FAST_WINDOW = 30
QIANWEN_POLL_MAX_INTERVAL = 10
QIANWEN_POLL_TIMEOUT = 300


def parse_api_keys(api_keys: Any) -> list[str]:
    """解析 API Keys 配置，支持字符串和列表格式.

    Args:
        api_keys: API Keys 配置，可以是字符串或列表

    Returns:
        解析后的 API Keys 列表
    """
    if isinstance(api_keys, str):
        if api_keys:
            return [k.strip() for k in api_keys.split(",") if k.strip()]
        return []
    if isinstance(api_keys, list):
        return [str(k).strip() for k in api_keys if str(k).strip()]
    return []


def normalize_size(size: str, separator: str = "x") -> str:
    """统一图片尺寸的分隔符.

    配置层统一使用 ``宽x高``（字母 x）书写，而千问云要求 ``宽*高``（星号），
    因此跨服务商复用同一个 size 配置时需要做分隔符转换。

    Args:
        size: 原始尺寸字符串，例如 "1024x1024" 或 "1024*1024"
        separator: 目标分隔符，千问传 "*"，Gitee 传 "x"

    Returns:
        归一化后的尺寸字符串；当 size 不是合法的「宽x高」格式时原样返回

    """
    if not size:
        return size
    # 同时兼容星号与字母 x 两种输入写法
    normalized = size.replace("*", "x")
    parts = normalized.split("x")
    if len(parts) != 2:
        return size
    width, height = parts
    if not (width.strip().isdigit() and height.strip().isdigit()):
        return size
    return f"{width.strip()}{separator}{height.strip()}"
