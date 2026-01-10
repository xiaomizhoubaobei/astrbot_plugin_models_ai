"""风格转换命令处理模块

处理 /ai-gitee style 命令，支持多种风格转换。
"""

import json
import os
import time
from typing import Any, AsyncGenerator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain, Image
from ..core import check_rate_limit, parse_prompt_and_size
from ..core.command_utils import extract_images_from_message


def _load_style_prompts() -> dict:
    """从 JSON 文件加载风格提示词"""
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompts_file = os.path.join(current_dir, "style_prompts.json")

    try:
        with open(prompts_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"风格提示词文件未找到: {prompts_file}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"风格提示词文件解析失败: {e}")
        return {}


# 风格提示词字典（从 JSON 文件加载）
STYLE_PROMPTS = _load_style_prompts()


async def style_command(
    plugin,
    event: "AstrMessageEvent",
    style_name: str = "",
    prompt: str = "",
) -> AsyncGenerator[Any, None]:
    """风格转换指令

    根据指定的风格名称转换图片风格，可附加自定义描述。

    用法: /ai-gitee style <风格名称> [自定义描述] [比例]
    示例: /ai-gitee style 手办化                       # 手办风格
          /ai-gitee style Q版化 一个可爱的女孩        # Q版风格 + 自定义描述
          /ai-gitee style cos化 猫娘 9:16              # cos风格 + 自定义描述 + 比例

    支持的风格：
    - 手办化, 手办化2, 手办化3, 手办化4, 手办化5, 手办化6
    - Q版化, cos化, cos化2, cos化3, cos化4, cos化5, cos化6, cos自拍, cos自拍2, cos自拍3, cos自拍4, cos自拍5, cos自拍6, cos相遇
    - 痛屋化, 痛屋化2, 痛车化
    - 孤独的我, 孤独的我2, 孤独的我3, 孤独的我4, 孤独的我5, 孤独的我6, 第一视角, 第三视角, 鬼图
    - 贴纸化, 玉足, 玩偶化, cos相遇
    - 三视图, 穿搭拆解, 拆解图, 角色界面, 角色设定
    - 3D打印, 微型化, 挂件化, 姿势表, 高清修复, 人物转身
    - 绘画四宫格, 发型九宫格, 头像九宫格, 表情九宫格
    - 多机位, 电影分镜, 动漫分镜
    - 真人化, 真人化2, 半真人, 半融合

    支持比例: 1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16

    Args:
        plugin: 插件实例，提供 api_client, rate_limiter, debug_log 等方法
        event: 消息事件对象
        style_name: 风格名称
        prompt: 自定义描述，可包含比例参数（格式：[描述] [比例]）

    Yields:
        生成的风格转换图片或错误消息
    """
    user_id = event.get_sender_id()
    request_id = user_id

    plugin.debug_log(f"[风格转换命令] 收到请求: user_id={user_id}, style_name={style_name}, prompt={prompt[:50] if prompt else ''}...")

    # 检查速率限制和防抖
    async for result in check_rate_limit(plugin, event, "风格转换命令", request_id):
        yield result
        return

    try:
        # 检查风格名称
        if not style_name:
            # 列出所有可用的风格
            style_list = "\n".join(f"- {name}" for name in sorted(STYLE_PROMPTS.keys()))
            yield event.plain_result(
                f"请指定风格名称！\n\n"
                f"使用方法：/ai-gitee style <风格名称> [自定义描述] [比例]\n\n"
                f"可用风格：\n{style_list}\n\n"
                f"支持比例：1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16\n\n"
                f"示例：\n"
                f"/ai-gitee style 手办化\n"
                f"/ai-gitee style Q版化 一个可爱的女孩\n"
                f"/ai-gitee style cos化 猫娘 9:16\n\n"
                f"提示：发送图片时将进行图生图转换，不发送图片则为文生图"
            )
            return

        # 检查风格是否存在
        if style_name not in STYLE_PROMPTS:
            available_styles = ", ".join(sorted(STYLE_PROMPTS.keys()))
            yield event.plain_result(
                f"风格 '{style_name}' 不存在！\n\n"
                f"可用风格：{available_styles}\n\n"
                f"使用方法：/ai-gitee style <风格名称> [自定义描述] [比例]"
            )
            return

        # 获取消息中的图片
        image_paths = await extract_images_from_message(event)
        plugin.debug_log(f"[风格转换命令] 检测到 {len(image_paths)} 张图片")

        # 获取风格提示词
        style_prompt = STYLE_PROMPTS[style_name]
        plugin.debug_log(f"[风格转换命令] 使用风格: {style_name}")

        # 解析提示词和目标尺寸
        target_size = plugin.api_client.default_size
        if prompt:
            # 如果用户提供了自定义描述，则解析提示词和比例
            try:
                prompt, target_size = parse_prompt_and_size(plugin, prompt)
                final_prompt = f"{prompt}, {style_prompt}"
            except ValueError as e:
                plugin.debug_log(f"[风格转换命令] 参数解析失败: {e}")
                yield event.plain_result(f"{e}。使用方法：/ai-gitee style <风格名称> [自定义描述] [比例]")
                return
        else:
            # 如果用户没有提供自定义描述，直接使用风格提示词
            final_prompt = style_prompt

        plugin.debug_log(
            f"[风格转换命令] 开始生成风格转换图片: user_id={user_id}, "
            f"style={style_name}, prompt={final_prompt[:80]}..., has_image={bool(image_paths)}, size={target_size}"
        )

        # 先发送提示消息
        if image_paths:
            yield event.plain_result(f"正在使用 {style_name} 风格转换图片（{len(image_paths)}张），请稍候...")
        else:
            yield event.plain_result(f"正在使用 {style_name} 风格生成图片，请稍候...")

        start_time = time.time()

        # 根据是否有图片选择不同的 API 调用方式
        if image_paths:
            # 图生图：使用 edit_image API
            image_path = await plugin.api_client.edit_image(
                prompt=final_prompt,
                image_paths=image_paths,
                task_types=["style"],
                model="Qwen-Image-Edit-2511",
                num_inference_steps=4,
                guidance_scale=1.0,
                download_urls=plugin.download_image_urls,
            )
        else:
            # 文生图：使用 generate_image API
            image_path = await plugin.api_client.generate_image(final_prompt, size=target_size)

        end_time = time.time()
        elapsed_time = end_time - start_time

        plugin.debug_log(
            f"[风格转换命令] 图片生成成功: path={image_path}, "
            f"耗时={elapsed_time:.2f}秒"
        )

        # 将图片和耗时信息合并到一个消息中发送
        yield event.chain_result([
            Image.fromFileSystem(image_path),  # type: ignore
            Plain(f"{style_name} 风格图片生成完成，耗时：{elapsed_time:.2f}秒")
        ])

    except Exception as e:
        logger.error(f"风格转换图片生成失败: {e}", exc_info=True)
        plugin.debug_log(f"[风格转换命令] 图片生成失败: error={str(e)}")
        yield event.plain_result(f"风格转换图片生成失败: {str(e)}")
    finally:
        plugin.rate_limiter.remove_processing(request_id)
        plugin.debug_log(f"[风格转换命令] 处理完成: user_id={user_id}")