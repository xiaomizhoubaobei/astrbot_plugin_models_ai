"""切换模型命令处理模块.

处理 /ai-gitee switch-model 命令，切换 AI 模型。
"""

from typing import Any, AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..core import PROVIDER_QIANWEN
from ..qianwen import is_supported_model, list_supported_models


async def switch_model_command(
    plugin,
    event: "AstrMessageEvent",
    model_name: str,
) -> AsyncGenerator[Any, None]:
    """切换模型命令.

    切换当前使用的 AI 模型。

    用法: /ai-gitee switch-model <模型名称>
    示例: /ai-gitee switch-model z-image-turbo
          /ai-gitee switch-model wan2.6-t2i

    Args:
        plugin: 插件实例，提供 api_client, debug_log 等方法
        event: 消息事件对象
        model_name: 要切换到的模型名称

    Yields:
        操作结果或错误消息
    """
    if not model_name:
        plugin.debug_log("[切换模型] 收到空模型名称")
        yield event.plain_result(
            "请提供模型名称！使用方法：/ai-gitee switch-model <模型名称>"
        )
        return

    user_id = event.get_sender_id()
    plugin.debug_log(f"[切换模型] 收到请求: user_id={user_id}, model_name={model_name}")

    # 千问云有固定的模型能力表，切到未登记型号时直接拒绝并列出可选值，
    # 比等到首次生图才以接口报错形式失败更易诊断
    provider = ""
    if hasattr(plugin, "config"):
        provider = str(plugin.config.get("provider", "gitee")).strip().lower()

    if provider == PROVIDER_QIANWEN and not is_supported_model(model_name):
        available = ", ".join(list_supported_models())
        plugin.debug_log(f"[切换模型] 千问云不支持的模型: {model_name}")
        yield event.plain_result(
            f"千问云暂不支持模型「{model_name}」。\n" f"可用模型: {available}"
        )
        return

    # 更新插件中的模型
    old_model = plugin.api_client.model
    plugin.api_client.model = model_name

    plugin.debug_log(f"[切换模型] 模型切换成功: {old_model} -> {model_name}")

    yield event.plain_result(f"✅ 模型已切换：{old_model} → {model_name}")
