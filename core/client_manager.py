"""客户端管理模块

负责 AsyncOpenAI 客户端和 aiohttp Session 的管理和复用。
"""

from typing import Optional

import aiohttp
import httpx
from openai import AsyncOpenAI

from astrbot.api import logger


class ClientManager:
    """客户端管理器，负责管理 OpenAI 客户端和 HTTP Session"""

    def __init__(self, base_url: str, debug_mode: bool = False) -> None:
        """初始化客户端管理器

        Args:
            base_url: API 基础 URL
            debug_mode: 是否启用 Debug 日志
        """
        self.debug_mode = debug_mode
        self.base_url = base_url
        self._openai_clients: dict[str, AsyncOpenAI] = {}
        self._http_session: Optional[aiohttp.ClientSession] = None
        # 创建共享的 httpx.AsyncClient，供所有 AsyncOpenAI 实例使用
        self._httpx_client: Optional[httpx.AsyncClient] = None
        self.debug_log(f"初始化客户端管理器: base_url={base_url}, debug_mode={debug_mode}")

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[ClientManager] {message}")

    def get_openai_client(self, api_key: str) -> AsyncOpenAI:
        """获取或创建 AsyncOpenAI 客户端

        使用 API Key 作为缓存键，如果已存在则复用，否则创建新实例。
        所有 AsyncOpenAI 实例共享同一个 httpx.AsyncClient 以减少资源占用。

        Args:
            api_key: API Key

        Returns:
            AsyncOpenAI 客户端实例

        Raises:
            ValueError: 当 api_key 为空时抛出异常
        """
        if not api_key:
            raise ValueError("API Key 不能为空")

        # 延迟初始化共享的 httpx.AsyncClient
        if self._httpx_client is None:
            self.debug_log("创建共享的 httpx.AsyncClient")
            self._httpx_client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                timeout=httpx.Timeout(60.0, connect=10.0),
            )

        if api_key not in self._openai_clients:
            self.debug_log(f"创建新的 OpenAI 客户端: api_key={api_key[:10]}...")
            self._openai_clients[api_key] = AsyncOpenAI(
                base_url=self.base_url,
                api_key=api_key,
                http_client=self._httpx_client,  # 使用共享的 httpx.AsyncClient
            )
        else:
            self.debug_log(f"复用 OpenAI 客户端: api_key={api_key[:10]}...")

        return self._openai_clients[api_key]

    async def get_http_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp Session

        如果当前 Session 已关闭或不存在，则创建新实例。

        Returns:
            aiohttp.ClientSession 实例
        """
        if self._http_session is None or self._http_session.closed:
            self.debug_log("创建新的 HTTP Session")
            self._http_session = aiohttp.ClientSession()
        else:
            self.debug_log("复用 HTTP Session")
        return self._http_session

    async def close(self) -> None:
        """清理所有客户端资源

        关闭 HTTP Session、共享的 httpx.AsyncClient 和所有 OpenAI 客户端连接，释放资源。
        应在插件卸载时调用。
        """
        self.debug_log("开始清理客户端资源")

        # 关闭 HTTP Session
        if self._http_session and not self._http_session.closed:
            self.debug_log("关闭 HTTP Session")
            await self._http_session.close()
            self._http_session = None

        # 关闭共享的 httpx.AsyncClient
        if self._httpx_client is not None:
            self.debug_log("关闭共享的 httpx.AsyncClient")
            await self._httpx_client.aclose()
            self._httpx_client = None

        # 清理 OpenAI 客户端（不需要调用 close，因为它们使用共享的 httpx.AsyncClient）
        client_count = len(self._openai_clients)
        self._openai_clients.clear()
        self.debug_log(f"已清理 {client_count} 个 OpenAI 客户端")
