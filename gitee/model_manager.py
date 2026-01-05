"""模型列表管理模块

负责获取和展示 Gitee AI 模型列表。
"""

from typing import Any

from astrbot.api import logger

from .api_client import GiteeAIClient

# 支持的模型类型列表
MODEL_TYPES = [
    "all",
    "text2speech",
    "text2image",
    "embeddings",
    "image2text",
    "speech2text",
    "text2text",
    "completions",
    "image2image",
    "voice_feature_extraction",
    "sentence_similarity",
    "rerank",
    "image_matting",
    "text2video",
    "image2video",
    "doc2md",
    "text23d",
    "image23d",
    "rerank_multimodal",
    "text2music",
    "image_video2video",
    "audio_video2video",
]


class ModelLister:
    """模型列表管理器

    负责获取和格式化 Gitee AI 模型列表。
    """

    def __init__(
        self,
        api_client: GiteeAIClient,
        debug_mode: bool = False,
    ) -> None:
        """初始化模型列表管理器

        Args:
            api_client: Gitee AI API 客户端
            debug_mode: 是否启用 Debug 日志
        """
        self.api_client = api_client
        self.debug_mode = debug_mode

        self.debug_log("模型列表管理器初始化完成")

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[ModelLister] {message}")

    @staticmethod
    def _parse_type_param(type_param: str) -> str:
        """解析类型参数

        Args:
            type_param: 类型参数字符串

        Returns:
            解析后的模型类型
        """
        model_type = "text2image"  # 默认类型
        if type_param.strip():
            # 支持 --type=text2image 格式
            if type_param.startswith("--type="):
                model_type = type_param.removeprefix("--type=").strip()
            else:
                model_type = type_param.strip()

        return model_type

    @staticmethod
    def _validate_model_type(model_type: str) -> bool:
        """验证模型类型是否有效

        Args:
            model_type: 模型类型

        Returns:
            是否有效
        """
        return model_type in MODEL_TYPES

    @staticmethod
    def _format_models_output(models: list[dict[str, Any]]) -> str:
        """格式化模型列表输出

        Args:
            models: 模型列表

        Returns:
            格式化后的输出字符串
        """
        # 提取模型名称并格式化输出
        model_names = [model["id"] for model in models]

        # 输出带编号的模型列表
        output = "\n".join(
            f"{i + 1}. {name}"
            for i, name in enumerate(model_names)
        )
        output += f"\n共 {len(model_names)} 个模型"

        return output

    async def list_models(self, type_param: str = "") -> tuple[bool, str]:
        """获取模型列表

        Args:
            type_param: 模型类型参数（可选），格式：--type=<类型>

        Returns:
            tuple[bool, str]: (是否成功, 结果消息)
        """
        self.debug_log(f"收到模型列表请求: type_param={type_param}")

        # 解析类型参数
        model_type = self._parse_type_param(type_param)

        # 验证类型参数
        if model_type and not self._validate_model_type(model_type):
            self.debug_log(f"无效的类型参数: {model_type}")
            error_msg = (
                f"无效的模型类型: {model_type}\n"
                f"支持的类型: {', '.join(MODEL_TYPES)}\n"
                f"使用方法: /ai-gitee-text2image [--type=<类型>]"
            )
            return False, error_msg

        self.debug_log(f"解析类型参数: type={model_type}")

        try:
            self.debug_log("开始获取模型列表")

            # 如果 type 为 "all"，则不传 type 参数以获取所有模型
            api_type = model_type if model_type != "all" else ""

            # 调用 API 获取模型列表
            models = await self.api_client.get_models(type=api_type)

            self.debug_log(f"模型列表获取成功: count={len(models)}")

            if not models:
                self.debug_log("模型列表为空")
                type_info = f"（类型: {model_type}）" if model_type else ""
                return True, f"没有找到任何模型{type_info}。"

            # 格式化输出
            output = self._format_models_output(models)

            self.debug_log(f"准备返回结果: count={len(models)}")
            return True, output

        except Exception as e:
            logger.error(f"获取模型列表失败: {e}", exc_info=True)
            self.debug_log(f"获取模型列表失败: error={str(e)}")
            return False, f"获取模型列表失败: {str(e)}"