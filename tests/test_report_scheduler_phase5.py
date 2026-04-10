from types import SimpleNamespace

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
