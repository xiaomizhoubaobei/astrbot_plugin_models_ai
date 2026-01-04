"""防抖和并发控制模块

负责请求防抖检查和并发控制。
"""

import time
from typing import Set

from astrbot.api import logger

from .config import DEBOUNCE_SECONDS, OPERATION_CACHE_TTL


class RateLimiter:
    """速率限制器，负责防抖检查和并发控制"""

    def __init__(self, debug_mode: bool = False) -> None:
        """初始化速率限制器

        Args:
            debug_mode: 是否启用 Debug 日志
        """
        self.debug_mode = debug_mode
        self.processing_users: Set[str] = set()
        self.last_operations: dict[str, float] = {}
        self.debug_log(f"初始化速率限制器: debug_mode={debug_mode}")

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[RateLimiter] {message}")

    def _cleanup_expired_operations(self) -> None:
        """清理过期的操作记录，防止内存泄漏"""
        current_time = time.time()
        expired_keys = [
            key
            for key, timestamp in self.last_operations.items()
            if current_time - timestamp > OPERATION_CACHE_TTL
        ]
        for key in expired_keys:
            del self.last_operations[key]

    def check_debounce(self, request_id: str) -> bool:
        """检查防抖，返回 True 表示需要拒绝请求

        Args:
            request_id: 请求标识符

        Returns:
            True 表示需要拒绝请求，False 表示允许请求
        """
        current_time = time.time()

        # 定期清理过期记录
        if len(self.last_operations) > 100:
            self._cleanup_expired_operations()

        if request_id in self.last_operations:
            elapsed = current_time - self.last_operations[request_id]
            if elapsed < DEBOUNCE_SECONDS:
                self.debug_log(f"防抖拦截: request_id={request_id}, elapsed={elapsed:.2f}s")
                return True

        self.last_operations[request_id] = current_time
        self.debug_log(f"防抖通过: request_id={request_id}")
        return False

    def is_processing(self, request_id: str) -> bool:
        """检查请求是否正在处理中

        Args:
            request_id: 请求标识符

        Returns:
            True 表示正在处理，False 表示未处理
        """
        return request_id in self.processing_users

    def add_processing(self, request_id: str) -> None:
        """添加请求到处理中列表

        Args:
            request_id: 请求标识符
        """
        self.processing_users.add(request_id)
        self.debug_log(f"添加到处理队列: request_id={request_id}, queue_size={len(self.processing_users)}")

    def remove_processing(self, request_id: str) -> None:
        """从处理中列表移除请求

        Args:
            request_id: 请求标识符
        """
        self.processing_users.discard(request_id)
        self.debug_log(f"从处理队列移除: request_id={request_id}, queue_size={len(self.processing_users)}")
