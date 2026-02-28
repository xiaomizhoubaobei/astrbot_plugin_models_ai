# 证件照自动生成功能 - 技术实现文档

## 1. 功能概述

证件照自动生成功能根据用户上传的人像照片，自动生成符合各类标准的证件照，包括尺寸裁剪、背景替换、美化等功能。此功能结合人像检测、图像裁剪和美化技术，通过Gitee AI API扩展实现。

## 2. 技术架构

### 2.1 组件依赖
- 核心组件：GiteeAIClient, ImageManager
- 人脸识别：集成API或本地模型
- 图像处理：现有图片处理管道

### 2.2 处理流程
```
上传图片 → 人脸检测 → 尺寸分析 → 背景替换 → 美化处理 → 标准化裁剪 → 输出证件照
```

## 3. 代码实现

### 3.1 创建命令处理文件
创建 `/workspace/commands/id_photo.py`：

```python
"""证件照生成命令处理模块

处理 /ai-gitee id-photo 命令，生成标准证件照。
"""

import time
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image, Plain

from ..core import check_rate_limit


# 证件照规格配置
ID_PHOTO_SPECS = {
    "passport": {"width": 35, "height": 49, "unit": "mm", "dpi": 300, "ratio": 35/49},
    "id-card": {"width": 26, "height": 32, "unit": "mm", "dpi": 350, "ratio": 26/32},
    "visa": {"width": 51, "height": 51, "unit": "mm", "dpi": 600, "ratio": 1.0},
    "driving-license": {"width": 21, "height": 26, "unit": "mm", "dpi": 300, "ratio": 21/26},
    "resume": {"width": 35, "height": 45, "unit": "mm", "dpi": 300, "ratio": 35/45},
    "school": {"width": 25, "height": 35, "unit": "mm", "dpi": 300, "ratio": 25/35}
}

# 背景色配置
BACKGROUND_COLORS = {
    "white": "#FFFFFF",
    "blue": "#4D8DFF",
    "red": "#FF0000"
}


async def id_photo_command(
    plugin,
    event: "AstrMessageEvent",
    photo_type: str = "passport",
    bg_color: str = "blue",
    output_quality: str = "high"
) -> AsyncGenerator[Any, None]:
    """证件照生成命令处理

    Args:
        plugin: 插件实例
        event: 消息事件对象
        photo_type: 证件类型
        bg_color: 背景色
        output_quality: 输出质量

    Yields:
        生成的证件照
    """
    # 获取用户上传的图片
    images = event.get_images()
    if not images:
        yield event.plain_result("请上传一张人像照片！使用方法：/ai-gitee id-photo <证件类型> [背景色]")
        return

    image_url = images[0]  # 取第一张图片
    user_id = event.get_sender_id()
    request_id = f"{user_id}_idphoto_{photo_type}"

    # 验证参数
    if photo_type not in ID_PHOTO_SPECS:
        valid_types = ", ".join(ID_PHOTO_SPECS.keys())
        yield event.plain_result(f"不支持的证件类型！支持类型：{valid_types}")
        return

    if bg_color not in BACKGROUND_COLORS:
        valid_colors = ", ".join(BACKGROUND_COLORS.keys())
        yield event.plain_result(f"不支持的背景色！支持颜色：{valid_colors}")
        return

    plugin.debug_log(f"[证件照生成] 收到请求: user_id={user_id}, type={photo_type}, bg={bg_color}")

    # 检查速率限制
    async for result in check_rate_limit(plugin, event, "证件照生成", request_id):
        yield result
        return

    try:
        # 发送处理中提示
        yield event.plain_result(f"正在生成{photo_type}证件照，请稍候...")

        start_time = time.time()
        # 调用API生成证件照
        result_path = await plugin.api_client.generate_id_photo(
            image_url=image_url,
            photo_type=photo_type,
            bg_color=BACKGROUND_COLORS[bg_color],
            output_quality=output_quality
        )
        end_time = time.time()

        # 获取规格信息
        spec = ID_PHOTO_SPECS[photo_type]
        spec_info = f"{spec['width']}×{spec['height']}{spec['unit']} ({spec['dpi']}dpi)"

        plugin.debug_log(f"[证件照生成] 处理完成: path={result_path}, 耗时={end_time - start_time:.2f}秒")

        # 发送结果和规格信息
        yield event.chain_result([
            Image.fromFileSystem(result_path),
            Plain(f"{photo_type.upper()}证件照生成完成\n规格：{spec_info}\n耗时：{end_time - start_time:.2f}秒")
        ])

    except Exception as e:
        logger.error(f"证件照生成失败: {e}", exc_info=True)
        plugin.debug_log(f"[证件照生成] 失败: error={str(e)}")
        yield event.plain_result(f"证件照生成失败: {str(e)}")
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[证件照生成] 处理完成: user_id={user_id}")
```

### 3.2 扩展GiteeAIClient
在 `/workspace/gitee/api_client.py` 中添加 `generate_id_photo` 方法：

```python
async def generate_id_photo(self, image_url: str, photo_type: str, bg_color: str = "#4D8DFF", output_quality: str = "high") -> str:
    """生成标准证件照

    Args:
        image_url: 人像图片URL
        photo_type: 证件类型
        bg_color: 背景色（十六进制）
        output_quality: 输出质量

    Returns:
        生成的证件照本地文件路径
    """
    self.debug_log(f"开始生成证件照: image_url={image_url[:50]}..., type={photo_type}, bg_color={bg_color}")

    api_key = self._get_next_api_key()
    session = await self.client_manager.get_http_session()

    # 证件照规格配置
    id_photo_specs = {
        "passport": {"width": 35, "height": 49, "dpi": 300},
        "id-card": {"width": 26, "height": 32, "dpi": 350},
        "visa": {"width": 51, "height": 51, "dpi": 600},
        "driving-license": {"width": 21, "height": 26, "dpi": 300},
        "resume": {"width": 35, "height": 45, "dpi": 300},
        "school": {"width": 25, "height": 35, "dpi": 300}
    }

    if photo_type not in id_photo_specs:
        raise ValueError(f"不支持的证件类型: {photo_type}")

    spec = id_photo_specs[photo_type]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 构建证件照生成请求
    payload = {
        "image_url": image_url,
        "action": "id_photo_generation",
        "specification": {
            "width_mm": spec["width"],
            "height_mm": spec["height"],
            "dpi": spec["dpi"]
        },
        "background": {
            "color": bg_color
        },
        "processing_options": {
            "face_detection": True,
            "auto_beautify": True,
            "light_adjustment": True
        }
    }

    try:
        # 发送证件照生成请求
        # 注意：这里的API端点和参数是假设的，需要根据实际API文档调整
        url = f"{self.base_url}/images/id-photo"  # 假设的端点
        response = await session.post(url, json=payload, headers=headers)

        if response.status == 200:
            result = await response.json()
            if "output_url" in result:
                processed_image_url = result["output_url"]
                filepath = await self.image_manager.download_image(processed_image_url, session)
                self.debug_log(f"证件照生成成功: {filepath}")
                return filepath
            else:
                raise RuntimeError("API未返回处理后的图片URL")
        else:
            error_detail = await response.text()
            raise RuntimeError(f"API请求失败: {response.status} - {error_detail}")

    except Exception as e:
        self.debug_log(f"证件照生成失败: {e}")
        raise RuntimeError(f"证件照生成失败: {str(e)}") from e
```

### 3.3 在主模块中注册命令
在 `/workspace/main.py` 中添加导入和命令方法：

```python
# 在 imports 部分添加
from .commands import id_photo  # 添加这一行

# 在 AIImage 类中添加命令处理方法
class AIImage(Star):
    # ... 现有代码 ...

    @ai_gitee_group.command("id-photo")
    async def id_photo_command_wrapper(
        self, event: "AstrMessageEvent", photo_type: str = "passport", bg_color: str = "blue", output_quality: str = "high"
    ) -> AsyncGenerator[Any, None]:
        """生成标准证件照命令

        用法: /ai-gitee id-photo <证件类型> [背景色] [输出质量]
        证件类型: passport(护照), id-card(身份证), visa(签证), driving-license(驾照), resume(简历), school(校园)
        背景色: white(白色), blue(蓝色), red(红色)，默认blue
        输出质量: standard(标准), high(高清), print(印刷)，默认high

        Args:
            event: 消息事件对象
            photo_type: 证件类型
            bg_color: 背景色
            output_quality: 输出质量

        Yields:
            符合标准的证件照
        """
        async for result in id_photo.id_photo_command(self, event, photo_type, bg_color, output_quality):
            yield result
```

### 3.4 更新配置（如需要）
如果需要配置证件照功能参数，可以更新 `_conf_schema.json`：

```json
{
    // ... 现有配置 ...
    "id_photo_default_type": {
        "description": "证件照默认类型",
        "type": "string",
        "default": "passport",
        "hint": "生成证件照的默认类型：passport, id-card, visa 等"
    },
    "id_photo_default_bg": {
        "description": "证件照默认背景色",
        "type": "string",
        "default": "blue",
        "hint": "证件照的默认背景色：white, blue, red"
    }
}
```

## 4. 技术要点

### 4.1 人像检测
- 智能识别人脸位置
- 确保头部比例符合标准
- 检测面部角度和光线

### 4.2 背景处理
- 背景替换为指定颜色
- 确保边缘自然过渡
- 保持人物边缘清晰

### 4.3 尺寸规格
- 按照不同证件标准裁剪
- 保持正确的宽高比
- 确保达到要求的DPI

## 5. 错误处理

### 5.1 输入验证
- 检查是否上传人像照片
- 验证证件类型是否支持
- 确认背景色是否有效

### 5.2 处理错误
- 人脸检测失败：提示重新上传
- 尺寸不符合要求：提供指导
- 背景替换失败：使用默认背景

## 6. 性能优化

### 6.1 异步处理
- 并行人像检测和尺寸分析
- 异步下载和保存结果
- 合理的超时设置

### 6.2 质量控制
- 智能判断是否需要美颜
- 保持面部真实性
- 避免过度处理

## 7. 测试方案

### 7.1 功能测试
- 测试各种证件类型的生成
- 验证不同背景色的效果
- 检查尺寸规格的准确性

### 7.2 边界测试
- 测试模糊或不清晰的人像
- 验证极端角度的照片
- 检查不同光照条件下的效果

## 8. 扩展性考虑

### 8.1 新增证件类型
- 通过配置文件扩展支持的证件类型
- 灵活调整尺寸规格参数

### 8.2 个性化选项
- 支持用户自定义尺寸
- 提供多种美颜程度选择
- 增加更多背景样式