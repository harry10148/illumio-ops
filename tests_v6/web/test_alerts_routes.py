"""Alerts API: the list and detail of the current PCE's alerts, their evidence, notes and policy explanation."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.alerting import Confidence, Trigger
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.values import AlertRuleType, SegmentView, Severity
from illumio_ops.services.alerts import views
from illumio_ops.store import alerts as store

from .conftest import LOCAL, csrf, login, post

NOW = datetime.now(UTC).replace(microsecond=0)


def seed(ctx, *, pce_url=None, rule_type=AlertRuleType.SYSTEM, subject="disk_low", evidence=None, severity=Severity.HIGH,
         at=None):
    url = ctx.settings.current().pce.url if pce_url is None else pce_url
    t = Trigger(rule_id="a" * 32, rule_type=rule_type, subject_key=subject, severity=severity, first_seen=NOW,
                last_seen=NOW, late=False, message_key="alert_system_disk_low",
                params={"free": "1 GB", "warn": "10 GB"}, facts={"free_bytes": 1}, evidence=evidence,
                confidence=Confidence())
    with ctx.db() as conn:
        return store.insert_alert(conn, pce_url=url, org_id=ctx.settings.current().pce.org_id, rule_name="",
                                  pack_key="rule_system_disk_low", trigger=t, at=at or NOW, channels=["line"], hold=None)


def get(client, url):
    return client.get(url, environ_overrides=LOCAL)


def test_list_filters_and_pages(client, ctx):
    login(client)
    for i in range(3):
        seed(ctx, severity=Severity.HIGH if i else Severity.LOW, at=NOW - timedelta(minutes=i))
    seed(ctx, at=NOW - timedelta(days=40))  # outside the default 7 days
    data = get(client, "/api/alerts").get_json()["data"]
    assert data["total"] == 3 and len(data["items"]) == 3
    first = data["items"][0]
    assert first["rule_name"] == "Disk space low" and first["summary"].startswith("Disk space is low")
    assert first["deliveries"] == [{"channel": "line", "status": "pending", "attempts": 0, "last_error": None,
                                    "sent_at": None}]
    high = get(client, "/api/alerts?severity=high&days=7").get_json()["data"]
    assert high["total"] == 2
    month = get(client, "/api/alerts?days=90").get_json()["data"]
    assert month["total"] == 4


def test_get_other_pce_alert_404(client, ctx):
    login(client)
    other = seed(ctx, pce_url="https://other.example:8443")
    assert get(client, f"/api/alerts/{other}").status_code == 404
    mine = seed(ctx)
    d = get(client, f"/api/alerts/{mine}").get_json()["data"]
    assert d["id"] == mine and d["facts"] == {"free_bytes": 1} and d["notes"] == [] and d["evidence_kind"] is None


def test_evidence_limit_hit_reported(client, ctx, monkeypatch):
    from illumio_ops.domain.flows import normalize_flow
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows
    from tests_v6.services.collect.conftest import raw_flow
    login(client)
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(raw_flow(i, NOW - timedelta(minutes=5), NOW - timedelta(minutes=1)))
                            for i in range(3)], origin=DataOrigin.INGEST, now=NOW)
    seg = FlowSegment(filter=FilterSpec(start=NOW - timedelta(hours=1), end=NOW), view=SegmentView.DETAIL, limit=200)
    a = seed(ctx, rule_type=AlertRuleType.TRAFFIC, evidence=seg)
    monkeypatch.setattr(views, "EVIDENCE_LIMIT", 2)
    e = get(client, f"/api/alerts/{a}/evidence").get_json()["data"]
    assert e["kind"] == "flow" and len(e["rows"]) == 2 and e["limit_hit"] is True and "coverage" in e


def test_note_add_requires_body(client, ctx):
    login(client)
    a = seed(ctx)
    assert post(client, f"/api/alerts/{a}/notes", {"body": ""}).status_code == 400
    r = post(client, f"/api/alerts/{a}/notes", {"body": "NetBird on dev, known"})
    notes = r.get_json()["data"]["notes"]
    assert notes[0]["body"] == "NetBird on dev, known" and notes[0]["created_by"] == "illumio"


def test_explain_only_for_traffic_alerts(client, ctx, monkeypatch):
    from illumio_ops.services.analysis.explain import PolicyExplanation
    login(client)
    system = seed(ctx)
    body = {"src_href": None, "src_ip": "10.0.0.1", "dst_href": "/orgs/1/workloads/w", "dst_ip": "10.0.0.2", "port": 22,
            "proto": 6}
    assert post(client, f"/api/alerts/{system}/explain", body).status_code == 400
    seg = FlowSegment(filter=FilterSpec(start=NOW - timedelta(hours=1), end=NOW), view=SegmentView.DETAIL, limit=200)
    flow = seed(ctx, rule_type=AlertRuleType.TRAFFIC, evidence=seg)
    seen = []
    monkeypatch.setattr(views, "explain_flow", lambda ctx, src, dst, port, proto: seen.append((src, dst, port)) or
                        PolicyExplanation(basis="active", source="none", allow=[], deny=[], override_deny=[],
                                          pce_status=None, pce_error=None, unresolved=["10.0.0.1"], partial=False))
    r = post(client, f"/api/alerts/{flow}/explain", body)
    assert r.status_code == 200 and r.get_json()["data"]["unresolved"] == ["10.0.0.1"] and seen[0][2] == 22


def test_console_link_by_deployment(client, ctx):
    login(client)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(
        {"url": "https://pce.example:8443", "org_id": "1", "deployment_type": "on_prem"}))
    a = seed(ctx, subject="/orgs/1/workloads/0f6a3b2c-1111-2222-3333-444455556666")
    d = get(client, f"/api/alerts/{a}").get_json()["data"]
    assert d["console_link"] == "https://pce.example:8443"  # no undocumented deep link (P4 acceptance ruling)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update({"deployment_type": "saas"}))
    b = seed(ctx, subject="disk_low")
    assert get(client, f"/api/alerts/{b}").get_json()["data"]["console_link"] == "https://console.illum.io"


def test_alert_routes_need_csrf_and_login(client, ctx):
    a = seed(ctx)
    assert get(client, "/api/alerts").status_code == 401
    login(client)
    r = client.post(f"/api/alerts/{a}/notes", json={"body": "x"}, environ_overrides=LOCAL)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "csrf_error"
    assert csrf(client)
