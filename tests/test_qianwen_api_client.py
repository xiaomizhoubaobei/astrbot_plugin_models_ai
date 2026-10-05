"""千问云客户端单元测试.

覆盖 ``qianwen/api_client.py`` 的行为契约，重点在三条容易被线上踩到的路径：

1. **请求构造**：新旧端点分别用 ``messages`` / ``prompt``；不支持的参数
   （negative_prompt / prompt_extend）不得下发，否则上游直接报错。
2. **结果解析**：``choices`` 与 ``results`` 两种响应格式都要能取到图片 URL，
   且声明格式不命中时能回退到另一种格式。
3. **错误与链路**：同步/异步链路、任务提交幂等键、轮询状态机（成功 / 失败 /
   超时 / 非 JSON）、错误分类脱敏、图片下载落盘。

全部通过假 aiohttp Session 驱动，不发真实网络请求。
"""

import asyncio
import json

import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.qianwen import api_client as ac  # noqa: E402
from astrbot_plugin_models_ai.qianwen.api_client import (  # noqa: E402
    QianwenClient,
    QianwenResponseError,
)


class FakeResponse:
    """最小 aiohttp 响应替身：支持 ``async with`` 与 ``text()``."""

    def __init__(self, body: str = "", status: int = 200, headers=None):
        self._body = body
        self.status = status
        self.headers = headers or {}

    async def text(self) -> str:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakePostContext:
    """``session.post(...)`` 返回的上下文管理器，记录请求参数."""

    def __init__(self, response: FakeResponse, recorder: list, kwargs: dict):
        self.response = response
        self.recorder = recorder
        self.kwargs = kwargs

    async def __aenter__(self):
        self.recorder.append(self.kwargs)
        return self.response

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """假 Session：按脚本依次吐出响应，并记录每次请求."""

    def __init__(self, responses):
        # responses 可为单个响应或响应列表（按调用顺序消费）
        self._responses = responses if isinstance(responses, list) else [responses]
        self._idx = 0
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def _next(self):
        if self._idx < len(self._responses):
            r = self._responses[self._idx]
            self._idx += 1
            return r
        return self._responses[-1]

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return FakePostContext(self._next(), self.posts, {"url": url, **kwargs})

    def get(self, url, **kwargs):
        self.gets.append({"url": url, **kwargs})
        return FakePostContext(self._next(), self.gets, {"url": url, **kwargs})


def _make_client(**overrides) -> QianwenClient:
    kwargs = dict(
        api_keys=["key-a", "key-b"],
        model="z-image-turbo",
        default_size="1024*1024",
        negative_prompt="低质量",
        base_url="https://example.invalid/api/v1",
        prompt_extend=True,
        debug_mode=False,
    )
    kwargs.update(overrides)
    return QianwenClient(**kwargs)


def test_get_next_api_key_round_robin() -> None:
    """多 Key 应按索引轮询，末位回到首位."""
    c = _make_client()
    assert [c._get_next_api_key() for _ in range(4)] == [
        "key-a",
        "key-b",
        "key-a",
        "key-b",
    ]


def test_get_next_api_key_empty_raises() -> None:
    """无 Key 时给出明确中文提示，而不是 IndexError."""
    c = _make_client(api_keys=[])
    with pytest.raises(ValueError, match="请先配置千问云 API Key"):
        c._get_next_api_key()


def test_build_headers_async_and_idempotency() -> None:
    """异步提交需带 X-DashScope-Async；幂等键仅在非空时注入."""
    c = _make_client()
    sync_headers = c._build_headers("k")
    assert sync_headers["Authorization"] == "Bearer k"
    assert "X-DashScope-Async" not in sync_headers
    assert "Idempotency-Key" not in sync_headers

    async_headers = c._build_headers("k", is_async=True, idempotency_key="idem-1")
    assert async_headers["X-DashScope-Async"] == "enable"
    assert async_headers["Idempotency-Key"] == "idem-1"


def test_build_input_switches_on_endpoint() -> None:
    """新端点用 messages，旧端点用 prompt."""
    c = _make_client()
    new_spec = ac.get_model_spec("z-image-turbo")
    old_spec = ac.get_model_spec("wan2.5-t2i-preview")

    new_input = c._build_input("画一只猫", new_spec)
    assert new_input["messages"][0]["content"][0]["text"] == "画一只猫"
    assert "prompt" not in new_input

    old_input = c._build_input("画一只猫", old_spec)
    assert old_input == {"prompt": "画一只猫"}


def test_build_parameters_respects_model_capabilities() -> None:
    """不支持的参数不得下发（否则上游直接报错）."""
    c = _make_client(negative_prompt="低质量", prompt_extend=True)

    # z-image-turbo 不支持 negative_prompt，但支持 prompt_extend
    spec_no = ac.get_model_spec("z-image-turbo")
    params = c._build_parameters("1024*1024", spec_no)
    assert params["size"] == "1024*1024"
    assert params["n"] == 1
    assert "negative_prompt" not in params
    assert params["prompt_extend"] is True

    # 万相 2.6 两者都支持
    spec_yes = ac.get_model_spec("wan2.6-t2i")
    params2 = c._build_parameters("1280*1280", spec_yes)
    assert params2["negative_prompt"] == "低质量"
    assert params2["prompt_extend"] is True


def test_qwen_image_payload_matches_official_shape() -> None:
    """Qwen-Image 的请求体应与官方 cURL 一致：messages 传参 + choices 结果 + 双参数."""
    c = _make_client(
        model="qwen-image-3.0-pro", negative_prompt="低质量", prompt_extend=True
    )
    spec = ac.get_model_spec("qwen-image-3.0-pro")

    # 提示词走 input.messages，而非旧端点的 input.prompt
    payload_input = c._build_input("画一幅海报", spec)
    assert payload_input["messages"][0]["role"] == "user"
    assert payload_input["messages"][0]["content"][0]["text"] == "画一幅海报"
    assert "prompt" not in payload_input

    # parameters 带 size / n / negative_prompt / prompt_extend
    params = c._build_parameters("2048*2048", spec)
    assert params["size"] == "2048*2048"
    assert params["n"] == 1
    assert params["negative_prompt"] == "低质量"
    assert params["prompt_extend"] is True

    # 完整请求体结构
    payload = c._build_payload("画一幅海报", "2048*2048", spec)
    assert payload["model"] == "qwen-image-3.0-pro"
    assert "input" in payload and "parameters" in payload


def test_qwen_image_extract_choices_format() -> None:
    """Qwen-Image 结果位于 output.choices[].message.content[].image."""
    c = _make_client(model="qwen-image-3.0-pro")
    spec = ac.get_model_spec("qwen-image-3.0-pro")
    data = {
        "output": {
            "choices": [
                {
                    "message": {"content": [{"image": "https://cdn/qwen.png"}]},
                    "finish_reason": "stop",
                }
            ]
        }
    }
    assert c._extract_image_url(data, spec) == "https://cdn/qwen.png"


def test_qwen_image_sync_generate_success(monkeypatch) -> None:
    """Qwen-Image 走同步链路：一次 POST 即返回图片并落盘."""
    body = json.dumps(
        {
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://cdn/qwen.png"}]}}
                ]
            },
            "request_id": "req-qwen",
        }
    )
    session = FakeSession(FakeResponse(body=body, status=200))
    c = _make_client(model="qwen-image-3.0-pro")

    async def _fake_session():
        return session

    async def _fake_download(url, sess):
        assert url == "https://cdn/qwen.png"
        return "/tmp/qwen.png"

    monkeypatch.setattr(c.client_manager, "get_http_session", _fake_session)
    monkeypatch.setattr(c, "_download", _fake_download)

    result = run(c.generate_image("画一只猫", "1024*1024"))
    assert result == "/tmp/qwen.png"
    # 同步链路不带 X-DashScope-Async 头
    assert "X-DashScope-Async" not in session.posts[0]["headers"]


def test_build_parameters_skips_empty_negative_prompt() -> None:
    """negative_prompt 为空时即使模型支持也不下发."""
    c = _make_client(negative_prompt="")
    spec = ac.get_model_spec("wan2.6-t2i")
    assert "negative_prompt" not in c._build_parameters("1280*1280", spec)


def test_resolve_size_uses_default_when_empty() -> None:
    """未指定尺寸时回落到客户端默认尺寸."""
    c = _make_client(default_size="1024*1024")
    spec = ac.get_model_spec("z-image-turbo")
    assert c._resolve_size("", spec) == "1024*1024"


def test_extract_image_url_both_formats() -> None:
    """两种线上响应格式都能取到 URL."""
    c = _make_client()

    choices_spec = ac.get_model_spec("z-image-turbo")  # choices
    choices_data = {
        "output": {
            "choices": [{"message": {"content": [{"image": "https://cdn/x.png"}]}}]
        }
    }
    assert c._extract_image_url(choices_data, choices_spec) == "https://cdn/x.png"

    results_spec = ac.get_model_spec("wan2.5-t2i-preview")  # results
    results_data = {"output": {"results": [{"url": "https://cdn/y.png"}]}}
    assert c._extract_image_url(results_data, results_spec) == "https://cdn/y.png"


def test_extract_image_url_falls_back_to_other_format() -> None:
    """声明格式未命中时应回退到另一种格式（抵御线上字段调整）."""
    c = _make_client()
    # spec 声明 choices，但响应是 results 形状
    spec = ac.get_model_spec("z-image-turbo")
    data = {"output": {"results": [{"url": "https://cdn/fallback.png"}]}}
    assert c._extract_image_url(data, spec) == "https://cdn/fallback.png"


def test_extract_image_url_missing_raises() -> None:
    """响应里完全没有图片地址时给出中文异常."""
    c = _make_client()
    spec = ac.get_model_spec("z-image-turbo")
    with pytest.raises(RuntimeError, match="未返回图片地址"):
        c._extract_image_url({"output": {}}, spec)


def test_build_error_classifies_status_and_code() -> None:
    """错误分类：认证 / 限流 / 审核 / 5xx / 兜底."""
    c = _make_client()
    assert "API Key 无效" in str(c._build_error({}, 401))
    assert "API Key 无效" in str(c._build_error({"code": "InvalidApiKey"}, 400))
    assert "超限" in str(c._build_error({"code": "Throttling"}, 400))
    assert "超限" in str(c._build_error({}, 429))
    assert "内容安全审核" in str(c._build_error({"code": "DataInspectionFailed"}, 400))
    assert "内容安全审核" in str(c._build_error({"code": "IPInfringementSuspect"}, 400))
    assert "服务器内部错误" in str(c._build_error({}, 503))
    assert "调用失败" in str(c._build_error({"code": "X", "message": "Y"}, 400))


def test_build_error_masks_credentials() -> None:
    """兜底错误文案必须脱敏，不得把 Key 带进回包."""
    c = _make_client()
    msg = str(
        c._build_error(
            {"code": "E", "message": "failed?api_key=sk-abcdef1234567890"}, 400
        )
    )
    assert "sk-abcdef1234567890" not in msg


def test_read_json_safely_200_ok() -> None:
    """200 且为合法 JSON 对象时正常解析."""
    c = _make_client()
    resp = FakeResponse(json.dumps({"output": {"task_id": "t1"}}), 200)
    assert run(c._read_json_safely(resp, 200)) == {"output": {"task_id": "t1"}}


def test_read_json_safely_200_empty_raises() -> None:
    """200 空响应体属确定性失败."""
    c = _make_client()
    with pytest.raises(QianwenResponseError, match="空响应体"):
        run(c._read_json_safely(FakeResponse("", 200), 200))


def test_read_json_safely_200_non_json_raises() -> None:
    """200 非 JSON 属确定性失败，须保留片段."""
    c = _make_client()
    with pytest.raises(QianwenResponseError, match="无法解析为 JSON"):
        run(c._read_json_safely(FakeResponse("<html>oops</html>", 200), 200))


def test_read_json_safely_200_top_level_not_object_raises() -> None:
    """200 顶层非对象（如数组）属确定性失败."""
    c = _make_client()
    with pytest.raises(QianwenResponseError, match="顶层不是 JSON 对象"):
        run(c._read_json_safely(FakeResponse("[1,2,3]", 200), 200))


def test_read_json_safely_non200_html_returns_empty() -> None:
    """非 200 且响应非 JSON（网关 HTML）时返回空字典，交由状态码分类."""
    c = _make_client()
    assert run(c._read_json_safely(FakeResponse("<html>502</html>", 502), 502)) == {}


def test_read_json_safely_non200_empty_returns_empty() -> None:
    """非 200 且空响应体返回空字典."""
    c = _make_client()
    assert run(c._read_json_safely(FakeResponse("", 503), 503)) == {}


def test_read_json_safely_non200_top_level_not_object() -> None:
    """非 200 但顶层非对象时同样返回空字典."""
    c = _make_client()
    assert run(c._read_json_safely(FakeResponse('"just-a-string"', 500), 500)) == {}


# ===== 链路级测试 =====


def _patch_session(client: QianwenClient, session: FakeSession) -> None:
    """把假 Session 注入客户端（绕过真实连接池）."""

    async def _get_session():
        return session

    client.client_manager.get_http_session = _get_session  # type: ignore[assignment]


def _patch_download(client: QianwenClient, path: str = "/tmp/out.png") -> list:
    """替换图片下载为记录调用，返回记录列表."""
    calls: list[tuple] = []

    async def _fake_download(image_url, session):
        calls.append((image_url, session))
        return path

    client._download = _fake_download  # type: ignore[assignment]
    return calls


def test_generate_image_sync_success() -> None:
    """同步链路：构造请求 -> 解析 choices -> 下载落盘."""
    c = _make_client(model="z-image-turbo")
    body = json.dumps(
        {
            "output": {
                "choices": [{"message": {"content": [{"image": "https://cdn/a.png"}]}}]
            }
        }
    )
    session = FakeSession(FakeResponse(body, 200))
    _patch_session(c, session)
    downloads = _patch_download(c)

    result = run(c.generate_image("一个女孩", "1024*1024"))

    assert result == "/tmp/out.png"
    assert downloads and downloads[0][0] == "https://cdn/a.png"
    # 请求体走新端点：messages 传参
    sent = session.posts[0]["json"]
    assert sent["model"] == "z-image-turbo"
    assert sent["input"]["messages"][0]["content"][0]["text"] == "一个女孩"
    # 同步请求不应带异步头
    assert "X-DashScope-Async" not in session.posts[0]["headers"]


def test_generate_image_async_success() -> None:
    """异步链路：提交任务 -> 轮询直到 SUCCEEDED -> 下载."""
    c = _make_client(model="wan2.6-t2i")
    submit_body = json.dumps({"output": {"task_id": "task-123"}})
    poll_body = json.dumps(
        {
            "output": {
                "task_status": "SUCCEEDED",
                "choices": [{"message": {"content": [{"image": "https://cdn/b.png"}]}}],
            }
        }
    )
    session = FakeSession(
        [FakeResponse(submit_body, 200), FakeResponse(poll_body, 200)]
    )
    _patch_session(c, session)
    downloads = _patch_download(c, "/tmp/b.png")

    result = run(c.generate_image("一只猫", "1280*1280"))

    assert result == "/tmp/b.png"
    # 提交请求应带异步头与幂等键
    submit_headers = session.posts[0]["headers"]
    assert submit_headers["X-DashScope-Async"] == "enable"
    assert submit_headers["Idempotency-Key"].startswith("cnb-qianwen-submit")
    # 轮询 URL 包含 task_id
    assert "task-123" in session.gets[0]["url"]
    assert downloads[0][0] == "https://cdn/b.png"


def test_generate_image_prompt_truncated() -> None:
    """超长提示词按模型上限截断后才下发."""
    c = _make_client(model="z-image-turbo")  # 上限 800
    body = json.dumps(
        {
            "output": {
                "choices": [{"message": {"content": [{"image": "https://cdn/a.png"}]}}]
            }
        }
    )
    session = FakeSession(FakeResponse(body, 200))
    _patch_session(c, session)
    _patch_download(c)

    run(c.generate_image("字" * 2000, "1024*1024"))
    sent_prompt = session.posts[0]["json"]["input"]["messages"][0]["content"][0]["text"]
    assert len(sent_prompt) == 800


def test_generate_image_wraps_unknown_error() -> None:
    """同步链路里的未知异常应被包装为中文 RuntimeError."""
    c = _make_client(model="z-image-turbo")

    class BoomSession:
        def post(self, *a, **k):
            raise ValueError("boom")

    _patch_session(c, BoomSession())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="千问云请求失败"):
        run(c.generate_image("x", "1024*1024"))


def test_submit_task_missing_task_id_raises() -> None:
    """提交返回 200 但没有 task_id 时给出明确异常."""
    c = _make_client(model="wan2.6-t2i")
    session = FakeSession(FakeResponse(json.dumps({"output": {}}), 200))
    _patch_session(c, session)
    with pytest.raises(RuntimeError, match="未返回任务 ID"):
        run(c.generate_image("x", "1280*1280"))


def test_poll_task_failed_status_raises() -> None:
    """任务态为 FAILED 时携带 code/message 快速失败."""
    c = _make_client(model="wan2.6-t2i")
    submit = json.dumps({"output": {"task_id": "t"}})
    failed = json.dumps(
        {"output": {"task_status": "FAILED", "code": "Bad", "message": "nope"}}
    )
    session = FakeSession([FakeResponse(submit, 200), FakeResponse(failed, 200)])
    _patch_session(c, session)
    with pytest.raises(RuntimeError, match="任务异常终止"):
        run(c.generate_image("x", "1280*1280"))


def test_poll_task_canceled_status_raises() -> None:
    """CANCELED 与 CANCELLED 两种拼写都判为终止."""
    c = _make_client(model="wan2.6-t2i")
    submit = json.dumps({"output": {"task_id": "t"}})
    canceled = json.dumps({"output": {"task_status": "CANCELED"}})
    session = FakeSession([FakeResponse(submit, 200), FakeResponse(canceled, 200)])
    _patch_session(c, session)
    with pytest.raises(RuntimeError, match="任务异常终止"):
        run(c.generate_image("x", "1280*1280"))


def test_poll_task_timeout_raises(monkeypatch) -> None:
    """累计轮询超过超时阈值时给出超时异常."""
    c = _make_client(model="wan2.6-t2i")
    submit = json.dumps({"output": {"task_id": "t-slow"}})
    running = json.dumps({"output": {"task_status": "RUNNING"}})
    session = FakeSession([FakeResponse(submit, 200), FakeResponse(running, 200)])
    _patch_session(c, session)

    # 压缩时间：轮询超时设为 0，使 while 不进循环
    monkeypatch.setattr(ac, "QIANWEN_POLL_TIMEOUT", 0)
    with pytest.raises(RuntimeError, match="超时"):
        run(c.generate_image("x", "1280*1280"))


def test_get_models_returns_registered_specs() -> None:
    """模型列表来自本地能力表，字段口径与契约一致."""
    c = _make_client()
    models = run(c.get_models())
    ids = [m["id"] for m in models]
    assert "z-image-turbo" in ids
    assert all(set(m) == {"id", "created", "owned_by"} for m in models)
    assert all(m["owned_by"] == "qianwen" for m in models)


def test_edit_image_not_supported() -> None:
    """千问云不支持图片编辑时给出可操作的中文提示."""
    c = _make_client()
    with pytest.raises(RuntimeError, match="暂不支持图片编辑"):
        run(c.edit_image(prompt="x"))


def test_maybe_cleanup_triggers_every_interval(monkeypatch) -> None:
    """每 CLEANUP_INTERVAL 次生成触发一次清理，并回收任务引用."""
    c = _make_client()
    calls: list[int] = []

    async def _cleanup():
        calls.append(1)

    c.image_manager.cleanup_old_images = _cleanup  # type: ignore[assignment]
    monkeypatch.setattr(ac, "CLEANUP_INTERVAL", 2)

    async def _drive():
        await c._maybe_cleanup()
        await c._maybe_cleanup()  # 第 2 次触发
        await asyncio.sleep(0)  # 让 background task 跑完
        await asyncio.sleep(0)

    run(_drive())
    assert len(calls) == 1
    assert c._generation_count == 0


def test_close_releases_client_manager() -> None:
    """close 应转发到 ClientManager.close."""
    c = _make_client()
    closed: list[bool] = []

    async def _close():
        closed.append(True)

    c.client_manager.close = _close  # type: ignore[assignment]
    run(c.close())
    assert closed == [True]
