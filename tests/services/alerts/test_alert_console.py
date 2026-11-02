"""The alerts home page's data (UI redesign spec §4.1, §5.1): categories, unprocessed alerts, the count strip, the
detail's timeline, what the vendor's tools cannot show, and who can be quarantined."""
import json
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.alerting import Confidence, Trigger
from illumio_ops.domain.values import AlertRuleType, Severity
from illumio_ops.services.alerts import views
from illumio_ops.services.alerts.views import AlertQuery
from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.analysis import DetectionWrite
from tests.services.collect.conftest import configured_ctx

NOW = datetime.now(UTC).replace(microsecond=0)
WEB = "/orgs/1/workloads/web"
IDLE = "/orgs/1/workloads/idle"
GONE = "/orgs/1/workloads/gone"


def _wl(href, hostname, mode):
    return workloads.WorkloadRow(
        href=href, hostname=hostname, name=None, managed=1, enforcement_mode=mode, visibility_level=None, os_id=None,
        ven_version=None, ven_href=None, label_set=None, online=1, risk_exposure=None, risk_percent=None,
        risk_updated_at=None, fetched_at="x")


def _ctx(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    c.settings.update(c.settings.current().revision, lambda d: d["display"].update(language="en"))
    with c.flows().connect() as conn:
        workloads.replace_inventory(conn, [_wl(WEB, "web-01", "selective"), _wl(IDLE, "idle-01", "idle")])
        conn.commit()
    return c


def _detection(ctx, subject, detector="fanout", *, summary=None, first=NOW - timedelta(minutes=30)) -> int:
    with ctx.flows().connect() as conn:
        analysis.upsert_detections(conn, [DetectionWrite(
            detector=detector, fingerprint=f"{detector}|{subject}", subject_key=subject, severity="high",
            first_seen=first, last_seen=first + timedelta(minutes=20), critical_asset=False,
            summary_json=json.dumps(summary or {"targets": 12, "window_minutes": 60}), segment_json="{}",
            confidence_json="{}")], dedup={detector: timedelta(hours=1)}, late=False, at=NOW)
        conn.commit()
        return int(conn.execute("SELECT id FROM detections WHERE fingerprint = ?",
                                (f"{detector}|{subject}",)).fetchone()[0])


def _alert(ctx, *, rule_type=AlertRuleType.SYSTEM, severity=Severity.HIGH, at=None, grouped=None, params=None,
           facts=None, subject="disk_low"):
    at = at or NOW
    t = Trigger(rule_id="r" * 32, rule_type=rule_type, subject_key=subject, severity=severity, first_seen=at,
                last_seen=at, late=False, message_key="alert_system_disk_low",
                params=params or {"free": "1 GB", "warn": "10 GB"}, facts=facts or {}, evidence=None,
                confidence=Confidence(), grouped_annotation=grouped)
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        return store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="", pack_key=None, trigger=t,
                                  at=at, channels=[], hold=None)


def _lateral(ctx, detector, *, det_id=None, summary=None, at=None):
    params = {**(summary or {}), "detector": detector, "host": "web-01"}
    subject = f"{detector}|x"
    if det_id:
        with ctx.flows().connect() as conn:
            subject = conn.execute("SELECT fingerprint FROM detections WHERE id = ?", (det_id,)).fetchone()[0]
    return _alert(ctx, rule_type=AlertRuleType.LATERAL, params=params, at=at,
                  facts={"detection_id": det_id} if det_id else {}, subject=subject)


def test_filter_by_category(tmp_path):
    ctx = _ctx(tmp_path)
    _lateral(ctx, "fanout")
    anomaly = _lateral(ctx, "direction_reversal")
    _alert(ctx)
    got = views.list_alerts(ctx, AlertQuery(category="anomaly"), now=NOW)
    assert [i.id for i in got.items] == [anomaly] and got.items[0].category == "anomaly"
    assert views.list_alerts(ctx, AlertQuery(category="lateral"), now=NOW).total == 1
    assert views.list_alerts(ctx, AlertQuery(category="system"), now=NOW).total == 1


def test_unprocessed_filter_excludes_grouped(tmp_path):
    ctx = _ctx(tmp_path)
    open_ = _alert(ctx)
    _alert(ctx, grouped=3)
    got = views.list_alerts(ctx, AlertQuery(unprocessed=True), now=NOW)
    assert [i.id for i in got.items] == [open_]


def test_counts_ignore_category_and_severity_filters(tmp_path):
    ctx = _ctx(tmp_path)
    _alert(ctx, severity=Severity.CRITICAL)
    _alert(ctx, severity=Severity.HIGH)
    _alert(ctx, severity=Severity.MEDIUM, grouped=1)
    _alert(ctx, severity=Severity.LOW, at=NOW - timedelta(days=9))  # outside the 7 days
    c = views.list_alerts(ctx, AlertQuery(category="event", severity=Severity.HIGH), now=NOW).counts
    assert (c.critical, c.high, c.medium, c.low, c.grouped) == (1, 1, 1, 0, 1)


def test_ends_from_params(tmp_path):
    ctx = _ctx(tmp_path)
    _lateral(ctx, "data_staging", summary={"sources": 6, "target": "file-03"})
    [item] = views.list_alerts(ctx, AlertQuery(), now=NOW).items
    assert (item.src, item.dst) == ("web-01", "file-03")


def test_detail_timeline_orders_by_time(tmp_path):
    ctx = _ctx(tmp_path)
    earlier = _detection(ctx, WEB, "blocked_surge", first=NOW - timedelta(hours=3))
    det = _detection(ctx, WEB, "fanout", first=NOW - timedelta(minutes=30))
    assert earlier != det
    alert = _lateral(ctx, "fanout", det_id=det, at=NOW)
    d = views.alert_detail(ctx, alert)
    assert d is not None
    kinds = [e.kind for e in d.timeline]
    assert kinds == ["detection", "detection", "alert"]
    assert [e.at for e in d.timeline] == sorted(e.at for e in d.timeline)
    assert "Blocked" in d.timeline[0].text or "blocked" in d.timeline[0].text.lower()


def test_detail_beyond_vendor_from_detection_summary(tmp_path):
    ctx = _ctx(tmp_path)
    alert = _lateral(ctx, "peer_deviation",
                     summary={"group": "app=pay", "group_size": 12, "starters": 1, "process": "psexesvc.exe"})
    d = views.alert_detail(ctx, alert)
    assert d is not None and len(d.beyond_vendor) == 2
    assert "app=pay" in d.beyond_vendor[0] and "psexesvc.exe" in d.beyond_vendor[1]
    assert all("{" not in s for s in d.beyond_vendor)
    plain = views.alert_detail(ctx, _alert(ctx))
    assert plain is not None and plain.beyond_vendor == []


def test_detail_quarantine_eligibility(tmp_path):
    ctx = _ctx(tmp_path)
    managed = views.alert_detail(ctx, _lateral(ctx, "fanout", det_id=_detection(ctx, WEB)))
    assert managed is not None and managed.quarantine.eligible and managed.quarantine.key == WEB
    idle = views.alert_detail(ctx, _lateral(ctx, "new_process", det_id=_detection(ctx, IDLE, "new_process")))
    assert idle is not None and idle.quarantine.eligible and idle.quarantine.no_enforcement
    unmanaged = views.alert_detail(ctx, _lateral(ctx, "cross_env", det_id=_detection(ctx, "ip:10.0.0.9", "cross_env")))
    assert unmanaged is not None and not unmanaged.quarantine.eligible
    assert unmanaged.quarantine.reason == "unmanaged"
    gone = views.alert_detail(ctx, _lateral(ctx, "pivot_chain", det_id=_detection(ctx, GONE, "pivot_chain")))
    assert gone is not None and gone.quarantine.reason == "not_in_inventory"
    account = views.alert_detail(ctx, _lateral(ctx, "account_fanout",
                                               det_id=_detection(ctx, "CORP\\svc", "account_fanout")))
    assert account is not None and account.quarantine.reason == "no_subject"
    system = views.alert_detail(ctx, _alert(ctx))
    assert system is not None and system.quarantine.reason == "no_subject" and not system.quarantine.eligible


def test_language_follows_settings(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["display"].update(language="zh_TW"))
    d = views.alert_detail(ctx, _lateral(ctx, "new_process", summary={"process": "x.exe"}))
    assert d is not None and d.beyond_vendor and "x.exe" in d.beyond_vendor[0]


# ── review fixes (Codex, plan A final review) ───────────────────────────────

def test_detail_ignores_a_reused_detection_id(tmp_path):
    """The flow store rebuilt after a PCE switch reuses detection ids: an old alert must not adopt another host's."""
    ctx = _ctx(tmp_path)
    other = _detection(ctx, IDLE, "fanout")
    alert = _alert(ctx, rule_type=AlertRuleType.LATERAL, params={"detector": "fanout", "host": "web-01"},
                   facts={"detection_id": other}, subject=f"fanout|{WEB}")  # the alert was about web, not idle
    d = views.alert_detail(ctx, alert)
    assert d is not None and d.quarantine.reason == "no_subject" and [e.kind for e in d.timeline] == ["alert"]


def test_timeline_finds_events_through_the_ven(tmp_path):
    from illumio_ops.domain.events import normalize_event
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.events import upsert_events
    ctx = _ctx(tmp_path)
    with ctx.flows().connect() as conn:
        rows = [w for w in workloads.all_workloads(conn)]
        workloads.replace_inventory(conn, [r if r.href != WEB else r.__class__(**{**r.__dict__, "ven_href": "/orgs/1/vens/v1"})
                                           for r in rows])
        upsert_events(conn, [normalize_event({
            "href": "/orgs/1/events/t1", "event_type": "agent.tampering", "status": "success", "severity": "warning",
            "timestamp": (NOW - timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "created_by": {"ven": {"href": "/orgs/1/vens/v1", "hostname": "web-01"}},
            "resource_changes": [], "notifications": []})], origin=DataOrigin.INGEST, now=NOW)
        conn.commit()
    det = _detection(ctx, WEB, "fanout")
    d = views.alert_detail(ctx, _lateral(ctx, "fanout", det_id=det, at=NOW))
    assert d is not None and "event" in [e.kind for e in d.timeline]
