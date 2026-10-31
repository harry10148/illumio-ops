import threading
import time

import pytest

from illumio_ops.pce.rate_limit import RateLimiter


def test_defaults_match_5x():
    rl = RateLimiter()
    assert rl.rate_per_minute == 400 and rl.capacity == 400 // 6


def test_invalid_rate_rejected():
    with pytest.raises(ValueError):
        RateLimiter(rate_per_minute=0)


def test_refills_at_configured_rate():
    rl = RateLimiter(rate_per_minute=60)  # 1/sec, burst 10
    t0 = time.monotonic()
    for _ in range(3):
        assert rl.acquire(timeout=2.0) is True
    assert time.monotonic() - t0 < 3.5


def test_times_out_when_empty():
    rl = RateLimiter(rate_per_minute=6, burst=1)
    assert rl.acquire(timeout=0.1) is True
    assert rl.acquire(timeout=0.1) is False


def test_thread_safe_under_contention():
    rl = RateLimiter(rate_per_minute=600, burst=10)
    granted = []
    lock = threading.Lock()

    def worker():
        if rl.acquire(timeout=1.0):
            with lock:
                granted.append(1)

    ts = [threading.Thread(target=worker) for _ in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert 10 <= len(granted) <= 25


def test_set_rate_applies_in_place():
    rl = RateLimiter(rate_per_minute=400)
    rl.set_rate(100)
    assert rl.rate_per_minute == 100 and rl.capacity == 100 // 6
    with pytest.raises(ValueError):
        rl.set_rate(0)
