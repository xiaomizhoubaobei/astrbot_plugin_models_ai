"""防抖与并发控制单元测试.

覆盖 ``core/rate_limiter.py``：防抖窗口、并发互斥集合，以及过期记录清理。
防抖误判会直接表现为「用户点一下就提示太快」，因此窗口边界要钉死。
"""

from _plugin_harness import ensure_host  # noqa: E402

ensure_host()

from astrbot_plugin_models_ai.core import rate_limiter as rl  # noqa: E402
from astrbot_plugin_models_ai.core.rate_limiter import RateLimiter  # noqa: E402


def test_first_request_passes() -> None:
    """首次请求不被拦截."""
    limiter = RateLimiter()
    assert limiter.check_debounce("u1") is False


def test_second_request_within_window_blocked() -> None:
    """窗口内第二次请求被防抖拦截."""
    limiter = RateLimiter()
    assert limiter.check_debounce("u1") is False
    assert limiter.check_debounce("u1") is True


def test_different_users_are_independent() -> None:
    """防抖按 request_id 隔离，不互相影响."""
    limiter = RateLimiter()
    assert limiter.check_debounce("u1") is False
    assert limiter.check_debounce("u2") is False


def test_request_after_window_passes(monkeypatch) -> None:
    """超过防抖窗口后应放行."""
    limiter = RateLimiter()
    limiter.check_debounce("u1")
    # 让已记录的最近操作时间早于窗口
    limiter.last_operations["u1"] -= rl.DEBOUNCE_SECONDS + 1
    assert limiter.check_debounce("u1") is False


def test_cleanup_expired_operations(monkeypatch) -> None:
    """过期记录应被清理，防止内存泄漏."""
    limiter = RateLimiter()
    limiter.last_operations["old"] = 0.0  # 极早时间戳
    limiter.last_operations["fresh"] = 1e12  # 未来时间戳
    limiter._cleanup_expired_operations()
    assert "old" not in limiter.last_operations
    assert "fresh" in limiter.last_operations


def test_debounce_triggers_cleanup_when_large(monkeypatch) -> None:
    """记录数超过阈值时自动触发一次清理."""
    limiter = RateLimiter()
    for i in range(150):
        limiter.last_operations[f"k{i}"] = 0.0
    # 触发 check_debounce 里的清理分支
    limiter.check_debounce("new-user")
    # 旧的过期记录被清掉，只剩新写入的
    assert len(limiter.last_operations) < 150


def test_processing_set_lifecycle() -> None:
    """处理中集合的增删查语义."""
    limiter = RateLimiter()
    assert limiter.is_processing("u1") is False
    limiter.add_processing("u1")
    assert limiter.is_processing("u1") is True
    limiter.remove_processing("u1")
    assert limiter.is_processing("u1") is False


def test_remove_processing_is_idempotent() -> None:
    """重复移除不应抛异常（discard 语义）."""
    limiter = RateLimiter()
    limiter.remove_processing("never-added")


def test_debug_log_runs_without_error() -> None:
    """开启 debug 时日志分支不应报错."""
    limiter = RateLimiter(debug_mode=True)
    limiter.debug_log("hello")
    limiter.check_debounce("u1")
