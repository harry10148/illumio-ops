"""The VEN status report (P5b-2 Task 2): online and offline by last heartbeat, policy sync problems, versions,
operating systems, enforcement modes and tampering with its known causes — from the inventory alone."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.store.flowdb import analysis, labels, workloads
from illumio_ops.store.flowdb.db import db_time
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def host(name, *, online=1, hb=timedelta(minutes=5), sync="applied", fw=1, received=None, applied=None,
         health=None, mode="full", version="26.2.20", os_id="ubuntu", status="active", app="Web", env="Prod"):
    return {"name": name, "online": online, "hb": hb, "sync": sync, "fw": fw, "received": received, "applied": applied, "health": health,
                "mode": mode, "version": version, "os_id": os_id, "status": status, "app": app, "env": env}


def _inventory(ctx, hosts):
    with ctx.flows().connect() as conn:
        rows = []
        for h in hosts:
            applied = h["applied"] if h["applied"] is not None else NOW - timedelta(hours=2)
            received = h["received"] if h["received"] is not None else applied
            rows.append(workloads.WorkloadRow(
                href=f"/orgs/1/workloads/{h['name']}", hostname=h["name"], name=None, managed=1,
                enforcement_mode=h["mode"], visibility_level=None, os_id=h["os_id"], ven_version=h["version"],
                ven_href=None, label_set=labels.label_set_id(conn, (("app", h["app"]), ("env", h["env"]))),
                online=h["online"], risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at=db_time(NOW),
                agent_status=h["status"], last_heartbeat_at=None if h["hb"] is None else db_time(NOW - h["hb"]),
                policy_sync_state=h["sync"], policy_received_at=None if h["status"] is None else db_time(received),
                policy_applied_at=None if h["status"] is None else db_time(applied), managed_since=None,
                fw_config_current=h["fw"], agent_health_json=json.dumps(h["health"]) if h["health"] else None))
        workloads.replace_inventory(conn, rows)
        conn.commit()


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.VEN_STATUS].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.VEN_STATUS), start=START, end=END, lang=lang, tz=UTC,
        now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid, i=0):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)][i]


def _kpi(doc):
    return {k.key: k.value for k in doc.kpis}


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_online_offline_buckets(ctx):
    _inventory(ctx, [host("on"), host("late", online=1, hb=timedelta(hours=3)),
                     host("d1", online=0, hb=timedelta(hours=5)), host("d2", online=0, hb=timedelta(hours=30)),
                     host("old", online=0, hb=timedelta(days=9))])
    k = _kpi(_build(ctx))
    assert (k["online"], k["lost_24h"], k["lost_48h"], k["long_offline"]) == (1, 2, 1, 1)
    rows = {r[0]: r[1] for r in _table(_build(ctx), "offline").rows}
    assert set(rows) == {"late", "d1", "d2", "old"}


def test_unknown_status_not_offline(ctx):
    _inventory(ctx, [host("on"), host("new", hb=None, status=None, sync=None, fw=None)])
    k = _kpi(_build(ctx))
    assert k["status_unknown"] == 1 and k["lost_24h"] == 0 and k["long_offline"] == 0 and k["sync_problems"] == 0
    assert any("not been collected" in q for q in _build(ctx).data_quality)


def test_sync_problems_online_only(ctx):
    _inventory(ctx, [host("ok"), host("syncing", sync="syncing"), host("stale_fw", fw=0),
                     host("behind", received=NOW - timedelta(minutes=10), applied=NOW - timedelta(hours=3)),
                     host("warn", health=[{"type": "ven.x", "severity": "warning"}]),
                     host("off_bad", online=0, hb=timedelta(hours=5), sync="syncing")])
    rows = {r[0]: r[1] for r in _table(_build(ctx), "sync").rows}
    assert set(rows) == {"syncing", "stale_fw", "behind", "warn"}
    assert _kpi(_build(ctx))["sync_problems"] == 4


def test_mode_unknown_not_selective(ctx):
    _inventory(ctx, [host("a", mode="selective"), host("b", mode=None)])
    row = _table(_build(ctx), "modes").rows[0]
    assert row[0] == "Web (Prod)" and row[1:] == (2, 0, 1, 0, 0, 1, "50.0%")


def test_versions_and_os(ctx):
    _inventory(ctx, [host("a"), host("b"), host("c", version="25.2.1", os_id="windows")])
    assert _table(_build(ctx), "versions").rows[0] == ("26.2.20", 2)
    assert {r[0] for r in _table(_build(ctx), "versions", 1).rows} == {"ubuntu", "windows"}


def test_tamper_section_from_analysis(tmp_path):
    a = configured_ctx(tmp_path / "a")
    _inventory(a, [host("on")])
    texts = " ".join(p for b in _section(_build(a), "tamper").blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert "not been computed" in texts
    b = configured_ctx(tmp_path / "b")
    _inventory(b, [host("on")])
    with b.flows().connect() as conn:
        analysis.write_result(conn, "tamper", params={}, at=NOW, result={"unmatched": 0, "hosts": [
            {"href": "/orgs/1/workloads/on", "hostname": "on", "n_60d": 12, "n_7d": 3, "pattern": "periodic",
             "median_minutes": 10.0, "last_at": NOW.isoformat(), "unexplained_7d": 2, "has_signal": True}]})
        conn.commit()
    doc = _build(b)
    assert _table(doc, "tamper").rows[0][:4] == ("on", 12, 3, 2) and _kpi(doc)["unexplained_tamper"] == 1


def test_all_kpis_rendered(ctx):
    _inventory(ctx, [host("on")])
    doc = _build(ctx)
    html = render_html(doc, tz=UTC)
    assert len(doc.kpis) >= 8 and all(k.label in html for k in doc.kpis)


def test_zh_tw_builds(ctx):
    _inventory(ctx, [host("on"), host("d1", online=0, hb=timedelta(hours=5))])
    assert _build(ctx, Language.ZH_TW).title
