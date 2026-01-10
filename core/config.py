"""配置管理模块

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


def parse_api_keys(api_keys: Any) -> list[str]:
    """解析 API Keys 配置，支持字符串和列表格式

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
