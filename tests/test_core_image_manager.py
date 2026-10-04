"""图片管理单元测试.

覆盖 ``core/image_manager.py``：下载落盘（含重试与扩展名判定）、
base64 保存、旧图片清理（数量上限与排序），以及保存路径唯一性。

图片目录通过 ``StarTools.get_data_dir`` 注入到临时目录，测试不污染真实数据目录。
"""

import base64
import os
import time

import pytest
from _plugin_harness import ensure_host, run  # noqa: E402

ensure_host()


class FakeResp:
    """最小 aiohttp 响应替身."""

    def __init__(
        self, body: bytes = b"img", status: int = 200, ctype: str = "image/png"
    ):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": ctype}

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """假 Session：按脚本吐响应."""

    def __init__(self, responses):
        self._responses = responses if isinstance(responses, list) else [responses]
        self._idx = 0

    def get(self, url, **kwargs):
        if self._idx < len(self._responses):
            r = self._responses[self._idx]
            self._idx += 1
        else:
            r = self._responses[-1]
        return r


@pytest.fixture
def image_manager(tmp_path, monkeypatch):
    """构造图片目录已指向 tmp 的 ImageManager."""
    from astrbot_plugin_models_ai.core import image_manager as im_mod
    from astrbot_plugin_models_ai.core.image_manager import ImageManager

    # 注入临时数据目录
    monkeypatch.setattr(
        im_mod.StarTools,
        "get_data_dir",
        staticmethod(lambda *_a, **_k: tmp_path),
    )
    mgr = ImageManager()
    return mgr


def test_get_extension_from_content_type(image_manager) -> None:
    """Content-Type 优先决定扩展名."""
    f = image_manager._get_extension_from_url_or_content_type
    assert f("http://x/a", "image/jpeg") == ".jpg"
    assert f("http://x/a", "image/png; charset=utf-8") == ".png"
    assert f("http://x/a", "image/webp") == ".webp"
    assert f("http://x/a", "image/gif") == ".gif"
    assert f("http://x/a", "image/bmp") == ".bmp"


def test_get_extension_from_url_fallback(image_manager) -> None:
    """无 Content-Type 时回落到 URL 后缀."""
    f = image_manager._get_extension_from_url_or_content_type
    assert f("http://x/a.png") == ".png"
    assert f("http://x/a.webp") == ".webp"
    assert f("http://x/a.gif") == ".gif"
    assert f("http://x/a.bmp") == ".bmp"
    assert f("http://x/a.jpg") == ".jpg"
    assert f("http://x/a.jpeg") == ".jpg"


def test_get_extension_default_jpg(image_manager) -> None:
    """无法判定时默认 .jpg."""
    f = image_manager._get_extension_from_url_or_content_type
    assert f("http://x/a") == ".jpg"
    # 无法识别的 Content-Type 也应回落
    assert f("http://x/a", "application/octet-stream") == ".jpg"


def test_save_path_is_unique(image_manager) -> None:
    """连续生成的保存路径不得相同（时间戳+随机串）."""
    paths = {image_manager.get_save_path(".jpg") for _ in range(20)}
    assert len(paths) == 20
    assert all(p.endswith(".jpg") for p in paths)


def test_download_image_success(image_manager) -> None:
    """下载成功应落盘并返回路径."""
    session = FakeSession(FakeResp(b"PNGDATA", 200, "image/png"))
    path = run(image_manager.download_image("http://x/a.png", session))
    assert os.path.exists(path)
    assert path.endswith(".png")
    with open(path, "rb") as f:
        assert f.read() == b"PNGDATA"


def test_download_image_non_200_raises(image_manager) -> None:
    """非 200 属确定性失败，快速抛出（不重试）."""
    session = FakeSession(FakeResp(b"", 404))
    with pytest.raises(RuntimeError, match="HTTP 404"):
        run(image_manager.download_image("http://x/a.png", session))


def test_download_image_retries_transient(image_manager, monkeypatch) -> None:
    """瞬时故障应重试并最终成功."""
    from astrbot_plugin_models_ai.core import image_manager as im_mod

    # 关掉真实退避等待
    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(im_mod.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    class FlakySession:
        def get(self, url, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionResetError("connection reset")
            return FakeResp(b"OK", 200, "image/png")

    path = run(image_manager.download_image("http://x/a.png", FlakySession()))
    assert calls["n"] == 2
    assert os.path.exists(path)


def test_save_base64_plain_data(image_manager) -> None:
    """无前缀的纯 base64 数据应能解码落盘（默认 .jpg）."""
    raw = base64.b64encode(b"hello-image").decode()
    path = run(image_manager.save_base64_image(raw))
    assert path.endswith(".jpg")
    with open(path, "rb") as f:
        assert f.read() == b"hello-image"


@pytest.mark.parametrize(
    "mime,ext",
    [
        ("image/png", ".png"),
        ("image/jpeg", ".jpg"),
        ("image/jpg", ".jpg"),
        ("image/webp", ".webp"),
        ("image/gif", ".gif"),
        ("image/bmp", ".bmp"),
    ],
)
def test_save_base64_data_uri_extension(image_manager, mime, ext) -> None:
    """data URI 前缀应决定扩展名."""
    payload = base64.b64encode(b"x").decode()
    uri = f"data:{mime};base64,{payload}"
    path = run(image_manager.save_base64_image(uri))
    assert path.endswith(ext)


def test_save_base64_unknown_mime_defaults_jpg(image_manager) -> None:
    """无法识别的 mime 回落 .jpg."""
    payload = base64.b64encode(b"x").decode()
    path = run(image_manager.save_base64_image(f"data:image/tiff;base64,{payload}"))
    assert path.endswith(".jpg")


def test_save_base64_invalid_raises(image_manager) -> None:
    """非法 base64 数据应抛异常."""
    with pytest.raises(Exception):
        run(image_manager.save_base64_image("!!!not-base64!!!"))


def test_cleanup_keeps_latest_n(image_manager) -> None:
    """清理应保留最新 MAX_CACHED_IMAGES 张，删除最旧的."""
    from astrbot_plugin_models_ai.core import image_manager as im_mod

    image_dir = image_manager._get_image_dir()
    # 造 25 个文件，mtime 依次递增
    base = time.time()
    for i in range(25):
        p = image_dir / f"img_{i:02d}.jpg"
        p.write_bytes(b"x")
        os.utime(p, (base + i, base + i))

    image_manager._sync_cleanup_old_images()

    remaining = sorted(f.name for f in image_dir.iterdir() if f.is_file())
    assert len(remaining) == im_mod.MAX_CACHED_IMAGES
    # 最旧的应被删掉，最新的应保留
    assert "img_00.jpg" not in remaining
    assert "img_24.jpg" in remaining


def test_cleanup_noop_when_under_limit(image_manager) -> None:
    """未超过上限时不删除任何文件."""
    image_dir = image_manager._get_image_dir()
    for i in range(3):
        (image_dir / f"k_{i}.jpg").write_bytes(b"x")
    image_manager._sync_cleanup_old_images()
    assert len(list(image_dir.iterdir())) == 3


def test_cleanup_ignores_non_image_files(image_manager) -> None:
    """非图片扩展名不参与计数与删除."""
    image_dir = image_manager._get_image_dir()
    (image_dir / "notes.txt").write_text("keep me")
    image_manager._sync_cleanup_old_images()
    assert (image_dir / "notes.txt").exists()


def test_async_cleanup_runs(image_manager) -> None:
    """异步清理应能正常跑完（线程池执行）."""
    image_dir = image_manager._get_image_dir()
    (image_dir / "a.jpg").write_bytes(b"x")
    run(image_manager.cleanup_old_images())
    assert (image_dir / "a.jpg").exists()


def test_debug_log_branch(image_manager) -> None:
    """debug 模式日志分支可执行."""
    image_manager.debug_mode = True
    image_manager.debug_log("hi")
    image_manager._log_retry(1, 1.0, RuntimeError("boom"))
