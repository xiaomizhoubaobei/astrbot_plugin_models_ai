"""生图命令处理模块

处理 /ai-gitee generate 命令，生成图片。
"""

import time
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Plain


async def generate_image_command(
    plugin,
    event: "AstrMessageEvent",
    prompt: str,
) -> AsyncGenerator[Any, None]:
    """生成图片指令（命令行调用）

    通过命令行调用，支持指定图片比例。

    用法: /ai-gitee generate <提示词> [比例]
    示例: /ai-gitee generate 一个女孩 9:16
    支持比例: 1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16

    Args:
        plugin: 插件实例，提供 api_client, rate_limiter, debug_log 等方法
        event: 消息事件对象
        prompt: 图片提示词，可包含比例参数（格式：<提示词> [比例]）

    Yields:
        生成的图片或错误消息

    Raises:
        Exception: 图片生成失败时抛出异常
    """
    if not prompt:
        plugin.debug_log("[命令] 收到空提示词")
        yield event.plain_result("请提供提示词！使用方法：/ai-gitee generate <提示词> [比例]")
        return

    user_id = event.get_sender_id()
    request_id = user_id

    plugin.debug_log(f"[命令] 收到生图请求: user_id={user_id}, prompt={prompt[:50]}...")

    # 防抖检查
    if plugin.rate_limiter.check_debounce(request_id):
        plugin.debug_log(f"[命令] 请求被防抖拦截: user_id={user_id}")
        yield event.plain_result("操作太快了，请稍后再试。")
        return

    if plugin.rate_limiter.is_processing(request_id):
        plugin.debug_log(f"[命令] 用户正在处理中: user_id={user_id}")
        yield event.plain_result("您有正在进行的生图任务，请稍候...")
        return

    plugin.rate_limiter.add_processing(request_id)

    # 解析提示词和目标尺寸
    try:
        prompt, target_size = plugin._parse_prompt_and_size(prompt)
    except ValueError as e:
        plugin.debug_log(f"[命令] 参数解析失败: {e}")
        yield event.plain_result(f"{e}。使用方法：/ai-gitee generate <提示词> [比例]")
        return

    plugin.debug_log(f"[命令] 解析参数: prompt={prompt[:50]}..., size={target_size}")

    try:
        plugin.debug_log(f"[命令] 开始生成图片: user_id={user_id}")
        # 先发送提示消息
        yield event.plain_result("正在生成图片，请稍候...")
        start_time = time.time()
        image_path = await plugin.api_client.generate_image(prompt, size=target_size)
        end_time = time.time()
        elapsed_time = end_time - start_time
        plugin.debug_log(
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
        plugin.debug_log(f"[命令] 图片生成失败: error={str(e)}")
        yield event.plain_result(f"生成图片失败: {str(e)}")
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[命令] 处理完成: user_id={user_id}")