# 智能背景移除功能 - 技术实现文档

## 1. 功能概述

智能背景移除功能允许用户上传图片，系统自动识别前景主体并移除背景，生成带有透明背景的PNG图片。此功能基于图像分割技术，利用Gitee AI API或扩展现有API功能实现。

## 2. 技术架构

### 2.1 组件依赖
- 核心组件：GiteeAIClient
- 图片管理：ImageManager
- 命令路由：commands目录下的处理函数

### 2.2 API集成方式
由于当前GiteeAIClient主要支持图像生成，需扩展其功能以支持图像分割。可采用以下方式之一：

1. 调用Gitee AI的图像编辑API（如果支持）
2. 集成第三方图像分割服务
3. 使用本地模型进行处理

## 3. 代码实现

### 3.1 命令处理文件
创建 `/workspace/commands/remove_bg.py`：

```python
"""背景移除命令处理模块

处理 /ai-gitee remove-bg 命令，移除图片背景。
"""

import time
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Plain

from ..core import check_rate_limit


async def remove_bg_command(
    plugin,
    event: "AstrMessageEvent",
    precision_level: str = "medium"
) -> AsyncGenerator[Any, None]:
    """背景移除命令处理

    Args:
        plugin: 插件实例
        event: 消息事件对象
        precision_level: 精确度等级（低、中、高）

    Yields:
        处理结果
    """
    # 获取用户上传的图片
    images = event.get_images()
    if not images:
        yield event.plain_result("请上传一张图片！使用方法：/ai-gitee remove-bg [图片]")
        return

    image_url = images[0]  # 取第一张图片
    user_id = event.get_sender_id()
    request_id = f"{user_id}_removebg"

    plugin.debug_log(f"[背景移除] 收到请求: user_id={user_id}, image_url_length={len(image_url)}")

    # 检查速率限制
    async for result in check_rate_limit(plugin, event, "背景移除", request_id):
        yield result
        return

    try:
        # 发送处理中提示
        yield event.plain_result("正在移除背景，请稍候...")

        start_time = time.time()
        # 调用API进行背景移除
        result_path = await plugin.api_client.remove_background(
            image_url=image_url,
            precision_level=precision_level
        )
        end_time = time.time()

        plugin.debug_log(f"[背景移除] 处理完成: path={result_path}, 耗时={end_time - start_time:.2f}秒")

        # 发送结果
        yield event.chain_result([
            Image.fromFileSystem(result_path),
            Plain(f"背景移除完成，耗时：{end_time - start_time:.2f}秒")
        ])

    except Exception as e:
        logger.error(f"背景移除失败: {e}", exc_info=True)
        plugin.debug_log(f"[背景移除] 失败: error={str(e)}")
        yield event.plain_result(f"背景移除失败: {str(e)}")
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[背景移除] 处理完成: user_id={user_id}")
```

### 3.2 扩展GiteeAIClient
修改 `/workspace/gitee/api_client.py`，添加 `remove_background` 方法：

```python
async def remove_background(self, image_url: str, precision_level: str = "medium") -> str:
    """移除图片背景，返回透明背景的PNG图片路径

    Args:
        image_url: 图片URL或本地路径
        precision_level: 精确度等级

    Returns:
        生成的图片本地文件路径
    """
    self.debug_log(f"开始背景移除: image_url={image_url[:50]}..., precision={precision_level}")

    # 这里需要根据实际API支持情况进行实现
    # 方案1: 如果Gitee AI支持图像编辑API
    api_key = self._get_next_api_key()
    session = await self.client_manager.get_http_session()

    # 构建请求参数（示例，需根据实际API调整）
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 根据精确度设置参数
    precision_map = {
        "low": 1,
        "medium": 2,
        "high": 3
    }
    precision_value = precision_map.get(precision_level, 2)

    payload = {
        "image_url": image_url,
        "mode": "remove_bg",  # 假设API支持此模式
        "precision": precision_value
    }

    try:
        # 发送背景移除请求
        # 注意：这里的API端点和参数是假设的，需要根据实际API文档调整
        url = f"{self.base_url}/images/edit"  # 假设的端点
        response = await session.post(url, json=payload, headers=headers)

        if response.status == 200:
            result = await response.json()
            if "output_url" in result:
                # 下载处理后的图片
                processed_image_url = result["output_url"]
                filepath = await self.image_manager.download_image(processed_image_url, session)
                self.debug_log(f"背景移除成功: {filepath}")

                # 清理临时文件（如果有）
                # ...

                return filepath
            else:
                raise RuntimeError("API未返回处理后的图片URL")
        else:
            error_detail = await response.text()
            raise RuntimeError(f"API请求失败: {response.status} - {error_detail}")

    except Exception as e:
        self.debug_log(f"背景移除失败: {e}")
        # 如果API不支持，可以在这里集成第三方服务或本地模型
        raise RuntimeError(f"背景移除失败: {str(e)}") from e
```

### 3.3 在主模块中注册命令
修改 `/workspace/main.py`，在适当位置添加导入和命令注册：

```python
# 在imports部分添加
from .commands import remove_bg  # 添加这一行

# 在AIImage类中添加命令处理方法
class AIImage(Star):
    # ... 现有代码 ...

    @ai_gitee_group.command("remove-bg")
    async def remove_bg_command_wrapper(
        self, event: "AstrMessageEvent", precision_level: str = "medium"
    ) -> AsyncGenerator[Any, None]:
        """移除图片背景命令

        用法: /ai-gitee remove-bg [精确度等级]
        精确度等级: low(低), medium(中), high(高)，默认为medium

        Args:
            event: 消息事件对象
            precision_level: 精确度等级

        Yields:
            透明背景的PNG图片
        """
        async for result in remove_bg.remove_bg_command(self, event, precision_level):
            yield result
```

### 3.4 更新配置模式（如需要）
如果需要新增配置项，更新 `_conf_schema.json`：

```json
{
    // ... 现有配置 ...
    "remove_bg_precision_default": {
        "description": "背景移除默认精确度",
        "type": "string",
        "default": "medium",
        "hint": "背景移除功能的默认精确度等级：low, medium, high"
    }
}
```

## 4. 错误处理

### 4.1 API错误
- 认证失败：提示用户检查API Key
- 服务不可用：提示稍后再试
- 图片格式不支持：提示支持的格式

### 4.2 业务逻辑错误
- 未上传图片：提示用户上传图片
- 处理失败：提供重试机制
- 精确度过高导致超时：建议使用较低精确度

## 5. 性能优化

### 5.1 异步处理
- 使用异步HTTP请求
- 图片下载异步化
- 合理使用并发

### 5.2 资源管理
- 及时释放API连接
- 自动清理临时文件
- 内存使用优化

## 6. 测试方案

### 6.1 单元测试
```python
# test_remove_bg.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_remove_bg_command():
    # 测试命令处理逻辑
    pass

@pytest.mark.asyncio
async def test_remove_background_api():
    # 测试API调用逻辑
    pass
```

### 6.2 集成测试
- 上传不同类型图片测试
- 测试不同精确度等级
- 验证错误处理机制

## 7. 部署注意事项

### 7.1 依赖检查
- 确保所需的图像处理库已安装
- 验证API Key配置正确

### 7.2 权限设置
- 确保有足够权限访问图片存储目录
- 验证网络请求权限

## 8. 维护和扩展

### 8.1 日志记录
- 记录处理过程和结果
- 监控API调用情况

### 8.2 功能扩展
- 支持更多精确度选项
- 添加前景增强功能
- 提供边缘平滑选项