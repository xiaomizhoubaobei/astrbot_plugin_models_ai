"""LLM 生图工具模块

提供 LLM 工具调用生成图片的功能。
"""

import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Plain

from ..core import parse_prompt_and_size


async def draw_image_tool(
    plugin,
    event: "AstrMessageEvent",
    prompt: str,
) -> str:
    """根据提示词生成图片。

    Args:
        plugin: 插件实例，提供 api_client, rate_limiter, debug_log 等方法
        event: 消息事件对象
        prompt: 图片提示词，需要包含主体、场景、风格等描述

    Returns:
        str: 生图结果描述
    """
    user_id = event.get_sender_id()
    request_id = user_id

    plugin.debug_log(f"[LLM工具] 收到生图请求: user_id={user_id}, prompt={prompt[:50]}...")

    # 防抖检查
    if plugin.rate_limiter.check_debounce(request_id):
        plugin.debug_log(f"[LLM工具] 请求被防抖拦截: user_id={user_id}")
        return "操作太快了，请稍后再试。"

    if plugin.rate_limiter.is_processing(request_id):
        plugin.debug_log(f"[LLM工具] 用户正在处理中: user_id={user_id}")
        return "您有正在进行的生图任务，请稍候..."

    plugin.rate_limiter.add_processing(request_id)

    # 解析提示词和目标尺寸
    try:
        prompt, target_size = parse_prompt_and_size(plugin, prompt)
    except ValueError as e:
        plugin.debug_log(f"[LLM工具] 参数解析失败: {e}")
        return f"{e}。请提供完整的提示词和可选的比例参数。"

    try:
        plugin.debug_log(f"[LLM工具] 开始生成图片: user_id={user_id}, size={target_size}")
        # 先发送提示消息
        await event.send(event.plain_result("正在生成图片，请稍候..."))
        start_time = time.time()
        image_path = await plugin.api_client.generate_image(prompt, size=target_size)
        end_time = time.time()
        elapsed_time = end_time - start_time
        plugin.debug_log(
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
        plugin.debug_log(f"[LLM工具] 图片生成失败: error={str(e)}")
        return f"生成图片时遇到问题: {str(e)}"
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[LLM工具] 处理完成: user_id={user_id}")