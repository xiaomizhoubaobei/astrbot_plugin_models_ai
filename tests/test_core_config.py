"""配置解析单元测试.

覆盖 ``core/config.py`` 的三个公开解析函数：API Key 归一化、
服务商解析（含历史迁移的逆向修复）、尺寸分隔符归一化。
"""

import pytest
from _plugin_harness import ensure_host  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.core import config as cfg  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a,b,c", ["a", "b", "c"]),
        (" a , b ", ["a", "b"]),
        ("single", ["single"]),
        ("", []),
        (",,", []),
        (["x", " y "], ["x", "y"]),
        ([1, 2], ["1", "2"]),
        ([], []),
        (None, []),
        (123, []),
    ],
)
def test_parse_api_keys(raw, expected) -> None:
    """字符串与列表两种配置都要兼容，且过滤空项."""
    assert cfg.parse_api_keys(raw) == expected


def test_resolve_provider_default_gitee() -> None:
    """未配置 provider 时默认 gitee，且无迁移提示."""
    provider, notice = cfg.resolve_provider({})
    assert provider == "gitee"
    assert notice is None


def test_resolve_provider_unknown_falls_back() -> None:
    """未知 provider 回退 gitee，并给出可诊断提示."""
    provider, notice = cfg.resolve_provider({"provider": "openai"})
    assert provider == "gitee"
    assert notice and "未知的服务商" in notice


def test_resolve_provider_qianwen_accepted() -> None:
    """qianwen 现在应被正常接受（不再强制改回 gitee）."""
    provider, notice = cfg.resolve_provider(
        {"provider": "qianwen", "qianwen_api_key": "qk-1"}
    )
    assert provider == "qianwen"
    assert notice is None


def test_resolve_provider_qianwen_migrates_legacy_key() -> None:
    """qianwen 且专用 Key 为空、通用 Key 有值时，应迁回专用项."""
    config = {"provider": "qianwen", "api_key": "legacy-key", "qianwen_api_key": ""}
    provider, notice = cfg.resolve_provider(config)
    assert provider == "qianwen"
    assert cfg.parse_api_keys(config["qianwen_api_key"]) == ["legacy-key"]
    assert notice and "迁移" in notice


def test_resolve_provider_qianwen_no_migration_when_both_empty() -> None:
    """两个 Key 项都为空时不做迁移，也不报提示."""
    config = {"provider": "qianwen", "api_key": "", "qianwen_api_key": ""}
    provider, notice = cfg.resolve_provider(config)
    assert provider == "qianwen"
    assert notice is None


def test_resolve_provider_normalizes_case_and_space() -> None:
    """provider 值应做大小写与空白归一化."""
    provider, _ = cfg.resolve_provider({"provider": "  QIANWEN  "})
    assert provider == "qianwen"


@pytest.mark.parametrize(
    "raw,sep,expected",
    [
        ("1024x1024", "*", "1024*1024"),
        ("1024*1024", "x", "1024x1024"),
        ("1024*1024", "*", "1024*1024"),
        ("512x768", "*", "512*768"),
        (" 1024 x 1024 ", "*", "1024*1024"),
    ],
)
def test_normalize_size_converts_separator(raw, sep, expected) -> None:
    """星号与字母 x 两种写法可互转，且容忍两侧空白."""
    assert cfg.normalize_size(raw, sep) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "1024", "1024x", "axb", "1024x1024x1024"],
)
def test_normalize_size_invalid_returned_unchanged(raw) -> None:
    """非法尺寸原样返回，不得抛异常或造出坏值."""
    assert cfg.normalize_size(raw, "*") == raw


def test_public_constants_defined() -> None:
    """关键常量应存在且格式正确（分隔符口径不能混用）."""
    assert cfg.DEFAULT_QIANWEN_SIZE == "1024*1024"
    assert "x" in cfg.DEFAULT_SIZE
    assert cfg.PROVIDER_QIANWEN in cfg.SUPPORTED_PROVIDERS
    assert cfg.PROVIDER_GITEE in cfg.SUPPORTED_PROVIDERS
    # 千问云比例表使用星号
    assert all("*" in sizes[0] for sizes in cfg.QIANWEN_SUPPORTED_RATIOS.values())
