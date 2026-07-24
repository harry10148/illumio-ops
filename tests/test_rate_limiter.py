import threading
import time

import pytest


def test_rate_limiter_refills_at_configured_rate():
    from src.pce_cache.rate_limiter import GlobalRateLimiter, reset_for_tests
    reset_for_tests()
    rl = GlobalRateLimiter(rate_per_minute=60)  # 1/sec
    t0 = time.monotonic()
    for _ in range(3):
        assert rl.acquire(timeout=2.0) is True
    elapsed = time.monotonic() - t0
    assert elapsed < 3.5


def test_rate_limiter_times_out_when_empty():
    from src.pce_cache.rate_limiter import GlobalRateLimiter, reset_for_tests
    reset_for_tests()
    rl = GlobalRateLimiter(rate_per_minute=6, burst=1)  # 1/10s, 1 token burst
    assert rl.acquire(timeout=0.1) is True   # consume the one token
    assert rl.acquire(timeout=0.1) is False  # next one should time out


def test_rate_limiter_is_thread_safe_under_contention():
    from src.pce_cache.rate_limiter import GlobalRateLimiter, reset_for_tests
    reset_for_tests()
    rl = GlobalRateLimiter(rate_per_minute=600, burst=10)  # 10/s
    granted = []
    lock = threading.Lock()

    def worker():
        if rl.acquire(timeout=1.0):
            with lock:
                granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert 10 <= len(granted) <= 25


def test_get_rate_limiter_applies_changed_rate_in_place():
    """設定變更（api_client 每次帶當前 rate_limit_per_minute 進來）必須就地
    生效，不能凍結在首次呼叫的值直到 process 重啟。"""
    from src.pce_cache.rate_limiter import get_rate_limiter, reset_for_tests
    reset_for_tests()
    rl = get_rate_limiter(rate_per_minute=400)
    assert rl._rate_per_minute == 400
    rl2 = get_rate_limiter(rate_per_minute=100)
    assert rl2 is rl                      # 仍是同一個 singleton
    assert rl._rate_per_minute == 100     # 但速率已更新
    assert rl._rate_per_sec == pytest.approx(100 / 60.0)
    assert rl._capacity == max(100 // 6, 1)
    assert rl._tokens <= rl._capacity     # 舊桶內多餘 token 被夾回新容量
    reset_for_tests()
