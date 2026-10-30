"""The workbench's predicted-block view in a browser (P6e): asked for with a button, each flow with the rule that
would block it (named, never an href), and marked when the conditions changed since."""
from datetime import UTC, datetime

from playwright.sync_api import expect

from illumio_ops.domain.policy import ActorRef, RuleRef, ServiceRef
from illumio_ops.domain.values import RuleAction
from illumio_ops.services import workbench
from illumio_ops.services.analysis.predicted_block import PredictedBlock, PredictedRow
from illumio_ops.services.flowsource import FlowRow
from tests_v6.e2e.conftest import sign_in

DENY = "/orgs/1/sec_policy/draft/rule_sets/100/deny_rules/237"


def _flow():
    now = datetime.now(UTC)
    return FlowRow(
        record_key="r1", conn_key="c1", direction="inbound", src_ip="10.0.0.1", dst_ip="10.0.0.2",
        src_key="/orgs/1/workloads/a", dst_key="/orgs/1/workloads/b", src_href="/orgs/1/workloads/a",
        dst_href="/orgs/1/workloads/b", src_hostname="web-01", dst_hostname="db-01", src_managed=True,
        dst_managed=True, src_mode="selective", dst_mode="visibility_only", src_labels={}, dst_labels={}, port=3389,
        proto=6, initiator_process=None, initiator_user=None, service_process=None, service_user=None,
        windows_service=None, policy_decision="potentially_blocked", first_detected=now, last_detected=now,
        num_connections=4, bytes_in=None, bytes_out=None, state=None, origin="pce")


def _predicted(*a, **kw):
    rule = RuleRef(href=DENY, rule_type=RuleAction.OVERRIDE_DENY, enabled=True, ruleset_name="Quarantine",
                   ruleset_href="/orgs/1/sec_policy/draft/rule_sets/100", description="",
                   consumers=(ActorRef(kind="label", key="app", value="Jumpdesk", name=None, href="/orgs/1/labels/49"),),
                   providers=(ActorRef(kind="all_workloads", key=None, value=None, name=None, href=None),),
                   services=(ServiceRef(port=None, to_port=None, proto=None, name="All Services", href="/s/1"),))
    return PredictedBlock(rows=[PredictedRow(flow=_flow(), draft_decision="blocked_by_override_deny",
                                             blocking_rules=[DENY], allow_rules=[], essential_service_rules=[])],
                          rules={DENY: rule}, capped=False, limit_hit=False, computed_at=datetime.now(UTC),
                          unsupported=False, missing_rules=[])


def test_recompute_shows_the_blocking_rule(context, live_app, monkeypatch):
    monkeypatch.setattr(workbench, "predict_blocks", _predicted)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/investigate")
    panel = page.locator("[data-role=predicted]")
    expect(panel.locator("[data-role=pred-rows]")).to_have_count(0)  # nothing until asked
    panel.locator("[data-role=pred-run]").click()
    row = panel.locator("[data-role=pred-rows] tbody tr")
    expect(row).to_have_count(1)
    text = row.inner_text()
    assert "web-01" in text and "Quarantine" in text and "app=Jumpdesk" in text and "/orgs/" not in text
    assert "3389/TCP" in text  # the protocol by name (lab 2026-10-31: "59412/6")
    expect(panel.locator("[data-role=pred-stale]")).to_have_count(0)  # unchanged conditions are not "changed"
    page.locator("select[name=period]").select_option(index=1)  # the conditions change: another period
    expect(panel.locator("[data-role=pred-stale]")).to_have_count(1)


def test_unsupported_said(context, live_app, monkeypatch):
    def unsupported(*a, **kw):
        return PredictedBlock(rows=[], rules={}, capped=False, limit_hit=False, computed_at=datetime.now(UTC),
                              unsupported=True, missing_rules=[])
    monkeypatch.setattr(workbench, "predict_blocks", unsupported)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/investigate")
    page.locator("[data-role=pred-run]").click()
    expect(page.locator("[data-role=pred-unsupported]")).to_have_count(1)
    expect(page.locator("[data-role=predicted] .muted")).to_have_count(0)  # not "no flows"


def test_failure_said_in_the_panel(context, live_app, monkeypatch):
    from illumio_ops.pce.async_query import PceQueryError

    def boom(*a, **kw):
        raise PceQueryError("update_rules", 500, "boom")
    monkeypatch.setattr(workbench, "predict_blocks", boom)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/investigate")
    page.locator("[data-role=pred-run]").click()
    expect(page.locator("[data-role=predicted] .form-error")).to_have_count(1)
