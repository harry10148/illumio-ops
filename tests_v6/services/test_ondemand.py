"""On-demand pulls (spec §6.4, 2026-10-29): a period read from the PCE into a throwaway flow store, a day at
a time, so a report can be built from it with the same SQL as from the local store."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.values import IngestSource, PolicyDecision
from illumio_ops.pce.async_query import AsyncQueryResult, PceQueryError
from illumio_ops.services import ondemand
from illumio_ops.services.coverage import store_coverage
from tests_v6.services.collect.conftest import configured_ctx, raw_flow

NOW = datetime(2026, 10, 28, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 25, tzinfo=UTC), datetime(2026, 10, 28, tzinfo=UTC)


class FakePce:
    """run_traffic_query stand-in: answer(start, end, max_results) -> rows; keeps every payload."""

    def __init__(self, answer):
        self.answer = answer
        self.payloads: list[dict] = []

    def __call__(self, client, payload, *, deadline, compute_draft=False, delete_after=True):
        self.payloads.append(payload)
        start = datetime.fromisoformat(payload["start_date"])
        end = datetime.fromisoformat(payload["end_date"])
        rows = self.answer(start, end, payload["max_results"])
        return AsyncQueryResult(rows=rows, matches_count=len(rows), flows_count=len(rows),
                                capped=len(rows) >= payload["max_results"])


def _hourly(start, end, max_results):
    """One record per hour of the window, each its own connection."""
    out, t, i = [], start, int(start.timestamp()) // 3600
    while t < end:
        out.append(raw_flow(i, t, t + timedelta(minutes=5)))
        t += timedelta(hours=1)
        i += 1
    return out


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path, mode="lightweight")


@pytest.fixture
def pce(monkeypatch):
    fake = FakePce(_hourly)
    monkeypatch.setattr(ondemand, "run_traffic_query", fake)
    return fake


def _leftovers(ctx):
    d = ondemand.ondemand_dir(ctx.paths)
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def _count(c):
    with c.flows().connect() as conn:
        return conn.execute("SELECT count(*) FROM flows").fetchone()[0]


def test_pull_writes_rows_into_temp_db(ctx, pce):
    with ondemand.pull_period(ctx, start=START, end=END, now=NOW) as res:
        assert res.rows == 72 and _count(res.ctx) == 72
        assert res.ctx.flows().path != ctx.flows().path
        with res.ctx.flows().connect() as conn:
            cov = store_coverage(conn, IngestSource.TRAFFIC, (START, END), floor=START, collected=True)
        assert cov.covers_any and not cov.gaps
    assert _count(ctx) == 0  # the install's own store is untouched


def test_one_query_when_the_period_fits(ctx, pce):
    """Lab, 2026-10-29: daily windows cost a 30-day baseline 30 queries on days the PCE kept nothing (16 minutes).
    The per-query cap already bounds memory, so a span is read whole and halved only when it caps."""
    with ondemand.pull_period(ctx, start=START, end=END, now=NOW) as res:
        assert res.rows == 72
    assert [(p["start_date"][:10], p["end_date"][:10]) for p in pce.payloads] == [("2026-10-25", "2026-10-28")]
    assert pce.payloads[0]["max_results"] == ondemand.PER_QUERY


def test_empty_span_costs_one_query(ctx, pce):
    pce.answer = lambda s, e, n: []
    with ondemand.pull_period(ctx, start=START - timedelta(days=30), end=END, now=NOW):
        pass
    assert len(pce.payloads) == 1


def test_capped_span_halved_until_it_fits(ctx, pce, monkeypatch):
    monkeypatch.setattr(ondemand, "PER_QUERY", 30)
    with ondemand.pull_period(ctx, start=START, end=END, now=NOW) as res:
        assert res.rows == 72 and not res.truncated
    assert len(pce.payloads) == 7  # 72 capped, 2 x 36 capped, 4 x 18


def test_capped_window_split_then_truncated(ctx, pce, monkeypatch):
    monkeypatch.setattr(ondemand, "PER_QUERY", 5)
    pce.answer = lambda s, e, n: [raw_flow(i, s, s + timedelta(seconds=1)) for i in range(n)]  # always full
    with ondemand.pull_period(ctx, start=START, end=START + timedelta(hours=1), now=NOW) as res:
        assert res.truncated and all(n == 5 for _, _, n in res.truncated)
        with res.ctx.flows().connect() as conn:
            cov = store_coverage(conn, IngestSource.TRAFFIC, (START, START + timedelta(hours=1)), floor=START,
                                 collected=True)
        assert any(g[2] == "truncated" for g in cov.gaps)
    assert len(pce.payloads) > 1  # halved before giving up


def test_total_cap_stops_and_says_so(ctx, pce, monkeypatch):
    monkeypatch.setattr(ondemand, "PER_QUERY", 30)
    monkeypatch.setattr(ondemand, "ONDEMAND_MAX_ROWS", 30)
    with ondemand.pull_period(ctx, start=START, end=END, now=NOW) as res:
        # the first half is read in two quarters (18 + 18 rows); the cap then stops the second half
        assert res.capped_total and res.rows == 36 and res.unread_from == START + timedelta(hours=36)
        with res.ctx.flows().connect() as conn:
            cov = store_coverage(conn, IngestSource.TRAFFIC, (START, END), floor=START, collected=True)
        assert any(g[0] == START + timedelta(hours=36) for g in cov.gaps)


def test_condition_sent_to_pce(ctx, pce):
    spec = FilterSpec(start=START, end=END, decisions=(PolicyDecision.BLOCKED,))
    with ondemand.pull_period(ctx, start=START, end=END, spec=spec, now=NOW):
        pass
    assert [p["policy_decisions"] for p in pce.payloads] == [["blocked"]]


def test_window_failure_fails_pull(ctx, pce):
    def answer(s, e, n):
        raise PceQueryError("poll", 500)
    pce.answer = answer
    with pytest.raises(ondemand.OnDemandFailed) as e, ondemand.pull_period(ctx, start=START, end=END, now=NOW):
        pass
    assert "2026-10-25" in str(e.value) and _leftovers(ctx) == []


def test_tmp_removed_on_success(ctx, pce):
    with ondemand.pull_period(ctx, start=START, end=END, now=NOW) as res:
        assert res.ctx.flows().path.exists()
    assert _leftovers(ctx) == []


def test_tmp_removed_on_error(ctx, pce):
    with pytest.raises(RuntimeError), ondemand.pull_period(ctx, start=START, end=END, now=NOW):
        raise RuntimeError("the report failed")
    assert _leftovers(ctx) == []


def test_caller_pce_error_is_not_a_pull_failure(ctx, pce):
    """A PCE error raised while the report is built (e.g. readiness's draft recompute) is the report's own."""
    with pytest.raises(PceQueryError), ondemand.pull_period(ctx, start=START, end=END, now=NOW):
        raise PceQueryError("update_rules", 404)


def test_startup_sweeps_leftovers(ctx):
    d = ondemand.ondemand_dir(ctx.paths)
    d.mkdir(parents=True)
    for name in ("a.sqlite", "a.sqlite-wal", "a.sqlite-shm"):
        (d / name).write_bytes(b"x")
    assert ondemand.sweep_leftovers(ctx.paths) == 3 and _leftovers(ctx) == []


def test_earliest_reported(ctx, pce):
    pce.answer = lambda s, e, n: _hourly(max(s, datetime(2026, 10, 26, tzinfo=UTC)), e, n)
    with ondemand.pull_period(ctx, start=START, end=END, now=NOW) as res:
        assert res.earliest == datetime(2026, 10, 26, tzinfo=UTC)


def test_install_store_of_another_pce_is_not_copied(ctx, pce):
    """The install's store still holds the previous PCE's data (a switch whose clearing has not run): its
    inventory must not reach a report about the new PCE."""
    from datetime import UTC, datetime

    from illumio_ops.services.collect.guard import BindingMismatch
    from illumio_ops.store.flowdb import binding
    with ctx.flows().connect() as conn:
        binding.bind(conn, "https://old.example.com:8443", "9", datetime(2026, 1, 1, tzinfo=UTC))
        conn.commit()
    with pytest.raises(BindingMismatch), ondemand.pull_period(ctx, start=START, end=END, now=NOW):
        pass
    assert _leftovers(ctx) == [] and pce.payloads == []
