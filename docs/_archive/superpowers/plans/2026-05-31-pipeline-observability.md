# Pipeline Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn the integrations/pipeline surface from lifetime counters into "is it flowing / where is it stuck": last-1h SIEM rates + real latency, cache ingest rate, a unified pipeline-health verdict, single-DLQ-item full-payload inspect, and DLQ replay-by-id with results.

**Architecture:** Compute windowed rates on the fly from existing timestamps (`siem_dispatch.sent_at/queued_at`, `pce_events.ingested_at`, `dead_letter.quarantined_at`) — no new rollup/time-series table; add two indexes on `siem_dispatch`. A shared `pce_cache/health.py` verdict function (also used by the dashboard overview). DLQ inspect rebuilds the full payload from the retained `source_table/source_id` via `dispatcher._build_payload` (no schema change). DLQ replay extended to accept specific ids.

**Tech Stack:** Python 3.12, SQLAlchemy (SQLite cache), Flask (`src/siem/web.py`, `src/pce_cache/web.py`), vanilla JS (`integrations.js`), pytest.

**Spec:** `docs/superpowers/specs/2026-05-31-pipeline-observability-design.md`

**Out of scope (per spec):** backfill async/progress; SIEM append-only per-attempt history table; delivery-outcome tracking of replays.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/pce_cache/models.py` | Modify | Add indexes on `siem_dispatch.queued_at`, `.sent_at` |
| `src/pce_cache/health.py` | Create | Shared `pipeline_verdict(...)` |
| `src/siem/web.py` | Modify | 1h metrics in `/status`; `GET /dlq/<id>`; replay-by-id |
| `src/siem/dlq.py` | Modify | `replay_ids(ids)` |
| `src/pce_cache/web.py` | Modify | `/api/cache/throughput` (1h ingest) |
| `src/static/js/integrations.js` | Modify | latency tile, per_destination fix, verdict tile, DLQ inspect |
| `tests/test_pipeline_observability.py` | Create | Unit tests |

---

## Task 1: SIEM last-1h metrics + real latency + indexes

**Files:** Modify `src/pce_cache/models.py` (indexes), `src/siem/web.py` (`dispatch_status`); Test `tests/test_pipeline_observability.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_observability.py
import datetime as dt, json, os, tempfile
import pytest
from src.config import ConfigManager


@pytest.fixture
def app_cm(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw", "secret_key": "s",
                               "allowed_ips": ["127.0.0.1"]},
                   "pce_cache": {"enabled": True, "db_path": str(tmp_path / "c.sqlite")},
                   "siem": {"enabled": True}}, f)
    cm = ConfigManager(config_file=path)
    yield cm, tmp_path
    os.unlink(path)


def _client(cm):
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True; app.config["WTF_CSRF_ENABLED"] = False
    c = app.test_client()
    c.post("/api/login", json={"username": "admin", "password": "pw"},
           environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    return c


def _seed_dispatch(db, rows):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import SiemDispatch
    eng = create_engine(f"sqlite:///{db}"); init_schema(eng)
    with sessionmaker(eng)() as s:
        for r in rows:
            s.add(SiemDispatch(**r))
        s.commit()


def test_siem_status_has_1h_window_and_latency(app_cm):
    cm, tmp = app_cm
    now = dt.datetime.now(dt.timezone.utc)
    _seed_dispatch(str(tmp / "c.sqlite"), [
        dict(source_table="pce_events", source_id=1, destination="d1", status="sent",
             retries=0, queued_at=now - dt.timedelta(minutes=10),
             sent_at=now - dt.timedelta(minutes=9)),           # latency ~60s, in 1h
        dict(source_table="pce_events", source_id=2, destination="d1", status="failed",
             retries=3, queued_at=now - dt.timedelta(minutes=5), sent_at=None),  # failed in 1h
        dict(source_table="pce_events", source_id=3, destination="d1", status="sent",
             retries=0, queued_at=now - dt.timedelta(hours=3),
             sent_at=now - dt.timedelta(hours=3)),             # old, outside 1h
    ])
    c = _client(cm)
    body = c.get("/api/siem/status", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    d1 = next(x for x in body["status"] if x["destination"] == "d1")
    assert d1["sent_1h"] == 1 and d1["failed_1h"] == 1
    assert d1["success_1h"] == 50.0
    assert d1["avg_latency_ms"] is not None and d1["avg_latency_ms"] > 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_siem_status_has_1h_window_and_latency -q`
Expected: FAIL — `KeyError: 'sent_1h'`.

- [ ] **Step 3: Add indexes** in `src/pce_cache/models.py` `SiemDispatch.__table_args__` (additive; `create_all` adds them):

```python
    __table_args__ = (
        Index("ix_dispatch_pending", "status", "next_attempt_at"),
        Index("ix_dispatch_queued_at", "queued_at"),
        Index("ix_dispatch_sent_at", "sent_at"),
    )
```

- [ ] **Step 4: Extend `dispatch_status`** in `src/siem/web.py:126` — per destination, add windowed counts + latency:

```python
        import datetime as _dt
        from sqlalchemy import func
        now = _dt.datetime.now(_dt.timezone.utc); hr = now - _dt.timedelta(hours=1)
        for entry in result:                       # result already has destination + cumulative counts
            dest = entry["destination"]
            sent_1h = s.execute(select(func.count()).select_from(SiemDispatch)
                .where(SiemDispatch.destination == dest)
                .where(SiemDispatch.status == "sent").where(SiemDispatch.sent_at >= hr)).scalar() or 0
            failed_1h = s.execute(select(func.count()).select_from(SiemDispatch)
                .where(SiemDispatch.destination == dest)
                .where(SiemDispatch.status == "failed").where(SiemDispatch.queued_at >= hr)).scalar() or 0
            denom = sent_1h + failed_1h
            # avg latency (seconds) over sent rows in window → ms
            lat = s.execute(select(func.avg(
                    func.julianday(SiemDispatch.sent_at) - func.julianday(SiemDispatch.queued_at)))
                .where(SiemDispatch.destination == dest)
                .where(SiemDispatch.status == "sent").where(SiemDispatch.sent_at >= hr)).scalar()
            entry["sent_1h"] = sent_1h
            entry["failed_1h"] = failed_1h
            entry["success_1h"] = round(sent_1h / denom * 100, 1) if denom else 100.0
            entry["avg_latency_ms"] = int(lat * 86400 * 1000) if lat else None
```

(`julianday` diff is in days → ×86400×1000 = ms. Keep the existing cumulative `pending/sent/failed/dlq` keys.)

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_siem_status_has_1h_window_and_latency -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pce_cache/models.py src/siem/web.py tests/test_pipeline_observability.py
git commit -m "feat(siem): last-1h sent/failed/success-rate + avg latency per destination"
```

---

## Task 2: Shared pipeline-health verdict

**Files:** Create `src/pce_cache/health.py`; Test.

- [ ] **Step 1: Write the failing test**

```python
def test_pipeline_verdict_thresholds():
    from src.pce_cache.health import pipeline_verdict
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=100.0, denom=10, dlq=0) == "ok"
    assert pipeline_verdict(lag_levels=["warning"], siem_success_1h=100.0, denom=10, dlq=0) == "warn"
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=98.0, denom=10, dlq=0) == "warn"
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=100.0, denom=10, dlq=1) == "warn"
    assert pipeline_verdict(lag_levels=["error"], siem_success_1h=100.0, denom=10, dlq=0) == "error"
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=90.0, denom=10, dlq=0) == "error"
    assert pipeline_verdict(lag_levels=["ok"], siem_success_1h=100.0, denom=0, dlq=0) == "ok"  # no traffic
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_pipeline_verdict_thresholds -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `src/pce_cache/health.py` (same thresholds as the dashboard overview spec's `_overview_pipeline`):

```python
"""Shared pipeline-health verdict (cache lag + SIEM 1h + DLQ). Used by the
dashboard overview and the integrations overview so thresholds never drift."""


def pipeline_verdict(*, lag_levels, siem_success_1h, denom, dlq, dlq_cap=10000):
    lag_err = any(l == "error" for l in (lag_levels or []))
    lag_warn = any(l == "warning" for l in (lag_levels or []))
    if lag_err or (denom and siem_success_1h < 95) or dlq >= int(dlq_cap * 0.8):
        return "error"
    if lag_warn or (denom and siem_success_1h < 99) or dlq > 0:
        return "warn"
    return "ok"
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_pipeline_verdict_thresholds -q`
Expected: PASS.

- [ ] **Step 5: Expose a thin `/api/cache/health` route** (single source for the UI tile — no JS-side thresholds)

In `src/pce_cache/web.py`, add a GET that gathers the inputs and returns the verdict:

```python
@bp.route("/health", methods=["GET"])
@login_required
def api_cache_health():
    from src.pce_cache.health import pipeline_verdict
    from src.pce_cache.lag_monitor import check_cache_lag
    # reuse the SIEM 1h aggregate + DLQ depth; compute lag levels here
    sf = _get_sf()
    lag = check_cache_lag(sf)
    levels = [r["level"] for r in lag]
    # success_1h + denom + dlq: reuse a small query or call into the siem aggregate helper
    ...  # gather siem_success_1h, denom, dlq (factor the Task-1 windowed query into a helper)
    verdict = pipeline_verdict(lag_levels=levels, siem_success_1h=success_1h, denom=denom, dlq=dlq)
    return jsonify({"verdict": verdict, "lag_levels": levels,
                    "siem_success_1h": success_1h, "dlq": dlq})
```

Factor the Task-1 windowed SIEM query into a reusable helper (e.g. `_siem_window_totals(s)`) so both `/status` and `/health` share it.

- [ ] **Step 6: Commit**

```bash
git add src/pce_cache/health.py src/pce_cache/web.py tests/test_pipeline_observability.py
git commit -m "feat(pipeline): shared pipeline_verdict + /api/cache/health"
```

> Cross-plan note: the dashboard plan's `_overview_pipeline` should import and call `pipeline_verdict` instead of inlining the thresholds. Whichever plan lands second wires the other to this function.

---

## Task 3: Cache ingest throughput (last 1h)

**Files:** Modify `src/pce_cache/web.py` (extend `/status` or add `/throughput`); Test.

- [ ] **Step 1: Write the failing test**

```python
def test_cache_throughput_last_1h(app_cm):
    cm, tmp = app_cm
    import datetime as dt
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceEvent
    now = dt.datetime.now(dt.timezone.utc)
    eng = create_engine(f"sqlite:///{tmp / 'c.sqlite'}"); init_schema(eng)
    with sessionmaker(eng)() as s:
        s.add(PceEvent(pce_href="/a", timestamp=now, ingested_at=now - dt.timedelta(minutes=5),
                       event_type="x", payload="{}"))
        s.add(PceEvent(pce_href="/b", timestamp=now, ingested_at=now - dt.timedelta(hours=3),
                       event_type="x", payload="{}"))
        s.commit()
    c = _client(cm)
    body = c.get("/api/cache/throughput", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert body["events_1h"] == 1
```

> Adjust `PceEvent(...)` kwargs to the model's actual required columns (`models.py:14-30` — confirm `pce_href`, `timestamp`, `ingested_at`, `event_type`, `payload`).

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_cache_throughput_last_1h -q`
Expected: FAIL — 404.

- [ ] **Step 3: Add the route** in `src/pce_cache/web.py` (mirror `api_cache_status`):

```python
@bp.route("/throughput", methods=["GET"])
@login_required
def api_cache_throughput():
    import datetime as dt
    from sqlalchemy import func, select
    from src.pce_cache.models import PceEvent, PceTrafficFlowRaw
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        sf = _get_sf()
    except Exception as e:
        return jsonify({"error": t("gui_err_cache_not_configured", e=e, lang=lang)}), 503
    hr = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    with sf() as s:
        ev = s.execute(select(func.count()).select_from(PceEvent)
                       .where(PceEvent.ingested_at >= hr)).scalar() or 0
        tr = s.execute(select(func.count()).select_from(PceTrafficFlowRaw)
                       .where(PceTrafficFlowRaw.ingested_at >= hr)).scalar() or 0
    return jsonify({"events_1h": int(ev), "traffic_1h": int(tr)})
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_cache_throughput_last_1h -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pce_cache/web.py tests/test_pipeline_observability.py
git commit -m "feat(cache): /api/cache/throughput last-1h ingest rate"
```

---

## Task 4: DLQ single-item inspect (rebuild full payload)

**Files:** Modify `src/siem/web.py` (add `GET /dlq/<int:id>`); Test.

- [ ] **Step 1: Write the failing test**

```python
def test_dlq_item_rebuilds_full_payload(app_cm):
    cm, tmp = app_cm
    import datetime as dt
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import DeadLetter, PceEvent
    now = dt.datetime.now(dt.timezone.utc)
    eng = create_engine(f"sqlite:///{tmp / 'c.sqlite'}"); init_schema(eng)
    with sessionmaker(eng)() as s:
        ev = PceEvent(pce_href="/x", timestamp=now, ingested_at=now,
                      event_type="agent.tampering", payload='{"full":"event-body"}')
        s.add(ev); s.flush()
        s.add(DeadLetter(source_table="pce_events", source_id=ev.id, destination="d1",
                         retries=3, last_error="connrefused", payload_preview='{"full":"eve',
                         quarantined_at=now))
        s.commit()
        dl_id = s.execute(__import__("sqlalchemy").select(DeadLetter.id)).scalar()
    c = _client(cm)
    body = c.get(f"/api/siem/dlq/{dl_id}", environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert body["id"] == dl_id
    assert body["last_error"] == "connrefused"
    assert "event-body" in (body["payload"] or "")   # full payload rebuilt from source row
```

> Confirm `dispatcher._build_payload(row)` returns a str/JSON for a `PceEvent` row; adapt the assertion to its real output shape.

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_dlq_item_rebuilds_full_payload -q`
Expected: FAIL — 404.

- [ ] **Step 3: Add the route** in `src/siem/web.py`:

```python
@bp.route("/dlq/<int:dl_id>", methods=["GET"])
@login_required
def get_dlq_item(dl_id):
    from src.pce_cache.models import DeadLetter, PceEvent, PceTrafficFlowRaw
    sf = _get_sf()
    with sf() as s:
        dl = s.get(DeadLetter, dl_id)
        if dl is None:
            return jsonify({"error": "not found"}), 404
        out = {"id": dl.id, "destination": dl.destination, "retries": dl.retries,
               "last_error": dl.last_error, "quarantined_at": dl.quarantined_at.isoformat()
               if dl.quarantined_at else None, "payload": None, "payload_source": None}
        model = {"pce_events": PceEvent, "pce_traffic_flows_raw": PceTrafficFlowRaw}.get(dl.source_table)
        row = s.get(model, dl.source_id) if model else None
        if row is not None:
            try:
                from src.siem.dispatcher import SiemDispatcher  # or the module fn
                out["payload"] = SiemDispatcher._build_payload(row)  # adapt to actual callable
                out["payload_source"] = "rebuilt"
            except Exception as e:
                out["payload"] = dl.payload_preview; out["payload_source"] = f"preview ({e})"
        else:
            out["payload"] = dl.payload_preview; out["payload_source"] = "preview (source gone)"
    return jsonify(out)
```

> Resolve the exact `_build_payload` callable (it's `dispatcher.py:126`). If it's an instance method needing dispatcher state, replicate its row→payload logic or instantiate minimally; if it's effectively static on the row, call it directly. The contract: full payload when the source row exists, else fall back to `payload_preview`.

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_dlq_item_rebuilds_full_payload -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/siem/web.py tests/test_pipeline_observability.py
git commit -m "feat(dlq): GET /api/siem/dlq/<id> rebuilds full payload from source row"
```

---

## Task 5: DLQ replay-by-id + per-item result

**Files:** Modify `src/siem/dlq.py` (`replay_ids`), `src/siem/web.py` (`replay_dlq` accepts `ids`); Test.

- [ ] **Step 1: Write the failing test**

```python
def test_dlq_replay_by_ids(app_cm):
    cm, tmp = app_cm
    import datetime as dt
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import DeadLetter, SiemDispatch
    now = dt.datetime.now(dt.timezone.utc)
    eng = create_engine(f"sqlite:///{tmp / 'c.sqlite'}"); init_schema(eng)
    with sessionmaker(eng)() as s:
        s.add(DeadLetter(source_table="pce_events", source_id=7, destination="d1",
                         retries=3, last_error="x", payload_preview="{}", quarantined_at=now))
        s.commit()
        dl_id = s.execute(select(DeadLetter.id)).scalar()
    c = _client(cm)
    body = c.post("/api/siem/dlq/replay", json={"ids": [dl_id]},
                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert body["status"] == "ok"
    assert any(r["id"] == dl_id and r["ok"] for r in body["requeued"])
    with sessionmaker(eng)() as s:                  # a pending dispatch row was created
        pend = s.execute(select(func.count()).select_from(SiemDispatch)
                         .where(SiemDispatch.status == "pending")).scalar()
        assert pend == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_dlq_replay_by_ids -q`
Expected: FAIL — current replay ignores `ids` and returns `{requeued: <int>}`.

- [ ] **Step 3: Add `replay_ids`** in `src/siem/dlq.py` (mirror `replay` at dlq.py:24 but select by id):

```python
    def replay_ids(self, ids):
        import datetime as dt
        from src.pce_cache.models import DeadLetter, SiemDispatch
        out = []
        with self._sf.begin() as s:
            for dl_id in ids:
                dl = s.get(DeadLetter, dl_id)
                if dl is None:
                    out.append({"id": dl_id, "ok": False, "error": "not found"}); continue
                s.add(SiemDispatch(source_table=dl.source_table, source_id=dl.source_id,
                                   destination=dl.destination, status="pending", retries=0,
                                   queued_at=dt.datetime.now(dt.timezone.utc)))
                out.append({"id": dl_id, "ok": True})
        return out
```

- [ ] **Step 4: Route accepts `ids`** in `src/siem/web.py` `replay_dlq` (web.py:186): if body has `ids`, call `replay_ids(ids)` and return `{"status":"ok","requeued": results}`; else keep the existing `{dest,limit}` path.

```python
    body = request.get_json(silent=True) or {}
    if body.get("ids"):
        results = DeadLetterQueue(_get_sf()).replay_ids(body["ids"])
        return jsonify({"status": "ok", "requeued": results})
    # ... existing dest/limit path unchanged ...
```

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_pipeline_observability.py::test_dlq_replay_by_ids -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/siem/dlq.py src/siem/web.py tests/test_pipeline_observability.py
git commit -m "feat(dlq): replay specific ids with per-item result"
```

---

## Task 6: Frontend — latency tile, verdict tile, DLQ inspect, cache rate

**Files:** Modify `src/static/js/integrations.js`.

- [ ] **Step 1: SIEM latency + 1h + per_destination fix** (`renderSiem` :540, KPI strip :574-583)
- Replace the hardcoded `—` avg-latency tile (:582) with `avg_latency_ms` (sum/avg across destinations, format `Nms`/`N.Ns`).
- The success-rate tile → use `success_1h` (weighted by `sent_1h+failed_1h`).
- Fix `:588` reading `status.per_destination` (never set) → iterate `status.status` rows for per-destination stats in `buildSiemRow`.

- [ ] **Step 2: Integrations overview verdict tile** (`_buildOvCards` :1268)
- In `renderOverview`, fetch `/api/cache/health` (the single-source endpoint from Task 2) and prepend a "Pipeline health" tile colored by `verdict` (ok/warn/error). Do NOT recompute thresholds in JS — just consume `verdict`.

- [ ] **Step 3: DLQ single-item inspect** (`dlqView` :1197)
- Change `dlqView(id)` to `await fetch('/api/siem/dlq/' + id)` and render the full `payload` + full `last_error` (replace the client-only 512-char preview modal).

- [ ] **Step 4: DLQ replay-by-id** (`dlqReplay`/`dlqReplaySelected` :1124-1150)
- POST `{ids: [...]}` with the actual selected row ids (currently they send only `{dest, limit}`); render the per-item `requeued` result then refresh.

- [ ] **Step 5: Cache ingest rate** (`buildCacheStatusCards` :110)
- Fetch `/api/cache/throughput`; show "近1h +N" next to the events/traffic lifetime counts.

- [ ] **Step 6: Verify**

Run: `node --check src/static/js/integrations.js` → OK.
Harness (mirror prior): feed sample `/api/siem/status` (+1h fields) and a DLQ item to the relevant render fns; assert latency tile shows ms (not `—`), verdict tile colored, DLQ view shows full payload. `venv/bin/python tmp/run_pipeline_ui.py` → PASS, no pageerror.

- [ ] **Step 7: Commit**

```bash
git add src/static/js/integrations.js
git commit -m "feat(integrations): 1h SIEM metrics, pipeline verdict tile, DLQ full inspect + replay-by-id"
```

---

## Task 7: Full regression + (optional deploy)

- [ ] **Step 1:** `venv/bin/python -m pytest -q -p no:cacheprovider` — all pass.
- [ ] **Step 2:** Verify the new indexes didn't break existing cache/siem tests: `venv/bin/python -m pytest tests/test_cache_web.py tests/ -k siem -q`.
- [ ] **Step 3:** Commit/push; deploy per session flow if desired; live-verify on the test box (SIEM latency real, DLQ inspect shows full payload).

## Notes for the executor
- No new rollup table — all rates are on-the-fly over indexed timestamps.
- `julianday(a)-julianday(b)` gives days in SQLite; ×86400×1000 → ms.
- `pipeline_verdict` (Task 2) is the single source of truth shared with the dashboard overview — don't duplicate thresholds in JS; prefer a `/api/cache/health` endpoint that calls it.
- `dispatcher._build_payload` (dispatcher.py:126): confirm whether it's callable on a bare source row or needs dispatcher context; the route must degrade to `payload_preview` if rebuild fails.
- Keep glossary terms (SIEM/DLQ/VEN/PCE) English in zh_TW; new UI labels (latency, pipeline health) → Chinese.
