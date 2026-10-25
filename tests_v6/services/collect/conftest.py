"""Collector test helpers: a context with a configured PCE, and fake PCE answers per window."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from illumio_ops.pce.async_query import AsyncQueryResult
from tests_v6.web.conftest import make_ctx

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
PCE = {"url": "https://pce.example.com:8443", "org_id": "1", "api_key": "k", "api_secret": "s"}


def configured_ctx(tmp_path, **collection):
    ctx = make_ctx(tmp_path)
    def mutate(d):
        d["pce"].update(PCE)
        d["collection"].update(collection)
    ctx.settings.update(ctx.settings.current().revision, mutate)
    return ctx


def raw_flow(i: int, first: datetime, last: datetime, *, direction: str = "outbound", port: int = 445,
             user: str | None = None) -> dict[str, Any]:
    return {
        "src": {"ip": f"10.0.1.{i % 250}", "workload": {"href": f"/orgs/1/workloads/src-{i}", "hostname": f"s{i}",
                                                        "managed": True, "enforcement_mode": "visibility_only",
                                                        "labels": [{"key": "env", "value": "Dev"}]}},
        "dst": {"ip": "10.0.2.1", "workload": {"href": "/orgs/1/workloads/dst", "hostname": "db",
                                                "managed": True, "enforcement_mode": "selective", "labels": []}},
        "service": {"port": port, "proto": 6, "user_name": user},
        "policy_decision": "potentially_blocked",
        "flow_direction": direction,
        "timestamp_range": {"first_detected": first.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "last_detected": last.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "num_connections": 1,
    }


class FakeTraffic:
    """Stands in for run_traffic_query; answers per (start, end) window."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.answer = lambda start, end, max_results: []   # -> list of rows, or raise

    def __call__(self, client, payload, *, deadline, compute_draft=False, delete_after=True):
        start = datetime.fromisoformat(payload["start_date"])
        end = datetime.fromisoformat(payload["end_date"])
        self.calls.append((payload["start_date"], payload["end_date"]))
        rows = self.answer(start, end, payload["max_results"])
        return AsyncQueryResult(rows=rows, matches_count=len(rows), flows_count=len(rows),
                                capped=len(rows) >= payload["max_results"])


@pytest.fixture
def fake_traffic(monkeypatch):
    from illumio_ops.services.collect import traffic
    fake = FakeTraffic()
    monkeypatch.setattr(traffic, "run_traffic_query", fake)
    return fake


def minutes(n: int) -> timedelta:
    return timedelta(minutes=n)
