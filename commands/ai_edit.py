"""AI 图片编辑命令处理模块

处理 /ai-gitee ai-edit 命令，使用 Gitee AI 编辑图片。
"""

import time
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Plain


async def ai_edit_image_command(
    plugin,
    event: "AstrMessageEvent",
    prompt: str = "",
    task_type: str = "",
) -> AsyncGenerator[Any, None]:
    """AI 图片编辑指令

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
        plugin: 插件实例
        event: 消息事件对象
        prompt: 编辑提示词
        task_type: 任务类型（id 或 style）

    Yields:
        编辑后的图片或错误消息
    """
    user_id = event.get_sender_id()
    request_id = user_id

    plugin.debug_log(f"[AI编辑命令] 收到编辑请求: user_id={user_id}, prompt={prompt[:50] if prompt else ''}..., task_type={task_type}")

    # 防抖检查
    if plugin.rate_limiter.check_debounce(request_id):
        plugin.debug_log(f"[AI编辑命令] 请求被防抖拦截: user_id={user_id}")
        yield event.plain_result("操作太快了，请稍后再试。")
        return

    if plugin.rate_limiter.is_processing(request_id):
        plugin.debug_log(f"[AI编辑命令] 用户正在处理中: user_id={user_id}")
        yield event.plain_result("您有正在进行的任务，请稍候...")
        return

    plugin.rate_limiter.add_processing(request_id)

    try:
        # 检查提示词
        if not prompt:
            plugin.debug_log("[AI编辑命令] 未提供提示词")
            yield event.plain_result(
                "请提供编辑提示词！\n\n"
                "使用方法：发送图片的同时输入 /ai-gitee ai-edit <提示词> [任务类型]\n\n"
                "示例：\n"
                "/ai-gitee ai-edit 将这张照片转换成油画风格\n"
                "/ai-gitee ai-edit 保持人物特征，改变背景为海滩 id\n\n"
                "任务类型（可选）：\n"
                "- style: 风格编辑（默认）\n"
                "- id: 身份编辑（保持人物身份）\n\n"
                "输入 /ai-gitee help 查看更多说明"
            )
            return

        # 获取消息中的图片
        image_paths = await _extract_images_from_message(event)
        if not image_paths:
            plugin.debug_log("[AI编辑命令] 未找到图片")
            yield event.plain_result(
                "请发送要编辑的图片！\n\n"
                "使用方法：发送图片的同时输入 /ai-gitee ai-edit <提示词> [任务类型]\n\n"
                "支持多张图片，AI 会根据提示词智能处理。"
            )
            return

        # 解析任务类型
        task_types = ["style"]
        if task_type and task_type.lower() in ["id", "style"]:
            task_types = [task_type.lower()]

        plugin.debug_log(
            f"[AI编辑命令] 开始编辑图片: images={len(image_paths)}, "
            f"task_types={task_types}, prompt={prompt[:50]}..."
        )

        yield event.plain_result(f"正在使用 AI 编辑图片（{len(image_paths)}张），这可能需要几分钟，请稍候...")

        start_time = time.time()

        # 调用 API 编辑图片
        image_path = await plugin.api_client.edit_image(
            prompt=prompt,
            image_paths=image_paths,
            task_types=task_types,
            model="Qwen-Image-Edit-2511",
            num_inference_steps=4,
            guidance_scale=1.0,
            download_urls=plugin.download_image_urls,
        )

        end_time = time.time()
        elapsed_time = end_time - start_time

        plugin.debug_log(
            f"[AI编辑命令] 图片编辑成功: path={image_path}, "
            f"耗时={elapsed_time:.2f}秒"
        )

        # 发送结果
        yield event.chain_result([
            Image.fromFileSystem(image_path),  # type: ignore
            Plain(f"AI 图片编辑完成，耗时：{elapsed_time:.2f}秒")
        ])

    except Exception as e:
        logger.error(f"AI 图片编辑失败: {e}", exc_info=True)
        plugin.debug_log(f"[AI编辑命令] 编辑失败: error={str(e)}")
        yield event.plain_result(f"AI 图片编辑失败: {str(e)}")
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[AI编辑命令] 处理完成: user_id={user_id}")


async def _extract_images_from_message(event: AstrMessageEvent) -> list[str]:
    """从消息中提取所有图片的路径

    Args:
        event: 消息事件对象

    Returns:
        图片路径列表
    """
    message_obj = event.message_obj
    image_paths = []

    if not message_obj or not message_obj.message:
        return image_paths

    for component in message_obj.message:
        if isinstance(component, Image):
            # 从 Image 组件中获取图片路径
            if hasattr(component, 'url') and component.url:
                # 如果是 URL，需要下载
                path = await _download_image(component.url)
                if path:
                    image_paths.append(path)
            elif hasattr(component, 'file') and component.file:
                image_paths.append(component.file)
            elif hasattr(component, 'path') and component.path:
                image_paths.append(component.path)

    return image_paths


async def _download_image(url: str) -> str | None:
    """下载图片到本地

    Args:
        url: 图片 URL

    Returns:
        本地文件路径
    """
    import aiohttp
    import uuid
    from pathlib import Path

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.read()
                    # 保存到临时目录
                    temp_dir = Path("data/plugins/astrbot_plugin_models_ai/temp")
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    temp_path = temp_dir / f"{uuid.uuid4()}.png"
                    temp_path.write_bytes(data)
                    return str(temp_path)
    except Exception as e:
        logger.error(f"下载图片失败: {e}")
        return None