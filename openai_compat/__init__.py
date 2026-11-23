"""通用 OpenAI 兼容上游模块.

提供任意遵循 OpenAI Images API 协议的服务商接入能力，配置 ``provider=openai``
后生图、模型列表与图片编辑均走该客户端。
"""

from .api_client import OpenAICompatibleClient

__all__ = ["OpenAICompatibleClient"]
