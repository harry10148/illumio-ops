# Phase 15 Implementation Plan — Alerts Subscribe to PCE Cache

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the alert path (`Analyzer.run_analysis()` + `events/poller.py`) to subscribe to the PCE cache via `ingested_at > last_check` polling, eliminating duplicate API calls that currently compete with the Phase 13 ingestor. Enable near-real-time alerts (30s polling floor) without breaching the 500/min PCE budget.

**Architecture:**
- New `CacheSubscriber` (`src/pce_cache/subscriber.py`): given a `since` cursor, returns all rows inserted after it, advancing the cursor on read. One subscriber per analyzer component so events and flows progress independently.
- `Analyzer._run_event_analysis()` (post-Phase 9 decomposition) swaps `api.get_events()` for `subscriber_events.poll_new_rows()` when `pce_cache.enabled`.
- `Analyzer._fetch_traffic()` likewise reads from `CacheSubscriber.poll_new_flows()`.
- `events/poller.py` becomes a thin adapter that delegates to the subscriber; the existing file-based watermark (`config/state.json`) is replaced by a row in `ingestion_watermarks` with `source="analyzer"`.
- APScheduler registers the analyzer job at a **30-second** interval when cache is enabled (vs the current 10-minute default). The 30s tick is cheap — it only reads local SQLite.

**Backward compatibility:** when `pce_cache.enabled = false`, every code path reverts to the current behaviour exactly. No regression for users who haven't enabled the cache.

**Tech Stack:** No new deps. Re-uses Phase 13 SQLAlchemy models + cache infra.

**Branch:** `feature/phase-15-alerts-cache` (from `main` after tag `v3.11.0-siem-cache`; can start in parallel with Phase 14)

**Target tag on merge:** `v3.13.0-alerts-cache`

**Baseline:** ≥ 470 passed (post-Phase 13; Phase 14 independence means this doesn't depend on 495). Target at merge: **≥ 495 passed** (+25 new tests).

---

## Pre-flight

- [ ] `git log --oneline main | head -5` shows Phase 13 merge commit.
- [ ] `src/pce_cache/models.py` importable; `PceEvent`, `PceTrafficFlowRaw`, `IngestionWatermark` all present.
- [ ] `src/analyzer.py::Analyzer.run_analysis` is the post-Phase 9 decomposed form (orchestrator + 5 private methods).

If the last check fails, stop — Phase 15 assumes the Phase 9 decomposition is in place.

---

## File Structure

### Create

| File | Responsibility |
|---|---|
| `src/pce_cache/subscriber.py` | `CacheSubscriber` — per-consumer cursor on `ingested_at` |
| `tests/test_pce_cache_subscriber.py` | Cursor advance, empty poll, duplicate-prevention across restarts |
| `tests/test_analyzer_on_cache.py` | Analyzer event/flow paths use subscriber when cache enabled |
| `tests/test_events_poller_on_cache.py` | Existing poller adapter reads from subscriber |

### Modify

| File | Change |
|---|---|
| `src/pce_cache/models.py` | Extend `IngestionWatermark` — add secondary `IngestionCursor` table for per-consumer cursors (schema migration doc: additive, no breaking change) |
| `src/analyzer.py` | `__init__` gains `subscriber_events`, `subscriber_flows`; `_run_event_analysis` / `_fetch_traffic` switch on presence |
| `src/events/poller.py` | `EventPoller` now delegates to `CacheSubscriber` when provided, else legacy API path |
| `src/main.py` | Construct subscribers when `cm.models.pce_cache.enabled`, pass into `Analyzer` |
| `src/scheduler/__init__.py` | When cache enabled: `monitor_cycle` interval drops from `interval_minutes` minutes to 30 seconds |
| `src/i18n_en.json` + `_ZH_EXPLICIT` | ~6 keys (`monitor_cache_enabled_hint`, `monitor_source_cache`, `monitor_lag_warning`) |
| `docs/PCE_Cache.md` | Add "Alerts on cache" section explaining the 30s tick |
| `docs/Project_Architecture.md` | Update diagram |
| `Status.md` / `Task.md` | Phase 15 entry |

---

## Task 1 — Branch + baseline

- [ ] Branch:

```bash
git checkout main && git pull
git checkout -b feature/phase-15-alerts-cache
```

- [ ] Baseline:

```bash
pytest -q
```

Expect ≥ 470 passed.

---

## Task 2 — `IngestionCursor` table (additive schema)

**Files:** Modify `src/pce_cache/models.py`, `src/pce_cache/schema.py`. Test via `tests/test_pce_cache_schema.py` (existing file — add case).

### Schema

```python
# Add to src/pce_cache/models.py

class IngestionCursor(Base):
    """Per-consumer cursor on `ingested_at` for cache subscribers.

    Separate from IngestionWatermark (which tracks the ingestor's own
    position relative to PCE) — this table tracks downstream consumers
    of the cache itself. Multiple consumers (analyzer, future alert
    engines, exporters) can hold independent cursors.
    """
    __tablename__ = "ingestion_cursors"

    consumer:         Mapped[str]      = mapped_column(String(64), primary_key=True)
    source_table:     Mapped[str]      = mapped_column(String(32), primary_key=True)  # "pce_events"|"pce_traffic_flows_raw"
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_row_id:      Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at:       Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 2.1**: Extend existing schema test to assert 7 tables exist after `init_schema()`.

- [ ] **Step 2.2**: Add the model.

- [ ] **Step 2.3**: Run — PASS.

- [ ] **Step 2.4**: Commit

```bash
git add src/pce_cache/models.py tests/test_pce_cache_schema.py
git commit -m "feat(phase-15): add IngestionCursor table for per-consumer cursors"
```

---

## Task 3 — `CacheSubscriber` implementation

**Files:** Create `src/pce_cache/subscriber.py`, `tests/test_pce_cache_subscriber.py`.

### Semantics

```python
class CacheSubscriber:
    def __init__(self, session_factory, consumer: str, source_table: str):
        ...

    def poll_new_rows(self, limit: int = 1000) -> list[dict]:
        """Return rows inserted since last poll. Advance cursor only on
        successful consumption (caller commits by returning normally)."""
```

Implementation uses `(last_ingested_at, last_row_id)` tuple cursor to avoid missing rows inserted within the same microsecond (SQLite timestamp resolution). Query:

```sql
SELECT * FROM pce_events
WHERE (ingested_at > :last_ts)
   OR (ingested_at = :last_ts AND id > :last_id)
ORDER BY ingested_at, id
LIMIT :limit
```

### Tests (5 cases)

```python
# tests/test_pce_cache_subscriber.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed(sf, uuid, ingested_at):
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href=f"/orgs/1/events/{uuid}",
            pce_event_id=uuid, timestamp=ingested_at,
            event_type="policy.update", severity="info", status="success",
            pce_fqdn="pce.example.com", raw_json="{}", ingested_at=ingested_at,
        ))


def test_first_poll_returns_all_rows(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    _seed(session_factory, "b", datetime(2026, 4, 19, 10, 1, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, consumer="analyzer", source_table="pce_events")
    rows = sub.poll_new_rows()
    assert len(rows) == 2


def test_second_poll_returns_only_new_rows(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, consumer="analyzer", source_table="pce_events")
    assert len(sub.poll_new_rows()) == 1
    assert len(sub.poll_new_rows()) == 0
    _seed(session_factory, "b", datetime(2026, 4, 19, 10, 1, tzinfo=timezone.utc))
    assert len(sub.poll_new_rows()) == 1


def test_cursor_persists_across_subscriber_restart(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    CacheSubscriber(session_factory, "analyzer", "pce_events").poll_new_rows()
    # Fresh subscriber instance should not re-read "a"
    assert len(CacheSubscriber(session_factory, "analyzer", "pce_events")
              .poll_new_rows()) == 0


def test_independent_consumers_have_independent_cursors(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    CacheSubscriber(session_factory, "analyzer", "pce_events").poll_new_rows()
    # Other consumer is still at zero — reads everything
    assert len(CacheSubscriber(session_factory, "exporter", "pce_events")
              .poll_new_rows()) == 1


def test_ties_on_ingested_at_broken_by_row_id(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    same_ts = datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)
    _seed(session_factory, "a", same_ts)
    _seed(session_factory, "b", same_ts)  # same ingested_at, different id
    sub = CacheSubscriber(session_factory, "analyzer", "pce_events")
    rows = sub.poll_new_rows(limit=1)
    assert len(rows) == 1
    rows2 = sub.poll_new_rows(limit=1)
    assert len(rows2) == 1
    assert rows[0]["pce_event_id"] != rows2[0]["pce_event_id"]
```

- [ ] **Step 3.1**: Tests

- [ ] **Step 3.2**: Run — FAIL

- [ ] **Step 3.3**: Implement

```python
# src/pce_cache/subscriber.py
from __future__ import annotations

from datetime import datetime, timezone

import orjson
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    IngestionCursor, PceEvent, PceTrafficFlowRaw,
)

_MODEL_MAP = {
    "pce_events": PceEvent,
    "pce_traffic_flows_raw": PceTrafficFlowRaw,
}


class CacheSubscriber:
    def __init__(self, session_factory: sessionmaker, consumer: str, source_table: str):
        if source_table not in _MODEL_MAP:
            raise ValueError(f"Unknown source_table: {source_table}")
        self._sf = session_factory
        self._consumer = consumer
        self._source = source_table
        self._model = _MODEL_MAP[source_table]

    def poll_new_rows(self, limit: int = 1000) -> list[dict]:
        last_ts, last_id = self._read_cursor()
        with self._sf() as s:
            q = select(self._model).order_by(self._model.ingested_at, self._model.id).limit(limit)
            if last_ts is not None:
                q = q.where(
                    or_(
                        self._model.ingested_at > last_ts,
                        and_(self._model.ingested_at == last_ts, self._model.id > last_id),
                    )
                )
            rows = s.execute(q).scalars().all()
        if not rows:
            return []
        last_row = rows[-1]
        self._write_cursor(last_row.ingested_at, last_row.id)
        return [_row_to_dict(r) for r in rows]

    def _read_cursor(self) -> tuple[datetime | None, int | None]:
        with self._sf() as s:
            row = s.get(IngestionCursor, (self._consumer, self._source))
        if row is None:
            return (None, None)
        return (row.last_ingested_at, row.last_row_id)

    def _write_cursor(self, ts: datetime, row_id: int) -> None:
        now = datetime.now(timezone.utc)
        with self._sf.begin() as s:
            row = s.get(IngestionCursor, (self._consumer, self._source))
            if row is None:
                row = IngestionCursor(consumer=self._consumer, source_table=self._source,
                                      updated_at=now)
                s.add(row)
            row.last_ingested_at = ts
            row.last_row_id = row_id
            row.updated_at = now


def _row_to_dict(row) -> dict:
    if hasattr(row, "raw_json") and row.raw_json:
        try:
            return orjson.loads(row.raw_json)
        except orjson.JSONDecodeError:
            pass
    # Fallback minimal projection
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
```

- [ ] **Step 3.4**: Run — PASS (5 tests)

- [ ] **Step 3.5**: Commit

```bash
git add src/pce_cache/subscriber.py tests/test_pce_cache_subscriber.py
git commit -m "feat(phase-15): CacheSubscriber with persistent per-consumer cursor"
```

---

## Task 4 — `Analyzer` migration

**Files:** Modify `src/analyzer.py`. Create `tests/test_analyzer_on_cache.py`.

### Design

`Analyzer.__init__` gains:

```python
def __init__(
    self,
    ...existing...,
    subscriber_events: CacheSubscriber | None = None,
    subscriber_flows: CacheSubscriber | None = None,
):
    self._sub_events = subscriber_events
    self._sub_flows = subscriber_flows
```

`_run_event_analysis()` becomes:

```python
def _run_event_analysis(self):
    if self._sub_events is not None:
        events = self._sub_events.poll_new_rows(limit=5000)
        logger.info("Analyzer event path: cache ({} rows)", len(events))
    else:
        events = self._legacy_event_pull()  # extracted from current code
    ...feed into existing normalizer + matcher + throttle...
```

`_fetch_traffic()` mirrors the same pattern for flows. The rest of the pipeline — normalization, rule matching, alert dispatch — is unchanged.

- [ ] **Step 4.1**: Tests (4 cases)
  - `test_analyzer_uses_subscriber_when_enabled`
  - `test_analyzer_falls_back_to_api_when_subscriber_none`
  - `test_analyzer_processes_empty_poll_without_dispatching`
  - `test_analyzer_dispatches_on_new_events_from_cache`

- [ ] **Step 4.2**: Extract `_legacy_event_pull()` from current `_run_event_analysis()` body (preserving behaviour).

- [ ] **Step 4.3**: Add the cache branch.

- [ ] **Step 4.4**: Same for `_fetch_traffic()`.

- [ ] **Step 4.5**: Run — PASS, all existing analyzer tests still green.

- [ ] **Step 4.6**: Commit

```bash
git add src/analyzer.py tests/test_analyzer_on_cache.py
git commit -m "feat(phase-15): analyzer reads events+flows from CacheSubscriber"
```

---

## Task 5 — `events/poller.py` adapter

**Files:** Modify `src/events/poller.py`. Create `tests/test_events_poller_on_cache.py`.

### Design

`EventPoller.__init__` gains an optional `subscriber` kwarg. `EventPoller.poll()` becomes:

```python
def poll(self):
    if self._subscriber is not None:
        return self._subscriber.poll_new_rows(limit=self._limit)
    return self._legacy_poll()  # existing API + config/state.json watermark code
```

Migration of existing callers: `src/main.py` and `src/analyzer.py` construct `EventPoller(subscriber=...)` when cache enabled.

- [ ] **Step 5.1**: Tests (3 cases)
- [ ] **Step 5.2**: Implement
- [ ] **Step 5.3**: Wire call sites
- [ ] **Step 5.4**: Run — PASS, existing poller tests still green
- [ ] **Step 5.5**: Commit

```bash
git add src/events/poller.py src/main.py src/analyzer.py tests/test_events_poller_on_cache.py
git commit -m "feat(phase-15): EventPoller delegates to CacheSubscriber when provided"
```

---

## Task 6 — Near-real-time monitor tick (30s when cache on)

**Files:** Modify `src/scheduler/__init__.py`. Create `tests/test_scheduler_intervals.py`.

### Design

`build_scheduler(cm, interval_minutes)` currently hard-codes the monitor tick at `IntervalTrigger(minutes=interval_minutes)`. Change to:

```python
if cm.models.pce_cache.enabled:
    monitor_trigger = IntervalTrigger(seconds=30)
    logger.info("Monitor tick: 30s (reading from PCE cache)")
else:
    monitor_trigger = IntervalTrigger(minutes=interval_minutes)
    logger.info("Monitor tick: {}m (direct API)", interval_minutes)

sched.add_job(run_monitor_cycle, trigger=monitor_trigger, args=[cm],
              id="monitor_cycle", replace_existing=True)
```

Rationale: reading local SQLite at 30s is free. The ingestor continues pulling PCE at its configured interval; the analyzer just catches up faster.

- [ ] **Step 6.1**: Tests (2 cases) — verify `monitor_cycle` job interval flips based on config.
- [ ] **Step 6.2**: Implement.
- [ ] **Step 6.3**: i18n keys `monitor_cache_enabled_hint` / `monitor_source_cache`.
- [ ] **Step 6.4**: Run — PASS.
- [ ] **Step 6.5**: Commit

```bash
git add src/scheduler/__init__.py tests/test_scheduler_intervals.py src/i18n_en.json src/i18n.py
git commit -m "feat(phase-15): 30s analyzer tick when pce_cache enabled"
```

---

## Task 7 — Alert lag monitoring

**Files:** Create `src/pce_cache/lag_monitor.py`, `tests/test_lag_monitor.py`.

### Design

New alert: when the ingestor's `ingestion_watermarks.last_sync_at` is older than `max(events_poll_interval_seconds, traffic_poll_interval_seconds) * 3`, emit a warning-level alert through the existing `Reporter` pipeline. This catches ingestor stalls that would otherwise silently make alerts inaccurate.

- [ ] **Step 7.1**: Tests (3 cases)
  - `test_lag_monitor_silent_when_within_threshold`
  - `test_lag_monitor_warns_when_exceeds_threshold`
  - `test_lag_monitor_error_when_exceeds_2x_threshold`

- [ ] **Step 7.2**: Implement as an APScheduler job — `run_cache_lag_monitor(cm)` registered at 60s interval when cache enabled.

- [ ] **Step 7.3**: i18n keys `alert_cache_lag_warning` / `alert_cache_lag_error`.

- [ ] **Step 7.4**: Commit

```bash
git add src/pce_cache/lag_monitor.py tests/test_lag_monitor.py src/scheduler \
        src/i18n_en.json src/i18n.py
git commit -m "feat(phase-15): cache lag monitor alerts on stalled ingestor"
```

---

## Task 8 — Docs + final validation

**Files:** Modify `docs/PCE_Cache.md`, `docs/Project_Architecture.md` (+ zh variant), `Status.md`, `Task.md`. Create `tests/test_phase_15_e2e.py`.

### E2E scenario

1. Cache seeded with 3 historical events.
2. Analyzer runs once — consumes all 3, fires alerts for matched rules.
3. 1 new event lands in cache → wait 30s (or force scheduler tick) → analyzer picks up 1 new event only.
4. Simulate ingestor stall (advance clock > 3x poll interval without `last_sync_at` update) → lag monitor emits warning.

- [ ] **Step 8.1**: Write E2E
- [ ] **Step 8.2**: Update architecture diagram (new arrow: `pce_cache → CacheSubscriber → Analyzer`)
- [ ] **Step 8.3**: Run full suite — expect **≥ 495 passed** (baseline 470 + 25 new)
- [ ] **Step 8.4**: i18n audit — 0 findings
- [ ] **Step 8.5**: Status.md + Task.md updates
- [ ] **Step 8.6**: PR + tag

```bash
git push -u origin feature/phase-15-alerts-cache
gh pr create --title "feat(v3.13.0): Phase 15 — alerts subscribe to PCE cache" \
             --body "$(cat <<'EOF'
## Summary
- `CacheSubscriber` + per-consumer cursor table
- `Analyzer.run_analysis()` event/flow paths read from cache when enabled
- `EventPoller` delegates to subscriber; legacy state.json unchanged when cache off
- 30s monitor tick when cache enabled (vs configured interval_minutes otherwise)
- Cache lag monitor warns on stalled ingestor

## Test plan
- [x] 495+ tests pass, 0 regressions
- [x] i18n audit 0 findings
- [x] E2E covers cache-hit / empty-poll / lag-warning / ingestor stall
- [x] Manual: verify monitor tick drops to 30s when pce_cache.enabled=true
EOF
)"

# On merge
git tag v3.13.0-alerts-cache && git push --tags
```

---

## Self-review checklist

- [ ] When `pce_cache.enabled = false`, every analyzer/poller path is byte-identical to pre-Phase-15 behaviour.
- [ ] Cursor persists across daemon restart (tested).
- [ ] Cursor ties on `ingested_at` broken deterministically by row id — no missed or duplicate events.
- [ ] 30s monitor tick only active when cache enabled; does NOT cause API spam (reads SQLite only).
- [ ] Lag monitor catches ingestor stalls before alerts silently drift.
- [ ] No changes to alert plugin APIs — `EMAIL` / `LINE` / `WEBHOOK` still receive their existing payload shape.

---

## Post-merge follow-up

1. Document in release notes: operators should expect alert latency to drop from `interval_minutes` to ~30s when they enable the cache.
2. Consider (Phase 16?) eliminating the legacy `config/state.json` event watermark path entirely once all deployments have migrated. Until then, both paths coexist by design.
