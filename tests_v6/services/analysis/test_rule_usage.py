"""Rule usage (P5c-1, user 2026-10-29: plan A): which draft rules the period's traffic used, from the PCE's own
draft recompute (async query + update_rules), a day at a time."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.pce.async_query import AsyncQueryResult, PceQueryError
from illumio_ops.pce.policy import PendingItem, PolicyNames, parse_pending
from illumio_ops.services.analysis import rule_usage
from tests_v6.services.collect.conftest import configured_ctx, raw_flow

NOW = datetime(2026, 10, 28, 1, tzinfo=UTC)
START, END = datetime(2026, 10, 25, tzinfo=UTC), datetime(2026, 10, 28, tzinfo=UTC)
ALLOW = "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/10"
IDLE = "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/11"
DENY = "/orgs/1/sec_policy/draft/rule_sets/2/deny_rules/20"
RULE_SETS = [
    {"href": "/orgs/1/sec_policy/draft/rule_sets/1", "name": "Web", "rules": [
        {"href": ALLOW, "enabled": True, "consumers": [], "providers": [], "ingress_services": []},
        {"href": IDLE, "enabled": True, "consumers": [], "providers": [], "ingress_services": []}],
     "deny_rules": []},
    {"href": "/orgs/1/sec_policy/draft/rule_sets/2", "name": "Guard", "rules": [],
     "deny_rules": [{"href": DENY, "enabled": True, "consumers": [], "providers": [], "ingress_services": []}]},
]


def row(i, day, *, decision="allowed", allow=(), deny=(), conns=1, direction="outbound", src_app="Web",
        dst_app="DB", port=443):
    first = datetime(2026, 10, day, 3, tzinfo=UTC) + timedelta(seconds=i)
    r = raw_flow(i, first, first + timedelta(minutes=5), direction=direction, port=port)
    r["src"]["workload"]["labels"] = [{"key": "app", "value": src_app}]
    r["dst"]["workload"]["labels"] = [{"key": "app", "value": dst_app}]
    r["num_connections"] = conns
    r["draft_policy_decision"] = decision
    r["rules"] = [{"href": h} for h in allow]
    r["enforcement_boundaries"] = [{"href": h} for h in deny]
    return r


class FakePce:
    def __init__(self, rows):
        self.rows, self.payloads, self.fail = rows, [], None

    def __call__(self, client, payload, *, deadline, compute_draft=False, delete_after=True):
        assert compute_draft
        self.payloads.append(payload)
        if self.fail:
            raise self.fail
        a, b = datetime.fromisoformat(payload["start_date"]), datetime.fromisoformat(payload["end_date"])
        rows = [dict(r) for r in self.rows
                if a <= datetime.fromisoformat(r["timestamp_range"]["first_detected"]) < b]
        return AsyncQueryResult(rows=rows, matches_count=len(rows), flows_count=len(rows),
                                capped=len(rows) >= payload["max_results"])


@pytest.fixture
def pce(monkeypatch):
    fake = FakePce([row(1, 25, allow=[ALLOW], conns=3), row(2, 26, allow=[ALLOW], conns=4),
                    row(3, 26, decision="blocked_by_boundary", deny=[DENY], conns=2),
                    row(4, 27, decision="potentially_blocked", conns=5, src_app="Batch", port=1433)])
    monkeypatch.setattr(rule_usage, "run_traffic_query", fake)
    monkeypatch.setattr(rule_usage, "fetch_rule_sets", lambda client, pversion, *, deadline: RULE_SETS)
    monkeypatch.setattr(rule_usage, "fetch_policy_names",
                        lambda client, pversion, *, deadline: PolicyNames(labels={}, names={}))
    monkeypatch.setattr(rule_usage, "fetch_pending", lambda client, *, deadline: [])
    return fake


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_hits_counted_per_rule(ctx, pce):
    u = rule_usage.rule_usage(ctx, start=START, end=END, now=NOW)
    assert (u.hits[ALLOW].flows, u.hits[ALLOW].connections) == (2, 7)
    assert u.hits[ALLOW].top_pairs == [("Web", "DB", 7)]
    assert IDLE not in u.hits and set(u.rules) == {ALLOW, IDLE, DENY}


def test_pair_counted_once(ctx, pce):
    """Both VENs reported the same connection: one connection, both ends' rules."""
    a = row(9, 25, allow=[ALLOW], conns=6, direction="outbound")
    b = row(9, 25, allow=[ALLOW], conns=6, direction="inbound")
    pce.rows = [a, b]
    u = rule_usage.rule_usage(ctx, start=START, end=END, now=NOW)
    assert (u.hits[ALLOW].flows, u.hits[ALLOW].connections) == (1, 6)


def test_deny_rule_hits(ctx, pce):
    u = rule_usage.rule_usage(ctx, start=START, end=END, now=NOW)
    assert (u.hits[DENY].flows, u.hits[DENY].connections) == (1, 2)


def test_no_rule_groups(ctx, pce):
    u = rule_usage.rule_usage(ctx, start=START, end=END, now=NOW)
    assert [(g.src_app, g.dst_app, g.port, g.connections) for g in u.no_rule] == [("Batch", "DB", 1433, 5)]


def test_windows_are_days(ctx, pce):
    rule_usage.rule_usage(ctx, start=START, end=END, now=NOW)
    assert [p["start_date"][:10] for p in pce.payloads] == ["2026-10-25", "2026-10-26", "2026-10-27"]
    assert all(p["max_results"] == rule_usage.PER_QUERY for p in pce.payloads)


def test_capped_window_halved_then_truncated(ctx, pce, monkeypatch):
    monkeypatch.setattr(rule_usage, "PER_QUERY", 1)
    pce.rows = [row(i, 25, allow=[ALLOW]) for i in range(4)]
    u = rule_usage.rule_usage(ctx, start=START, end=START + timedelta(days=1), now=NOW)
    # only the half holding the rows splits again: the day, then 00-12, 00-06, 03-06 (three splits), cut short
    assert u.truncated == [(datetime(2026, 10, 25, 3, tzinfo=UTC), datetime(2026, 10, 25, 6, tzinfo=UTC))]
    assert len(pce.payloads) == 1 + 2 + 2 + 2


def test_unsupported_when_update_rules_404(ctx, pce):
    pce.fail = PceQueryError("update_rules", 404)
    u = rule_usage.rule_usage(ctx, start=START, end=END, now=NOW)
    assert u.unsupported and u.hits == {}


def test_query_failure_raises(ctx, pce):
    pce.fail = PceQueryError("poll", 500)
    with pytest.raises(PceQueryError):
        rule_usage.rule_usage(ctx, start=START, end=END, now=NOW)


def test_pending_parsed():
    body = {"rule_sets": [{"href": "/orgs/1/sec_policy/draft/rule_sets/663", "name": "G_Deny",
                           "update_type": "create", "updated_at": "2026-08-04T02:19:25.504Z"}], "ip_lists": []}
    assert parse_pending(body) == [PendingItem(kind="rule_sets", href="/orgs/1/sec_policy/draft/rule_sets/663",
                                               name="G_Deny", update_type="create",
                                               updated_at="2026-08-04T02:19:25.504Z")]


def test_no_rule_total_counts_every_group(ctx, pce, monkeypatch):
    """Lab 2026-10-29: the KPI added up only the 50 groups shown."""
    monkeypatch.setattr(rule_usage, "NO_RULE_TOP", 1)
    pce.rows = [row(5, 25, decision="potentially_blocked", conns=5, port=1433),
                row(6, 25, decision="potentially_blocked", conns=2, port=22)]
    u = rule_usage.rule_usage(ctx, start=START, end=END, now=NOW)
    assert len(u.no_rule) == 1 and u.no_rule_connections == 7
