"""Quarantine service (P6d): which policy refers to each level (read key), the label put on or taken off with the
write key only, every attempt recorded, nothing shown as done that the PCE refused."""
import json
import re
from datetime import UTC, datetime

import pytest
import responses

from illumio_ops.services import quarantine
from illumio_ops.store.flowdb import labels as label_store
from illumio_ops.store.flowdb import workloads
from tests_v6.domain.test_quarantine import LAB_SET
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 31, 9, tzinfo=UTC)
API = "https://pce.example.com:8443/api/v2"
ORG = f"{API}/orgs/1"
WL = "/orgs/1/workloads/w1"
VIS = "/orgs/1/workloads/w2"
MILD, MOD, SEV = "/orgs/1/labels/232", "/orgs/1/labels/133", "/orgs/1/labels/134"
APP = {"href": "/orgs/1/labels/49", "key": "app", "value": "Jumpdesk"}
LABELS = [{"href": MILD, "key": "Quarantine", "value": "Mild", "usage": {"ruleset": False}},
          {"href": MOD, "key": "Quarantine", "value": "Moderate", "usage": {"ruleset": False}},
          {"href": SEV, "key": "Quarantine", "value": "Severe", "usage": {"ruleset": True}}]


def _wl(href, hostname, mode, label_set=None):
    return workloads.WorkloadRow(
        href=href, hostname=hostname, name=None, managed=1, enforcement_mode=mode, visibility_level=None, os_id=None,
        ven_version=None, ven_href=None, label_set=label_set, online=1, risk_exposure=None, risk_percent=None,
        risk_updated_at=None, fetched_at="x")


def _ctx(tmp_path, *, write=True):
    c = configured_ctx(tmp_path, mode="full")
    if write:
        c.settings.update(c.settings.current().revision,
                          lambda d: d["pce"].update(write_api_key="wk", write_api_secret="ws"))
    with c.flows().connect() as conn:
        quarantined = label_store.label_set_id(conn, (("Quarantine", "Mild"),))
        workloads.replace_inventory(conn, [_wl(WL, "web-01", "selective"), _wl(VIS, "vis-01", "visibility_only",
                                                                                quarantined)])
        conn.commit()
    return c


@pytest.fixture
def ctx(tmp_path):
    return _ctx(tmp_path)


def _policy(labels=LABELS, active=(LAB_SET,), draft=(LAB_SET,)):
    responses.add(responses.GET, re.compile(rf"{re.escape(ORG)}/labels\?.*key=Quarantine.*"), json=list(labels))
    for v, sets in (("active", active), ("draft", draft)):
        responses.add(responses.GET, re.compile(rf"{re.escape(ORG)}/sec_policy/{v}/rule_sets\?.*"), json=list(sets))
    responses.add(responses.GET, re.compile(rf"{re.escape(API)}/orgs/1/(labels/\d+|sec_policy/\w+/(ip_lists|services)/\d+)$"),
                  json={"name": "PrivateIP", "key": "app", "value": "Jumpdesk"})


def _auth_user(call):
    import base64
    return base64.b64decode(call.request.headers["Authorization"].split()[1]).decode().split(":")[0]


# ── check ────────────────────────────────────────────────────────────────────

@responses.activate
def test_check_levels(ctx):
    _policy()
    c = quarantine.check(ctx)
    assert c.write_key and c.labels == {"Mild": MILD, "Moderate": MOD, "Severe": SEV}
    assert {k: v.state for k, v in c.levels.items()} == {"Mild": "none", "Moderate": "none", "Severe": "active"}
    assert len(c.levels["Severe"].rules) == 2 and c.names  # the actors named for the page
    assert all(_auth_user(call) == "k" for call in responses.calls)  # reads on the main key


@responses.activate
def test_check_no_label_referred_to_reads_no_rule_sets(ctx):
    _policy(labels=[{**lb, "usage": {"ruleset": False}} for lb in LABELS])
    c = quarantine.check(ctx)
    assert {v.state for v in c.levels.values()} == {"none"}
    assert not any("rule_sets" in call.request.url for call in responses.calls)


@responses.activate
def test_check_draft_only(ctx):
    _policy(active=())
    assert quarantine.check(ctx).levels["Severe"].state == "draft_only"


# ── apply / remove ───────────────────────────────────────────────────────────

def _workload(href, labels):
    responses.add(responses.GET, f"{API}{href}", json={"href": href, "labels": labels})


@responses.activate
def test_apply_puts_only_the_quarantine_label_with_the_write_key(ctx):
    _policy()
    _workload(WL, [APP, {"href": MILD, "key": "Quarantine", "value": "Mild"}])
    responses.add(responses.PUT, f"{API}{WL}", status=204)
    out = quarantine.apply(ctx, [WL], "Severe", by="admin", acknowledge_no_policy=False, now=NOW)
    [r] = out.results
    assert (r.status, r.previous, r.name) == ("ok", "Mild", "web-01")
    put = next(c for c in responses.calls if c.request.method == "PUT")
    assert json.loads(put.request.body) == {"labels": [{"href": APP["href"]}, {"href": SEV}]}
    assert _auth_user(put) == "wk"
    get_wl = [c for c in responses.calls if c.request.method == "GET" and c.request.url.endswith(WL)]
    assert get_wl and _auth_user(get_wl[-1]) == "wk"  # read again right before the write
    [row] = quarantine.history(ctx, WL)
    assert (row.action, row.level, row.result, row.by) == ("apply", "Severe", "ok", "admin")
    assert row.original_labels == [{"href": APP["href"], "key": "app", "value": "Jumpdesk"},
                                   {"href": MILD, "key": "Quarantine", "value": "Mild"}]


@responses.activate
def test_refused_write_is_failed_and_recorded(ctx):
    _policy()
    _workload(WL, [APP])
    responses.add(responses.PUT, f"{API}{WL}", status=403, json={"error": "Access denied."})
    [r] = quarantine.apply(ctx, [WL], "Severe", by="admin", acknowledge_no_policy=False, now=NOW).results
    assert r.status == "failed" and "403" in (r.detail or "") and "Access denied" in (r.detail or "")
    [row] = quarantine.history(ctx, WL)
    assert row.result == "failed" and "403" in (row.detail or "")


@responses.activate
def test_no_policy_needs_acknowledging(ctx):
    _policy()
    with pytest.raises(quarantine.NoPolicy):
        quarantine.apply(ctx, [WL], "Mild", by="admin", acknowledge_no_policy=False, now=NOW)
    assert not any(c.request.method == "PUT" for c in responses.calls)
    _workload(WL, [APP])
    responses.add(responses.PUT, f"{API}{WL}", status=204)
    [r] = quarantine.apply(ctx, [WL], "Mild", by="admin", acknowledge_no_policy=True, now=NOW).results
    assert r.status == "ok"


def test_no_write_key(tmp_path):
    c = _ctx(tmp_path, write=False)
    with pytest.raises(quarantine.NoWriteKey):
        quarantine.apply(c, [WL], "Severe", by="admin", acknowledge_no_policy=True, now=NOW)
    with pytest.raises(quarantine.NoWriteKey):
        quarantine.remove(c, [WL], by="admin", now=NOW)


@responses.activate
def test_missing_label_created_first(ctx):
    _policy(labels=[lb for lb in LABELS if lb["value"] != "Mild"])
    responses.add(responses.POST, f"{ORG}/labels", status=201, json={"href": "/orgs/1/labels/900"})
    _workload(WL, [APP])
    responses.add(responses.PUT, f"{API}{WL}", status=204)
    out = quarantine.apply(ctx, [WL], "Mild", by="admin", acknowledge_no_policy=True, now=NOW)
    assert out.label_created and out.results[0].status == "ok"
    post = next(c for c in responses.calls if c.request.method == "POST")
    assert json.loads(post.request.body) == {"key": "Quarantine", "value": "Mild"} and _auth_user(post) == "wk"


@responses.activate
def test_label_cannot_be_created(ctx):
    _policy(labels=[lb for lb in LABELS if lb["value"] != "Mild"])
    responses.add(responses.POST, f"{ORG}/labels", status=406, json=[{"token": "invalid_label_key"}])
    out = quarantine.apply(ctx, [WL], "Mild", by="admin", acknowledge_no_policy=True, now=NOW)
    assert out.label_error and "406" in out.label_error
    assert [r.status for r in out.results] == ["failed"]
    assert not any(c.request.method == "PUT" for c in responses.calls)
    assert quarantine.history(ctx, WL)[0].result == "failed"


@responses.activate
def test_unmanaged_and_unknown_skipped(ctx):
    _policy()
    out = quarantine.apply(ctx, ["ip:10.0.0.9", "/orgs/1/workloads/gone"], "Severe", by="admin",
                           acknowledge_no_policy=False, now=NOW)
    assert [(r.status, r.detail) for r in out.results] == [("skipped", "unmanaged"), ("skipped", "not_in_inventory")]
    assert not any(c.request.method == "PUT" for c in responses.calls)


@responses.activate
def test_remove_takes_off_only_the_quarantine_label(ctx):
    _policy()
    _workload(WL, [APP, {"href": SEV, "key": "Quarantine", "value": "Severe"}])
    _workload(VIS, [APP])  # not quarantined on the PCE (any more)
    responses.add(responses.PUT, f"{API}{WL}", status=204)
    out = quarantine.remove(ctx, [WL, VIS], by="admin", now=NOW)
    assert [(r.key, r.status, r.previous) for r in out.results] == [(WL, "ok", "Severe"), (VIS, "not_quarantined", None)]
    [put] = [c for c in responses.calls if c.request.method == "PUT"]
    assert put.request.url.endswith(WL) and json.loads(put.request.body) == {"labels": [{"href": APP["href"]}]}


def test_batch_limit_and_level_checked(ctx):
    with pytest.raises(ValueError):
        quarantine.apply(ctx, [WL] * 51, "Severe", by="a", acknowledge_no_policy=True, now=NOW)
    with pytest.raises(ValueError):
        quarantine.apply(ctx, [WL], "Extreme", by="a", acknowledge_no_policy=True, now=NOW)


# ── preview ──────────────────────────────────────────────────────────────────

@responses.activate
def test_preview_targets_and_both_directions(ctx, monkeypatch):
    _policy()
    seen = []
    monkeypatch.setattr(quarantine, "_simulate", lambda c, p, at: seen.append(p))
    p = quarantine.preview(ctx, [WL, VIS, "ip:10.0.0.9"], "Severe", now=NOW)
    assert [(t.key, t.ok, t.no_enforcement, t.current) for t in p.targets] == [
        (WL, True, False, None), (VIS, True, True, "Mild"), ("ip:10.0.0.9", False, False, None)]
    into, out = seen
    assert into.dst.hrefs == (WL, VIS) and into.src.is_empty() and out.src.hrefs == (WL, VIS) and out.dst.is_empty()


def test_preview_simulates_the_last_week(ctx, monkeypatch):
    seen = {}
    monkeypatch.setattr(quarantine, "simulate_deny", lambda c, p, **kw: seen.update(kw) or None)
    monkeypatch.setattr(quarantine, "_named", lambda c, sim, pull: None)
    from illumio_ops.domain.deny import DenyProposal
    from illumio_ops.domain.filter import EndpointFilter
    quarantine._simulate(ctx, DenyProposal(src=EndpointFilter(), dst=EndpointFilter(hrefs=(WL,))), NOW)
    assert seen["window"] == (NOW - quarantine.PREVIEW, NOW) and seen["edges"] == []


@responses.activate
def test_secrets_never_recorded(ctx):
    _policy()
    _workload(WL, [APP])
    responses.add(responses.PUT, f"{API}{WL}", status=204)
    quarantine.apply(ctx, [WL], "Severe", by="admin", acknowledge_no_policy=False, now=NOW)
    with ctx.db() as conn:
        dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM quarantine_actions")])
    assert "wk" not in dump.replace("workloads", "") and "ws" not in dump


# ── final review (2026-10-31) ─────────────────────────────────────────────────

@responses.activate
def test_switch_mid_batch_stops_and_records_under_the_pce_written(ctx):
    """#1: the PCE changed while a batch ran: the rest are not written (their hrefs belong to the previous PCE)."""
    from illumio_ops.store.flowdb import workloads as wls
    with ctx.flows().connect() as conn:
        wls.replace_inventory(conn, [_wl(WL, "web-01", "selective"), _wl("/orgs/1/workloads/w3", "web-03", "selective")])
        conn.commit()
    _policy()
    _workload(WL, [APP])
    _workload("/orgs/1/workloads/w3", [APP])

    def switch(request):
        ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://pce-b.example:8443"))
        return (204, {}, "")
    responses.add_callback(responses.PUT, f"{API}{WL}", callback=switch)
    out = quarantine.apply(ctx, [WL, "/orgs/1/workloads/w3"], "Severe", by="a", acknowledge_no_policy=False, now=NOW)
    assert [(r.status, r.detail) for r in out.results] == [("ok", None), ("failed", "pce_changed")]
    assert sum(1 for c in responses.calls if c.request.method == "PUT") == 1
    with ctx.db() as conn:
        urls = {r["pce_url"] for r in conn.execute("SELECT pce_url FROM quarantine_actions")}
    assert urls == {"https://pce.example.com:8443"}


@responses.activate
def test_write_is_never_retried_blindly(ctx, monkeypatch):
    """#2: a retried PUT resends labels read before someone else changed them: the write goes out once."""
    from illumio_ops.pce.client import PceClient
    sent = []
    real = PceClient.request

    def spy(self, method, path, **kw):
        if method == "PUT":
            sent.append(kw.get("bounded"))
        return real(self, method, path, **kw)
    monkeypatch.setattr(PceClient, "request", spy)
    _policy()
    _workload(WL, [APP])
    responses.add(responses.PUT, f"{API}{WL}", status=204)
    quarantine.apply(ctx, [WL], "Severe", by="a", acknowledge_no_policy=False, now=NOW)
    assert sent == [True]


@responses.activate
def test_write_timeout_is_unknown_and_recorded(ctx):
    """#3: the PCE may have applied a write whose answer never came: said, recorded, the batch goes on."""
    import requests

    from illumio_ops.store.flowdb import workloads as wls
    with ctx.flows().connect() as conn:
        wls.replace_inventory(conn, [_wl(WL, "web-01", "selective"), _wl("/orgs/1/workloads/w3", "web-03", "selective")])
        conn.commit()
    _policy()
    _workload(WL, [APP])
    _workload("/orgs/1/workloads/w3", [APP])
    responses.add(responses.PUT, f"{API}{WL}", body=requests.exceptions.ReadTimeout("read timed out"))
    responses.add(responses.PUT, f"{API}/orgs/1/workloads/w3", status=204)
    out = quarantine.apply(ctx, [WL, "/orgs/1/workloads/w3"], "Severe", by="a", acknowledge_no_policy=False, now=NOW)
    assert [r.status for r in out.results] == ["unknown", "ok"]
    assert quarantine.history(ctx, WL)[0].result == "unknown"


@responses.activate
def test_other_quarantine_values_recognised(ctx):
    """#5: a Quarantine label of another value (href only on the workload) is a quarantine, and removed."""
    legacy = {"href": "/orgs/1/labels/77", "key": "Quarantine", "value": "Legacy", "usage": {"ruleset": False}}
    _policy(labels=[*LABELS, legacy])
    _workload(WL, [APP, {"href": "/orgs/1/labels/77"}])
    responses.add(responses.PUT, f"{API}{WL}", status=204)
    [r] = quarantine.remove(ctx, [WL], by="a", now=NOW).results
    assert (r.status, r.previous) == ("ok", "Legacy")
    put = next(c for c in responses.calls if c.request.method == "PUT")
    assert json.loads(put.request.body) == {"labels": [{"href": APP["href"]}]}


@responses.activate
def test_refusals_recorded(ctx, tmp_path):
    """#7: a request refused before writing (no policy acknowledged, no write key) is recorded too."""
    _policy()
    with pytest.raises(quarantine.NoPolicy):
        quarantine.apply(ctx, [WL], "Mild", by="a", acknowledge_no_policy=False, now=NOW)
    [row] = quarantine.history(ctx, WL)
    assert (row.result, row.detail) == ("refused", "no_policy")
    c = _ctx(tmp_path / "nokey", write=False)
    with pytest.raises(quarantine.NoWriteKey):
        quarantine.remove(c, [WL], by="a", now=NOW)
    assert quarantine.history(c, WL)[0].detail == "no_write_key"
