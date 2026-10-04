"""Gitee 模型列表管理器单元测试.

覆盖 ``gitee/model_manager.py``：类型参数解析 / 校验、输出格式化，
以及 ``list_models`` 的成功、空列表、类型非法与 API 异常四条分支。
"""

import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.gitee.model_manager import (  # noqa: E402
    MODEL_TYPES,
    ModelLister,
)


class StubClient:
    """记录 get_models 入参并返回预设值的客户端替身."""

    def __init__(self, models=None, raises=None):
        self._models = models if models is not None else []
        self._raises = raises
        self.calls: list[str] = []

    async def get_models(self, type=""):
        self.calls.append(type)
        if self._raises:
            raise self._raises
        return self._models


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", "text2image"),
        ("   ", "text2image"),
        ("--type=all", "all"),
        ("--type=text2text", "text2text"),
        ("--type= text2image ", "text2image"),
        ("text2image", "text2image"),
        ("  text2text  ", "text2text"),
    ],
)
def test_parse_type_param(raw, expected) -> None:
    """支持 --type= 与裸值两种写法，默认 text2image."""
    assert ModelLister._parse_type_param(raw) == expected


def test_validate_model_type() -> None:
    """合法类型通过，非法类型拒绝."""
    assert ModelLister._validate_model_type("text2image") is True
    assert ModelLister._validate_model_type("all") is True
    assert ModelLister._validate_model_type("nonsense") is False


def test_format_models_output() -> None:
    """输出应带编号并以总数结尾."""
    out = ModelLister._format_models_output([{"id": "a"}, {"id": "b"}, {"id": "c"}])
    assert "1. a" in out
    assert "2. b" in out
    assert "3. c" in out
    assert "共 3 个模型" in out


def test_list_models_default_passes_text2image() -> None:
    """默认请求将 type=text2image 透传给客户端."""
    client = StubClient(models=[{"id": "z-image-turbo"}])
    lister = ModelLister(client)
    ok, msg = run(lister.list_models(""))
    assert ok is True
    assert "z-image-turbo" in msg
    assert client.calls == ["text2image"]


def test_list_models_all_strips_type() -> None:
    """type=all 时不传 type 参数（抓取所有模型）."""
    client = StubClient(models=[{"id": "x"}])
    lister = ModelLister(client)
    ok, _ = run(lister.list_models("--type=all"))
    assert ok is True
    assert client.calls == [""]


def test_list_models_empty_returns_friendly_message() -> None:
    """空列表返回友好提示，而不是空白输出."""
    client = StubClient(models=[])
    lister = ModelLister(client)
    ok, msg = run(lister.list_models("--type=text2image"))
    assert ok is True
    assert "没有找到任何模型" in msg


def test_list_models_invalid_type() -> None:
    """非法类型直接拒绝，且不调用 API."""
    client = StubClient(models=[{"id": "x"}])
    lister = ModelLister(client)
    ok, msg = run(lister.list_models("--type=bogus"))
    assert ok is False
    assert "无效的模型类型" in msg
    assert client.calls == []


def test_list_models_api_exception_returns_failure() -> None:
    """客户端抛异常时返回失败元组，不向上抛."""
    client = StubClient(raises=RuntimeError("boom"))
    lister = ModelLister(client)
    ok, msg = run(lister.list_models(""))
    assert ok is False
    assert "获取模型列表失败" in msg


def test_model_types_contains_expected() -> None:
    """类型白名单应包含关键类型."""
    for t in ["all", "text2image", "image2image", "text2video"]:
        assert t in MODEL_TYPES


def test_debug_log_branch() -> None:
    """debug 模式日志分支可执行."""
    lister = ModelLister(StubClient(), debug_mode=True)
    lister.debug_log("hi")
