"""帮助命令处理模块

处理 /ai-gitee help 命令，显示帮助信息。
"""

from typing import Any, AsyncGenerator

from astrbot.api.event import AstrMessageEvent


async def help_command(
    plugin,
    event: "AstrMessageEvent",
) -> AsyncGenerator[Any, None]:
    """显示帮助信息

    用法: /ai-gitee help

    Args:
        plugin: 插件实例
        event: 消息事件对象

    Yields:
        帮助信息
    """
    help_text = """
📚 ai-gitee 指令帮助

🎨 生图命令:
  /ai-gitee generate <提示词> [比例]
  示例: /ai-gitee generate 一个女孩 9:16
  支持比例: 1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16

🤖 AI 图片编辑:
  /ai-gitee ai-edit <提示词> [任务类型]
  注意: 发送命令时请同时附上要编辑的图片（支持多张）

  参数:
  - 提示词: 描述你想要的编辑效果
  - 任务类型（可选）:
    * id: 身份编辑（保持人物身份）
    * style: 风格编辑（改变图片风格，默认）

  示例:
  - /ai-gitee ai-edit 将这张照片转换成油画风格
  - /ai-gitee ai-edit 让这张照片更有电影感 style
  - /ai-gitee ai-edit 保持人物特征，改变背景为海滩 id

🔄 切换模型:
  /ai-gitee switch-model <模型名称>
  示例: /ai-gitee switch-model z-image-turbo
        /ai-gitee switch-model flux-schnell

📋 模型列表:
  /ai-gitee text2image [--type=<类型>]
  示例: /ai-gitee text2image
        /ai-gitee text2image --type=all
        /ai-gitee text2image --type=text2text

  支持类型:
  - all: 所有类型
  - text2image: 文本生成图像（默认）
  - text2text: 文本生成文本
  - embeddings: 向量嵌入生成
  - image2text: 图像转文本
  - speech2text: 语音转文本
  - text2speech: 文本转语音
  - completions: 补全任务
  - image2image: 图像生成图像
  - voice_feature_extraction: 语音特征提取
  - sentence_similarity: 句子相似度计算
  - rerank: 重排序
  - image_matting: 图像抠图
  - text2video: 文本生成视频
  - image2video: 图像生成视频
  - doc2md: 文档转 Markdown
  - text23d: 文本生成 3D 模型
  - image23d: 图像生成 3D 模型
  - rerank_multimodal: 多模态重排序
  - text2music: 文本生成音乐
  - image_video2video: 图像/视频生成视频
  - audio_video2video: 音频/视频生成视频

❓ 帮助命令:
  /ai-gitee help
"""
    yield event.plain_result(help_text)