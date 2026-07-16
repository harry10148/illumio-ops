# Phase A：可觀測性 backlog 六項修復 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓每個背景 job 的「應跑未跑」在 GUI 一眼可見，並修掉 2026-07-16 全面掃描列出的六個可觀測性缺口（job 健康儲存與面板、SIEM 誤綠、rule 排程 last_run、summary 新鮮度、TLS 憑證天數、告警通道測試送信）。

**Architecture:** 新增薄模組 `src/job_health.py`（複用 `state_store.update_state_file` 的鎖＋原子寫，落地 `logs/job_health.json`）；`build_scheduler` 用 generic wrapper 包所有 job 記錄 last_run/status；GUI 由 `/api/dashboard/overview` 增量暴露 `job_health`/`tls`，整合 tab overview 子頁加「Job 健康」表格卡。SIEM 誤綠在 `_overview_pipeline` 補 idle 判定傳入 `pipeline_verdict`。rule 排程仿 report scheduler 的 `rule_schedule_states` 寫進 state.json。其餘為既有結構的小幅增量。

**Tech Stack:** Python（Flask routes、APScheduler、orjson/json）、vanilla JS（integrations.js/dashboard.js/settings.js/rule-scheduler.js，CSP data-action 委派）、pytest 靜態＋HTTP harness。

## Global Constraints

- 程式註解繁中，但 **JS/HTML 禁止「行尾」CJK 註解**（i18n audit Cat C 只豁免整行註解）；Python 無此限制。
- i18n：每個新 key 同步進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`（平鋪、字母序位置）；zh 譯文遵守 glossary（Offline/Online/Policy/Sync/SIEM/DLQ/Job 等詞保留英文）。
- CSP：動態 DOM 事件一律 `data-action="fnName" data-args='[...]'` 委派到 `window.fnName`；不得 inline onclick。
- CSS：新樣式沿用整合頁既有 class（`.cards`/`.card card-ok|card-warn|card-err|card-neutral`/`.label`/`.value`/`.table-container`/`.rule-table`），不新增 magic margin/padding。
- 時間戳一律 UTC ISO-Z：`datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`。
- job_health 寫入節流：同一 job 距上次寫入 < 60 秒不重寫（秒級 tick job 防磁碟churn）。
- 每個 task 完成時跑該 task 的測試檔＋`pytest tests/test_i18n_glossary.py tests/test_i18n_audit.py -q`（防 Cat C/E 回歸）。
- Commit 訊息英文 conventional commits；不用 emoji。
- Subagent 執行紀律：worktree 內工作、開工與 commit 前驗證 `pwd` 與 `git branch --show-current`、絕不 `git checkout/merge/reset/branch`、絕不 cd 到主 checkout。

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `src/job_health.py` | Create | job 健康儲存（record/load、節流、路徑解析） |
| `src/scheduler/__init__.py` | Modify | generic `_instrument` wrapper 包所有 add_job |
| `src/gui/routes/dashboard.py` | Modify | overview 增 `job_health`/`tls`；`_overview_pipeline` SIEM idle |
| `src/pce_cache/health.py` | Modify | `pipeline_verdict` 增 `siem_idle` 參數 |
| `src/scheduler/jobs.py` | Modify | ven/posture summary 增 `computed_at`；新 `run_tls_renew_check` |
| `src/rule_scheduler.py` | Modify | `ScheduleEngine.check` 寫 `rule_schedule_states` |
| `src/gui/routes/rule_scheduler.py` | Modify | `rs_schedules_list` enrich last_run |
| `src/static/js/integrations.js` | Modify | overview 子頁加 Job 健康表格卡＋TLS 卡 |
| `src/static/js/dashboard.js` | Modify | ven/posture tile 顯示資料齡與 stale 標灰 |
| `src/static/js/rule-scheduler.js` + `src/templates/index.html` | Modify | 排程列表加「上次執行」欄 |
| `src/static/js/settings.js` | Modify | 通道卡加「送測試」按鈕（複用 /api/actions/test-alert） |
| `src/i18n_en.json` / `src/i18n_zh_TW.json` | Modify | 新 gui_jh_* / gui_ov_* / gui_rs_* / gui_set_* key |
| `tests/test_job_health.py` 等 | Create/Modify | 各 task 對應測試 |

---

### Task 1: job_health 儲存模組 + scheduler generic wrapper

**Files:**
- Create: `src/job_health.py`
- Modify: `src/scheduler/__init__.py`（build_scheduler 內、所有 add_job）
- Test: `tests/test_job_health.py`（新）

**Interfaces:**
- Consumes: `src/state_store.update_state_file(state_file, updater)`、`load_state_file(state_file)`（鎖＋原子寫）。
- Produces（後續 task 依賴的確切名稱）:
  - `job_health.record_job_run(job_id: str, status: str, detail: str = "", *, interval_seconds: int | None = None, min_write_gap_seconds: int = 60) -> None`
  - `job_health.record_job_registered(job_id: str, interval_seconds: int) -> None`
  - `job_health.load_job_health() -> dict`（`{job_id: {"last_run","last_status","detail","interval_seconds","registered_at"}}`）
  - `job_health._job_health_file() -> str`（測試 monkeypatch 點，回 `<root>/logs/job_health.json`）
  - scheduler 內部：`_instrument(job_id: str, fn, interval_seconds: int)`（wrapper，非公開介面）
  - JSON 檔記錄 status 值域：`"ok" | "error" | "registered"`。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_job_health.py`：

```python
"""job 健康儲存（2026-07-16 可觀測性 backlog）：每個排程 job 記錄
last_run/status，讓「應跑未跑」在 GUI 可見（archive 事故的根治配套）。"""
from __future__ import annotations

import datetime
import json

import pytest

from src import job_health


@pytest.fixture()
def jh_file(tmp_path, monkeypatch):
    path = str(tmp_path / "job_health.json")
    monkeypatch.setattr(job_health, "_job_health_file", lambda: path)
    return path


def test_record_and_load_roundtrip(jh_file):
    job_health.record_job_registered("pce_cache_archive", 86400)
    job_health.record_job_run("pce_cache_archive", "ok", detail="rows=12")
    data = job_health.load_job_health()
    entry = data["pce_cache_archive"]
    assert entry["last_status"] == "ok"
    assert entry["detail"] == "rows=12"
    assert entry["interval_seconds"] == 86400
    assert entry["last_run"].endswith("Z")
    assert entry["registered_at"].endswith("Z")


def test_registered_does_not_clobber_last_run(jh_file):
    """重啟時 record_job_registered 不得洗掉上一輪的 last_run/status。"""
    job_health.record_job_run("ven_summary", "ok", interval_seconds=300)
    before = job_health.load_job_health()["ven_summary"]["last_run"]
    job_health.record_job_registered("ven_summary", 300)
    after = job_health.load_job_health()["ven_summary"]
    assert after["last_run"] == before
    assert after["last_status"] == "ok"
    assert after["interval_seconds"] == 300


def test_error_status_recorded(jh_file):
    job_health.record_job_run("monitor_cycle", "error", detail="boom", interval_seconds=30)
    entry = job_health.load_job_health()["monitor_cycle"]
    assert entry["last_status"] == "error"
    assert entry["detail"] == "boom"


def test_write_throttle_skips_recent(jh_file):
    """秒級 tick job（monitor 30s/siem tick）不得每次都重寫磁碟：
    60 秒內的重複 ok 寫入直接略過。"""
    job_health.record_job_run("siem_dispatch", "ok", interval_seconds=5)
    first = json.load(open(jh_file))["siem_dispatch"]["last_run"]
    job_health.record_job_run("siem_dispatch", "ok", interval_seconds=5)
    second = json.load(open(jh_file))["siem_dispatch"]["last_run"]
    assert second == first


def test_write_throttle_never_skips_errors_or_status_change(jh_file):
    job_health.record_job_run("siem_dispatch", "ok", interval_seconds=5)
    job_health.record_job_run("siem_dispatch", "error", detail="x", interval_seconds=5)
    assert job_health.load_job_health()["siem_dispatch"]["last_status"] == "error"


def test_scheduler_jobs_are_instrumented(tmp_path, monkeypatch):
    """build_scheduler 註冊的每個 job 都必須：(a) 種下 registered 記錄；
    (b) func 為 instrument wrapper（執行時會寫 last_run）。"""
    path = str(tmp_path / "job_health.json")
    monkeypatch.setattr(job_health, "_job_health_file", lambda: path)
    from unittest.mock import MagicMock
    from src.scheduler import build_scheduler
    cm = MagicMock()
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.db_path = str(tmp_path / "c.sqlite")
    cm.models.pce_cache.archive_enabled = True
    cm.models.pce_cache.archive_dir = str(tmp_path / "archive")
    cm.models.pce_cache.archive_interval_hours = 24
    cm.models.pce_cache.archive_gzip_after_days = 7
    cm.models.pce_cache.archive_retention_days = 0
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.siem.enabled = False
    cm.config = {}
    sched = build_scheduler(cm)
    try:
        data = job_health.load_job_health()
        for job in sched.get_jobs():
            assert job.id in data, f"{job.id} 未種下 registered 記錄"
            assert data[job.id]["last_status"] in ("registered", "ok", "error")
            assert data[job.id]["interval_seconds"] > 0
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_job_health.py -v`
Expected: 全部 FAIL（`ModuleNotFoundError: src.job_health`）。

- [ ] **Step 3: 實作 `src/job_health.py`**

```python
"""Job 健康儲存：每個排程 job 的 last_run / last_status 落地 logs/job_health.json。

2026-07-14 archive 事故的根治配套——「應跑未跑」必須可觀測。複用
state_store 的檔案鎖＋原子寫（多 executor 執行緒併發寫同檔）。
寫入節流：同 job 60 秒內的重複 ok 寫入略過（秒級 tick job 防磁碟 churn）；
error 或狀態變化一律寫。
"""
from __future__ import annotations

import datetime
import os

from src.state_store import load_state_file, update_state_file


def _job_health_file() -> str:
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(pkg_dir)
    return os.path.join(root_dir, "logs", "job_health.json")


def _now_z() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_job_health() -> dict:
    return load_state_file(_job_health_file())


def record_job_registered(job_id: str, interval_seconds: int) -> None:
    """排程註冊時種下記錄：讓「從未跑過」立即可見，且不得洗掉既有 last_run。"""
    now = _now_z()

    def _merge(data: dict) -> dict:
        entry = dict(data.get(job_id) or {})
        entry.setdefault("last_status", "registered")
        entry["interval_seconds"] = int(interval_seconds)
        entry["registered_at"] = now
        data[job_id] = entry
        return data

    _safe_update(_merge)


def record_job_run(job_id: str, status: str, detail: str = "", *,
                   interval_seconds: int | None = None,
                   min_write_gap_seconds: int = 60) -> None:
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    if status == "ok":
        # 節流前置檢查（無鎖快速路徑）：距上次同狀態寫入太近就略過
        try:
            prev = load_job_health().get(job_id) or {}
            if prev.get("last_status") == "ok" and prev.get("last_run"):
                last = datetime.datetime.strptime(
                    prev["last_run"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=datetime.timezone.utc)
                if (now_dt - last).total_seconds() < min_write_gap_seconds:
                    return
        except Exception:
            pass

    def _merge(data: dict) -> dict:
        entry = dict(data.get(job_id) or {})
        entry["last_run"] = now
        entry["last_status"] = status
        entry["detail"] = str(detail)[:300]
        if interval_seconds is not None:
            entry["interval_seconds"] = int(interval_seconds)
        data[job_id] = entry
        return data

    _safe_update(_merge)


def _safe_update(merge) -> None:
    """健康記錄是輔助訊號：寫入失敗絕不影響 job 本體，吞掉並靜默。"""
    try:
        os.makedirs(os.path.dirname(_job_health_file()), exist_ok=True)
        update_state_file(_job_health_file(), merge)
    except Exception:
        pass
```

- [ ] **Step 4: 在 build_scheduler 加 generic wrapper**

`src/scheduler/__init__.py`，`_kick0` 定義之後插入：

```python
    # 每個 job 都包 instrument wrapper：執行後寫 logs/job_health.json 的
    # last_run/status（「應跑未跑」可觀測化，archive 事故根治配套）。
    # 註冊當下先種 registered 記錄，讓從未跑過的 job 立即可見。
    import functools as _ft
    from src.job_health import record_job_registered, record_job_run

    def _instrument(job_id, fn, interval_seconds):
        record_job_registered(job_id, interval_seconds)

        @_ft.wraps(fn)
        def _run(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                record_job_run(job_id, "error", str(exc),
                               interval_seconds=interval_seconds)
                raise
            record_job_run(job_id, "ok", interval_seconds=interval_seconds)
            return result
        return _run
```

然後把**每個** `sched.add_job(<fn>, ...)` 的第一參數改為 `_instrument("<job_id>", <fn>, <interval 秒數>)`，job_id 與 `id=` 完全一致，interval 秒數與 trigger 一致。逐一列出（照現行檔案順序）：

| id | 包法 |
|---|---|
| `monitor_cycle` | `_instrument("monitor_cycle", run_monitor_cycle, 30 if _cache_enabled else interval_minutes * 60)` |
| `tick_report_schedules` | `_instrument("tick_report_schedules", tick_report_schedules, 60)` |
| `tick_rule_schedules` | `_instrument("tick_rule_schedules", tick_rule_schedules, rule_interval)` |
| `ven_summary` | `_instrument("ven_summary", run_ven_summary, ven_summary_interval)` |
| `posture_summary` | `_instrument("posture_summary", run_posture_summary, posture_summary_interval)` |
| `pce_cache_ingest_events` | `_instrument("pce_cache_ingest_events", run_events_ingest, cache_cfg.events_poll_interval_seconds)` |
| `pce_cache_ingest_traffic` | `_instrument("pce_cache_ingest_traffic", run_traffic_ingest, cache_cfg.traffic_poll_interval_seconds)` |
| `pce_cache_aggregate` | `_instrument("pce_cache_aggregate", run_traffic_aggregate, 3600)` |
| `pce_cache_retention` | `_instrument("pce_cache_retention", run_cache_retention, 86400)` |
| `cache_lag_monitor` | `_instrument("cache_lag_monitor", run_cache_lag_monitor, 60)` |
| `pce_cache_capacity_monitor` | `_instrument("pce_cache_capacity_monitor", run_capacity_monitor, 1800)` |
| `pce_cache_archive` | `_instrument("pce_cache_archive", run_cache_archive, cache_cfg.archive_interval_hours * 3600)` |
| `siem_dispatch` | `_instrument("siem_dispatch", run_siem_dispatch, siem_cfg.dispatch_tick_seconds)` |

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest tests/test_job_health.py tests/test_scheduler_cache_archive.py tests/test_scheduler_intervals.py tests/test_scheduler_integration.py tests/test_daemon_contract.py tests/test_state_store.py -v`
Expected: 全數 PASS（既有 scheduler 測試不回歸；`test_scheduler_integration` 用 `.modify(func=...)` 換函式，與 wrapper 無衝突）。

- [ ] **Step 6: Commit**

```bash
git add src/job_health.py src/scheduler/__init__.py tests/test_job_health.py
git commit -m "feat(observability): job health store and scheduler instrumentation"
```

---

### Task 2: overview API 暴露 job_health（含 overdue 判定）與 TLS 憑證資訊

**Files:**
- Modify: `src/gui/routes/dashboard.py`（`api_dashboard_overview` :307-327、新增兩個 `_overview_*` helper）
- Test: `tests/test_dashboard_overview.py`（沿用既有 HTTP harness fixture）

**Interfaces:**
- Consumes: Task 1 的 `job_health.load_job_health()`；`src/gui/_helpers._cert_days_remaining(cert_path)`、`_get_cert_info(cert_path)`（既有）。
- Produces: overview 回應新增兩個 top-level key（Task 3/7 前端消費）：
  - `"job_health": [{"job_id","last_run","last_status","detail","interval_seconds","level"}]`，`level ∈ ok|warn|error`；排序 error → warn → ok、同級按 job_id。
  - `"tls": {"enabled": bool, "days_remaining": int|None, "expiring_soon": bool}`。
- overdue 判定：`last_status=="error"` → error；`last_status=="registered"` 且 `now-registered_at > max(2*interval, 600s)` → warn（never ran）；`last_run` 距今 > `max(2*interval, 600s)` → warn（overdue）；否則 ok。

- [ ] **Step 1: 寫失敗測試**

`tests/test_dashboard_overview.py` 檔尾新增（沿用該檔既有 `client` fixture 與 login 慣例；fixture 名稱以檔內現行為準，下方以 `client` 表示）：

```python
def test_overview_includes_job_health(client, tmp_path, monkeypatch):
    """2026-07-16 可觀測性 backlog：overview 必須回 job_health 清單，
    從未跑過（registered 超過 2×interval）與逾期的 job 標 warn。"""
    import datetime
    from src import job_health as jh
    path = str(tmp_path / "job_health.json")
    monkeypatch.setattr(jh, "_job_health_file", lambda: path)
    import src.gui.routes.dashboard as dash
    monkeypatch.setattr(dash.job_health, "_job_health_file", lambda: path,
                        raising=False)
    now = datetime.datetime.now(datetime.timezone.utc)
    old = (now - datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    jh.update_or_seed = None  # 佔位避免誤用
    import json as _json
    _json.dump({
        "pce_cache_archive": {"last_status": "registered",
                               "registered_at": old, "interval_seconds": 3600},
        "ven_summary": {"last_run": fresh, "last_status": "ok",
                         "detail": "", "interval_seconds": 300},
        "pce_cache_retention": {"last_run": old, "last_status": "ok",
                                 "detail": "", "interval_seconds": 1800},
        "monitor_cycle": {"last_run": fresh, "last_status": "error",
                           "detail": "boom", "interval_seconds": 30},
    }, open(path, "w"))
    r = client.get("/api/dashboard/overview",
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    body = r.get_json()
    levels = {e["job_id"]: e["level"] for e in body["job_health"]}
    assert levels["pce_cache_archive"] == "warn"      # never ran
    assert levels["pce_cache_retention"] == "warn"    # overdue（3h > 2×30m）
    assert levels["ven_summary"] == "ok"
    assert levels["monitor_cycle"] == "error"
    order = [e["level"] for e in body["job_health"]]
    assert order == sorted(order, key=lambda v: {"error": 0, "warn": 1, "ok": 2}[v])


def test_overview_includes_tls(client, monkeypatch):
    import src.gui.routes.dashboard as dash
    monkeypatch.setattr(dash, "_tls_overview",
                        lambda cm: {"enabled": True, "days_remaining": 12,
                                    "expiring_soon": True})
    r = client.get("/api/dashboard/overview",
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    body = r.get_json()
    assert body["tls"]["days_remaining"] == 12
    assert body["tls"]["expiring_soon"] is True
```

（實作時若既有 fixture 名不同，沿用檔內名稱；`jh.update_or_seed = None` 一行刪除——為測試草稿殘句，不得保留。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_dashboard_overview.py -v -k "job_health or tls"`
Expected: KeyError `job_health` / `tls`。

- [ ] **Step 3: 實作 dashboard.py**

檔頭 import 區加 `from src import job_health`。在 `_overview_pipeline` 附近新增：

```python
def _overview_job_health():
    """job_health.json → 前端清單；level: error（上次失敗）/ warn（從未跑或
    逾期 > max(2×interval, 600s)）/ ok。error → warn → ok 排序。"""
    import datetime as _dt

    def _parse(ts):
        try:
            return _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=_dt.timezone.utc)
        except Exception:
            return None

    now = _dt.datetime.now(_dt.timezone.utc)
    out = []
    try:
        data = job_health.load_job_health()
    except Exception:
        return out
    for job_id, entry in (data or {}).items():
        if not isinstance(entry, dict):
            continue
        interval = int(entry.get("interval_seconds") or 0)
        grace = max(2 * interval, 600)
        status = entry.get("last_status") or ""
        level = "ok"
        if status == "error":
            level = "error"
        elif status == "registered":
            reg = _parse(entry.get("registered_at") or "")
            if reg is None or (now - reg).total_seconds() > grace:
                level = "warn"
        else:
            last = _parse(entry.get("last_run") or "")
            if last is None or (now - last).total_seconds() > grace:
                level = "warn"
        out.append({
            "job_id": job_id,
            "last_run": entry.get("last_run"),
            "last_status": status,
            "detail": entry.get("detail", ""),
            "interval_seconds": interval,
            "level": level,
        })
    rank = {"error": 0, "warn": 1, "ok": 2}
    out.sort(key=lambda e: (rank.get(e["level"], 3), e["job_id"]))
    return out


def _tls_overview(cm):
    """TLS 憑證天數（self-signed 或自備憑證）；GUI 未啟用 TLS 回 enabled=False。"""
    from src.gui._helpers import _cert_days_remaining
    try:
        tls_cfg = (cm.config.get("web_gui") or {}).get("tls") or {}
        if not tls_cfg.get("enabled", True):
            return {"enabled": False, "days_remaining": None, "expiring_soon": False}
        if tls_cfg.get("self_signed", True):
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            cert_path = os.path.join(root_dir, "config", "tls", "self_signed.pem")
        else:
            cert_path = tls_cfg.get("cert_file") or ""
        days = _cert_days_remaining(cert_path) if cert_path else None
        warn_days = int(tls_cfg.get("auto_renew_days", 30))
        return {"enabled": True, "days_remaining": days,
                "expiring_soon": days is not None and days <= warn_days}
    except Exception:
        return {"enabled": True, "days_remaining": None, "expiring_soon": False}
```

`api_dashboard_overview` 回應 dict 加兩行：

```python
        "job_health": _overview_job_health(),
        "tls": _tls_overview(cm),
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_dashboard_overview.py tests/test_pipeline_observability.py -v`
Expected: 全數 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/gui/routes/dashboard.py tests/test_dashboard_overview.py
git commit -m "feat(observability): expose job health and tls cert status in overview api"
```

---

### Task 3: 整合頁「Job 健康」表格卡 + TLS 卡（前端）

**Files:**
- Modify: `src/static/js/integrations.js`（overview render :1489-1500、卡片建構函式群 :1378-1487 附近）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_gui_job_health_panel.py`（新，靜態字串斷言）

**Interfaces:**
- Consumes: Task 2 的 overview `job_health`/`tls`。
- Produces: `_buildOvJobHealth(jobHealth)`、`_buildOvTlsCard(tls)`（integrations.js 內部函式，靜態測試鎖定字面）。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_gui_job_health_panel.py`：

```python
"""整合頁 Job 健康表格卡（靜態字串斷言，比照本 repo JS 測試慣例）。"""
from pathlib import Path

_JS = Path("src/static/js/integrations.js")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")


def test_overview_pane_fetches_dashboard_overview():
    js = _JS.read_text(encoding="utf-8")
    assert "/api/dashboard/overview" in js


def test_job_health_table_card_present():
    js = _JS.read_text(encoding="utf-8")
    fn = js.split("function _buildOvJobHealth(", 1)[1].split("\nfunction ", 1)[0]
    for frag in ("gui_ov_job_health", "gui_jh_th_job", "gui_jh_th_last_run",
                 "gui_jh_th_status", "gui_jh_never_ran",
                 "table-container", "rule-table"):
        assert frag in fn, frag


def test_tls_card_present():
    js = _JS.read_text(encoding="utf-8")
    fn = js.split("function _buildOvTlsCard(", 1)[1].split("\nfunction ", 1)[0]
    assert "gui_ov_tls_cert" in fn
    assert "card-warn" in fn


def test_job_health_i18n_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_ov_job_health", "gui_jh_th_job", "gui_jh_th_last_run",
              "gui_jh_th_status", "gui_jh_th_interval", "gui_jh_th_detail",
              "gui_jh_never_ran", "gui_jh_overdue", "gui_ov_tls_cert",
              "gui_ov_tls_days", "gui_ov_tls_expiring"):
        assert k in en and k in zh, k
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_gui_job_health_panel.py -v`
Expected: FAIL（函式與 key 不存在）。

- [ ] **Step 3: 實作 integrations.js**

(a) overview render 的 `Promise.all` 陣列加一項 `fetch('/api/dashboard/overview').then(function(r){return r.ok ? r.json() : null;}).catch(function(){return null;})`，解構變數命名 `ovv`（與既有變數不衝突）。

(b) 卡片建構函式（放在 `_buildOvRecentTable` 之後；**註解必須整行、不得行尾 CJK**）：

```js
// Job 健康表格卡：每個排程 job 的上次執行與狀態（error/warn 置頂）。
// level 由後端判定：error=上次失敗、warn=從未跑或逾期、ok=正常。
function _buildOvJobHealth(jobHealth) {
  var list = jobHealth || [];
  if (!list.length) return '';
  var rows = list.map(function (e) {
    var mark = e.level === 'error' ? 'var(--color-danger,#f43f5e)'
      : e.level === 'warn' ? 'var(--color-warning,#f59e0b)'
      : 'var(--color-success,#22c55e)';
    var lastRun = e.last_run ? escapeHtml(e.last_run)
      : '<span data-i18n="gui_jh_never_ran">never ran</span>';
    var statusTxt = e.level === 'warn' && e.last_run
      ? (escapeHtml(e.last_status) + ' · <span data-i18n="gui_jh_overdue">overdue</span>')
      : escapeHtml(e.last_status || '');
    var mins = e.interval_seconds >= 3600
      ? (Math.round(e.interval_seconds / 3600) + 'h')
      : (Math.round(e.interval_seconds / 60) + 'm');
    return '<tr>'
      + '<td><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + mark + ';margin-right:6px;"></span>'
      + escapeHtml(e.job_id) + '</td>'
      + '<td>' + lastRun + '</td>'
      + '<td>' + statusTxt + '</td>'
      + '<td>' + mins + '</td>'
      + '<td>' + escapeHtml(e.detail || '') + '</td>'
      + '</tr>';
  }).join('');
  return '<h3 style="color:var(--accent2);font-size:.9rem;font-weight:700;margin:16px 0 8px;" data-i18n="gui_ov_job_health">Job Health</h3>'
    + '<div class="table-container"><table class="rule-table">'
    + '<thead><tr>'
    + '<th data-i18n="gui_jh_th_job">Job</th>'
    + '<th data-i18n="gui_jh_th_last_run">Last Run</th>'
    + '<th data-i18n="gui_jh_th_status">Status</th>'
    + '<th data-i18n="gui_jh_th_interval">Interval</th>'
    + '<th data-i18n="gui_jh_th_detail">Detail</th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
}

// TLS 憑證卡：剩餘天數；低於 auto_renew_days 門檻標 warn。
function _buildOvTlsCard(tls) {
  if (!tls || !tls.enabled) return '';
  var warn = !!tls.expiring_soon;
  var days = (tls.days_remaining == null) ? '—' : String(tls.days_remaining);
  var cls = warn ? 'card-warn' : 'card-ok';
  return '<div class="cards" style="margin-bottom:8px;">'
    + '<div class="card ' + cls + '" style="flex:0 0 auto;min-width:160px;">'
    + '<div class="label" data-i18n="gui_ov_tls_cert">TLS Certificate</div>'
    + '<div class="value">' + days + ' <span data-i18n="gui_ov_tls_days">days</span></div>'
    + (warn ? '<div style="font-size:.7rem;color:var(--dim);margin-top:4px;" data-i18n="gui_ov_tls_expiring">Expiring soon</div>' : '')
    + '</div></div>';
}
```

(c) renderOverview 組版處，在管線健康卡（`_buildOvPipelineHealth(health)`）之後插入 `+ _buildOvTlsCard(ovv && ovv.tls)`，在 Recent dispatch 表之前插入 `+ _buildOvJobHealth(ovv && ovv.job_health)`；render 完呼叫既有 i18n apply（該檔既有慣例函式，照現行 render 流程末尾用法）。

(d) i18n 兩檔各加（en / zh_TW，字母序插入；zh 保留 Job/Run/Status/TLS 英文）：

```json
"gui_jh_never_ran": "never ran",
"gui_jh_overdue": "overdue",
"gui_jh_th_detail": "Detail",
"gui_jh_th_interval": "Interval",
"gui_jh_th_job": "Job",
"gui_jh_th_last_run": "Last Run",
"gui_jh_th_status": "Status",
"gui_ov_job_health": "Job Health",
"gui_ov_tls_cert": "TLS Certificate",
"gui_ov_tls_days": "days",
"gui_ov_tls_expiring": "Expiring soon — renew or restart to apply"
```

```json
"gui_jh_never_ran": "從未執行",
"gui_jh_overdue": "逾期",
"gui_jh_th_detail": "備註",
"gui_jh_th_interval": "間隔",
"gui_jh_th_job": "Job",
"gui_jh_th_last_run": "上次執行",
"gui_jh_th_status": "狀態",
"gui_ov_job_health": "Job 健康",
"gui_ov_tls_cert": "TLS 憑證",
"gui_ov_tls_days": "天",
"gui_ov_tls_expiring": "即將到期——請續期或重啟套用"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_gui_job_health_panel.py tests/test_i18n_glossary.py tests/test_i18n_audit.py -v`
Expected: 全數 PASS（Cat C：新 JS 註解皆整行）。

- [ ] **Step 5: Commit**

```bash
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json tests/test_gui_job_health_panel.py
git commit -m "feat(gui): job health table and tls certificate card on integrations overview"
```

---

### Task 4: SIEM 誤綠修復（enabled 但空轉 → warn）

**Files:**
- Modify: `src/pce_cache/health.py`（pipeline_verdict）
- Modify: `src/gui/routes/dashboard.py`（`_overview_pipeline` :100-137）
- Test: `tests/test_pipeline_observability.py`

**Interfaces:**
- Consumes: 既有 `SiemDispatch`（`queued_at` 欄）、`cm.models.siem`（`enabled`、`destinations[].enabled`）。
- Produces: `pipeline_verdict(*, lag_levels, siem_success_1h, denom, dlq, dlq_cap=10000, siem_idle=False)`——新 keyword 參數，預設 False（既有呼叫不變）；`_overview_pipeline` 回傳 dict 增 `"siem_idle": bool`。
- `siem_idle` 定義（route 端計算）：`siem.enabled` 且（無任何 enabled destination，**或** 近 24h `SiemDispatch.queued_at` 計數為 0 而 cache_lag 顯示 ingest 有資料（任一 source 的 lag 非 None））。

- [ ] **Step 1: 修改測試（RED）**

`tests/test_pipeline_observability.py` 的 `test_pipeline_verdict_thresholds`（:41-49）調整：保留 `denom=0, dlq=0` → `"ok"` 的斷言（no traffic 且未標 idle 仍健康），**新增**：

```python
def test_pipeline_verdict_siem_idle_is_warn():
    """SIEM enabled 但空轉（無啟用目的地，或有資料卻 24h 零 enqueue）不得綠燈：
    2026-07-16 掃描抓到 denom=0 短路讓「SIEM 完全沒動」誤判 ok。"""
    from src.pce_cache.health import pipeline_verdict
    assert pipeline_verdict(lag_levels=[], siem_success_1h=100.0,
                            denom=0, dlq=0, siem_idle=True) == "warn"
    assert pipeline_verdict(lag_levels=[], siem_success_1h=100.0,
                            denom=0, dlq=0, siem_idle=False) == "ok"


def test_overview_pipeline_flags_siem_idle_when_no_enabled_destination(tmp_path):
    """siem.enabled=true、destinations 全 disabled → pipeline verdict=warn、
    siem_idle=true。沿用本檔既有 HTTP fixture 建 app（config 含 siem 區塊）。"""
    # 實作時沿用本檔既有 fixture 模式：config 增
    #   "siem": {"enabled": True, "destinations": [
    #       {"name": "x", "enabled": False, "host": "h", "port": 514}]}
    # после login，GET /api/dashboard/overview，斷言：
    #   body["pipeline"]["siem_idle"] is True
    #   body["pipeline"]["verdict"] in ("warn", "error")
```

（第二個測試依檔內既有 fixture 樣式落地完整可執行版本——上方註解為需求描述，交付碼不得留註解版，必須是可執行 assert。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_pipeline_observability.py -v`
Expected: 新測試 FAIL（TypeError: unexpected keyword `siem_idle` / KeyError `siem_idle`）。

- [ ] **Step 3: 實作**

`src/pce_cache/health.py`：

```python
def pipeline_verdict(*, lag_levels, siem_success_1h, denom, dlq,
                     dlq_cap=10000, siem_idle=False):
    """整體管線判定。siem_idle＝SIEM 啟用但空轉（無啟用目的地，或來源有資料
    而 24h 零 enqueue）——denom=0 的「無流量」與「壞掉沒在送」必須可區分，
    後者至少 warn（2026-07-16 誤綠修復）。"""
    lag_err = any(l == "error" for l in (lag_levels or []))
    lag_warn = any(l == "warning" for l in (lag_levels or []))
    if lag_err or (denom and siem_success_1h < 95) or dlq >= int(dlq_cap * 0.8):
        return "error"
    if lag_warn or (denom and siem_success_1h < 99) or dlq > 0 or siem_idle:
        return "warn"
    return "ok"
```

`_overview_pipeline`（dashboard.py）在 SIEM 統計段之後補：

```python
        siem_idle = False
        try:
            siem_cfg = cm.models.siem
            if getattr(siem_cfg, "enabled", False):
                dests = [d for d in (getattr(siem_cfg, "destinations", None) or [])
                         if getattr(d, "enabled", False)]
                if not dests:
                    siem_idle = True
                else:
                    day_ago = now - datetime.timedelta(hours=24)
                    enq_24h = s.execute(
                        select(func.count()).select_from(SiemDispatch)
                        .where(SiemDispatch.queued_at >= day_ago)).scalar() or 0
                    has_source_data = any(
                        c.get("lag_s") is not None for c in cache_lag)
                    siem_idle = enq_24h == 0 and has_source_data
        except Exception:
            siem_idle = False
```

verdict 呼叫傳入 `siem_idle=siem_idle`，回傳 dict 增 `"siem_idle": siem_idle`。（`now`/`select`/`func` 依該函式現有 import 與變數；`day_ago` 查詢須放在既有 `with session_factory() as s:` 區塊內。）

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_pipeline_observability.py tests/test_dashboard_overview.py -v`
Expected: 全數 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/health.py src/gui/routes/dashboard.py tests/test_pipeline_observability.py
git commit -m "fix(health): siem enabled-but-idle no longer reads as green"
```

---

### Task 5: rule 排程 per-schedule last_run（仿 report scheduler）

**Files:**
- Modify: `src/rule_scheduler.py`（`ScheduleEngine.check` :214-325）
- Modify: `src/gui/routes/rule_scheduler.py`（`rs_schedules_list` :233）
- Modify: `src/static/js/rule-scheduler.js`（`rsLoadSchedules` :480-560）、`src/templates/index.html`（排程表 thead :2286-2309、colspan 12→13）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_rule_scheduler.py`、`tests/test_gui_job_health_panel.py`（JS 靜態斷言附掛）

**Interfaces:**
- Consumes: `src.state_store.update_state_file/load_state_file`、`src.gui._helpers._resolve_state_file`。
- Produces: state.json 新 key `rule_schedule_states`：`{href: {"last_checked","last_action","last_result","error"}}`；`GET /api/rule_scheduler/schedules` 每筆 enrich `last_checked/last_action/last_result`。
- 寫入語意：`check()` 每 tick 結束以**單一** `update_state_file` merge 全部 schedule 的 `last_checked`（ISO-Z）；有動作嘗試者另記 `last_action`（`enable|disable|expire`）與 `last_result`（`ok|error`）＋`error` 訊息（截 300 字）。

- [ ] **Step 1: 寫失敗測試**

`tests/test_rule_scheduler.py` 檔尾新增（照該檔既有 ScheduleDB/engine harness 慣例組 schedules 與 mock api）：

```python
def test_check_persists_per_schedule_state(tmp_path, monkeypatch):
    """2026-07-16 backlog：rule 排程要有 per-schedule 執行紀錄
    （report scheduler 早有，rule 這側缺——排程沒生效時分不出
    「時間未到」還是「從未觸發」）。"""
    import json
    from unittest.mock import MagicMock
    from src.rule_scheduler import ScheduleDB, ScheduleEngine
    state_file = str(tmp_path / "state.json")
    monkeypatch.setattr("src.rule_scheduler._resolve_rule_state_file",
                        lambda: state_file)
    db = ScheduleDB(str(tmp_path / "rule_schedules.json"))
    db.db = {"/orgs/1/sec_policy/active/rule_sets/1": {
        "type": "recurring", "name": "rs", "is_ruleset": True,
        "action": "enable", "days": ["mon", "tue", "wed", "thu", "fri",
                                      "sat", "sun"],
        "start": "00:00", "end": "23:59", "timezone": "UTC",
    }}
    api = MagicMock()
    api.has_draft_changes.return_value = False
    api.get_live_item.return_value = {"enabled": True}
    engine = ScheduleEngine(db, api)
    engine.check(silent=True, tz_str="UTC")
    states = json.load(open(state_file))["rule_schedule_states"]
    entry = states["/orgs/1/sec_policy/active/rule_sets/1"]
    assert entry["last_checked"].endswith("Z")


def test_schedules_list_enriches_last_state(...):
    # 沿用 tests 中 rule_scheduler GUI 端點既有 harness（若無 HTTP 測試，
    # 以 blueprint 函式層測試 rs_schedules_list enrich 邏輯），斷言回傳
    # 每筆含 last_checked / last_action / last_result 三鍵。
```

（第二個測試同樣須落地為可執行版本，harness 依 tests 現況選 HTTP 或函式層。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_rule_scheduler.py -v -k "persists or enriches"`
Expected: AttributeError（`_resolve_rule_state_file` 不存在）。

- [ ] **Step 3: 實作**

(a) `src/rule_scheduler.py` 模組層新增：

```python
def _resolve_rule_state_file() -> str:
    """rule 排程執行狀態存 logs/state.json（與 report scheduler 同檔異 key）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "logs", "state.json")


_RULE_STATE_KEY = "rule_schedule_states"
```

(b) `ScheduleEngine.check()` 迴圈內：建 `tick_states: dict = {}`；每筆 schedule 處理起點記 `now_z = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` 與 `tick_states[href] = {"last_checked": now_z}`；在執行 enable/disable toggle 的成功/失敗分支補 `tick_states[href].update({"last_action": action, "last_result": "ok"})` 或 `{"last_action": action, "last_result": "error", "error": str(exc)[:300]}`；one_time 過期清除處記 `{"last_action": "expire", "last_result": "ok"}`。`check()` 尾端（return 前）：

```python
        if tick_states:
            try:
                from src.state_store import update_state_file

                def _merge(data):
                    states = dict(data.get(_RULE_STATE_KEY) or {})
                    for href, st in tick_states.items():
                        cur = dict(states.get(href) or {})
                        cur.update(st)
                        states[href] = cur
                    data[_RULE_STATE_KEY] = states
                    return data

                update_state_file(_resolve_rule_state_file(), _merge)
            except Exception:
                logger.opt(exception=True).debug("rule schedule state persist failed")
```

（過期被刪除的 href 也一併從 states 清除：`_merge` 內 `for href in list(states): if href not in self.db.get_all() and href not in tick_states: states.pop(href)`——避免殭屍條目。）

(c) `rs_schedules_list`（gui/routes/rule_scheduler.py:233）enrich，仿 reports.py:985-987：

```python
        from src.state_store import load_state_file
        from src.rule_scheduler import _resolve_rule_state_file, _RULE_STATE_KEY
        states = load_state_file(_resolve_rule_state_file()).get(_RULE_STATE_KEY, {})
        # 迴圈組 entry 處：
        st = states.get(href) or {}
        entry["last_checked"] = st.get("last_checked")
        entry["last_action"] = st.get("last_action")
        entry["last_result"] = st.get("last_result")
```

(d) 前端：index.html 排程表 `<thead>` 加 `<th data-i18n="gui_rs_th_last_run">Last Run</th>`（位置在既有狀態欄後）、兩處 `colspan="12"` 改 `13`；`rule-scheduler.js` `rsLoadSchedules` 的 forEach 內對應位置加：

```js
    var lastTd = document.createElement('td');
    if (s.last_checked) {
      var resTxt = s.last_result === 'error' ? ' !' : '';
      lastTd.textContent = s.last_checked + (s.last_action ? (' (' + s.last_action + resTxt + ')') : '');
      if (s.last_result === 'error') lastTd.style.color = 'var(--danger)';
    } else {
      lastTd.setAttribute('data-i18n', 'gui_jh_never_ran');
      lastTd.textContent = 'never ran';
    }
    tr.appendChild(lastTd);
```

（若該檔用 innerHTML 模板組 tr，改用同型字串插入並 escape；以現行寫法為準。）

(e) i18n：`gui_rs_th_last_run` → en "Last Run"、zh "上次執行"。

(f) JS 靜態斷言附掛到 `tests/test_gui_job_health_panel.py`：

```python
def test_rule_scheduler_list_shows_last_run():
    js = Path("src/static/js/rule-scheduler.js").read_text(encoding="utf-8")
    html = Path("src/templates/index.html").read_text(encoding="utf-8")
    assert "last_checked" in js
    assert "gui_rs_th_last_run" in html
    assert 'colspan="12"' not in html.split('id="rs-schedules-body"')[0][-2000:]
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_rule_scheduler.py tests/test_rule_scheduler_cli.py tests/test_gui_job_health_panel.py tests/test_i18n_glossary.py -v`
Expected: 全數 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/rule_scheduler.py src/gui/routes/rule_scheduler.py src/static/js/rule-scheduler.js src/templates/index.html src/i18n_en.json src/i18n_zh_TW.json tests/test_rule_scheduler.py tests/test_gui_job_health_panel.py
git commit -m "feat(rule-scheduler): persist and display per-schedule last run state"
```

---

### Task 6: ven/posture summary 新鮮度（computed_at + 前端 stale 標示）

**Files:**
- Modify: `src/scheduler/jobs.py`（run_ven_summary :339-347、run_posture_summary :384）
- Modify: `src/gui/routes/dashboard.py`（`_overview_ven` :211-226、`_overview_posture` :177-208 透傳欄位）
- Modify: `src/static/js/dashboard.js`（renderOverview 的 ven/posture tile）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_ven_summary_job.py`、`tests/test_dashboard_overview.py`、`tests/test_gui_job_health_panel.py`（JS 靜態）

**Interfaces:**
- Produces: `ven_summary` dict 新欄 `computed_at`（**僅成功路徑寫**；`_mark_err` 不動它——`updated_at` 繼續表示「最後嘗試」，`computed_at` 表示「最後成功計算」）；posture 沿用既有 `generated_at`（已只在成功路徑寫，不需新欄）。overview 的 `ven` 區透傳 `computed_at`，`posture` 區已含 `generated_at`。
- 前端 stale 門檻：`now - computed_at > 3 × interval`（ven 300s → 15 分鐘；posture 600s → 30 分鐘）→ tile 數值變 `var(--dim)` 並附 `(<age>)`。

- [ ] **Step 1: 寫失敗測試**

`tests/test_ven_summary_job.py` 檔尾（沿用該檔 mock harness）：

```python
def test_ven_summary_writes_computed_at_on_success_only(tmp_path, monkeypatch):
    """computed_at＝最後成功計算時間：job 卡死/失敗時凍結數字要能被看出
    不新鮮（updated_at 會被 _mark_err 更新，不能當新鮮度用）。"""
    # 沿用檔內既有成功路徑 harness 跑一次 run_ven_summary，斷言：
    summary = json.load(open(dashboard_path))["ven_summary"]
    assert summary["computed_at"].endswith("Z")
    # 再以 ApiClient 拋例外的 harness 跑一次，斷言 computed_at 不變、
    # last_error 有值、updated_at 有更新。
```

（落地為完整可執行測試，變數名依檔內 harness。）

`tests/test_gui_job_health_panel.py` 加：

```python
def test_dashboard_tiles_show_staleness():
    js = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    assert "computed_at" in js
    assert "_ovStale" in js
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_ven_summary_job.py tests/test_gui_job_health_panel.py -v -k "computed_at or staleness"`
Expected: KeyError `computed_at` / 斷言失敗。

- [ ] **Step 3: 實作**

(a) `run_ven_summary` summary dict（:339-347）加一行 `"computed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),`（`_mark_err` 路徑不碰 computed_at）。

(b) `_overview_ven` 回傳 dict 透傳 `"computed_at": vs.get("computed_at")`；`_overview_posture` 確認回傳含 `generated_at`（已有則不動）。

(c) `dashboard.js` renderOverview：新增 helper（整行註解）：

```js
// 資料新鮮度：computed/generated 時戳距今超過門檻（毫秒）視為 stale。
function _ovStale(ts, thresholdMs) {
  if (!ts) return true;
  var t = Date.parse(ts);
  if (isNaN(t)) return true;
  return (Date.now() - t) > thresholdMs;
}
```

ven tile 渲染處：`var venStale = _ovStale(v.computed_at, 15 * 60 * 1000);`，stale 時數值容器加 `style="color:var(--dim)"` 並在 body 尾附 `'<div style="font-size:11px;color:var(--dim);">' + T('gui_ov_stale_since', 'stale') + ' ' + _fmtAge((Date.now() - Date.parse(v.computed_at)) / 1000) + '</div>'`（`computed_at` 缺值時顯示 `T('gui_jh_never_ran', 'never ran')`）。posture tile 同法用 `p.generated_at` 與 30 分鐘門檻。

(d) i18n：`gui_ov_stale_since` → en "stale for"、zh "資料停更"。

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_ven_summary_job.py tests/test_dashboard_overview.py tests/test_gui_job_health_panel.py tests/test_i18n_glossary.py -v`
Expected: 全數 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/scheduler/jobs.py src/gui/routes/dashboard.py src/static/js/dashboard.js src/i18n_en.json src/i18n_zh_TW.json tests/test_ven_summary_job.py tests/test_gui_job_health_panel.py
git commit -m "feat(observability): freshness timestamps for ven and posture summaries"
```

---

### Task 7: TLS 每日續期檢查 job

**Files:**
- Modify: `src/scheduler/jobs.py`（新 `run_tls_renew_check`）
- Modify: `src/scheduler/__init__.py`（註冊 job，gated）
- Test: `tests/test_scheduler_cache_archive.py`（註冊測試附掛）、`tests/test_job_health.py`（job 函式測試附掛）

**Interfaces:**
- Consumes: `src.gui._helpers._maybe_auto_renew_self_signed(cert_dir, threshold_days)`（既有，回 `(renewed: bool, days: int|None)`）。
- Produces: `run_tls_renew_check(cm) -> None`；job id `tls_renew_check`，interval 24h，`next_run_time=_kick0 + 100s`，僅 `web_gui.tls.enabled and web_gui.tls.self_signed and web_gui.tls.auto_renew` 時註冊。
- 已知限制（docstring 明載）：續期只落地憑證檔，**執行中的 GUI listener 不會熱換**——續期後記 warning log 與 job_health detail 提示重啟；到期可視性由 Task 2/3 的 tls 卡涵蓋。

- [ ] **Step 1: 寫失敗測試**

`tests/test_job_health.py` 附掛：

```python
def test_run_tls_renew_check_invokes_helper(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch
    from src.scheduler.jobs import run_tls_renew_check
    cm = MagicMock()
    cm.config = {"web_gui": {"tls": {"enabled": True, "self_signed": True,
                                      "auto_renew": True, "auto_renew_days": 30}}}
    with patch("src.gui._helpers._maybe_auto_renew_self_signed",
               return_value=(True, 396)) as mock_renew:
        run_tls_renew_check(cm)
    mock_renew.assert_called_once()
    _args, kwargs = mock_renew.call_args
    assert kwargs.get("threshold_days") == 30


def test_run_tls_renew_check_swallows_exceptions():
    from unittest.mock import MagicMock, patch
    from src.scheduler.jobs import run_tls_renew_check
    cm = MagicMock()
    cm.config = {"web_gui": {"tls": {"enabled": True, "self_signed": True,
                                      "auto_renew": True}}}
    with patch("src.gui._helpers._maybe_auto_renew_self_signed",
               side_effect=RuntimeError("boom")), \
         patch("src.scheduler.jobs.logger") as mock_logger:
        run_tls_renew_check(cm)
    assert mock_logger.exception.called
```

`tests/test_scheduler_cache_archive.py` 附掛：

```python
def test_tls_renew_job_registered_when_self_signed_auto_renew(tmp_path):
    from src.scheduler import build_scheduler
    cm = _cm(tmp_path, archive_enabled=False)
    cm.models.pce_cache.enabled = False
    cm.models.siem.enabled = False
    cm.config = {"web_gui": {"tls": {"enabled": True, "self_signed": True,
                                      "auto_renew": True}}}
    sched = build_scheduler(cm)
    try:
        job = sched.get_job("tls_renew_check")
        assert job is not None
        assert job.next_run_time is not None
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)


def test_tls_renew_job_absent_when_disabled(tmp_path):
    from src.scheduler import build_scheduler
    cm = _cm(tmp_path, archive_enabled=False)
    cm.models.pce_cache.enabled = False
    cm.models.siem.enabled = False
    cm.config = {"web_gui": {"tls": {"enabled": True, "self_signed": True,
                                      "auto_renew": False}}}
    sched = build_scheduler(cm)
    try:
        assert sched.get_job("tls_renew_check") is None
    finally:
        for j in list(sched.get_jobs()):
            sched.remove_job(j.id)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_job_health.py tests/test_scheduler_cache_archive.py -v -k "tls"`
Expected: ImportError / job 不存在。

- [ ] **Step 3: 實作**

`src/scheduler/jobs.py` 檔尾新增：

```python
def run_tls_renew_check(cm) -> None:
    """每日檢查 self-signed 憑證天數，低於門檻時就地重簽。

    限制：只落地憑證檔，執行中的 GUI listener 不會熱換——續期後記
    warning 提示重啟套用。到期天數的常態可視性由 overview 的 tls 卡涵蓋。
    """
    try:
        import os
        from src.gui._helpers import _maybe_auto_renew_self_signed
        tls_cfg = (cm.config.get("web_gui") or {}).get("tls") or {}
        if not (tls_cfg.get("enabled", True) and tls_cfg.get("self_signed", True)
                and tls_cfg.get("auto_renew", True)):
            return
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cert_dir = os.path.join(root, "config", "tls")
        threshold = int(tls_cfg.get("auto_renew_days", 30))
        renewed, days = _maybe_auto_renew_self_signed(cert_dir,
                                                      threshold_days=threshold)
        if renewed:
            logger.warning(
                "TLS self-signed cert renewed on disk ({} days remaining); "
                "restart the service to apply", days)
        else:
            logger.info("TLS cert check: {} days remaining", days)
    except Exception as exc:
        logger.exception("run_tls_renew_check failed: {}", exc)
```

`src/scheduler/__init__.py`（posture_summary 之後）：

```python
    try:
        _tls_cfg = (cm.config.get("web_gui") or {}).get("tls") or {}
        if (_tls_cfg.get("enabled", True) and _tls_cfg.get("self_signed", True)
                and _tls_cfg.get("auto_renew", True)):
            from src.scheduler.jobs import run_tls_renew_check
            sched.add_job(
                _instrument("tls_renew_check", run_tls_renew_check, 86400),
                trigger=IntervalTrigger(hours=24),
                args=[cm],
                id="tls_renew_check",
                name="TLS self-signed renew check",
                replace_existing=True,
                next_run_time=_kick0 + _dt0.timedelta(seconds=100),
            )
    except Exception as exc:
        logger.exception("Failed to register tls renew job: {}", exc)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_job_health.py tests/test_scheduler_cache_archive.py tests/test_scheduler_intervals.py -v`
Expected: 全數 PASS（含通用 kick 守門：新 job 自帶 next_run_time）。

- [ ] **Step 5: Commit**

```bash
git add src/scheduler/jobs.py src/scheduler/__init__.py tests/test_job_health.py tests/test_scheduler_cache_archive.py
git commit -m "feat(tls): daily self-signed renewal check job"
```

---

### Task 8: settings 通道卡「送測試」按鈕

**Files:**
- Modify: `src/static/js/settings.js`（`_renderAlertPluginCards` :228-258、新 window handler）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_gui_settings_subtab_render.py`（附掛靜態斷言）

**Interfaces:**
- Consumes: 既有 `POST /api/actions/test-alert`（actions.py:491，body `{"channel": name}`，呼叫 `send_alerts(force_test=True, channels=[channel])`）；既有 toast/`post()` helper（settings.js/utils.js 慣例）。
- Produces: `window.testAlertChannel(name)`；每張 plugin card 一顆 `data-action="testAlertChannel" data-args='["<name>"]'` 按鈕。

- [ ] **Step 1: 寫失敗測試**

`tests/test_gui_settings_subtab_render.py` 檔尾：

```python
def test_alert_plugin_cards_have_test_send_button():
    """2026-07-16 backlog：通道設定壞掉與健康閒置在 GUI 長相相同——
    每張通道卡提供送測試按鈕（複用既有 /api/actions/test-alert）。"""
    js = Path("src/static/js/settings.js").read_text(encoding="utf-8")
    fn = js.split("function _renderAlertPluginCards(", 1)[1].split("\nfunction ", 1)[0]
    assert 'data-action="testAlertChannel"' in fn
    assert "gui_set_test_send" in fn
    assert "window.testAlertChannel" in js


def test_test_send_i18n_bilingual():
    import json
    en = json.loads(Path("src/i18n_en.json").read_text(encoding="utf-8"))
    zh = json.loads(Path("src/i18n_zh_TW.json").read_text(encoding="utf-8"))
    for k in ("gui_set_test_send", "gui_set_test_sent", "gui_set_test_failed"):
        assert k in en and k in zh, k
```

（該檔若無 `from pathlib import Path`，補之。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_gui_settings_subtab_render.py -v -k "test_send"`
Expected: FAIL。

- [ ] **Step 3: 實作**

(a) `_renderAlertPluginCards` 每張 card 的 header 區（enable checkbox 同列）加：

```js
    + '<button type="button" class="btn btn-secondary btn-sm" '
    + 'data-action="testAlertChannel" data-args=\'["' + name + '"]\' '
    + 'data-i18n="gui_set_test_send">Send test</button>'
```

(b) settings.js 檔尾新增 handler（整行註解）：

```js
// 通道送測試：複用 actions 的 test-alert 端點，結果以 toast 呈現。
window.testAlertChannel = async function (name) {
  try {
    var r = await post('/api/actions/test-alert', { channel: name });
    var results = (r && r.results) || [];
    var failed = results.filter(function (x) { return x.status === 'failed'; });
    if (r && r.ok && !failed.length) {
      toast(_t('gui_set_test_sent') + ': ' + name);
    } else {
      var err = failed.length ? (failed[0].error || '') : (r && r.error) || '';
      toast(_t('gui_set_test_failed') + ': ' + name + ' ' + err, 'err');
    }
  } catch (e) {
    toast(_t('gui_set_test_failed') + ': ' + name, 'err');
  }
};
```

（`/api/actions/test-alert` 回應形狀以 actions.py:491-516 現況為準；若回 `{ok, results}` 以外形狀，依實際欄位調整判定，測試不鎖回應形狀。）

(c) i18n：

```json
"gui_set_test_send": "Send test",
"gui_set_test_sent": "Test alert sent",
"gui_set_test_failed": "Test alert failed"
```

```json
"gui_set_test_send": "送測試",
"gui_set_test_sent": "測試告警已送出",
"gui_set_test_failed": "測試告警失敗"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_gui_settings_subtab_render.py tests/test_i18n_glossary.py tests/test_i18n_audit.py -v`
Expected: 全數 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/static/js/settings.js src/i18n_en.json src/i18n_zh_TW.json tests/test_gui_settings_subtab_render.py
git commit -m "feat(gui): per-channel test-send button on alert settings cards"
```

---

### Task 9: 全套驗證 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`（`## [Unreleased]`）

- [ ] **Step 1: 全套測試**

Run: `pytest --tb=short -q`
Expected: 全數 PASS（基準 3094+，新測試全計入）。

- [ ] **Step 2: CHANGELOG**

`### Added` 補：

```markdown
- Job health observability: every scheduled job records its last run and
  status to `logs/job_health.json`; the Integrations overview shows a Job
  Health table (never-ran and overdue jobs flagged) plus a TLS certificate
  card, and a daily job renews the self-signed cert on disk when close to
  expiry (restart still required to apply). Rule schedules now persist and
  display per-schedule last-run state like report schedules; VEN/posture
  dashboard tiles show data freshness and grey out when stale; alert channel
  settings cards gained a test-send button.
```

`### Fixed` 補：

```markdown
- Pipeline health no longer reads green when SIEM is enabled but idle (no
  enabled destination, or ingest has data while nothing was enqueued for
  24h) — such states now surface as warn with a `siem_idle` flag.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): observability backlog delivery"
```

---

## 完成後整合與真機驗證（執行期，非計畫任務）

1. finishing-a-development-branch：合併回 main、push、`gh run watch` 盯 CI 綠。
2. 部署測試機：`ssh illumio-ops-test 'cd /root/illumio-ops && git pull --ff-only origin main && systemctl restart illumio-ops && sleep 5 && systemctl is-active illumio-ops'`。
3. 真機驗證（逐項）：
   - 重啟 5 分鐘後 `cat /root/illumio-ops/logs/job_health.json`——所有 job 應有 last_run/ok；
   - Playwright 截圖整合 overview 子頁——Job 健康表與 TLS 卡渲染正確；
   - 建一條 rule 排程、跑「立即檢查」，列表出現「上次執行」；
   - settings 通道卡按「送測試」，收到測試告警且 toast 正確；
   - 暫停 ingest 模擬（或直接改 job_health.json 時戳）確認 overdue 顯示 warn。

## Self-Review 紀錄

- 覆蓋：六項 backlog ↔ Task 1-3（job 健康+面板+retention/aggregate/capacity 可視化）、Task 4（SIEM 誤綠）、Task 5（rule last_run）、Task 6（summary 新鮮度）、Task 7＋Task 2/3 tls 卡（TLS）、Task 8（送測試）。
- 名稱一致性：`job_health.load_job_health/record_job_run/record_job_registered/_job_health_file`（Task 1 定義，Task 2 消費）；`_instrument`（Task 1 定義，Task 7 註冊消費）；`pipeline_verdict(..., siem_idle=False)`（Task 4）；`rule_schedule_states/_resolve_rule_state_file/_RULE_STATE_KEY`（Task 5 內自洽）；`computed_at`/`_ovStale`（Task 6）；`testAlertChannel`（Task 8）。
- 已知風險已交代：TLS 熱換限制（docstring＋i18n 文案「重啟套用」）；job_health 寫入節流語意（error 不節流）；rule states 殭屍條目清理。
- Task 4/5/6 各有一段測試以需求描述形式存在（fixture 名依檔內現況）——實作者必須落地為完整可執行測試，reviewer 以此驗收，不得保留描述性註解版。
