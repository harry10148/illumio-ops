"""Rule Hit Count (spec §6.5 RHC, P5c-2): is it on, turn it on (on-prem; SaaS says the PCE refuses), pull the PCE's
own report. Ported from 5.x rule_hit_count_enablement / reports (lab-verified 2026-07-11)."""
import json
from datetime import UTC, datetime

import pytest
import responses

from illumio_ops.domain.values import RhcState
from illumio_ops.services import rhc
from tests_v6.services.collect.conftest import configured_ctx

pytestmark = pytest.mark.real_rhc

ORG = "https://pce.example.com:8443/api/v2/orgs/1"
TPL = f"{ORG}/report_templates/rule_hit_count_report"
ACTIVE_FW = f"{ORG}/sec_policy/active/firewall_settings"
DRAFT_FW = f"{ORG}/sec_policy/draft/firewall_settings"
START, END = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC)
REPORT = "/orgs/1/reports/abc"


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


@pytest.fixture
def wctx(tmp_path):
    c = configured_ctx(tmp_path)
    c.settings.update(c.settings.current().revision,
                      lambda d: d["pce"].update(write_api_key="wk", write_api_secret="ws"))
    return c


def _saas(c):
    c.settings.update(c.settings.current().revision, lambda d: d["pce"].update(deployment_type="saas"))
    return c


def _auth_user(call):
    import base64
    return base64.b64decode(call.request.headers["Authorization"].split()[1]).decode().split(":")[0]


# ── status ───────────────────────────────────────────────────────────────────

@responses.activate
@pytest.mark.parametrize(("tpl_on", "scopes", "state"), [
    (True, [[]], RhcState.ENABLED), (False, [], RhcState.DISABLED),
    (True, [], RhcState.PARTIAL), (False, [[]], RhcState.PARTIAL)])
def test_status_states(wctx, tpl_on, scopes, state):
    responses.add(responses.GET, TPL, json={"enabled": tpl_on})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": scopes})
    s = rhc.rhc_status(wctx)
    assert s.state is state and s.pce_report is tpl_on and s.ven_scopes is bool(scopes)
    assert (s.reason_key is None) == (state is not RhcState.PARTIAL)


@responses.activate
def test_status_unsupported_on_404(wctx):
    responses.add(responses.GET, TPL, status=404, json={})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": []})
    s = rhc.rhc_status(wctx)
    assert s.state is RhcState.UNSUPPORTED and s.reason_key == "rhc_reason_unsupported"


@responses.activate
def test_status_read_key_cannot_read_template(ctx):
    """Only the Owner role reads the template: with the read key alone the answer is unknown, and says why."""
    responses.add(responses.GET, TPL, status=403, json={})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": [[]]})
    s = rhc.rhc_status(ctx)
    assert s.state is RhcState.UNKNOWN and s.reason_key == "rhc_reason_needs_write_key"
    assert s.ven_scopes is True and s.pce_report is None and not s.write_key


@responses.activate
def test_status_uses_write_key_when_saved(wctx):
    responses.add(responses.GET, TPL, json={"enabled": True})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": [[]]})
    rhc.rhc_status(wctx)
    assert {_auth_user(c) for c in responses.calls} == {"wk"}


@responses.activate
def test_status_unreachable_is_unknown(wctx):
    responses.add(responses.GET, TPL, body=ConnectionError("down"))
    s = rhc.rhc_status(wctx)
    assert s.state is RhcState.UNKNOWN and s.reason_key == "rhc_reason_unreachable"


def test_status_not_configured(tmp_path):
    from tests_v6.web.conftest import make_ctx
    assert rhc.rhc_status(make_ctx(tmp_path)).reason_key == "rhc_reason_not_configured"


# ── enable ───────────────────────────────────────────────────────────────────

def _off(draft=None):
    responses.add(responses.GET, TPL, json={"enabled": False})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": []})
    responses.add(responses.GET, DRAFT_FW, json=draft if draft is not None else
                  {"href": "/orgs/1/sec_policy/draft/firewall_settings", "rule_hit_count_enabled_scopes": []})


@responses.activate
def test_enable_three_steps(wctx):
    _off()
    responses.add(responses.PUT, TPL, status=204)
    responses.add(responses.PUT, DRAFT_FW, status=204)
    responses.add(responses.POST, f"{ORG}/sec_policy", status=201, json={})
    r = rhc.enable_rhc(wctx)
    assert r.ok and r.steps_done == ["pce_report_template", "ven_firewall_settings_draft", "provisioned"]
    puts = [c for c in responses.calls if c.request.method in ("PUT", "POST")]
    assert json.loads(puts[0].request.body) == {"enabled": True}
    assert json.loads(puts[1].request.body) == {"rule_hit_count_enabled_scopes": [[]]}
    assert json.loads(puts[2].request.body)["change_subset"] == {
        "firewall_settings": [{"href": "/orgs/1/sec_policy/draft/firewall_settings"}]}
    assert {_auth_user(c) for c in responses.calls} == {"wk"}


@responses.activate
def test_enable_skips_what_is_already_on(wctx):
    responses.add(responses.GET, TPL, json={"enabled": True})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": []})
    responses.add(responses.GET, DRAFT_FW, json={"rule_hit_count_enabled_scopes": []})
    responses.add(responses.PUT, DRAFT_FW, status=204)
    responses.add(responses.POST, f"{ORG}/sec_policy", status=201, json={})
    r = rhc.enable_rhc(wctx)
    assert r.ok and r.steps_done == ["ven_firewall_settings_draft", "provisioned"] and r.skipped == ["pce_report_template"]


@responses.activate
def test_pending_firewall_settings_refused(wctx):
    """Provisioning firewall_settings ships the whole draft: someone's unreviewed edits would go to every VEN.
    Refused before anything is written."""
    _off(draft={"rule_hit_count_enabled_scopes": [], "update_type": "update"})
    r = rhc.enable_rhc(wctx)
    assert not r.ok and r.error_key == "rhc_err_pending_firewall" and r.steps_done == []
    assert all(c.request.method == "GET" for c in responses.calls)


@responses.activate
def test_step_failure_stops_and_lists_done(wctx):
    _off()
    responses.add(responses.PUT, TPL, status=204)
    responses.add(responses.PUT, DRAFT_FW, status=500, json={})
    r = rhc.enable_rhc(wctx)
    assert not r.ok and r.steps_done == ["pce_report_template"] and r.error_key == "rhc_err_step_failed"
    assert not any(c.request.method == "POST" for c in responses.calls)


@responses.activate
def test_saas_refused_says_support(wctx):
    _saas(wctx)
    _off()
    responses.add(responses.PUT, TPL, status=403, json={"error": "Access denied."})
    r = rhc.enable_rhc(wctx)
    assert not r.ok and r.error_key == "rhc_err_refused_saas" and r.steps_done == []
    assert sum(c.request.method == "PUT" for c in responses.calls) == 1  # no retry


@responses.activate
def test_on_prem_refused_says_owner(wctx):
    _off()
    responses.add(responses.PUT, TPL, status=403, json={})
    assert rhc.enable_rhc(wctx).error_key == "rhc_err_refused"


def test_enable_needs_write_key(ctx):
    r = rhc.enable_rhc(ctx)
    assert not r.ok and r.error_key == "rhc_err_no_write_key"


@responses.activate
def test_enable_unsupported(wctx):
    responses.add(responses.GET, TPL, status=404, json={})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": []})
    r = rhc.enable_rhc(wctx)
    assert not r.ok and r.error_key == "rhc_err_unsupported"


@responses.activate
def test_enable_already_on_does_nothing(wctx):
    responses.add(responses.GET, TPL, json={"enabled": True})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": [[]]})
    r = rhc.enable_rhc(wctx)
    assert r.ok and r.steps_done == [] and len(r.skipped) == 3


# ── pull ─────────────────────────────────────────────────────────────────────

CSV = ("﻿Rule HREF,Rule Set Name,Rule Description,Rule Hit Count,Timestamp of Last Hit,Days Since Last Hit\n"
       "/orgs/1/sec_policy/active/rule_sets/1/sec_rules/10,Web,allow web,42,2026-10-29T10:00:00Z,1\n"
       "/orgs/1/sec_policy/active/rule_sets/1/sec_rules/11,Web,,0,,\n"
       "/orgs/1/sec_policy/active/rule_sets/1/sec_rules/12,Web,,n/a,,\n"
       "/orgs/1/sec_policy/active/rule_sets/1/sec_rules/13,Web,,,,\n")


def _report(status="done", csv=CSV):
    responses.add(responses.POST, f"{ORG}/reports", status=201, json={"href": REPORT})
    responses.add(responses.GET, f"https://pce.example.com:8443/api/v2{REPORT}", json={"status": status})
    responses.add(responses.GET, f"https://pce.example.com:8443/api/v2{REPORT}/download", body=csv.encode())


@responses.activate
def test_pull_sends_full_iso_timestamps(wctx, monkeypatch):
    """A bare date gets 406 (lab 25.2.40)."""
    monkeypatch.setattr(rhc, "_sleep", lambda s: None)
    _report()
    rhc.pull_rhc(wctx, START, END)
    body = json.loads(responses.calls[0].request.body)
    assert body["report_parameters"]["report_time_range"] == {"start_date": "2026-10-01T00:00:00Z",
                                                               "end_date": "2026-10-30T00:00:00Z"}
    assert body["report_template"] == {"href": "/orgs/1/report_templates/rule_hit_count_report"}
    assert body["report_format"] == "csv" and _auth_user(responses.calls[0]) == "wk"


@responses.activate
def test_csv_parsed_unparsable_skipped_and_counted(wctx, monkeypatch):
    monkeypatch.setattr(rhc, "_sleep", lambda s: None)
    _report()
    p = rhc.pull_rhc(wctx, START, END)
    assert [(r.rule_href.rsplit("/", 1)[-1], r.hit_count) for r in p.rows] == [("10", 42), ("11", 0)]
    assert p.rows[0].ruleset_name == "Web" and p.rows[0].last_hit_at == "2026-10-29T10:00:00Z"
    assert p.rows[1].last_hit_at is None and p.unparsed == 2


@responses.activate
def test_csv_missing_columns(wctx, monkeypatch):
    monkeypatch.setattr(rhc, "_sleep", lambda s: None)
    _report(csv="Name,Count\nx,1\n")
    with pytest.raises(rhc.RhcPullError) as e:
        rhc.pull_rhc(wctx, START, END)
    assert e.value.key == "rhc_err_csv_columns"


@responses.activate
def test_pull_poll_timeout(wctx, monkeypatch):
    monkeypatch.setattr(rhc, "_sleep", lambda s: None)
    _report(status="pending")
    with pytest.raises(rhc.RhcPullError) as e:
        rhc.pull_rhc(wctx, START, END, timeout_seconds=0)
    assert e.value.key == "rhc_err_pull_timeout"


@responses.activate
def test_pull_pce_failed(wctx, monkeypatch):
    monkeypatch.setattr(rhc, "_sleep", lambda s: None)
    _report(status="failed")
    with pytest.raises(rhc.RhcPullError) as e:
        rhc.pull_rhc(wctx, START, END)
    assert e.value.key == "rhc_err_pull_failed"


@responses.activate
def test_pull_download_failure(wctx, monkeypatch):
    monkeypatch.setattr(rhc, "_sleep", lambda s: None)
    responses.add(responses.POST, f"{ORG}/reports", status=201, json={"href": REPORT})
    responses.add(responses.GET, f"https://pce.example.com:8443/api/v2{REPORT}", json={"status": "done"})
    responses.add(responses.GET, f"https://pce.example.com:8443/api/v2{REPORT}/download", status=404, body=b"")
    with pytest.raises(rhc.RhcPullError) as e:
        rhc.pull_rhc(wctx, START, END)
    assert e.value.key == "rhc_err_pull_download"


@responses.activate
def test_pull_refused(ctx):
    """The read key cannot produce PCE reports (403): said, with the reason."""
    responses.add(responses.POST, f"{ORG}/reports", status=403,
                  json={"error": "report template type rule_hit_count_report not enabled"})
    with pytest.raises(rhc.RhcPullError) as e:
        rhc.pull_rhc(ctx, START, END)
    assert e.value.key == "rhc_err_pull_refused" and "not enabled" in (e.value.detail or "")


@responses.activate
def test_cached_status_reuses_a_recent_check(wctx):
    """The report catalog asks on every load; the PCE is asked at most once per STATUS_CACHE_SECONDS, and an
    explicit check (rhc_status) refreshes it."""
    responses.add(responses.GET, TPL, json={"enabled": True})
    responses.add(responses.GET, ACTIVE_FW, json={"rule_hit_count_enabled_scopes": [[]]})
    rhc.forget_status()
    assert rhc.cached_status(wctx).state is RhcState.ENABLED
    assert rhc.cached_status(wctx).state is RhcState.ENABLED
    assert len(responses.calls) == 2
    rhc.rhc_status(wctx)
    assert len(responses.calls) == 4


def test_csv_na_last_hit_is_none():
    """Lab 2026-10-30: the PCE writes "N/A" for a rule never hit."""
    rows, _ = rhc.parse_rhc_csv("Rule HREF,Rule Hit Count,Timestamp of Last Hit\n/orgs/1/x/1,0,N/A\n")
    assert rows[0].last_hit_at is None
