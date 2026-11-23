"""通用 OpenAI 兼容上游单元测试.

覆盖 ``provider=openai`` 的装配、Key 回退、生图两种结果格式、模型列表、
图片编辑与错误分类；不发真实网络请求。
"""

import base64

import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai import main as main_mod  # noqa: E402
from astrbot_plugin_models_ai.main import AIImage  # noqa: E402
from astrbot_plugin_models_ai.openai_compat import OpenAICompatibleClient  # noqa: E402
from astrbot_plugin_models_ai.openai_compat import api_client as oc  # noqa: E402


def _make_plugin(config):
    """构造插件实例（绕过真实 Star 运行时）."""
    return AIImage(context=object(), config=config)


class _ImageData:
    """模拟 SDK 返回的图片数据."""

    def __init__(self, url: str | None = None, b64: str | None = None) -> None:
        if url is not None:
            self.url = url
        if b64 is not None:
            self.b64_json = b64


class _Resp:
    """模拟 SDK 响应."""

    def __init__(self, data: list[_ImageData]) -> None:
        self.data = data


class _Images:
    """模拟 SDK images 资源."""

    def __init__(self, data: list[_ImageData]) -> None:
        self._data = data
        self.generate_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    async def generate(self, **kwargs):
        """记录参数并返回假响应."""
        self.generate_calls.append(kwargs)
        return _Resp(self._data)

    async def edit(self, **kwargs):
        """记录参数并返回假响应."""
        self.edit_calls.append(kwargs)
        return _Resp(self._data)


def _make_client(**overrides) -> OpenAICompatibleClient:
    """构造通用 OpenAI 兼容客户端."""
    kwargs = dict(
        api_keys=["k1", "k2"],
        model="test-model",
        default_size="1024x1024",
        base_url="https://openai.example.com/v1",
    )
    kwargs.update(overrides)
    return OpenAICompatibleClient(**kwargs)


def _patch_sdk(client: OpenAICompatibleClient, images: _Images) -> None:
    """替换为假 SDK 客户端."""

    class _FakeSDK:
        def __init__(self) -> None:
            self.images = images

    client.client_manager.get_openai_client = lambda _k: _FakeSDK()  # type: ignore


# ===== 装配 =====


def test_openai_provider_builds_client() -> None:
    """provider=openai 时装配通用客户端，并把端点主机纳入白名单."""
    plugin = _make_plugin(
        {
            "provider": "openai",
            "openai_api_key": "key-1",
            "openai_base_url": "https://openai.example.com/v1",
            "model": "test-model",
        }
    )
    assert isinstance(plugin.api_client, OpenAICompatibleClient)
    assert plugin.api_client.api_keys == ["key-1"]
    assert plugin.api_client.model == "test-model"
    assert "openai.example.com" in plugin.api_client.image_manager._allowed_hosts


def test_openai_provider_falls_back_to_generic_key() -> None:
    """专用 Key 为空时回退通用 api_key，便于从 Gitee 迁移."""
    plugin = _make_plugin({"provider": "openai", "api_key": "generic-key"})
    assert plugin.api_client.api_keys == ["generic-key"]


def test_openai_provider_defaults() -> None:
    """未配置 base_url / model / size 时使用通用默认值."""
    plugin = _make_plugin({"provider": "openai", "openai_api_key": "key"})
    assert plugin.api_client.base_url == main_mod.DEFAULT_OPENAI_BASE_URL
    assert plugin.api_client.model == main_mod.DEFAULT_MODEL
    assert plugin.api_client.default_size == main_mod.DEFAULT_SIZE


def test_openai_extra_body_parsed() -> None:
    """合法 JSON 字符串形式的额外请求体被解析为字典."""
    plugin = _make_plugin(
        {
            "provider": "openai",
            "openai_api_key": "key",
            "openai_extra_body": '{"response_format": "b64_json"}',
        }
    )
    assert plugin.api_client.extra_body == {"response_format": "b64_json"}


def test_openai_extra_body_bad_json_ignored() -> None:
    """非法 JSON 的额外请求体被忽略，不影响插件初始化."""
    plugin = _make_plugin(
        {
            "provider": "openai",
            "openai_api_key": "key",
            "openai_extra_body": "not-json",
        }
    )
    assert plugin.api_client.extra_body == {}


def test_openai_key_round_robin() -> None:
    """多 Key 按索引轮询."""
    client = _make_client()
    assert [client._get_next_api_key() for _ in range(3)] == ["k1", "k2", "k1"]


def test_openai_empty_key_raises() -> None:
    """未配置 Key 时报错."""
    client = _make_client(api_keys=[])
    with pytest.raises(ValueError, match="请先配置 API Key"):
        client._get_next_api_key()


# ===== 生图 =====


def test_generate_image_url_path(tmp_path) -> None:
    """返回 URL 时走下载落盘分支，并透传 size 与 extra_body."""
    client = _make_client(extra_body={"response_format": "url"})
    images = _Images([_ImageData(url="https://openai.example.com/a.png")])
    _patch_sdk(client, images)

    out = str(tmp_path / "a.png")

    async def _fake_session():
        return object()

    async def _download(url, session):
        return out

    client.client_manager.get_http_session = _fake_session  # type: ignore[assignment]
    client.image_manager.download_image = _download  # type: ignore[assignment]

    assert run(client.generate_image("一只猫", size="512x512")) == out
    call = images.generate_calls[0]
    assert call["prompt"] == "一只猫"
    assert call["model"] == "test-model"
    assert call["size"] == "512x512"
    assert call["extra_body"] == {"response_format": "url"}


def test_generate_image_base64_path(tmp_path) -> None:
    """返回 b64_json 时走 Base64 落盘分支."""
    client = _make_client()
    content = base64.b64encode(b"fake-image").decode()
    images = _Images([_ImageData(b64=content)])
    _patch_sdk(client, images)

    out = str(tmp_path / "b.png")

    async def _save(b64_data):
        return out

    client.image_manager.save_base64_image = _save  # type: ignore[assignment]
    assert run(client.generate_image("一只狗")) == out
    assert "size" in images.generate_calls[0]
    assert "extra_body" not in images.generate_calls[0]


def test_generate_image_no_data_raises() -> None:
    """响应无数据时抛出中文异常."""
    client = _make_client()
    _patch_sdk(client, _Images([]))
    with pytest.raises(RuntimeError, match="未返回数据"):
        run(client.generate_image("空响应"))


def test_generate_image_auth_error(monkeypatch) -> None:
    """认证错误转换为中文 RuntimeError."""
    from openai import AuthenticationError

    client = _make_client()

    class _BoomImages:
        async def generate(self, **kwargs):
            raise AuthenticationError(
                "invalid key",
                response=type(
                    "R",
                    (),
                    {"status_code": 401, "request": object(), "headers": {}},
                )(),
                body=None,
            )

    _patch_sdk(client, _BoomImages())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="API Key 无效"):
        run(client.generate_image("测试"))


# ===== 模型列表 =====


def test_get_models() -> None:
    """模型列表按 OpenAI 协议字段解析."""
    client = _make_client()

    class _RespCtx:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return {
                "data": [
                    {"id": "m1", "created": 1, "owned_by": "owner"},
                    {"id": "m2"},
                ]
            }

        async def text(self):
            return ""

    class _Session:
        def get(self, url, headers):
            assert url == "https://openai.example.com/v1/models"
            return _RespCtx()

    async def _fake_session():
        return _Session()

    client.client_manager.get_http_session = _fake_session  # type: ignore[assignment]
    models = run(client.get_models())
    assert models == [
        {"id": "m1", "created": 1, "owned_by": "owner"},
        {"id": "m2", "created": 0, "owned_by": ""},
    ]


# ===== 图片编辑 =====


def test_edit_image(tmp_path) -> None:
    """本地图片编辑走标准 images.edit 接口."""
    client = _make_client()
    image = tmp_path / "src.png"
    image.write_bytes(b"fake")

    images = _Images([_ImageData(b64=base64.b64encode(b"edited").decode())])
    _patch_sdk(client, images)

    out = str(tmp_path / "out.png")

    async def _save(b64_data):
        return out

    client.image_manager.save_base64_image = _save  # type: ignore[assignment]
    assert run(client.edit_image("改成油画", [str(image)])) == out
    call = images.edit_calls[0]
    assert call["model"] == "test-model"
    assert call["prompt"] == "改成油画"
    assert call["image"][0][0] == "src.png"


def test_edit_image_unsupported_provider_hint() -> None:
    """千问云仍保留原有不支持编辑的提示（回归保护）."""
    plugin = _make_plugin({"provider": "qianwen", "qianwen_api_key": "key"})
    with pytest.raises(RuntimeError, match="暂不支持图片编辑"):
        run(plugin.api_client.edit_image("test", []))
