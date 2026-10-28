"""The audit report (P5b-2 Task 3): what happened on the PCE — attention items by risk, users and failed sign-ins,
policy provisions, agent security events and brute force — from the events the product collected."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.events import normalize_event
from illumio_ops.domain.report import BarBlock, TableBlock, TextBlock
from illumio_ops.domain.values import (
    DataOrigin,
    IngestSource,
    Language,
    ReportType,
    Severity,
)
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.events import upsert_events
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
_n = iter(range(1, 1_000_000))


def event(event_type, at, *, user=None, system=False, ip=None, status="success", extra=None):
    i = next(_n)
    raw = {"href": f"/orgs/1/events/e{i}", "event_type": event_type, "timestamp": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "severity": "info", "status": status,
           "created_by": {"system": {}} if system else {"user": {"href": f"/users/{user}", "username": user}}}
    if ip:
        raw["action"] = {"src_ip": ip, "api_method": "POST", "api_endpoint": "/login"}
    raw.update(extra or {})
    return normalize_event(raw)


def _write(ctx, records):
    with ctx.flows().connect() as conn:
        upsert_events(conn, records, origin=DataOrigin.INGEST, now=NOW)
        conn.commit()


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.AUDIT].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.AUDIT), start=START, end=END, lang=lang, tz=UTC, now=NOW,
        pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _tables(doc, sid):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)]


def _kpi(doc):
    return {k.key: k.value for k in doc.kpis}


D = datetime(2026, 10, 22, 3, tzinfo=UTC)


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_kpis_and_attention(ctx):
    _write(ctx, [event("agent.tampering", D, system=True), event("sec_policy.create", D, user="alice"),
                 event("sec_policy.create", D, user="bob"), event("rule_set.update", D, user="alice"),
                 event("request.authentication_failed", D, user="eve", ip="10.1.1.1", status="failure"),
                 event("request.authorization_failed", D, user="eve", ip="10.1.1.1", status="failure"),
                 event("user.sign_in", D, user="alice")])
    doc = _build(ctx)
    k = _kpi(doc)
    assert (k["total"], k["high_risk"], k["auth_failed"], k["authz_denied"], k["policy_provisions"],
            k["draft_changes"], k["agent_security"], k["actors"], k["source_ips"]) == (7, 2, 1, 1, 2, 1, 1, 3, 1)
    attention = {r[0]: r for r in _tables(doc, "attention")[0].rows}
    assert attention["agent.tampering"][1] == "Critical" and attention["sec_policy.create"][2] == 2
    assert "user.sign_in" not in attention
    assert doc.findings[0].severity is Severity.CRITICAL


def test_system_actor_not_correlated(ctx):
    _write(ctx, [event("sec_policy.create", D, system=True), event("rule_set.update", D, system=True),
                 event("sec_policy.create", D, user="alice")])
    doc = _build(ctx)
    assert _kpi(doc)["actors"] == 1
    assert [r[0] for r in _tables(doc, "users")[0].rows] == ["alice"]


def test_brute_force_same_ip_30min(ctx):
    fails = [event("request.authentication_failed", D + timedelta(minutes=5 * i), user="x", ip="10.9.9.9",
                   status="failure") for i in range(5)]
    spread = [event("request.authentication_failed", D + timedelta(hours=i), user="y", ip="10.8.8.8",
                    status="failure") for i in range(5)]
    _write(ctx, fails + spread)
    rows = _tables(_build(ctx), "brute_force")[0].rows
    assert [r[0] for r in rows] == ["10.9.9.9"] and rows[0][1] == 5


def test_policy_provisions_list(ctx):
    _write(ctx, [event("sec_policy.create", D, user="alice", extra={"resource_changes": [{"resource": {"sec_policy": {
        "href": "/orgs/1/sec_policy/12", "commit_message": "open db", "workloads_affected": 64}}}]})])
    row = _tables(_build(ctx), "policy")[0].rows[0]
    assert row[1:] == ("alice", 64, "open db")


def test_trend_has_values(ctx):
    _write(ctx, [event("user.sign_in", D, user="a"), event("user.sign_in", D + timedelta(days=1), user="a")])
    bars = next(b for b in _section(_build(ctx), "types").blocks if isinstance(b, BarBlock))
    assert len(bars.points) == 7 and sum(v or 0 for _, v in bars.points) == 2


def test_no_events_says_so(ctx):
    doc = _build(ctx)
    assert all(k.value is None and k.note for k in doc.kpis)
    text = " ".join(p for s in doc.sections for b in s.blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert "no events" in (text + " ".join(t.empty_text for s in doc.sections for t in _tables(doc, s.id))).lower()


def test_previous_period_only_when_collected(ctx):
    _write(ctx, [event("user.sign_in", D, user="a")])
    assert all(k.previous is None for k in _build(ctx).kpis)
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.EVENTS, START - (END - START), END)
        conn.commit()
    assert {k.key: k.previous for k in _build(ctx).kpis}["total"] == 0


def test_all_kpis_rendered(ctx):
    _write(ctx, [event("user.sign_in", D, user="a")])
    doc = _build(ctx)
    html = render_html(doc, tz=UTC)
    assert len(doc.kpis) >= 9 and all(k.label in html for k in doc.kpis)


def test_zh_tw_builds(ctx):
    _write(ctx, [event("agent.tampering", D, system=True)])
    assert _build(ctx, Language.ZH_TW).title
