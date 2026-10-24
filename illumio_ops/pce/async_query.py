"""The single async traffic-query lifecycle (5.x had two implementations and seven poll loops).

submit → poll → (optional) update_rules for draft policy decisions → download → delete.
Every failure raises PceQueryError naming the stage; an empty download while the PCE reported
matches is retried once and then treated as a failure, never as "no traffic".
"""
from __future__ import annotations

import gzip
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from loguru import logger

from illumio_ops.pce.client import PceClient
from illumio_ops.pce.timefmt import pce_time

Stage = Literal["submit", "poll", "failed", "timeout", "update_rules", "download"]
FAILED_STATES = frozenset({"failed", "killed", "cancel_requested", "cancelled", "canceled"})
_POLL_START, _POLL_FACTOR, _POLL_MAX = 2.0, 1.5, 10.0
_EMPTY_RETRY_WAIT = 3.0
_sleep = time.sleep


class PceQueryError(Exception):
    def __init__(self, stage: Stage, status: int | None = None, detail: str = "") -> None:
        self.stage: Stage = stage
        self.status = status
        super().__init__(f"traffic query {stage} failed" + (f" (HTTP {status})" if status else "")
                         + (f": {detail}" if detail else ""))


@dataclass(frozen=True)
class AsyncQueryResult:
    rows: list[dict[str, Any]]
    matches_count: int | None
    flows_count: int | None
    capped: bool


def traffic_payload(start: datetime, end: datetime, *, max_results: int, query_name: str,
                    sources: dict[str, Any] | None = None, destinations: dict[str, Any] | None = None,
                    services: dict[str, Any] | None = None,
                    policy_decisions: list[str] | None = None) -> dict[str, Any]:
    return {
        "query_name": query_name,
        "start_date": pce_time(start),
        "end_date": pce_time(end),
        "policy_decisions": list(policy_decisions or []),
        "max_results": max_results,
        "sources": sources or {"include": [[]], "exclude": []},
        "destinations": destinations or {"include": [[]], "exclude": []},
        "services": services or {"include": [], "exclude": []},
        "sources_destinations_query_op": "and",
    }


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _poll(client: PceClient, href: str, deadline: float, *, done: Any, stage: Stage) -> dict[str, Any]:
    wait = _POLL_START
    while True:
        if _remaining(deadline) <= 0:
            raise PceQueryError("timeout")
        resp = client.request("GET", href, org_scoped=False, timeout=30, deadline=deadline)
        if resp.status == 200:
            body = resp.json()
            status = str(body.get("status", "")).lower()
            if status in FAILED_STATES:
                raise PceQueryError("failed", detail=status)
            rules = body.get("rules")
            if stage == "update_rules" and isinstance(rules, str) and rules.lower() in FAILED_STATES:
                raise PceQueryError("update_rules", detail=rules)
            if done(body):
                return dict(body)
        elif resp.status not in (404, 410):  # not visible yet right after submit: keep waiting
            raise PceQueryError("poll", resp.status)
        _sleep(min(wait, max(_remaining(deadline), 0.0)))
        wait = min(wait * _POLL_FACTOR, _POLL_MAX)


def _parse_download(body: bytes) -> list[dict[str, Any]]:
    try:
        body = gzip.decompress(body)
    except OSError:
        pass  # served uncompressed
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line in (b"[", b"]"):
            continue
        if line.endswith(b","):
            line = line[:-1]
        item = json.loads(line)
        rows.extend(item if isinstance(item, list) else [item])
    return rows


def _download(client: PceClient, href: str, deadline: float) -> list[dict[str, Any]]:
    resp = client.request("GET", f"{href}/download", org_scoped=False, timeout=300, deadline=deadline)
    if resp.status != 200:
        raise PceQueryError("download", resp.status)
    try:
        return _parse_download(resp.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PceQueryError("download", detail=type(exc).__name__) from None


def run_traffic_query(client: PceClient, payload: Mapping[str, Any], *, deadline: float,
                      compute_draft: bool = False, delete_after: bool = True) -> AsyncQueryResult:
    resp = client.request("POST", "/traffic_flows/async_queries", json=dict(payload), timeout=60, deadline=deadline)
    if resp.status not in (200, 201, 202):
        raise PceQueryError("submit", resp.status)
    href = resp.json().get("href")
    if not href:
        raise PceQueryError("submit", resp.status, "no href in the response")
    status = _poll(client, href, deadline, stage="poll",
                   done=lambda b: str(b.get("status", "")).lower() == "completed")
    if compute_draft:
        put = client.request("PUT", f"{href}/update_rules", org_scoped=False, json={}, timeout=60, deadline=deadline)
        if put.status not in (200, 202, 204):
            raise PceQueryError("update_rules", put.status)
        status = _poll(client, href, deadline, stage="update_rules",
                       done=lambda b: str(b.get("status", "")).lower() == "completed"
                       and str(b.get("rules") or "completed").lower() == "completed")
    matches = status.get("matches_count")
    rows = _download(client, href, deadline)
    if not rows and isinstance(matches, int) and matches > 0:
        # The PCE sometimes reports completed before the result file exists (5.x, long-running service).
        _sleep(_EMPTY_RETRY_WAIT)
        rows = _download(client, href, deadline)
        if not rows:
            raise PceQueryError("download", detail=f"PCE reported {matches} matches but the result was empty")
    if delete_after:
        try:
            gone = client.request("DELETE", href, org_scoped=False, timeout=30)
            if gone.status not in (200, 202, 204):
                logger.warning("could not delete finished traffic query (HTTP {})", gone.status)
        except Exception as exc:  # noqa: BLE001 - cleanup only; the result is already in hand
            logger.warning("could not delete finished traffic query: {}", type(exc).__name__)
    flows = status.get("flows_count")
    return AsyncQueryResult(
        rows=rows,
        matches_count=matches if isinstance(matches, int) else None,
        flows_count=flows if isinstance(flows, int) else None,
        capped=len(rows) >= int(payload["max_results"]),
    )
