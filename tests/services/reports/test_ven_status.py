"""The VEN status report (P5b-2 Task 2): online and offline by last heartbeat, policy sync problems, versions,
operating systems, enforcement modes and tampering with its known causes — from the inventory alone."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.report import TableBlock
from illumio_ops.domain.values import Language, ReportType, Severity
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.store.flowdb import analysis, labels, ven_compat, workloads
from illumio_ops.store.flowdb.db import db_time
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def host(name, *, online=1, hb=timedelta(minutes=5), sync="applied", fw=1, received=None, applied=None,
         health=None, mode="full", version="26.2.20", os_id="ubuntu", status="active", app="Web", env="Prod",
         compat=None):
    return {"name": name, "online": online, "hb": hb, "sync": sync, "fw": fw, "received": received, "applied": applied, "health": health,
                "mode": mode, "version": version, "os_id": os_id, "status": status, "app": app, "env": env,
                "compat": compat}


def _inventory(ctx, hosts, read_at=NOW):
    with ctx.flows().connect() as conn:
        rows = []
        for h in hosts:
            applied = h["applied"] if h["applied"] is not None else NOW - timedelta(hours=2)
            received = h["received"] if h["received"] is not None else applied
            rows.append(workloads.WorkloadRow(
                href=f"/orgs/1/workloads/{h['name']}", hostname=h["name"], name=None, managed=1,
                enforcement_mode=h["mode"], visibility_level=None, os_id=h["os_id"], ven_version=h["version"],
                ven_href=f"/orgs/1/vens/{h['name']}", label_set=labels.label_set_id(conn, (("app", h["app"]), ("env", h["env"]))),
                online=h["online"], risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at=db_time(read_at),
                agent_status=h["status"], last_heartbeat_at=None if h["hb"] is None else db_time(read_at - h["hb"]),
                policy_sync_state=h["sync"], policy_received_at=None if h["status"] is None else db_time(received),
                policy_applied_at=None if h["status"] is None else db_time(applied), managed_since=None,
                fw_config_current=h["fw"], agent_health_json=json.dumps(h["health"]) if h["health"] else None))
        workloads.replace_inventory(conn, rows)
        for h in hosts:
            if h["compat"] is not None:  # (qualify_status, issues, report_at)
                status, issues, report_at = h["compat"]
                ven_compat.record(conn, f"/orgs/1/vens/{h['name']}", qualify_status=status, issues=issues,
                                  report_at=report_at, at=read_at)
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


def test_online_is_judged_at_the_inventory_read_not_aged_until_the_report(ctx):
    """The inventory is read once an hour: a heartbeat 5 minutes before a read 58 minutes ago is online, as the PCE
    said then (aged against the report's clock, a whole fleet showed as lost each hour before the next read)."""
    _inventory(ctx, [host("on"), host("d1", online=0, hb=timedelta(hours=5))], read_at=NOW - timedelta(minutes=58))
    k = _kpi(_build(ctx))
    assert (k["online"], k["lost_24h"]) == (1, 1)


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
    doc = _build(a)  # 6.6.0: not computed yet — no section, no number, one data note
    assert "tamper" not in {s.id for s in doc.sections} and "unexplained_tamper" not in _kpi(doc)
    assert sum("tamper analysis has not been computed" in q for q in doc.data_quality) == 1
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
    assert len(doc.kpis) >= 7 and all(k.label in html for k in doc.kpis)  # the tamper number needs its analysis


def test_zh_tw_builds(ctx):
    _inventory(ctx, [host("on"), host("d1", online=0, hb=timedelta(hours=5))])
    assert _build(ctx, Language.ZH_TW).title


def test_compat_state_from_the_pces_compatibility_report():
    """The PCE's VEN compatibility report (GET /vens/<id>/compatibility_report, lab 26.2.20): green, yellow, red.
    Workload agent_health carries no compatibility entries on a real PCE, so it is not read. Only a host in Idle is
    checked: the PCE writes the report while a VEN is in Idle, and a report kept from before is a leftover."""
    from illumio_ops.services.reports.ven_status import compat_state
    from illumio_ops.store.flowdb.ven_compat import VenCompat

    def row(status):
        return VenCompat("/orgs/1/vens/v", status, (), None, "2026-10-27T00:00:00.000000Z")
    assert compat_state(row("green"), "idle") == "pass"
    assert compat_state(row("Yellow"), "idle") == "warn"
    assert compat_state(row("red"), "idle") == "fail"
    assert compat_state(row(None), "idle") == "unknown"  # the PCE has no report for this VEN
    assert compat_state(row("purple"), "idle") == "unknown"
    assert compat_state(None, "idle") == "unknown"  # not read yet
    assert compat_state(row("red"), "full") == "na"
    assert compat_state(None, "full") == "na"
    assert compat_state(row("yellow"), "selective") == "na"  # a leftover from its time in Idle
    assert compat_state(row("green"), "visibility_only") == "na"
    assert compat_state(None, None) == "na"


def test_online_list_and_compat_tally(ctx):
    _inventory(ctx, [host("b-on", mode="idle", compat=("yellow", ("ipv4_forwarding_enabled", "iptables_rule_cnt"),
                                                         db_time(NOW - timedelta(days=40)))),
                     host("a-on", version="25.2.1", mode="idle"),
                     host("c-on", version="25.2.1"),
                     host("d-on", mode="selective", compat=("green", (), db_time(NOW - timedelta(days=100)))),
                     host("off", online=0, hb=timedelta(hours=5), mode="idle",
                          compat=("red", ("required_packages_installed",), db_time(NOW - timedelta(days=1))))])
    doc = _build(ctx)
    online = _table(doc, "online")
    assert [r[0] for r in online.rows] == ["a-on", "b-on", "c-on", "d-on"] and online.total_rows == 4
    cols = [c.key for c in online.columns]
    assert len(cols) < 9  # stays a portrait table
    row = dict(zip(cols, online.rows[1], strict=True))
    assert row["app"] == "Web (Prod)" and row["version"] == "26.2.20"
    assert row["compat"] == "Warning (IPv4 forwarding, existing iptables rules)"  # says which checks, readably
    assert row["mode"] == "Idle"
    assert dict(zip(cols, online.rows[0], strict=True))["compat"] == "Unknown"
    assert dict(zip(cols, online.rows[2], strict=True))["compat"] == "Not checked (not Idle)"
    assert dict(zip(cols, online.rows[3], strict=True))["compat"] == "Not checked (not Idle)"  # its report is a leftover
    tally = {r[0]: r[1] for r in _table(doc, "online", 1).rows}
    assert tally == {"Pass": 0, "Warning": 1, "Fail": 1, "Unknown": 1, "Not checked (not Idle)": 2}
    quality = " ".join(doc.data_quality)
    assert "compatibility report" in quality and "1 hosts" in quality
    assert "2026-09-17" in quality  # the oldest report the PCE holds, so a stale one is visible
    assert "2026-07-19" not in quality  # a leftover of a host out of Idle is not counted


def test_compat_checks_read_as_words_in_both_languages(ctx):
    """The PCE names its checks in snake_case; a known one reads as words, an unknown one breaks at its underscores so
    a narrow table can wrap it rather than cut it."""
    _inventory(ctx, [host("h", mode="idle", compat=("red", ("routing_table_conflict", "windows_firewall_gpo_state"),
                                                      None))])
    zh = _build(ctx, Language.ZH_TW)
    row = dict(zip([c.key for c in _table(zh, "online").columns], _table(zh, "online").rows[0], strict=True))
    assert row["compat"] == "不通過（路由表衝突、windows firewall gpo state）"


def test_compat_issues_beyond_three_are_counted(ctx):
    _inventory(ctx, [host("h", mode="idle", compat=("yellow", ("a", "b", "c", "d", "e"), None))])
    row = dict(zip([c.key for c in _table(_build(ctx), "online").columns], _table(_build(ctx), "online").rows[0],
                   strict=True))
    assert row["compat"] == "Warning (a, b, c +2)"


def test_findings_count_what_the_tables_list(ctx):
    """Each finding's number is the row count of a table in the same report."""
    _inventory(ctx, [host("on"), host("d1", online=0, hb=timedelta(hours=5)),
                     host("old", online=0, hb=timedelta(days=9)), host("stale", fw=0),
                     host("idle", mode="idle", compat=("yellow", ("ipv4_forwarding_enabled",), NOW.isoformat()))])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "tamper", params={}, at=NOW, result={"unmatched": 0, "hosts": [
            {"href": "/orgs/1/workloads/on", "hostname": "on", "n_60d": 12, "n_7d": 3, "pattern": "periodic",
             "median_minutes": 10.0, "last_at": NOW.isoformat(), "unexplained_7d": 2, "has_signal": True},
            {"href": "/orgs/1/workloads/stale", "hostname": "stale", "n_60d": 4, "n_7d": 0, "pattern": "sporadic",
             "median_minutes": None, "last_at": NOW.isoformat(), "unexplained_7d": 0, "has_signal": False}]})
        conn.commit()
    doc = _build(ctx)
    titles = [f.title for f in doc.findings]
    assert len(doc.findings) == 4
    assert titles[0].startswith(f"{_table(doc, 'offline').total_rows} ")
    assert doc.findings[0].severity is Severity.HIGH  # one of them has been silent for more than 48 hours
    assert any(t.startswith("1 ") and "tampering" in t for t in titles)
    assert any(t.startswith(f"{_table(doc, 'sync').total_rows} ") and "policy" in t for t in titles)
    assert any(t.startswith("1 ") and "compatibility" in t for t in titles)
    by = {f.action_code: f for f in doc.findings}
    assert set(by) == {"ven_offline", "ven_tamper", "ven_sync", "ven_compat"} and all(f.action_short for f in by.values())
    off = by["ven_offline"]
    assert off.what == "Under 24 hours: 1; 24–48 hours: 0; over 48 hours: 1."
    assert off.why == "A VEN that is not reporting gets no policy updates and sends no traffic."
    assert off.action_focus == "old has been out of contact the longest."
    assert by["ven_compat"].what.startswith("Warning: 1; failed: 0,") and "gets in the way" in by["ven_compat"].why
    assert "no known cause recorded on the host page" in by["ven_tamper"].what and by["ven_tamper"].why
    assert by["ven_sync"].what == "" and by["ven_sync"].why


def test_no_findings_when_nothing_needs_action(ctx):
    _inventory(ctx, [host("on"), host("new", hb=None, status=None, sync=None, fw=None)])
    assert _build(ctx).findings == ()


def test_offline_under_48_hours_is_medium(ctx):
    _inventory(ctx, [host("on"), host("d1", online=0, hb=timedelta(hours=5))])
    (finding,) = _build(ctx, Language.ZH_TW).findings
    assert finding.severity is Severity.MEDIUM and finding.title.startswith("1 ")


def test_sync_state_and_tamper_pattern_read_as_words(ctx):
    # 2026-11-10 report review: the tables printed the PCE's raw "syncing" and the analysis' raw "sporadic".
    _inventory(ctx, [host("on"), host("busy", sync="syncing"), host("odd", sync="quarantined")])
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "tamper", params={}, at=NOW, result={"unmatched": 0, "hosts": [
            {"href": "/orgs/1/workloads/on", "hostname": "on", "n_60d": 4, "n_7d": 1, "pattern": "sporadic",
             "median_minutes": None, "last_at": NOW.isoformat(), "unexplained_7d": 1, "has_signal": False},
            {"href": "/orgs/1/workloads/busy", "hostname": "busy", "n_60d": 4, "n_7d": 1, "pattern": "periodic",
             "median_minutes": None, "last_at": NOW.isoformat(), "unexplained_7d": 1, "has_signal": False}]})
        conn.commit()
    for lang, applied, syncing, sporadic in ((Language.EN, "Applied", "Syncing", "sporadic"),
                                             (Language.ZH_TW, "已套用", "同步中", "零星")):
        doc = _build(ctx, lang)
        sync = {r[0]: r[6] for r in _table(doc, "online").rows}
        # a state with no wording is shown as the PCE sent it, never guessed
        assert (sync["on"], sync["busy"], sync["odd"]) == (applied, syncing, "quarantined")
        assert {r[0]: r[2] for r in _table(doc, "sync").rows}["busy"] == syncing
        pattern = {r[0]: r[4] for r in _table(doc, "tamper").rows}
        assert (pattern["on"], pattern["busy"]) == (sporadic, "periodic")
