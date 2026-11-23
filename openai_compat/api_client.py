"""通用 OpenAI 兼容上游 API 调用模块.

面向任意实现 OpenAI ``/v1/images/generations`` 与 ``/v1/models`` 协议的服务商：
仅依赖 ``base_url`` / ``api_key`` / ``model`` 三要素，不夹带 Gitee 或千问云
专有参数。请求重试、异常脱敏、取图出站白名单统一复用 ``core`` 层能力。
"""

import asyncio
from typing import Any, Optional

import aiohttp
from astrbot.api import logger
from openai import APIError, AuthenticationError, RateLimitError

from ..core import (
    CLEANUP_INTERVAL,
    DEFAULT_MAX_RETRIES,
    SUPPORTED_RATIOS,
    ClientManager,
    ImageManager,
    describe_http_status,
    mask_text,
    to_user_message,
    with_retry,
)


class OpenAICompatibleClient:
    """通用 OpenAI 兼容上游客户端.

    与 ``GiteeAIClient`` 遵循同一套能力契约：多 Key 轮询、URL / Base64 两种
    生图结果落地、模型列表查询、标准图片编辑，并按约定周期清理过期图片。
    """

    def __init__(
        self,
        api_keys: list[str],
        model: str,
        default_size: str,
        base_url: str,
        debug_mode: bool = False,
        extra_body: Optional[dict[str, Any]] = None,
        allowed_image_hosts: Optional[list[str]] = None,
        allow_any_image_host: bool = False,
    ) -> None:
        """初始化通用 OpenAI 兼容上游客户端.

        Args:
            api_keys: API Keys 列表，按顺序轮询使用
            model: 模型名称
            default_size: 默认图片尺寸（宽x高）
            base_url: 上游 API 基础地址，例如 ``https://api.example.com/v1``
            debug_mode: 是否启用 Debug 日志
            extra_body: 需要透传给上游的额外请求体（可选）
            allowed_image_hosts: 用户额外追加的可信取图主机白名单
            allow_any_image_host: 是否关闭取图主机校验（显式配置才生效）
        """
        self.debug_mode = debug_mode
        self.api_keys = api_keys
        self.model = model
        self.default_size = default_size
        self.base_url = base_url
        self.extra_body = extra_body if extra_body else {}

        # 供 parse_prompt_and_size 读取，使比例解析沿用通用尺寸表
        self.supported_ratios = SUPPORTED_RATIOS

        self.client_manager = ClientManager(base_url, debug_mode=debug_mode)
        self.image_manager = ImageManager(
            debug_mode=debug_mode,
            allowed_image_hosts=allowed_image_hosts,
            provider_base_url=base_url,
            allow_any_image_host=allow_any_image_host,
        )

        self.current_key_index = 0
        self._generation_count = 0
        self._background_tasks: set[asyncio.Task[Any]] = set()

        self.debug_log(
            f"初始化 OpenAI 兼容上游客户端: model={model}, size={default_size}, "
            f"base_url={mask_text(base_url, limit=80)}, api_keys={len(api_keys)}"
        )

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志.

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[OpenAICompatibleClient] {message}")

    def _get_next_api_key(self) -> str:
        """轮询获取下一个 API Key.

        Returns:
            API Key

        Raises:
            ValueError: 未配置 API Key 时抛出
        """
        if not self.api_keys:
            raise ValueError("请先配置 API Key")

        index = self.current_key_index
        api_key = self.api_keys[index]
        self.current_key_index = (index + 1) % len(self.api_keys)
        # 安全约定：调试日志绝不回显 API Key 内容，仅记录轮询索引
        self.debug_log(f"轮询 API Key: index={index}")
        return api_key

    def _log_retry(self, scene: str):
        """构造重试日志回调，交给 ``with_retry`` 使用.

        Args:
            scene: 场景名（如「生图请求」）

        Returns:
            回调，签名为 ``(第几次重试, 退避秒数, 异常)``
        """

        def _callback(attempt: int, delay: float, exc: BaseException) -> None:
            """记录一次重试，异常文本已脱敏."""
            self.debug_log(
                f"{scene} 失败，第 {attempt}/{DEFAULT_MAX_RETRIES} 次重试"
                f"（{delay:.0f}s 后）: {type(exc).__name__} - {mask_text(exc)}"
            )

        return _callback

    def _maybe_cleanup(self) -> None:
        """每 N 次生成触发一次过期图片清理，并保留任务引用防止被 GC 回收."""
        self._generation_count += 1
        if self._generation_count < CLEANUP_INTERVAL:
            return
        self._generation_count = 0
        self.debug_log("触发图片清理任务")
        task = asyncio.create_task(self.image_manager.cleanup_old_images())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _download_remote_image(self, url: str, session: Any) -> tuple[bytes, str]:
        """下载远程图片，经出站白名单校验与统一错误分类.

        Args:
            url: 远程图片 URL
            session: aiohttp Session

        Returns:
            ``(图片字节, MIME 类型)`` 元组

        Raises:
            RuntimeError: 白名单拒绝、非 2xx 或网络异常时抛出
        """
        # 复用 ImageManager 的白名单判定，保持与生图结果取图一致的安全口径
        from ..core.url_guard import check_image_url, extract_host

        if self.image_manager._enforce_host_check:
            allowed, reason = check_image_url(
                url,
                self.image_manager._allowed_hosts,
                allow_any=self.image_manager._allow_any_image_host,
            )
            if not allowed:
                self.debug_log(f"取图被出站白名单拒绝: host={extract_host(url)}")
                raise RuntimeError(f"下载待编辑图片失败：{reason}")

        async def _fetch() -> tuple[bytes, str]:
            """拉取一次远程图片，非 200 视为确定性业务失败."""
            async with session.get(url) as response:
                if response.status != 200:
                    raise RuntimeError(
                        "下载待编辑图片失败："
                        f"{describe_http_status(response.status)}"
                    )
                content = await response.read()
                mime = response.headers.get("Content-Type", "application/octet-stream")
                return content, mime

        try:
            return await with_retry(
                _fetch,
                max_retries=DEFAULT_MAX_RETRIES,
                label="远程图片下载",
                on_retry=self._log_retry("远程图片下载"),
            )
        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"下载失败: {mask_text(e)}")
            raise RuntimeError(f"下载待编辑图片失败：{to_user_message(e)}") from e

    async def generate_image(self, prompt: str, size: str = "") -> str:
        """调用上游 ``images/generations`` 生成图片并返回本地文件路径.

        Args:
            prompt: 图片提示词
            size: 图片尺寸（可选，缺省用配置值）

        Returns:
            生成的图片本地文件路径

        Raises:
            RuntimeError: 上游调用失败或响应无图片数据时抛出
        """
        target_size = size or self.default_size
        self.debug_log(f"开始生成图片: prompt={prompt[:50]}..., size={target_size}")

        api_key = self._get_next_api_key()
        client = self.client_manager.get_openai_client(api_key)

        kwargs: dict[str, Any] = {"prompt": prompt, "model": self.model}
        if target_size:
            kwargs["size"] = target_size
        # 额外请求体仅在用户显式配置时透传，避免把某家上游的私有字段强加给别家
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body

        async def _request():
            """执行一次生图请求，SDK 异常交由外层统一分类."""
            return await client.images.generate(**kwargs)  # type: ignore

        try:
            response = await with_retry(
                _request,
                max_retries=DEFAULT_MAX_RETRIES,
                label="OpenAI 兼容上游生图请求",
                on_retry=self._log_retry("生图请求"),
            )
        except AuthenticationError as e:
            self.debug_log(f"API 认证失败: {mask_text(e)}")
            raise RuntimeError("API Key 无效或已过期，请检查配置。") from e
        except RateLimitError as e:
            self.debug_log(f"API 速率限制: {mask_text(e)}")
            raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。") from e
        except APIError as e:
            self.debug_log(f"API 错误: {mask_text(e)}")
            if e.status_code == 500:
                raise RuntimeError("上游服务器内部错误，请稍后再试。") from e
            raise RuntimeError(f"API调用失败：{to_user_message(e)}") from e
        except Exception as e:
            self.debug_log(f"未知错误: {mask_text(e)}")
            raise RuntimeError(f"API调用失败：{to_user_message(e)}") from e

        if not response.data:  # type: ignore
            raise RuntimeError("生成图片失败：未返回数据")

        image_data = response.data[0]  # type: ignore
        filepath = ""
        if getattr(image_data, "url", None):
            self.debug_log("图片数据格式: URL")
            session = await self.client_manager.get_http_session()
            filepath = await self.image_manager.download_image(image_data.url, session)
        elif getattr(image_data, "b64_json", None):
            self.debug_log("图片数据格式: Base64")
            filepath = await self.image_manager.save_base64_image(image_data.b64_json)
        else:
            raise RuntimeError("生成图片失败：未返回 URL 或 Base64 数据")

        self.debug_log(f"图片保存成功: {filepath}")
        self._maybe_cleanup()
        return filepath

    async def get_models(
        self, vendor: str = "", type: str = ""
    ) -> list[dict[str, Any]]:
        """查询上游 ``/models`` 模型列表.

        Args:
            vendor: 算力厂商筛选（OpenAI 协议不支持，仅为契约兼容保留）
            type: 模型类型筛选（OpenAI 协议不支持，仅为契约兼容保留）

        Returns:
            模型列表，每项包含 id / created / owned_by

        Raises:
            RuntimeError: 查询失败时抛出中文异常
        """
        self.debug_log(f"开始获取模型列表: vendor={vendor}, type={type}")

        api_key = self._get_next_api_key()
        session = await self.client_manager.get_http_session()
        headers = {"Authorization": f"Bearer {api_key}"}
        url = f"{self.base_url.rstrip('/')}/models"

        async def _request() -> dict[str, Any]:
            """拉取一次模型列表，非 2xx 转成确定性业务异常（不参与重试）."""
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    body = mask_text(await response.text())
                    if response.status in (401, 403):
                        raise RuntimeError("API Key 无效或已过期，请检查配置。")
                    if response.status == 429:
                        raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。")
                    if response.status >= 500:
                        raise RuntimeError("上游服务器内部错误，请稍后再试。")
                    raise RuntimeError(
                        f"获取模型列表失败：{describe_http_status(response.status)}"
                        + (f"（响应：{body}）" if body else "")
                    )
                payload: dict[str, Any] = await response.json()
                return payload

        try:
            data = await with_retry(
                _request,
                max_retries=DEFAULT_MAX_RETRIES,
                label="OpenAI 兼容上游模型列表请求",
                on_retry=self._log_retry("模型列表请求"),
            )
        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"API 调用失败: {mask_text(e)}")
            raise RuntimeError(f"API调用失败：{to_user_message(e)}") from e

        models = data.get("data", []) or []
        result: list[dict[str, Any]] = []
        for model in models:
            result.append(
                {
                    "id": model.get("id", ""),
                    "created": model.get("created", 0),
                    "owned_by": model.get("owned_by", ""),
                }
            )
        self.debug_log(f"模型列表获取成功: count={len(result)}")
        return result

    async def edit_image(
        self,
        prompt: str,
        image_paths: list[str],
        task_types: list[str] | None = None,
        model: str = "",
        num_inference_steps: int = 4,
        guidance_scale: float = 1.0,
        download_urls: bool = False,
    ) -> str:
        """调用上游标准 ``images/edits`` 编辑图片并返回本地文件路径.

        仅接受本地图片文件；远程 URL 会先下载到内存再上传。``task_types`` /
        ``num_inference_steps`` / ``guidance_scale`` 属 Gitee 专有参数，在标准
        OpenAI 协议中无对应字段，这里仅接收以保证命令层契约一致，不透传。

        Args:
            prompt: 编辑提示词
            image_paths: 本地图片路径或 http(s) 图片 URL
            task_types: 任务类型（未使用，保持命令层契约一致）
            model: 编辑模型名，留空时复用当前生图模型
            num_inference_steps: 推理步数（未使用）
            guidance_scale: 引导系数（未使用）
            download_urls: 是否下载远程图片后再上传（标准接口必须上传文件）

        Returns:
            编辑后的图片本地文件路径

        Raises:
            RuntimeError: 上游调用失败或响应无图片数据时抛出
        """
        del task_types, num_inference_steps, guidance_scale, download_urls
        self.debug_log(
            f"开始编辑图片: prompt={prompt[:50]}..., images={len(image_paths)}"
        )

        api_key = self._get_next_api_key()
        client = self.client_manager.get_openai_client(api_key)
        payloads: list[tuple[str, bytes, str]] = []
        for filepath in image_paths:
            name = filepath.rsplit("/", 1)[-1] or "image.png"
            if filepath.startswith(("http://", "https://")):
                # 远程图片由消息发送方控制，先按出站白名单校验防 SSRF，
                # 再下载到内存上传（标准 images/edit 只收 multipart 文件）
                session = await self.client_manager.get_http_session()
                content, mime = await self._download_remote_image(filepath, session)
                payloads.append((name, content, mime))
            else:
                with open(filepath, "rb") as handle:
                    payloads.append(
                        (name, handle.read(), "application/octet-stream")
                    )

        async def _request():
            """执行一次标准图片编辑请求."""
            return await client.images.edit(  # type: ignore
                model=model or self.model,
                prompt=prompt,
                image=payloads,
                size=self.default_size or None,
            )

        try:
            response = await with_retry(
                _request,
                max_retries=DEFAULT_MAX_RETRIES,
                label="OpenAI 兼容上游图片编辑请求",
                on_retry=self._log_retry("图片编辑请求"),
            )
        except AuthenticationError as e:
            raise RuntimeError("API Key 无效或已过期，请检查配置。") from e
        except RateLimitError as e:
            raise RuntimeError("API 调用次数超限或并发过高，请稍后再试。") from e
        except APIError as e:
            if e.status_code == 500:
                raise RuntimeError("上游服务器内部错误，请稍后再试。") from e
            raise RuntimeError(f"API调用失败：{to_user_message(e)}") from e
        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"未知错误: {mask_text(e)}")
            raise RuntimeError(f"API调用失败：{to_user_message(e)}") from e

        if not response.data:  # type: ignore
            raise RuntimeError("图片编辑失败：未返回数据")
        image_data = response.data[0]  # type: ignore
        if getattr(image_data, "url", None):
            session = await self.client_manager.get_http_session()
            filepath = await self.image_manager.download_image(image_data.url, session)
        elif getattr(image_data, "b64_json", None):
            filepath = await self.image_manager.save_base64_image(image_data.b64_json)
        else:
            raise RuntimeError("图片编辑失败：未返回 URL 或 Base64 数据")

        self.debug_log(f"图片编辑结果保存成功: {filepath}")
        self._maybe_cleanup()
        return filepath

    async def close(self) -> None:
        """释放客户端占用的资源."""
        self.debug_log("开始清理 OpenAI 兼容上游客户端资源")
        await self.client_manager.close()
        self.debug_log("OpenAI 兼容上游客户端资源清理完成")
