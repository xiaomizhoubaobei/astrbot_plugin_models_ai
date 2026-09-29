"""服务商客户端协议模块.

定义跨服务商共享的客户端契约。

本项目采用结构化子类型（鸭子类型）实现多服务商切换：命令层与 LLM 工具层只依赖
这里声明的能力，而不依赖具体实现，从而避免引入抽象基类去牵动每个服务商客户端
的全部方法签名。任何服务商只要满足本协议，即可无缝替换并复用全部命令。
"""

from typing import Any, Protocol


class ImageGenerationClient(Protocol):
    """生图服务商客户端契约.

    所有服务商客户端（如 ``GiteeAIClient``、``QianwenClient``）都应满足该契约，
    以保证命令层与工具层可以无差别调用。
    """

    #: 当前使用的模型名称，switch-model 命令会直接改写该属性
    model: str

    #: 默认图片尺寸；各服务商的分隔符不同（Gitee 为 宽x高，千问云为 宽*高）
    default_size: str

    #: 「比例 -> 可选尺寸列表」映射，供 parse_prompt_and_size 使用
    supported_ratios: dict[str, list[str]]

    async def generate_image(self, prompt: str, size: str = "") -> str:
        """根据提示词生成图片并返回本地文件路径.

        Args:
            prompt: 图片提示词
            size: 目标尺寸（可选）

        Returns:
            生成的图片本地文件路径
        """
        ...

    async def get_models(
        self, vendor: str = "", type: str = ""
    ) -> list[dict[str, Any]]:
        """获取该服务商可用的模型列表.

        Args:
            vendor: 算力厂商筛选（部分服务商不支持）
            type: 模型类型筛选（部分服务商不支持）

        Returns:
            模型列表，每项至少包含 id 字段
        """
        ...

    async def close(self) -> None:
        """释放客户端占用的资源."""
        ...
