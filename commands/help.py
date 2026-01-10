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

🎨 风格转换:
  /ai-gitee style <风格名称> [自定义描述] [比例]
  示例: /ai-gitee style 手办化                       # 手办风格（文生图）
        /ai-gitee style Q版化 一个可爱的女孩        # Q版风格 + 自定义描述（文生图）
        /ai-gitee style cos化 猫娘 9:16              # cos风格 + 自定义描述 + 比例（文生图）
        [发送图片] /ai-gitee style 手办化           # 基于图片的风格转换（图生图）

  支持风格分类:
  - 手办化: 手办化, 手办化2, 手办化3, 手办化4, 手办化5, 手办化6
  - 角色转换: Q版化, Q版化2, Q版化3, Q版化4, Q版化5, Q版化6, cos化, cos自拍, 真人化, 真人化2, 半真人, 半融合
  - 场景化: 痛屋化, 痛屋化2, 痛屋化3, 痛屋化4, 痛屋化5, 痛屋化6, 痛车化, 痛车化2, 痛车化3, 痛车化4, 痛车化5, 痛车化6, 孤独的我, 第一视角, 第三视角, 鬼图
  - 物品化: 贴纸化, 玉足, 玩偶化, 3D打印, 微型化, 挂件化
  - 角色设计: cos相遇, 三视图, 穿搭拆解, 拆解图, 角色界面, 角色设定
  - 多图生成: 姿势表, 绘画四宫格, 发型九宫格, 头像九宫格, 表情九宫格
  - 特殊效果: 高清修复, 人物转身, 多机位, 电影分镜, 动漫分镜

  支持比例: 1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16
  说明: 输入 /ai-gitee style 查看所有可用风格
  提示: 发送图片时将进行图生图转换，不发送图片则为文生图

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