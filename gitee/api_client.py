"""API 调用模块.

负责 Gitee AI API 的调用和错误处理。

出站请求统一经由 ``core.net_errors`` 做两件事：

- **指数退避重试**：DNS / 连接超时 / 读取超时 / 连接重置等瞬时故障按
  1s / 2s / 4s 重试；认证、限流、参数类错误属于确定性失败，快速返回中文提示。
- **错误分类脱敏**：与千问云共用同一套分类器，切换服务商后排障口径一致，
  且回包文本会抹掉 API Key 与 URL query。
"""

import asyncio
import json
import mimetypes
import os
from typing import Any

import aiohttp
from astrbot.api import logger
from openai import APIError, AuthenticationError, RateLimitError

from ..core import (
    DEFAULT_MAX_RETRIES,
    SUPPORTED_RATIOS,
    ClientManager,
    ImageManager,
    build_timeout,
    is_safe_to_replay,
    mask_text,
    new_idempotency_key,
    to_user_message,
    with_retry,
)


class GiteeAIClient:
    """Gitee AI API 客户端，负责调用图像生成 API."""

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
        """初始化 Gitee AI 客户端.

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

        # 供 parse_prompt_and_size 读取，使比例映射随服务商切换
        self.supported_ratios = SUPPORTED_RATIOS

        self.client_manager = ClientManager(base_url, debug_mode=debug_mode)
        self.image_manager = ImageManager(debug_mode=debug_mode)

        # 记录已创建的 Background Task，避免任务被 GC 提前回收
        self.current_key_index = 0
        self._generation_count = 0
        self._background_tasks: set[asyncio.Task[Any]] = set()

        self.debug_log(
            f"初始化 Gitee AI 客户端: model={model}, size={default_size}, "
            f"api_keys={len(api_keys)}, debug_mode={debug_mode}"
        )

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志.

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[GiteeAIClient] {message}")

    def _get_next_api_key(self) -> str:
        """轮询获取下一个 API Key.

        Returns:
            API Key

        Raises:
            ValueError: 当没有配置 API Key 时抛出异常
        """
        if not self.api_keys:
            raise ValueError("请先配置 API Key")

        api_key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self.debug_log(
            f"轮询 API Key: index={self.current_key_index - 1}, api_key={api_key[:10]}..."
        )
        return api_key

    def _log_retry(self, scene: str):
        """构造一个「记录重试」的回调，交给 ``with_retry`` 使用.

        Args:
            scene: 场景名（如「生图请求」「模型列表请求」），用于日志区分

        Returns:
            回调函数，签名为 ``(第几次重试, 退避秒数, 异常)``
        """

        def _callback(attempt: int, delay: float, exc: BaseException) -> None:
            """记录一次重试，异常文本已脱敏."""
            self.debug_log(
                f"{scene} 失败，第 {attempt}/{DEFAULT_MAX_RETRIES} 次重试"
                f"（{delay:.0f}s 后）: {type(exc).__name__} - {mask_text(exc)}"
            )

        return _callback

    async def generate_image(self, prompt: str, size: str = "") -> str:
        """调用 Gitee AI API 生成图片，返回本地文件路径.

        Args:
            prompt: 图片提示词
            size: 图片大小（可选）

        Returns:
            生成的图片本地文件路径

        Raises:
            Exception: API 调用失败时抛出异常
        """
        self.debug_log(
            f"开始生成图片: prompt={prompt[:50]}..., size={size or self.default_size}"
        )

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

        async def _request():
            """执行一次生图请求，SDK 异常交由外层统一分类."""
            return await client.images.generate(**kwargs)  # type: ignore

        try:
            # OpenAI SDK 已把网络异常包成 APIConnectionError，这里统一按
            # 瞬时故障重试；认证 / 限流 / 参数错误会被 is_retryable 判为不重试。
            response = await with_retry(
                _request,
                max_retries=DEFAULT_MAX_RETRIES,
                label="Gitee AI 生图请求",
                on_retry=self._log_retry("生图请求"),
            )
            self.debug_log("API 响应接收成功")
        except AuthenticationError as e:
            self.debug_log(f"API 认证失败: {mask_text(e)}")
            raise RuntimeError("API Key 无效或已过期，请检查配置。") from e
        except RateLimitError as e:
            self.debug_log(f"API 速率限制: {mask_text(e)}")
            raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。") from e
        except APIError as e:
            self.debug_log(f"API 错误: {mask_text(e)}")
            if e.status_code == 500:
                raise RuntimeError("Gitee AI 服务器内部错误，请稍后再试。") from e
            raise RuntimeError(f"API调用失败：{to_user_message(e)}") from e
        except Exception as e:
            self.debug_log(f"未知错误: {mask_text(e)}")
            raise RuntimeError(f"API调用失败：{to_user_message(e)}") from e

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

    async def get_models(
        self, vendor: str = "", type: str = ""
    ) -> list[dict[str, Any]]:
        """获取模型列表.

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

        # 使用原始 HTTP 请求调用 Gitee AI 的 models API
        url = f"{self.base_url}/models"
        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        async def _request() -> dict[str, Any]:
            """拉取一次模型列表，非 2xx 转成中文业务异常（不参与重试）."""
            async with session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    body = mask_text(await response.text())
                    # 这里必须按真实 status 分支，不能再靠字符串里是否含 "401"
                    # 去猜——域名/query 里恰好出现该数字会误判。
                    if response.status in (401, 403):
                        raise RuntimeError("API Key 无效或已过期，请检查配置。")
                    if response.status == 429:
                        raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。")
                    if response.status >= 500:
                        raise RuntimeError("Gitee AI 服务器内部错误，请稍后再试。")
                    raise RuntimeError(
                        f"获取模型列表失败: HTTP {response.status}"
                        + (f"（响应：{body}）" if body else "")
                    )
                payload: dict[str, Any] = await response.json()
                return payload

        try:
            data = await with_retry(
                _request,
                max_retries=DEFAULT_MAX_RETRIES,
                label="Gitee AI 模型列表请求",
                on_retry=self._log_retry("模型列表请求"),
            )
        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"API 调用失败: {mask_text(e)}")
            raise RuntimeError(f"API调用失败：{to_user_message(e)}") from e

        self.debug_log(
            f"模型列表获取成功: response_type={data.get('object')}, "
            f"count={len(data.get('data', []))}"
        )

        # 转换为字典列表
        models_data = []
        for model in data.get("data", []):
            models_data.append(
                {
                    "id": model.get("id", ""),
                    "created": model.get("created", 0),
                    "owned_by": model.get("owned_by", ""),
                }
            )

        return models_data

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
        """调用 Gitee AI API 编辑图片，返回本地文件路径.

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

        # 构建表单字段：值既可能是普通字符串，也可能是
        # (文件名, 内容, MIME 类型) 三元组，故显式声明为 Any
        fields: list[tuple[str, Any]] = [
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
                fields.append(("task_types", json.dumps(item)))

        # 添加图片
        for filepath in image_paths:
            name = os.path.basename(filepath)
            if filepath.startswith(("http://", "https://")):
                if download_urls:
                    # 下载远程图片后再上传（复用统一超时配置，区分连接/读取）
                    file_timeout = build_timeout()
                    response = await session.get(filepath, timeout=file_timeout)
                    response.raise_for_status()
                    content = await response.read()
                    remote_mime = response.headers.get(
                        "Content-Type", "application/octet-stream"
                    )
                    fields.append(("image", (name, content, remote_mime)))
                else:
                    # 直接传递 URL
                    fields.append(("image_url", filepath))
            else:
                # 读取本地图片
                mime_type, _ = mimetypes.guess_type(filepath)
                with open(filepath, "rb") as f:
                    content = f.read()
                fields.append(
                    ("image", (name, content, mime_type or "application/octet-stream"))
                )

        # 构建请求头
        # Idempotency-Key：图片编辑是「创建异步任务」的非幂等 POST，
        # 连接在响应回程中断时若原样重试，会在上游生成孤立的重复编辑任务。
        # 这里为**同一次逻辑提交**（含其全部重试）生成并复用同一个幂等键，
        # 配合下方收窄后的重试判定，双保险抑制重复作业。
        idempotency_key = new_idempotency_key("cnb-gitee-edit")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Failover-Enabled": "true",
            "Idempotency-Key": idempotency_key,
        }

        self.debug_log("发送图片编辑请求")

        def _build_form() -> aiohttp.FormData:
            """按需重建表单请求体，保证每次重试都拿到未消费的新载荷.

            ``aiohttp.FormData`` 装载的请求体是一次性可读的：首次 POST 发送后
            即被消费。若在 ``_submit`` 外只构建一份并闭包复用，重试时会带着
            已处理的残留载荷再次提交而失败。故这里改为每次调用都依据原始
            ``fields`` 重建一份，确保请求可安全重放。

            注意：只有当 ``fields`` 含文件型字段（本地图片，或下载后再上传的
            远程图片）时，正文才是 ``multipart/form-data``；若全部图片都以
            URL 形式传递（``download_urls=False``），``aiohttp.FormData`` 会
            自动退化为 ``application/x-www-form-urlencoded``。
            """
            form = aiohttp.FormData()
            for field in fields:
                if isinstance(field[1], tuple):
                    # 文件字段
                    name, value, content_type = field[1]
                    form.add_field(
                        field[0], value, filename=name, content_type=content_type
                    )
                else:
                    # 普通字段
                    form.add_field(field[0], field[1])
            return form

        async def _submit() -> dict[str, Any]:
            """提交一次编辑任务，非 2xx 转成中文业务异常（不参与重试）."""
            async with session.post(
                f"{self.base_url}/async/images/edits",
                headers=headers,
                data=_build_form(),
            ) as response:
                if response.status != 200:
                    body = mask_text(await response.text())
                    if response.status in (401, 403):
                        raise RuntimeError("API Key 无效或已过期，请检查配置。")
                    if response.status == 429:
                        raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。")
                    if response.status >= 500:
                        raise RuntimeError("Gitee AI 服务器内部错误，请稍后再试。")
                    raise RuntimeError(
                        f"图片编辑失败: HTTP {response.status}"
                        + (f"（响应：{body}）" if body else "")
                    )
                payload: dict[str, Any] = await response.json()
                return payload

        try:
            result = await with_retry(
                _submit,
                max_retries=DEFAULT_MAX_RETRIES,
                label="Gitee AI 图片编辑任务提交",
                on_retry=self._log_retry("图片编辑提交"),
                # 非幂等任务创建：只重放「请求确定未送达上游」的建连类故障，
                # 结果不明的连接重置 / 读取超时一律不重试，避免作业倍增
                should_retry=is_safe_to_replay,
            )

            task_id = result.get("task_id")
            if not task_id:
                raise RuntimeError("未返回任务 ID")

            self.debug_log(f"任务创建成功: task_id={task_id}")

            # 轮询任务状态
            filepath = await self._poll_edit_task(task_id, session, api_key)
            self.debug_log(f"图片编辑完成: {filepath}")

            return filepath

        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"图片编辑失败: {mask_text(e)}")
            raise RuntimeError(f"图片编辑失败：{to_user_message(e)}") from e

    async def _poll_edit_task(
        self,
        task_id: str,
        session,
        api_key: str,
        timeout: int = 30 * 60,
        retry_interval: int = 10,
    ) -> str:
        """轮询图片编辑任务状态.

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

            async def _query() -> dict[str, Any]:
                """查询一次任务状态，非 2xx 转成中文业务异常（不参与重试）."""
                async with session.get(
                    f"{self.base_url}/task/{task_id}",
                    headers=headers,
                    timeout=build_timeout(),
                ) as response:
                    if response.status != 200:
                        if response.status in (401, 403):
                            raise RuntimeError("API Key 无效或已过期，请检查配置。")
                        if response.status >= 500:
                            raise RuntimeError("Gitee AI 服务器内部错误，请稍后再试。")
                        raise RuntimeError(f"任务查询失败: HTTP {response.status}")
                    payload: dict[str, Any] = await response.json()
                    return payload

            try:
                result = await with_retry(
                    _query,
                    max_retries=DEFAULT_MAX_RETRIES,
                    label="Gitee AI 编辑任务状态查询",
                    on_retry=self._log_retry("编辑任务轮询"),
                )

                if result.get("error"):
                    error_msg = result.get("message", "未知错误")
                    raise RuntimeError(f"任务错误: {mask_text(error_msg)}")

                status = result.get("status", "unknown")
                self.debug_log(f"任务状态: {status}")

                if status == "success":
                    if "output" in result and "file_url" in result["output"]:
                        file_url = result["output"]["file_url"]
                        completed_at = result.get("completed_at", 0)
                        started_at = result.get("started_at", 0)
                        duration = (
                            (completed_at - started_at) / 1000
                            if completed_at and started_at
                            else 0
                        )
                        self.debug_log(f"任务完成，耗时: {duration:.2f}秒")
                        # 下载图片
                        return await self.image_manager.download_image(
                            file_url, session
                        )
                    else:
                        raise RuntimeError("任务成功但未返回图片 URL")
                elif status in ["failed", "cancelled"]:
                    raise RuntimeError(f"任务失败: {status}")
                else:
                    # 任务仍在进行中，等待重试
                    await asyncio.sleep(retry_interval)
                    continue

            except RuntimeError:
                raise
            except Exception as e:
                if attempts >= max_attempts:
                    raise RuntimeError(f"任务轮询失败：{to_user_message(e)}") from e
                self.debug_log(f"轮询失败，等待重试: {mask_text(e)}")
                await asyncio.sleep(retry_interval)

        raise RuntimeError(f"任务超时（已等待 {timeout} 秒）")

    async def close(self) -> None:
        """清理资源."""
        self.debug_log("开始清理 API 客户端资源")
        await self.client_manager.close()
        self.debug_log("API 客户端资源清理完成")
