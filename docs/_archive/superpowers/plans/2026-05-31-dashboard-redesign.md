# Dashboard Redesign (Live Operational Overview) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dashboard's stitched-from-reports top zone with a purpose-built live operational overview — four verdict tiles (VEN health / blocked-now / pipeline / alerts) fed by one new `/api/dashboard/overview` endpoint + a periodic VEN-summary job — and retire the dual-JS (`dashboard_v2.js`) tangle.

**Architecture:** A scheduler job (`run_ven_summary`) periodically fetches workloads and writes a VEN summary to `logs/state.json`. A new GET route `/api/dashboard/overview` composes four sections (each with its own `ok/warn/error/unknown` verdict and graceful per-section degradation) from: state (`ven_summary`, alerts), the `pce_traffic_flows_agg` cache table (blocked), and the cache DB watermarks + `SiemDispatch` table (pipeline). The frontend consolidates into a single `dashboard.js` that fetches this one endpoint, renders four drill-down tiles with a real `as_of` + auto-refresh, keeps the existing lower detail zone, and drops `dashboard_v2.js`.

**Tech Stack:** Python 3.12, Flask blueprints, SQLAlchemy (SQLite cache), APScheduler, pytest; vanilla JS frontend; i18n via `i18n_en.json`/`i18n_zh_TW.json`.

**Spec:** `docs/superpowers/specs/2026-05-31-dashboard-redesign-design.md`

**Refinements vs spec (decided from codebase facts):**
- `degraded` is **deferred** (the VEN generator exposes only online/offline; `policy_sync` "synced" semantics are ambiguous). Keep `degraded:0` in the payload for contract stability; VEN verdict depends on offline only.
- New route is **not** `@login_required` — matches every existing `/api/dashboard/*` route (auth is handled app-wide, not per-route). Per-route auth divergence would be inconsistent and is a separate governance item.
- VEN summary is stored in `logs/state.json` (`state["ven_summary"]`) via `update_state_file()` (independent of `pce_cache.enabled`), read by the route via `_resolve_state_file()` — exactly how `pce_stats` already flows.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/scheduler/jobs.py` | Modify (add `run_ven_summary`) | Periodic VEN summary → state |
| `src/scheduler/__init__.py` | Modify (register job) | Schedule `run_ven_summary` every 300s |
| `src/gui/routes/dashboard.py` | Modify (add route + 4 helper fns) | `/api/dashboard/overview` composition |
| `src/i18n_en.json`, `src/i18n_zh_TW.json` | Modify (add keys) | Tile titles/labels |
| `src/templates/index.html` | Modify (replace story-card block + CSS) | New 4-tile markup |
| `src/static/js/dashboard.js` | Modify (add overview render; absorb live loaders; delete dead fns) | Single dashboard module |
| `src/static/js/dashboard_v2.js` | **Delete** | (retired) |
| `tests/test_ven_summary_job.py` | Create | Job unit tests |
| `tests/test_dashboard_overview.py` | Create | Endpoint unit tests |

---

## Task 1: `run_ven_summary` job → writes `state["ven_summary"]`

**Files:**
- Modify: `src/scheduler/jobs.py` (add function near other jobs)
- Test: `tests/test_ven_summary_job.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ven_summary_job.py
import json, os, tempfile
from unittest.mock import patch, MagicMock


def _wl(host, hb_hours, status="active"):
    return {"hostname": host,
            "interfaces": [{"address": "10.0.0.1"}],
            "labels": [],
            "agent": {"status": {"status": status,
                                 "hours_since_last_heartbeat": hb_hours,
                                 "security_policy_sync_state": "active",
                                 "last_heartbeat_on": "2026-05-31T00:00:00Z",
                                 "agent_version": "21.5.35"}}}


def test_run_ven_summary_writes_counts(tmp_path):
    from src.scheduler.jobs import run_ven_summary
    state_file = str(tmp_path / "state.json")
    cm = MagicMock()
    cm.config = {"settings": {"timezone": "UTC"}}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [
        _wl("a", 0.2), _wl("b", 0.3), _wl("c", 99.0)]  # 2 online, 1 offline
    api.__enter__.return_value = api
    api.__exit__.return_value = False

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
        run_ven_summary(cm)

    s = json.load(open(state_file))["ven_summary"]
    assert s["total"] == 3 and s["online"] == 2 and s["offline"] == 1
    assert s["degraded"] == 0
    assert len(s["attention"]) == 1 and s["attention"][0]["host"] == "c"
    assert s["updated_at"]


def test_run_ven_summary_preserves_last_good_on_error(tmp_path):
    from src.scheduler.jobs import run_ven_summary
    from src.state_store import update_state_file
    state_file = str(tmp_path / "state.json")
    update_state_file(state_file, lambda s: {**s, "ven_summary": {"total": 5, "online": 5, "offline": 0}})
    cm = MagicMock(); cm.config = {"settings": {}}
    api = MagicMock(); api.__enter__.return_value = api; api.__exit__.return_value = False
    api.fetch_managed_workloads.side_effect = RuntimeError("PCE down")

    with patch("src.scheduler.jobs.ApiClient", return_value=api), \
         patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
        run_ven_summary(cm)

    s = json.load(open(state_file))["ven_summary"]
    assert s["total"] == 5          # last-good counts preserved
    assert "last_error" in s and "PCE down" in s["last_error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_ven_summary_job.py -q`
Expected: FAIL — `ImportError: cannot import name 'run_ven_summary'`.

- [ ] **Step 3: Implement the job**

Add to `src/scheduler/jobs.py` (after `run_siem_dispatch`). Reuse the VEN generator's `_is_online_row` semantics inline (heartbeat ≤ 1h AND status in active/online):

```python
def run_ven_summary(cm) -> None:
    """Fetch managed workloads, compute a VEN health summary, write to state.

    Independent of pce_cache. Stored in logs/state.json["ven_summary"] so the
    dashboard overview reads it instantly without hitting the PCE per refresh.
    On failure, last-good counts are preserved and last_error is recorded.
    """
    import datetime
    from src.api_client import ApiClient
    from src.gui._helpers import _resolve_state_file
    from src.state_store import update_state_file

    _ONLINE = {"active", "online"}
    _THRESH_H = 1.0
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        with ApiClient(cm) as api:
            workloads = api.fetch_managed_workloads()
        total = online = 0
        attention = []
        oldest_age = 0.0
        for w in workloads or []:
            st = (w.get("agent") or {}).get("status") or {}
            total += 1
            status = str(st.get("status", "")).lower()
            hslh = st.get("hours_since_last_heartbeat")
            try:
                hslh = float(hslh) if hslh is not None else None
            except (TypeError, ValueError):
                hslh = None
            is_online = status in _ONLINE and hslh is not None and hslh <= _THRESH_H
            if is_online:
                online += 1
            else:
                host = w.get("hostname") or w.get("name") or "?"
                reason = (f"{int(hslh)}h no heartbeat" if hslh is not None
                          else f"status={status or 'unknown'}")
                attention.append({"host": host, "reason": reason})
            if hslh is not None:
                oldest_age = max(oldest_age, hslh * 3600.0)
        summary = {
            "total": total, "online": online, "offline": total - online,
            "degraded": 0,  # deferred — see plan refinements
            "oldest_heartbeat_age_s": int(oldest_age),
            "attention": attention[:20],
            "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        update_state_file(_resolve_state_file(),
                          lambda s: {**s, "ven_summary": summary})
        logger.info("VEN summary: {}/{} online", online, total)
    except Exception as exc:
        logger.exception("run_ven_summary failed: {}", exc)
        def _mark_err(s):
            vs = dict(s.get("ven_summary") or {})
            vs["last_error"] = str(exc)[:300]
            vs["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            return {**s, "ven_summary": vs}
        try:
            update_state_file(_resolve_state_file(), _mark_err)
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_ven_summary_job.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/scheduler/jobs.py tests/test_ven_summary_job.py
git commit -m "feat(dashboard): run_ven_summary job → state['ven_summary']"
```

---

## Task 2: Register `run_ven_summary` in the scheduler

**Files:**
- Modify: `src/scheduler/__init__.py:10-14` (import) and `:84-91` (add job after `tick_rule_schedules`)

- [ ] **Step 1: Add the import**

In `src/scheduler/__init__.py`, extend the jobs import (lines 10-14):

```python
from src.scheduler.jobs import (
    run_monitor_cycle,
    tick_report_schedules,
    tick_rule_schedules,
    run_ven_summary,
)
```

- [ ] **Step 2: Register the job** (after the `tick_rule_schedules` `add_job` block, ~line 91)

```python
    ven_summary_interval = int(
        cm.config.get("dashboard", {}).get("ven_summary_interval_seconds", 300)
    )
    sched.add_job(
        run_ven_summary,
        trigger=IntervalTrigger(seconds=ven_summary_interval),
        args=[cm],
        id="ven_summary",
        name="VEN status summary",
        replace_existing=True,
    )
```

- [ ] **Step 3: Verify import + build don't error**

Run: `venv/bin/python -c "from src.scheduler import build_scheduler; print('ok')"`
Expected: prints `ok` (no ImportError).

- [ ] **Step 4: Commit**

```bash
git add src/scheduler/__init__.py
git commit -m "feat(dashboard): schedule run_ven_summary every 300s"
```

---

## Task 3: `/api/dashboard/overview` — VEN section + route skeleton

**Files:**
- Modify: `src/gui/routes/dashboard.py` (add helper `_overview_ven` + route, near other routes)
- Test: `tests/test_dashboard_overview.py` (create)

- [ ] **Step 1: Write the failing test** (mirror `tests/test_cache_web.py` client fixture)

```python
# tests/test_dashboard_overview.py
import json, os, tempfile
import pytest
from src.config import ConfigManager


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw",
                               "secret_key": "s", "allowed_ips": ["127.0.0.1"]},
                   "pce_cache": {"enabled": False, "db_path": str(tmp_path / "c.sqlite")}}, f)
    cm = ConfigManager(config_file=path)
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True; app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        yield c
    os.unlink(path)


def test_overview_ven_verdict_from_state(client, tmp_path, monkeypatch):
    from src.gui import _helpers
    sf = str(tmp_path / "state.json")
    json.dump({"ven_summary": {"total": 21, "online": 19, "offline": 2,
                               "degraded": 0, "oldest_heartbeat_age_s": 147600,
                               "attention": [{"host": "x", "reason": "41h no heartbeat"}]}},
              open(sf, "w"))
    monkeypatch.setattr(_helpers, "_resolve_state_file", lambda: sf)
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200
    ven = r.get_json()["ven"]
    assert ven["online"] == 19 and ven["offline"] == 2
    assert ven["verdict"] == "warn"           # offline>=1, not over 10% of 21 (=3)
    assert "as_of" in r.get_json()


def test_overview_ven_unknown_when_missing(client, tmp_path, monkeypatch):
    from src.gui import _helpers
    sf = str(tmp_path / "state.json"); json.dump({}, open(sf, "w"))
    monkeypatch.setattr(_helpers, "_resolve_state_file", lambda: sf)
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["ven"]["verdict"] == "unknown"
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_dashboard_overview.py -q`
Expected: FAIL — 404 (route not registered).

- [ ] **Step 3: Implement the VEN helper + route skeleton**

In `src/gui/routes/dashboard.py`, add helpers (module level, after imports) and the route inside `make_dashboard_blueprint`:

```python
def _overview_ven(state):
    vs = state.get("ven_summary")
    if not isinstance(vs, dict) or "total" not in vs:
        return {"verdict": "unknown", "note": "no ven_summary yet"}
    total = int(vs.get("total", 0)); offline = int(vs.get("offline", 0))
    err_threshold = max(1, -(-total // 10))  # ceil(total*0.10)
    if offline == 0:
        verdict = "ok"
    elif offline > err_threshold:
        verdict = "error"
    else:
        verdict = "warn"
    return {"total": total, "online": int(vs.get("online", 0)), "offline": offline,
            "degraded": int(vs.get("degraded", 0)),
            "oldest_heartbeat_age_s": int(vs.get("oldest_heartbeat_age_s", 0)),
            "attention": (vs.get("attention") or [])[:20], "verdict": verdict}
```

Route (inside the factory, near `api_dashboard_snapshot`):

```python
    @bp.route('/api/dashboard/overview', methods=['GET'])
    def api_dashboard_overview():
        import datetime
        cm.load()
        state = {}
        STATE_FILE = _resolve_state_file()
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except Exception:
                state = {}
        return jsonify({
            "as_of": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ven": _overview_ven(state),
        })
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_dashboard_overview.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gui/routes/dashboard.py tests/test_dashboard_overview.py
git commit -m "feat(dashboard): /api/dashboard/overview with VEN section"
```

---

## Task 4: Overview — blocked section (agg cache, vs-prev)

**Files:** Modify `src/gui/routes/dashboard.py` (add `_overview_blocked` + a cache-session helper); add test.

- [ ] **Step 1: Write the failing test**

```python
def test_overview_blocked_from_agg(client, tmp_path):
    # The `client` fixture configures pce_cache.db_path = tmp_path/"c.sqlite"; pytest
    # gives the fixture and this test the SAME tmp_path, so seeding that exact file
    # means the route's _cache_session reads our rows — no monkeypatch needed.
    import datetime as dt
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceTrafficFlowAgg
    eng = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}"); init_schema(eng)
    today = dt.datetime.now(dt.timezone.utc)
    rows = [("allowed", 100, today), ("blocked", 30, today),
            ("potentially_blocked", 70, today)]
    with sessionmaker(eng)() as s:
        for i, (act, n, day) in enumerate(rows):
            s.add(PceTrafficFlowAgg(bucket_day=day, src_workload="a", dst_workload="b",
                                    port=440 + i, protocol="TCP", action=act, flow_count=n))
        s.commit()
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    blocked = r.get_json()["blocked"]
    assert blocked["blocked"] == 30 and blocked["potential"] == 70 and blocked["allowed"] == 100
    assert blocked["verdict"] == "ok"   # no spike vs prev window
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_dashboard_overview.py::test_overview_blocked_from_agg -q`
Expected: FAIL — `KeyError: 'blocked'`.

- [ ] **Step 3: Implement** (add helpers to `dashboard.py`)

```python
def _cache_session(cm):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    eng = create_engine(f"sqlite:///{cm.models.pce_cache.db_path}")
    init_schema(eng)
    return sessionmaker(eng)


_BLOCKED_KEYS = {"allowed": "allowed", "potentially_blocked": "potential", "blocked": "blocked"}


def _overview_blocked(cm, window_days=7):
    import datetime as dt
    from sqlalchemy import func, select
    from src.pce_cache.models import PceTrafficFlowAgg
    now = dt.datetime.now(dt.timezone.utc)
    cur_start = now - dt.timedelta(days=window_days)
    prev_start = now - dt.timedelta(days=2 * window_days)
    try:
        sf = _cache_session(cm)
        def _sum(s, lo, hi):
            out = {"allowed": 0, "potential": 0, "blocked": 0}
            rows = s.execute(
                select(PceTrafficFlowAgg.action, func.sum(PceTrafficFlowAgg.flow_count))
                .where(PceTrafficFlowAgg.bucket_day >= lo)
                .where(PceTrafficFlowAgg.bucket_day < hi)
                .group_by(PceTrafficFlowAgg.action)).all()
            for action, n in rows:
                out[_BLOCKED_KEYS.get((action or "").lower(), "blocked")] += int(n or 0)
            return out
        with sf() as s:
            cur = _sum(s, cur_start, now)
            prev = _sum(s, prev_start, cur_start)
    except Exception as e:
        return {"verdict": "unknown", "note": str(e)[:120]}
    cur_flag = cur["blocked"] + cur["potential"]
    prev_flag = prev["blocked"] + prev["potential"]
    vs_prev = int(round((cur_flag - prev_flag) / prev_flag * 100)) if prev_flag else 0
    verdict = "warn" if (prev_flag and vs_prev > 50) else "ok"
    return {"window_days": window_days, **cur, "flagged": cur_flag,
            "vs_prev_pct": vs_prev, "verdict": verdict}
```

Add `"blocked": _overview_blocked(cm),` to the route's `jsonify({...})`.

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_dashboard_overview.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gui/routes/dashboard.py tests/test_dashboard_overview.py
git commit -m "feat(dashboard): overview blocked section from agg cache"
```

---

## Task 5: Overview — pipeline + alerts sections + assembly

**Files:** Modify `src/gui/routes/dashboard.py` (`_overview_pipeline`, `_overview_alerts`); add tests.

- [ ] **Step 1: Write failing tests**

```python
def test_overview_alerts_from_state(client, tmp_path, monkeypatch):
    from src.gui import _helpers
    sf = str(tmp_path / "state.json")
    json.dump({"dispatch_history": [
                  {"timestamp": "2026-05-31T00:00:00Z", "channel": "line", "status": "success"},
                  {"timestamp": "2026-05-31T00:01:00Z", "channel": "mail", "status": "failed"}],
               "throttle_state": {"r1": {"suppressed": 8}}}, open(sf, "w"))
    monkeypatch.setattr(_helpers, "_resolve_state_file", lambda: sf)
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    al = r.get_json()["alerts"]
    assert al["failed"] >= 1 and al["verdict"] == "warn"
    assert "recent" in al


def test_overview_pipeline_present(client, monkeypatch):
    r = client.get("/api/dashboard/overview", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    pl = r.get_json()["pipeline"]
    assert "verdict" in pl   # ok/warn/error/unknown depending on cache availability
```

- [ ] **Step 2: Run to verify fail**

Run: `venv/bin/python -m pytest tests/test_dashboard_overview.py -k "alerts or pipeline" -q`
Expected: FAIL — `KeyError: 'alerts'` / `'pipeline'`.

- [ ] **Step 3: Implement**

```python
def _overview_pipeline(cm):
    import datetime as dt
    from sqlalchemy import func, select
    try:
        from src.pce_cache.lag_monitor import check_cache_lag
        from src.pce_cache.models import SiemDispatch, DeadLetter
        sf = _cache_session(cm)
        lag = check_cache_lag(sf, max_lag_seconds=300)
        cache_lag = [{"source": r["source"], "lag_s": int(r["lag_seconds"]),
                      "level": r["level"]} for r in lag]
        now = dt.datetime.now(dt.timezone.utc); hr_ago = now - dt.timedelta(hours=1)
        with sf() as s:
            sent = s.execute(select(func.count()).select_from(SiemDispatch)
                             .where(SiemDispatch.status == "sent")
                             .where(SiemDispatch.sent_at >= hr_ago)).scalar() or 0
            failed = s.execute(select(func.count()).select_from(SiemDispatch)
                               .where(SiemDispatch.status == "failed")
                               .where(SiemDispatch.queued_at >= hr_ago)).scalar() or 0
            dlq = s.execute(select(func.count()).select_from(DeadLetter)).scalar() or 0
        denom = sent + failed
        success_1h = round(sent / denom * 100, 1) if denom else 100.0
        lag_err = any(c["level"] == "error" for c in cache_lag)
        lag_warn = any(c["level"] == "warning" for c in cache_lag)
        if lag_err or success_1h < 95 or dlq >= 8000:
            verdict = "error"
        elif lag_warn or (denom and success_1h < 99) or dlq > 0:
            verdict = "warn"
        else:
            verdict = "ok"
        return {"cache_lag": cache_lag, "siem_success_1h": success_1h,
                "dlq": int(dlq), "verdict": verdict}
    except Exception as e:
        return {"verdict": "unknown", "note": str(e)[:120]}


def _overview_alerts(state):
    import datetime as dt
    hist = state.get("dispatch_history") or []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    def _recent(ts):
        try:
            return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")) >= cutoff
        except Exception:
            return True
    last24 = [h for h in hist if _recent(h.get("timestamp"))]
    failed = sum(1 for h in last24 if h.get("status") == "failed")
    suppressed = sum(int((v or {}).get("suppressed", 0))
                     for v in (state.get("throttle_state") or {}).values()
                     if isinstance(v, dict))
    verdict = "warn" if failed >= 1 else "ok"
    return {"fired_24h": len(last24), "suppressed": suppressed, "failed": failed,
            "recent": last24[-5:], "verdict": verdict}
```

Add to the route payload: `"pipeline": _overview_pipeline(cm), "alerts": _overview_alerts(state),`.

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_dashboard_overview.py -q`
Expected: PASS (all overview tests).

- [ ] **Step 5: Commit**

```bash
git add src/gui/routes/dashboard.py tests/test_dashboard_overview.py
git commit -m "feat(dashboard): overview pipeline + alerts sections"
```

---

## Task 6: i18n keys for the tiles

**Files:** Modify `src/i18n_en.json`, `src/i18n_zh_TW.json` (add after `gui_story_group_risk`).

- [ ] **Step 1: Add keys to BOTH files (same insertion point, keep parity)**

`i18n_en.json`:
```json
  "gui_ov_ven_title": "VEN Health",
  "gui_ov_blocked_title": "Blocked now",
  "gui_ov_pipeline_title": "Pipeline",
  "gui_ov_alerts_title": "Alerts",
  "gui_ov_online": "online",
  "gui_ov_offline": "offline",
  "gui_ov_oldest_hb": "oldest heartbeat",
  "gui_ov_vs_prev": "vs prev",
  "gui_ov_cache_lag_label": "cache lag",
  "gui_ov_siem_1h": "SIEM 1h",
  "gui_ov_fired_24h": "fired 24h",
  "gui_ov_suppressed": "suppressed",
  "gui_ov_failed": "failed",
  "gui_ov_as_of": "as of",
  "gui_ov_autorefresh": "auto-refresh",
  "gui_ov_refresh_now": "Refresh",
  "gui_ov_stale": "data may be stale",
```

`i18n_zh_TW.json` (Blocked/Potentially Blocked stay English per glossary; SIEM/VEN/DLQ stay English; the rest Chinese):
```json
  "gui_ov_ven_title": "VEN 健康",
  "gui_ov_blocked_title": "現在被擋",
  "gui_ov_pipeline_title": "管線健康",
  "gui_ov_alerts_title": "告警",
  "gui_ov_online": "online",
  "gui_ov_offline": "offline",
  "gui_ov_oldest_hb": "最舊心跳",
  "gui_ov_vs_prev": "vs 前期",
  "gui_ov_cache_lag_label": "cache 延遲",
  "gui_ov_siem_1h": "SIEM 1h",
  "gui_ov_fired_24h": "24h 觸發",
  "gui_ov_suppressed": "已抑制",
  "gui_ov_failed": "失敗",
  "gui_ov_as_of": "資料截至",
  "gui_ov_autorefresh": "自動刷新",
  "gui_ov_refresh_now": "手動刷新",
  "gui_ov_stale": "資料可能過時",
```

- [ ] **Step 2: Verify parity + audit**

Run: `venv/bin/python -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -q`
Expected: PASS. Also: `venv/bin/python -c "import json;e=json.load(open('src/i18n_en.json'));z=json.load(open('src/i18n_zh_TW.json'));assert set(e)==set(z);print(len(e))"`

- [ ] **Step 3: Commit**

```bash
git add src/i18n_en.json src/i18n_zh_TW.json
git commit -m "i18n: add dashboard overview tile keys"
```

---

## Task 7: Frontend — new 4-tile markup + CSS

**Files:** Modify `src/templates/index.html` — replace the `.db-status-row` block (the 3 story cards, ~lines 636-665) with 4 overview tiles; the `db-hero-wrap` (623-635) and `db-maturity-panel` blocks become unused (leave hidden or remove in Task 9).

- [ ] **Step 1: Replace the `.db-status-row` block**

```html
<div class="ov-bar">
  <span class="ov-fresh"><span data-i18n="gui_ov_as_of">as of</span> <span id="ov-as-of">—</span></span>
  <label class="ov-auto"><input type="checkbox" id="ov-autorefresh" checked>
    <span data-i18n="gui_ov_autorefresh">auto-refresh</span> 30s</label>
  <button class="btn btn-sm" id="ov-refresh" data-i18n="gui_ov_refresh_now">Refresh</button>
</div>
<div class="ov-tiles">
  <a class="ov-tile" id="ov-ven"      data-tab="traffic-workload" data-qtab="workloads">
    <div class="ov-tile-h"><span data-i18n="gui_ov_ven_title">VEN Health</span><i class="ov-mark" id="ov-ven-mark"></i></div>
    <div class="ov-tile-body" id="ov-ven-body"></div></a>
  <a class="ov-tile" id="ov-blocked"  data-tab="traffic-workload" data-qtab="traffic">
    <div class="ov-tile-h"><span data-i18n="gui_ov_blocked_title">Blocked now</span><i class="ov-mark" id="ov-blocked-mark"></i></div>
    <div class="ov-tile-body" id="ov-blocked-body"></div></a>
  <a class="ov-tile" id="ov-pipeline" data-tab="integrations">
    <div class="ov-tile-h"><span data-i18n="gui_ov_pipeline_title">Pipeline</span><i class="ov-mark" id="ov-pipeline-mark"></i></div>
    <div class="ov-tile-body" id="ov-pipeline-body"></div></a>
  <a class="ov-tile" id="ov-alerts"   data-tab="events">
    <div class="ov-tile-h"><span data-i18n="gui_ov_alerts_title">Alerts</span><i class="ov-mark" id="ov-alerts-mark"></i></div>
    <div class="ov-tile-body" id="ov-alerts-body"></div></a>
</div>
```

- [ ] **Step 2: Add scoped CSS** (in the `#p-dashboard` style block, near the `.db-status-row` CSS ~line 280)

```css
#p-dashboard .ov-bar { display:flex; align-items:center; gap:12px; justify-content:flex-end;
  font-size:12px; color:var(--dim); margin-bottom:8px; }
#p-dashboard .ov-bar .ov-fresh.stale { color:var(--danger,#ef4444); }
#p-dashboard .ov-tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
#p-dashboard .ov-tile { display:block; background:var(--bg2); border:1px solid var(--border);
  border-radius:12px; padding:14px 16px; text-decoration:none; color:inherit; cursor:pointer; }
#p-dashboard .ov-tile:hover { border-color:var(--slate-50,#64748b); }
#p-dashboard .ov-tile-h { display:flex; justify-content:space-between; align-items:center;
  font-weight:600; font-size:13px; margin-bottom:8px; }
#p-dashboard .ov-mark { width:10px; height:10px; border-radius:999px; display:inline-block; background:var(--dim); }
#p-dashboard .ov-mark.ok { background:var(--color-success,#16a34a); }
#p-dashboard .ov-mark.warn { background:var(--color-warning,#f59e0b); }
#p-dashboard .ov-mark.error { background:var(--color-danger,#dc2626); }
#p-dashboard .ov-tile-body { font-size:13px; line-height:1.7; }
#p-dashboard .ov-tile-body .ov-drill { font-size:11px; color:var(--dim); margin-top:6px; }
@media (max-width:900px){ #p-dashboard .ov-tiles { grid-template-columns:repeat(2,1fr); } }
```

- [ ] **Step 3: Verify template renders** (smoke)

Run: `venv/bin/python -m pytest tests/test_dashboard_overview.py -q` (app still boots) and `node --check` is N/A for HTML; instead grep:
Run: `grep -c "ov-tiles" src/templates/index.html`  Expected: `1`.

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html
git commit -m "feat(dashboard): 4-tile overview markup + CSS"
```

---

## Task 8: Frontend — render the tiles from `/api/dashboard/overview`

**Files:** Modify `src/static/js/dashboard.js` — add `renderOverview(d)` + `loadOverview()`; call `loadOverview()` from the live `loadDashboard` (currently in dashboard_v2.js — see Task 9 for consolidation; for now add the call in the winning `loadDashboard`).

- [ ] **Step 1: Add the render functions to `dashboard.js`**

```javascript
function _ovMark(id, verdict) {
  var el = document.getElementById(id); if (!el) return;
  el.className = 'ov-mark ' + (['ok','warn','error'].indexOf(verdict) >= 0 ? verdict : '');
}
function _ovRows(rows) {
  return rows.map(function (r) { return '<div>' + r + '</div>'; }).join('');
}
function renderOverview(d) {
  d = d || {};
  var T = (k, f) => (window._t ? window._t(k) : f);
  // VEN
  var v = d.ven || {};
  _ovMark('ov-ven-mark', v.verdict);
  document.getElementById('ov-ven-body').innerHTML = (v.verdict === 'unknown')
    ? '<div style="color:var(--dim)">—</div>'
    : _ovRows([(v.online + '/' + v.total + ' ' + T('gui_ov_online','online')),
               (v.offline ? ('⚠ ' + v.offline + ' ' + T('gui_ov_offline','offline')) : ('0 ' + T('gui_ov_offline','offline'))),
               (T('gui_ov_oldest_hb','oldest heartbeat') + ' ' + _fmtAge(v.oldest_heartbeat_age_s))])
      + '<div class="ov-drill">→ Workloads</div>';
  // Blocked
  var b = d.blocked || {};
  _ovMark('ov-blocked-mark', b.verdict);
  document.getElementById('ov-blocked-body').innerHTML = (b.verdict === 'unknown')
    ? '<div style="color:var(--dim)">—</div>'
    : _ovRows(['Blocked ' + (b.blocked || 0).toLocaleString(),
               'Potentially Blocked ' + (b.potential || 0).toLocaleString(),
               (b.vs_prev_pct >= 0 ? '↑' : '↓') + Math.abs(b.vs_prev_pct || 0) + '% ' + T('gui_ov_vs_prev','vs prev')])
      + '<div class="ov-drill">→ Traffic</div>';
  // Pipeline
  var p = d.pipeline || {};
  _ovMark('ov-pipeline-mark', p.verdict);
  var lag = (p.cache_lag || []).map(function (c) { return c.source + ' ' + _fmtAge(c.lag_s); }).join(' · ');
  document.getElementById('ov-pipeline-body').innerHTML = (p.verdict === 'unknown')
    ? '<div style="color:var(--dim)">—</div>'
    : _ovRows([(T('gui_ov_cache_lag_label','cache lag') + ' ' + (lag || '—')),
               (T('gui_ov_siem_1h','SIEM 1h') + ' ' + (p.siem_success_1h != null ? p.siem_success_1h + '%' : '—')),
               'DLQ ' + (p.dlq || 0)])
      + '<div class="ov-drill">→ Integrations</div>';
  // Alerts
  var a = d.alerts || {};
  _ovMark('ov-alerts-mark', a.verdict);
  document.getElementById('ov-alerts-body').innerHTML = _ovRows([
      T('gui_ov_fired_24h','fired 24h') + ' ' + (a.fired_24h || 0),
      T('gui_ov_suppressed','suppressed') + ' ' + (a.suppressed || 0),
      T('gui_ov_failed','failed') + ' ' + (a.failed || 0)])
    + '<div class="ov-drill">→ Events</div>';
  // freshness
  var asOf = document.getElementById('ov-as-of');
  if (asOf && d.as_of) asOf.textContent = new Date(d.as_of).toLocaleTimeString();
}
function _fmtAge(s) {
  s = Math.max(0, Math.floor(Number(s) || 0));
  if (s < 60) return s + 's'; if (s < 3600) return Math.floor(s / 60) + 'm'; return Math.floor(s / 3600) + 'h';
}
async function loadOverview(force) {
  // auto-refreshes (force falsy) respect the toggle + tab visibility;
  // manual refresh / tab-open pass force=true and always fetch.
  if (!force) {
    var cb = document.getElementById('ov-autorefresh');
    if (cb && !cb.checked) return;
    if (document.hidden) return;
  }
  try {
    var r = await get('/api/dashboard/overview');
    renderOverview(r || {});
  } catch (e) { /* leave previous render */ }
}
window.loadOverview = loadOverview;
```

- [ ] **Step 2: Call `loadOverview()` from the live `loadDashboard`**

In the winning `loadDashboard` (dashboard_v2.js:124 today; after Task 9 it lives in dashboard.js), add `loadOverview(true);` near the top (tab-open is always a forced fetch). For this task add it to dashboard_v2.js's `loadDashboard` body.

- [ ] **Step 3: Verify via harness** (mirror the prior trend/line-card harnesses)

Create `tmp/ov_harness.html`:
```html
<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<div id="p-dashboard">
  <span id="ov-as-of">—</span>
  <div class="ov-tile" id="ov-ven"><i class="ov-mark" id="ov-ven-mark"></i><div id="ov-ven-body"></div></div>
  <div class="ov-tile" id="ov-blocked"><i class="ov-mark" id="ov-blocked-mark"></i><div id="ov-blocked-body"></div></div>
  <div class="ov-tile" id="ov-pipeline"><i class="ov-mark" id="ov-pipeline-mark"></i><div id="ov-pipeline-body"></div></div>
  <div class="ov-tile" id="ov-alerts"><i class="ov-mark" id="ov-alerts-mark"></i><div id="ov-alerts-body"></div></div>
</div>
<script>
  // stub globals dashboard.js touches at load (add more if a pageerror names them, as integrations.js needed `debounce`)
  window.get = async () => ({}); window._t = (k) => k; window.debounce = (f) => f;
</script>
<script src="../src/static/js/dashboard.js"></script>
<script>
  window.__sample = { as_of: "2026-05-31T06:00:00Z",
    ven: { total:21, online:19, offline:2, oldest_heartbeat_age_s:147600, verdict:"warn" },
    blocked: { blocked:1290, potential:16298, vs_prev_pct:12, verdict:"ok" },
    pipeline: { cache_lag:[{source:"events",lag_s:240,level:"ok"}], siem_success_1h:100, dlq:0, verdict:"ok" },
    alerts: { fired_24h:2, suppressed:8, failed:0, verdict:"ok" } };
</script>
</body></html>
```
Create `tmp/run_ov.py`:
```python
from playwright.sync_api import sync_playwright
H = "file:///home/harry/rd/illumio-ops/tmp/ov_harness.html"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(H); pg.wait_for_timeout(200)
    out = pg.evaluate("""() => { renderOverview(window.__sample);
      const m = id => document.getElementById(id).className;
      const t = id => document.getElementById(id).innerText;
      return { venMark:m('ov-ven-mark'), blockedMark:m('ov-blocked-mark'),
               ven:t('ov-ven-body'), blocked:t('ov-blocked-body') }; }""")
    b.close()
print(out); print("errs:", errs or "none")
assert "warn" in out["venMark"] and "ok" in out["blockedMark"]
assert "19/21" in out["ven"] and "1,290" in out["blocked"]
print("PASS")
```
Run: `venv/bin/python tmp/run_ov.py` Expected: prints `PASS` and `errs: none`. (`renderOverview` is a hoisted function declaration, so it's callable even if dashboard.js's DOMContentLoaded bootstrap partially errors; add any stubs a pageerror names.)

- [ ] **Step 4: Commit**

```bash
git add src/static/js/dashboard.js src/static/js/dashboard_v2.js
git commit -m "feat(dashboard): render overview tiles from /api/dashboard/overview"
```

---

## Task 9: Consolidate to single `dashboard.js`, retire `dashboard_v2.js`, auto-refresh + drill-down

**Files:** Modify `src/static/js/dashboard.js` (absorb v2's live loaders), `src/templates/index.html` (drop v2 script + dead hero/maturity markup + add drill click handler), **delete** `src/static/js/dashboard_v2.js`.

Per facts pack: v2 WINS for `loadDashboard`/`loadDashboardSnapshot`; v1's `renderHero`/`renderStoryGroups`/`renderMaturity`/`renderTopActions`/`loadDashboardPolicyUsageSummary` are DEAD (never called). `loadDashboardCharts` (v1) and `loadDashboardAuditSummary` (v2) are live.

- [ ] **Step 1: Move v2's live loaders into dashboard.js**

Copy `loadDashboard` (v2:124), `loadDashboardSnapshot` (v2:186), `loadDashboardAuditSummary` (v2:310), `ensureDashboardLayout` (v2:97), `_buildAuditSummaryFieldset` (v2:22), `_dashboardSetCard` into `dashboard.js`, REPLACING dashboard.js's older `loadDashboard`/`loadDashboardSnapshot`. Ensure the moved `loadDashboard` calls `loadOverview()` (Task 8) and still calls `loadDashboardSnapshot()` + `loadDashboardAuditSummary()` + `loadDashboardCharts()`.

- [ ] **Step 2: Delete dead v1 functions** from dashboard.js (no longer referenced after the story cards are gone):
`renderHero` (1310), `renderHeroEmpty` (1327), `renderStoryGroups` (1347), `renderTopActions` (1359), `renderMaturity` (1399), and the story-card `setCard` calls for d-rules/d-health/etc. (now superseded by overview). Keep `loadDashboardCharts`, `loadDashboardQueries`, cooldown UI.

- [ ] **Step 3: Remove the v2 script tag + dead markup** in index.html:
Delete line `<script defer src="/static/js/dashboard_v2.js"></script>` (2922). Remove the now-unused `db-hero-wrap` (623-635) and `db-maturity-panel` blocks (and their now-dead CSS is harmless; leave it).

- [ ] **Step 4: Delete the file**

```bash
git rm src/static/js/dashboard_v2.js
```

- [ ] **Step 5: Drill-down + manual refresh; reuse the existing auto-refresh interval**

The existing `utils.js:334` 30s interval already calls `loadDashboard()` on the active dashboard tab, and `loadDashboard` now calls `loadOverview()` (unforced) — so the tiles auto-refresh for free and the `ov-autorefresh` toggle + `document.hidden` are honored by the gate inside `loadOverview` (Task 8). **Do NOT add a second timer.** Add only a delegated click handler to dashboard.js (module scope):

```javascript
document.addEventListener('click', function (e) {
  if (e.target.closest('#ov-refresh')) { loadOverview(true); return; }   // manual = forced
  var tile = e.target.closest('.ov-tile'); if (!tile) return;
  e.preventDefault();
  var tab = tile.getAttribute('data-tab'); var qtab = tile.getAttribute('data-qtab');
  if (tab && window.switchTab) window.switchTab(tab);
  if (qtab && window.switchQTab) window.switchQTab(qtab);
});
```

Freshness staleness: in `renderOverview`, after setting `ov-as-of`, toggle a `stale` class on the `.ov-fresh` span when `Date.now() - Date.parse(d.as_of) > 60000`.

- [ ] **Step 6: Verify**

Run: `node --check src/static/js/dashboard.js` Expected: OK.
Run: `grep -c "dashboard_v2" src/templates/index.html` Expected: `0`.

- [ ] **Step 7: Commit**

```bash
git add src/static/js/dashboard.js src/templates/index.html
git commit -m "refactor(dashboard): consolidate to single dashboard.js, retire dashboard_v2.js"
```

---

## Task 10: Full regression + deploy + live verify

- [ ] **Step 1: Full suite**

Run: `venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: all pass (prior baseline 1469 + new overview/ven tests).

- [ ] **Step 2: i18n parity + audit** (redundant safety)

Run: `venv/bin/python -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py tests/test_audit_dashboard_i18n.py -q`
Expected: PASS.

- [ ] **Step 3: Commit any fixups, push, deploy** (follow session deploy flow)

```bash
git checkout -b feat/dashboard-live-overview && git ... # or commit on main per user pref
ssh illumio-ops-test 'cd /root/illumio-ops && git pull && sudo systemctl restart illumio-ops.service && sleep 3 && systemctl is-active illumio-ops.service'
```

- [ ] **Step 4: Live verify** (SSH tunnel + Playwright login, mirror prior live checks)

Confirm: four tiles render with real numbers + verdict colors; `as_of` shows a real time and ticks on auto-refresh; clicking a tile navigates to the right tab/qtab; VEN tile populated after `run_ven_summary` has fired once (≤5 min). Capture a screenshot.

---

## Notes for the executor
- Follow existing patterns: cache sessions via `create_engine(f"sqlite:///{cm.models.pce_cache.db_path}")` + `init_schema`; state via `_resolve_state_file()` + `update_state_file()`.
- `get()` is the project's fetch helper in the JS layer (already used by quarantine.js/dashboard.js).
- Glossary: keep Blocked / Potentially Blocked / SIEM / VEN / DLQ in English in zh_TW.
- Do NOT touch the lower detail zone loaders (`loadDashboardSnapshot`, `loadDashboardAuditSummary`, `loadDashboardCharts`) beyond moving them into the single file.
- `renderOverview`'s `innerHTML` interpolates **numbers + the controlled `cache_lag.source` enum** only (safe). If you later render free-text into a tile (e.g. attention hostnames from the VEN summary), escape it via the existing `escapeHtml`/`escapeAttr` helper (as `integrations.js`/`dashboard.js` already do) — don't interpolate raw PCE strings.
