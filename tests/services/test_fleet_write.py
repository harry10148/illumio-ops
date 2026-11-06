"""VEN fleet writes: enforcement progression (preview per host with what Full would block, apply only what the preview
showed, one field written per host with the write key, every attempt recorded) and the traffic update rate increase."""
import base64
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
import responses

from illumio_ops.domain.values import DataOrigin
from illumio_ops.services import fleet_write
from illumio_ops.services.fleet_write import EnforcementHost, LabelPick
from illumio_ops.store.flowdb import labels as label_store
from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_findings import flow

NOW = datetime(2026, 10, 27, 1, tzinfo=UTC)
API = "https://pce.example.com:8443/api/v2"
VIS, IDLE, FULL, SEL = (f"/orgs/1/workloads/{n}" for n in ("db", "idle-01", "full-01", "sel-01"))


def _wl(href, hostname, mode, label_set=None):
    return workloads.WorkloadRow(
        href=href, hostname=hostname, name=None, managed=1, enforcement_mode=mode, visibility_level=None, os_id=None,
        ven_version=None, ven_href=None, label_set=label_set, online=1, risk_exposure=None, risk_percent=None,
        risk_updated_at=None, fetched_at="x", last_heartbeat_at=(NOW - timedelta(minutes=3)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"))


def _ctx(tmp_path, *, write=True):
    c = configured_ctx(tmp_path, mode="full")
    if write:
        c.settings.update(c.settings.current().revision,
                          lambda d: d["pce"].update(write_api_key="wk", write_api_secret="ws"))
    with c.flows().connect() as conn:
        prod = label_store.label_set_id(conn, (("app", "DB"), ("env", "Prod")))
        workloads.replace_inventory(conn, [_wl(VIS, "db", "visibility_only", prod), _wl(IDLE, "idle-01", "idle", prod),
                                           _wl(FULL, "full-01", "full"), _wl(SEL, "sel-01", "selective")])
        upsert_flows(conn, [flow(src="a", dst="db", decision="potentially_blocked", conns=3),
                            flow(src="a", dst="db", decision="potentially_blocked", conns=2),
                            flow(src="b", dst="db", decision="potentially_blocked", conns=1),
                            flow(src="c", dst="db", decision="allowed", conns=4),
                            flow(src="a", dst="other", decision="potentially_blocked", conns=9)],
                     origin=DataOrigin.INGEST, now=NOW)
        conn.commit()
    return c


@pytest.fixture
def ctx(tmp_path):
    return _ctx(tmp_path)


def _user(call):
    return base64.b64decode(call.request.headers["Authorization"].split()[1]).decode().split(":")[0]


def _rows(ctx):
    with ctx.db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM fleet_actions ORDER BY id")]


# ── preview ──────────────────────────────────────────────────────────────────

def test_preview_full_counts_what_was_reported_potentially_blocked_into_each_host(ctx):
    p = fleet_write.preview(ctx, [VIS, FULL, "ip:10.0.0.9", "/orgs/1/workloads/gone"], "full", now=NOW)
    assert [(t.key, t.ok, t.reason, t.current) for t in p.targets] == [
        (VIS, True, None, "visibility_only"), (FULL, False, "same_mode", "full"),
        ("ip:10.0.0.9", False, "unmanaged", None), ("/orgs/1/workloads/gone", False, "not_in_inventory", None)]
    assert p.basis == "connections" and p.write_key
    [b] = p.blocks
    assert (b.key, b.inbound, b.would_block) == (VIS, 10, 6)  # the flow into "other" is not this host's
    assert [(s.name, s.connections) for s in b.top_sources] == [("a", 5), ("b", 1)]
    assert p.window_end - p.window_start == fleet_write.PREVIEW


def test_preview_selective_and_visibility_compute_no_count(ctx, monkeypatch):
    monkeypatch.setattr(fleet_write, "_blocks", lambda *a, **k: pytest.fail("no ranking for this target"))
    sel = fleet_write.preview(ctx, [VIS], "selective", now=NOW)
    assert sel.basis == "deny_rules" and sel.blocks == [] and sel.targets[0].ok
    vis = fleet_write.preview(ctx, [IDLE], "visibility_only", now=NOW)
    assert vis.basis == "none" and vis.blocks == []


def test_preview_refuses_backward(ctx):
    p = fleet_write.preview(ctx, [FULL, SEL], "selective", now=NOW)
    assert [(t.ok, t.reason) for t in p.targets] == [(False, "not_forward"), (False, "same_mode")]


def test_label_selection_resolves_to_hosts_and_is_bounded(ctx, monkeypatch):
    assert fleet_write.select(ctx, [LabelPick(key="env", value="Prod")]) == [VIS, IDLE]
    assert fleet_write.select(ctx, [LabelPick(key="env", value="Prod"), LabelPick(key="app", value="Web")]) == []
    monkeypatch.setattr(fleet_write, "MAX_BATCH", 1)
    with pytest.raises(fleet_write.SelectionTooLarge):
        fleet_write.select(ctx, [LabelPick(key="env", value="Prod")])
    with pytest.raises(ValueError):
        fleet_write.select(ctx, [])


# ── apply ────────────────────────────────────────────────────────────────────

def _live(href, mode, managed=True):
    responses.add(responses.GET, f"{API}{href}", json={"href": href, "enforcement_mode": mode, "managed": managed,
                                                         "labels": []})


@responses.activate
def test_apply_writes_only_the_mode_with_the_write_key_and_records(ctx):
    _live(VIS, "visibility_only")
    responses.add(responses.PUT, f"{API}{VIS}", status=204)
    out = fleet_write.apply(ctx, [EnforcementHost(key=VIS, from_mode="visibility_only")], "full", by="admin", now=NOW)
    [r] = out.results
    assert (r.status, r.previous, r.name) == ("ok", "visibility_only", "db")
    put = next(c for c in responses.calls if c.request.method == "PUT")
    assert json.loads(put.request.body) == {"enforcement_mode": "full"}
    assert all(_user(c) == "wk" for c in responses.calls)
    [row] = _rows(ctx)
    assert (row["action"], row["previous_mode"], row["target_mode"], row["result"], row["by_user"], row["batch_id"]) == (
        "enforcement", "visibility_only", "full", "ok", "admin", out.batch_id)
    with ctx.flows().connect() as conn:  # the inventory says what the PCE now holds
        assert {w.href: w.enforcement_mode for w in workloads.all_workloads(conn)}[VIS] == "full"


@responses.activate
def test_partial_failure_is_per_host_and_hosts_not_chosen_are_untouched(ctx):
    _live(VIS, "visibility_only")
    _live(IDLE, "idle")
    responses.add(responses.PUT, f"{API}{VIS}", status=204)
    responses.add(responses.PUT, f"{API}{IDLE}", status=403, json={"error": "Access denied."})
    out = fleet_write.apply(ctx, [EnforcementHost(key=VIS, from_mode="visibility_only"),
                                  EnforcementHost(key=IDLE, from_mode="idle"),
                                  EnforcementHost(key=FULL, from_mode="full")], "full", by="admin", now=NOW)
    assert [(r.key, r.status) for r in out.results] == [(VIS, "ok"), (IDLE, "failed"), (FULL, "skipped")]
    assert "403" in (out.results[1].detail or "") and out.results[2].detail == "same_mode"
    written = {c.request.url.removeprefix(API) for c in responses.calls if c.request.method == "PUT"}
    assert written == {VIS, IDLE}  # SEL was never chosen, FULL was refused
    assert [r["result"] for r in _rows(ctx)] == ["ok", "failed", "skipped"]


@responses.activate
def test_a_mode_changed_since_the_preview_is_not_written(ctx):
    _live(VIS, "selective")  # someone moved it in the PCE after the preview
    out = fleet_write.apply(ctx, [EnforcementHost(key=VIS, from_mode="visibility_only")], "full", by="a", now=NOW)
    assert [(r.status, r.detail, r.previous) for r in out.results] == [("skipped", "mode_changed", "selective")]
    # the inventory moved on too: refused before any read
    out = fleet_write.apply(ctx, [EnforcementHost(key=IDLE, from_mode="visibility_only")], "full", by="a", now=NOW)
    assert [(r.status, r.detail) for r in out.results] == [("skipped", "mode_changed")]
    assert not any(c.request.method == "PUT" for c in responses.calls)
    assert sum(1 for c in responses.calls if c.request.url.endswith(IDLE)) == 0


@responses.activate
def test_unanswered_write_is_unknown_not_done(ctx):
    from requests.exceptions import ConnectionError as ConnErr
    _live(VIS, "visibility_only")
    responses.add(responses.PUT, f"{API}{VIS}", body=ConnErr("reset"))
    [r] = fleet_write.apply(ctx, [EnforcementHost(key=VIS, from_mode="visibility_only")], "full", by="a",
                            now=NOW).results
    assert r.status == "unknown"
    assert _rows(ctx)[0]["result"] == "unknown"
    assert sum(1 for c in responses.calls if c.request.method == "PUT") == 1  # sent once, never retried


def test_no_write_key_refuses_and_records(tmp_path):
    ctx = _ctx(tmp_path, write=False)
    with pytest.raises(fleet_write.NoWriteKey):
        fleet_write.apply(ctx, [EnforcementHost(key=VIS, from_mode="visibility_only")], "full", by="a", now=NOW)
    assert [(r["result"], r["detail"]) for r in _rows(ctx)] == [("refused", "no_write_key")]
    with pytest.raises(fleet_write.NoWriteKey):
        fleet_write.increase_rate(ctx, [VIS], by="a", now=NOW)


def test_bad_input(ctx):
    with pytest.raises(ValueError):
        fleet_write.apply(ctx, [EnforcementHost(key=VIS, from_mode="visibility_only")], "idle", by="a", now=NOW)
    with pytest.raises(ValueError):
        fleet_write.preview(ctx, ["not-a-host"], "full", now=NOW)
    with pytest.raises(ValueError):
        fleet_write.preview(ctx, [VIS] * 2 + [f"/orgs/1/workloads/x{i}" for i in range(60)], "full", now=NOW)


# ── traffic update rate ──────────────────────────────────────────────────────

@responses.activate
def test_increase_rate_one_call_for_the_batch_with_the_write_key(ctx):
    responses.add(responses.POST, f"{API}/orgs/1/workloads/set_flow_reporting_frequency", status=204)
    out = fleet_write.increase_rate(ctx, [VIS, IDLE, "ip:10.0.0.9"], by="admin", now=NOW)
    assert [(r.key, r.status) for r in out.results] == [("ip:10.0.0.9", "skipped"), (VIS, "ok"), (IDLE, "ok")]
    [call] = responses.calls
    assert json.loads(call.request.body) == {"workloads": [{"href": VIS}, {"href": IDLE}]} and _user(call) == "wk"
    assert out.until == NOW + timedelta(minutes=10)
    assert sorted(r["result"] for r in _rows(ctx) if r["action"] == "traffic_rate") == ["ok", "ok", "skipped"]


@responses.activate
def test_increase_rate_refused_says_so_for_every_host(ctx):
    responses.add(responses.POST, re.compile(r".*/set_flow_reporting_frequency"), status=406,
                  json=[{"token": "invalid_uri"}])
    out = fleet_write.increase_rate(ctx, [VIS, IDLE], by="admin", now=NOW)
    assert {r.status for r in out.results} == {"failed"} and out.until is None
    assert "406" in (out.results[0].detail or "")


@responses.activate
def test_history_reads_back_this_pce_newest_first(ctx):
    responses.add(responses.POST, re.compile(r".*/set_flow_reporting_frequency"), status=204)
    fleet_write.increase_rate(ctx, [VIS], by="admin", now=NOW)
    _live(VIS, "visibility_only")
    responses.add(responses.PUT, f"{API}{VIS}", status=204)
    fleet_write.apply(ctx, [EnforcementHost(key=VIS, from_mode="visibility_only")], "selective", by="admin", now=NOW)
    h = fleet_write.history(ctx)
    assert [(a.action, a.target_mode, a.result) for a in h] == [("enforcement", "selective", "ok"),
                                                                ("traffic_rate", None, "ok")]
