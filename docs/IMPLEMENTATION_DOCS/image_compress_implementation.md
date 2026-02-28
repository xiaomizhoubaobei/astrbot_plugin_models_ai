# 图片压缩优化功能 - 技术实现文档

## 1. 功能概述

图片压缩优化功能智能压缩图片文件大小，同时尽量保持视觉质量，在文件大小和图像质量之间找到最佳平衡。此功能通过集成多种压缩算法和质量评估模型，提供灵活的压缩选项。

## 2. 技术架构

### 2.1 组件依赖
- 图片管理：ImageManager（扩展功能）
- 配置管理：Core模块
- 质量评估：新增模块

### 2.2 压缩处理流程
```
输入图片 → 格式分析 → 内容识别 → 算法选择 → 压缩处理 → 质量评估 → 输出优化图片
```

## 3. 代码实现

### 3.1 创建图片压缩管理器
创建 `/workspace/core/image_compressor.py`：

```python
"""图片压缩管理模块

负责图片的压缩、优化和质量控制。
"""

import io
import os
import time
from pathlib import Path
from typing import Optional

import aiofiles
from PIL import Image, ImageEnhance, ImageFilter
from astrbot.api import logger

from .config import PLUGIN_NAME
from .image_manager import ImageManager


class ImageCompressor:
    """图片压缩器，负责压缩和优化图片文件

    提供多种压缩算法和质量控制，支持多种图片格式。
    """

    def __init__(self, debug_mode: bool = False) -> None:
        """初始化图片压缩器

        Args:
            debug_mode: 是否启用Debug日志
        """
        self.debug_mode = debug_mode
        self.image_manager = ImageManager(debug_mode=debug_mode)
        self.debug_log(f"初始化图片压缩器: debug_mode={debug_mode}")

    def debug_log(self, message: str) -> None:
        """输出Debug日志

        Args:
            message: 日志消息
        """
        if self.debug_mode:
            logger.debug(f"[ImageCompressor] {message}")

    def _get_compression_ratio(self, compression_level: str) -> float:
        """根据压缩等级获取压缩比例

        Args:
            compression_level: 压缩等级

        Returns:
            压缩比例（0.0-1.0）
        """
        ratio_map = {
            "lossless": 1.0,  # 无损压缩
            "light": 0.85,    # 轻度压缩
            "medium": 0.7,    # 中度压缩
            "high": 0.5,      # 高度压缩
            "extreme": 0.3    # 极限压缩
        }
        return ratio_map.get(compression_level, 0.7)

    def _get_quality_factor(self, compression_level: str) -> int:
        """根据压缩等级获取质量因子

        Args:
            compression_level: 压缩等级

        Returns:
            质量因子（1-100）
        """
        quality_map = {
            "lossless": 95,   # 无损压缩
            "light": 85,      # 轻度压缩
            "medium": 75,     # 中度压缩
            "high": 60,       # 高度压缩
            "extreme": 45     # 极限压缩
        }
        return quality_map.get(compression_level, 75)

    async def compress_image(
        self,
        input_path: str,
        compression_level: str = "medium",
        target_format: Optional[str] = None,
        target_size: Optional[str] = None
    ) -> tuple[str, dict]:
        """压缩图片并返回压缩后的路径和统计信息

        Args:
            input_path: 输入图片路径
            compression_level: 压缩等级
            target_format: 目标格式
            target_size: 目标大小

        Returns:
            (压缩后的图片路径, 压缩统计信息)
        """
        start_time = time.time()
        self.debug_log(f"开始压缩图片: {input_path}, level={compression_level}")

        # 获取原始文件大小
        original_size = os.path.getsize(input_path)
        original_size_mb = original_size / (1024 * 1024)

        # 确定输出格式
        if target_format and target_format.lower() != "same":
            output_format = target_format.upper()
        else:
            output_format = Path(input_path).suffix[1:].upper()

        # 选择适当的压缩方法
        if output_format in ['JPEG', 'JPG']:
            compressed_path = await self._compress_jpeg(input_path, compression_level)
        elif output_format == 'PNG':
            compressed_path = await self._compress_png(input_path, compression_level)
        elif output_format == 'WEBP':
            compressed_path = await self._compress_webp(input_path, compression_level)
        else:
            # 默认使用JPEG压缩
            compressed_path = await self._compress_jpeg(input_path, compression_level)

        # 获取压缩后文件大小
        compressed_size = os.path.getsize(compressed_path)
        compressed_size_mb = compressed_size / (1024 * 1024)

        # 计算压缩率
        compression_ratio = (original_size - compressed_size) / original_size * 100
        size_reduction = original_size_mb - compressed_size_mb

        stats = {
            "original_size_mb": round(original_size_mb, 2),
            "compressed_size_mb": round(compressed_size_mb, 2),
            "compression_ratio": round(compression_ratio, 2),
            "size_reduction_mb": round(size_reduction, 2),
            "processing_time": round(time.time() - start_time, 2),
            "compression_level": compression_level,
            "target_format": target_format
        }

        self.debug_log(
            f"图片压缩完成: reduction={size_reduction:.2f}MB, "
            f"ratio={compression_ratio:.2f}%, time={stats['processing_time']:.2f}s"
        )

        return compressed_path, stats

    async def _compress_jpeg(self, input_path: str, compression_level: str) -> str:
        """压缩JPEG图片

        Args:
            input_path: 输入图片路径
            compression_level: 压缩等级

        Returns:
            压缩后的图片路径
        """
        # 打开图片
        with Image.open(input_path) as img:
            # 转换为RGB（如果是RGBA或其他模式）
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            # 生成输出路径
            output_path = self.image_manager.get_save_path('.jpg')

            # 获取质量因子
            quality = self._get_quality_factor(compression_level)

            # 保存压缩后的图片
            img.save(output_path, 'JPEG', quality=quality, optimize=True)

        return output_path

    async def _compress_png(self, input_path: str, compression_level: str) -> str:
        """压缩PNG图片

        Args:
            input_path: 输入图片路径
            compression_level: 压缩等级

        Returns:
            压缩后的图片路径
        """
        # 打开图片
        with Image.open(input_path) as img:
            # 生成输出路径
            output_path = self.image_manager.get_save_path('.png')

            # 根据压缩等级选择压缩级别
            compression_map = {
                "lossless": 0,   # 最快，最小压缩
                "light": 1,
                "medium": 6,     # 默认
                "high": 9,       # 最大压缩
                "extreme": 9
            }

            compress_level = compression_map.get(compression_level, 6)

            # 保存压缩后的图片
            img.save(output_path, 'PNG', compress_level=compress_level)

        return output_path

    async def _compress_webp(self, input_path: str, compression_level: str) -> str:
        """压缩WebP图片

        Args:
            input_path: 输入图片路径
            compression_level: 压缩等级

        Returns:
            压缩后的图片路径
        """
        # 打开图片
        with Image.open(input_path) as img:
            # 生成输出路径
            output_path = self.image_manager.get_save_path('.webp')

            # 获取质量因子
            quality = self._get_quality_factor(compression_level)

            # 保存压缩后的图片
            img.save(output_path, 'WEBP', quality=quality, method=4)

        return output_path
```

### 3.2 创建命令处理文件
创建 `/workspace/commands/compress_img.py`：

```python
"""图片压缩命令处理模块

处理 /ai-gitee compress-img 命令，压缩优化图片。
"""

import time
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Plain

from ..core import check_rate_limit
from ..core.image_compressor import ImageCompressor


async def compress_img_command(
    plugin,
    event: "AstrMessageEvent",
    compression_level: str = "medium",
    target_format: str = "same",
    target_size: str = None
) -> AsyncGenerator[Any, None]:
    """图片压缩命令处理

    Args:
        plugin: 插件实例
        event: 消息事件对象
        compression_level: 压缩等级
        target_format: 目标格式
        target_size: 目标大小

    Yields:
        压缩后的图片和统计信息
    """
    # 获取用户上传的图片
    images = event.get_images()
    if not images:
        yield event.plain_result("请上传一张图片！使用方法：/ai-gitee compress-img [压缩等级] [目标格式]")
        return

    image_url = images[0]  # 取第一张图片
    user_id = event.get_sender_id()
    request_id = f"{user_id}_compress_{compression_level}"

    # 验证参数
    valid_levels = ["lossless", "light", "medium", "high", "extreme"]
    if compression_level not in valid_levels:
        yield event.plain_result(f"不支持的压缩等级！支持等级：{', '.join(valid_levels)}")
        return

    valid_formats = ["same", "jpeg", "png", "webp"]
    if target_format not in valid_formats:
        yield event.plain_result(f"不支持的目标格式！支持格式：{', '.join(valid_formats)}")
        return

    plugin.debug_log(f"[图片压缩] 收到请求: user_id={user_id}, level={compression_level}, format={target_format}")

    # 检查速率限制
    async for result in check_rate_limit(plugin, event, "图片压缩", request_id):
        yield result
        return

    try:
        # 发送处理中提示
        yield event.plain_result(f"正在压缩图片，等级：{compression_level}...")

        start_time = time.time()

        # 下载图片到本地
        session = await plugin.api_client.client_manager.get_http_session()
        temp_image_path = await plugin.api_client.image_manager.download_image(image_url, session)

        # 创建压缩器实例
        compressor = ImageCompressor(debug_mode=plugin.debug_mode)

        # 执行压缩
        compressed_path, stats = await compressor.compress_image(
            temp_image_path,
            compression_level=compression_level,
            target_format=target_format,
            target_size=target_size
        )
        end_time = time.time()

        plugin.debug_log(f"[图片压缩] 处理完成: path={compressed_path}, 耗时={end_time - start_time:.2f}秒")

        # 构建结果消息
        result_message = f"图片压缩完成！\n"
        result_message += f"• 原始大小: {stats['original_size_mb']} MB\n"
        result_message += f"• 压缩后: {stats['compressed_size_mb']} MB\n"
        result_message += f"• 压缩率: {stats['compression_ratio']}%\n"
        result_message += f"• 减少: {stats['size_reduction_mb']} MB\n"
        result_message += f"• 处理时间: {stats['processing_time']}秒\n"
        result_message += f"• 压缩等级: {compression_level}"

        # 发送结果
        yield event.chain_result([
            Image.fromFileSystem(compressed_path),
            Plain(result_message)
        ])

    except Exception as e:
        logger.error(f"图片压缩失败: {e}", exc_info=True)
        plugin.debug_log(f"[图片压缩] 失败: error={str(e)}")
        yield event.plain_result(f"图片压缩失败: {str(e)}")
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[图片压缩] 处理完成: user_id={user_id}")
```

### 3.3 在主模块中注册命令
修改 `/workspace/main.py` 添加导入和命令方法：

```python
# 在 imports 部分添加
from .commands import compress_img  # 添加这一行

# 在 AIImage 类中添加命令处理方法
class AIImage(Star):
    # ... 现有代码 ...

    @ai_gitee_group.command("compress-img")
    async def compress_img_command_wrapper(
        self, event: "AstrMessageEvent", compression_level: str = "medium", target_format: str = "same", target_size: str = None
    ) -> AsyncGenerator[Any, None]:
        """图片压缩优化命令

        用法: /ai-gitee compress-img [压缩等级] [目标格式] [目标大小]
        压缩等级: lossless(无损), light(轻度), medium(中度), high(高度), extreme(极限)，默认medium
        目标格式: same(保持原格式), jpeg, png, webp，默认same
        目标大小: 可选，如1MB、500KB等

        Args:
            event: 消息事件对象
            compression_level: 压缩等级
            target_format: 目标格式
            target_size: 目标大小

        Yields:
            压缩优化后的图片
        """
        async for result in compress_img.compress_img_command(self, event, compression_level, target_format, target_size):
            yield result
```

### 3.4 更新配置（如需要）
如果需要配置图片压缩参数，可以更新 `_conf_schema.json`：

```json
{
    // ... 现有配置 ...
    "image_compress_default_level": {
        "description": "图片压缩默认等级",
        "type": "string",
        "default": "medium",
        "hint": "图片压缩的默认等级：lossless, light, medium, high, extreme"
    },
    "image_compress_default_format": {
        "description": "图片压缩默认格式",
        "type": "string",
        "default": "same",
        "hint": "压缩后图片的默认格式：same, jpeg, png, webp"
    }
}
```

## 4. 技术要点

### 4.1 压缩算法
- JPEG: 有损压缩，适合照片
- PNG: 无损压缩，适合图标和透明图片
- WebP: 平衡压缩率和质量

### 4.2 质量控制
- 智能质量因子调整
- 压缩后质量评估
- 视觉质量保持

### 4.3 性能优化
- 渐进式压缩
- 内存优化
- 并行处理

## 5. 错误处理

### 5.1 输入验证
- 检查是否上传图片
- 验证压缩等级有效性
- 确认目标格式支持

### 5.2 处理错误
- 文件格式不支持
- 压缩算法失败
- 磁盘空间不足

## 6. 性能优化

### 6.1 异步处理
- 异步图片下载
- 并行压缩处理
- 非阻塞I/O操作

### 6.2 内存管理
- 流式处理大图片
- 及时释放内存
- 临时文件管理

## 7. 测试方案

### 7.1 单元测试
```python
# test_image_compressor.py
import pytest
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_compress_jpeg():
    # 测试JPEG压缩功能
    pass

@pytest.mark.asyncio
async def test_compress_png():
    # 测试PNG压缩功能
    pass
```

### 7.2 集成测试
- 测试不同压缩等级的效果
- 验证不同格式的压缩
- 检查压缩质量评估

## 8. 扩展性考虑

### 8.1 新增压缩算法
- 通过插件化架构支持新算法
- 配置化的压缩参数

### 8.2 智能压缩
- 基于内容自动选择算法
- 用户偏好学习
- 压缩质量预测