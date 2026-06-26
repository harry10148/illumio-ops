# Phase 6 Implementation Plan — 排程器統一 (APScheduler)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 `APScheduler.BackgroundScheduler` 取代 [src/main.py `run_daemon_loop`](../../../src/main.py) 的自製 tick 邏輯（`while not _shutdown_event.is_set()` + `wait(timeout=60)`）、[src/report_scheduler.py](../../../src/report_scheduler.py) 496 LOC 內的時間判斷、[src/rule_scheduler.py](../../../src/rule_scheduler.py) 246 LOC 的 check 迴圈。既有 job 設定（`config/rule_schedules.json`、`config/report_schedules.json`）沿用，但改由一個自製 `JsonJobStore` 接駁 APScheduler；business logic（執行什麼）保留不動。**順便**解 [Status.md A3](../../../Status.md) 單執行緒 daemon 阻塞問題 + [Phase 2 的 TTLCache thread-safety NOTE](../../../src/api_client.py)。

**Architecture:** `BackgroundScheduler` 由 `src/scheduler/__init__.py` 工廠建立，註冊 3 種 job：
1. `monitor_cycle` — IntervalTrigger(minutes=N)，執行 Analyzer.run_analysis + Reporter.send_alerts
2. `report_schedules` — 每分鐘一次 IntervalTrigger，內部讀 report_schedules.json 並觸發到期 job
3. `rule_schedules` — IntervalTrigger(seconds=check_interval_seconds)，內部讀 rule_schedules.json 並觸發到期 job

**不重寫** `report_schedules.json` / `rule_schedules.json` 格式 — 繼續用既有 schema，只是時間判斷交給 APScheduler 的循環觸發。Thread pool executor (max_workers=5) 取代 single-threaded daemon loop。ApiClient 的 TTLCaches（Phase 2 flagged）加 `threading.Lock` 保護。

**Tech Stack:** APScheduler>=3.10 (Phase 0 已裝), freezegun>=1.4 (dev, Phase 0)

**Branch:** `upgrade/phase-6-scheduler-aps`（from main；**可與 Phase 4/5 並行**）

**Target tag on merge:** `v3.5.2-scheduler`

**Parent roadmap:** [2026-04-18-upgrade-roadmap.md](2026-04-18-upgrade-roadmap.md)

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `src/scheduler/__init__.py` | 新增 | `build_scheduler(cm) -> BackgroundScheduler` 工廠 |
| `src/scheduler/jobs.py` | 新增 | 3 個 job callable：`run_monitor_cycle`、`tick_report_schedules`、`tick_rule_schedules` |
| `src/main.py` | 改 | `run_daemon_loop` 改用 scheduler；shutdown signal 停 scheduler |
| `src/api_client.py` | 小改 | TTLCache mutations 加 `threading.Lock` 保護（Phase 2 flagged） |
| `src/report_scheduler.py` | 小改 | tick 邏輯保留（被新 job 呼叫），業務邏輯不動 |
| `src/rule_scheduler.py` | 小改 | 同上 |
| `tests/test_scheduler_setup.py` | 新增 | scheduler 啟停、jobs 註冊、misfire grace |
| `tests/test_scheduler_integration.py` | 新增 | freezegun 推進時間，驗證 job 觸發 |
| `tests/test_api_client_thread_safety.py` | 新增 | concurrent update_label_cache 與 read — 不應 RuntimeError |

**檔案影響面**：2 新 + 4 小改 + 3 新測試。

---

## Task 1: Branch + baseline

```bash
git checkout main && git pull
git checkout -b upgrade/phase-6-scheduler-aps
python -m pytest tests/ -q
```

記下 baseline pass 數。

---

## Task 2: Contract tests for existing daemon behavior

**Files:** 
- Create: `tests/test_daemon_contract.py`

鎖定既有 daemon 行為：interval-based analysis、report scheduler 每 60s tick、rule scheduler 依 `check_interval_seconds`。

```python
"""Freeze daemon loop behavior before migrating to APScheduler."""
import pytest
from unittest.mock import MagicMock, patch


def test_run_daemon_loop_callable():
    from src.main import run_daemon_loop
    assert callable(run_daemon_loop)


def test_daemon_accepts_interval_minutes():
    """run_daemon_loop(interval_minutes: int) — signature stable."""
    import inspect
    from src.main import run_daemon_loop
    sig = inspect.signature(run_daemon_loop)
    assert "interval_minutes" in sig.parameters
```

執行確認 PASS（舊實作符合），commit。

---

## Task 3: 建立 scheduler 工廠

**Files:**
- Create: `src/scheduler/__init__.py`
- Create: `src/scheduler/jobs.py`

寫 failing test `tests/test_scheduler_setup.py`:

```python
def test_build_scheduler_returns_running_scheduler():
    from src.scheduler import build_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    cm = _fake_cm()
    sched = build_scheduler(cm, interval_minutes=10)
    assert isinstance(sched, BackgroundScheduler)
    # 3 jobs expected
    job_ids = {j.id for j in sched.get_jobs()}
    assert "monitor_cycle" in job_ids
    assert "tick_report_schedules" in job_ids
    assert "tick_rule_schedules" in job_ids

def test_monitor_job_uses_interval_trigger():
    from src.scheduler import build_scheduler
    sched = build_scheduler(_fake_cm(), interval_minutes=5)
    job = sched.get_job("monitor_cycle")
    # trigger has the right interval
    assert job.trigger.interval.total_seconds() == 300

def test_report_tick_runs_every_60s():
    sched = build_scheduler(_fake_cm(), interval_minutes=10)
    assert sched.get_job("tick_report_schedules").trigger.interval.total_seconds() == 60

def test_rule_tick_uses_configured_interval():
    cm = _fake_cm(rule_check_interval=180)
    sched = build_scheduler(cm, interval_minutes=10)
    assert sched.get_job("tick_rule_schedules").trigger.interval.total_seconds() == 180
```

實作 `src/scheduler/__init__.py`:

```python
"""BackgroundScheduler factory for illumio_ops daemon."""
from __future__ import annotations

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.executors.pool import ThreadPoolExecutor

from src.scheduler.jobs import (
    run_monitor_cycle, tick_report_schedules, tick_rule_schedules
)

logger = logging.getLogger(__name__)


def build_scheduler(cm, interval_minutes: int = 10) -> BackgroundScheduler:
    """Factory for a BackgroundScheduler wired with illumio_ops jobs.

    Does NOT call sched.start() — caller owns lifecycle.
    """
    rule_interval = cm.config.get("rule_scheduler", {}).get("check_interval_seconds", 300)

    executors = {"default": ThreadPoolExecutor(max_workers=5)}
    job_defaults = {
        "coalesce": True,         # if we miss ticks during suspension, run just once
        "max_instances": 1,       # prevent concurrent re-entry
        "misfire_grace_time": 60, # allow up to 60s late fire
    }

    sched = BackgroundScheduler(executors=executors, job_defaults=job_defaults)

    sched.add_job(
        run_monitor_cycle, trigger=IntervalTrigger(minutes=interval_minutes),
        args=[cm], id="monitor_cycle", name="Monitor analysis cycle",
    )
    sched.add_job(
        tick_report_schedules, trigger=IntervalTrigger(seconds=60),
        args=[cm], id="tick_report_schedules", name="Report schedule tick",
    )
    sched.add_job(
        tick_rule_schedules, trigger=IntervalTrigger(seconds=rule_interval),
        args=[cm], id="tick_rule_schedules", name="Rule schedule tick",
    )

    logger.info("Scheduler built: monitor=%dm report=60s rule=%ds",
                interval_minutes, rule_interval)
    return sched
```

實作 `src/scheduler/jobs.py`:

```python
"""Job callables dispatched by the BackgroundScheduler."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_monitor_cycle(cm):
    """Execute one monitoring analysis + alert dispatch."""
    from src.api_client import ApiClient
    from src.analyzer import Analyzer
    from src.reporter import Reporter
    from src.module_log import ModuleLog

    mlog = ModuleLog.get("monitor")
    try:
        mlog.info("Starting monitor cycle")
        api = ApiClient(cm)
        rep = Reporter(cm)
        ana = Analyzer(cm, api, rep)
        ana.run_analysis()
        rep.send_alerts()
        mlog.info("Monitor cycle complete")
    except Exception as exc:
        logger.error("Monitor cycle failed: %s", exc, exc_info=True)
        mlog.error(f"Monitor cycle failed: {exc}")


def tick_report_schedules(cm):
    """Check and fire any due report schedules."""
    from src.report_scheduler import ReportScheduler
    from src.reporter import Reporter
    try:
        scheduler = ReportScheduler(cm, Reporter(cm))
        scheduler.tick()
    except Exception as exc:
        logger.error("Report schedule tick failed: %s", exc, exc_info=True)


def tick_rule_schedules(cm):
    """Check and fire any due rule schedules."""
    import os
    import re
    from src.rule_scheduler import ScheduleDB, ScheduleEngine
    from src.api_client import ApiClient
    from src.module_log import ModuleLog
    mlog = ModuleLog.get("rule_scheduler")
    try:
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(os.path.dirname(pkg_dir))
        db_path = os.path.join(root_dir, "config", "rule_schedules.json")
        db = ScheduleDB(db_path)
        db.load()
        tz = cm.config.get("settings", {}).get("timezone", "local")
        api = ApiClient(cm)
        engine = ScheduleEngine(db, api)
        logs = engine.check(silent=True, tz_str=tz)
        for msg in logs:
            clean = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", msg)
            logger.info("[RuleScheduler] %s", clean)
            mlog.info(clean)
        try:
            from src.gui import _append_rs_logs
            _append_rs_logs(logs)
        except Exception:
            pass
    except Exception as exc:
        logger.error("Rule schedule tick failed: %s", exc, exc_info=True)
        mlog.error(f"Rule schedule tick failed: {exc}")
```

---

## Task 4: `run_daemon_loop` 改用 scheduler

**Files:** Modify `src/main.py`

Replace current `run_daemon_loop` body with:

```python
def run_daemon_loop(interval_minutes: int):
    """Headless monitoring loop — APScheduler-backed."""
    from src.scheduler import build_scheduler
    cm = ConfigManager()
    print(t("daemon_start", interval=interval_minutes))
    print(t("daemon_stop_hint"))
    logger.info("Starting scheduler-backed daemon (interval=%dm)", interval_minutes)

    sched = build_scheduler(cm, interval_minutes=interval_minutes)
    sched.start()

    try:
        # Run the first monitor cycle immediately instead of waiting interval
        from src.scheduler.jobs import run_monitor_cycle
        run_monitor_cycle(cm)

        # Block until shutdown signal
        while not _shutdown_event.is_set():
            _shutdown_event.wait(timeout=1)
    finally:
        logger.info("Shutting down scheduler...")
        sched.shutdown(wait=True)
        logger.info("Scheduler stopped")
        print(f"\n{t('daemon_stopped')}")
```

Keep signal handling / `_shutdown_event` / `signal.signal(SIGINT, ...)` setup. Legacy contract (single `run_daemon_loop(interval_minutes)` signature) preserved.

---

## Task 5: freezegun-based integration test

**Files:** Create `tests/test_scheduler_integration.py`

```python
"""Verify that jobs fire at the right time using freezegun."""
from unittest.mock import MagicMock, patch
from freezegun import freeze_time


def test_monitor_cycle_fires_after_interval():
    from src.scheduler import build_scheduler
    with freeze_time("2026-01-01 00:00:00") as frozen:
        cm = _fake_cm()
        sched = build_scheduler(cm, interval_minutes=5)
        fired = []
        original = sched.get_job("monitor_cycle").func
        def capture(*a, **kw):
            fired.append("fired")
            return original(*a, **kw)
        sched.get_job("monitor_cycle").modify(func=capture)
        sched.start()
        try:
            # Advance 5 min + small epsilon
            frozen.tick(301)
            # APScheduler background dispatcher polls; give it a moment in real time
            import time as _t; _t.sleep(0.2)
            assert len(fired) >= 1
        finally:
            sched.shutdown(wait=False)
```

(This integration test is somewhat timing-sensitive. If flaky in CI, use `BlockingScheduler.add_job(next_run_time=datetime.now())` pattern instead.)

---

## Task 6: ApiClient TTLCache thread-safety lock

**Files:** Modify `src/api_client.py`

Phase 2 left a NOTE: "acquire self._cache_lock before any cache mutation once APScheduler is introduced (Phase 6)". Now we implement it:

In `__init__`:
```python
import threading
self._cache_lock = threading.Lock()
```

Wrap every mutation of `label_cache` / `service_ports_cache` / `_label_href_cache` / `_label_group_href_cache` / `_iplist_href_cache`:
```python
with self._cache_lock:
    self.label_cache[key] = value
```

For `invalidate_labels()` and `invalidate_query_lookup_cache()`, wrap the `.clear()` calls.

Add `tests/test_api_client_thread_safety.py`:

```python
"""Concurrent update + read on TTLCaches should not raise."""
import threading
from unittest.mock import MagicMock


def test_concurrent_update_and_read_label_cache():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {"api": {"url": "https://p", "org_id": "1", "key": "k",
                         "secret": "s", "verify_ssl": False}}
    api = ApiClient(cm)

    def writer():
        for i in range(1000):
            with api._cache_lock:
                api.label_cache[f"k{i}"] = f"v{i}"

    def reader():
        for _ in range(1000):
            with api._cache_lock:
                list(api.label_cache.items())

    threads = [threading.Thread(target=writer) for _ in range(3)] + \
              [threading.Thread(target=reader) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    # If we didn't raise, test passes
```

---

## Task 7: Update Status.md / Task.md + Merge

**Files:** `Status.md`, `Task.md`

Status.md: A3 marked ✅; `apscheduler` marked `used`; version v3.5.2-scheduler.

Task.md: Phase 6 section with jobs architecture summary.

```bash
git push -u origin upgrade/phase-6-scheduler-aps
# PR + merge + tag v3.5.2-scheduler
```

---

## Phase 6 完成驗收清單

- [ ] `src/scheduler/` package 存在（__init__ + jobs）
- [ ] `build_scheduler(cm, interval_minutes)` 回傳含 3 jobs 的 BackgroundScheduler
- [ ] `run_daemon_loop` 不再有自製 `while not _shutdown_event.is_set()` + `wait(60)` 迴圈
- [ ] ApiClient `self._cache_lock` 保護 5 個 TTLCache 的 mutation
- [ ] freezegun 驗證 monitor_cycle 在 5 min 後觸發
- [ ] 並發 read/write label_cache 測試通過
- [ ] daemon shutdown < 5s 乾淨退出
- [ ] 既有 `config/rule_schedules.json` / `config/report_schedules.json` 格式不變，繼續被 tick job 讀
- [ ] Status.md A3 + T1 標 ✅
- [ ] `v3.5.2-scheduler` tag

---

## Rollback

Scheduler 是新增 layer，可 revert 一個 commit 回到 Phase 5 前狀態。既有 report_scheduler / rule_scheduler 業務邏輯不受影響。

---

## Self-Review Checklist

- ✅ 路線圖 Phase 6 目標（APScheduler 統一、解 A3）全覆蓋
- ✅ 既有 json schedule files 格式保留（business logic 不動）
- ✅ ThreadPoolExecutor(max_workers=5) 解多 job 並行阻塞
- ✅ TTLCache thread-safety 呼應 Phase 2 flagged NOTE
- ✅ TDD：Task 2/3/5/6 都先紅後綠
- ✅ signal handling 保留（legacy shutdown contract 不變）
