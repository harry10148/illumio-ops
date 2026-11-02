"""The host page's usual behaviour, what differs this time, quarantine eligibility and host search (UI redesign
spec §4.4, §5.1)."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.services import hosts
from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.analysis import DetectionWrite
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
WEB = "/orgs/1/workloads/web"
DB = "/orgs/1/workloads/db"


def _wl(href, hostname, mode="selective"):
    return workloads.WorkloadRow(
        href=href, hostname=hostname, name=None, managed=1, enforcement_mode=mode, visibility_level=None, os_id=None,
        ven_version="26.2.20", ven_href=None, label_set=None, online=1, risk_exposure=None, risk_percent=None,
        risk_updated_at=None, fetched_at="x")


def _rollup(conn, day, src, dst, *, port=445, user="", process="", connections=1):
    conn.execute(
        "INSERT INTO flow_rollup_daily (day, src_key, dst_key, port, proto, policy_decision, initiator_user, "
        "initiator_process, connections, flow_records, bytes_in, bytes_out, bytes_known_records) "
        "VALUES (?, ?, ?, ?, 6, 'allowed', ?, ?, ?, 1, 0, 0, 0)", (day, src, dst, port, user, process, connections))


def _day(n):
    return (NOW - timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    with c.flows().connect() as conn:
        workloads.replace_inventory(conn, [_wl(WEB, "web-01"), _wl(DB, "db-01", "idle")])
        for n in range(1, 11):
            _rollup(conn, _day(n), WEB, DB, user="CORP\\svc", process="sqlcmd.exe", connections=10)
        for i in range(7):
            _rollup(conn, _day(2), WEB, f"ip:10.0.0.{i}", process=f"p{i}.exe", connections=i + 1)
        _rollup(conn, _day(31), WEB, "ip:10.9.9.9", process="old.exe", connections=999)  # older than 30 days
        conn.commit()
    return c


def test_usual_top5_by_connections_30d(ctx):
    p = hosts.profile(ctx, WEB, now=NOW)
    assert p.usual_state == "ok" and p.usual is not None
    assert [r.value for r in p.usual.top_destinations][:2] == ["db-01", "10.0.0.6"]
    assert len(p.usual.top_destinations) == 5 and p.usual.top_destinations[0].connections == 100
    assert p.usual.top_processes[0].value == "sqlcmd.exe"
    assert "old.exe" not in [r.value for r in p.usual.top_processes]
    assert [r.value for r in p.usual.top_accounts] == ["CORP\\svc"]  # unknown accounts ('') are not listed
    assert p.usual.days_covered == 30


def test_usual_basic_mode(tmp_path):
    light = configured_ctx(tmp_path, mode="lightweight")
    p = hosts.profile(light, WEB, now=NOW)
    assert p.usual is None and p.usual_state == "basic_mode"


def test_usual_accumulating_when_fewer_than_7_days(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    with c.flows().connect() as conn:
        workloads.replace_inventory(conn, [_wl(WEB, "web-01")])
        _rollup(conn, _day(1), WEB, DB, connections=3)
        conn.commit()
    p = hosts.profile(c, WEB, now=NOW)
    assert p.usual_state == "accumulating" and p.usual is not None and p.usual.days_covered == 1
    assert p.usual.top_destinations[0].connections == 3


def test_different_lists_detection_summaries_7d(ctx):
    with ctx.flows().connect() as conn:
        for name, first in (("new_process", NOW - timedelta(days=2)), ("fanout", NOW - timedelta(days=9))):
            analysis.upsert_detections(conn, [DetectionWrite(
                detector=name, fingerprint=f"{name}|{WEB}", subject_key=WEB, severity="medium", first_seen=first,
                last_seen=first + timedelta(minutes=5), critical_asset=False,
                summary_json=json.dumps({"process": "psexesvc.exe", "port": 445, "target": "db-01"}),
                segment_json="{}", confidence_json="{}")], dedup={name: timedelta(minutes=1)}, late=False, at=NOW)
        conn.commit()
    p = hosts.profile(ctx, WEB, now=NOW)
    assert [d.detector for d in p.different] == ["new_process"]
    assert "psexesvc.exe" in p.different[0].text and "{" not in p.different[0].text


def test_quarantine_eligibility(ctx):
    assert hosts.profile(ctx, WEB, now=NOW).quarantine.eligible
    idle = hosts.profile(ctx, DB, now=NOW).quarantine
    assert idle.eligible and idle.no_enforcement
    gone = hosts.profile(ctx, "/orgs/1/workloads/gone", now=NOW).quarantine
    assert not gone.eligible and gone.reason == "not_in_inventory"
    ip = hosts.profile(ctx, "ip:10.0.0.9", now=NOW).quarantine
    assert not ip.eligible and ip.reason == "unmanaged"


def test_search_by_name_and_ip(ctx):
    assert [h.key for h in hosts.search(ctx, "web").items] == [WEB]
    assert [h.key for h in hosts.search(ctx, "DB-").items] == [DB]
    ip = hosts.search(ctx, "10.1.2.3").items
    assert [(h.key, h.managed) for h in ip] == [("ip:10.1.2.3", False)]
    assert hosts.search(ctx, "").items == []


def test_different_keeps_the_newest_when_many(ctx):
    with ctx.flows().connect() as conn:
        for i in range(22):
            first = NOW - timedelta(days=6) + timedelta(hours=i)
            analysis.upsert_detections(conn, [DetectionWrite(
                detector="new_process", fingerprint=f"np{i}|{WEB}", subject_key=WEB, severity="medium",
                first_seen=first, last_seen=first, critical_asset=False, summary_json="{}", segment_json="{}",
                confidence_json="{}")], dedup={"new_process": timedelta(minutes=1)}, late=False, at=NOW)
        conn.commit()
    p = hosts.profile(ctx, WEB, now=NOW)
    assert p.different[0].first_seen == NOW - timedelta(days=6) + timedelta(hours=21)


def test_search_ip_resolves_a_known_workload(ctx):
    from illumio_ops.domain.flows import normalize_flow
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows
    from tests.services.collect.conftest import raw_flow
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(raw_flow(3, NOW - timedelta(hours=2), NOW - timedelta(hours=1)))],
                     origin=DataOrigin.INGEST, now=NOW)
        conn.commit()
    [hit] = hosts.search(ctx, "10.0.1.3").items
    assert (hit.key, hit.managed) == ("/orgs/1/workloads/src-3", True)
