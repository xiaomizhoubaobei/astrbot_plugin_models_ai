"""AstrBot AI 图像生成插件

支持 /ai 命令调用，支持多种图片比例和多 Key 轮询。
"""

from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter as filter_cmd
from astrbot.api.star import Context, Star
from .commands import generate_image_command, list_models_command, help_command, switch_model_command, ai_edit_image_command, style_command
from .core import (
    DEFAULT_BASE_URL,
    DEFAULT_INFERENCE_STEPS,
    DEFAULT_MODEL,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_SIZE,
    SUPPORTED_RATIOS,
    RateLimiter,
    parse_api_keys,
    parse_prompt_and_size,
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
        self.download_image_urls = config.get("download_image_urls", False)

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
            f"api_keys_count={len(api_keys)}, debug_mode={self.debug_mode}, "
            f"download_image_urls={self.download_image_urls}"
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

    @ai_gitee_group.command("ai-edit")
    async def ai_edit_image_command_wrapper(
        self, event: "AstrMessageEvent", prompt: str = "", task_type: str = ""
    ) -> AsyncGenerator[Any, None]:
        """AI 图片编辑命令

        使用 Gitee AI 的图片编辑功能对图片进行智能编辑。

        用法: /ai-gitee ai-edit <提示词> [任务类型]

        参数:
        - 提示词: 描述你想要的编辑效果
        - 任务类型（可选）:
          * id: 身份编辑（保持人物身份）
          * style: 风格编辑（改变图片风格）
          * 默认: style

        示例:
          /ai-gitee ai-edit 将这张照片转换成油画风格
          /ai-gitee ai-edit 让这张照片更有电影感 style
          /ai-gitee ai-edit 保持人物特征，改变背景为海滩 id

        注意: 发送命令时请同时附上要编辑的图片（支持多张图片）

        Args:
            event: 消息事件对象
            prompt: 编辑提示词
            task_type: 任务类型（id 或 style）

        Yields:
            编辑后的图片或错误消息
        """
        async for result in ai_edit_image_command(self, event, prompt, task_type):
            yield result

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

    @ai_gitee_group.command("style")
    async def style_command_wrapper(
        self, event: "AstrMessageEvent", style_name: str = "", prompt: str = ""
    ) -> AsyncGenerator[Any, None]:
        """风格转换命令

        根据指定的风格名称转换图片风格，可附加自定义描述。

        用法: /ai-gitee style <风格名称> [自定义描述] [比例]
        示例: /ai-gitee style 手办化                       # 手办风格
              /ai-gitee style Q版化 一个可爱的女孩        # Q版风格 + 自定义描述
              /ai-gitee style cos化 猫娘 9:16              # cos风格 + 自定义描述 + 比例

        支持的风格：
        - 手办化, 手办化2, 手办化3, 手办化4, 手办化5, 手办化6
        - Q版化, cos化, cos自拍
        - 痛屋化, 痛屋化2, 痛车化
        - 孤独的我, 第一视角, 第三视角, 鬼图
        - 贴纸化, 玉足, 玩偶化, cos相遇
        - 三视图, 穿搭拆解, 拆解图, 角色界面, 角色设定
        - 3D打印, 微型化, 挂件化, 姿势表, 高清修复, 人物转身
        - 绘画四宫格, 发型九宫格, 头像九宫格, 表情九宫格
        - 多机位, 电影分镜, 动漫分镜
        - 真人化, 真人化2, 半真人, 半融合

        支持比例: 1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16

        Args:
            event: 消息事件对象
            style_name: 风格名称
            prompt: 自定义描述，可包含比例参数（格式：[描述] [比例]）

        Yields:
            生成的风格转换图片或错误消息
        """
        async for result in style_command(self, event, style_name, prompt):
            yield result

    async def close(self) -> None:
        """清理插件资源

        在插件卸载时调用，关闭所有客户端连接和释放资源。
        """
        self.debug_log("开始清理插件资源")
        await self.api_client.close()
        self.debug_log("插件资源清理完成")