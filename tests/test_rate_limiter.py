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
