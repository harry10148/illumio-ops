"""Windowed /events reads. At its row cap the PCE returns only the NEWEST rows of the window,
so a capped page means the caller must split the window (5.x lost events this way)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from illumio_ops.domain.values import DeploymentType
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.client import PceClient, PceTransportError
from illumio_ops.pce.timefmt import pce_time
from illumio_ops.settings.schema import PceSettings

EVENTS_PAGE_LIMIT = 10000
_RETRY_WAIT = 2.0
_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_sleep = time.sleep


@dataclass(frozen=True)
class EventsPage:
    items: list[dict[str, Any]]
    capped: bool


def events_timeout(cfg: PceSettings) -> float:
    """Per-attempt timeout: the configured value, else SaaS 180 s / on-prem 30 s (SaaS /events
    has a fixed 22-60 s+ latency)."""
    if cfg.events_timeout_seconds is not None:
        return float(cfg.events_timeout_seconds)
    return 180.0 if cfg.deployment_type is DeploymentType.SAAS else 30.0


def fetch_events(client: PceClient, *, start: datetime, end: datetime, timeout: float, deadline: float,
                 max_results: int = EVENTS_PAGE_LIMIT) -> EventsPage:
    query = urlencode({"timestamp[gte]": pce_time(start), "timestamp[lte]": pce_time(end),
                       "max_results": str(max_results)})
    last_status: int | None = None
    while True:
        if deadline - time.monotonic() <= 0:
            raise PceQueryError("timeout", last_status)
        try:
            resp = client.request("GET", f"/events?{query}", timeout=timeout, bounded=True, deadline=deadline)
        except PceTransportError as exc:
            if exc.kind != "timeout":
                raise
            last_status = None
        else:
            if resp.status == 200:
                items = resp.json()
                if not isinstance(items, list):
                    raise PceQueryError("failed", 200, "response is not a list")
                return EventsPage(items=items, capped=len(items) >= max_results)
            if resp.status not in _RETRYABLE:
                raise PceQueryError("failed", resp.status)
            last_status = resp.status
        _sleep(min(_RETRY_WAIT, max(deadline - time.monotonic(), 0.0)))
