"""客户端管理模块

负责 AsyncOpenAI 客户端和 aiohttp Session 的管理和复用。
"""

from typing import Optional

import aiohttp
from openai import AsyncOpenAI

from astrbot.api import logger


# Debug 日志开关（默认关闭，通过配置文件控制）
DEBUG_MODE = False


def debug_log(message: str) -> None:
    """输出 Debug 日志

    Args:
        message: 日志消息
    """
    if DEBUG_MODE:
        logger.debug(f"[ClientManager] {message}")


class ClientManager:
    """客户端管理器，负责管理 OpenAI 客户端和 HTTP Session"""

    def __init__(self, base_url: str, debug_mode: bool = False) -> None:
        """初始化客户端管理器

        Args:
            base_url: API 基础 URL
            debug_mode: 是否启用 Debug 日志
        """
        global DEBUG_MODE
        DEBUG_MODE = debug_mode

        self.base_url = base_url
        self._openai_clients: dict[str, AsyncOpenAI] = {}
        self._http_session: Optional[aiohttp.ClientSession] = None
        debug_log(f"初始化客户端管理器: base_url={base_url}, debug_mode={debug_mode}")

    def get_openai_client(self, api_key: str) -> AsyncOpenAI:
        """获取或创建 AsyncOpenAI 客户端

        使用 API Key 作为缓存键，如果已存在则复用，否则创建新实例。

        Args:
            api_key: API Key

        Returns:
            AsyncOpenAI 客户端实例

        Raises:
            ValueError: 当 api_key 为空时抛出异常
        """
        if not api_key:
            raise ValueError("API Key 不能为空")

        if api_key not in self._openai_clients:
            debug_log(f"创建新的 OpenAI 客户端: api_key={api_key[:10]}...")
            self._openai_clients[api_key] = AsyncOpenAI(
                base_url=self.base_url,
                api_key=api_key,
            )
        else:
            debug_log(f"复用 OpenAI 客户端: api_key={api_key[:10]}...")

        return self._openai_clients[api_key]

    async def get_http_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp Session

        如果当前 Session 已关闭或不存在，则创建新实例。

        Returns:
            aiohttp.ClientSession 实例
        """
        if self._http_session is None or self._http_session.closed:
            debug_log("创建新的 HTTP Session")
            self._http_session = aiohttp.ClientSession()
        else:
            debug_log("复用 HTTP Session")
        return self._http_session

    async def close(self) -> None:
        """清理所有客户端资源

        关闭 HTTP Session 和所有 OpenAI 客户端连接，释放资源。
        应在插件卸载时调用。
        """
        debug_log("开始清理客户端资源")

        # 关闭 HTTP Session
        if self._http_session and not self._http_session.closed:
            debug_log("关闭 HTTP Session")
            await self._http_session.close()
            self._http_session = None

        # 清理 OpenAI 客户端
        client_count = len(self._openai_clients)
        for client in self._openai_clients.values():
            await client.close()
        self._openai_clients.clear()
        debug_log(f"已关闭 {client_count} 个 OpenAI 客户端")