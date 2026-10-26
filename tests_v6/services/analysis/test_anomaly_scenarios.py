"""The anomaly detectors end to end (spec §6.5.8): a store with 20 days of history behind a full 30-day baseline,
one cycle's live records, and run_detection storing exactly the detections each scenario plants."""
import json
from datetime import timedelta
from typing import Any

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.services import flowsource_anomaly
from illumio_ops.services.analysis.detect import run_detection
from illumio_ops.store.flowdb import analysis, ingest_state, workloads
from illumio_ops.store.flowdb.db import StaleGeneration
from illumio_ops.store.flowdb.flows import upsert_flows
from illumio_ops.store.flowdb.labels import label_set_id
from tests_v6.services.collect.conftest import NOW, configured_ctx

W = "/orgs/1/workloads/"
DAY = 24 * 60


IPS: dict[str, str] = {}


def end(e: str) -> dict[str, Any]:
    if e.startswith("ip:"):
        return {"ip": e[3:]}
    ip = IPS.setdefault(e, f"10.1.0.{len(IPS) + 1}")
    return {"ip": ip, "workload": {"href": W + e, "hostname": e, "managed": True, "labels": []}}


def flow(src: str, dst: str, *, port: int, minutes_ago: int, user: str | None = None, process: str | None = None,
         decision: str = "potentially_blocked") -> Any:
    last = NOW - timedelta(minutes=minutes_ago)
    return normalize_flow({
        "src": end(src), "dst": end(dst),
        "service": {"port": port, "proto": 6, "user_name": user, "process_name": process},
        "policy_decision": decision, "flow_direction": "outbound",
        "timestamp_range": {"first_detected": (last - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "last_detected": last.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "num_connections": 1})


def setup(tmp_path, *, inventory: dict[str, dict[str, str]], history: list[Any], live: list[Any]):
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        rows = []
        for name, labels in inventory.items():
            ls = label_set_id(conn, tuple(sorted(labels.items()))) if labels else None
            rows.append(workloads.WorkloadRow(
                href=W + name, hostname=name, name=None, managed=1, enforcement_mode="visibility_only",
                visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=ls, online=1,
                risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x"))
        workloads.replace_inventory(conn, rows)
        upsert_flows(conn, history, origin=DataOrigin.BACKFILL, now=NOW - timedelta(days=1))
        upsert_flows(conn, live, origin=DataOrigin.INGEST, now=NOW, increments="cycle")
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, NOW - timedelta(days=31), NOW)
        ingest_state.mark_ok(conn, IngestSource.TRAFFIC, NOW, watermark=NOW, rows=0)
    return ctx


def stored(ctx):
    with ctx.flows().connect() as conn:
        return analysis.detections_since(conn, NOW - timedelta(days=30), limit=500)


def kinds(ctx):
    return {r["detector"] for r in stored(ctx)}


def by_kind(ctx, kind):
    return [r for r in stored(ctx) if r["detector"] == kind]


def test_scenario_peer(tmp_path):
    web = {f"pay-web{i}": {"app": "Pay", "role": "Web"} for i in range(6)}
    inventory = {**web, "pay-db": {"app": "Pay", "role": "DB"}, "hr-app": {"app": "HR", "role": "App"}}
    history = [flow(h, "pay-db", port=5432, minutes_ago=20 * DAY) for h in web]
    ctx = setup(tmp_path, inventory=inventory, history=history,
                live=[flow("pay-web0", "hr-app", port=8443, minutes_ago=5)])
    run_detection(ctx, now=NOW)
    assert kinds(ctx) == {"peer_deviation"}
    [d] = by_kind(ctx, "peer_deviation")
    assert d["subject_key"] == W + "pay-web0" and json.loads(d["summary_json"])["group_size"] == 6


def test_scenario_account(tmp_path):
    inventory = {"ws-1": {}, "srv-9": {}, "app": {}}
    ctx = setup(tmp_path, inventory=inventory,
                history=[flow("ws-1", "app", port=8080, minutes_ago=20 * DAY, user="CORP\\alice")],
                live=[flow("srv-9", "app", port=8080, minutes_ago=5, user="corp\\Alice")])
    run_detection(ctx, now=NOW)
    assert kinds(ctx) == {"account_new_source"}
    [d] = by_kind(ctx, "account_new_source")
    assert d["subject_key"] == "corp\\alice" and json.loads(d["summary_json"])["known_sources"] == 1


def test_scenario_tool(tmp_path):
    ctx = setup(tmp_path, inventory={"srv-3": {}}, history=[],
                live=[flow("srv-3", "ip:10.0.5.7", port=8080, minutes_ago=5, process="PsExec.exe")])
    run_detection(ctx, now=NOW)
    assert kinds(ctx) == {"suspicious_tool"}


def test_scenario_new_process(tmp_path):
    ctx = setup(tmp_path, inventory={"srv-3": {}, "app": {}},
                history=[flow("srv-3", "app", port=8080, minutes_ago=20 * DAY, process="sshd")],
                live=[flow("srv-3", "app", port=8080, minutes_ago=5, process="curl")])
    run_detection(ctx, now=NOW)
    assert kinds(ctx) == {"new_process"}


def test_scenario_directory(tmp_path):
    inventory = {"dc-1": {}, "s1": {}, "s2": {}, "s3": {}, "ws-4": {}, **{f"t{i}": {} for i in range(10)}}
    history = [flow(s, "dc-1", port=p, minutes_ago=20 * DAY) for s in ("s1", "s2", "s3", "ws-4") for p in (88, 389)]
    live = [flow("ws-4", "ip:10.0.9.9", port=389, minutes_ago=5),
            flow("ip:10.0.8.8", "dc-1", port=88, minutes_ago=30)]
    live += [flow("ip:10.0.8.8", f"t{i}", port=445, minutes_ago=15) for i in range(10)]
    ctx = setup(tmp_path, inventory=inventory, history=history, live=live)
    run_detection(ctx, now=NOW)
    assert {"auth_to_non_dc", "new_dc_client", "fanout"} <= kinds(ctx)
    [auth] = by_kind(ctx, "auth_to_non_dc")
    assert auth["subject_key"] == W + "ws-4"
    [client] = by_kind(ctx, "new_dc_client")
    assert client["subject_key"] == "ip:10.0.8.8" and client["severity"] == "medium"
    [fan] = by_kind(ctx, "fanout")
    assert fan["severity"] == "high" and "after_directory" in json.loads(fan["summary_json"])


def test_late_pass_skips_volume(tmp_path):
    ctx = setup(tmp_path, inventory={"srv-3": {}}, history=[], live=[])
    r = run_detection(ctx, now=NOW, window=(NOW - timedelta(days=1), NOW), late=True)
    [vol] = [s for s in r.statuses if s["detector"] == "volume_surge"]
    assert vol["reason_key"] == "detector_live_only"


def test_switch_during_anomaly_reads_stores_nothing(tmp_path, monkeypatch):
    ctx = setup(tmp_path, inventory={"ws-1": {}, "srv-9": {}, "app": {}},
                history=[flow("ws-1", "app", port=8080, minutes_ago=20 * DAY, user="CORP\\alice")],
                live=[flow("srv-9", "app", port=8080, minutes_ago=5, user="corp\\Alice")])

    def switched(*a, **kw):
        raise StaleGeneration
    monkeypatch.setattr(flowsource_anomaly, "account_first_seen", switched)
    r = run_detection(ctx, now=NOW)
    assert r.window is None and stored(ctx) == []


@pytest.mark.parametrize("name", ["volume_surge", "peer_deviation"])
def test_statuses_name_every_anomaly_detector(tmp_path, name):
    ctx = setup(tmp_path, inventory={"srv-3": {}}, history=[], live=[])
    r = run_detection(ctx, now=NOW)
    assert name in {s["detector"] for s in r.statuses}
