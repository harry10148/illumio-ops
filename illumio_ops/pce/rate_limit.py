"""Outbound PCE request budget (token bucket), ported from 5.x src/pce_cache/rate_limiter.py.

This limits what this process sends to the PCE. Inbound GUI rate limiting is
flask-limiter's job; the two are unrelated.
"""
from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, rate_per_minute: int = 400, burst: int | None = None) -> None:
        if rate_per_minute < 1:
            raise ValueError("rate_per_minute must be >= 1")
        self._rate_per_minute = rate_per_minute
        self._rate_per_sec = rate_per_minute / 60.0
        self._capacity = burst if burst is not None else max(rate_per_minute // 6, 1)
        self._tokens = float(self._capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    @property
    def rate_per_minute(self) -> int:
        return self._rate_per_minute

    @property
    def capacity(self) -> int:
        return self._capacity

    def set_rate(self, rate_per_minute: int) -> None:
        """Change the rate in place (burst returns to the default formula)."""
        if rate_per_minute < 1:
            raise ValueError("rate_per_minute must be >= 1")
        with self._lock:
            self._refill_locked()  # settle at the old rate first
            self._rate_per_minute = rate_per_minute
            self._rate_per_sec = rate_per_minute / 60.0
            self._capacity = max(rate_per_minute // 6, 1)
            self._tokens = min(self._tokens, float(self._capacity))

    def acquire(self, timeout: float = 0.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                wait = (1.0 - self._tokens) / self._rate_per_sec
            remaining = deadline - time.monotonic()
            if timeout <= 0.0 or remaining <= 0:
                return False
            time.sleep(min(wait, remaining))

    def _refill_locked(self) -> None:
        now = time.monotonic()
        self._tokens = min(self._capacity, self._tokens + (now - self._last_refill) * self._rate_per_sec)
        self._last_refill = now
