"""千问云（万相 / Qwen-Image / Z-Image）模块.

提供千问云文生图 API 调用相关功能，支持同步（z-image-turbo）与
异步轮询（万相系列）两种链路。
"""

from .api_client import QianwenClient
from .model_config import (
    ENDPOINT_MULTIMODAL,
    ENDPOINT_TASK,
    ENDPOINT_TEXT2IMAGE,
    QianwenModelSpec,
    get_model_spec,
    is_async_model,
    is_supported_model,
    list_supported_models,
)

__all__ = [
    "ENDPOINT_MULTIMODAL",
    "ENDPOINT_TASK",
    "ENDPOINT_TEXT2IMAGE",
    "QianwenClient",
    "QianwenModelSpec",
    "get_model_spec",
    "is_async_model",
    "is_supported_model",
    "list_supported_models",
]
