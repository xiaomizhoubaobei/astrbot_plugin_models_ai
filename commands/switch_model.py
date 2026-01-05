"""切换模型命令处理模块

处理 /ai-gitee switch-model 命令，切换 AI 模型。
"""

from typing import Any, AsyncGenerator

from astrbot.api.event import AstrMessageEvent


async def switch_model_command(
    plugin,
    event: "AstrMessageEvent",
    model_name: str,
) -> AsyncGenerator[Any, None]:
    """切换模型命令

    切换当前使用的 AI 模型。

    用法: /ai-gitee switch-model <模型名称>
    示例: /ai-gitee switch-model z-image-turbo
          /ai-gitee switch-model flux-schnell

    Args:
        plugin: 插件实例，提供 api_client, debug_log 等方法
        event: 消息事件对象
        model_name: 要切换到的模型名称

    Yields:
        操作结果或错误消息
    """
    if not model_name:
        plugin.debug_log("[切换模型] 收到空模型名称")
        yield event.plain_result("请提供模型名称！使用方法：/ai-gitee switch-model <模型名称>")
        return

    user_id = event.get_sender_id()
    plugin.debug_log(f"[切换模型] 收到请求: user_id={user_id}, model_name={model_name}")

    # 更新插件中的模型
    old_model = plugin.api_client.model
    plugin.api_client.model = model_name

    plugin.debug_log(f"[切换模型] 模型切换成功: {old_model} -> {model_name}")

    yield event.plain_result(f"✅ 模型已切换：{old_model} → {model_name}")