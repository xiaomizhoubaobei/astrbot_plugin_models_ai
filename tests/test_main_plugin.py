"""插件主入口单元测试.

覆盖 ``main.py`` 的装配与配置收敛逻辑（插件类不依赖真实 AstrBot 运行时）：

- 按 provider 装配 Gitee / 千问云客户端；
- 未知 provider 回退，并发出迁移提示；
- 千问云模型未登记时回退默认模型、尺寸分隔符归一化为星号；
- 千问云专用 Key 为空时从通用 Key 迁移；
- ``close`` 释放资源。

命令包装器与 LLM 工具包装器只是薄转发，命令层与工具层的分支已分别在
``test_commands.py`` / ``test_llm_tools_draw.py`` 覆盖，这里不再重复。
"""

from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai import main as main_mod  # noqa: E402
from astrbot_plugin_models_ai.gitee.api_client import GiteeAIClient  # noqa: E402
from astrbot_plugin_models_ai.main import AIImage  # noqa: E402
from astrbot_plugin_models_ai.qianwen.api_client import QianwenClient  # noqa: E402


def _make_plugin(config):
    """构造插件实例（绕过真实 Star 运行时）."""
    return AIImage(context=object(), config=config)


def test_default_provider_is_gitee() -> None:
    """未配置 provider 时装配 Gitee 客户端."""
    plugin = _make_plugin({"api_key": "k1", "debug_mode": False})
    assert isinstance(plugin.api_client, GiteeAIClient)
    assert plugin.api_client.model == main_mod.DEFAULT_MODEL


def test_unknown_provider_falls_back_to_gitee() -> None:
    """未知 provider 回退 Gitee，且不装配千问云客户端."""
    plugin = _make_plugin({"provider": "openai", "api_key": "k1"})
    assert isinstance(plugin.api_client, GiteeAIClient)


def test_qianwen_provider_builds_qianwen_client() -> None:
    """provider=qianwen 时装配千问云客户端，且尺寸为星号格式."""
    plugin = _make_plugin(
        {
            "provider": "qianwen",
            "qianwen_api_key": "qk-1",
            "model": "z-image-turbo",
            "size": "1024x1024",
        }
    )
    assert isinstance(plugin.api_client, QianwenClient)
    assert plugin.api_client.default_size == "1024*1024"


def test_qianwen_unsupported_model_falls_back() -> None:
    """千问云未登记的模型回退为千问云默认模型."""
    plugin = _make_plugin(
        {
            "provider": "qianwen",
            "qianwen_api_key": "qk-1",
            "model": "flux-schnell",  # 非千问云型号
        }
    )
    assert plugin.api_client.model == main_mod.DEFAULT_QIANWEN_MODEL


def test_qianwen_legacy_key_migration() -> None:
    """qianwen 专用 Key 为空时从通用 api_key 迁移."""
    plugin = _make_plugin(
        {
            "provider": "qianwen",
            "api_key": "legacy-key",
            "qianwen_api_key": "",
        }
    )
    assert isinstance(plugin.api_client, QianwenClient)
    assert plugin.api_client.api_keys == ["legacy-key"]


def test_qianwen_empty_size_uses_default() -> None:
    """千问云尺寸配置为空时退回千问云默认分辨率."""
    plugin = _make_plugin({"provider": "qianwen", "qianwen_api_key": "qk", "size": ""})
    assert plugin.api_client.default_size == main_mod.DEFAULT_QIANWEN_SIZE


def test_api_key_string_parsed_as_list() -> None:
    """字符串形式的 api_key 被解析为列表."""
    plugin = _make_plugin({"api_key": "a,b,c"})
    assert plugin.api_client.api_keys == ["a", "b", "c"]


def test_components_initialized() -> None:
    """限流器与模型列表管理器应被装配."""
    plugin = _make_plugin({"api_key": "k1"})
    assert plugin.rate_limiter is not None
    assert plugin.model_lister is not None
    assert plugin.model_lister.api_client is plugin.api_client


def test_debug_mode_flag() -> None:
    """debug_mode 与 download_image_urls 从配置读取."""
    plugin = _make_plugin(
        {"api_key": "k1", "debug_mode": True, "download_image_urls": True}
    )
    assert plugin.debug_mode is True
    assert plugin.download_image_urls is True


def test_close_releases_client() -> None:
    """close 应转发到底层客户端 close."""
    plugin = _make_plugin({"api_key": "k1"})
    closed = []

    async def _close():
        closed.append(True)

    plugin.api_client.close = _close  # type: ignore[assignment]
    run(plugin.close())
    assert closed == [True]


# ===== 命令 / 工具包装器（薄转发）=====


def _drive(agen):
    async def _inner():
        return [item async for item in agen]

    return run(_inner())


def test_group_attribute_exists() -> None:
    """指令组属性应被框架装饰器挂上（桩件下为指令组对象）."""
    plugin = _make_plugin({"api_key": "k1"})
    assert hasattr(plugin, "ai_gitee_group")


def test_help_wrapper_forwards() -> None:
    plugin = _make_plugin({"api_key": "k1"})

    class Event:
        def get_sender_id(self):
            return "u1"

        def plain_result(self, text):
            return text

    out = _drive(plugin.help_command_wrapper(Event()))
    assert out and "ai-gitee 指令帮助" in out[0]


def test_generate_wrapper_forwards() -> None:
    plugin = _make_plugin({"api_key": "k1"})

    class Event:
        def get_sender_id(self):
            return "u1"

        def plain_result(self, text):
            return text

    out = _drive(plugin.generate_image_command_wrapper(Event(), ""))
    assert out and "请提供提示词" in out[0]


def test_switch_model_wrapper_forwards() -> None:
    plugin = _make_plugin({"api_key": "k1"})

    class Event:
        def get_sender_id(self):
            return "u1"

        def plain_result(self, text):
            return text

    out = _drive(plugin.switch_model_command_wrapper(Event(), ""))
    assert out and "请提供模型名称" in out[0]


def test_text2image_wrapper_forwards() -> None:
    plugin = _make_plugin({"api_key": "k1"})

    class Event:
        def get_sender_id(self):
            return "u1"

        def plain_result(self, text):
            return text

    out = _drive(plugin.list_models_command_wrapper(Event(), ""))
    assert out  # 至少产出一条"正在获取"或列表结果


def test_style_wrapper_forwards() -> None:
    plugin = _make_plugin({"api_key": "k1"})

    class Event:
        def get_sender_id(self):
            return "u1"

        def plain_result(self, text):
            return text

    out = _drive(plugin.style_command_wrapper(Event(), "", ""))
    assert out and "请指定风格名称" in out[0]


def test_ai_edit_wrapper_forwards() -> None:
    plugin = _make_plugin({"api_key": "k1"})

    class Event:
        def get_sender_id(self):
            return "u1"

        def plain_result(self, text):
            return text

    out = _drive(plugin.ai_edit_image_command_wrapper(Event(), "", ""))
    assert out and "请提供编辑提示词" in out[0]


def test_draw_wrapper_forwards() -> None:
    """LLM 工具包装器应转发到 draw_image_tool."""
    from _plugin_harness import FakeResult

    plugin = _make_plugin({"api_key": "k1"})

    class Event:
        def get_sender_id(self):
            return "u1"

        def plain_result(self, text):
            r = FakeResult()
            r.text = text
            return r

    out = _drive(plugin.draw(Event(), "   "))
    assert out  # 空提示词 -> 参数错误文本
