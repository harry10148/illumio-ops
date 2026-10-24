"""Collection GETs (workloads, labels, ...): one page of at most 500 rows, then the async path.

Truncation is judged only by "exactly 500 rows came back": with a query filter the PCE's
X-Total-Count is the unfiltered total (5.x, measured on a real PCE), so it cannot tell.
Above 500 the PCE's asynchronous collection GET is used (Prefer: respond-async → 202 + Location
→ job → result.href). If that path fails the caller gets PceCollectionIncomplete, never the
first 500 rows dressed up as the whole set.
"""
from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from loguru import logger

from illumio_ops.pce.client import (
    PceBudgetExhausted,
    PceClient,
    PceResponse,
    PceTransportError,
)

PAGE_LIMIT = 500
_JOB_FAILED = frozenset({"failed", "cancel_requested", "cancelled", "canceled"})
_sleep = time.sleep


class PceCollectionIncomplete(Exception):
    def __init__(self, path: str, partial_count: int, reason: str) -> None:
        self.path = path
        self.partial_count = partial_count
        self.reason = reason
        super().__init__(f"{path}: only {partial_count} rows could be read ({reason})")


def _job_wait(raw: str | None) -> float:
    try:
        wait = float(raw) if raw is not None else 2.0
    except ValueError:
        wait = 2.0
    if not math.isfinite(wait):
        wait = 2.0
    return min(max(wait, 2.0), 10.0)


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def get_all(client: PceClient, path: str, *, params: Mapping[str, str], deadline: float) -> list[dict[str, Any]]:
    first = client.request("GET", f"{path}?{urlencode({**params, 'max_results': str(PAGE_LIMIT)})}",
                           timeout=60, deadline=deadline)
    if first.status != 200:
        raise PceCollectionIncomplete(path, 0, f"HTTP {first.status}")
    rows = first.json()
    if not isinstance(rows, list):
        raise PceCollectionIncomplete(path, 0, "response is not a list")
    if len(rows) < PAGE_LIMIT:
        return rows
    # The async request must not carry the page limit: the PCE applies max_results to the
    # result file too (LAB-PCE 26.2.20: 500 rows back while 124,255 matched).
    target = f"{path}?{urlencode(params)}" if params else path
    return _async_collection(client, path, target, len(rows), deadline)


def _async_collection(client: PceClient, path: str, target: str, partial: int, deadline: float) -> list[dict[str, Any]]:
    try:
        return _run_async_collection(client, path, target, partial, deadline)
    except PceTransportError as exc:
        raise PceCollectionIncomplete(path, partial, f"async collection interrupted ({exc.kind})") from None
    except PceBudgetExhausted:
        raise PceCollectionIncomplete(path, partial, "async collection ran out of rate budget") from None


def _run_async_collection(client: PceClient, path: str, target: str, partial: int,
                          deadline: float) -> list[dict[str, Any]]:
    started: PceResponse = client.request("GET", target, timeout=60, deadline=deadline,
                                          headers={"Prefer": "respond-async"})
    job = started.headers.get("Location") or started.headers.get("location")
    if started.status != 202 or not job:
        raise PceCollectionIncomplete(path, partial, f"async collection not accepted (HTTP {started.status})")
    while True:
        if _remaining(deadline) <= 0:
            raise PceCollectionIncomplete(path, partial, "async collection did not finish in time")
        resp = client.request("GET", job, org_scoped=False, timeout=30, deadline=deadline)
        body = resp.json() if resp.status == 200 and resp.body else {}
        status = str(body.get("status", "")).lower() if isinstance(body, dict) else ""
        if status == "done":
            result = body.get("result") if isinstance(body, dict) else None
            href = result.get("href") if isinstance(result, dict) else None
            if not href:
                raise PceCollectionIncomplete(path, partial, "async collection finished without a result")
            data = client.request("GET", href, org_scoped=False, timeout=120, deadline=deadline)
            rows = data.json() if data.status == 200 else None
            if not isinstance(rows, list):
                raise PceCollectionIncomplete(path, partial, f"async result unreadable (HTTP {data.status})")
            logger.info("collection {} read {} rows through the async path", path, len(rows))
            return rows
        if status in _JOB_FAILED:
            raise PceCollectionIncomplete(path, partial, f"async collection {status}")
        _sleep(min(_job_wait(resp.headers.get("Retry-After")), max(_remaining(deadline), 0.0)))
