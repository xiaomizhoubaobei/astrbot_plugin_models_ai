"""千问云（Qwen / DashScope）模块.

提供千问云文生图 API 调用相关功能，支持同步（Qwen-Image 系列）与
异步轮询（Wan 系列）两种链路。
"""

from .api_client import QianwenClient
from .model_config import (
    QianwenModelSpec,
    get_model_spec,
    is_async_model,
    list_supported_models,
)

__all__ = [
    "QianwenClient",
    "QianwenModelSpec",
    "get_model_spec",
    "is_async_model",
    "list_supported_models",
]
