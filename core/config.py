"""配置管理模块.

负责配置常量定义、配置解析和验证。
"""

from typing import Any

# 插件配置
PLUGIN_NAME = "astrbot_plugin_models_ai"

# 配置常量
DEFAULT_BASE_URL = "https://ai.gitee.com/v1"
DEFAULT_MODEL = "z-image-turbo"
DEFAULT_SIZE = "1024x1024"
DEFAULT_INFERENCE_STEPS = 9
DEFAULT_NEGATIVE_PROMPT = (
    "low quality, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, worst quality, normal quality, "
    "jpeg artifacts, signature, watermark, username, blurry"
)

# 防抖和清理配置
DEBOUNCE_SECONDS = 10.0
MAX_CACHED_IMAGES = 20
OPERATION_CACHE_TTL = 300  # 5分钟清理一次过期操作记录
CLEANUP_INTERVAL = 10  # 每 N 次生成执行一次清理

# Gitee AI 支持的图片比例
SUPPORTED_RATIOS: dict[str, list[str]] = {
    "1:1": ["256x256", "512x512", "1024x1024", "2048x2048"],
    "4:3": ["1152x896", "2048x1536"],
    "3:4": ["768x1024", "1536x2048"],
    "3:2": ["2048x1360"],
    "2:3": ["1360x2048"],
    "16:9": ["1024x576", "2048x1152"],
    "9:16": ["576x1024", "1152x2048"],
}


# ===== 万相 / 千问云（QianwenAI 平台，DashScope 兼容协议）配置 =====
# 说明：千问云文生图不提供 OpenAI 兼容模式，故走原生 REST 接口（aiohttp 直连）。
# 官方文档：https://platform.qianwenai.com/docs/api-reference/image-generation/wan-text-to-image-v2/create-task
DEFAULT_QIANWEN_BASE_URL = "https://maas.qianwenaiapi.com/api/v1"
# 默认选用 z-image-turbo：同步链路、出图快，适合作为切到万相后的开箱默认值
DEFAULT_QIANWEN_MODEL = "z-image-turbo"
# 注意：千问云尺寸分隔符是星号「宽*高」，与 Gitee 的字母 x 不同，不可混用
DEFAULT_QIANWEN_SIZE = "1024*1024"

# 千问云支持的比例 -> 推荐分辨率（格式为 宽*高）
# 说明：各比例首项作为该比例的默认推荐值；具体型号可接受的范围由
# qianwen/model_config.py 的能力表做二次校验与降级，不会因越界直接失败。
QIANWEN_SUPPORTED_RATIOS: dict[str, list[str]] = {
    "1:1": ["1024*1024", "1280*1280", "1536*1536"],
    "4:3": ["1152*864", "1472*1104"],
    "3:4": ["864*1152", "1104*1472"],
    "3:2": ["1248*832", "1536*1024"],
    "2:3": ["832*1248", "1024*1536"],
    "16:9": ["1280*720", "1696*960"],
    "9:16": ["720*1280", "960*1696"],
}

# 千问云万相异步任务轮询策略，对齐官方「每 5 秒轮询一次」的建议：
# 初始按 QIANWEN_POLL_INITIAL_INTERVAL 轮询，超过快速窗口后逐步退避到
# QIANWEN_POLL_MAX_INTERVAL，累计超过 QIANWEN_POLL_TIMEOUT 判定为超时失败。
QIANWEN_POLL_INITIAL_INTERVAL = 5
QIANWEN_POLL_FAST_WINDOW = 30
QIANWEN_POLL_MAX_INTERVAL = 15
QIANWEN_POLL_TIMEOUT = 300


def parse_api_keys(api_keys: Any) -> list[str]:
    """解析 API Keys 配置，支持字符串和列表格式.

    Args:
        api_keys: API Keys 配置，可以是字符串或列表

    Returns:
        解析后的 API Keys 列表
    """
    if isinstance(api_keys, str):
        if api_keys:
            return [k.strip() for k in api_keys.split(",") if k.strip()]
        return []
    if isinstance(api_keys, list):
        return [str(k).strip() for k in api_keys if str(k).strip()]
    return []


# 服务商配置（provider）
PROVIDER_GITEE = "gitee"
PROVIDER_QIANWEN = "qianwen"  # 千问云（万相 / Qwen-Image / Z-Image）
SUPPORTED_PROVIDERS: list[str] = [PROVIDER_GITEE, PROVIDER_QIANWEN]

# 各服务商对应的 API Key 配置项，便于按 provider 取用正确的 Key
PROVIDER_API_KEY_FIELDS: dict[str, str] = {
    PROVIDER_GITEE: "api_key",
    PROVIDER_QIANWEN: "qianwen_api_key",
}


def resolve_provider(config: dict[str, Any]) -> tuple[str, str | None]:
    """解析服务商配置，并对历史配置做兼容迁移.

    背景：``qianwen``（千问云）服务商曾在 v0.0.7 短暂支持后回退移除，期间
    ``resolve_provider`` 会把 ``provider=qianwen`` 强制归一化为 ``gitee`` 并迁移 Key。
    现在千问云（万相）已重新支持，因此这里必须**恢复为正常接受**，否则用户
    即便配置了 ``provider=qianwen`` 也会被静默改回 Gitee。

    同时保留一项兼容动作：若 ``provider=qianwen`` 但 ``qianwen_api_key`` 为空，
    而 ``api_key`` 里有值（历史上被迁移过去的 Key），则把它迁回 ``qianwen_api_key``，
    避免用户升级后首个请求以「空 Key」形式失败。

    Args:
        config: 插件配置字典

    Returns:
        (effective_provider, migration_notice) 二元组：
        - effective_provider: 归一化后实际生效的服务商
        - migration_notice: 迁移/回退提示文案；无需处理时为 ``None``
    """
    raw_provider = (
        str(config.get("provider", PROVIDER_GITEE) or PROVIDER_GITEE).strip().lower()
    )

    # 未知 provider：回退到受支持的默认值，避免装配到不存在的能力上
    if raw_provider not in SUPPORTED_PROVIDERS:
        return (
            PROVIDER_GITEE,
            f"检测到未知的服务商 provider={raw_provider!r}，"
            f"已回退为 {PROVIDER_GITEE!r}。可选值：{', '.join(SUPPORTED_PROVIDERS)}。",
        )

    # 千问云：若专用 Key 项为空而通用项有值，则迁回专用项（历史迁移的逆向修复）
    if raw_provider == PROVIDER_QIANWEN:
        qianwen_field = PROVIDER_API_KEY_FIELDS[PROVIDER_QIANWEN]
        if not parse_api_keys(config.get(qianwen_field, [])):
            generic_keys = parse_api_keys(config.get("api_key", []))
            if generic_keys:
                # 直接写回 config，使后续所有读取方都能拿到迁移后的 Key
                config[qianwen_field] = generic_keys
                notice = (
                    f"检测到 provider={PROVIDER_QIANWEN!r} 但 {qianwen_field!r} 为空，"
                    f"已将 api_key 中的 {len(generic_keys)} 个 Key 迁移至 {qianwen_field!r}，"
                    "请确认该 Key 对千问云有效。"
                )
                return raw_provider, notice

    return raw_provider, None


def normalize_size(size: str, separator: str = "x") -> str:
    """统一图片尺寸的分隔符.

    配置层统一使用 ``宽x高``（字母 x）书写，而千问云要求 ``宽*高``（星号），
    因此跨服务商复用同一个 size 配置时需要做分隔符转换。

    Args:
        size: 原始尺寸字符串，例如 "1024x1024" 或 "1024*1024"
        separator: 目标分隔符，千问云传 "*"，Gitee 传 "x"

    Returns:
        归一化后的尺寸字符串；当 size 不是合法的「宽x高」格式时原样返回
    """
    if not size:
        return size
    # 同时兼容星号与字母 x 两种输入写法
    normalized = size.replace("*", "x")
    parts = normalized.split("x")
    if len(parts) != 2:
        return size
    width, height = parts
    if not (width.strip().isdigit() and height.strip().isdigit()):
        return size
    return f"{width.strip()}{separator}{height.strip()}"
