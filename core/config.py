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
# 当前仅支持 gitee；qianwen 曾短暂支持后于 v0.0.7 回退，作为历史配置识别用常量保留
PROVIDER_GITEE = "gitee"
PROVIDER_QIANWEN = "qianwen"  # 已下线：历史配置识别与迁移用
SUPPORTED_PROVIDERS: list[str] = [PROVIDER_GITEE]


def resolve_provider(config: dict[str, Any]) -> tuple[str, str | None]:
    """解析服务商配置，并对已下线的 provider 做兼容迁移.

    背景：``qianwen``（千问云）服务商曾在 v0.0.7 短暂支持，随后被回退移除。
    但用户可能已持久化保存了 ``provider=qianwen`` 的配置，此时：
    - ``api_key``（Gitee Key）为空，而 Key 实际填在 ``qianwen_api_key`` 里；
    - 若直接按 gitee 装配客户端，会带着空 Key 初始化，直到首次生图才失败，
      错误信息与真实原因（服务商已下线）脱节，难以排查。

    为保证「升级后首次请求必失败」变为「可诊断的明确提示」，这里做两件事：
    1. 把已下线 provider 归一化为当前唯一可用服务商 ``gitee``；
    2. 在 ``api_key`` 为空时，尝试从 ``qianwen_api_key`` 迁移 Key（仅在能明确
       取到非空值时才迁移，不覆盖用户已填的 ``api_key``）。

    Args:
        config: 插件配置字典

    Returns:
        (effective_provider, migration_notice) 二元组：
        - effective_provider: 归一化后实际生效的服务商（当前恒为 ``gitee``）
        - migration_notice: 迁移提示文案；无需迁移时为 ``None``
    """
    raw_provider = str(config.get("provider", PROVIDER_GITEE) or PROVIDER_GITEE).strip().lower()

    # 未知或已下线 provider：归一化为受支持的默认值，避免装配到不存在的能力上
    if raw_provider not in SUPPORTED_PROVIDERS:
        notice = (
            f"检测到已下线或未知的服务商 provider={raw_provider!r}，"
            f"已回退为 {PROVIDER_GITEE!r}。"
        )
        # 历史 qianwen 配置：Key 通常填在 qianwen_api_key，需迁移到 api_key 才能继续使用
        if raw_provider == PROVIDER_QIANWEN and not parse_api_keys(config.get("api_key", [])):
            legacy_keys = parse_api_keys(config.get("qianwen_api_key", []))
            if legacy_keys:
                # 直接写回 config，使后续所有读取方（含命令层）都能拿到迁移后的 Key
                config["api_key"] = legacy_keys
                config.pop("qianwen_api_key", None)
                notice += (
                    f"已自动将 {len(legacy_keys)} 个千问云 API Key 迁移至 Gitee 配置项，"
                    "请确认该 Key 对 Gitee AI 有效。"
                )
        return PROVIDER_GITEE, notice

    return raw_provider, None
