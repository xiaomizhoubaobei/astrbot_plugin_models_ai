"""命令处理模块

提供 ai-gitee 指令组的各种命令处理逻辑。
"""

from .generate import generate_image_command
from .switch_model import switch_model_command
from .text2image import list_models_command
from .help import help_command
from .ai_edit import ai_edit_image_command

__all__ = [
    "generate_image_command",
    "switch_model_command",
    "list_models_command",
    "help_command",
    "ai_edit_image_command",
]