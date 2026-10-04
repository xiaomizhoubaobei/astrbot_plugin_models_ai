"""命令处理工具模块.

提供命令处理中的公共辅助函数。
"""

import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator
from urllib.parse import urlparse
from urllib.request import url2pathname

import aiohttp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image

from .net_errors import build_timeout, mask_text, to_user_message, with_retry


async def check_rate_limit(
    plugin,
    event: AstrMessageEvent,
    command_name: str,
    request_id: str,
) -> AsyncGenerator[Any, None]:
    """检查速率限制和防抖.

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
    """解析提示词和目标尺寸.

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

    # 比例到具体尺寸的映射随服务商变化（Gitee 用 宽x高，千问云用 宽*高），
    # 因此从当前客户端取，而不是用全局常量
    supported_ratios = plugin.api_client.supported_ratios

    # 解析比例参数
    ratio = "1:1"
    prompt_parts = prompt.rsplit(" ", 1)
    if len(prompt_parts) > 1 and prompt_parts[1] in supported_ratios:
        ratio = prompt_parts[1]
        prompt = prompt_parts[0].strip()

    # 分割后再次检查提示词是否为空
    if not prompt:
        raise ValueError("请提供提示词，不能仅指定比例")

    # 确定目标尺寸
    target_size = plugin.api_client.default_size
    if ratio != "1:1" or (
        ratio == "1:1" and plugin.api_client.default_size not in supported_ratios["1:1"]
    ):
        target_size = supported_ratios[ratio][0]

    return prompt, target_size


def _is_file_uri(value: str) -> bool:
    """判断字符串是否为 ``file:`` URI（大小写不敏感，解析失败即否）."""
    if not isinstance(value, str):
        return False
    try:
        return urlparse(value).scheme.lower() == "file"
    except ValueError:
        return False


def _file_uri_to_path(value: str) -> str:
    """把 ``file://`` URI 归一化为本地路径，其余形式原样返回.

    AstrBot 的 ``Image.fromFileSystem`` 会把 ``file`` 字段写成 ``file://``
    URI（如 ``file:///tmp/a.png``），只有 ``path`` 字段才是可直接 ``open``
    的本地路径。上游改用 ``MediaResolver`` 后统一走 ``convert_to_file_path``，
    但为兼容旧宿主 / 测试桩件，这里对拿到的引用做一次归一化，避免把 URI
    当成文件路径传给 ``open()`` 直接报 FileNotFoundError。

    归一化规则与上游 ``media_utils.file_uri_to_path`` 保持一致：
    - 处理带 host（``file://host/path``，Windows 盘符除外）的形态；
    - 兼容旧 AstrBot 生成的 ``file:////abs/path``（POSIX 绝对路径）。

    Args:
        value: 组件上的 ``file`` / ``url`` / ``path`` 字段值

    Returns:
        本地路径（若输入是 ``file://`` URI）或原值
    """
    if not _is_file_uri(value):
        return value

    parsed = urlparse(value)
    netloc = parsed.netloc or ""
    raw_path = parsed.path or ""

    if netloc and netloc.lower() != "localhost":
        # Windows 盘符形态 file://C:/a.png
        if len(netloc) == 2 and netloc[1] == ":" and netloc[0].isalpha():
            return str(Path(url2pathname(f"{netloc}{raw_path}")))
        return str(Path(url2pathname(f"//{netloc}{raw_path}")))

    path = url2pathname(raw_path)
    # url2pathname 在 Windows 上会产出反斜杠，这里两种前缀都兼容
    if (
        len(path) >= 4
        and path[0] in ("/", "\\")
        and path[2] == ":"
        and path[1].isalpha()
    ):
        # file:///C:/a.png -> C:/a.png
        path = path[1:]
    elif os.name != "nt" and path.startswith("//"):
        # 兼容旧 AstrBot 生成的 file:////abs/path（POSIX 绝对路径）
        path = "/" + path.lstrip("/")
    return str(Path(path))


async def _resolve_image_component(component: Any) -> str | None:
    """把单个图片组件解析成本地可读路径.

    优先使用上游官方提供的 ``convert_to_file_path()``：它内部走
    ``MediaResolver``，统一支持本地路径、``file://`` URI、http(s) URL 与
    base64，并自带下载与落盘，是各版本间最稳的适配方式。

    Args:
        component: 消息中的图片组件

    Returns:
        本地文件路径；无法解析时返回 ``None``
    """
    convert = getattr(component, "convert_to_file_path", None)
    if callable(convert):
        try:
            path = await convert()
            if path:
                return str(path)
        except Exception as e:
            logger.debug(f"convert_to_file_path 解析失败，回退字段解析: {mask_text(e)}")

    # 兜底：旧宿主或测试桩件没有该异步方法时，按字段优先级手工解析
    raw_url = getattr(component, "url", "") or ""
    if raw_url:
        return await download_image(raw_url)

    # path 是真实本地路径，优先于可能是 file:// URI 的 file 字段
    raw_path = getattr(component, "path", "") or ""
    if raw_path:
        return _file_uri_to_path(str(raw_path))

    raw_file = getattr(component, "file", "") or ""
    if raw_file:
        if str(raw_file).startswith(("http://", "https://")):
            return await download_image(str(raw_file))
        return _file_uri_to_path(str(raw_file))

    return None


async def extract_images_from_message(event: AstrMessageEvent) -> list[str]:
    """从消息中提取所有图片的本地路径.

    兼容 AstrBot v4 的图片组件形态：无论组件持有的是本地路径、``file://``
    URI 还是 http(s) URL，都统一解析为可直接读取的本地文件路径，供上游
    图生图 / 图片编辑接口以 multipart 方式上传。

    Args:
        event: 消息事件对象

    Returns:
        图片本地路径列表（无法解析的组件会被跳过）
    """
    message_obj = event.message_obj
    # 显式标注元素类型，避免 mypy 推断失败
    image_paths: list[str] = []

    if not message_obj or not message_obj.message:
        return image_paths

    for component in message_obj.message:
        if not isinstance(component, Image):
            continue
        path = await _resolve_image_component(component)
        if path:
            image_paths.append(path)

    return image_paths


async def download_image(url: str) -> str | None:
    """下载图片到本地（带指数退避重试与分类日志）.

    用于把用户消息里的远程图片取回本地再上传给上游，属于「链路上的辅助请求」，
    失败不影响主流程，因此这里只记录分类后的日志并返回 ``None``，
    由调用方决定后续降级策略。

    Args:
        url: 图片 URL

    Returns:
        本地文件路径；下载失败时返回 ``None``
    """
    logger.debug(f"开始下载图片: {mask_text(url, limit=80)}")

    async def _fetch() -> bytes | None:
        """执行一次下载，返回响应体；非 200 视为业务失败（不重试）."""
        # 使用三段式超时，便于把「连不上」与「等不到响应」区分开
        async with aiohttp.ClientSession(timeout=build_timeout()) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"下载图片失败: HTTP {response.status}")
                    return None
                return await response.read()

    try:
        data = await with_retry(_fetch, label="辅助图片下载")
    except Exception as e:
        # 错误分类后再落日志，DNS / 超时 / TLS 一眼可辨，且已脱敏
        logger.error(f"下载图片失败: {to_user_message(e)}")
        return None

    if data is None:
        return None

    try:
        # 保存到临时目录
        temp_dir = Path("data/plugins/astrbot_plugin_models_ai/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{uuid.uuid4()}.png"
        temp_path.write_bytes(data)
        return str(temp_path)
    except OSError as e:
        logger.error(f"保存图片失败: {mask_text(e)}")
        return None
