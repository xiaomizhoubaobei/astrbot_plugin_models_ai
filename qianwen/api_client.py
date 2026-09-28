"""千问云文生图 API 调用模块.

负责千问云（Qwen / DashScope）图像生成 API 的调用和错误处理。

千问文生图为 DashScope 原生接口（不支持 OpenAI 兼容模式），因此这里使用 aiohttp
直接调用原生 REST 接口，不引入 dashscope SDK：

- 同步链路：Qwen-Image 系列，一次 POST 请求直接返回图片 URL
- 异步链路：Wan 系列，提交任务后按退避策略轮询 task_status 直到 SUCCEEDED

官方文档：https://platform.qianwenai.com/docs/developer-guides/image-generation/text-to-image
"""

import asyncio
import time
from typing import Any

import aiohttp
from astrbot.api import logger

from ..core import (
    QIANWEN_POLL_FAST_WINDOW,
    QIANWEN_POLL_INITIAL_INTERVAL,
    QIANWEN_POLL_MAX_INTERVAL,
    QIANWEN_POLL_TIMEOUT,
    QIANWEN_SUPPORTED_RATIOS,
    ClientManager,
    ImageManager,
)
from .model_config import QianwenModelSpec, get_model_spec, list_supported_models


class QianwenClient:
    """千问云 API 客户端，负责调用图像生成 API."""

    def __init__(
        self,
        api_keys: list[str],
        model: str,
        default_size: str,
        negative_prompt: str,
        base_url: str,
        prompt_extend: bool = True,
        debug_mode: bool = False,
    ) -> None:
        """初始化千问云客户端.

        Args:
            api_keys: API Keys 列表
            model: 模型名称
            default_size: 默认图片大小，格式为「宽*高」
            negative_prompt: 负面提示词
            base_url: API 基础 URL
            prompt_extend: 是否启用提示词自动改写
            debug_mode: 是否启用 Debug 日志
        """
        self.debug_mode = debug_mode
        self.api_keys = api_keys
        self.model = model
        self.default_size = default_size
        self.negative_prompt = negative_prompt
        self.base_url = base_url
        self.prompt_extend = prompt_extend

        # 供 parse_prompt_and_size 读取，使比例映射随服务商切换
        self.supported_ratios = QIANWEN_SUPPORTED_RATIOS

        self.client_manager = ClientManager(base_url, debug_mode=debug_mode)
        self.image_manager = ImageManager(debug_mode=debug_mode)

        self.current_key_index = 0
        self._generation_count = 0
        self._background_tasks: set[asyncio.Task[Any]] = set()

        self.debug_log(
            f"初始化千问云客户端: model={model}, size={default_size}, "
            f"api_keys={len(api_keys)}, debug_mode={debug_mode}"
        )

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志.

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[QianwenClient] {message}")

    def _get_next_api_key(self) -> str:
        """轮询获取下一个 API Key.

        Returns:
            API Key

        Raises:
            ValueError: 当没有配置 API Key 时抛出异常
        """
        if not self.api_keys:
            raise ValueError("请先配置千问云 API Key")

        api_key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self.debug_log(f"轮询 API Key: api_key={api_key[:10]}...")
        return api_key

    def _build_headers(self, api_key: str, is_async: bool = False) -> dict[str, str]:
        """构建请求头.

        Args:
            api_key: API Key
            is_async: 是否为异步任务提交请求，需要带 X-DashScope-Async 头

        Returns:
            请求头字典
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        # 异步任务提交必须显式声明，否则服务端会按同步阻塞处理
        if is_async:
            headers["X-DashScope-Async"] = "enable"
        return headers

    def _build_input(self, prompt: str, spec: QianwenModelSpec) -> dict[str, Any]:
        """构建请求体中的 input 部分.

        Args:
            prompt: 图片提示词
            spec: 模型能力描述

        Returns:
            input 字段字典

        Note:
            Qwen-Image、Wan 2.7、wan2.6-t2i 通过 input.messages 传提示词，
            Wan 2.5 及更早版本通过 input.prompt 传。
        """
        if spec.prompt_field == "prompt":
            return {"prompt": prompt}
        return {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        }

    def _build_parameters(self, size: str, spec: QianwenModelSpec) -> dict[str, Any]:
        """构建请求体中的 parameters 部分，并按模型能力裁剪参数.

        Args:
            size: 目标尺寸，格式为「宽*高」
            spec: 模型能力描述

        Returns:
            parameters 字段字典
        """
        parameters: dict[str, Any] = {
            "size": size,
            # 官方文档建议测试阶段 n 设为 1，同时避免重复计费
            "n": 1,
        }

        # negative_prompt 仅部分模型支持，不支持的模型传参会直接报错
        if self.negative_prompt and spec.supports_negative_prompt:
            parameters["negative_prompt"] = self.negative_prompt

        # prompt_extend 同样仅部分模型支持
        if self.prompt_extend and spec.supports_prompt_extend:
            parameters["prompt_extend"] = True

        return parameters

    def _build_payload(
        self, prompt: str, size: str, spec: QianwenModelSpec
    ) -> dict[str, Any]:
        """构建完整的请求体.

        Args:
            prompt: 图片提示词
            size: 目标尺寸
            spec: 模型能力描述

        Returns:
            请求体字典
        """
        return {
            "model": self.model,
            "input": self._build_input(prompt, spec),
            "parameters": self._build_parameters(size, spec),
        }

    def _resolve_size(self, size: str, spec: QianwenModelSpec) -> str:
        """确定最终下发给模型的尺寸，越界时降级到模型默认值.

        Args:
            size: 期望尺寸
            spec: 模型能力描述

        Returns:
            验收通过的尺寸字符串
        """
        target = size if size else self.default_size
        resolved = spec.resolve_size(target)
        if resolved != target:
            self.debug_log(
                f"尺寸 {target} 不被模型 {self.model} 支持，降级为 {resolved}"
            )
        return resolved

    async def generate_image(self, prompt: str, size: str = "") -> str:
        """调用千问云 API 生成图片，返回本地文件路径.

        Args:
            prompt: 图片提示词
            size: 图片大小（可选），格式为「宽*高」

        Returns:
            生成的图片本地文件路径

        Raises:
            RuntimeError: API 调用失败时抛出中文异常
        """
        self.debug_log(f"开始生成图片: prompt={prompt[:50]}..., size={size}")

        spec = get_model_spec(self.model)
        target_size = self._resolve_size(size, spec)
        self.debug_log(f"模型调用模式: {spec.call_mode}, 最终尺寸: {target_size}")

        try:
            if spec.call_mode == "async":
                result = await self._generate_async(prompt, target_size, spec)
            else:
                result = await self._generate_sync(prompt, target_size, spec)
        except RuntimeError:
            # 已经是转换过的中文异常，直接向上抛避免二次包装
            raise
        except Exception as e:
            self.debug_log(f"未知错误: {e}")
            raise RuntimeError(f"千问云 API 调用失败: {e}") from e

        await self._maybe_cleanup()
        return result

    async def _maybe_cleanup(self) -> None:
        """按生成次数触发一次旧图片清理."""
        from ..core import CLEANUP_INTERVAL

        self._generation_count += 1
        if self._generation_count >= CLEANUP_INTERVAL:
            self._generation_count = 0
            self.debug_log("触发图片清理任务")
            task = asyncio.create_task(self.image_manager.cleanup_old_images())
            # 保存任务引用防止被 GC 提前回收
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _generate_sync(
        self, prompt: str, size: str, spec: QianwenModelSpec
    ) -> str:
        """同步调用链路，适用于 Qwen-Image 系列.

        Args:
            prompt: 图片提示词
            size: 目标尺寸
            spec: 模型能力描述

        Returns:
            图片本地文件路径

        Raises:
            RuntimeError: 调用失败时抛出中文异常
        """
        api_key = self._get_next_api_key()
        session = await self.client_manager.get_http_session()
        payload = self._build_payload(prompt, size, spec)
        url = f"{self.base_url}/services/aigc/multimodal-generation/generation"

        self.debug_log(f"发送同步请求: model={self.model}, size={size}")

        timeout = aiohttp.ClientTimeout(total=QIANWEN_POLL_TIMEOUT)
        try:
            async with session.post(
                url,
                json=payload,
                headers=self._build_headers(api_key),
                timeout=timeout,
            ) as response:
                data = await response.json(content_type=None)
                if response.status != 200:
                    raise self._build_error(data, response.status)
        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"同步请求异常: {e}")
            raise RuntimeError(f"千问云请求失败: {e}") from e

        image_url = self._extract_image_url(data)
        return await self._download(image_url, session)

    async def _generate_async(
        self, prompt: str, size: str, spec: QianwenModelSpec
    ) -> str:
        """异步调用链路，适用于 Wan 系列：提交任务 + 轮询结果.

        Args:
            prompt: 图片提示词
            size: 目标尺寸
            spec: 模型能力描述

        Returns:
            图片本地文件路径

        Raises:
            RuntimeError: 任务失败或超时时抛出中文异常
        """
        api_key = self._get_next_api_key()
        session = await self.client_manager.get_http_session()

        task_id = await self._submit_task(session, api_key, prompt, size, spec)
        self.debug_log(f"异步任务已提交: task_id={task_id}")

        return await self._poll_task(session, api_key, task_id)

    async def _submit_task(
        self,
        session: Any,
        api_key: str,
        prompt: str,
        size: str,
        spec: QianwenModelSpec,
    ) -> str:
        """提交异步生图任务.

        Args:
            session: aiohttp Session
            api_key: API Key
            prompt: 图片提示词
            size: 目标尺寸
            spec: 模型能力描述

        Returns:
            任务 ID

        Raises:
            RuntimeError: 提交失败时抛出中文异常
        """
        payload = self._build_payload(prompt, size, spec)
        url = f"{self.base_url}/services/aigc/image-generation/generation"

        self.debug_log(f"提交异步任务: model={self.model}, size={size}")

        try:
            async with session.post(
                url,
                json=payload,
                headers=self._build_headers(api_key, is_async=True),
            ) as response:
                data = await response.json(content_type=None)
                if response.status != 200:
                    raise self._build_error(data, response.status)
        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"提交任务异常: {e}")
            raise RuntimeError(f"提交千问云任务失败: {e}") from e

        task_id = data.get("output", {}).get("task_id")
        if not task_id:
            raise RuntimeError("提交任务失败：未返回任务 ID")
        return task_id

    async def _poll_task(self, session: Any, api_key: str, task_id: str) -> str:
        """轮询异步任务直到完成或超时.

        对齐官方建议：前 30 秒每 3 秒轮询一次，之后逐步延长间隔，
        超过总超时则判定失败。

        Args:
            session: aiohttp Session
            api_key: API Key
            task_id: 任务 ID

        Returns:
            图片本地文件路径

        Raises:
            RuntimeError: 任务失败、被取消或超时时抛出中文异常
        """
        url = f"{self.base_url}/tasks/{task_id}"
        headers = self._build_headers(api_key)
        start_time = time.time()
        elapsed = 0.0

        while elapsed < QIANWEN_POLL_TIMEOUT:
            try:
                async with session.get(url, headers=headers) as response:
                    data = await response.json(content_type=None)
                    if response.status != 200:
                        raise self._build_error(data, response.status)
            except RuntimeError:
                raise
            except Exception as e:
                self.debug_log(f"轮询异常: {e}，等待重试")
                data = None

            if data is not None:
                output = data.get("output", {}) or {}
                status = output.get("task_status", "UNKNOWN")
                self.debug_log(f"任务状态 [{elapsed:.0f}s]: {status}")

                if status == "SUCCEEDED":
                    image_url = self._extract_image_url(data)
                    return await self._download(image_url, session)
                if status in ("FAILED", "CANCELED"):
                    code = data.get("code") or output.get("code", "未知")
                    message = data.get("message") or output.get("message", "未知错误")
                    raise RuntimeError(
                        f"千问云任务异常终止（状态 {status}），"
                        f"task_id={task_id}, code={code}, message={message}"
                    )

            # 退避策略：快速窗口内高频轮询，之后逐步放宽到最大间隔
            if elapsed < QIANWEN_POLL_FAST_WINDOW:
                interval = QIANWEN_POLL_INITIAL_INTERVAL
            else:
                interval = min(QIANWEN_POLL_MAX_INTERVAL, int(elapsed / 10) + 3)
            await asyncio.sleep(interval)
            elapsed = time.time() - start_time

        raise RuntimeError(
            f"千问云任务超时（已等待 {int(elapsed)} 秒），task_id={task_id}"
        )

    def _extract_image_url(self, data: dict[str, Any]) -> str:
        """从响应体中提取图片 URL.

        Args:
            data: 接口返回的 JSON 字典

        Returns:
            图片 URL

        Raises:
            RuntimeError: 响应中没有图片地址时抛出中文异常
        """
        choices = (data.get("output", {}) or {}).get("choices") or []
        for choice in choices:
            content = (choice.get("message", {}) or {}).get("content") or []
            for item in content:
                if isinstance(item, dict) and item.get("image"):
                    return str(item["image"])
        raise RuntimeError("生成图片失败：响应中未返回图片地址")

    async def _download(self, image_url: str, session: Any) -> str:
        """下载图片到本地.

        官方文档明确图片 URL 24 小时后过期，因此拿到结果后必须立即落盘。

        Args:
            image_url: 图片 URL
            session: aiohttp Session

        Returns:
            本地文件路径
        """
        self.debug_log(f"开始下载图片: url={image_url[:60]}...")
        filepath = await self.image_manager.download_image(image_url, session)
        self.debug_log(f"图片保存成功: {filepath}")
        return filepath

    def _build_error(self, data: dict[str, Any], status: int) -> RuntimeError:
        """把接口错误转换为面向用户的中文异常.

        Args:
            data: 接口返回的 JSON 字典
            status: HTTP 状态码

        Returns:
            已构造好的 RuntimeError
        """
        code = str(data.get("code", "") or "")
        message = str(data.get("message", "") or "")

        # 认证类错误
        if status in (401, 403) or code in ("InvalidApiKey", "Unauthorized"):
            return RuntimeError("千问云 API Key 无效或已过期，请检查配置。")

        # 限流类错误
        if status == 429 or "Throttling" in code or "Throttling" in message:
            return RuntimeError("千问云 API 调用次数超限或并发过高，请稍后再试。")

        # 内容安全审核未通过
        if "DataInspectionFailed" in code or "DataInspectionFailed" in message:
            return RuntimeError("提示词未通过千问云内容安全审核，请更换描述后重试。")

        # 服务端错误
        if status >= 500:
            return RuntimeError("千问云服务器内部错误，请稍后再试。")

        # 其余错误保留服务端原始信息，同时保留上下文
        detail = f"{code} {message}".strip() or f"HTTP {status}"
        logger.debug(f"千问云错误响应: status={status}, detail={detail}")
        return RuntimeError(f"千问云 API 调用失败: {detail}")

    async def get_models(
        self, vendor: str = "", type: str = ""
    ) -> list[dict[str, Any]]:
        """获取千问云已登记的生图模型列表.

        千问云未提供公开的模型列表查询接口，这里返回本地能力表中登记的模型，
        保证 text2image 命令与 Gitee 服务商表现一致。

        Args:
            vendor: 算力厂商筛选（千问不支持，仅为保持签名兼容而保留）
            type: 模型类型筛选（千问不支持，仅为保持签名兼容而保留）

        Returns:
            模型列表，每项包含 id / created / owned_by 字段
        """
        self.debug_log(f"获取千问云模型列表: vendor={vendor}, type={type}")
        return [
            {"id": name, "created": 0, "owned_by": "qwen"}
            for name in list_supported_models()
        ]

    async def edit_image(self, *args: Any, **kwargs: Any) -> str:
        """千问云暂不支持图片编辑.

        本次仅实现文生图；图片编辑与风格转换仍由 Gitee 服务商提供。
        这里显式抛出中文异常，避免切换服务商后出现难以理解的 AttributeError。

        Args:
            args: 位置参数（未使用）
            kwargs: 关键字参数（未使用）

        Returns:
            永不返回

        Raises:
            RuntimeError: 始终抛出，提示当前服务商不支持该能力
        """
        raise RuntimeError(
            "当前服务商为千问云，暂不支持图片编辑功能。"
            "如需使用 AI 编辑或图生图风格转换，请将 provider 切换为 gitee。"
        )

    async def close(self) -> None:
        """清理资源."""
        self.debug_log("开始清理千问云客户端资源")
        await self.client_manager.close()
        self.debug_log("千问云客户端资源清理完成")
