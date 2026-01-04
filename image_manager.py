"""图片管理模块

负责图片的保存、下载和清理。
"""

import asyncio
import base64
import os
import time
from pathlib import Path
from typing import Optional

import aiofiles
import aiohttp

from astrbot.api import logger
from astrbot.api.star import StarTools

from .config import MAX_CACHED_IMAGES


# Debug 日志开关（默认关闭，通过配置文件控制）
DEBUG_MODE = False


def debug_log(message: str) -> None:
    """输出 Debug 日志

    Args:
        message: 日志消息
    """
    if DEBUG_MODE:
        logger.debug(f"[ImageManager] {message}")


class ImageManager:
    """图片管理器，负责图片的保存、下载和清理

    提供图片下载、保存和自动清理功能，支持多种图片格式。
    """

    def __init__(self, debug_mode: bool = False) -> None:
        """初始化图片管理器

        Args:
            debug_mode: 是否启用 Debug 日志
        """
        global DEBUG_MODE
        DEBUG_MODE = debug_mode

        self._image_dir: Optional[Path] = None
        debug_log(f"初始化图片管理器: debug_mode={debug_mode}")

    def _get_image_dir(self) -> Path:
        """获取图片保存目录（延迟初始化）

        Returns:
            图片保存目录路径

        Note:
            目录在首次访问时创建，使用 AstrBot 的数据目录。
        """
        if self._image_dir is None:
            base_dir = StarTools.get_data_dir("astrbot_plugin_gitee_aiimg")
            self._image_dir = base_dir / "images"
            self._image_dir.mkdir(exist_ok=True)
            debug_log(f"初始化图片目录: {self._image_dir}")
        return self._image_dir

    def get_save_path(self, extension: str = ".jpg") -> str:
        """生成唯一的图片保存路径

        使用时间戳和随机字符串生成唯一文件名，避免文件名冲突。

        Args:
            extension: 文件扩展名，默认为 ".jpg"

        Returns:
            图片保存路径（绝对路径）
        """
        image_dir = self._get_image_dir()
        filename = f"{int(time.time())}_{os.urandom(4).hex()}{extension}"
        return str(image_dir / filename)

    async def download_image(self, url: str, session: aiohttp.ClientSession) -> str:
        """下载图片并异步保存到文件

        通过 HTTP 下载图片并保存到本地，使用异步 I/O 提高性能。

        Args:
            url: 图片 URL
            session: aiohttp Session 实例

        Returns:
            保存的图片文件路径（绝对路径）

        Raises:
            Exception: 当 HTTP 状态码不是 200 时抛出异常
            Exception: 当网络请求失败时抛出异常
        """
        debug_log(f"开始下载图片: url={url[:50]}...")

        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"下载图片失败: HTTP {resp.status}")
            data = await resp.read()

        debug_log(f"图片下载完成: size={len(data)} bytes")

        filepath = self.get_save_path()
        async with aiofiles.open(filepath, "wb") as f:
            await f.write(data)

        debug_log(f"图片保存成功: {filepath}")
        return filepath

    async def save_base64_image(self, b64_data: str) -> str:
        """异步保存 base64 图片到文件

        将 Base64 编码的图片数据解码并保存到本地文件。

        Args:
            b64_data: Base64 编码的图片数据

        Returns:
            保存的图片文件路径（绝对路径）

        Raises:
            ValueError: 当 Base64 数据无效时抛出异常
            OSError: 当文件写入失败时抛出异常
        """
        debug_log(f"开始保存 Base64 图片: data_size={len(b64_data)}")

        filepath = self.get_save_path()
        image_bytes = base64.b64decode(b64_data)

        async with aiofiles.open(filepath, "wb") as f:
            await f.write(image_bytes)

        debug_log(f"Base64 图片保存成功: {filepath}, size={len(image_bytes)} bytes")
        return filepath

    def _sync_cleanup_old_images(self) -> None:
        """同步清理旧图片（在线程池中执行）

        删除超过最大缓存数量的旧图片，按修改时间排序，保留最新的图片。

        Note:
            此方法在线程池中执行，避免阻塞事件循环。
            支持的图片格式: .jpg, .png, .webp
        """
        try:
            image_dir = self._get_image_dir()
            # 收集所有支持的图片格式
            images: list[Path] = []
            for ext in ("*.jpg", "*.png", "*.webp"):
                images.extend(image_dir.glob(ext))

            debug_log(f"清理旧图片: total={len(images)}, max={MAX_CACHED_IMAGES}")

            # 按修改时间排序
            images.sort(key=lambda p: p.stat().st_mtime)

            if len(images) > MAX_CACHED_IMAGES:
                to_delete = images[: len(images) - MAX_CACHED_IMAGES]
                deleted_count = 0
                for img_path in to_delete:
                    try:
                        img_path.unlink()
                        deleted_count += 1
                    except OSError:
                        # 忽略删除失败的文件，可能是已被其他进程删除
                        pass
                debug_log(f"清理完成: deleted={deleted_count}, kept={len(images) - deleted_count}")
        except Exception as e:
            logger.warning(f"清理旧图片时出错: {e}")
            debug_log(f"清理旧图片失败: {e}")

    async def cleanup_old_images(self) -> None:
        """异步清理旧图片，使用线程池执行阻塞操作

        在线程池中执行清理操作，避免阻塞事件循环。
        当图片数量超过 MAX_CACHED_IMAGES 时，自动删除最旧的图片。
        """
        debug_log("触发异步清理任务")
        await asyncio.to_thread(self._sync_cleanup_old_images)
        debug_log("异步清理任务完成")