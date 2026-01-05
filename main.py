"""AstrBot AI 图像生成插件

支持 /ai 命令调用，支持多种图片比例和多 Key 轮询。
"""

import time
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter as filter_cmd
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star

from .api_client import GiteeAIClient
from .config import (
    DEFAULT_BASE_URL,
    DEFAULT_INFERENCE_STEPS,
    DEFAULT_MODEL,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_SIZE,
    SUPPORTED_RATIOS,
    parse_api_keys,
)
from .model_manager import ModelLister
from .rate_limiter import RateLimiter


class GiteeAIImage(Star):
    """Gitee AI 图像生成插件

    提供命令行方式生成图片，支持多种图片比例和 API Key 轮询。
    """

    def __init__(self, context: Context, config: dict) -> None:
        """初始化 Gitee AI 图像生成插件

        Args:
            context: AstrBot 上下文对象
            config: 插件配置字典，包含 API Key、模型、图片大小等配置
        """
        super().__init__(context)
        self.config = config
        self.debug_mode = config.get("debug_mode", False)

        self.debug_log("开始初始化插件")

        # 解析配置
        base_url = config.get("base_url", DEFAULT_BASE_URL)
        api_keys = parse_api_keys(config.get("api_key", []))
        model = config.get("model", DEFAULT_MODEL)
        default_size = config.get("size", DEFAULT_SIZE)
        num_inference_steps = config.get("num_inference_steps", DEFAULT_INFERENCE_STEPS)
        negative_prompt = config.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)

        self.debug_log(
            f"配置解析完成: model={model}, size={default_size}, "
            f"api_keys_count={len(api_keys)}, debug_mode={self.debug_mode}"
        )

        # 初始化组件
        self.api_client = GiteeAIClient(
            api_keys=api_keys,
            model=model,
            default_size=default_size,
            num_inference_steps=num_inference_steps,
            negative_prompt=negative_prompt,
            base_url=base_url,
            debug_mode=self.debug_mode,
        )
        self.rate_limiter = RateLimiter(debug_mode=self.debug_mode)
        self.model_lister = ModelLister(
            api_client=self.api_client,
            rate_limiter=self.rate_limiter,
            debug_mode=self.debug_mode,
        )

        self.debug_log("插件初始化完成")

    def _parse_prompt_and_size(self, prompt: str) -> tuple[str, str]:
        """解析提示词和目标尺寸

        从提示词中提取比例参数，并计算目标尺寸。

        Args:
            prompt: 原始提示词，可能包含比例参数（格式：<提示词> [比例]）

        Returns:
            tuple[str, str]: (解析后的提示词, 目标尺寸)

        Raises:
            ValueError: 当提示词为空或仅包含比例时抛出异常
        """
        # 去除首尾空白字符
        prompt = prompt.strip()

        # 检查是否为空
        if not prompt:
            raise ValueError("提示词不能为空")

        # 解析比例参数
        ratio = "1:1"
        prompt_parts = prompt.rsplit(" ", 1)
        if len(prompt_parts) > 1 and prompt_parts[1] in SUPPORTED_RATIOS:
            ratio = prompt_parts[1]
            prompt = prompt_parts[0].strip()

        # 分割后再次检查提示词是否为空
        if not prompt:
            raise ValueError("请提供提示词，不能仅指定比例")

        # 确定目标尺寸
        target_size = self.api_client.default_size
        if ratio != "1:1" or (
            ratio == "1:1" and self.api_client.default_size not in SUPPORTED_RATIOS["1:1"]
        ):
            target_size = SUPPORTED_RATIOS[ratio][0]

        return prompt, target_size

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[AstrBot-GiteeAI] {message}")

    @filter_cmd.command("ai-gitee")
    async def generate_image_command(
        self, event: "AstrMessageEvent", prompt: str
    ) -> AsyncGenerator[Any, None]:
        """生成图片指令（命令行调用）

        通过命令行调用，支持指定图片比例。

        用法: /ai-gitee <提示词> [比例]
        示例: /ai-gitee 一个女孩 9:16
        支持比例: 1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16

        Args:
            event: 消息事件对象
            prompt: 图片提示词，可包含比例参数（格式：<提示词> [比例]）

        Yields:
            生成的图片或错误消息

        Raises:
            Exception: 图片生成失败时抛出异常
        """
        if not prompt:
            self.debug_log("[命令] 收到空提示词")
            yield event.plain_result("请提供提示词！使用方法：/ai-gitee <提示词> [比例]")
            return

        user_id = event.get_sender_id()
        request_id = user_id

        self.debug_log(f"[命令] 收到生图请求: user_id={user_id}, prompt={prompt[:50]}...")

        # 防抖检查
        if self.rate_limiter.check_debounce(request_id):
            self.debug_log(f"[命令] 请求被防抖拦截: user_id={user_id}")
            yield event.plain_result("操作太快了，请稍后再试。")
            return

        if self.rate_limiter.is_processing(request_id):
            self.debug_log(f"[命令] 用户正在处理中: user_id={user_id}")
            yield event.plain_result("您有正在进行的生图任务，请稍候...")
            return

        self.rate_limiter.add_processing(request_id)

        # 解析提示词和目标尺寸
        try:
            prompt, target_size = self._parse_prompt_and_size(prompt)
        except ValueError as e:
            self.debug_log(f"[命令] 参数解析失败: {e}")
            yield event.plain_result(f"{e}。使用方法：/ai-gitee <提示词> [比例]")
            return

        self.debug_log(f"[命令] 解析参数: prompt={prompt[:50]}..., size={target_size}")

        try:
            self.debug_log(f"[命令] 开始生成图片: user_id={user_id}")
            # 先发送提示消息
            yield event.plain_result("正在生成图片，请稍候...")
            start_time = time.time()
            image_path = await self.api_client.generate_image(prompt, size=target_size)
            end_time = time.time()
            elapsed_time = end_time - start_time
            self.debug_log(
                f"[命令] 图片生成成功: path={image_path},"
                f"耗时={elapsed_time:.2f}秒"
            )
            # 将图片和耗时信息合并到一个消息中发送
            yield event.chain_result([
                Image.fromFileSystem(image_path),  # type: ignore
                Plain(f"图片生成完成，耗时：{elapsed_time:.2f}秒")
            ])

        except Exception as e:
            logger.error(f"生图失败: {e}", exc_info=True)
            self.debug_log(f"[命令] 图片生成失败: error={str(e)}")
            yield event.plain_result(f"生成图片失败: {str(e)}")
        finally:
            self.rate_limiter.remove_processing(request_id)
            self.debug_log(f"[命令] 处理完成: user_id={user_id}")

    @filter_cmd.llm_tool(name="draw_image")
    async def draw(self, event: "AstrMessageEvent", prompt: str):
        """根据提示词生成图片。

        Args:
            prompt(str): 图片提示词，需要包含主体、场景、风格等描述
        """
        user_id = event.get_sender_id()
        request_id = user_id

        self.debug_log(f"[LLM工具] 收到生图请求: user_id={user_id}, prompt={prompt[:50]}...")

        # 防抖检查
        if self.rate_limiter.check_debounce(request_id):
            self.debug_log(f"[LLM工具] 请求被防抖拦截: user_id={user_id}")
            return "操作太快了，请稍后再试。"

        if self.rate_limiter.is_processing(request_id):
            self.debug_log(f"[LLM工具] 用户正在处理中: user_id={user_id}")
            return "您有正在进行的生图任务，请稍候..."

        self.rate_limiter.add_processing(request_id)

        # 解析提示词和目标尺寸
        try:
            prompt, target_size = self._parse_prompt_and_size(prompt)
        except ValueError as e:
            self.debug_log(f"[LLM工具] 参数解析失败: {e}")
            return f"{e}。请提供完整的提示词和可选的比例参数。"

        try:
            self.debug_log(f"[LLM工具] 开始生成图片: user_id={user_id}, size={target_size}")
            # 先发送提示消息
            await event.send(event.plain_result("正在生成图片，请稍候..."))
            start_time = time.time()
            image_path = await self.api_client.generate_image(prompt, size=target_size)
            end_time = time.time()
            elapsed_time = end_time - start_time
            self.debug_log(
                f"[LLM工具] 图片生成成功: path={image_path},"
                f"耗时={elapsed_time:.2f}秒"
            )
            # 将图片和耗时信息合并到一个消息中发送
            await event.send(event.chain_result([
                Image.fromFileSystem(image_path),  # type: ignore
                Plain(f"图片生成完成，耗时：{elapsed_time:.2f}秒")
            ]))
            return f"图片已生成并发送。耗时：{elapsed_time:.2f}秒。Prompt: {prompt}"

        except Exception as e:
            logger.error(f"生图失败: {e}", exc_info=True)
            self.debug_log(f"[LLM工具] 图片生成失败: error={str(e)}")
            return f"生成图片时遇到问题: {str(e)}"
        finally:
            self.rate_limiter.remove_processing(request_id)
            self.debug_log(f"[LLM工具] 处理完成: user_id={user_id}")

    @filter_cmd.command("ai-gitee-text2image")
    async def list_models_command(
        self, event: "AstrMessageEvent", type_param: str = ""
    ) -> AsyncGenerator[Any, None]:
        """获取模型列表命令

        支持按类型筛选模型列表。默认返回 text2image 类型模型。

        用法: /ai-gitee-text2image [--type=<类型>]
        示例: /ai-gitee-text2image              # 返回 text2image 类型模型（默认）
              /ai-gitee-text2image --type=all    # 返回所有类型模型
              /ai-gitee-text2image --type=text2text

        支持类型:
        - all: 所有类型
        - text2image: 文本生成图像（默认）
        - text2text: 文本生成文本
        - embeddings: 向量嵌入生成
        - image2text: 图像转文本
        - speech2text: 语音转文本
        - text2speech: 文本转语音
        - completions: 补全任务
        - image2image: 图像生成图像
        - voice_feature_extraction: 语音特征提取
        - sentence_similarity: 句子相似度计算
        - rerank: 重排序
        - image_matting: 图像抠图
        - text2video: 文本生成视频
        - image2video: 图像生成视频
        - doc2md: 文档转 Markdown
        - text23d: 文本生成 3D 模型
        - image23d: 图像生成 3D 模型
        - rerank_multimodal: 多模态重排序
        - text2music: 文本生成音乐
        - image_video2video: 图像/视频生成视频
        - audio_video2video: 音频/视频生成视频

        Args:
            event: 消息事件对象
            type_param: 模型类型参数（可选），格式：--type=<类型>

        Yields:
            模型列表或错误消息
        """
        user_id = event.get_sender_id()
        request_id = user_id

        self.debug_log(f"[模型列表] 收到请求: user_id={user_id}, type_param={type_param}")

        # 防抖检查
        if self.rate_limiter.check_debounce(request_id):
            self.debug_log(f"[模型列表] 请求被防抖拦截: user_id={user_id}")
            yield event.plain_result("操作太快了，请稍后再试。")
            return

        if self.rate_limiter.is_processing(request_id):
            self.debug_log(f"[模型列表] 用户正在处理中: user_id={user_id}")
            yield event.plain_result("您有正在进行的请求，请稍候...")
            return

        self.rate_limiter.add_processing(request_id)

        try:
            # 使用 ModelLister 获取模型列表
            success, result = await self.model_lister.list_models(type_param)
            yield event.plain_result(result)
        finally:
            self.rate_limiter.remove_processing(request_id)
            self.debug_log(f"[模型列表] 处理完成: user_id={user_id}")

    async def close(self) -> None:
        """清理插件资源

        在插件卸载时调用，关闭所有客户端连接和释放资源。
        """
        self.debug_log("开始清理插件资源")
        await self.api_client.close()
        self.debug_log("插件资源清理完成")
