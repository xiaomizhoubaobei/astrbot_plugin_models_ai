"""API 调用模块

负责 Gitee AI API 的调用和错误处理。
"""

import asyncio
from typing import Any

from astrbot.api import logger
from openai import AuthenticationError, RateLimitError, APIError

from ..core import ClientManager, ImageManager


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
        except AuthenticationError as e:
            self.debug_log(f"API 认证失败: {e}")
            raise RuntimeError("API Key 无效或已过期，请检查配置。") from e
        except RateLimitError as e:
            self.debug_log(f"API 速率限制: {e}")
            raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。") from e
        except APIError as e:
            self.debug_log(f"API 错误: {e}")
            if e.status_code == 500:
                raise RuntimeError("Gitee AI 服务器内部错误，请稍后再试。") from e
            raise RuntimeError(f"API调用失败: {e}") from e
        except Exception as e:
            self.debug_log(f"未知错误: {e}")
            raise RuntimeError(f"API调用失败: {e}") from e

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
        from ..core import CLEANUP_INTERVAL
        
        self._generation_count += 1
        if self._generation_count >= CLEANUP_INTERVAL:
            self._generation_count = 0
            self.debug_log("触发图片清理任务")
            task = asyncio.create_task(self.image_manager.cleanup_old_images())
            # 保存任务引用防止 GC 回收
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return filepath

    async def get_models(self, vendor: str = "", type: str = "") -> list[dict[str, Any]]:
        """获取模型列表

        Args:
            vendor: 算力厂商筛选（可选）
            type: 模型类型筛选（可选），支持：text2image, text2text, embeddings, etc.

        Returns:
            模型列表数据，每个元素包含 id, created, owned_by 等字段

        Raises:
            RuntimeError: API 调用失败时抛出异常
        """
        self.debug_log(f"开始获取模型列表: vendor={vendor}, type={type}")

        api_key = self._get_next_api_key()
        session = await self.client_manager.get_http_session()

        # 构建查询参数
        params: list[tuple[str, str]] = []
        if vendor:
            params.append(("vendor", vendor))
        if type:
            params.append(("type", type))

        self.debug_log(f"发送模型列表请求: params={params}")

        try:
            # 使用原始 HTTP 请求调用 Gitee AI 的 models API
            url = f"{self.base_url}/models"
            headers = {
                "Authorization": f"Bearer {api_key}",
            }

            response = await session.get(url, params=params, headers=headers)
            response.raise_for_status()

            data = await response.json()
            self.debug_log(f"模型列表获取成功: response_type={data.get('object')}, count={len(data.get('data', []))}")

            # 转换为字典列表
            models_data = []
            for model in data.get("data", []):
                models_data.append({
                    "id": model.get("id", ""),
                    "created": model.get("created", 0),
                    "owned_by": model.get("owned_by", ""),
                })

            return models_data

        except Exception as e:
            self.debug_log(f"API 调用失败: {e}")
            # 根据错误类型返回友好的错误信息
            error_msg = str(e)
            if "401" in error_msg or "403" in error_msg:
                raise RuntimeError("API Key 无效或已过期，请检查配置。") from e
            elif "429" in error_msg:
                raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。") from e
            elif "500" in error_msg:
                raise RuntimeError("Gitee AI 服务器内部错误，请稍后再试。") from e
            else:
                raise RuntimeError(f"API调用失败: {error_msg}") from e

    async def edit_image(
        self,
        prompt: str,
        image_paths: list[str],
        task_types: list[str] | None = None,
        model: str = "Qwen-Image-Edit-2511",
        num_inference_steps: int = 4,
        guidance_scale: float = 1.0,
        download_urls: bool = False,
    ) -> str:
        """调用 Gitee AI API 编辑图片，返回本地文件路径

        Args:
            prompt: 编辑提示词
            image_paths: 图片路径列表（支持本地路径或 URL）
            task_types: 任务类型列表（可选），支持：id, style 等
            model: 编辑模型名称
            num_inference_steps: 推理步数
            guidance_scale: 引导系数
            download_urls: 是否下载 URL 图片后再上传（默认 False，直接传 URL）

        Returns:
            编辑后的图片本地文件路径

        Raises:
            Exception: API 调用失败时抛出异常
        """
        self.debug_log(
            f"开始编辑图片: prompt={prompt[:50]}..., "
            f"images={len(image_paths)}, task_types={task_types}, download_urls={download_urls}"
        )

        api_key = self._get_next_api_key()
        session = await self.client_manager.get_http_session()

        # 构建请求参数
        if task_types is None:
            task_types = ["style"]

        # 构建表单字段
        fields = [
            ("prompt", prompt),
            ("model", model),
            ("num_inference_steps", str(num_inference_steps)),
            ("guidance_scale", str(guidance_scale)),
        ]

        # 添加任务类型
        for item in task_types:
            if isinstance(item, str):
                fields.append(("task_types", item))
            else:
                import json
                fields.append(("task_types", json.dumps(item)))

        # 添加图片
        import mimetypes
        import os

        for filepath in image_paths:
            name = os.path.basename(filepath)
            if filepath.startswith(("http://", "https://")):
                if download_urls:
                    # 下载远程图片后再上传
                    response = await session.get(filepath, timeout=10)
                    response.raise_for_status()
                    content = await response.read()
                    mime_type = response.headers.get("Content-Type", "application/octet-stream")
                    fields.append(("image", (name, content, mime_type)))
                else:
                    # 直接传递 URL
                    fields.append(("image_url", filepath))
            else:
                # 读取本地图片
                mime_type, _ = mimetypes.guess_type(filepath)
                with open(filepath, "rb") as f:
                    content = f.read()
                fields.append(("image", (name, content, mime_type or "application/octet-stream")))

        # 构建请求头
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Failover-Enabled": "true",
        }

        # 发送请求
        import aiohttp

        data = aiohttp.FormData()
        for field in fields:
            if isinstance(field[1], tuple):
                # 文件字段
                name, value, content_type = field[1]
                data.add_field(field[0], value, filename=name, content_type=content_type)
            else:
                # 普通字段
                data.add_field(field[0], field[1])

        self.debug_log("发送图片编辑请求")

        try:
            async with session.post(
                f"{self.base_url}/async/images/edits",
                headers=headers,
                data=data
            ) as response:
                response.raise_for_status()
                result = await response.json()

            task_id = result.get("task_id")
            if not task_id:
                raise RuntimeError("未返回任务 ID")

            self.debug_log(f"任务创建成功: task_id={task_id}")

            # 轮询任务状态
            filepath = await self._poll_edit_task(task_id, session, api_key)
            self.debug_log(f"图片编辑完成: {filepath}")

            return filepath

        except Exception as e:
            self.debug_log(f"图片编辑失败: {e}")
            raise RuntimeError(f"图片编辑失败: {str(e)}") from e

    async def _poll_edit_task(
        self,
        task_id: str,
        session,
        api_key: str,
        timeout: int = 30 * 60,
        retry_interval: int = 10,
    ) -> str:
        """轮询图片编辑任务状态

        Args:
            task_id: 任务 ID
            session: HTTP 会话
            api_key: API Key
            timeout: 超时时间（秒）
            retry_interval: 重试间隔（秒）

        Returns:
            编辑后的图片本地文件路径

        Raises:
            RuntimeError: 任务失败或超时时抛出异常
        """
        max_attempts = int(timeout / retry_interval)
        attempts = 0

        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        while attempts < max_attempts:
            attempts += 1
            self.debug_log(f"轮询任务状态 [{attempts}/{max_attempts}]...")

            try:
                async with session.get(
                    f"{self.base_url}/task/{task_id}",
                    headers=headers,
                    timeout=10
                ) as response:
                    response.raise_for_status()
                    result = await response.json()

                if result.get("error"):
                    error_msg = result.get("message", "未知错误")
                    raise RuntimeError(f"任务错误: {error_msg}")

                status = result.get("status", "unknown")
                self.debug_log(f"任务状态: {status}")

                if status == "success":
                    if "output" in result and "file_url" in result["output"]:
                        file_url = result["output"]["file_url"]
                        completed_at = result.get('completed_at', 0)
                        started_at = result.get('started_at', 0)
                        duration = (completed_at - started_at) / 1000 if completed_at and started_at else 0
                        self.debug_log(f"任务完成，耗时: {duration:.2f}秒")
                        # 下载图片
                        return await self.image_manager.download_image(file_url, session)
                    else:
                        raise RuntimeError("任务成功但未返回图片 URL")
                elif status in ["failed", "cancelled"]:
                    raise RuntimeError(f"任务失败: {status}")
                else:
                    # 任务仍在进行中，等待重试
                    await asyncio.sleep(retry_interval)
                    continue

            except Exception as e:
                if attempts >= max_attempts:
                    raise RuntimeError(f"任务轮询失败: {str(e)}") from e
                self.debug_log(f"轮询失败，等待重试: {e}")
                await asyncio.sleep(retry_interval)

        raise RuntimeError(f"任务超时（已等待 {timeout} 秒）")

    async def close(self) -> None:
        """清理资源"""
        self.debug_log("开始清理 API 客户端资源")
        await self.client_manager.close()
        self.debug_log("API 客户端资源清理完成")
