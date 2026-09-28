"""LLM 生图工具模块.

提供 LLM 工具调用生成图片的功能。
"""

import time
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core import parse_prompt_and_size


async def draw_image_tool(
    plugin,
    event: "AstrMessageEvent",
    prompt: str,
) -> AsyncGenerator[Any, None]:
    """根据提示词生成图片.

    按照 AstrBot v4 的 LLM 工具约定，本函数以异步生成器的方式返回结果：

    - yield MessageEventResult：由框架以 tool_direct_result 直接投递给用户，
      并结束本轮 Agent 循环（图片已直发，无需 LLM 再复述图片内容）；
    - yield str：作为工具返回值交回 LLM，由 LLM 自行组织回复（用于失败/参数错误）。

    Args:
        plugin: 插件实例，提供 api_client, rate_limiter, debug_log 等方法
        event: 消息事件对象
        prompt: 图片提示词，需要包含主体、场景、风格等描述

    Yields:
        MessageEventResult: 生成成功时直发给用户的图片消息
        str: 失败或参数错误时回传给 LLM 的文本信息
    """
    user_id = event.get_sender_id()
    request_id = user_id

    plugin.debug_log(f"[LLM工具] 收到生图请求: user_id={user_id}, prompt={prompt[:50]}...")

    # 防抖检查：命中时直接告知用户，并结束本轮 Agent 循环
    if plugin.rate_limiter.check_debounce(request_id):
        plugin.debug_log(f"[LLM工具] 请求被防抖拦截: user_id={user_id}")
        yield event.plain_result("操作太快了，请稍后再试。")
        return

    if plugin.rate_limiter.is_processing(request_id):
        plugin.debug_log(f"[LLM工具] 用户正在处理中: user_id={user_id}")
        yield event.plain_result("您有正在进行的生图任务，请稍候...")
        return

    # 解析提示词和目标尺寸（解析失败时不占用并发名额，避免名额泄漏）
    try:
        prompt, target_size = parse_prompt_and_size(plugin, prompt)
    except ValueError as e:
        plugin.debug_log(f"[LLM工具] 参数解析失败: {e}")
        yield f"{e}。请提供完整的提示词和可选的比例参数。"
        return

    plugin.rate_limiter.add_processing(request_id)
    try:
        plugin.debug_log(f"[LLM工具] 开始生成图片: user_id={user_id}, size={target_size}")
        # 生图耗时较长，先直发一条提示消息安抚用户
        await event.send(event.plain_result("正在生成图片，请稍候..."))

        start_time = time.time()
        image_path = await plugin.api_client.generate_image(prompt, size=target_size)
        elapsed_time = time.time() - start_time
        plugin.debug_log(
            f"[LLM工具] 图片生成成功: path={image_path}," f"耗时={elapsed_time:.2f}秒"
        )

        # 图片与耗时信息合并为一条消息直发给用户
        yield event.make_result().file_image(image_path).message(
            f"图片生成完成，耗时：{elapsed_time:.2f}秒"
        )
    except Exception as e:
        logger.error(f"生图失败: {e}", exc_info=True)
        plugin.debug_log(f"[LLM工具] 图片生成失败: error={str(e)}")
        # 失败信息回传给 LLM，交由 LLM 决定重试或向用户说明
        yield f"生成图片时遇到问题: {str(e)}"
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[LLM工具] 处理完成: user_id={user_id}")
