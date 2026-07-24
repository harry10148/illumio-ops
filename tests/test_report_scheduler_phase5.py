import datetime
from types import SimpleNamespace

import pytest

from src.report_scheduler import ReportScheduler, _now_in_schedule_tz


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


# ─── Regression: tz='local' naive/aware datetime subtraction (HIGH) ───────────

def test_should_run_local_tz_aware_now_with_stored_last_run_no_typeerror():
    """tz='local' makes `now` tz-AWARE while the stored last_run parses NAIVE.
    The min-rerun-gap subtraction must not raise TypeError; within the gap it
    returns False (pre-fix this raised and killed the whole tick)."""
    scheduler = ReportScheduler(_DummyConfigManager(), _DummyReporter())
    now = _now_in_schedule_tz("local")
    assert now.tzinfo is not None, "precondition: 'local' yields an aware now"
    last_run = now.replace(tzinfo=None).isoformat()  # naive, just now → within gap
    sched = {"id": 1, "enabled": True, "schedule_type": "daily", "hour": 8, "minute": 0}
    assert scheduler.should_run(sched, now, last_run_str=last_run) is False


def test_tick_local_tz_with_stored_last_run_evaluates_all_schedules(monkeypatch):
    """A stored last_run on the FIRST schedule under tz='local' must not abort
    tick(); every schedule is still evaluated (real should_run, no TypeError)."""
    reporter = _DummyReporter()
    cm = _DummyConfigManager()
    cm.config = {
        "settings": {"timezone": "local"},
        "report_schedules": [
            {"id": 1, "name": "First", "enabled": True,
             "schedule_type": "daily", "hour": 8, "minute": 0},
            {"id": 2, "name": "Second", "enabled": True,
             "schedule_type": "daily", "hour": 8, "minute": 0},
        ],
    }
    cm.load = lambda: None
    scheduler = ReportScheduler(cm, reporter)

    recent = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
    monkeypatch.setattr(scheduler, "_load_states",
                        lambda: {"1": {"last_run": recent}, "2": {"last_run": recent}})

    evaluated = []
    real_should_run = ReportScheduler.should_run

    def spy(self, sched, now, *a, **kw):
        evaluated.append(sched["id"])
        return real_should_run(self, sched, now, *a, **kw)

    monkeypatch.setattr(ReportScheduler, "should_run", spy)

    scheduler.tick()  # must not raise
    assert evaluated == [1, 2]


def test_tick_isolates_a_failing_should_run_per_schedule(monkeypatch):
    """Defense-in-depth: even if should_run raises for one schedule, tick() must
    keep evaluating the remaining schedules instead of aborting the cycle."""
    reporter = _DummyReporter()
    cm = _DummyConfigManager()
    cm.config = {
        "settings": {"timezone": "local"},
        "report_schedules": [
            {"id": 1, "name": "Bad", "enabled": True},
            {"id": 2, "name": "Good", "enabled": True},
        ],
    }
    cm.load = lambda: None
    scheduler = ReportScheduler(cm, reporter)

    evaluated = []

    def flaky(sched, now):
        evaluated.append(sched["id"])
        if sched["id"] == 1:
            raise TypeError("can't subtract offset-naive and offset-aware datetimes")
        return False

    monkeypatch.setattr(scheduler, "should_run", flaky)

    scheduler.tick()  # must not raise
    assert evaluated == [1, 2]


# ─── H（2026-07-24 審查）：報表失敗不推進 last_run、該期重試、有界 backoff ──

def _due_daily_sched():
    return {"id": 7, "name": "Daily", "enabled": True,
            "schedule_type": "daily", "hour": 0, "minute": 0}


def test_run_failure_does_not_advance_last_run(tmp_path, monkeypatch):
    """產報表失敗不得推進 last_run——否則 daily 下 tick 判已跑、該期永久漏。"""
    import json
    reporter = _DummyReporter()
    cm = _DummyConfigManager()
    cm.config = {"settings": {"timezone": "UTC"},
                 "report_schedules": [_due_daily_sched()]}
    cm.load = lambda: None
    scheduler = ReportScheduler(cm, reporter)
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(scheduler, "_state_file", state_file)
    monkeypatch.setattr(scheduler, "should_run", lambda sched, now: True)
    monkeypatch.setattr(scheduler, "run_schedule",
                        lambda sched: (_ for _ in ()).throw(RuntimeError("PCE down")))
    scheduler.tick()
    st = json.load(open(state_file))["report_schedule_states"]["7"]
    assert st["status"] == "failed"
    assert not st.get("last_run")          # 未推進
    assert st.get("consecutive_failures", 0) >= 1
    assert st.get("last_attempt")


def test_run_failure_backoff_skips_immediate_retry(tmp_path, monkeypatch):
    """連續失敗要 backoff：剛失敗過的排程同一輪/下一輪 tick 內不重打。"""
    reporter = _DummyReporter()
    cm = _DummyConfigManager()
    cm.config = {"settings": {"timezone": "UTC"},
                 "report_schedules": [_due_daily_sched()]}
    cm.load = lambda: None
    scheduler = ReportScheduler(cm, reporter)
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(scheduler, "_state_file", state_file)
    monkeypatch.setattr(scheduler, "should_run", lambda sched, now: True)
    calls = {"n": 0}

    def _boom(sched):
        calls["n"] += 1
        raise RuntimeError("PCE down")

    monkeypatch.setattr(scheduler, "run_schedule", _boom)
    scheduler.tick()   # 第一次失敗
    scheduler.tick()   # backoff 內 → 不重打
    assert calls["n"] == 1


def test_run_success_clears_failure_tracking(tmp_path, monkeypatch):
    import json
    reporter = _DummyReporter()
    cm = _DummyConfigManager()
    cm.config = {"settings": {"timezone": "UTC"},
                 "report_schedules": [_due_daily_sched()]}
    cm.load = lambda: None
    scheduler = ReportScheduler(cm, reporter)
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr(scheduler, "_state_file", state_file)
    monkeypatch.setattr(scheduler, "should_run", lambda sched, now: True)
    monkeypatch.setattr(scheduler, "run_schedule", lambda sched: True)
    scheduler.tick()
    st = json.load(open(state_file))["report_schedule_states"]["7"]
    assert st["status"] == "success"
    assert st["last_run"]
    assert st.get("consecutive_failures", 0) == 0
