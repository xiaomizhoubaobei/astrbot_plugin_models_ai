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

from .config import MAX_CACHED_IMAGES, PLUGIN_NAME


class ImageManager:
    """图片管理器，负责图片的保存、下载和清理

    提供图片下载、保存和自动清理功能，支持多种图片格式。
    """

    def __init__(self, debug_mode: bool = False) -> None:
        """初始化图片管理器

        Args:
            debug_mode: 是否启用 Debug 日志
        """
        self.debug_mode = debug_mode
        self._image_dir: Optional[Path] = None
        self.debug_log(f"初始化图片管理器: debug_mode={debug_mode}")

    def debug_log(self, message: str) -> None:
        """输出 Debug 日志

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[ImageManager] {message}")

    def _get_image_dir(self) -> Path:
        """获取图片保存目录（延迟初始化）

        Returns:
            图片保存目录路径

        Note:
            目录在首次访问时创建，使用 AstrBot 的数据目录。
        """
        if self._image_dir is None:
            base_dir = StarTools.get_data_dir(PLUGIN_NAME)
            self._image_dir = base_dir / "images"
            self._image_dir.mkdir(exist_ok=True)
            self.debug_log(f"初始化图片目录: {self._image_dir}")
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

    @staticmethod
    def _get_extension_from_url_or_content_type(
        url: str, content_type: Optional[str] = None
    ) -> str:
        """从 URL 或 Content-Type 获取图片文件扩展名

        Args:
            url: 图片 URL
            content_type: HTTP 响应头的 Content-Type

        Returns:
            文件扩展名（包含点号，如 ".jpg"）
        """
        # 首先尝试从 Content-Type 获取
        if content_type:
            content_type_lower = content_type.lower()
            if "image/jpeg" in content_type_lower or "image/jpg" in content_type_lower:
                return ".jpg"
            if "image/png" in content_type_lower:
                return ".png"
            if "image/webp" in content_type_lower:
                return ".webp"
            if "image/gif" in content_type_lower:
                return ".gif"
            if "image/bmp" in content_type_lower:
                return ".bmp"

        # 其次尝试从 URL 获取
        url_lower = url.lower()
        if url_lower.endswith(".png"):
            return ".png"
        if url_lower.endswith(".webp"):
            return ".webp"
        if url_lower.endswith(".gif"):
            return ".gif"
        if url_lower.endswith(".bmp"):
            return ".bmp"
        if url_lower.endswith(".jpg") or url_lower.endswith(".jpeg"):
            return ".jpg"

        # 默认返回 .jpg
        return ".jpg"

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
        self.debug_log(f"开始下载图片: url={url[:50]}...")

        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"下载图片失败: HTTP {resp.status}")
            data = await resp.read()
            content_type = resp.headers.get("Content-Type")

        self.debug_log(f"图片下载完成: size={len(data)} bytes, content_type={content_type}")

        # 根据内容类型或 URL 确定文件扩展名
        extension = self._get_extension_from_url_or_content_type(url, content_type)
        filepath = self.get_save_path(extension)

        async with aiofiles.open(filepath, "wb") as f:
            await f.write(data)

        self.debug_log(f"图片保存成功: {filepath}")
        return filepath

    async def save_base64_image(self, b64_data: str) -> str:
        """异步保存 base64 图片到文件

        将 Base64 编码的图片数据解码并保存到本地文件。

        Args:
            b64_data: Base64 编码的图片数据，可能包含 data URI 前缀

        Returns:
            保存的图片文件路径（绝对路径）

        Raises:
            ValueError: 当 Base64 数据无效时抛出异常
            OSError: 当文件写入失败时抛出异常
        """
        self.debug_log(f"开始保存 Base64 图片: data_size={len(b64_data)}")

        # 检查是否包含 data URI 前缀
        extension = ".jpg"  # 默认扩展名
        if b64_data.startswith("data:image/"):
            # 解析 data URI 前缀，例如 "data:image/png;base64,"
            try:
                header_end = b64_data.find(";base64,")
                if header_end != -1:
                    mime_type = b64_data[5:header_end]  # 提取 "image/png"
                    mime_type_lower = mime_type.lower()
                    if mime_type_lower == "image/jpeg" or mime_type_lower == "image/jpg":
                        extension = ".jpg"
                    elif mime_type_lower == "image/png":
                        extension = ".png"
                    elif mime_type_lower == "image/webp":
                        extension = ".webp"
                    elif mime_type_lower == "image/gif":
                        extension = ".gif"
                    elif mime_type_lower == "image/bmp":
                        extension = ".bmp"
                    self.debug_log(f"从 Base64 前缀检测到格式: {mime_type}")
            except Exception as e:
                self.debug_log(f"解析 Base64 前缀失败: {e}，使用默认格式")

        # 解码 Base64 数据
        # 如果包含 data URI 前缀，需要先移除
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]

        image_bytes = base64.b64decode(b64_data)

        filepath = self.get_save_path(extension)
        async with aiofiles.open(filepath, "wb") as f:
            await f.write(image_bytes)

        self.debug_log(f"Base64 图片保存成功: {filepath}, size={len(image_bytes)} bytes")
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
            # 支持的图片扩展名
            supported_exts = {".jpg", ".jpeg", ".png", ".webp"}

            # 使用 os.scandir 一次性获取文件信息和元数据，减少系统调用
            images_with_mtime: list[tuple[str, float]] = []
            with os.scandir(image_dir) as entries:
                for entry in entries:
                    if entry.is_file() and entry.name.lower().endswith(tuple(supported_exts)):
                        images_with_mtime.append((entry.path, entry.stat().st_mtime))

            self.debug_log(f"清理旧图片: total={len(images_with_mtime)}, max={MAX_CACHED_IMAGES}")

            # 按修改时间排序（已预先获取 mtime，无需再次调用 stat）
            images_with_mtime.sort(key=lambda x: x[1])

            if len(images_with_mtime) > MAX_CACHED_IMAGES:
                to_delete = images_with_mtime[: len(images_with_mtime) - MAX_CACHED_IMAGES]
                deleted_count = 0
                for img_path, _ in to_delete:
                    try:
                        os.unlink(img_path)
                        deleted_count += 1
                    except OSError as e:
                        # 记录删除失败的文件，可能是已被其他进程删除
                        self.debug_log(f"删除文件失败: {img_path}, 错误: {e}")
                self.debug_log(f"清理完成: deleted={deleted_count}, kept={len(images_with_mtime) - deleted_count}")
        except OSError as e:
            logger.warning(f"清理旧图片时出错: {e}")
            self.debug_log(f"清理旧图片失败: {e}")

    async def cleanup_old_images(self) -> None:
        """异步清理旧图片，使用线程池执行阻塞操作

        在线程池中执行清理操作，避免阻塞事件循环。
        当图片数量超过 MAX_CACHED_IMAGES 时，自动删除最旧的图片。
        """
        self.debug_log("触发异步清理任务")
        await asyncio.to_thread(self._sync_cleanup_old_images)
        self.debug_log("异步清理任务完成")
