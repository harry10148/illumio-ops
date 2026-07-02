"""C.5.3/5/6 驗證：report_scheduler due 判定改為 catch-up 語意
（now >= 排程時刻 且 last_run < 該排程時刻），_MIN_RERUN_GAP 只守非 cron 分支，
cron 分支收斂到 tz_utils.resolve_tz 並比照 tick() 的 global_tz fallback 鏈。
"""
from __future__ import annotations

import datetime

from freezegun import freeze_time

from src.report_scheduler import ReportScheduler


def _sched(cron_expr=None, **kw):
    base = {"id": 1, "enabled": True}
    if cron_expr:
        base["cron_expr"] = cron_expr
    base.update(kw)
    return base


def _make_scheduler(global_tz=None):
    from unittest.mock import MagicMock
    cm = MagicMock()
    cm.config = {"settings": {"timezone": global_tz} if global_tz else {}}
    reporter = MagicMock()
    scheduler = ReportScheduler(cm, reporter)
    scheduler._load_states = MagicMock(return_value={})
    return scheduler


# ─── (a) 精確分鐘錯過後補跑一次、只補一次 ───────────────────────────────────

def test_daily_catches_up_once_after_missed_exact_minute():
    """tick 因跑前一個排程而錯過 08:00 精確分鐘，08:01:30 才檢查——應補跑一次。"""
    s = _make_scheduler()
    sched = _sched(schedule_type="daily", hour=8, minute=0)

    now_late = datetime.datetime(2026, 6, 1, 8, 1, 30)
    assert s.should_run(sched, now_late, last_run_str=None) is True, \
        "must catch up when now is past the target minute and never run"


def test_daily_does_not_rerun_same_day_after_catchup():
    """補跑一次之後，同一天再檢查（即使還在 08:xx）不應再次觸發。"""
    s = _make_scheduler()
    sched = _sched(schedule_type="daily", hour=8, minute=0)

    ran_at = datetime.datetime(2026, 6, 1, 8, 1, 30)
    last_run = ran_at.isoformat()

    later_same_day = datetime.datetime(2026, 6, 1, 8, 5, 0)
    assert s.should_run(sched, later_same_day, last_run_str=last_run) is False

    much_later_same_day = datetime.datetime(2026, 6, 1, 23, 0, 0)
    assert s.should_run(sched, much_later_same_day, last_run_str=last_run) is False


def test_daily_fires_again_next_day_after_catchup():
    s = _make_scheduler()
    sched = _sched(schedule_type="daily", hour=8, minute=0)
    last_run = datetime.datetime(2026, 6, 1, 8, 1, 30).isoformat()

    next_day = datetime.datetime(2026, 6, 2, 8, 0, 30)
    assert s.should_run(sched, next_day, last_run_str=last_run) is True


def test_daily_not_due_before_target_time():
    s = _make_scheduler()
    sched = _sched(schedule_type="daily", hour=8, minute=0)
    before = datetime.datetime(2026, 6, 1, 7, 59, 0)
    assert s.should_run(sched, before, last_run_str=None) is False


# ─── (c) daily 不因 catch-up 語意重複觸發（tick 每分鐘檢查多次） ──────────────

def test_daily_tick_every_minute_only_fires_once_across_the_day():
    s = _make_scheduler()
    sched = _sched(schedule_type="daily", hour=8, minute=0)
    last_run_str = None
    fire_count = 0
    t = datetime.datetime(2026, 6, 1, 7, 58, 0)
    end = datetime.datetime(2026, 6, 1, 10, 0, 0)
    while t <= end:
        due = s.should_run(sched, t, last_run_str=last_run_str)
        if due:
            fire_count += 1
            last_run_str = t.isoformat()
        t += datetime.timedelta(minutes=1)
    assert fire_count == 1, f"expected exactly one fire across the day, got {fire_count}"


# ─── (b) 15 分鐘 cron 一小時觸發 4 次（子項 3 的 gap 收斂到非-cron） ──────────

def test_sub_hourly_cron_fires_four_times_per_hour():
    s = _make_scheduler()
    sched = _sched(cron_expr="*/15 * * * *")
    last_run_str = None
    fires = []
    t = datetime.datetime(2026, 6, 1, 9, 0, 0)
    end = datetime.datetime(2026, 6, 1, 9, 59, 0)
    while t <= end:
        due = s.should_run(sched, t, last_run_str=last_run_str)
        if due:
            fires.append(t)
            last_run_str = t.isoformat()
        t += datetime.timedelta(minutes=1)
    assert [f.minute for f in fires] == [0, 15, 30, 45], fires


def test_sub_hourly_cron_not_blocked_by_min_rerun_gap():
    """3600s _MIN_RERUN_GAP 不再套用到 cron 分支——15 分鐘後必須能再次觸發。"""
    s = _make_scheduler()
    sched = _sched(cron_expr="*/15 * * * *")
    fired_at = datetime.datetime(2026, 6, 1, 9, 0, 0)
    fifteen_later = datetime.datetime(2026, 6, 1, 9, 15, 0)
    assert s.should_run(sched, fifteen_later, last_run_str=fired_at.isoformat()) is True


def test_cron_does_not_refire_same_trigger_time_after_running():
    """cron 的重跑保護：last_run 等於上一次實際觸發時刻時，同一觸發時刻不重跑。"""
    s = _make_scheduler()
    sched = _sched(cron_expr="0 8 * * MON-FRI")
    fired_at = datetime.datetime(2024, 1, 1, 8, 0, 0)  # Monday
    later_same_day = datetime.datetime(2024, 1, 1, 8, 30, 0)
    assert s.should_run(sched, later_same_day, last_run_str=fired_at.isoformat()) is False


# ─── (5) UTC+8 cron 觸發時刻鎖定（收斂到 tz_utils 後行為不變） ───────────────

def test_cron_utc_plus_8_trigger_time_locked_and_no_unknown_tz_warning(caplog):
    """UTC+8 排程走 tz_utils.resolve_tz——觸發時刻與收斂前一致，且不再誤發
    'Unknown timezone' warning（ZoneInfo 不認 'UTC+8'，過去每 tick 誤發一次）。
    """
    from src.report_scheduler import _now_in_schedule_tz

    sched = _sched(cron_expr="0 9 * * *", timezone="UTC+8")
    s = _make_scheduler()

    with freeze_time("2026-06-01T01:00:00+00:00"):  # 09:00 UTC+8
        now = _now_in_schedule_tz("UTC+8")
        assert s.should_run(sched, now, last_run_str=None) is True

    with freeze_time("2026-06-01T09:00:00+00:00"):  # 17:00 UTC+8 — should NOT fire
        now = _now_in_schedule_tz("UTC+8")
        assert s.should_run(sched, now, last_run_str=None) is False

    assert not any("Unknown timezone" in rec.message for rec in caplog.records), caplog.text


# ─── (6) should_run 的 global_tz fallback 要跟 tick() 一致 ──────────────────

def test_cron_uses_global_tz_fallback_when_schedule_timezone_unset():
    """schedule 沒有 timezone、global settings.timezone='Asia/Taipei'——
    cron '0 9 * * *' 應在台北 09:00 觸發（比照 tick() 的 fallback 鏈）。"""
    s = _make_scheduler(global_tz="Asia/Taipei")
    sched = _sched(cron_expr="0 9 * * *")  # no per-schedule timezone

    # tick() would compute `now` via _now_in_schedule_tz(global_tz) — simulate
    # the naive Taipei wall-clock it would produce.
    now_taipei_0900 = datetime.datetime(2026, 6, 1, 9, 0, 0)
    assert s.should_run(sched, now_taipei_0900, last_run_str=None) is True

    now_taipei_1700 = datetime.datetime(2026, 6, 1, 17, 0, 0)
    assert s.should_run(sched, now_taipei_1700, last_run_str=None) is False


def test_tick_end_to_end_global_tz_fallback_taipei_0900(monkeypatch):
    """完整 tick() 路徑：global settings.timezone='Asia/Taipei'、schedule 無
    timezone，cron 0 9 * * * 在台北時間 09:00 應觸發並呼叫 run_schedule。"""
    from unittest.mock import MagicMock

    cm = MagicMock()
    cm.config = {
        "settings": {"timezone": "Asia/Taipei"},
        "report_schedules": [
            {"id": 1, "name": "Taipei9am", "enabled": True, "cron_expr": "0 9 * * *"},
        ],
    }
    cm.load = lambda: None
    reporter = MagicMock()
    scheduler = ReportScheduler(cm, reporter)
    scheduler._load_states = MagicMock(return_value={})
    ran = []
    scheduler.run_schedule = lambda sched: ran.append(sched["id"]) or True
    scheduler._save_state = MagicMock()

    with freeze_time("2026-06-01T01:00:00+00:00"):  # 09:00 Asia/Taipei
        scheduler.tick()

    assert ran == [1]
