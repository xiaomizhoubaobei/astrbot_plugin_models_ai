"""API 调用模块

负责 Gitee AI API 的调用和错误处理。
"""

import asyncio
from typing import Any

from astrbot.api import logger

from .client_manager import ClientManager
from .config import CLEANUP_INTERVAL
from .image_manager import ImageManager


class GiteeAIClient:
    """Gitee AI API 客户端，负责调用图像生成 API"""

    def __init__(
        self,
        api_keys: list[str],
        model: str,
        default_size: str,
        num_inference_steps: int,
        negative_prompt: str,
        base_url: str,
        debug_mode: bool = False,
    ) -> None:
        """初始化 Gitee AI 客户端

        Args:
            api_keys: API Keys 列表
            model: 模型名称
            default_size: 默认图片大小
            num_inference_steps: 推理步数
            negative_prompt: 负面提示词
            base_url: API 基础 URL
            debug_mode: 是否启用 Debug 日志
        """
        self.debug_mode = debug_mode
        self.api_keys = api_keys
        self.model = model
        self.default_size = default_size
        self.num_inference_steps = num_inference_steps
        self.negative_prompt = negative_prompt
        self.base_url = base_url

        self.client_manager = ClientManager(base_url, debug_mode=debug_mode)
        self.image_manager = ImageManager(debug_mode=debug_mode)

        self.current_key_index = 0
        self._generation_count = 0
        self._background_tasks: set[asyncio.Task[Any]] = set()

        self.debug_log(
            f"初始化 Gitee AI 客户端: model={model}, size={default_size}, "
            f"api_keys={len(api_keys)}, debug_mode={debug_mode}"
        )

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[GiteeAIClient] {message}")

    def _get_next_api_key(self) -> str:
        """轮询获取下一个 API Key

        Returns:
            API Key

        Raises:
            ValueError: 当没有配置 API Key 时抛出异常
        """
        if not self.api_keys:
            raise ValueError("请先配置 API Key")

        api_key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self.debug_log(f"轮询 API Key: index={self.current_key_index - 1}, api_key={api_key[:10]}...")
        return api_key

    async def generate_image(self, prompt: str, size: str = "") -> str:
        """调用 Gitee AI API 生成图片，返回本地文件路径

        Args:
            prompt: 图片提示词
            size: 图片大小（可选）

        Returns:
            生成的图片本地文件路径

        Raises:
            Exception: API 调用失败时抛出异常
        """
        self.debug_log(f"开始生成图片: prompt={prompt[:50]}..., size={size or self.default_size}")

        api_key = self._get_next_api_key()
        client = self.client_manager.get_openai_client(api_key)
        target_size = size if size else self.default_size

        # 构建请求参数
        extra_body: dict[str, Any] = {
            "num_inference_steps": self.num_inference_steps,
        }

        if self.negative_prompt:
            extra_body["negative_prompt"] = self.negative_prompt

        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "model": self.model,
            "extra_body": extra_body,
        }

        if target_size:
            kwargs["size"] = target_size

        self.debug_log(f"发送 API 请求: model={self.model}, size={target_size}")

        try:
            response = await client.images.generate(**kwargs)  # type: ignore
            self.debug_log("API 响应接收成功")
        except Exception as e:
            error_msg = str(e)
            self.debug_log(f"API 调用失败: {error_msg}")
            if "401" in error_msg:
                raise RuntimeError("API Key 无效或已过期，请检查配置。") from e
            if "429" in error_msg:
                raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。") from e
            if "500" in error_msg:
                raise RuntimeError("Gitee AI 服务器内部错误，请稍后再试。") from e
            raise RuntimeError(f"API调用失败: {error_msg}") from e

        if not response.data:  # type: ignore
            raise RuntimeError("生成图片失败：未返回数据")

        image_data = response.data[0]  # type: ignore

        # 检查图片数据是否包含 url 属性
        if hasattr(image_data, "url") and image_data.url:
            self.debug_log("图片数据格式: URL")
            session = await self.client_manager.get_http_session()
            filepath = await self.image_manager.download_image(image_data.url, session)
        elif hasattr(image_data, "b64_json") and image_data.b64_json:
            self.debug_log("图片数据格式: Base64")
            filepath = await self.image_manager.save_base64_image(image_data.b64_json)
        else:
            raise RuntimeError("生成图片失败：未返回 URL 或 Base64 数据")

        self.debug_log(f"图片保存成功: {filepath}")

        # 每 N 次生成执行一次清理
        self._generation_count += 1
        if self._generation_count >= CLEANUP_INTERVAL:
            self._generation_count = 0
            self.debug_log("触发图片清理任务")
            task = asyncio.create_task(self.image_manager.cleanup_old_images())
            # 保存任务引用防止 GC 回收
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return filepath

    async def close(self) -> None:
        """清理资源"""
        self.debug_log("开始清理 API 客户端资源")
        await self.client_manager.close()
        self.debug_log("API 客户端资源清理完成")
