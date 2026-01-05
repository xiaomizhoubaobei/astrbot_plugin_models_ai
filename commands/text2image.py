"""模型列表命令处理模块

处理 /ai-gitee text2image 命令，获取模型列表。
"""

from typing import Any, AsyncGenerator

from astrbot.api.event import AstrMessageEvent


async def list_models_command(
    plugin,
    event: "AstrMessageEvent",
    type_param: str = "",
) -> AsyncGenerator[Any, None]:
    """获取模型列表命令

    支持按类型筛选模型列表。默认返回 text2image 类型模型。

    用法: /ai-gitee text2image [--type=<类型>]
    示例: /ai-gitee text2image              # 返回 text2image 类型模型（默认）
          /ai-gitee text2image --type=all    # 返回所有类型模型
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

    Args:
        plugin: 插件实例，提供 model_lister, rate_limiter, debug_log 等方法
        event: 消息事件对象
        type_param: 模型类型参数（可选），格式：--type=<类型>

    Yields:
        模型列表或错误消息
    """
    user_id = event.get_sender_id()
    request_id = user_id

    plugin.debug_log(f"[模型列表] 收到请求: user_id={user_id}, type_param={type_param}")

    # 防抖检查
    if plugin.rate_limiter.check_debounce(request_id):
        plugin.debug_log(f"[模型列表] 请求被防抖拦截: user_id={user_id}")
        yield event.plain_result("操作太快了，请稍后再试。")
        return

    if plugin.rate_limiter.is_processing(request_id):
        plugin.debug_log(f"[模型列表] 用户正在处理中: user_id={user_id}")
        yield event.plain_result("您有正在进行的请求，请稍候...")
        return

    plugin.rate_limiter.add_processing(request_id)

    try:
        # 发送正在获取的提示
        yield event.plain_result("正在获取模型列表，请稍候...")

        # 使用 ModelLister 获取模型列表
        success, result = await plugin.model_lister.list_models(type_param)
        yield event.plain_result(result)
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[模型列表] 处理完成: user_id={user_id}")