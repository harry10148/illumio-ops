from types import SimpleNamespace

import pytest

from src.report_scheduler import ReportScheduler


class _DummyReporter:
    def __init__(self):
        self.payload = None

    def send_scheduled_report_email(self, subject, html_body, attachment_paths=None, custom_recipients=None):
        self.payload = {
            "subject": subject,
            "html_body": html_body,
            "attachment_paths": attachment_paths or [],
            "custom_recipients": custom_recipients or [],
        }


class _DummyConfigManager:
    def __init__(self):
        self.config = {
            "report": {"output_dir": "reports"},
            "settings": {},
        }


def test_scheduler_email_includes_attack_summary_block():
    reporter = _DummyReporter()
    scheduler = ReportScheduler(_DummyConfigManager(), reporter)
    result = SimpleNamespace(
        record_count=8,
        findings=[],
        module_results={
            "mod00": {
                "boundary_breaches": [{"finding": "Cross-scope change burst", "action": "Review boundary controls"}],
                "suspicious_pivot_behavior": [{"finding": "Suspicious admin pivot", "action": "Validate actor intent"}],
                "blast_radius": [],
                "blind_spots": [],
                "action_matrix": [{"action": "Require staged policy rollout", "priority": 90}],
            }
        },
    )

    scheduler._send_report_email(
        schedule={"name": "Nightly Audit"},
        result=result,
        paths=["/tmp/audit.html"],
        start_date="2026-04-01T00:00:00Z",
        end_date="2026-04-02T23:59:59Z",
        custom_recipients=["ops@example.com"],
        report_type="audit",
    )

    assert reporter.payload is not None
    body = reporter.payload["html_body"]
    assert "Attack Summary" in body
    assert "Cross-scope change burst" in body


def test_tick_uses_global_timezone_when_schedule_timezone_is_null(monkeypatch):
    reporter = _DummyReporter()
    cm = _DummyConfigManager()
    cm.config = {
        "settings": {"timezone": "UTC+8"},
        "report_schedules": [
            {
                "id": 1,
                "name": "Daily",
                "enabled": True,
                "timezone": None,
                "schedule_type": "daily",
                "hour": 8,
                "minute": 0,
            }
        ],
    }
    cm.load = lambda: None
    scheduler = ReportScheduler(cm, reporter)
    seen_timezones = []

    def fake_now(tz_str):
        seen_timezones.append(tz_str)
        return SimpleNamespace()

    monkeypatch.setattr("src.report_scheduler._now_in_schedule_tz", fake_now)
    monkeypatch.setattr(scheduler, "should_run", lambda sched, now: False)

    scheduler.tick()

    assert seen_timezones == ["UTC+8"]


def test_scheduled_email_failure_is_reported():
    class FailingReporter(_DummyReporter):
        def send_scheduled_report_email(self, subject, html_body, attachment_paths=None, custom_recipients=None):
            return False

    scheduler = ReportScheduler(_DummyConfigManager(), FailingReporter())
    result = SimpleNamespace(record_count=1, findings=[], module_results={})

    with pytest.raises(RuntimeError):
        scheduler._send_report_email(
            schedule={"name": "Daily"},
            result=result,
            paths=["/tmp/report.html"],
            start_date="2026-04-01T00:00:00Z",
            end_date="2026-04-02T23:59:59Z",
            custom_recipients=["ops@example.com"],
            report_type="traffic",
        )
