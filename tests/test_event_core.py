import datetime
import io
from contextlib import redirect_stdout
from types import SimpleNamespace

from src.analyzer import Analyzer
from src.api_client import EventFetchError
from src.config import ConfigManager
from src.events import EventPoller, matches_event_rule, normalize_event, parse_event_timestamp
from src.settings import FULL_EVENT_CATALOG


class DummyReporter:
    def add_health_alert(self, alert):
        return None

    def add_event_alert(self, alert):
        return None

    def add_traffic_alert(self, alert):
        return None

    def add_metric_alert(self, alert):
        return None


def test_matches_event_rule_supports_nested_fields():
    rule = {
        "type": "event",
        "filter_value": "user.login,request.authentication_failed",
        "filter_status": "*",
        "filter_severity": "err|warning",
        "match_fields": {
            "created_by.user.username": "admin@.*",
        },
    }
    event = {
        "event_type": "request.authentication_failed",
        "status": "failure",
        "severity": "err",
        "created_by": {"user": {"username": "admin@illumio.local"}},
    }

    assert matches_event_rule(rule, event) is True


def test_matches_event_rule_treats_literal_dots_as_exact_values():
    rule = {
        "type": "event",
        "filter_value": "request.authentication_failed",
        "filter_status": "failure",
        "filter_severity": "err",
        "match_fields": {
            "created_by.user.username": "admin@example.com",
        },
    }
    event = {
        "event_type": "requestXauthentication_failed",
        "status": "failure",
        "severity": "err",
        "created_by": {"user": {"username": "admin@exampleXcom"}},
    }

    assert matches_event_rule(rule, event) is False


def test_event_poller_dedups_overlap_and_does_not_regress_watermark():
    class FakeApi:
        def fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
            return [
                {
                    "href": "/orgs/1/events/1",
                    "event_type": "user.login",
                    "timestamp": "2026-04-08T00:00:00Z",
                }
            ]

    poller = EventPoller(FakeApi(), overlap_seconds=60)
    watermark = "2026-04-08T00:05:00Z"
    batch = poller.fetch_batch(
        watermark=watermark,
        seen_events={"/orgs/1/events/1": "2026-04-08T00:00:00Z"},
    )

    assert batch.events == []
    assert parse_event_timestamp(batch.next_watermark) >= parse_event_timestamp(watermark)


def test_normalize_event_prefers_vendor_action_fields_and_resource_changes():
    event = {
        "href": "/orgs/1/events/sample-1",
        "timestamp": "2022-12-12T14:24:16.828Z",
        "created_by": {"user": {"username": "alex.goller@illumio.com"}},
        "event_type": "user.sign_in",
        "status": "success",
        "severity": "info",
        "action": {
            "api_endpoint": "/login/users/sign_in",
            "api_method": "POST",
            "src_ip": "80.187.113.36",
        },
        "resource_changes": [
            {
                "resource": {
                    "user": {
                        "username": "alex.goller@illumio.com",
                    }
                }
            }
        ],
        "notifications": [
            {
                "info": {
                    "user": {
                        "username": "alex.goller@illumio.com",
                    }
                }
            }
        ],
    }

    normalized = normalize_event(event)

    assert normalized["actor"] == "alex.goller@illumio.com"
    assert normalized["source_ip"] == "80.187.113.36"
    assert normalized["action"] == "POST /login/users/sign_in"
    assert normalized["target_type"] == "user"
    assert normalized["target_name"] == "alex.goller@illumio.com"
    assert normalized["known_event_type"] is True
    assert normalized["parser_notes"] == []


def test_normalize_event_tracks_unknown_types_and_parser_notes():
    event = {
        "href": "/orgs/1/events/sample-2",
        "timestamp": "2026-04-08T12:00:00Z",
        "event_type": "totally.custom.event",
        "status": "warn",
        "severity": "warning",
        "action": {"api_method": "POST"},
    }

    normalized = normalize_event(event)

    assert normalized["known_event_type"] is False
    assert "unknown_event_type" in normalized["parser_notes"]
    assert "action_unresolved" not in normalized["parser_notes"]


def test_normalize_event_supports_local_extension_and_container_cluster_actor():
    event = {
        "href": "/orgs/1/events/sample-3",
        "timestamp": "2026-04-08T00:04:55.296Z",
        "created_by": {
            "container_cluster": {
                "href": "/orgs/1/container_clusters/cluster-1",
                "name": "local_k8s",
            }
        },
        "event_type": "container_cluster.security_policy_applied",
        "status": "success",
        "severity": "info",
        "action": {
            "api_method": "PUT",
            "api_endpoint": "/api/v2/orgs/1/container_clusters/cluster-1/security_policy_applied",
            "src_ip": "172.16.15.121",
        },
        "resource_changes": [],
        "notifications": [],
    }

    normalized = normalize_event(event)

    assert normalized["known_event_type"] is True
    assert normalized["actor"] == "local_k8s"
    assert normalized["target_type"] == "container_cluster"
    assert normalized["target_name"] == "local_k8s"
    assert normalized["action"] == "PUT /container_clusters/cluster-1/security_policy_applied"
    assert normalized["parser_notes"] == []


def test_normalize_event_marks_user_create_session_as_known_and_uses_notification_user():
    event = {
        "href": "/orgs/1/events/sample-4",
        "timestamp": "2026-04-08T03:01:02.673Z",
        "created_by": {"system": {}},
        "event_type": "user.create_session",
        "status": "success",
        "severity": "info",
        "action": {
            "api_method": "POST",
            "api_endpoint": "/api/v2/users/create_session",
            "src_ip": "FILTERED",
        },
        "notifications": [
            {"info": {"user": {"username": "admin@lab.local"}}}
        ],
        "resource_changes": [],
    }

    normalized = normalize_event(event)

    assert normalized["known_event_type"] is True
    assert normalized["actor"] == "System"
    assert normalized["target_type"] == "user"
    assert normalized["target_name"] == "admin@lab.local"
    assert normalized["action"] == "POST /api/v2/users/create_session"


def test_analyzer_preserves_event_watermark_on_fetch_failure(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.analyzer.STATE_FILE", str(state_file))

    class FailingApi:
        def check_health(self):
            return 200, "ok"

        def fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
            raise EventFetchError(503, "temporary failure")

        def execute_traffic_query_stream(self, *args, **kwargs):
            return []

    cm = SimpleNamespace(config={"rules": []})
    analyzer = Analyzer(cm, FailingApi(), DummyReporter())
    original_watermark = analyzer.state["event_watermark"]

    analyzer.run_analysis()

    assert analyzer.state["event_watermark"] == original_watermark


def test_cli_event_catalog_excludes_pce_health_system_rule():
    assert "pce_health" not in FULL_EVENT_CATALOG.get("System", {})


def test_system_rules_overwrite_by_filter_value(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"api":{"url":"test","org_id":"1","key":"","secret":""},"rules":[]}',
        encoding="utf-8",
    )

    cm = ConfigManager(config_file=str(config_file))
    first_rule = {
        "id": 1,
        "type": "system",
        "name": "PCE Health A",
        "filter_key": "system_check",
        "filter_value": "pce_health",
        "threshold_type": "immediate",
        "threshold_count": 1,
        "threshold_window": 10,
        "cooldown_minutes": 30,
    }
    second_rule = {
        "id": 2,
        "type": "system",
        "name": "PCE Health B",
        "filter_key": "system_check",
        "filter_value": "pce_health",
        "threshold_type": "immediate",
        "threshold_count": 1,
        "threshold_window": 10,
        "cooldown_minutes": 15,
    }

    cm.add_or_update_rule(first_rule)
    cm.add_or_update_rule(second_rule)

    assert len(cm.config["rules"]) == 1
    assert cm.config["rules"][0]["name"] == "PCE Health B"
    assert cm.config["rules"][0]["cooldown_minutes"] == 15


def test_analyzer_count_threshold_uses_event_timestamps(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.analyzer.STATE_FILE", str(state_file))

    fixed_now = datetime.datetime(2026, 4, 8, 12, 0, 0, tzinfo=datetime.timezone.utc)
    old_event = {
        "href": "/orgs/1/events/old",
        "event_type": "request.authentication_failed",
        "status": "failure",
        "severity": "err",
        "timestamp": "2026-04-08T11:30:00Z",
    }
    new_event = {
        "href": "/orgs/1/events/new",
        "event_type": "request.authentication_failed",
        "status": "failure",
        "severity": "err",
        "timestamp": "2026-04-08T11:58:00Z",
    }

    class Api:
        def check_health(self):
            return 200, "ok"

        def fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
            return [old_event, new_event]

        def execute_traffic_query_stream(self, *args, **kwargs):
            return []

    class Reporter(DummyReporter):
        def __init__(self):
            self.event_alerts = []

        def add_event_alert(self, alert):
            self.event_alerts.append(alert)

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
        "cooldown_minutes": 10,
    }
    cm = SimpleNamespace(config={"rules": [rule]})
    reporter = Reporter()
    analyzer = Analyzer(cm, Api(), reporter)
    analyzer.state["event_watermark"] = "2026-04-08T11:00:00Z"

    analyzer._record_event_matches(rule["id"], [old_event], fixed_now)
    count = analyzer._event_count_in_window(
        rule["id"],
        fixed_now - datetime.timedelta(minutes=10),
    )

    assert count == 0


def test_analyzer_tracks_unknown_events_and_parser_samples(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.analyzer.STATE_FILE", str(state_file))

    unknown_event = {
        "href": "/orgs/1/events/unknown",
        "event_type": "vendor.future_event",
        "status": "success",
        "severity": "info",
        "timestamp": "2026-04-08T11:58:00Z",
        "action": {"api_method": "POST", "api_endpoint": "/api/v2/orgs/1/test", "src_ip": "1.2.3.4"},
    }

    class Api:
        def check_health(self):
            return 200, "ok"

        def fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
            return [unknown_event]

        def execute_traffic_query_stream(self, *args, **kwargs):
            return []

    cm = SimpleNamespace(config={"rules": []})
    analyzer = Analyzer(cm, Api(), DummyReporter())
    analyzer.state["event_watermark"] = "2026-04-08T11:00:00Z"

    analyzer.run_analysis()

    assert analyzer.state["unknown_events"]["vendor.future_event"]["count"] == 1
    assert analyzer.state["event_parser_stats"]["last_batch_unknown"] == 1
    assert analyzer.state["event_parser_samples"][-1]["event_type"] == "vendor.future_event"


def test_run_debug_mode_uses_current_matcher_for_nested_fields(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.analyzer.STATE_FILE", str(state_file))
    now = datetime.datetime.now(datetime.timezone.utc)
    base_ts = (now - datetime.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    other_ts = (now - datetime.timedelta(minutes=1, seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    matching_event = {
        "href": "/orgs/1/events/match",
        "event_type": "request.authentication_failed",
        "status": "failure",
        "severity": "err",
        "timestamp": base_ts,
        "message": "MATCH",
        "created_by": {"user": {"username": "admin@example.com"}},
    }
    non_matching_event = {
        "href": "/orgs/1/events/miss",
        "event_type": "request.authentication_failed",
        "status": "failure",
        "severity": "err",
        "timestamp": other_ts,
        "message": "MISS",
        "created_by": {"user": {"username": "other@example.com"}},
    }

    class Api:
        def fetch_events(self, start_time_str):
            return [matching_event, non_matching_event]

        def execute_traffic_query_stream(self, *args, **kwargs):
            return []

    rule = {
        "id": 1,
        "type": "event",
        "name": "Nested auth rule",
        "filter_value": "request.authentication_failed",
        "filter_status": "failure",
        "filter_severity": "err",
        "match_fields": {"created_by.user.username": "admin@example.com"},
        "threshold_type": "count",
        "threshold_count": 1,
        "threshold_window": 10,
        "cooldown_minutes": 10,
    }
    cm = SimpleNamespace(config={"rules": [rule]})
    analyzer = Analyzer(cm, Api(), DummyReporter())

    buf = io.StringIO()
    with redirect_stdout(buf):
        analyzer.run_debug_mode(mins=10, pd_sel=3)
    output = buf.getvalue()

    assert "MATCH" in output
    assert "MISS" not in output


def test_run_debug_mode_noninteractive_skips_save_prompt(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.analyzer.STATE_FILE", str(state_file))

    class Api:
        def fetch_events(self, start_time_str):
            return []

        def execute_traffic_query_stream(self, *args, **kwargs):
            return []

    def fail_safe_input(*args, **kwargs):
        raise AssertionError("safe_input should not be called in non-interactive debug mode")

    monkeypatch.setattr("src.analyzer.safe_input", fail_safe_input)

    cm = SimpleNamespace(config={"rules": []})
    analyzer = Analyzer(cm, Api(), DummyReporter())

    buf = io.StringIO()
    with redirect_stdout(buf):
        analyzer.run_debug_mode(mins=10, pd_sel=3, interactive=False)

    output = buf.getvalue()
    assert "JSON" not in output


def test_run_debug_mode_system_rule_uses_health_check_not_traffic(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.analyzer.STATE_FILE", str(state_file))

    class Api:
        def fetch_events(self, start_time_str):
            return []

        def execute_traffic_query_stream(self, *args, **kwargs):
            return [{
                "policy_decision": "blocked",
                "num_connections": 999,
                "timestamp_range": {"last_detected": "2026-04-08T12:00:00Z"},
            }]

        def check_health(self):
            return 503, "upstream timeout"

    rule = {
        "id": 1,
        "type": "system",
        "name": "PCE Health",
        "filter_value": "pce_health",
        "threshold_count": 1,
        "threshold_window": 10,
        "cooldown_minutes": 30,
    }
    cm = SimpleNamespace(config={"rules": [rule]})
    analyzer = Analyzer(cm, Api(), DummyReporter())

    buf = io.StringIO()
    with redirect_stdout(buf):
        analyzer.run_debug_mode(mins=10, pd_sel=3, interactive=False)
    output = buf.getvalue()

    assert "PCE Health (SYSTEM)" in output
    assert "Health Check: pce_health" in output
    assert "Status: 503" in output
    assert "upstream timeout" in output
    assert "PD:" not in output
    assert "計算出的總數" not in output
