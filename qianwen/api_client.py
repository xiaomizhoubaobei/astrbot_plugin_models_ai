"""千问云（万相 / Qwen-Image / Z-Image）文生图 API 调用模块.

千问云文生图为 DashScope 原生协议，不提供 OpenAI 兼容模式，因此这里用 aiohttp
直接调用原生 REST 接口，不引入 dashscope SDK：

- 同步链路：一次 POST 直接返回图片 URL（z-image-turbo）
- 异步链路：提交任务后按退避策略轮询 ``/tasks/{task_id}``（万相系列）

所有出站请求统一经由 ``core.net_errors`` 处理两件事：

- **指数退避重试**：DNS / 连接超时 / 读取超时 / 连接重置等瞬时故障按
  1s / 2s / 4s 重试（``with_retry``）；证书校验失败等确定性错误快速失败。
- **错误分类脱敏**：不同故障阶段给出可区分的中文提示，且回包前抹掉
  API Key、Bearer token 与 URL query，避免凭证进入聊天窗口。

官方文档见 ``model_config.py`` 顶部注释中的四份链接。
"""

import asyncio
import json
import time
from typing import Any

import aiohttp
from astrbot.api import logger

from ..core import (
    CLEANUP_INTERVAL,
    DEFAULT_MAX_RETRIES,
    QIANWEN_POLL_FAST_WINDOW,
    QIANWEN_POLL_INITIAL_INTERVAL,
    QIANWEN_POLL_MAX_INTERVAL,
    QIANWEN_POLL_TIMEOUT,
    QIANWEN_SUPPORTED_RATIOS,
    ClientManager,
    ImageManager,
    is_safe_to_replay,
    mask_text,
    new_idempotency_key,
    to_user_message,
    with_retry,
)
from .model_config import (
    ENDPOINT_TASK,
    PROMPT_LIMIT_TOKENS,
    QianwenModelSpec,
    get_model_spec,
    list_supported_models,
)


class QianwenResponseError(RuntimeError):
    """200 响应体无法解析为 JSON 对象时抛出.

    与网络故障（可重试）和业务错误（``_build_error`` 产出）区分开：
    这类「响应形状不符合契约」的错误重发请求也不会有收益，属于确定性失败，
    由调用方快速失败并在消息里保留原始片段以便排障。
    """


class QianwenClient:
    """千问云 API 客户端，负责调用文生图 API 并落地图片."""

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
        self.base_url = base_url.rstrip("/")
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
            f"api_keys={len(api_keys)}, prompt_extend={prompt_extend}, "
            f"debug_mode={debug_mode}"
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

    def _build_headers(
        self, api_key: str, is_async: bool = False, idempotency_key: str = ""
    ) -> dict[str, str]:
        """构建请求头.

        Args:
            api_key: API Key
            is_async: 是否为异步任务提交请求，需要带 X-DashScope-Async 头
            idempotency_key: 幂等键（可选），用于「创建任务」类非幂等请求去重；
                同一次逻辑提交的全部重试应复用同一个键

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
        # 幂等键仅在非空时注入，避免污染同步请求的请求头
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _build_input(self, prompt: str, spec: QianwenModelSpec) -> dict[str, Any]:
        """构建请求体中的 input 部分.

        Args:
            prompt: 图片提示词
            spec: 模型能力描述

        Returns:
            input 字段字典

        Note:
            新端点（multimodal-generation）用 ``input.messages`` 传提示词；
            旧端点（text2image/image-synthesis）用 ``input.prompt``。
        """
        if spec.endpoint.startswith("/services/aigc/text2image"):
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
            # 官方建议测试阶段 n 设为 1，同时避免按图计费产生额外花费
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
            prompt: 图片提示词（已按模型上限截断）
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
        safe_prompt = spec.resolve_prompt(prompt)
        if safe_prompt != prompt:
            # 上限计法随模型不同（字符 / token），日志里一并打印，便于对齐官方口径排错
            unit = "token" if spec.prompt_limit_mode == PROMPT_LIMIT_TOKENS else "字符"
            self.debug_log(
                f"提示词超过模型上限 {spec.max_prompt_length} {unit}，已自动截断"
                f"（原 {len(prompt)} 字符 → {len(safe_prompt)} 字符）"
            )

        self.debug_log(
            f"模型调用模式: {spec.call_mode}, 端点: {spec.endpoint}, "
            f"结果格式: {spec.response_format}, 最终尺寸: {target_size}"
        )

        try:
            if spec.call_mode == "async":
                result = await self._generate_async(safe_prompt, target_size, spec)
            else:
                result = await self._generate_sync(safe_prompt, target_size, spec)
        except RuntimeError:
            # 已经是转换过的中文异常，直接向上抛避免二次包装
            raise
        except Exception as e:
            self.debug_log(f"未知错误: {mask_text(e)}")
            raise RuntimeError(f"千问云 API 调用失败: {to_user_message(e)}") from e

        await self._maybe_cleanup()
        return result

    async def _maybe_cleanup(self) -> None:
        """按生成次数触发一次旧图片清理."""
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
        """同步调用链路，适用于 z-image-turbo 等同步模型.

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
        url = f"{self.base_url}{spec.endpoint}"

        self.debug_log(f"发送同步请求: model={self.model}, size={size}")

        timeout = aiohttp.ClientTimeout(total=QIANWEN_POLL_TIMEOUT)

        async def _request() -> dict[str, Any]:
            """执行一次同步请求，非 2xx 直接抛业务异常（不参与重试）."""
            async with session.post(
                url,
                json=payload,
                headers=self._build_headers(api_key),
                timeout=timeout,
            ) as response:
                data = await self._read_json_safely(response, response.status)
                if response.status != 200:
                    raise self._build_error(data, response.status)
                return data

        try:
            # 仅重试连接类瞬时故障；_build_error 抛出的业务异常应快速失败
            data = await with_retry(
                _request,
                max_retries=DEFAULT_MAX_RETRIES,
                label="千问云同步生图请求",
                on_retry=self._log_retry("同步请求"),
            )
        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"同步请求异常: {mask_text(e)}")
            raise RuntimeError(f"千问云请求失败：{to_user_message(e)}") from e

        image_url = self._extract_image_url(data, spec)
        return await self._download(image_url, session)

    async def _generate_async(
        self, prompt: str, size: str, spec: QianwenModelSpec
    ) -> str:
        """异步调用链路，适用于万相系列：提交任务 + 轮询结果.

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

        return await self._poll_task(session, api_key, task_id, spec)

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
        url = f"{self.base_url}{spec.endpoint}"

        self.debug_log(f"提交异步任务: model={self.model}, size={size}, url={url}")

        # Idempotency-Key：任务提交是「创建异步作业」的非幂等 POST，
        # 连接在响应回程中断时若原样重试，会在上游生成孤立的重复任务。
        # 为同一次逻辑提交（含其全部重试）生成并复用同一个幂等键。
        idempotency_key = new_idempotency_key("cnb-qianwen-submit")

        async def _request() -> dict[str, Any]:
            """提交一次任务，非 2xx 抛业务异常（不参与重试）."""
            async with session.post(
                url,
                json=payload,
                headers=self._build_headers(
                    api_key, is_async=True, idempotency_key=idempotency_key
                ),
            ) as response:
                data = await self._read_json_safely(response, response.status)
                if response.status != 200:
                    raise self._build_error(data, response.status)
                return data

        try:
            data = await with_retry(
                _request,
                max_retries=DEFAULT_MAX_RETRIES,
                label="千问云任务提交",
                on_retry=self._log_retry("提交任务"),
                # 非幂等任务创建：只重放「请求确定未送达上游」的建连类故障
                should_retry=is_safe_to_replay,
            )
        except RuntimeError:
            raise
        except Exception as e:
            self.debug_log(f"提交任务异常: {mask_text(e)}")
            raise RuntimeError(f"提交千问云任务失败：{to_user_message(e)}") from e

        task_id = (data.get("output", {}) or {}).get("task_id")
        if not task_id:
            raise RuntimeError("提交任务失败：未返回任务 ID")
        return str(task_id)

    async def _poll_task(
        self,
        session: Any,
        api_key: str,
        task_id: str,
        spec: QianwenModelSpec,
    ) -> str:
        """轮询异步任务直到完成或超时.

        对齐官方建议：先按较短间隔轮询，超过快速窗口后逐步退避，
        累计超过 QIANWEN_POLL_TIMEOUT 判定失败。

        Args:
            session: aiohttp Session
            api_key: API Key
            task_id: 任务 ID
            spec: 模型能力描述（决定结果字段的解析格式）

        Returns:
            图片本地文件路径

        Raises:
            RuntimeError: 任务失败、被取消或超时时抛出中文异常
        """
        url = f"{self.base_url}{ENDPOINT_TASK.format(task_id=task_id)}"
        headers = self._build_headers(api_key)
        start_time = time.time()
        elapsed = 0.0

        while elapsed < QIANWEN_POLL_TIMEOUT:
            data: dict[str, Any] | None = None

            async def _request() -> dict[str, Any]:
                """查询一次任务状态，非 2xx 抛业务异常（不参与重试）."""
                async with session.get(url, headers=headers) as response:
                    payload = await self._read_json_safely(response, response.status)
                    if response.status != 200:
                        raise self._build_error(payload, response.status)
                    return payload

            try:
                data = await with_retry(
                    _request,
                    max_retries=DEFAULT_MAX_RETRIES,
                    label="千问云任务状态查询",
                    on_retry=self._log_retry("轮询"),
                )
            except QianwenResponseError:
                # 轮询端点返回 200 但响应体不符合契约：属确定性失败，
                # 继续空转只会拖到超时，这里立即上抛并保留原始片段。
                raise
            except RuntimeError:
                # _build_error 产出的业务异常（如任务态已 FAILED）同样快速失败
                raise
            except Exception as e:
                # 单次轮询的网络类失败不终止任务，交由下一轮退避重试
                self.debug_log(f"轮询异常: {mask_text(e)}，等待重试")
                data = None

            if data is not None:
                output = data.get("output", {}) or {}
                status = output.get("task_status", "UNKNOWN")
                self.debug_log(f"任务状态 [{elapsed:.0f}s]: {status}")

                if status == "SUCCEEDED":
                    image_url = self._extract_image_url(data, spec)
                    return await self._download(image_url, session)
                if status in ("FAILED", "CANCELED", "CANCELLED"):
                    code = data.get("code") or output.get("code", "未知")
                    message = data.get("message") or output.get("message", "未知错误")
                    # 服务端 message 可能回显请求内容，统一脱敏后再上报
                    raise RuntimeError(
                        f"千问云任务异常终止（状态 {status}），"
                        f"task_id={task_id}, code={mask_text(code)}, "
                        f"message={mask_text(message)}"
                    )

            # 退避策略：快速窗口内高频轮询，之后逐步放宽到最大间隔
            if elapsed < QIANWEN_POLL_FAST_WINDOW:
                interval = QIANWEN_POLL_INITIAL_INTERVAL
            else:
                interval = min(QIANWEN_POLL_MAX_INTERVAL, int(elapsed / 10) + 5)
            await asyncio.sleep(interval)
            elapsed = time.time() - start_time

        raise RuntimeError(
            f"千问云任务超时（已等待 {int(elapsed)} 秒），task_id={task_id}"
        )

    def _extract_image_url(self, data: dict[str, Any], spec: QianwenModelSpec) -> str:
        """从响应体中提取图片 URL.

        兼容两种线上格式：

        - ``choices``（万相 2.6 / z-image）：``output.choices[].message.content[].image``
        - ``results``（万相 2.5 及更早版本）：``output.results[].url``

        即便 ``spec`` 标注的格式没命中，也会回退尝试另一种格式，
        避免因线上字段调整而整条链路不可用。

        Args:
            data: 接口返回的 JSON 字典
            spec: 模型能力描述，指示优先解析哪种格式

        Returns:
            图片 URL

        Raises:
            RuntimeError: 响应中没有图片地址时抛出中文异常
        """
        output = data.get("output", {}) or {}

        # 优先按模型声明的格式解析，其次回退到另一种格式
        orders = (
            ("choices", "results")
            if spec.response_format == "choices"
            else (
                "results",
                "choices",
            )
        )
        for fmt in orders:
            if fmt == "choices":
                for choice in output.get("choices") or []:
                    content = (choice.get("message", {}) or {}).get("content") or []
                    for item in content:
                        if isinstance(item, dict) and item.get("image"):
                            return str(item["image"])
            else:
                for item in output.get("results") or []:
                    if isinstance(item, dict) and item.get("url"):
                        return str(item["url"])

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

    def _log_retry(self, scene: str):
        """构造一个「记录重试」的回调，交给 ``with_retry`` 使用.

        Args:
            scene: 场景名（如「同步请求」「提交任务」「轮询」），用于日志区分

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

    async def _read_json_safely(self, response: Any, status: int) -> dict[str, Any]:
        """读取响应体并安全解析为 JSON 字典.

        上游在 5xx / 网关故障时返回的往往是 HTML 错误页而非 JSON，
        此时先解析再判断状态会抛 ``ContentTypeError`` / ``JSONDecodeError``，
        导致 ``_build_error`` 的准确中文分类被绕过、最终落入泛化的
        「网络请求异常」。这里按状态码分两条路径处理：

        - **非 200**：解析失败（HTML 等）或文本为空时返回空字典，交由
          ``_build_error`` 按状态码给出中文提示，原始片段只进 debug 日志。
        - **200**：响应形状是成功契约的一部分，必须能解析为 JSON 对象。
          文本为空、非 JSON、或顶层不是对象都视为**确定性失败**，抛出
          ``QianwenResponseError`` 并保留截断后的原始片段——否则调用方会拿到
          ``{}`` 继续读必备字段，最终表现为误导性的「未返回图片地址」
          「未返回任务 ID」，或轮询链路对着空对象空转到超时。

        Args:
            response: aiohttp 响应对象
            status: HTTP 状态码，决定解析失败是「交给错误分类」还是「直接失败」

        Returns:
            解析出的字典；非 200 且无法解析时为空字典

        Raises:
            QianwenResponseError: 200 响应体为空 / 非 JSON / 顶层非对象
        """
        # 一次读取原始文本，避免重复消费响应体
        raw = await response.text()

        if status == 200:
            if not raw:
                raise QianwenResponseError("千问云返回空响应体（HTTP 200）")
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                self.debug_log(f"200 响应非 JSON: body={mask_text(raw[:200])}")
                raise QianwenResponseError(
                    "千问云返回的响应无法解析为 JSON（HTTP 200），"
                    f"原始片段：{mask_text(raw[:200])}"
                ) from None
            if not isinstance(parsed, dict):
                self.debug_log(
                    f"200 响应 JSON 顶层非对象: type={type(parsed).__name__}"
                )
                raise QianwenResponseError(
                    "千问云返回的响应顶层不是 JSON 对象（HTTP 200），"
                    f"实际类型：{type(parsed).__name__}"
                )
            return parsed

        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            # 非 JSON（如 502/503 网关的 HTML 错误页）：返回空字典，
            # 让状态码分支决定用户可见提示，原始片段只进 debug 日志。
            self.debug_log(f"响应非 JSON: status={status}, body={mask_text(raw[:200])}")
            return {}

        if not isinstance(parsed, dict):
            self.debug_log(f"响应 JSON 顶层非对象: status={status}")
            return {}
        return parsed

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

        # 内容安全审核未通过（官方文档给出 DataInspectionFailed / IPInfringementSuspect）
        if "DataInspectionFailed" in code or "IPInfringementSuspect" in code:
            return RuntimeError(
                "提示词未通过千问云内容安全审核：可尝试关闭提示词自动改写，"
                "或调整提示词后重试。"
            )

        # 服务端错误
        if status >= 500:
            return RuntimeError("千问云服务器内部错误，请稍后再试。")

        # 其余错误保留服务端原始信息，同时保留上下文（回包前脱敏）
        detail = f"{code} {message}".strip() or f"HTTP {status}"
        logger.debug(f"千问云错误响应: status={status}, detail={mask_text(detail)}")
        return RuntimeError(f"千问云 API 调用失败：{mask_text(detail)}")

    async def get_models(
        self, vendor: str = "", type: str = ""
    ) -> list[dict[str, Any]]:
        """获取千问云已登记的生图模型列表.

        千问云未提供公开的模型列表查询接口，这里返回本地能力表中登记的模型，
        使 text2image 命令在各服务商下表现一致。

        Args:
            vendor: 算力厂商筛选（千问云不支持，仅为保持契约兼容而保留）
            type: 模型类型筛选（千问云不支持，仅为保持契约兼容而保留）

        Returns:
            模型列表，每项包含 id / created / owned_by 字段
        """
        self.debug_log(f"获取千问云模型列表: vendor={vendor}, type={type}")
        return [
            {"id": name, "created": 0, "owned_by": "qianwen"}
            for name in list_supported_models()
        ]

    async def edit_image(self, *args: Any, **kwargs: Any) -> str:
        """千问云暂不支持图片编辑.

        本次仅实现文生图；图片编辑与图生图风格转换仍由 Gitee 服务商提供。
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
