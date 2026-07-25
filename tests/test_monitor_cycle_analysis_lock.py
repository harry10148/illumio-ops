"""R3/R4 gate：排程器的 monitor cycle 必須在「跨行程檔案鎖 + 行程內鎖」內
建構並執行 Analyzer。

R3 — CLI 選單與 GUI 都已經取 main.analysis_lock_path() 的檔案鎖，排程器沒取，
     於是「CLI 跑一次分析」與常駐服務的 cycle 仍然完全沒有序列化：兩邊各自
     在 Analyzer.__init__ 取走整份 state 快照，後結束的一方把對方剛寫的
     alert_history（告警冷卻）整組還原 → 同一則告警重寄。
R4 — Analyzer(...) 的建構會 load_state()。在鎖外建構等於「鎖外取快照、鎖內
     寫回」，鎖形同虛設（併發的 reset watermark 會被還原）。
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_run_monitor_cycle_builds_analyzer_inside_both_locks(monkeypatch):
    import src.analyzer
    import src.api_client
    import src.file_lock
    import src.main
    import src.reporter
    from src.scheduler.jobs import run_monitor_cycle

    seen = {}
    file_lock_depth = {"n": 0}

    @contextmanager
    def _recording_file_lock(path, timeout=None):
        seen["lock_path"] = path
        seen["timeout"] = timeout
        file_lock_depth["n"] += 1
        try:
            yield
        finally:
            file_lock_depth["n"] -= 1

    def _snapshot(tag):
        seen[tag] = (file_lock_depth["n"] > 0, src.analyzer.analysis_lock.locked())

    class _FakeAnalyzer:
        def __init__(self, *a, **kw):
            _snapshot("during_init")

        def run_analysis(self):
            _snapshot("during_analysis")

    class _FakeReporter:
        def __init__(self, *a, **kw):
            pass

        def send_alerts(self, *a, **kw):
            _snapshot("during_send")

    class _FakeApi:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(src.file_lock, "file_lock", _recording_file_lock)
    monkeypatch.setattr(src.analyzer, "Analyzer", _FakeAnalyzer)
    monkeypatch.setattr(src.reporter, "Reporter", _FakeReporter)
    monkeypatch.setattr(src.api_client, "ApiClient", _FakeApi)
    monkeypatch.setattr(src.main, "_make_subscribers", lambda cm: (None, None))
    monkeypatch.setattr(src.main, "_make_cache_reader", lambda cm: None)

    run_monitor_cycle(object())

    assert seen["lock_path"] == src.main.analysis_lock_path(), \
        "取的不是 CLI/GUI 那把跨行程鎖 → 三方仍未互斥"
    assert seen["timeout"] and seen["timeout"] > 0
    assert seen["during_init"] == (True, True), \
        "Analyzer 在鎖外建構（load_state 取快照）→ 鎖等於沒作用"
    assert seen["during_analysis"] == (True, True)
    assert seen["during_send"] == (True, True)
    assert file_lock_depth["n"] == 0, "離開後檔案鎖未釋放"
    assert not src.analyzer.analysis_lock.locked(), "離開後行程內鎖未釋放"


def test_run_monitor_cycle_surfaces_lock_timeout(monkeypatch):
    """等不到鎖時不得靜默跳過：TimeoutError 要往上拋，_instrument 才會把
    job_health 記成 error（不然面板永遠是綠的、cycle 卻沒跑）。"""
    import src.file_lock
    from src.scheduler.jobs import run_monitor_cycle

    @contextmanager
    def _timeout_lock(path, timeout=None):
        raise TimeoutError(path)
        yield  # pragma: no cover

    import src.api_client
    import src.main

    class _FakeApi:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(src.file_lock, "file_lock", _timeout_lock)
    monkeypatch.setattr(src.api_client, "ApiClient", _FakeApi)
    monkeypatch.setattr(src.main, "_make_subscribers", lambda cm: (None, None))
    monkeypatch.setattr(src.main, "_make_cache_reader", lambda cm: None)
    import src.reporter

    class _FakeReporter:
        def __init__(self, *a, **kw):
            pass

    monkeypatch.setattr(src.reporter, "Reporter", _FakeReporter)

    with pytest.raises(TimeoutError):
        run_monitor_cycle(object())
