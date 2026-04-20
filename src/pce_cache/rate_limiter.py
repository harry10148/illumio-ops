from __future__ import annotations

import threading
import time


class GlobalRateLimiter:
    def __init__(self, rate_per_minute: int = 400, burst: int | None = None):
        if rate_per_minute < 1:
            raise ValueError("rate_per_minute must be >= 1")
        self._rate_per_sec = rate_per_minute / 60.0
        self._capacity = burst if burst is not None else max(rate_per_minute // 6, 1)
        self._tokens = float(self._capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 0.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                deficit = 1.0 - self._tokens
                wait = deficit / self._rate_per_sec
            if timeout <= 0.0:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(wait, remaining))

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_sec)
        self._last_refill = now


_INSTANCE: GlobalRateLimiter | None = None
_INSTANCE_LOCK = threading.Lock()


def get_rate_limiter(rate_per_minute: int = 400) -> GlobalRateLimiter:
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = GlobalRateLimiter(rate_per_minute=rate_per_minute)
        return _INSTANCE


def reset_for_tests() -> None:
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None
