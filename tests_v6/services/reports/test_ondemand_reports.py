"""Flow reports when the install keeps no traffic for the period (spec §6.4, 2026-10-29): lightweight mode, or a
period that starts before the local retention, pulls the period from the PCE into a throwaway store."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, Language, ReportStatus, ReportType
from illumio_ops.pce.async_query import AsyncQueryResult, PceQueryError
from illumio_ops.services import ondemand
from illumio_ops.services.reports import generate
from illumio_ops.services.reports.registry import ReportParams
from illumio_ops.store import reports as store
from illumio_ops.store.flowdb import labels, workloads
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import configured_ctx, raw_flow

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)  # a 7-day report covers 10-20 .. 10-27


def raw(i, *, dst="db", port=443, decision="allowed", conns=1, day=22, src_app="Web", dst_app="DB"):
    first = datetime(2026, 10, day, 3, tzinfo=UTC) + timedelta(seconds=i)
    r = raw_flow(i, first, first + timedelta(minutes=5), port=port)
    r["policy_decision"], r["num_connections"] = decision, conns
    r["src"]["workload"].update(href=f"/orgs/1/workloads/s{i}", hostname=f"s{i}",
                                labels=[{"key": "env", "value": "Dev"}, {"key": "app", "value": src_app}])
    r["dst"]["workload"].update(href=f"/orgs/1/workloads/{dst}", hostname=dst,
                                labels=[{"key": "env", "value": "Dev"}, {"key": "app", "value": dst_app}])
    return r


ROWS = [raw(1, conns=3), raw(2, conns=4), raw(3, port=22, decision="potentially_blocked", conns=5),
        raw(4, port=23, decision="blocked", conns=1)]


class FakePce:
    def __init__(self, rows):
        self.rows, self.payloads, self.fail = rows, [], False

    def __call__(self, client, payload, *, deadline, compute_draft=False, delete_after=True):
        self.payloads.append(payload)
        if self.fail:
            raise PceQueryError("poll", 500)
        a, b = datetime.fromisoformat(payload["start_date"]), datetime.fromisoformat(payload["end_date"])
        rows = [r for r in self.rows
                if a <= datetime.fromisoformat(r["timestamp_range"]["first_detected"]) < b]
        return AsyncQueryResult(rows=rows, matches_count=len(rows), flows_count=len(rows),
                                capped=len(rows) >= payload["max_results"])


@pytest.fixture
def pce(monkeypatch):
    fake = FakePce(ROWS)
    monkeypatch.setattr(ondemand, "run_traffic_query", fake)
    return fake


def _run(ctx, rtype=ReportType.TRAFFIC, lookback=7, **kw):
    rid = generate.enqueue(ctx, ReportParams(report_type=rtype, lookback_days=lookback, lang=Language.EN, **kw),
                           trigger="manual", schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    with ctx.db() as conn:
        return store.get(conn, rid)


def _flows(ctx):
    with ctx.flows().connect() as conn:
        return conn.execute("SELECT count(*) FROM flows").fetchone()[0]


def _html(ctx, row):
    return next((ctx.paths.reports_dir / str(row.id) / f).read_text() for f in row.files if f.endswith(".html"))


def _kpi(row, key):
    return next(k["value"] for k in row.kpis if k["key"] == key)


def test_lightweight_report_uses_ondemand(tmp_path, pce):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    row = _run(ctx)
    assert row.status is ReportStatus.DONE, row.error_key
    assert pce.payloads and _flows(ctx) == 0  # read from the PCE, nothing kept
    assert list(ondemand.ondemand_dir(ctx.paths).iterdir()) == []


def test_ondemand_builds_same_report_as_store(tmp_path, pce):
    light = _run(configured_ctx(tmp_path / "a", mode="lightweight"))
    full_ctx = configured_ctx(tmp_path / "b", mode="full")
    with full_ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(r) for r in ROWS], origin=DataOrigin.INGEST, now=NOW)
    calls = len(pce.payloads)
    full = _run(full_ctx)
    assert len(pce.payloads) == calls  # full mode within retention reads its own store
    assert [(k["key"], k["value"]) for k in light.kpis] == [(k["key"], k["value"]) for k in full.kpis]


def test_period_before_retention_goes_ondemand(tmp_path, pce):
    ctx = configured_ctx(tmp_path, mode="alert", retention={"flow_days": 8, "event_days": 90, "rollup_days": 8,
                                                             "baseline_days": 30})
    row = _run(ctx, lookback=30)
    assert row.status is ReportStatus.DONE, row.error_key
    first = datetime.fromisoformat(pce.payloads[0]["start_date"])
    assert first <= NOW - timedelta(days=29)  # the whole 30-day period, not just the 8 kept days


def test_ondemand_failure_fails_report(tmp_path, pce):
    pce.fail = True
    row = _run(configured_ctx(tmp_path, mode="lightweight"))
    assert row.status is ReportStatus.FAILED and row.error_key == "rpt_err_ondemand_failed"
    assert row.files == []


def test_quality_says_ondemand_and_current_labels(tmp_path, pce):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    html = _html(ctx, _run(ctx))
    assert "queried from the PCE when the report was made" in html and "labels as they are now" in html


def test_quality_states_pce_earliest(tmp_path, pce):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    html = _html(ctx, _run(ctx))
    assert "The PCE returned traffic from" in html  # the first record is 10-22, the period starts 10-20


def test_inventory_seeded(tmp_path, pce):
    """Reports join the flows with the inventory (enforcement modes, labels): the throwaway store has it too."""
    ctx = configured_ctx(tmp_path, mode="lightweight")
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/db", hostname="db", name=None, managed=1, enforcement_mode="full",
            visibility_level=None, os_id=None, ven_version=None, ven_href=None,
            label_set=labels.label_set_id(conn, (("app", "DB"), ("env", "Dev"))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x")])
        conn.commit()
    row = _run(ctx, ReportType.NETWORK_INVENTORY)
    assert row.status is ReportStatus.DONE, row.error_key
    assert "db" in _html(ctx, row)


def test_lateral_posture_lightweight_computes_exposure(tmp_path, pce):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    pce.rows = [raw(10, port=22), raw(11, port=3389, dst="app")]
    row = _run(ctx, ReportType.LATERAL_POSTURE)
    assert row.status is ReportStatus.DONE, row.error_key
    html = _html(ctx, row)
    assert "not computed" not in html.lower()


def test_new_connections_lightweight_pulls_baseline(tmp_path, pce):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    row = _run(ctx, ReportType.NEW_CONNECTIONS)
    # the baseline (30 days) before the 7-day period is read too, so "new" means new against it
    assert datetime.fromisoformat(pce.payloads[0]["start_date"]) == row.period_start - timedelta(days=30)


def test_lightweight_availability_not_greyed(tmp_path):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    assert all(v is None for v in generate.availability(ctx).values())


def test_ondemand_lookback_reaches_90_days(tmp_path, pce):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    assert generate.refusal(ctx.settings.current(), ReportParams(report_type=ReportType.TRAFFIC, lookback_days=90),
                            now=NOW) is None
