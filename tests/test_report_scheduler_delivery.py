"""排程報表：產生與寄送分開處理。

舊行為：寄送失敗（含部分收件人被拒、沒有收件人）讓整個排程 raise → 不推進
last_run → 每小時重抓 PCE、重產報表、重寄給已收到的人。PCE 斷線被吞成空資料
→ 記成 success。
"""
from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest

from src.config_models import ConfigSchema
from src.report_scheduler import ReportScheduler, ScheduleOutcome


class _Reporter:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.sent = 0
        self.last_report_email_outcome = "unknown"
        self.last_report_email_refused = {}

    def send_scheduled_report_email(self, **kw):
        self.sent += 1
        kind = self.outcomes.pop(0) if self.outcomes else "sent"
        self.last_report_email_outcome = kind
        if kind == "partial":
            self.last_report_email_refused = {"bad@example.com": "550"}
        return kind == "sent"


def _cm(tmp_path):
    cm = SimpleNamespace(models=ConfigSchema())
    cm.config = {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "report": {"output_dir": str(tmp_path)},
        "settings": {},
        "report_schedules": [{"id": 7, "name": "daily", "enabled": True, "report_type": "traffic",
                              "schedule_type": "daily", "hour": 0, "minute": 0,
                              "format": ["html"], "email_report": True}],
    }
    cm.load = lambda: None
    return cm


@pytest.fixture
def sched(tmp_path, monkeypatch):
    def make(outcomes, generate=None):
        reporter = _Reporter(outcomes)
        s = ReportScheduler(_cm(tmp_path), reporter)
        s._state_file = str(tmp_path / "state.json")
        calls = {"generate": 0}
        report = tmp_path / "r.html"
        report.write_text("x")

        def fake_generate(self, report_type, api, fmt, output_dir, start_date, end_date, name,
                          filters=None, lang="en", schedule=None):
            calls["generate"] += 1
            if generate:
                return generate(api)
            return SimpleNamespace(record_count=3, module_results={}, findings=[]), [str(report)]

        monkeypatch.setattr(ReportScheduler, "_generate_report", fake_generate)
        monkeypatch.setattr(s, "_prune_by_count", lambda *a, **k: None)
        monkeypatch.setattr(s, "_prune_old_reports", lambda *a, **k: None)
        return s, reporter, calls
    return make


def _state(s):
    with open(s._state_file, encoding="utf-8") as f:
        return json.load(f)["report_schedule_states"]["7"]


def test_partial_refusal_is_final_and_not_resent(sched):
    s, reporter, calls = sched(["partial"])
    s.tick()
    st = _state(s)
    assert st["status"] == "delivery_partial"
    assert "bad@example.com" in st["error"]
    assert st.get("last_run") and "pending_delivery" not in st
    s.tick()  # 不再 due、也沒有待重寄
    assert calls["generate"] == 1 and reporter.sent == 1


def test_missing_recipients_does_not_loop(sched):
    s, reporter, calls = sched(["no_recipients"])
    s.tick()
    assert _state(s)["status"] == "delivery_failed"
    s.tick()
    assert calls["generate"] == 1 and reporter.sent == 1


def test_transient_failure_resends_email_only(sched):
    s, reporter, calls = sched(["transient", "sent"])
    s.tick()
    st = _state(s)
    assert st["status"] == "delivery_pending" and st["pending_delivery"]["attempts"] == 1
    # 退避時間到
    def _due(entry):
        entry["pending_delivery"]["next_attempt"] = "2000-01-01T00:00:00+00:00"
    s._update_entry(7, _due)
    s.tick()
    st = _state(s)
    assert st["status"] == "success" and "pending_delivery" not in st
    assert calls["generate"] == 1  # 報表沒有重產
    assert reporter.sent == 2


def test_transient_failures_give_up_after_max_attempts(sched):
    s, reporter, calls = sched(["transient"] * 10)
    s.tick()
    for _ in range(6):
        s._update_entry(7, lambda e: e.get("pending_delivery") and e["pending_delivery"].update(
            next_attempt="2000-01-01T00:00:00+00:00"))
        s.tick()
    st = _state(s)
    assert st["status"] == "delivery_failed" and "pending_delivery" not in st
    assert reporter.sent == 5 and calls["generate"] == 1


def test_pce_fetch_error_is_a_failure_not_success(sched):
    def gen(api):
        api.last_fetch_error = "503: Service Unavailable"
        return None, []
    s, reporter, calls = sched([], generate=gen)
    s.tick()
    st = _state(s)
    assert st["status"] == "failed" and "503" in st["error"]
    assert not st.get("last_run")  # 該期保留重試
    assert reporter.sent == 0


def test_genuinely_empty_period_is_no_data(sched):
    s, reporter, calls = sched([], generate=lambda api: (None, []))
    s.tick()
    st = _state(s)
    assert st["status"] == "no_data" and st.get("last_run")


def test_running_marker_blocks_second_scheduler(sched):
    s, reporter, calls = sched(["sent"])
    s._mark_running(7)
    s.tick()
    assert calls["generate"] == 0
    # 殘留標記（行程被殺）過期後照常執行
    s._update_entry(7, lambda e: e.update(running_since="2000-01-01T00:00:00+00:00"))
    s.tick()
    assert calls["generate"] == 1


def test_outcome_truthiness_matches_produced_report():
    assert ScheduleOutcome()
    assert ScheduleOutcome(status="delivery_failed")
    assert not ScheduleOutcome(status="no_data")
