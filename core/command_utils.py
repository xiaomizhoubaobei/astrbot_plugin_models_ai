"""命令处理工具模块

提供命令处理中的公共辅助函数。
"""

import aiohttp
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image

from .config import SUPPORTED_RATIOS


async def check_rate_limit(
    plugin,
    event: AstrMessageEvent,
    command_name: str,
    request_id: str,
) -> AsyncGenerator[Any, None]:
    """检查速率限制和防抖

    Args:
        plugin: 插件实例
        event: 消息事件对象
        command_name: 命令名称（用于日志）
        request_id: 请求标识符

    Yields:
        如果需要拒绝请求，则返回拒绝消息；否则不返回
    """
    plugin.debug_log(f"[{command_name}] 收到请求: request_id={request_id}")

    # 防抖检查
    if plugin.rate_limiter.check_debounce(request_id):
        plugin.debug_log(f"[{command_name}] 请求被防抖拦截: request_id={request_id}")
        yield event.plain_result("操作太快了，请稍后再试。")
        return

    if plugin.rate_limiter.is_processing(request_id):
        plugin.debug_log(f"[{command_name}] 用户正在处理中: request_id={request_id}")
        yield event.plain_result("您有正在进行的生图任务，请稍候...")
        return

    plugin.rate_limiter.add_processing(request_id)


def parse_prompt_and_size(plugin, prompt: str) -> tuple[str, str]:
    """解析提示词和目标尺寸

    从提示词中提取比例参数，并计算目标尺寸。

    Args:
        plugin: 插件实例
        prompt: 原始提示词，可能包含比例参数（格式：<提示词> [比例]）

    Returns:
        tuple[str, str]: (解析后的提示词, 目标尺寸)

    Raises:
        ValueError: 当提示词为空或仅包含比例时抛出异常
    """
    # 去除首尾空白字符
    prompt = prompt.strip()

    # 检查是否为空
    if not prompt:
        raise ValueError("提示词不能为空")

    # 解析比例参数
    ratio = "1:1"
    prompt_parts = prompt.rsplit(" ", 1)
    if len(prompt_parts) > 1 and prompt_parts[1] in SUPPORTED_RATIOS:
        ratio = prompt_parts[1]
        prompt = prompt_parts[0].strip()

    # 分割后再次检查提示词是否为空
    if not prompt:
        raise ValueError("请提供提示词，不能仅指定比例")

    # 确定目标尺寸
    target_size = plugin.api_client.default_size
    if ratio != "1:1" or (
        ratio == "1:1" and plugin.api_client.default_size not in SUPPORTED_RATIOS["1:1"]
    ):
        target_size = SUPPORTED_RATIOS[ratio][0]

    return prompt, target_size


async def extract_images_from_message(event: AstrMessageEvent) -> list[str]:
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
                path = await download_image(component.url)
                if path:
                    image_paths.append(path)
            elif hasattr(component, 'file') and component.file:
                image_paths.append(component.file)
            elif hasattr(component, 'path') and component.path:
                image_paths.append(component.path)

    return image_paths


async def download_image(url: str) -> str | None:
    """下载图片到本地

    Args:
        url: 图片 URL

    Returns:
        本地文件路径
    """
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