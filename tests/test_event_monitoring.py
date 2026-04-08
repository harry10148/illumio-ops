import datetime
import json
from types import SimpleNamespace

from src.analyzer import Analyzer
from src.alerts.base import AlertOutputPlugin
from src.events import AlertThrottler, StatsTracker
from src.reporter import Reporter


class DummyReporter:
    def add_health_alert(self, alert):
        return None

    def add_event_alert(self, alert):
        return None

    def add_traffic_alert(self, alert):
        return None

    def add_metric_alert(self, alert):
        return None


def test_alert_throttler_blocks_after_limit():
    state = {}
    throttler = AlertThrottler(state)
    rule = {"id": 1, "name": "Burst auth failures", "throttle": "2/10m"}

    allowed_first, _ = throttler.allow(rule)
    allowed_second, _ = throttler.allow(rule)
    allowed_third, meta = throttler.allow(rule)

    assert allowed_first is True
    assert allowed_second is True
    assert allowed_third is False
    assert meta["throttle"] == "2/10m"
    assert state["throttle_state"]["1"]["throttle_suppressed"] == 1
    assert state["throttle_state"]["1"]["next_allowed_at"]


def test_stats_tracker_records_timeline_and_dispatch():
    state = {}
    tracker = StatsTracker(state)

    tracker.record_pce_success("events", message="fetched=3")
    tracker.record_rule_trigger({"id": 9, "name": "Policy audit", "type": "event"}, match_count=3)
    tracker.record_dispatch({"channel": "mail", "status": "success", "target": "ops@example.com"}, subject="test", counts={"events": 1})

    assert state["pce_stats"]["event_poll_status"] == "ok"
    assert state["dispatch_history"][-1]["channel"] == "mail"
    assert any(item["kind"] == "rule_trigger" for item in state["event_timeline"])


def test_analyzer_records_pce_error_and_suppression(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.analyzer.STATE_FILE", str(state_file))
    event_ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    event = {
        "href": "/orgs/1/events/auth-1",
        "event_type": "request.authentication_failed",
        "status": "failure",
        "severity": "err",
        "timestamp": event_ts,
    }

    class Api:
        def check_health(self):
            return 503, "cluster degraded"

        def fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
            return [event]

        def execute_traffic_query_stream(self, *args, **kwargs):
            return []

    rule = {
        "id": 1,
        "type": "event",
        "name": "Failed auth",
        "filter_value": "request.authentication_failed",
        "filter_status": "failure",
        "filter_severity": "err",
        "threshold_type": "count",
        "threshold_count": 1,
        "threshold_window": 10,
        "cooldown_minutes": 60,
    }
    health_rule = {
        "id": 2,
        "type": "system",
        "name": "PCE health",
        "filter_value": "pce_health",
        "cooldown_minutes": 30,
    }
    cm = SimpleNamespace(config={"rules": [rule, health_rule]})
    analyzer = Analyzer(cm, Api(), DummyReporter())
    recent = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
    analyzer.state["alert_history"]["1"] = recent.strftime("%Y-%m-%dT%H:%M:%SZ")

    analyzer.run_analysis()

    assert analyzer.state["pce_stats"]["health_status"] == "error"
    assert analyzer.state["pce_stats"]["last_error_stage"] == "health"
    assert analyzer.state["throttle_state"]["1"]["cooldown_suppressed"] >= 1
    assert any(item["kind"] == "suppressed" for item in analyzer.state["event_timeline"])


def test_reporter_persists_dispatch_history(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.reporter.STATE_FILE", str(state_file))

    cm = SimpleNamespace(
        config={
            "alerts": {"active": ["mail"]},
            "email": {"sender": "bot@example.com", "recipients": ["ops@example.com"]},
            "smtp": {},
            "settings": {"timezone": "UTC"},
        }
    )
    reporter = Reporter(cm)
    reporter.add_event_alert({"rule": "auth", "time": "2026-04-08 12:00:00", "desc": "failed auth", "severity": "err", "count": 1})

    class DummyMailPlugin:
        def send(self, reporter_obj, subj):
            return {"channel": "mail", "status": "success", "target": "ops@example.com"}

    monkeypatch.setattr(reporter, "_get_output_plugin", lambda name: DummyMailPlugin() if name == "mail" else None)

    results = reporter.send_alerts()
    state = json.loads(state_file.read_text(encoding="utf-8"))

    assert results[0]["status"] == "success"
    assert state["dispatch_history"][-1]["channel"] == "mail"
    assert state["dispatch_history"][-1]["status"] == "success"


def test_reporter_builds_vendor_event_payload():
    cm = SimpleNamespace(
        config={
            "api": {"url": "https://pce.example.com:8443/api/v2"},
            "alerts": {},
            "settings": {"timezone": "UTC"},
        }
    )
    reporter = Reporter(cm)
    raw_event = {
        "href": "/orgs/1/events/evt-1",
        "timestamp": "2026-04-08T12:00:00Z",
        "event_type": "sec_policy.create",
        "status": "success",
        "severity": "info",
        "created_by": {"user": {"username": "admin@example.com"}},
        "action": {
            "api_method": "POST",
            "api_endpoint": "/api/v2/orgs/1/sec_policy",
            "src_ip": "10.0.0.5",
            "http_status_code": 201,
        },
        "resource_changes": [{
            "change_type": "create",
            "resource": {"sec_policy": {"name": "policy-1", "href": "/orgs/1/sec_policy/1"}},
            "changes": {"enabled": {"before": False, "after": True}},
        }],
        "notifications": [{
            "notification_type": "email",
            "info": {"user": {"username": "ops@example.com"}},
        }],
    }
    payload = reporter._build_vendor_event_payloads([raw_event])[0]

    assert payload["event_type"] == "sec_policy.create"
    assert payload["created_by"] == "admin@example.com"
    assert payload["action"]["api_method"] == "POST"
    assert payload["action"]["src_ip"] == "10.0.0.5"
    assert payload["resource_changes_count"] == 1
    assert payload["resource_changes"][0]["resource_type"] == "sec_policy"
    assert payload["notifications_count"] == 1
    assert payload["notifications"][0]["notification_type"] == "email"
    assert payload["pce_link"] == "https://pce.example.com:8443/#/events/evt-1"


def test_send_webhook_includes_vendor_event_payloads(monkeypatch):
    captured = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return Response()

    cm = SimpleNamespace(
        config={
            "api": {"url": "https://pce.example.com:8443/api/v2"},
            "alerts": {"webhook_url": "https://hooks.example.com/alert"},
            "settings": {"timezone": "UTC"},
        }
    )
    reporter = Reporter(cm)
    reporter.add_event_alert({
        "time": "2026-04-08T12:00:00Z",
        "rule": "Policy Create",
        "desc": "policy created",
        "severity": "info",
        "count": 1,
        "raw_data": [{
            "href": "/orgs/1/events/evt-1",
            "timestamp": "2026-04-08T12:00:00Z",
            "event_type": "sec_policy.create",
            "status": "success",
            "severity": "info",
            "created_by": {"user": {"username": "admin@example.com"}},
            "action": {"api_method": "POST", "api_endpoint": "/api/v2/orgs/1/sec_policy"},
            "resource_changes": [],
            "notifications": [],
        }],
        "parsed_data": [],
    })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = reporter._send_webhook("subject")

    assert result["status"] == "success"
    assert captured["url"] == "https://hooks.example.com/alert"
    assert captured["body"]["content_model"] == "vendor_pretty_cool_events_baseline"
    assert captured["body"]["event_alert_payloads"][0]["events"][0]["event_type"] == "sec_policy.create"
    assert captured["body"]["event_alert_payloads"][0]["events"][0]["action"]["api_method"] == "POST"


def test_reporter_line_and_mail_templates_include_vendor_context():
    cm = SimpleNamespace(
        config={
            "api": {"url": "https://pce.example.com:8443/api/v2"},
            "alerts": {},
            "settings": {"timezone": "UTC"},
        }
    )
    reporter = Reporter(cm)
    reporter.add_event_alert({
        "time": "2026-04-08T12:00:00Z",
        "rule": "Policy Create",
        "desc": "policy created",
        "severity": "info",
        "count": 1,
        "source": "admin@example.com",
        "raw_data": [{
            "href": "/orgs/1/events/evt-1",
            "timestamp": "2026-04-08T12:00:00Z",
            "event_type": "sec_policy.create",
            "status": "success",
            "severity": "info",
            "created_by": {"user": {"username": "admin@example.com"}},
            "action": {
                "api_method": "POST",
                "api_endpoint": "/api/v2/orgs/1/sec_policy",
                "src_ip": "10.0.0.5",
            },
            "resource_changes": [],
            "notifications": [],
        }],
        "parsed_data": [],
    })

    line_message = reporter._build_line_message("subject")
    mail_html = reporter._build_mail_html("subject")

    assert "sec_policy.create" in line_message
    assert "10.0.0.5" in line_message
    assert "View on PCE" in mail_html
    assert "POST /api/v2/orgs/1/sec_policy" in mail_html


def test_reporter_dispatches_registered_plugins_without_hardcoded_channel_names():
    class DummyPlugin(AlertOutputPlugin):
        name = "dummy_test_plugin"

        def send(self, reporter, subject: str) -> dict:
            return {
                "channel": self.name,
                "status": "success",
                "target": "dummy-target",
                "error": "",
                "subject": subject,
            }

    cm = SimpleNamespace(
        config={
            "alerts": {"active": ["dummy_test_plugin"]},
            "settings": {"timezone": "UTC"},
        }
    )
    reporter = Reporter(cm)
    reporter.add_health_alert({"time": "2026-04-08 12:00:00", "status": "503", "details": "cluster degraded"})

    results = reporter.send_alerts(force_test=True)

    assert len(results) == 1
    assert results[0]["channel"] == "dummy_test_plugin"
    assert results[0]["status"] == "success"
