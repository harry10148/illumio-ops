# Cache Coverage + Ingestor Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make report generation prefer the SQLite cache when it actually contains data, surface ingestor failures, fix the daemon-restart cascade that prevents periodic flow ingest from running, and add an opt-in UI option to clip the report range to the cache window.

**Architecture:** Four independent commits, each individually revertable.
1. `cover_state` switches from `MIN(ingested_at)` to a new `earliest_data_timestamp` helper using `MIN(last_detected)` (traffic) / `MIN(timestamp)` (events). Backfilled rows then count as covered.
2. When the hybrid API gap returns zero rows, retag the source from `"mixed"` to `"cache"` so empty fallbacks don't pollute the report metadata.
3. Cache ingest jobs are scheduled with `next_run_time=now+10s`, the traffic poll interval drops from 3600s → 600s, and `TrafficIngestor.run_once()` always emits a per-poll log line so silent skips become visible.
4. Add a `clip_to_cache` parameter that clips the report start/end to the cache's actual data range, surfaced in the GUI as an off-by-default checkbox above the format selector.

**Tech Stack:** Python 3.12, SQLAlchemy 2, APScheduler `BackgroundScheduler` + `IntervalTrigger`, Flask, Jinja2 templates, vanilla JS, pytest, Loguru.

**Test runner:** This repo's `venv/bin/pytest` shebang is broken (points at an old path). Always invoke pytest as:
```
venv/bin/python3 -m pytest <args>
```

---

## File Structure

| Commit | Modify | Test |
|---|---|---|
| 1 | `src/pce_cache/reader.py`<br>`src/report/report_generator.py:181`<br>`src/report/audit_generator.py:447`<br>`src/analyzer.py:856` | `tests/test_pce_cache_reader.py` |
| 2 | `src/report/report_generator.py:_fetch_traffic`<br>`src/report/audit_generator.py:_fetch_events`<br>`src/analyzer.py` (hybrid branch) | `tests/test_report_generator_on_cache.py` |
| 3 | `src/scheduler/__init__.py:102-111`<br>`src/pce_cache/ingestor_traffic.py:run_once`<br>`config/config.json` | `tests/test_pce_cache_ingestor_traffic.py`<br>`tests/test_scheduler_setup.py` |
| 4 | `src/report/report_generator.py:generate_from_api`<br>`src/gui/routes/reports.py:api_generate_report`<br>`src/templates/index.html:1878`<br>`src/static/js/dashboard.js:980-988`<br>`src/i18n_en.json`, `src/i18n_zh_TW.json` | `tests/test_report_generator_on_cache.py` |

Each commit is self-contained — Commit 2 builds on Commit 1's helper but doesn't *require* it; the code paths overlap but test files don't.

---

## Task 1: `cover_state` uses data timestamp, not ingest time

**Why:** Current `cover_state` calls `earliest_ingested_at` (`MIN(ingested_at)`). When a backfill writes rows whose `last_detected` is days old but `ingested_at = now`, `cover_state` reports the cache as starting "today", forcing every future report into hybrid fetch. The reader.py:39-41 comment ("This is intentional") documents the existing trade-off; this task replaces that trade-off with one that respects backfilled data.

**Files:**
- Modify: `src/pce_cache/reader.py` — add `earliest_data_timestamp(source)`, switch `cover_state` to it
- Modify: `src/report/report_generator.py:181` — partial branch's `cache_start`
- Modify: `src/report/audit_generator.py:447` — partial branch's `cache_start`
- Modify: `src/analyzer.py:856` — partial branch's `cache_start`
- Test: `tests/test_pce_cache_reader.py` — new regression test

- [ ] **Step 1.1: Write the failing regression test**

Append to `tests/test_pce_cache_reader.py`:

```python
def test_cover_state_full_when_backfill_old_data_with_recent_ingested_at(session_factory):
    """Regression: backfill writes old `timestamp` but recent `ingested_at`.
    cover_state must judge by data timestamp so request whose start ≥ data
    start returns 'full', not 'partial'.
    """
    now = datetime.now(timezone.utc)
    data_ts = now - timedelta(days=5)        # event happened 5 days ago
    ingest_ts = now - timedelta(hours=1)     # but was backfilled an hour ago
    with session_factory.begin() as s:
        s.add(PceEvent(
            pce_href="/orgs/1/events/backfill-1",
            pce_event_id="backfill-1",
            timestamp=data_ts,
            event_type="policy.update",
            severity="info",
            status="success",
            pce_fqdn="pce.example.com",
            raw_json='{"event_type": "policy.update"}',
            ingested_at=ingest_ts,
        ))
    rd = CacheReader(session_factory, events_retention_days=90, traffic_raw_retention_days=7)
    # Request 4 days back — start (4d) ≥ data_ts (5d ago); cache covers it
    assert rd.cover_state("events", now - timedelta(days=4), now) == "full"
```

- [ ] **Step 1.2: Run the new test, confirm it fails**

```bash
venv/bin/python3 -m pytest tests/test_pce_cache_reader.py::test_cover_state_full_when_backfill_old_data_with_recent_ingested_at -v
```
Expected: `FAILED ... AssertionError: assert 'partial' == 'full'`

- [ ] **Step 1.3: Add `earliest_data_timestamp` helper in `reader.py`**

Insert after the existing `earliest_ingested_at` method (around line 50) in `src/pce_cache/reader.py`:

```python
    def earliest_data_timestamp(self, source: str) -> datetime | None:
        """MIN(last_detected) for traffic, MIN(timestamp) for events.
        Used by cover_state to judge cache coverage by ACTUAL data window,
        not by when rows were inserted (which would defeat backfill workflows).
        """
        if source == "events":
            col = PceEvent.timestamp
        else:
            col = PceTrafficFlowRaw.last_detected
        with self._sf() as s:
            result = s.execute(select(func.min(col))).scalar()
            if result is None:
                return None
            if result.tzinfo is None:
                result = result.replace(tzinfo=timezone.utc)
            return result
```

- [ ] **Step 1.4: Switch `cover_state` to use the new helper**

In `src/pce_cache/reader.py:33-34`, replace:

```python
        earliest = self.earliest_ingested_at(source)
        if earliest is None or start < earliest:
            return "partial"
```

with:

```python
        earliest = self.earliest_data_timestamp(source)
        if earliest is None or start < earliest:
            return "partial"
```

Also update the comment block on `earliest_ingested_at` (line 39-41) — it currently claims its conservative behavior is "intentional" via cover_state. After this change cover_state no longer calls it. Replace the comment with:

```python
    def earliest_ingested_at(self, source: str) -> datetime | None:
        """MIN(ingested_at). Operational metric for ingest-lag monitoring.
        NOT used by cover_state — see earliest_data_timestamp for that.
        """
```

- [ ] **Step 1.5: Run the new test + the rest of test_pce_cache_reader.py**

```bash
venv/bin/python3 -m pytest tests/test_pce_cache_reader.py -v
```
Expected: ALL PASS (8 existing + 1 new = 9).

- [ ] **Step 1.6: Update three callers' `cache_start` to use the data timestamp**

The partial branches compute `cache_start` for the API gap. They must use the same helper or the API gap will still be measured against `ingested_at`.

`src/report/report_generator.py:181` — replace:
```python
                cache_start = self._cache.earliest_ingested_at("traffic")
```
with:
```python
                cache_start = self._cache.earliest_data_timestamp("traffic")
```

`src/report/audit_generator.py:447` — replace:
```python
                cache_start = self._cache.earliest_ingested_at("events")
```
with:
```python
                cache_start = self._cache.earliest_data_timestamp("events")
```

`src/analyzer.py:856` — replace:
```python
            cache_start = self._cache_reader.earliest_ingested_at("traffic")
```
with:
```python
            cache_start = self._cache_reader.earliest_data_timestamp("traffic")
```

- [ ] **Step 1.7: Update the cache_reader test mock helper**

In `tests/test_report_generator_on_cache.py:23-29`, the helper currently mocks `earliest_ingested_at`. Add the new method too so the tests still drive the partial branch:

```python
def _make_cache_reader(cover_state="full", flows=None, earliest=None):
    cr = MagicMock()
    cr.cover_state.return_value = cover_state
    cr.read_flows_raw.return_value = flows or [_make_flow()]
    cr.read_flows_agg.return_value = []
    cr.earliest_ingested_at.return_value = earliest
    cr.earliest_data_timestamp.return_value = earliest
    return cr
```

- [ ] **Step 1.8: Run all affected test files**

```bash
venv/bin/python3 -m pytest tests/test_pce_cache_reader.py tests/test_report_generator_on_cache.py tests/test_phase_14_e2e.py -v
```
Expected: ALL PASS.

- [ ] **Step 1.9: Commit**

```bash
git add src/pce_cache/reader.py src/report/report_generator.py src/report/audit_generator.py src/analyzer.py tests/test_pce_cache_reader.py tests/test_report_generator_on_cache.py
git commit -m "$(cat <<'EOF'
fix(cache): cover_state judges coverage by data timestamp, not ingest time

cover_state previously called earliest_ingested_at (MIN(ingested_at)),
which intentionally returned 'partial' after a backfill — rows with old
last_detected but recent ingested_at were treated as if the cache only
started "today". That defeated the backfill workflow entirely.

Add earliest_data_timestamp() returning MIN(last_detected) for traffic
and MIN(timestamp) for events, and route cover_state plus the three
hybrid-fetch partial branches (report_generator, audit_generator,
analyzer.query_flows) through it. earliest_ingested_at is preserved
for ingest-lag monitoring.
EOF
)"
```

---

## Task 2: Hybrid empty-gap retag — `mixed` → `cache`

**Why:** When `cover_state="partial"`, the code fetches an API gap and tags the result as `"mixed"`. If the gap returns zero rows (PCE has no data in that window — common when the request range starts before PCE retention), every report metadata field still says "mixed", which misleads the user and pollutes downstream snapshots.

**Files:**
- Modify: `src/report/report_generator.py` lines ~180-194 (`_fetch_traffic`)
- Modify: `src/report/audit_generator.py` lines ~446-464 (`_fetch_events`)
- Modify: `src/analyzer.py` lines ~855-869 (hybrid traffic branch)
- Test: `tests/test_report_generator_on_cache.py` (add 1 new test)

- [ ] **Step 2.1: Write the failing test**

Append to `tests/test_report_generator_on_cache.py`:

```python
def test_fetch_traffic_partial_with_empty_api_gap_tags_as_cache(tmp_path):
    """When PCE returns zero rows for the gap, the result is effectively
    full cache — source must be 'cache', not 'mixed'."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()  # already returns []
    cache_start = datetime.now(timezone.utc) - timedelta(days=3)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = datetime.now(timezone.utc) - timedelta(days=7)
    end = datetime.now(timezone.utc)
    result = gen._fetch_traffic(start, end)
    assert result["source"] == "cache"
    api.fetch_traffic_for_report.assert_called_once()
    cache.read_flows_raw.assert_called_once()
```

- [ ] **Step 2.2: Run the test, confirm it fails**

```bash
venv/bin/python3 -m pytest tests/test_report_generator_on_cache.py::test_fetch_traffic_partial_with_empty_api_gap_tags_as_cache -v
```
Expected: `FAILED ... assert 'mixed' == 'cache'`

- [ ] **Step 2.3: Update `_fetch_traffic` partial branch**

In `src/report/report_generator.py:180-194`, replace:

```python
            if state == "partial":
                cache_start = self._cache.earliest_data_timestamp("traffic")
                if cache_start is not None and cache_start > start:
                    logger.info(
                        "Traffic report: hybrid fetch — API gap [{} → {}), cache [{} → {}]",
                        start, cache_start, cache_start, end,
                    )
                    gap = self.api.fetch_traffic_for_report(
                        start_time_str=_fmt_iso(start),
                        end_time_str=_fmt_iso(cache_start),
                        filters=filters,
                    ) or []
                    cached = self._cache.read_flows_raw(cache_start, end)
                    # agg data not available for hybrid results
                    return {"raw": gap + cached, "agg": None, "source": "mixed"}
```

with:

```python
            if state == "partial":
                cache_start = self._cache.earliest_data_timestamp("traffic")
                if cache_start is not None and cache_start > start:
                    logger.info(
                        "Traffic report: hybrid fetch — API gap [{} → {}), cache [{} → {}]",
                        start, cache_start, cache_start, end,
                    )
                    gap = self.api.fetch_traffic_for_report(
                        start_time_str=_fmt_iso(start),
                        end_time_str=_fmt_iso(cache_start),
                        filters=filters,
                    ) or []
                    cached = self._cache.read_flows_raw(cache_start, end)
                    # agg data not available for hybrid results
                    source = "mixed" if gap else "cache"
                    return {"raw": gap + cached, "agg": None, "source": source}
```

- [ ] **Step 2.4: Run the new test, confirm it passes**

```bash
venv/bin/python3 -m pytest tests/test_report_generator_on_cache.py -v
```
Expected: ALL PASS.

- [ ] **Step 2.5: Apply identical change to `_fetch_events`**

In `src/report/audit_generator.py:462-464`, replace:

```python
                    if gap is not None:
                        cached = self._cache.read_events(cache_start, end)
                        return gap + cached, "mixed"
```

with:

```python
                    if gap is not None:
                        cached = self._cache.read_events(cache_start, end)
                        source = "mixed" if gap else "cache"
                        return gap + cached, source
```

- [ ] **Step 2.6: Apply identical change to `analyzer.query_flows`**

In `src/analyzer.py:868-869`, replace:

```python
                gap_list = list(gap_stream) if gap_stream else []
                return gap_list + cached, "mixed"
```

with:

```python
                gap_list = list(gap_stream) if gap_stream else []
                source = "mixed" if gap_list else "cache"
                return gap_list + cached, source
```

- [ ] **Step 2.7: Run all affected test suites**

```bash
venv/bin/python3 -m pytest tests/test_report_generator_on_cache.py tests/test_phase_14_e2e.py -v
```
Expected: ALL PASS.

- [ ] **Step 2.8: Commit**

```bash
git add src/report/report_generator.py src/report/audit_generator.py src/analyzer.py tests/test_report_generator_on_cache.py
git commit -m "$(cat <<'EOF'
fix(cache): retag hybrid 'mixed' as 'cache' when API gap is empty

cover_state='partial' triggers a hybrid fetch that asks PCE for the gap
before cache_start. When PCE retention is shorter than the request
window, that gap legitimately returns zero rows — every flow in the
result actually came from the cache. Previously the report metadata
still said 'mixed', which polluted trend snapshots and confused users.

Apply the retag in all three hybrid sites: report_generator._fetch_traffic,
audit_generator._fetch_events, analyzer.query_flows.
EOF
)"
```

---

## Task 3: Scheduler reliability — fire on restart, halve interval, log every poll

**Why:** Three compounding issues prevent periodic ingest from running:
1. Each `/api/daemon/restart` re-adds jobs with `replace_existing=True`. APScheduler resets `next_run_time = now + interval`. With restarts every few minutes (Integrations UI saves trigger restart) and `traffic_poll_interval_seconds=3600`, the timer almost never reaches first fire.
2. `traffic_poll_interval_seconds=3600` (1 h) means up to an hour of staleness even when fires happen.
3. `TrafficIngestor.run_once()` only logs `"Traffic ingest: N rows inserted"` *after* it runs successfully and inserts ≥1 row. When PCE returns 0 flows or the job never fired, there's no trace.

**Files:**
- Modify: `src/scheduler/__init__.py:102-111` — pass `next_run_time` to ingest jobs
- Modify: `src/pce_cache/ingestor_traffic.py:38-56` — log every poll
- Modify: `config/config.json` — `traffic_poll_interval_seconds: 3600 → 600`
- Test: `tests/test_pce_cache_ingestor_traffic.py` (add log-line test)
- Test: `tests/test_scheduler_setup.py` (add next_run_time test)

- [ ] **Step 3.1: Write the failing log-line test**

Append to `tests/test_pce_cache_ingestor_traffic.py`:

```python
def test_run_once_logs_poll_summary_even_on_empty(session_factory, caplog):
    """Empty PCE response must still emit an INFO line so silent skips
    are visible in the log timeline."""
    import logging
    from unittest.mock import MagicMock
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    fake = MagicMock()
    fake.get_traffic_flows_async = MagicMock(return_value=[])
    ing = TrafficIngestor(api=fake, session_factory=session_factory,
                           watermark=WatermarkStore(session_factory))
    with caplog.at_level(logging.INFO, logger="src.pce_cache.ingestor_traffic"):
        n = ing.run_once()
    assert n == 0
    # Must contain a poll-summary line that names fetched + inserted counts
    assert any("Traffic ingest poll" in rec.message for rec in caplog.records), \
        f"expected 'Traffic ingest poll' line; got: {[r.message for r in caplog.records]}"
```

(`session_factory` fixture should already exist in this test file. If not, copy the one from `tests/test_pce_cache_reader.py`.)

- [ ] **Step 3.2: Run the test, confirm it fails**

```bash
venv/bin/python3 -m pytest tests/test_pce_cache_ingestor_traffic.py::test_run_once_logs_poll_summary_even_on_empty -v
```
Expected: `FAILED` — no log line matches.

- [ ] **Step 3.3: Add poll-summary log in `run_once`**

In `src/pce_cache/ingestor_traffic.py:38-56`, replace:

```python
    def run_once(self) -> int:
        since = self._since_cursor()
        try:
            flows = self._api.get_traffic_flows_async(
                max_results=self._max_results,
                rate_limit=True,
                since=since,
            )
        except Exception as exc:
            logger.exception("Traffic ingest failed: {}", exc)
            self._wm.record_error(self.SOURCE, str(exc))
            return 0

        inserted = self._insert_batch(flows)
        if flows:
            last = max(_ts(f, "last_detected") for f in flows)
            if last:
                self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last))
        return inserted
```

with:

```python
    def run_once(self) -> int:
        since = self._since_cursor()
        try:
            flows = self._api.get_traffic_flows_async(
                max_results=self._max_results,
                rate_limit=True,
                since=since,
            )
        except Exception as exc:
            logger.exception("Traffic ingest failed: {}", exc)
            self._wm.record_error(self.SOURCE, str(exc))
            return 0

        inserted = self._insert_batch(flows)
        watermark_advanced = False
        if flows:
            last = max(_ts(f, "last_detected") for f in flows)
            if last:
                self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last))
                watermark_advanced = True
        logger.info(
            "Traffic ingest poll: fetched={} inserted={} watermark_advanced={} since={}",
            len(flows), inserted, watermark_advanced, since,
        )
        return inserted
```

- [ ] **Step 3.4: Run the test, confirm it passes**

```bash
venv/bin/python3 -m pytest tests/test_pce_cache_ingestor_traffic.py -v
```
Expected: ALL PASS.

- [ ] **Step 3.5: Write the failing scheduler `next_run_time` test**

Append to `tests/test_scheduler_setup.py`:

```python
def test_cache_ingest_jobs_have_next_run_time_within_30s(monkeypatch, tmp_path):
    """Ingest jobs must fire within ~10s of scheduler start, not after
    a full traffic_poll_interval_seconds delay. Otherwise daemon restarts
    keep resetting the timer and ingest never runs."""
    import datetime as _dt
    from src.scheduler import build_scheduler

    class _CM:
        def __init__(self):
            self.config = {"scheduler": {}, "rule_scheduler": {"check_interval_seconds": 300}}
            class _PCE:
                enabled = True
                db_path = str(tmp_path / "c.sqlite")
                events_poll_interval_seconds = 300
                traffic_poll_interval_seconds = 600
                rate_limit_per_minute = 400
                async_threshold_events = 10000
                class _S:
                    sample_ratio_allowed = 1
                    max_rows_per_batch = 200000
                traffic_sampling = _S()
                traffic_filter = type("F", (), {"actions": [], "workload_label_env": [],
                                                "ports": [], "protocols": [], "exclude_src_ips": []})()
                events_retention_days = 90
                traffic_raw_retention_days = 7
                traffic_agg_retention_days = 90
            class _SIEM:
                enabled = False
            self.models = type("M", (), {"pce_cache": _PCE(), "siem": _SIEM()})()

    sched = build_scheduler(_CM(), interval_minutes=10)
    now = _dt.datetime.now(_dt.timezone.utc)
    job = sched.get_job("pce_cache_ingest_traffic")
    assert job is not None
    delta = (job.next_run_time - now).total_seconds()
    assert -5 <= delta <= 30, f"expected first fire within ~30s of start; got delta={delta}s"
```

- [ ] **Step 3.6: Run the test, confirm it fails**

```bash
venv/bin/python3 -m pytest tests/test_scheduler_setup.py::test_cache_ingest_jobs_have_next_run_time_within_30s -v
```
Expected: `FAILED` — `delta` ≈ 600 (the full interval).

- [ ] **Step 3.7: Add `next_run_time` to ingest job registrations**

In `src/scheduler/__init__.py:96-111`, replace the `if cache_cfg.enabled:` block:

```python
        if cache_cfg.enabled:
            from apscheduler.triggers.interval import IntervalTrigger as _IT
            from src.scheduler.jobs import (
                run_events_ingest, run_traffic_ingest,
                run_traffic_aggregate, run_cache_retention,
            )
            from src.pce_cache.lag_monitor import run_cache_lag_monitor
            sched.add_job(run_events_ingest, _IT(seconds=cache_cfg.events_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_events", replace_existing=True)
            sched.add_job(run_traffic_ingest, _IT(seconds=cache_cfg.traffic_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_traffic", replace_existing=True)
            sched.add_job(run_traffic_aggregate, _IT(hours=1),
                          args=[cm], id="pce_cache_aggregate", replace_existing=True)
            sched.add_job(run_cache_retention, _IT(hours=24),
                          args=[cm], id="pce_cache_retention", replace_existing=True)
            sched.add_job(run_cache_lag_monitor, _IT(seconds=60),
                          args=[cm], id="cache_lag_monitor", replace_existing=True)
```

with:

```python
        if cache_cfg.enabled:
            import datetime as _dt
            from apscheduler.triggers.interval import IntervalTrigger as _IT
            from src.scheduler.jobs import (
                run_events_ingest, run_traffic_ingest,
                run_traffic_aggregate, run_cache_retention,
            )
            from src.pce_cache.lag_monitor import run_cache_lag_monitor
            # Fire ingest jobs ~10s after scheduler start so daemon restarts
            # don't keep resetting the timer to (now + full interval), which
            # previously kept periodic ingest from ever firing across many
            # restarts within one interval window.
            _kick = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=10)
            sched.add_job(run_events_ingest, _IT(seconds=cache_cfg.events_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_events", replace_existing=True,
                          next_run_time=_kick)
            sched.add_job(run_traffic_ingest, _IT(seconds=cache_cfg.traffic_poll_interval_seconds),
                          args=[cm], id="pce_cache_ingest_traffic", replace_existing=True,
                          next_run_time=_kick)
            sched.add_job(run_traffic_aggregate, _IT(hours=1),
                          args=[cm], id="pce_cache_aggregate", replace_existing=True)
            sched.add_job(run_cache_retention, _IT(hours=24),
                          args=[cm], id="pce_cache_retention", replace_existing=True)
            sched.add_job(run_cache_lag_monitor, _IT(seconds=60),
                          args=[cm], id="cache_lag_monitor", replace_existing=True)
```

- [ ] **Step 3.8: Run the scheduler test + ingestor tests**

```bash
venv/bin/python3 -m pytest tests/test_scheduler_setup.py tests/test_pce_cache_ingestor_traffic.py -v
```
Expected: ALL PASS.

- [ ] **Step 3.9: Halve the traffic poll interval**

Edit `config/config.json` — under `pce_cache`, change:
```json
"traffic_poll_interval_seconds": 3600,
```
to:
```json
"traffic_poll_interval_seconds": 600,
```

- [ ] **Step 3.10: Verify config loads cleanly**

```bash
venv/bin/python3 -c "import json; c=json.load(open('config/config.json')); assert c['pce_cache']['traffic_poll_interval_seconds'] == 600; print('OK')"
```
Expected: `OK`

- [ ] **Step 3.11: Commit**

```bash
git add src/scheduler/__init__.py src/pce_cache/ingestor_traffic.py config/config.json tests/test_pce_cache_ingestor_traffic.py tests/test_scheduler_setup.py
git commit -m "$(cat <<'EOF'
fix(scheduler): cache ingest fires on restart, traffic poll 1h→10min

Three issues kept periodic flow ingest from running:

1. Each /api/daemon/restart re-added the ingest jobs with
   replace_existing=True, which reset next_run_time to now + interval.
   With the Integrations UI triggering restarts every few minutes and
   traffic_poll_interval_seconds=3600, the first fire never arrived.
2. 1-hour interval is too sparse — even if fires happened, cache lag
   reached 1h before catching new flows.
3. TrafficIngestor.run_once only logged after a successful insert, so
   "PCE returned 0 flows" runs left no trace.

Pass next_run_time = now + 10s when registering the events/traffic
ingest jobs so they fire shortly after scheduler start regardless of
restart count. Drop traffic_poll_interval_seconds 3600 → 600. Add a
"Traffic ingest poll: fetched=N inserted=N watermark_advanced=…" line
so empty polls are visible.
EOF
)"
```

---

## Task 4: Opt-in `clip_to_cache` parameter + GUI checkbox

**Why:** Even with Tasks 1-3, when the request window starts before the cache window (e.g. user asks for 7 days but cache only holds 5), the system still calls the API for the leading gap. If the user accepts that the cache is the source of truth, they want the report range silently clipped to what the cache actually has — eliminating the API call entirely.

**Files:**
- Modify: `src/report/report_generator.py:204-272` (`generate_from_api` signature + clip logic)
- Modify: `src/gui/routes/reports.py:142-260` (`api_generate_report` accepts `clip_to_cache`)
- Modify: `src/templates/index.html:1878` (insert checkbox above format selector)
- Modify: `src/static/js/dashboard.js:982-988` (read checkbox, send field)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json` (3 new keys)
- Test: `tests/test_report_generator_on_cache.py` (add 2 clip tests)

- [ ] **Step 4.1: Write the failing clip-on test**

Append to `tests/test_report_generator_on_cache.py`:

```python
def test_generate_from_api_clip_to_cache_clips_start_to_cache_data(tmp_path):
    """clip_to_cache=True must clip the request start to earliest_data_timestamp,
    so the API call covers no leading gap and source ends up 'cache'."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    cache_start = datetime.now(timezone.utc) - timedelta(days=3)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = gen.generate_from_api(start_date=start, end_date=end, clip_to_cache=True)
    # cover_state was forced to be re-evaluated against clipped start;
    # cache.cover_state should now be called with clipped start ≥ cache_start
    args, _ = cache.cover_state.call_args
    clipped_start = args[1]
    assert clipped_start >= cache_start - timedelta(seconds=1)
    api.fetch_traffic_for_report.assert_not_called()  # cover_state full → no API
```

For the assertion to work, the test also needs `cover_state` to flip from "partial" to "full" when called with the clipped start. Adjust the mock side_effect:

```python
    # Allow cover_state to look at the actual start passed in
    def _cover(source, s, e):
        return "full" if s >= cache_start else "partial"
    cache.cover_state.side_effect = _cover
```

Place this *before* the `gen.generate_from_api(...)` call.

- [ ] **Step 4.2: Run the test, confirm it fails**

```bash
venv/bin/python3 -m pytest tests/test_report_generator_on_cache.py::test_generate_from_api_clip_to_cache_clips_start_to_cache_data -v
```
Expected: `FAILED` — `generate_from_api()` got an unexpected keyword argument `'clip_to_cache'`.

- [ ] **Step 4.3: Add `clip_to_cache` parameter and clipping logic**

In `src/report/report_generator.py`, change the `generate_from_api` signature (line 204-210):

```python
    def generate_from_api(self, start_date: Optional[str] = None,
                          end_date: Optional[str] = None,
                          max_results: int = 200_000,
                          filters: Optional[dict] = None,
                          traffic_report_profile: str = "security_risk",
                          detail_level: str = _REPORT_DETAIL_LEVEL,
                          lang: str = "en",
                          clip_to_cache: bool = False) -> ReportResult:
```

Then, after the existing `start_dt = ...` / `end_dt = ...` block (around line 234-235), insert:

```python
        # Clip the request window to actual cache data range when requested.
        # Lets the user opt out of the leading-gap API call when PCE has
        # nothing older than what the cache already holds.
        if clip_to_cache and self._cache is not None:
            cache_earliest = self._cache.earliest_data_timestamp("traffic")
            if cache_earliest is not None and cache_earliest > start_dt:
                logger.info(
                    "ReportGenerator: clip_to_cache clipping start {} → {}",
                    start_dt, cache_earliest,
                )
                start_dt = cache_earliest
                start_date = start_dt.isoformat().replace("+00:00", "Z")
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if end_dt > now_utc:
                end_dt = now_utc
                end_date = end_dt.isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4.4: Run the test, confirm it passes**

```bash
venv/bin/python3 -m pytest tests/test_report_generator_on_cache.py -v
```
Expected: ALL PASS.

- [ ] **Step 4.5: Write the clip-off (default) regression test**

Append to `tests/test_report_generator_on_cache.py`:

```python
def test_generate_from_api_clip_to_cache_default_off_does_not_clip(tmp_path):
    """clip_to_cache defaults False — request range is NOT mutated, hybrid
    fetch still runs as before."""
    from src.report.report_generator import ReportGenerator
    api = _make_mock_api()
    cache_start = datetime.now(timezone.utc) - timedelta(days=3)
    cache = _make_cache_reader(cover_state="partial", earliest=cache_start)
    gen = ReportGenerator(api=api, cache_reader=cache)
    start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    end = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    gen.generate_from_api(start_date=start, end_date=end)
    # Default behavior: API call is made for the leading gap
    api.fetch_traffic_for_report.assert_called_once()
```

- [ ] **Step 4.6: Run all on-cache tests**

```bash
venv/bin/python3 -m pytest tests/test_report_generator_on_cache.py -v
```
Expected: ALL PASS.

- [ ] **Step 4.7: Wire `clip_to_cache` through the GUI route**

In `src/gui/routes/reports.py:233`, before the `result = gen.generate_from_api(...)` call, add:

```python
                clip_to_cache = str(d.get('clip_to_cache', '')).lower() in ('true', '1', 'on')
```

Then change the `generate_from_api` call (line 233):

```python
                result = gen.generate_from_api(start_date=start_date, end_date=end_date,
                                               filters=report_filters,
                                               traffic_report_profile=traffic_report_profile,
                                               lang=lang, clip_to_cache=clip_to_cache)
```

- [ ] **Step 4.8: Add the i18n strings**

In `src/i18n_en.json`, add inside the top-level object (next to other `gui_report_*` keys):

```json
  "gui_clip_to_cache_label": "Clip to cache range (skip API gap)",
  "gui_clip_to_cache_hint": "When on, the report start/end is silently clipped to what the local cache actually has. Avoids extra PCE API calls when PCE retention is shorter than your request window.",
```

In `src/i18n_zh_TW.json`, add the same keys with translations:

```json
  "gui_clip_to_cache_label": "依快取範圍自動裁切（跳過 API 補洞）",
  "gui_clip_to_cache_hint": "啟用後，報表的起訖會自動裁切到本地快取實際擁有的範圍。當 PCE 留存比你查詢區間短時，可避免無效的 API 呼叫。",
```

- [ ] **Step 4.9: Add the checkbox to the report-generation modal**

In `src/templates/index.html`, immediately *before* the `<div id="m-gen-format-row">` block (around line 1878), insert:

```html
      <div id="m-gen-clip-row" style="margin-top:10px;">
        <label style="display:flex;align-items:center;gap:6px;font-size:0.85rem;color:var(--dim);cursor:pointer;">
          <input type="checkbox" id="m-gen-clip-to-cache" style="margin:0;">
          <span data-i18n="gui_clip_to_cache_label">Clip to cache range (skip API gap)</span>
        </label>
        <p style="font-size:11px;color:var(--dim);margin:4px 0 0 22px;" data-i18n="gui_clip_to_cache_hint">When on, the report start/end is silently clipped to what the local cache actually has.</p>
      </div>
```

- [ ] **Step 4.10: Wire the checkbox into the JS submit**

In `src/static/js/dashboard.js`, edit `_doGenerateTraffic` around line 982-988. Replace:

```javascript
      const r = await post('/api/reports/generate', {
        source: 'api', format: fmtEl2 ? fmtEl2.value : 'all',
        start_date: startDate, end_date: endDate,
        traffic_report_profile: profileEl ? profileEl.value : 'security_risk',
        lang: langEl ? langEl.value : 'en',
        ...(reportFilters ? { filters: reportFilters } : {}),
      });
```

with:

```javascript
      const clipEl = document.getElementById('m-gen-clip-to-cache');
      const clipToCache = !!(clipEl && clipEl.checked);
      const r = await post('/api/reports/generate', {
        source: 'api', format: fmtEl2 ? fmtEl2.value : 'all',
        start_date: startDate, end_date: endDate,
        traffic_report_profile: profileEl ? profileEl.value : 'security_risk',
        lang: langEl ? langEl.value : 'en',
        clip_to_cache: clipToCache,
        ...(reportFilters ? { filters: reportFilters } : {}),
      });
```

- [ ] **Step 4.11: Run the full report-generator + GUI test sweep**

```bash
venv/bin/python3 -m pytest tests/test_report_generator_on_cache.py tests/test_report_generator.py tests/test_gui_dashboard.py tests/test_gui_misc.py -v
```
Expected: ALL PASS.

- [ ] **Step 4.12: Commit**

```bash
git add src/report/report_generator.py src/gui/routes/reports.py src/templates/index.html src/static/js/dashboard.js src/i18n_en.json src/i18n_zh_TW.json tests/test_report_generator_on_cache.py
git commit -m "$(cat <<'EOF'
feat(report): opt-in clip_to_cache to skip API gap when cache is authoritative

Even with the cover_state fix, a 7-day request against a 5-day cache
still triggers a hybrid API call for the leading 2-day gap. When the
user accepts the cache as the source of truth (e.g. PCE retention is
shorter than the request window), they want that API call skipped.

Add clip_to_cache (default False) to ReportGenerator.generate_from_api;
when True, clip the start to MIN(last_detected) and the end to now.
Surface as an off-by-default checkbox above the format selector in
the report-generation modal, with EN + zh_TW i18n strings.
EOF
)"
```

---

## Final Verification

- [ ] **Step F.1: Full test suite**

```bash
venv/bin/python3 -m pytest tests/ -x --tb=short -q 2>&1 | tail -30
```
Expected: ALL PASS (no regressions across the whole suite).

- [ ] **Step F.2: Manual smoke test (optional, requires running app)**

If the user has the GUI running:
1. Open the report-generation modal.
2. Set start = (cache_start - 2 days), end = now.
3. Tick **Clip to cache range** → submit. Confirm `logs/illumio_ops.log` shows `clip_to_cache clipping start ... → ...` and the API was *not* called for the leading gap.
4. Untick → submit again. Confirm hybrid log line appears as before.
5. Within 30s of restarting the daemon, confirm `logs/illumio_ops.log` shows `Traffic ingest poll: fetched=...` (no longer 1-hour wait).

---

## Out of Scope (deferred)

- Daemon-restart debouncing in the Integrations UI (the underlying cause of the cascade) — Task 3 makes the system tolerant to it but doesn't remove the cascade. Track separately if it becomes a problem again.
- A "cache-only" mode that refuses to touch the API at all. `clip_to_cache` is the user-facing equivalent for reports; if Top10/dashboards need the same control, they belong in a follow-up plan.
- PCE-side retention configuration audit (was raised during diagnosis; lives outside the codebase).
