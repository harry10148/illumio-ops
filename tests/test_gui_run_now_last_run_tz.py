"""GUI Run-Now 路徑的 last_run 寫入基準需與 tick() 一致：schedule 有明確
timezone 時寫入 naive schedule-local（不是 UTC-aware），讓緊接著的 tick
判定不會誤判成「尚未跑過」而重跑。讀取端（should_run）對兩種格式的相容性
不受影響——本測試同時涵蓋這點。
"""
import datetime
import json
import threading
import time

from tests._helpers import _csrf


def test_run_now_writes_naive_schedule_local_last_run_and_blocks_tick_rerun(
    client, app_persistent, monkeypatch, tmp_path
):
    cm = app_persistent.config["CM"]
    cm.load()
    cm.config["report_schedules"] = [
        {
            "id": 456,
            "name": "TaipeiDaily",
            "enabled": True,
            "report_type": "traffic",
            "schedule_type": "daily",
            "hour": 9,
            "minute": 0,
            "timezone": "Asia/Taipei",
            "email_report": False,
        }
    ]
    cm.save()

    state_file = tmp_path / "state.json"
    monkeypatch.setattr("src.gui.routes.reports._resolve_state_file", lambda: str(state_file))

    done = threading.Event()

    def _fast_run_schedule(self, schedule):
        done.set()
        return True

    monkeypatch.setattr("src.report_scheduler.ReportScheduler.run_schedule", _fast_run_schedule)

    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    })
    csrf_token = _csrf(login)

    response = client.post(
        "/api/report-schedules/456/run",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    assert done.wait(timeout=2)

    # 背景 thread 在 run_schedule 回傳後才寫入 "success" 狀態，稍微等一下。
    state = {}
    for _ in range(50):
        with state_file.open(encoding="utf-8") as f:
            state = json.load(f)
        if state.get("report_schedule_states", {}).get("456", {}).get("status") == "success":
            break
        time.sleep(0.05)

    entry = state["report_schedule_states"]["456"]
    assert entry["status"] == "success"
    last_run = entry["last_run"]
    parsed = datetime.datetime.fromisoformat(last_run)
    assert parsed.tzinfo is None, f"expected naive schedule-local last_run, got {last_run!r}"

    # 隨後 tick 的 due 判定：同一天內 last_run 已存在，不得再次觸發。
    from src.report_scheduler import ReportScheduler
    scheduler = ReportScheduler(cm, reporter=None)
    sched = cm.get_report_schedules()[0]
    now_taipei = parsed + datetime.timedelta(minutes=1)
    assert scheduler.should_run(sched, now_taipei, last_run_str=last_run) is False
