"""AstrBot AI 图像生成插件

支持 /ai 命令调用，支持多种图片比例和多 Key 轮询。
"""

from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter as filter_cmd
from astrbot.api.star import Context, Star
from .commands import generate_image_command, list_models_command, help_command, switch_model_command
from .core import (
    DEFAULT_BASE_URL,
    DEFAULT_INFERENCE_STEPS,
    DEFAULT_MODEL,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_SIZE,
    SUPPORTED_RATIOS,
    RateLimiter,
    parse_api_keys,
)
from .gitee import GiteeAIClient, ModelLister
from .llm_tools import draw_image_tool


class AIImage(Star):
    """AI 图像生成插件

    提供命令行方式生成图片，支持多种图片比例和 API Key 轮询。
    """

    def __init__(self, context: Context, config: dict) -> None:
        """初始化  AI 图像生成插件

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

    @filter_cmd.command_group("ai-gitee")
    async def ai_gitee_group(self):
        """ai-gitee 指令组，提供 AI 图像生成和模型查询功能"""
        pass

    @ai_gitee_group.command("help")
    async def help_command_wrapper(self, event: "AstrMessageEvent"):
        """显示帮助信息

        用法: /ai-gitee help

        Args:
            event: 消息事件对象

        Yields:
            帮助信息
        """
        async for result in help_command(self, event):
            yield result

    @ai_gitee_group.command("generate")
    async def generate_image_command_wrapper(
        self, event: "AstrMessageEvent", prompt: str
    ) -> AsyncGenerator[Any, None]:
        """生成图片指令（命令行调用）

        通过命令行调用，支持指定图片比例。

        用法: /ai-gitee generate <提示词> [比例]
        示例: /ai-gitee generate 一个女孩 9:16
        支持比例: 1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16

        Args:
            event: 消息事件对象
            prompt: 图片提示词，可包含比例参数（格式：<提示词> [比例]）

        Yields:
            生成的图片或错误消息

        Raises:
            Exception: 图片生成失败时抛出异常
        """
        async for result in generate_image_command(self, event, prompt):
            yield result

    @ai_gitee_group.command("switch-model")
    async def switch_model_command_wrapper(
        self, event: "AstrMessageEvent", model_name: str
    ) -> AsyncGenerator[Any, None]:
        """切换模型命令

        切换当前使用的 AI 模型。

        用法: /ai-gitee switch-model <模型名称>
        示例: /ai-gitee switch-model z-image-turbo
              /ai-gitee switch-model flux-schnell

        Args:
            event: 消息事件对象
            model_name: 要切换到的模型名称

        Yields:
            操作结果或错误消息
        """
        async for result in switch_model_command(self, event, model_name):
            yield result

    @filter_cmd.llm_tool(name="draw_image")
    async def draw(self, event: "AstrMessageEvent", prompt: str):
        """根据提示词生成图片。

        Args:
            prompt(str): 图片提示词，需要包含主体、场景、风格等描述
        """
        return await draw_image_tool(self, event, prompt)

    @ai_gitee_group.command("text2image")
    async def list_models_command_wrapper(
        self, event: "AstrMessageEvent", type_param: str = ""
    ) -> AsyncGenerator[Any, None]:
        """获取模型列表命令

        支持按类型筛选模型列表。默认返回 text2image 类型模型。

        用法: /ai-gitee text2image [--type=<类型>]
        示例: /ai-gitee text2image              # 返回 text2image 类型模型（默认）
              /ai-gitee text2image --type=all    # 返回所有类型模型
              /ai-gitee text2image --type=text2text

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
        async for result in list_models_command(self, event, type_param):
            yield result

    async def close(self) -> None:
        """清理插件资源

        在插件卸载时调用，关闭所有客户端连接和释放资源。
        """
        self.debug_log("开始清理插件资源")
        await self.api_client.close()
        self.debug_log("插件资源清理完成")
