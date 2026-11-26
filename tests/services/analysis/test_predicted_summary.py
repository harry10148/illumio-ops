"""predicted_summary: the draft recompute counted by destination app and blocking rule, without keeping every row
(P5b-2 Task 5: the readiness report)."""
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.services.analysis import predicted_block
from illumio_ops.services.analysis.predicted_block import predicted_summary
from tests.services.analysis.test_predicted_block import SPEC, TEDT_DENY, fake  # noqa: F401  (fixture)
from tests.services.collect.conftest import configured_ctx


def test_predicted_grouped_by_rule(tmp_path, fake):  # noqa: F811
    s = predicted_summary(configured_ctx(tmp_path), SPEC)
    by_rule = {}
    for g in s.groups:
        by_rule[g.rule_href] = by_rule.get(g.rule_href, 0) + g.flows
    # 8 flows are blocked; 3 of them go into managed hosts (what enforcement blocks; the others go to addresses)
    assert by_rule == {TEDT_DENY: 3} and s.blocked_flows == 3 and s.rules[TEDT_DENY].ruleset_name == "tedt"
    assert s.unsupported is False and s.capped is False


def test_predicted_summary_unsupported(tmp_path, fake, monkeypatch):  # noqa: F811
    def no_draft(client, payload, *, deadline, compute_draft=False, delete_after=True):
        raise PceQueryError("update_rules", 404)
    monkeypatch.setattr(predicted_block, "run_traffic_query", no_draft)
    s = predicted_summary(configured_ctx(tmp_path), SPEC)
    assert s.unsupported is True and s.groups == []


# ── a period past the row limit is read in pieces (6.16.0) ───────────────────

def _flow(i, first, last, *, decision="blocked_by_boundary", conns=1, direction="inbound"):
    from tests.services.collect.conftest import raw_flow
    raw = raw_flow(i, first, last)
    raw["flow_direction"] = direction
    raw["num_connections"] = conns
    raw["draft_policy_decision"] = decision
    raw["enforcement_boundaries"] = [{"href": TEDT_DENY}] if decision.startswith("blocked") else []
    raw["rules"], raw["override_deny_rules"] = [], []
    return raw


def _pieces(monkeypatch, answer):
    """run_traffic_query answering by the window asked: `answer(start, end) -> (rows, capped)`."""
    from datetime import datetime

    from illumio_ops.pce.async_query import AsyncQueryResult
    asked = []

    def query(client, payload, *, deadline, compute_draft=False, delete_after=True):
        a = datetime.fromisoformat(payload["start_date"])
        b = datetime.fromisoformat(payload["end_date"])
        asked.append((a, b))
        rows, capped = answer(a, b)
        return AsyncQueryResult(rows=list(rows), matches_count=len(rows), flows_count=len(rows), capped=capped)
    monkeypatch.setattr(predicted_block, "run_traffic_query", query)
    return asked


def test_a_capped_period_is_read_a_utc_day_at_a_time_and_added(tmp_path, fake, monkeypatch):  # noqa: F811
    from datetime import UTC, datetime, timedelta

    from illumio_ops.domain.filter import FilterSpec
    d1, d2, d3, d4 = (datetime(2026, 10, d, tzinfo=UTC) for d in (20, 21, 22, 23))
    spec = FilterSpec(start=d1, end=d4)
    hour = timedelta(hours=1)
    days = {d1: [_flow(1, d1 + hour, d1 + 2 * hour, conns=3)],
            # seen first on the 20th and still open on the 21st: the PCE gives it back for both days
            d2: [_flow(1, d1 + hour, d2 + hour, conns=3), _flow(2, d2 + hour, d2 + 2 * hour, conns=5)],
            d3: [_flow(3, d3 + hour, d3 + 2 * hour, conns=7), _flow(4, d3 + hour, d3 + 2 * hour, decision="unknown")]}

    def answer(a, b):
        if b - a > timedelta(days=1):
            return days[d1], True  # the whole period: the PCE stops at the limit with a part of it
        return days[a], False
    asked = _pieces(monkeypatch, answer)
    s = predicted_summary(configured_ctx(tmp_path), spec, max_results=50_000)
    assert [a for a, _ in asked] == [d1, d1, d2, d3]  # the whole period, then its three UTC days
    assert all(b < a + timedelta(days=1) for a, b in asked[1:])  # none touches the next day's midnight
    assert (s.blocked_flows, s.blocked_connections, s.undetermined_flows) == (3, 15, 1)  # flow 1 once: 3 + 5 + 7
    assert (s.capped, s.queries, s.truncated) == (False, 4, [])
    assert s.rules[TEDT_DENY].ruleset_name == "tedt"


def test_a_day_at_the_limit_is_halved_and_what_still_caps_is_named(tmp_path, fake, monkeypatch):  # noqa: F811
    from datetime import UTC, datetime, timedelta

    from illumio_ops.domain.filter import FilterSpec
    d1 = datetime(2026, 10, 20, tzinfo=UTC)
    spec = FilterSpec(start=d1, end=d1 + timedelta(days=1))
    row = _flow(1, d1 + timedelta(minutes=5), d1 + timedelta(minutes=6), conns=2)

    def answer(a, b):
        first_piece = a == d1  # the busy start of the day never fits
        return ([row] if first_piece else []), first_piece
    asked = _pieces(monkeypatch, answer)
    s = predicted_summary(configured_ctx(tmp_path), spec, max_results=50_000)
    assert s.capped is True and s.truncated == [(d1, d1 + timedelta(hours=3))]  # a day halved three times
    assert s.queries == len(asked) == 8 and s.blocked_connections == 2  # 1 whole + 1 day + 2 + 2 + 2
