"""排程器與 GUI 共用同一把序列化鎖的守門測試。

`--monitor-gui`（正式部署模式）把 APScheduler 跑在背景 thread、Flask 跑在
主 thread，**同一行程**。若鎖各自定義在 GUI blueprint 裡，排程器側的寫入者
完全不受約束——這正是先前 ScheduleDB lost-update 與併發分析 cycle 互蓋
state 的成因。這裡用 identity 斷言把「同一把鎖」釘死，任何一側改回自己
new 一把 Lock 都會紅。
"""
import threading


def test_rule_scheduler_db_lock_is_shared_with_gui():
    import src.rule_scheduler as core
    import src.gui.routes.rule_scheduler as gui_rs

    assert gui_rs._rs_db_lock is core._rs_db_lock
    assert gui_rs._rs_db_set_status is core._rs_db_set_status


def test_rs_db_lock_is_reentrant():
    """GUI 端有「持鎖後再呼叫 helper」的巢狀用法，非 RLock 會自我死鎖。"""
    import src.rule_scheduler as core

    assert core._rs_db_lock.acquire(blocking=False)
    try:
        assert core._rs_db_lock.acquire(blocking=False), "巢狀取得失敗——不是 RLock"
        core._rs_db_lock.release()
    finally:
        core._rs_db_lock.release()


def test_analysis_lock_is_shared_between_gui_and_scheduler():
    import src.analyzer as analyzer
    import src.gui.routes.actions as actions

    assert actions._analysis_lock is analyzer.analysis_lock
    assert isinstance(analyzer.analysis_lock, type(threading.Lock()))


def test_run_monitor_cycle_holds_analysis_lock_during_analysis(monkeypatch):
    """排程器的 monitor cycle 必須在鎖內跑 run_analysis／send_alerts。"""
    import src.analyzer as analyzer
    from src.scheduler.jobs import run_monitor_cycle

    held = {}

    class _FakeAnalyzer:
        def __init__(self, *a, **kw):
            pass

        def run_analysis(self):
            held["during_analysis"] = analyzer.analysis_lock.locked()

    class _FakeReporter:
        def __init__(self, *a, **kw):
            pass

        def send_alerts(self, *a, **kw):
            held["during_send"] = analyzer.analysis_lock.locked()

    class _FakeApi:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import src.api_client
    import src.reporter
    import src.main

    monkeypatch.setattr(src.analyzer, "Analyzer", _FakeAnalyzer)
    monkeypatch.setattr(src.reporter, "Reporter", _FakeReporter)
    monkeypatch.setattr(src.api_client, "ApiClient", _FakeApi)
    monkeypatch.setattr(src.main, "_make_subscribers", lambda cm: (None, None))
    monkeypatch.setattr(src.main, "_make_cache_reader", lambda cm: None)

    run_monitor_cycle(object())

    assert held.get("during_analysis") is True, "run_analysis 不在 analysis_lock 內"
    assert held.get("during_send") is True, "send_alerts 不在 analysis_lock 內"
    assert not analyzer.analysis_lock.locked(), "離開後鎖未釋放"


def test_rs_db_delete_reloads_under_lock(tmp_path):
    """刪除到期排程時必須鎖內重讀：不得用過期快照把併發新增的排程整檔蓋掉。"""
    import json
    from src.rule_scheduler import ScheduleDB, _rs_db_delete

    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text(json.dumps({"/a": {"name": "a"}}), encoding="utf-8")

    db = ScheduleDB(str(db_path))
    db.load()  # 取得「tick 開始時」的快照：只有 /a

    # 另一個寫入者（GUI）在這期間新增了 /b
    db_path.write_text(json.dumps({"/a": {"name": "a"}, "/b": {"name": "b"}}),
                       encoding="utf-8")

    _rs_db_delete(db, "/a")

    on_disk = json.loads(db_path.read_text(encoding="utf-8"))
    assert "/a" not in on_disk, "到期條目未被刪除"
    assert "/b" in on_disk, "併發新增的排程被過期快照蓋掉了"


def test_rs_db_set_status_does_not_resurrect_deleted_entry(tmp_path):
    import json
    from src.rule_scheduler import ScheduleDB, _rs_db_set_status

    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text(json.dumps({"/a": {"name": "a", "pce_status": "active"}}),
                       encoding="utf-8")

    db = ScheduleDB(str(db_path))
    db.load()

    # 併發刪除
    db_path.write_text(json.dumps({}), encoding="utf-8")

    _rs_db_set_status(db, "/a", "deleted")

    assert json.loads(db_path.read_text(encoding="utf-8")) == {}, \
        "已刪除的條目被 pce_status 寫回復活"
