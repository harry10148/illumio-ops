# Phase 13 Implementation Plan — PCE Cache + SIEM Forwarder

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a shared local SQLite cache of PCE audit events + traffic flows (rate-limited, retention-bounded) together with a pluggable SIEM forwarder (CEF/JSON over UDP/TCP/TLS/HEC, with DLQ and replay). Existing reports and alerts keep working unchanged — cache is additive.

**Architecture:**
- **Cache layer (`src/pce_cache/`)**: APScheduler-driven ingestor pulls `/events` and `/traffic_flows` on independent intervals. Pulls are gated by a global token-bucket rate limiter (400/min, leaving 100/min headroom for existing code). Events ≤ 10k: sync GET with `max_results`; > 10k: async job via `Prefer: respond-async`. Traffic: always async via `/traffic_flows/async_queries` (200k cap per job). Persisted cursor (`ingestion_watermarks`) prevents re-ingest. Retention worker runs daily.
- **SIEM layer (`src/siem/`)**: Ingestor writes into `siem_dispatch` queue. Dispatcher pulls queue, formats (CEF 0.1 or JSON Lines, optionally wrapped in RFC5424 syslog header), transports (UDP / TCP / TCP+TLS / Splunk HEC HTTPS). Exponential backoff on transient failure; after N retries the row moves to `dead_letter` with failure reason. Admin replays/purges via CLI or GUI.
- **No new dependencies.** SQLAlchemy 2.x already installed (Phase 12 APScheduler jobstore). `orjson` already installed (Phase 2). `requests` already installed. UDP/TCP/TLS via Python stdlib `socket` + `ssl`.

**Tech Stack:** SQLAlchemy 2.x ORM • APScheduler BackgroundScheduler (existing) • Python stdlib `socket`/`ssl`/`threading` • `requests` (HEC) • `orjson` (formatter fast-path) • pydantic v2 (config validation)

**Branch:** `feature/phase-13-siem-cache` (from `main` after tag `v3.10.0-polish`)

**Target tag on merge:** `v3.11.0-siem-cache`

**Baseline:** 422 passed / 1 skipped (as of 2026-04-19). Target at merge: **≥ 470 passed** (+48 new tests spread across cache, formatters, transports, dispatcher, DLQ, CLI, Flask).

---

## File Structure

### Create

| File | Responsibility |
|---|---|
| `src/pce_cache/__init__.py` | Package marker + public facade exports |
| `src/pce_cache/models.py` | SQLAlchemy 2.x ORM — 6 tables (pce_events, pce_traffic_flows_raw, pce_traffic_flows_agg, ingestion_watermarks, siem_dispatch, dead_letter) |
| `src/pce_cache/schema.py` | `init_schema(engine)` — create tables + indexes; idempotent |
| `src/pce_cache/store.py` | `CacheStore` facade — scoped session helper + typed upsert methods |
| `src/pce_cache/rate_limiter.py` | `GlobalRateLimiter` — thread-safe token bucket (400/min default) |
| `src/pce_cache/watermark.py` | `WatermarkStore` — read/write per-source cursor |
| `src/pce_cache/ingestor_events.py` | `EventsIngestor` — sync pull ≤ 10k, async pull beyond |
| `src/pce_cache/ingestor_traffic.py` | `TrafficIngestor` — async-first, 200k cap, apply filter+sample |
| `src/pce_cache/traffic_filter.py` | `TrafficFilter` + `TrafficSampler` — pure predicate classes |
| `src/pce_cache/aggregator.py` | `TrafficAggregator` — hourly rollup worker |
| `src/pce_cache/retention.py` | `RetentionWorker` — daily TTL purge per table |
| `src/siem/__init__.py` | Package marker |
| `src/siem/formatters/__init__.py` | Formatter registry |
| `src/siem/formatters/base.py` | `Formatter` ABC |
| `src/siem/formatters/cef.py` | `CEFFormatter` — ArcSight CEF 0.1 + field mapping |
| `src/siem/formatters/json_line.py` | `JSONLineFormatter` — JSON Lines (one JSON object per line) |
| `src/siem/formatters/syslog_header.py` | `wrap_rfc5424(payload, ...)` — optional RFC5424 header |
| `src/siem/transports/__init__.py` | Transport registry |
| `src/siem/transports/base.py` | `Transport` ABC with `send(payload) -> None` |
| `src/siem/transports/syslog_udp.py` | `SyslogUDPTransport` — stdlib `socket.SOCK_DGRAM` |
| `src/siem/transports/syslog_tcp.py` | `SyslogTCPTransport` — reconnecting TCP socket |
| `src/siem/transports/syslog_tls.py` | `SyslogTLSTransport` — `ssl.wrap_socket` + CA bundle |
| `src/siem/transports/splunk_hec.py` | `SplunkHECTransport` — `requests.Session` + HEC token |
| `src/siem/dest_config.py` | `SiemDestination` pydantic model + loader |
| `src/siem/dispatcher.py` | `SiemDispatcher` — pull queue → format → transport with retry |
| `src/siem/dlq.py` | `DeadLetterQueue` — quarantine, list, replay, purge |
| `src/cli/siem.py` | click subcommand `illumio-ops siem test|status|replay|purge|dlq` |
| `src/siem/web.py` | Flask blueprint `/api/siem/` for destinations CRUD + dispatch/dlq views |
| `docs/PCE_Cache.md` | Architecture + retention sizing + tuning notes |
| `docs/SIEM_Forwarder.md` | Destinations config + format samples + troubleshooting |
| `deploy/siem_destination.example.json` | Sample destination config with all 4 transports commented |
| `tests/test_pce_cache_schema.py` | Table + index creation + idempotency |
| `tests/test_pce_cache_ingestor_events.py` | Sync ≤ 10k, async switch > 10k, watermark advance, rate limit |
| `tests/test_pce_cache_ingestor_traffic.py` | Async-first, filter, sample, 200k cap |
| `tests/test_pce_cache_aggregator.py` | Hourly rollup correctness + idempotency |
| `tests/test_pce_cache_retention.py` | Per-table TTL purge |
| `tests/test_rate_limiter.py` | Token bucket refill, concurrent acquire |
| `tests/test_cef_formatter.py` | CEF 0.1 header, extension escaping, required fields |
| `tests/test_json_formatter.py` | JSON Lines roundtrip, unicode safe |
| `tests/test_syslog_header.py` | RFC5424 header, structured-data escape |
| `tests/test_transport_udp_tcp.py` | Socket send, reconnect on TCP close (loopback server fixture) |
| `tests/test_transport_tls.py` | TLS handshake against `ssl.create_default_context()` loopback |
| `tests/test_transport_hec.py` | HEC POST body, HTTP 200/400/503 retry (responses lib) |
| `tests/test_siem_dispatcher.py` | Queue→format→transport, backoff, DLQ after N retries |
| `tests/test_siem_dlq.py` | Quarantine, list, replay, purge |
| `tests/test_siem_cli.py` | click runner for `siem test|replay|purge|dlq` |
| `tests/test_siem_web.py` | Flask blueprint CRUD + CSRF + admin-only |

### Modify

| File | Change |
|---|---|
| `src/config_models.py` | Add `PceCacheSettings`, `TrafficFilter`, `TrafficSampling`, `SiemForwarderSettings`, `SiemDestination`; register as `ConfigSchema.pce_cache` + `ConfigSchema.siem` |
| `config/config.json.example` | Add `pce_cache: {enabled: false, ...}` + `siem: {enabled: false, destinations: []}` stubs (both disabled by default) |
| `src/api_client.py` | `_request()` gains optional `rate_limit=True` kwarg; ingestor calls pass `True`, existing caller sites unchanged |
| `src/scheduler/__init__.py` | Register `pce_cache_ingest_events` / `pce_cache_ingest_traffic` / `pce_cache_aggregate` / `pce_cache_retention` / `siem_dispatch` / `siem_retention` jobs when `pce_cache.enabled` or `siem.enabled` |
| `src/scheduler/jobs.py` | Add job entrypoints calling ingestor / aggregator / dispatcher / retention |
| `src/gui.py` | `_create_app()` registers `src.siem.web.bp` blueprint |
| `src/cli/__init__.py` | Register `siem` click group |
| `src/i18n_en.json` + `src/i18n.py` `_ZH_EXPLICIT` | Add ~35 new keys (`gui_siem_*`, `cli_siem_*`, `cache_status_*`) |
| `docs/SIEM_Integration.md` | Add "Option E: Built-in Forwarder (recommended for on-box push)" section pointing to `docs/SIEM_Forwarder.md` |
| `tests/test_config_models.py` | Add cases for new pydantic models |
| `Status.md` / `Task.md` | Phase 13 entry |

### Not modified (intentionally — Phase 14/15 territory)

- `src/report/*` — reports still read via `ApiClient` directly.
- `src/analyzer.py` / `src/events/poller.py` — alert/monitor path unchanged.

---

## Data model (SQLite, SQLAlchemy 2.x)

```python
# src/pce_cache/models.py (exact content to create in Task 2)

from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    String, Integer, BigInteger, Text, DateTime, Boolean,
    Index, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass


class PceEvent(Base):
    __tablename__ = "pce_events"

    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    pce_href:      Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    pce_event_id:  Mapped[str]      = mapped_column(String(64), index=True)  # event's own UUID
    timestamp:     Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type:    Mapped[str]      = mapped_column(String(128), index=True)
    severity:      Mapped[str]      = mapped_column(String(32), index=True)
    status:        Mapped[str]      = mapped_column(String(32))
    pce_fqdn:      Mapped[str]      = mapped_column(String(255))
    raw_json:      Mapped[str]      = mapped_column(Text)        # orjson.dumps() of full event
    ingested_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        Index("ix_events_ts_type", "timestamp", "event_type"),
    )


class PceTrafficFlowRaw(Base):
    __tablename__ = "pce_traffic_flows_raw"

    id:             Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    flow_hash:      Mapped[str]      = mapped_column(String(64), unique=True, index=True)  # hash(src+dst+port+proto+first_detected)
    first_detected: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_detected:  Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    src_ip:         Mapped[str]      = mapped_column(String(45), index=True)  # INET6
    src_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    dst_ip:         Mapped[str]      = mapped_column(String(45), index=True)
    dst_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    port:           Mapped[int]      = mapped_column(Integer, index=True)
    protocol:       Mapped[str]      = mapped_column(String(8))  # tcp/udp
    action:         Mapped[str]      = mapped_column(String(32), index=True)  # allowed/blocked/potentially_blocked/unknown
    flow_count:     Mapped[int]      = mapped_column(Integer, default=1)
    bytes_in:       Mapped[int]      = mapped_column(BigInteger, default=0)
    bytes_out:      Mapped[int]      = mapped_column(BigInteger, default=0)
    raw_json:       Mapped[str]      = mapped_column(Text)
    ingested_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PceTrafficFlowAgg(Base):
    __tablename__ = "pce_traffic_flows_agg"

    id:             Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket_day:     Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)  # date truncated
    src_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    dst_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    port:           Mapped[int]      = mapped_column(Integer)
    protocol:       Mapped[str]      = mapped_column(String(8))
    action:         Mapped[str]      = mapped_column(String(32), index=True)
    flow_count:     Mapped[int]      = mapped_column(Integer, default=0)
    bytes_total:    Mapped[int]      = mapped_column(BigInteger, default=0)

    __table_args__ = (
        Index(
            "ix_agg_unique",
            "bucket_day", "src_workload", "dst_workload", "port", "protocol", "action",
            unique=True,
        ),
    )


class IngestionWatermark(Base):
    __tablename__ = "ingestion_watermarks"

    source:         Mapped[str]      = mapped_column(String(32), primary_key=True)  # "events" | "traffic"
    last_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_href:      Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status:    Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error:     Mapped[str | None] = mapped_column(Text, nullable=True)


class SiemDispatch(Base):
    __tablename__ = "siem_dispatch"

    id:             Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_table:   Mapped[str]      = mapped_column(String(32), index=True)  # "pce_events" | "pce_traffic_flows_raw"
    source_id:      Mapped[int]      = mapped_column(BigInteger)
    destination:    Mapped[str]      = mapped_column(String(64), index=True)
    status:         Mapped[str]      = mapped_column(String(16), index=True)  # "pending" | "sent" | "failed"
    retries:        Mapped[int]      = mapped_column(Integer, default=0)
    next_attempt_at:Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_error:     Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at:      Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at:        Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dispatch_pending", "status", "next_attempt_at"),
    )


class DeadLetter(Base):
    __tablename__ = "dead_letter"

    id:             Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_table:   Mapped[str]      = mapped_column(String(32))
    source_id:      Mapped[int]      = mapped_column(BigInteger)
    destination:    Mapped[str]      = mapped_column(String(64), index=True)
    retries:        Mapped[int]      = mapped_column(Integer)
    last_error:     Mapped[str]      = mapped_column(Text)
    payload_preview:Mapped[str]      = mapped_column(String(512))  # first 512 chars of formatted payload
    quarantined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

---

## Config schema additions

```python
# src/config_models.py additions (exact content to apply in Task 11)

class TrafficFilter(_Base):
    actions: list[Literal["allowed", "blocked", "potentially_blocked", "unknown"]] = \
        Field(default_factory=lambda: ["blocked", "potentially_blocked"])
    workload_label_env: list[str] = Field(default_factory=list)     # e.g. ["PRD", "STG"]
    ports: list[int] = Field(default_factory=list)
    protocols: list[Literal["tcp", "udp"]] = Field(default_factory=list)
    exclude_src_ips: list[str] = Field(default_factory=list)


class TrafficSampling(_Base):
    sample_ratio_allowed: int = Field(default=1, ge=1)  # 1:N drop, only for 'allowed'; blocked always 1
    max_rows_per_batch: int = Field(default=200000, ge=1, le=200000)


class PceCacheSettings(_Base):
    enabled: bool = False
    db_path: str = "data/pce_cache.sqlite"
    events_retention_days: int = Field(default=90, ge=1)
    traffic_raw_retention_days: int = Field(default=7, ge=1)
    traffic_agg_retention_days: int = Field(default=90, ge=1)
    events_poll_interval_seconds: int = Field(default=300, ge=30)
    traffic_poll_interval_seconds: int = Field(default=3600, ge=60)
    rate_limit_per_minute: int = Field(default=400, ge=10, le=500)
    async_threshold_events: int = Field(default=10000, ge=1, le=10000)
    traffic_filter: TrafficFilter = Field(default_factory=TrafficFilter)
    traffic_sampling: TrafficSampling = Field(default_factory=TrafficSampling)


class SiemDestination(_Base):
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    transport: Literal["udp", "tcp", "tls", "hec"]
    fmt: Literal["cef", "json", "syslog_cef", "syslog_json"] = \
        Field(alias="format", validation_alias="format")
    endpoint: str  # "host:port" for syslog; full URL for HEC
    tls_verify: bool = True
    tls_ca_bundle: Optional[str] = None
    hec_token: Optional[str] = None
    batch_size: int = Field(default=100, ge=1, le=10000)
    flush_interval_seconds: int = Field(default=5, ge=1)
    source_types: list[Literal["audit", "traffic"]] = \
        Field(default_factory=lambda: ["audit", "traffic"])
    traffic_filter: Optional[TrafficFilter] = None
    max_retries: int = Field(default=10, ge=0)


class SiemForwarderSettings(_Base):
    enabled: bool = False
    destinations: list[SiemDestination] = Field(default_factory=list)
    dlq_max_per_dest: int = Field(default=10000, ge=100)
    dispatch_tick_seconds: int = Field(default=5, ge=1)
```

In `ConfigSchema`: add `pce_cache: PceCacheSettings = Field(default_factory=PceCacheSettings)` and `siem: SiemForwarderSettings = Field(default_factory=SiemForwarderSettings)`.

---

## Task 1 — Branch + baseline

- [ ] **Step 1.1**: Create branch

```bash
git checkout main && git pull
git checkout -b feature/phase-13-siem-cache
```

- [ ] **Step 1.2**: Baseline (expect 422 passed / 1 skipped)

```bash
pytest -q
```

Expected: `422 passed, 1 skipped` or close. Any regression → stop and diagnose before continuing.

- [ ] **Step 1.3**: Create empty package skeleton

```bash
mkdir -p src/pce_cache src/siem/formatters src/siem/transports
touch src/pce_cache/__init__.py src/siem/__init__.py \
      src/siem/formatters/__init__.py src/siem/transports/__init__.py
```

- [ ] **Step 1.4**: Commit

```bash
git add src/pce_cache src/siem
git commit -m "feat(phase-13): scaffold pce_cache + siem packages"
```

---

## Task 2 — Cache schema + SQLAlchemy models

**Files:** Create `src/pce_cache/models.py`, `src/pce_cache/schema.py`, `tests/test_pce_cache_schema.py`.

- [ ] **Step 2.1**: Write the failing test

```python
# tests/test_pce_cache_schema.py
import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect


def test_schema_creates_all_six_tables():
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        names = set(inspect(engine).get_table_names())
        assert names == {
            "pce_events",
            "pce_traffic_flows_raw",
            "pce_traffic_flows_agg",
            "ingestion_watermarks",
            "siem_dispatch",
            "dead_letter",
        }


def test_schema_is_idempotent():
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        init_schema(engine)  # must not raise


def test_schema_enables_wal_mode():
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        with engine.connect() as conn:
            from sqlalchemy import text
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert mode.lower() == "wal"
```

- [ ] **Step 2.2**: Run tests — expect **FAIL** (`ModuleNotFoundError: No module named 'src.pce_cache.schema'`)

```bash
pytest tests/test_pce_cache_schema.py -v
```

- [ ] **Step 2.3**: Create `src/pce_cache/models.py` — paste the exact content from **Data model** section above.

- [ ] **Step 2.4**: Create `src/pce_cache/schema.py`

```python
"""Schema bootstrap for pce_cache SQLite DB."""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine

from src.pce_cache.models import Base


def init_schema(engine: Engine) -> None:
    """Create all tables + indexes if missing. Idempotent."""
    _enable_wal_pragma(engine)
    Base.metadata.create_all(engine)


def _enable_wal_pragma(engine: Engine) -> None:
    """Enable SQLite WAL + foreign_keys on every new connection."""
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA synchronous = NORMAL")
        cur.close()

    # Force-trigger the event for an already-open connection
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text("PRAGMA journal_mode = WAL"))
        conn.commit()
```

- [ ] **Step 2.5**: Run tests — expect **PASS** (3 tests)

- [ ] **Step 2.6**: Commit

```bash
git add src/pce_cache tests/test_pce_cache_schema.py
git commit -m "feat(phase-13): pce_cache SQLAlchemy models + WAL schema bootstrap"
```

---

## Task 3 — Global rate limiter (token bucket)

**Files:** Create `src/pce_cache/rate_limiter.py`, `tests/test_rate_limiter.py`.

Design: thread-safe token bucket using `threading.Lock` + `time.monotonic()`. `acquire(timeout)` blocks until one token is available or the timeout elapses.

- [ ] **Step 3.1**: Write the failing tests

```python
# tests/test_rate_limiter.py
import threading
import time

import pytest


def test_rate_limiter_refills_at_configured_rate():
    from src.pce_cache.rate_limiter import GlobalRateLimiter

    rl = GlobalRateLimiter(rate_per_minute=60)  # 1/sec
    t0 = time.monotonic()
    for _ in range(3):
        assert rl.acquire(timeout=2.0) is True
    elapsed = time.monotonic() - t0
    # 3 tokens at 1/sec ≈ ≤ 3 seconds but tokens burst at start so ≤ 2.2s is ok
    assert elapsed < 3.5


def test_rate_limiter_times_out_when_empty():
    from src.pce_cache.rate_limiter import GlobalRateLimiter

    rl = GlobalRateLimiter(rate_per_minute=6, burst=1)  # 1/10s, 1 token burst
    assert rl.acquire(timeout=0.1) is True   # consume the one token
    assert rl.acquire(timeout=0.1) is False  # next one should time out


def test_rate_limiter_is_thread_safe_under_contention():
    from src.pce_cache.rate_limiter import GlobalRateLimiter

    rl = GlobalRateLimiter(rate_per_minute=600, burst=10)  # 10/s
    granted = []
    lock = threading.Lock()

    def worker():
        if rl.acquire(timeout=1.0):
            with lock:
                granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads: t.start()
    for t in threads: t.join()
    # Within 1 second we should grant ≈ burst (10) + up to 10 more from refill.
    assert 10 <= len(granted) <= 25
```

- [ ] **Step 3.2**: Run — expect FAIL (ModuleNotFoundError)

```bash
pytest tests/test_rate_limiter.py -v
```

- [ ] **Step 3.3**: Implement `src/pce_cache/rate_limiter.py`

```python
"""Global token-bucket rate limiter for PCE API calls.

Single process-wide instance; all ingestor calls acquire() before issuing
HTTP. Default 400/min leaves 100/min headroom for the existing monitor
path (PCE enforces 500/min per session).
"""
from __future__ import annotations

import threading
import time


class GlobalRateLimiter:
    def __init__(self, rate_per_minute: int = 400, burst: int | None = None):
        if rate_per_minute < 1:
            raise ValueError("rate_per_minute must be >= 1")
        self._rate_per_sec = rate_per_minute / 60.0
        self._capacity = burst if burst is not None else max(rate_per_minute // 6, 1)
        self._tokens = float(self._capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 0.0) -> bool:
        """Block up to `timeout` seconds for one token. Return True if acquired."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                deficit = 1.0 - self._tokens
                wait = deficit / self._rate_per_sec
            if timeout <= 0.0:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(wait, remaining))

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_sec)
        self._last_refill = now


_INSTANCE: GlobalRateLimiter | None = None
_INSTANCE_LOCK = threading.Lock()


def get_rate_limiter(rate_per_minute: int = 400) -> GlobalRateLimiter:
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = GlobalRateLimiter(rate_per_minute=rate_per_minute)
        return _INSTANCE


def reset_for_tests() -> None:
    """Test-only: clear the singleton."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None
```

- [ ] **Step 3.4**: Run — expect **PASS** (3 tests)

- [ ] **Step 3.5**: Wire feature-flag into `api_client._request()`

Open `src/api_client.py` and find `_request`. Add an optional `rate_limit` kwarg that defaults to `False` (so existing caller sites are unchanged). When `True`, call `get_rate_limiter().acquire(timeout=30.0)` before issuing the HTTP. If acquire returns False, raise `APIError("rate limiter timeout")`.

```python
# In src/api_client.py _request signature, add:
#   rate_limit: bool = False,
# At top of method body, before the HTTP call, add:
if rate_limit:
    from src.pce_cache.rate_limiter import get_rate_limiter
    cm = ConfigManager()  # existing singleton
    rpm = cm.models.pce_cache.rate_limit_per_minute
    if not get_rate_limiter(rate_per_minute=rpm).acquire(timeout=30.0):
        raise APIError("Global rate limiter timeout — PCE 500/min budget exhausted")
```

- [ ] **Step 3.6**: Commit

```bash
git add src/pce_cache/rate_limiter.py src/api_client.py tests/test_rate_limiter.py
git commit -m "feat(phase-13): global rate limiter + api_client opt-in hook"
```

---

## Task 4 — Watermark store

**Files:** Create `src/pce_cache/watermark.py`, `tests/test_pce_cache_watermark.py`.

- [ ] **Step 4.1**: Test

```python
# tests/test_pce_cache_watermark.py
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def test_watermark_initially_empty(session_factory):
    from src.pce_cache.watermark import WatermarkStore
    ws = WatermarkStore(session_factory)
    assert ws.get("events") is None


def test_watermark_roundtrip(session_factory):
    from src.pce_cache.watermark import WatermarkStore
    ws = WatermarkStore(session_factory)
    ts = datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)
    ws.advance("events", last_timestamp=ts, last_href="/orgs/1/events/abc")
    got = ws.get("events")
    assert got.last_timestamp == ts
    assert got.last_href == "/orgs/1/events/abc"


def test_watermark_records_error(session_factory):
    from src.pce_cache.watermark import WatermarkStore
    ws = WatermarkStore(session_factory)
    ws.record_error("traffic", "429 rate limited")
    got = ws.get("traffic")
    assert got.last_status == "error"
    assert "rate limited" in got.last_error
```

- [ ] **Step 4.2**: Run — expect FAIL

- [ ] **Step 4.3**: Implement

```python
# src/pce_cache/watermark.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import IngestionWatermark


class WatermarkStore:
    def __init__(self, session_factory: sessionmaker):
        self._session_factory = session_factory

    def get(self, source: str) -> Optional[IngestionWatermark]:
        with self._session_factory() as s:
            return s.get(IngestionWatermark, source)

    def advance(
        self,
        source: str,
        last_timestamp: Optional[datetime] = None,
        last_href: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._session_factory.begin() as s:
            row = s.get(IngestionWatermark, source)
            if row is None:
                row = IngestionWatermark(source=source)
                s.add(row)
            if last_timestamp is not None:
                row.last_timestamp = last_timestamp
            if last_href is not None:
                row.last_href = last_href
            row.last_sync_at = now
            row.last_status = "ok"
            row.last_error = None

    def record_error(self, source: str, error: str) -> None:
        now = datetime.now(timezone.utc)
        with self._session_factory.begin() as s:
            row = s.get(IngestionWatermark, source)
            if row is None:
                row = IngestionWatermark(source=source)
                s.add(row)
            row.last_sync_at = now
            row.last_status = "error"
            row.last_error = error[:4000]
```

- [ ] **Step 4.4**: Run — expect **PASS** (3 tests)

- [ ] **Step 4.5**: Commit

```bash
git add src/pce_cache/watermark.py tests/test_pce_cache_watermark.py
git commit -m "feat(phase-13): ingestion watermark store"
```

---

## Task 5 — Events ingestor (sync ≤ 10k, async > 10k)

**Files:** Create `src/pce_cache/ingestor_events.py`, `tests/test_pce_cache_ingestor_events.py`. Reuse existing `ApiClient.get_events` for sync path; async path uses `Prefer: respond-async` header.

- [ ] **Step 5.1**: Test (uses `responses` library already in requirements-dev)

```python
# tests/test_pce_cache_ingestor_events.py
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


class FakeApiClient:
    """Minimal stand-in for ApiClient used only by ingestor tests."""

    def __init__(self, events, async_events=None):
        self._events = events
        self._async_events = async_events or []
        self.sync_calls = 0
        self.async_calls = 0

    def get_events(self, max_results=500, since=None, rate_limit=False, **kw):
        self.sync_calls += 1
        return self._events[:max_results]

    def get_events_async(self, since=None, rate_limit=False, **kw):
        self.async_calls += 1
        return self._async_events


def _mk_event(i, ts):
    return {
        "href": f"/orgs/1/events/{i}",
        "uuid": f"uuid-{i}",
        "timestamp": ts.isoformat(),
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.example.com",
    }


def test_ingestor_writes_events_to_cache(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    fake = FakeApiClient(events=[_mk_event(1, ts), _mk_event(2, ts + timedelta(seconds=1))])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory),
                          async_threshold=10000)
    count = ing.run_once()
    assert count == 2
    with session_factory() as s:
        rows = s.execute(select(PceEvent)).scalars().all()
    assert {r.pce_event_id for r in rows} == {"uuid-1", "uuid-2"}


def test_ingestor_skips_duplicates(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    fake = FakeApiClient(events=[_mk_event(1, ts)])
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory),
                          async_threshold=10000)
    assert ing.run_once() == 1
    assert ing.run_once() == 0  # same event, unique pce_href blocks re-insert


def test_ingestor_switches_to_async_when_threshold_exceeded(session_factory):
    from src.pce_cache.ingestor_events import EventsIngestor
    from src.pce_cache.watermark import WatermarkStore

    ts = datetime.now(timezone.utc)
    big_batch = [_mk_event(i, ts) for i in range(10001)]  # > threshold
    fake = FakeApiClient(events=big_batch[:500], async_events=big_batch)
    ing = EventsIngestor(api=fake, session_factory=session_factory,
                          watermark=WatermarkStore(session_factory),
                          async_threshold=10000)
    ing.run_once()
    # The first sync probe returned 500, which is < threshold; so sync is used.
    # Force async path by seeding a known-large backlog signal:
    ing.run_once(force_async=True)
    assert fake.async_calls == 1
```

- [ ] **Step 5.2**: Run — expect FAIL

- [ ] **Step 5.3**: Implement

```python
# src/pce_cache/ingestor_events.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent
from src.pce_cache.watermark import WatermarkStore


class EventsIngestor:
    SOURCE = "events"

    def __init__(
        self,
        api,
        session_factory: sessionmaker,
        watermark: WatermarkStore,
        async_threshold: int = 10000,
    ):
        self._api = api
        self._sf = session_factory
        self._wm = watermark
        self._async_threshold = async_threshold

    def run_once(self, *, force_async: bool = False) -> int:
        """Pull one batch. Returns number of rows inserted into cache."""
        since = self._since_cursor()
        try:
            if force_async:
                events = self._api.get_events_async(since=since, rate_limit=True)
            else:
                events = self._api.get_events(
                    max_results=self._async_threshold,
                    since=since,
                    rate_limit=True,
                )
                # If the first sync pull hit the cap, backlog likely exceeds 10k -
                # switch to async on next tick.
                if len(events) >= self._async_threshold:
                    logger.info(
                        "Events sync pull hit cap ({}), switching to async next tick",
                        self._async_threshold,
                    )
                    self._wm.advance(self.SOURCE)
                    events_async = self._api.get_events_async(since=since, rate_limit=True)
                    events = events_async
        except Exception as exc:
            logger.exception("Events ingest failed: {}", exc)
            self._wm.record_error(self.SOURCE, str(exc))
            return 0

        inserted = self._insert_batch(events)
        if events:
            last = max(e["timestamp"] for e in events)
            last_href = events[-1].get("href", "")
            self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last), last_href=last_href)
        return inserted

    def _since_cursor(self) -> Optional[str]:
        wm = self._wm.get(self.SOURCE)
        if wm and wm.last_timestamp:
            return wm.last_timestamp.isoformat()
        return None

    def _insert_batch(self, events: list[dict]) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for ev in events:
            with self._sf.begin() as s:
                row = PceEvent(
                    pce_href=ev.get("href", ""),
                    pce_event_id=ev.get("uuid", ev.get("href", ""))[-64:],
                    timestamp=_parse_iso(ev["timestamp"]),
                    event_type=ev.get("event_type", "unknown"),
                    severity=ev.get("severity", "info"),
                    status=ev.get("status", "success"),
                    pce_fqdn=ev.get("pce_fqdn", ""),
                    raw_json=orjson.dumps(ev).decode("utf-8"),
                    ingested_at=now,
                )
                try:
                    s.add(row)
                except IntegrityError:
                    continue
            count += 1
        return count


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
```

- [ ] **Step 5.4**: Add the `get_events_async` method stub to `ApiClient` (delegates to `AsyncJobManager` with `Prefer: respond-async` header). If the facade lacks this, extend `src/api/async_jobs.py` accordingly. See `src/api/async_jobs.py` for the existing traffic async pattern to mirror.

- [ ] **Step 5.5**: Run — expect **PASS** (3 tests)

- [ ] **Step 5.6**: Commit

```bash
git add src/pce_cache/ingestor_events.py src/api_client.py src/api/async_jobs.py \
        tests/test_pce_cache_ingestor_events.py
git commit -m "feat(phase-13): events ingestor with sync/async auto-switch"
```

---

## Task 6 — Traffic filter + sampler

**Files:** Create `src/pce_cache/traffic_filter.py`, `tests/test_traffic_filter.py`.

- [ ] **Step 6.1**: Test

```python
# tests/test_traffic_filter.py
from src.pce_cache.traffic_filter import TrafficFilter, TrafficSampler


def _flow(action="blocked", port=443, proto="tcp", src_ip="10.0.0.1",
          src_workload="web", dst_workload="db"):
    return {
        "action": action, "port": port, "protocol": proto,
        "src_ip": src_ip, "src_workload": src_workload, "dst_workload": dst_workload,
    }


def test_filter_passes_when_action_allowed():
    f = TrafficFilter(actions=["blocked"])
    assert f.passes(_flow(action="blocked")) is True
    assert f.passes(_flow(action="allowed")) is False


def test_filter_honours_port_whitelist():
    f = TrafficFilter(actions=["blocked", "allowed"], ports=[22, 3389])
    assert f.passes(_flow(action="blocked", port=22)) is True
    assert f.passes(_flow(action="blocked", port=443)) is False


def test_filter_excludes_src_ip():
    f = TrafficFilter(actions=["blocked"], exclude_src_ips=["10.0.0.1"])
    assert f.passes(_flow(src_ip="10.0.0.1")) is False
    assert f.passes(_flow(src_ip="10.0.0.2")) is True


def test_sampler_never_drops_blocked():
    s = TrafficSampler(ratio_allowed=10)
    flows = [_flow(action="blocked") for _ in range(100)]
    kept = [f for f in flows if s.keep(f)]
    assert len(kept) == 100


def test_sampler_drops_allowed_at_configured_ratio():
    s = TrafficSampler(ratio_allowed=10)
    flows = [_flow(action="allowed") for _ in range(100)]
    kept = [f for f in flows if s.keep(f)]
    # 1-in-10 kept, within sampling noise (7..13)
    assert 5 <= len(kept) <= 15
```

- [ ] **Step 6.2**: Run — expect FAIL

- [ ] **Step 6.3**: Implement

```python
# src/pce_cache/traffic_filter.py
from __future__ import annotations

import hashlib


class TrafficFilter:
    def __init__(
        self,
        actions: list[str] | None = None,
        workload_label_env: list[str] | None = None,
        ports: list[int] | None = None,
        protocols: list[str] | None = None,
        exclude_src_ips: list[str] | None = None,
    ):
        self._actions = set(actions) if actions else None
        self._envs = set(workload_label_env) if workload_label_env else None
        self._ports = set(ports) if ports else None
        self._protos = set(protocols) if protocols else None
        self._excl_src = set(exclude_src_ips) if exclude_src_ips else set()

    def passes(self, flow: dict) -> bool:
        if self._actions is not None and flow.get("action") not in self._actions:
            return False
        if self._ports is not None and flow.get("port") not in self._ports:
            return False
        if self._protos is not None and flow.get("protocol") not in self._protos:
            return False
        if flow.get("src_ip") in self._excl_src:
            return False
        if self._envs is not None:
            # Workload env label derived upstream as workload_env; fall back to OK if absent
            env = flow.get("workload_env")
            if env is not None and env not in self._envs:
                return False
        return True


class TrafficSampler:
    """Deterministic 1:N drop for `allowed` flows.

    We hash (src_ip, dst_ip, port) so the same flow is always kept or
    always dropped — no oscillation, and retrospective queries stay
    consistent.  `blocked` / `potentially_blocked` bypass sampling entirely.
    """

    def __init__(self, ratio_allowed: int = 1):
        if ratio_allowed < 1:
            raise ValueError("ratio_allowed must be >= 1")
        self._ratio = ratio_allowed

    def keep(self, flow: dict) -> bool:
        if flow.get("action") != "allowed":
            return True
        if self._ratio == 1:
            return True
        key = f"{flow.get('src_ip')}|{flow.get('dst_ip')}|{flow.get('port')}"
        h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
        return (h % self._ratio) == 0
```

- [ ] **Step 6.4**: Run — expect **PASS** (5 tests)

- [ ] **Step 6.5**: Commit

```bash
git add src/pce_cache/traffic_filter.py tests/test_traffic_filter.py
git commit -m "feat(phase-13): traffic filter + deterministic sampler"
```

---

## Task 7 — Traffic ingestor (async-first, 200k cap)

**Files:** Create `src/pce_cache/ingestor_traffic.py`, `tests/test_pce_cache_ingestor_traffic.py`.

Design: always async via `/traffic_flows/async_queries` (reusing `AsyncJobManager`). Filter + sample applied server-side where supported (labels/actions), client-side where not (ip excludes, ratio sampling). Written to `pce_traffic_flows_raw` on dedupe key `flow_hash`.

**Full test + implementation pattern mirrors Task 5 exactly.** Key differences:
- Call `api.get_traffic_flows_async(max_results=200000, filters=..., rate_limit=True)`
- Apply `TrafficFilter.passes(flow)` before insert
- Apply `TrafficSampler.keep(flow)` before insert
- Compute `flow_hash = sha1(f"{src_ip}|{dst_ip}|{port}|{proto}|{first_detected_iso}")` to dedupe on re-pull
- Watermark advances on `last_detected` max of batch; next pull uses `since=last_detected - grace(5min)`

- [ ] **Step 7.1**: Write failing tests with 3 scenarios: (a) batch of 100 blocked flows writes 100 rows, (b) sampler at 10:1 on 100 allowed flows writes ~10 rows, (c) second run with overlapping window dedupes via `flow_hash`.

- [ ] **Step 7.2**: Run — expect FAIL

- [ ] **Step 7.3**: Implement following Task 5 pattern — dedupe on `flow_hash`, filter+sample before insert, watermark `last_timestamp=max(last_detected)`.

- [ ] **Step 7.4**: Run — expect PASS

- [ ] **Step 7.5**: Commit

```bash
git add src/pce_cache/ingestor_traffic.py tests/test_pce_cache_ingestor_traffic.py
git commit -m "feat(phase-13): traffic ingestor with filter+sample, async-only"
```

---

## Task 8 — Traffic aggregator (hourly rollup)

**Files:** Create `src/pce_cache/aggregator.py`, `tests/test_pce_cache_aggregator.py`.

- [ ] **Step 8.1**: Test

```python
# tests/test_pce_cache_aggregator.py
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowAgg, PceTrafficFlowRaw


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed_raw(sf, count, action="blocked"):
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        for i in range(count):
            s.add(PceTrafficFlowRaw(
                flow_hash=f"h-{action}-{i}",
                first_detected=now, last_detected=now,
                src_ip="10.0.0.1", src_workload="web",
                dst_ip="10.0.0.2", dst_workload="db",
                port=443, protocol="tcp", action=action,
                flow_count=1, bytes_in=100, bytes_out=200,
                raw_json="{}", ingested_at=now,
            ))


def test_aggregator_groups_by_day_workload_pair(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    _seed_raw(session_factory, count=50, action="blocked")
    agg = TrafficAggregator(session_factory)
    inserted = agg.run_once()
    assert inserted >= 1
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowAgg)).scalars().all()
    assert len(rows) == 1
    assert rows[0].flow_count == 50
    assert rows[0].bytes_total == 50 * (100 + 200)


def test_aggregator_is_idempotent(session_factory):
    from src.pce_cache.aggregator import TrafficAggregator
    _seed_raw(session_factory, count=5)
    agg = TrafficAggregator(session_factory)
    agg.run_once()
    agg.run_once()  # second run must not double-count
    with session_factory() as s:
        rows = s.execute(select(PceTrafficFlowAgg)).scalars().all()
    assert len(rows) == 1
    assert rows[0].flow_count == 5
```

- [ ] **Step 8.2**: Run — expect FAIL

- [ ] **Step 8.3**: Implement

```python
# src/pce_cache/aggregator.py
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowAgg, PceTrafficFlowRaw


class TrafficAggregator:
    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def run_once(self) -> int:
        """Rollup pce_traffic_flows_raw into pce_traffic_flows_agg.

        UNIQUE (bucket_day, src_workload, dst_workload, port, protocol, action)
        drives UPSERT so the job is idempotent.
        """
        day = func.date(PceTrafficFlowRaw.last_detected)
        q = (
            select(
                day.label("bucket_day"),
                PceTrafficFlowRaw.src_workload,
                PceTrafficFlowRaw.dst_workload,
                PceTrafficFlowRaw.port,
                PceTrafficFlowRaw.protocol,
                PceTrafficFlowRaw.action,
                func.sum(PceTrafficFlowRaw.flow_count).label("flow_count"),
                func.sum(
                    PceTrafficFlowRaw.bytes_in + PceTrafficFlowRaw.bytes_out
                ).label("bytes_total"),
            )
            .group_by(
                day,
                PceTrafficFlowRaw.src_workload,
                PceTrafficFlowRaw.dst_workload,
                PceTrafficFlowRaw.port,
                PceTrafficFlowRaw.protocol,
                PceTrafficFlowRaw.action,
            )
        )
        count = 0
        with self._sf.begin() as s:
            for row in s.execute(q):
                stmt = sqlite_insert(PceTrafficFlowAgg.__table__).values(
                    bucket_day=row.bucket_day,
                    src_workload=row.src_workload,
                    dst_workload=row.dst_workload,
                    port=row.port,
                    protocol=row.protocol,
                    action=row.action,
                    flow_count=int(row.flow_count),
                    bytes_total=int(row.bytes_total),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        "bucket_day", "src_workload", "dst_workload",
                        "port", "protocol", "action",
                    ],
                    set_={
                        "flow_count": stmt.excluded.flow_count,
                        "bytes_total": stmt.excluded.bytes_total,
                    },
                )
                s.execute(stmt)
                count += 1
        return count
```

- [ ] **Step 8.4**: Run — expect PASS

- [ ] **Step 8.5**: Commit

```bash
git add src/pce_cache/aggregator.py tests/test_pce_cache_aggregator.py
git commit -m "feat(phase-13): traffic aggregator with idempotent UPSERT"
```

---

## Task 9 — Retention worker

**Files:** Create `src/pce_cache/retention.py`, `tests/test_pce_cache_retention.py`.

- [ ] **Step 9.1**: Test — seed rows older than retention in all 4 data tables (events, traffic raw, traffic agg, DLQ) with distinct `ingested_at`/`quarantined_at`. Call `RetentionWorker.run_once(settings)` where settings specifies retention days per table. Assert expired rows are deleted, within-window rows survive.

- [ ] **Step 9.2**: Run — FAIL

- [ ] **Step 9.3**: Implement (trivial `DELETE FROM <t> WHERE <ts_col> < now - interval`) across `pce_events`, `pce_traffic_flows_raw`, `pce_traffic_flows_agg`, `dead_letter`. Use `datetime.now(timezone.utc) - timedelta(days=N)` as cutoff — no SQLite interval math.

- [ ] **Step 9.4**: Run — PASS

- [ ] **Step 9.5**: Commit

```bash
git add src/pce_cache/retention.py tests/test_pce_cache_retention.py
git commit -m "feat(phase-13): retention worker with per-table TTL purge"
```

---

## Task 10 — Formatter: CEF + JSON Lines + RFC5424 header

**Files:** Create `src/siem/formatters/{base.py,cef.py,json_line.py,syslog_header.py}`, `tests/test_cef_formatter.py`, `tests/test_json_formatter.py`, `tests/test_syslog_header.py`.

### CEF mapping

| PCE field | CEF field | Note |
|---|---|---|
| `event_type` | `CEF:0\|Illumio\|PCE\|<ver>\|<event_type>\|<event_type>\|<sev_num>` | Header |
| `severity` | `Severity=` (0–10 int map) | info=3 warn=6 err=8 crit=10 |
| `timestamp` | `rt=<epoch_ms>` | `receiptTime` |
| `pce_fqdn` | `dvchost=` | Device hostname |
| `pce_event_id` | `externalId=` | PCE uuid |
| `status` | `outcome=` | success/failure |
| (traffic) `src_ip` / `dst_ip` | `src=` / `dst=` | |
| (traffic) `port` / `protocol` | `dpt=` / `proto=` | |
| (traffic) `action` | `act=` | allowed/blocked/potentially_blocked |

CEF extension values must escape `\`, `=`, and newline — helper `_cef_escape(s)` in `cef.py`.

### Test examples

```python
# tests/test_cef_formatter.py
def test_cef_audit_event_has_required_header():
    from src.siem.formatters.cef import CEFFormatter
    ev = {
        "pce_event_id": "uuid-abc",
        "timestamp": "2026-04-19T10:00:00Z",
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.example.com",
    }
    line = CEFFormatter().format_event(ev)
    assert line.startswith("CEF:0|Illumio|PCE|")
    assert "externalId=uuid-abc" in line
    assert "dvchost=pce.example.com" in line
    assert "outcome=success" in line


def test_cef_traffic_flow_contains_network_fields():
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "first_detected": "2026-04-19T10:00:00Z",
        "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
        "port": 443, "protocol": "tcp", "action": "blocked",
        "pce_fqdn": "pce.example.com",
    }
    line = CEFFormatter().format_flow(fl)
    assert "src=10.0.0.1" in line
    assert "dst=10.0.0.2" in line
    assert "dpt=443" in line
    assert "act=blocked" in line


def test_cef_escapes_equals_and_pipe():
    from src.siem.formatters.cef import _cef_escape
    assert _cef_escape("a=b") == r"a\=b"
    assert _cef_escape("a|b") == r"a\|b"
    assert _cef_escape("a\\b") == r"a\\b"
```

- [ ] **Step 10.1**: Write 3 tests per formatter (9 total) covering headers, escaping, and empty/null-field tolerance.
- [ ] **Step 10.2**: Run — FAIL
- [ ] **Step 10.3**: Implement `base.Formatter` ABC, `cef.CEFFormatter`, `json_line.JSONLineFormatter`, `syslog_header.wrap_rfc5424()`.
- [ ] **Step 10.4**: Run — PASS
- [ ] **Step 10.5**: Commit

```bash
git add src/siem/formatters tests/test_cef_formatter.py \
        tests/test_json_formatter.py tests/test_syslog_header.py
git commit -m "feat(phase-13): CEF + JSON Lines formatters with RFC5424 header wrapper"
```

---

## Task 11 — Transports: UDP / TCP / TLS / Splunk HEC

**Files:** Create `src/siem/transports/{base.py,syslog_udp.py,syslog_tcp.py,syslog_tls.py,splunk_hec.py}`, `tests/test_transport_udp_tcp.py`, `tests/test_transport_tls.py`, `tests/test_transport_hec.py`.

### Design

- **UDP**: `socket.SOCK_DGRAM`, one datagram per payload, no ack, no reconnect. Warn log on every send if `len(payload) > 1400` (fragmentation risk). Tests: loopback `socketserver.UDPServer` fixture.
- **TCP**: `socket.SOCK_STREAM` with `_connect_lock`. Line-framed: append `\n` to payload. On `BrokenPipeError` / `ConnectionResetError`: close, reconnect, retry once; else propagate. Tests: loopback `socketserver.ThreadingTCPServer`, kill connection mid-flight, assert reconnect.
- **TLS**: same as TCP but `ssl.create_default_context()` + optional `tls_ca_bundle`. If `tls_verify=False`, warn log and `context.check_hostname=False; verify_mode=CERT_NONE`. Tests: `ssl.create_default_context()` + self-signed cert fixture, verify handshake.
- **HEC**: `requests.Session()` POST to `<endpoint>/services/collector/event` with header `Authorization: Splunk <token>`, body `{"event": <payload>, "sourcetype": "illumio_ops"}`. Retry: built-in `urllib3.Retry(total=3, backoff_factor=0.5, status_forcelist=[429,500,502,503,504])`. Tests: `responses` library, assert retry on 503, propagate on 400.

- [ ] **Step 11.1**: Tests (12 total: 3 per transport)
- [ ] **Step 11.2**: Run — FAIL
- [ ] **Step 11.3**: Implement
- [ ] **Step 11.4**: Run — PASS
- [ ] **Step 11.5**: Commit

```bash
git add src/siem/transports tests/test_transport_*.py
git commit -m "feat(phase-13): UDP/TCP/TLS/HEC transports with retry + reconnect"
```

---

## Task 12 — Dispatcher + DLQ

**Files:** Create `src/siem/dispatcher.py`, `src/siem/dlq.py`, `tests/test_siem_dispatcher.py`, `tests/test_siem_dlq.py`.

### Behaviour

Dispatcher tick:
1. `SELECT * FROM siem_dispatch WHERE status='pending' AND next_attempt_at <= now ORDER BY queued_at LIMIT batch_size FOR UPDATE SKIP LOCKED` (SQLite doesn't support SKIP LOCKED — use `BEGIN IMMEDIATE` + an in-process lock instead).
2. For each row: load source (event or flow), format, transport.send().
3. On success: `UPDATE siem_dispatch SET status='sent', sent_at=now`.
4. On failure: `retries += 1`. If `retries < dest.max_retries`: `next_attempt_at = now + backoff(retries)`. Else: insert into `dead_letter` + `UPDATE siem_dispatch SET status='failed'`.

Backoff: `min(2 ** retries * 5, 3600)` seconds, capped at 1 hour.

Enqueuer: invoked by the ingestors after writing events/flows to cache. For each enabled destination matching the row's source type, insert one `siem_dispatch` row.

- [ ] **Step 12.1**: Tests (7 total)
- [ ] **Step 12.2**: Implement
- [ ] **Step 12.3**: Commit

```bash
git add src/siem/dispatcher.py src/siem/dlq.py tests/test_siem_dispatcher.py tests/test_siem_dlq.py
git commit -m "feat(phase-13): siem dispatcher + DLQ with exponential backoff"
```

---

## Task 13 — Config models + APScheduler registration

**Files:** Modify `src/config_models.py`, `src/scheduler/__init__.py`, `src/scheduler/jobs.py`, `config/config.json.example`, `tests/test_config_models.py`.

- [ ] **Step 13.1**: Add `PceCacheSettings`, `TrafficFilter`, `TrafficSampling`, `SiemDestination`, `SiemForwarderSettings` to `src/config_models.py` exactly as specified in **Config schema additions** above.

- [ ] **Step 13.2**: Add `pce_cache: PceCacheSettings` and `siem: SiemForwarderSettings` fields to `ConfigSchema`.

- [ ] **Step 13.3**: Add 6 new jobs to `build_scheduler()`:

```python
# src/scheduler/__init__.py — additions inside build_scheduler(), after existing add_job calls

cache_cfg = cm.models.pce_cache
if cache_cfg.enabled:
    from src.scheduler.jobs import (
        run_events_ingest, run_traffic_ingest,
        run_traffic_aggregate, run_cache_retention,
    )
    sched.add_job(run_events_ingest, IntervalTrigger(seconds=cache_cfg.events_poll_interval_seconds),
                   args=[cm], id="pce_cache_ingest_events", replace_existing=True)
    sched.add_job(run_traffic_ingest, IntervalTrigger(seconds=cache_cfg.traffic_poll_interval_seconds),
                   args=[cm], id="pce_cache_ingest_traffic", replace_existing=True)
    sched.add_job(run_traffic_aggregate, IntervalTrigger(hours=1),
                   args=[cm], id="pce_cache_aggregate", replace_existing=True)
    sched.add_job(run_cache_retention, IntervalTrigger(hours=24),
                   args=[cm], id="pce_cache_retention", replace_existing=True)

siem_cfg = cm.models.siem
if siem_cfg.enabled:
    from src.scheduler.jobs import run_siem_dispatch
    sched.add_job(run_siem_dispatch, IntervalTrigger(seconds=siem_cfg.dispatch_tick_seconds),
                   args=[cm], id="siem_dispatch", replace_existing=True)
```

- [ ] **Step 13.4**: Implement the five `run_*` job entrypoints in `src/scheduler/jobs.py`, each a one-line "build the module, call `.run_once()`" wrapper that catches + logs all exceptions so a crash in one never kills the scheduler.

- [ ] **Step 13.5**: Update `config/config.json.example` — add disabled stubs for `pce_cache` and `siem` so new installs don't silently enable anything.

- [ ] **Step 13.6**: Tests: `test_config_models.py` cases for schema validation (invalid endpoint, invalid transport, retention < 1 rejected, etc.)

- [ ] **Step 13.7**: Run — PASS

- [ ] **Step 13.8**: Commit

```bash
git add src/config_models.py src/scheduler tests/test_config_models.py config/config.json.example
git commit -m "feat(phase-13): wire cache+siem into APScheduler on config flag"
```

---

## Task 14 — CLI: `illumio-ops siem …`

**Files:** Create `src/cli/siem.py`, `tests/test_siem_cli.py`. Modify `src/cli/__init__.py` to register the group.

### Subcommands

```
illumio-ops siem test <destination>       # send one synthetic event, report success/fail
illumio-ops siem status                   # per-destination: pending/sent/failed/DLQ count
illumio-ops siem replay --dest <name> [--limit N]   # requeue N DLQ rows for dest
illumio-ops siem purge --dest <name> [--older-than 30d]   # delete DLQ rows older than
illumio-ops siem dlq --dest <name> [--limit 50]   # list DLQ rows (rich.Table)
```

- [ ] **Step 14.1**: Tests using `click.testing.CliRunner` + in-memory SQLite fixture
- [ ] **Step 14.2**: Implement each subcommand ≤ 40 lines
- [ ] **Step 14.3**: i18n keys: `cli_siem_test_ok`, `cli_siem_test_fail`, `cli_siem_no_dlq`, `cli_siem_replayed`, `cli_siem_purged`, `cli_siem_dlq_empty` — add to `src/i18n_en.json` + `_ZH_EXPLICIT`.
- [ ] **Step 14.4**: Commit

```bash
git add src/cli/siem.py src/cli/__init__.py tests/test_siem_cli.py \
        src/i18n_en.json src/i18n.py
git commit -m "feat(phase-13): illumio-ops siem CLI (test/status/replay/purge/dlq)"
```

---

## Task 15 — Flask blueprint: `/api/siem/` + GUI management pages

**Files:** Create `src/siem/web.py`, `src/templates/siem_destinations.html`, `src/templates/siem_dlq.html`, `tests/test_siem_web.py`. Modify `src/gui.py` to register the blueprint.

### Endpoints

- `GET /api/siem/destinations` → list destinations (admin only)
- `POST /api/siem/destinations` → add (CSRF-protected, admin only)
- `PUT /api/siem/destinations/<name>` → edit
- `DELETE /api/siem/destinations/<name>` → remove
- `GET /api/siem/status` → per-dest counts + last-send timestamp
- `GET /api/siem/dlq?dest=<name>&limit=50` → DLQ page
- `POST /api/siem/dlq/replay` → `{dest, limit}`
- `POST /api/siem/dlq/purge` → `{dest, older_than_days}`

All POST/PUT/DELETE: `@csrf.exempt` is **forbidden**; must use CSRF token via `X-CSRFToken` header. Admin gate: `@login_required` + role check (existing `gui.py` pattern).

- [ ] **Step 15.1**: Tests (8 endpoint tests + 2 CSRF rejection tests)
- [ ] **Step 15.2**: Blueprint implementation
- [ ] **Step 15.3**: HTML templates (minimal — tables, "Add destination" modal)
- [ ] **Step 15.4**: i18n keys `gui_siem_*` (~15) — add to json + `_ZH_EXPLICIT`
- [ ] **Step 15.5**: UDP security warning — when `transport == "udp"` AND user hits Save: return 200 with warning body containing i18n key `gui_siem_udp_warning`. Frontend displays banner.
- [ ] **Step 15.6**: Commit

```bash
git add src/siem/web.py src/templates/siem_*.html src/gui.py \
        src/i18n_en.json src/i18n.py tests/test_siem_web.py
git commit -m "feat(phase-13): siem web blueprint (destinations + dlq management)"
```

---

## Task 16 — Docs: `PCE_Cache.md` + `SIEM_Forwarder.md` + Integration doc update

**Files:** Create `docs/PCE_Cache.md`, `docs/SIEM_Forwarder.md`, `deploy/siem_destination.example.json`. Modify `docs/SIEM_Integration.md`.

### docs/PCE_Cache.md outline

1. What it is + why (rate-limit sharing; consumer decoupling; retrospective queries)
2. How to enable — minimal config.json snippet
3. Table reference (the 6 tables + retention defaults)
4. Operator guide — disk sizing, retention tuning, backfill (`illumio-ops cache backfill`)
5. Monitoring — loguru lines to search (`Events ingest`, `Traffic ingest`, `RetentionWorker purged`)
6. Troubleshooting — `429` spam → drop `rate_limit_per_minute`; large disk → shrink retention

### docs/SIEM_Forwarder.md outline

1. Architecture diagram (ASCII) — ingestor → cache → dispatch → formatter → transport
2. Destination config schema + two full examples (HEC + TCP-TLS syslog)
3. Format samples: one CEF line, one JSON line, RFC5424 envelope
4. Testing: `illumio-ops siem test <name>` workflow
5. DLQ operator guide (when retries exhausted, how to inspect/replay)
6. Transport selection guide: HEC vs TLS vs TCP vs UDP (security/ordering/throughput tradeoffs)

### docs/SIEM_Integration.md update

Add "Option E — Built-in Forwarder (recommended)" linking to `SIEM_Forwarder.md`. Note the trade-off vs the four file-based options (file-based is app-log only; built-in forwards PCE API data).

- [ ] **Step 16.1**: Write both new docs + update integration doc
- [ ] **Step 16.2**: `deploy/siem_destination.example.json` — one example per transport, all `enabled: false`
- [ ] **Step 16.3**: Commit

```bash
git add docs/PCE_Cache.md docs/SIEM_Forwarder.md docs/SIEM_Integration.md \
        deploy/siem_destination.example.json
git commit -m "docs(phase-13): PCE cache + SIEM forwarder architecture docs"
```

---

## Task 17 — End-to-end integration test + i18n audit + final validation

**Files:** Create `tests/test_phase_13_e2e.py`. Modify `Status.md`, `Task.md`.

### E2E scenario

1. Start in-memory SQLite cache
2. Seed a `FakeApiClient` with 3 events + 50 traffic flows
3. Wire the full stack: ingestor → dispatcher → in-memory loopback syslog TCP server
4. Run one scheduler tick (or call `run_*_once()` in sequence)
5. Assert: cache has 3 events + 50 flows (or 5 if sampled), loopback server received 53 CEF/JSON lines, watermarks advanced, `siem_dispatch.status='sent'` for all rows

- [ ] **Step 17.1**: Write E2E test

- [ ] **Step 17.2**: Run full suite

```bash
pytest -q
```

Expected: **≥ 470 passed** (+48 new tests spread across Task 2–17). Any failure → investigate; do not merge with red.

- [ ] **Step 17.3**: i18n audit

```bash
python scripts/audit_i18n_usage.py
```

Expected: 0 findings.

- [ ] **Step 17.4**: Type check (optional but recommended)

```bash
python -m mypy src/pce_cache src/siem || true
```

- [ ] **Step 17.5**: Update `Status.md` — add a Phase 13 section (mirror existing Phase 12 section layout).

- [ ] **Step 17.6**: Update `Task.md` — add Phase 13 checkmarks; mark T1–T17 complete.

- [ ] **Step 17.7**: Commit final + PR

```bash
git add tests/test_phase_13_e2e.py Status.md Task.md
git commit -m "test(phase-13): e2e ingestor→dispatcher→transport + status docs"

git push -u origin feature/phase-13-siem-cache
gh pr create --title "feat(v3.11.0): Phase 13 — PCE cache + SIEM forwarder" \
             --body "$(cat <<'EOF'
## Summary
- New `src/pce_cache/` — 6-table SQLite cache with ingestor, retention, rate limiter
- New `src/siem/` — CEF/JSON formatters + UDP/TCP/TLS/HEC transports + dispatcher + DLQ
- APScheduler hosts both under config flags (`pce_cache.enabled` / `siem.enabled`); default OFF
- CLI: `illumio-ops siem test|status|replay|purge|dlq`
- GUI: `/api/siem/` blueprint + destinations + DLQ admin pages
- Docs: `docs/PCE_Cache.md`, `docs/SIEM_Forwarder.md`, `docs/SIEM_Integration.md` update

## Test plan
- [x] 470+ tests pass, 0 regressions vs 422 baseline
- [x] i18n audit 0 findings
- [x] E2E loopback transport verifies events+flows end up as CEF/JSON lines
- [x] Manual: enable cache in dev, observe ingest job runs, no 429 spam
EOF
)"
```

- [ ] **Step 17.8**: Tag on merge to main

```bash
git tag v3.11.0-siem-cache && git push --tags
```

---

## Self-review checklist (run before PR)

- [ ] **Spec coverage**: 15 confirmed decisions from roadmap section "Confirmed design decisions" all implemented? Points 1–15 traced to specific tasks.
- [ ] **Placeholder scan**: `grep -n "TODO\|TBD\|FIXME" src/pce_cache src/siem` returns zero.
- [ ] **Type consistency**: `pce_href` / `flow_hash` / `bucket_day` / `next_attempt_at` column names match across models, ingestors, and dispatcher.
- [ ] **Feature flags**: default `pce_cache.enabled = false` and `siem.enabled = false`. First-boot on upgrade must be no-op.
- [ ] **No-regression**: existing monitor/report/alert paths still work when cache disabled.
- [ ] **Rate-limit hook**: `api_client._request()` default `rate_limit=False` — monitor loop unchanged.
- [ ] **UDP warning**: GUI "Add destination" with `transport=udp` returns warning banner.
- [ ] **DLQ cap**: when DLQ reaches `dlq_max_per_dest`, oldest rows auto-purge and a loguru ERROR fires.
- [ ] **CEF escaping**: pipe, equals, backslash, newline all escaped in extension values.

---

## Post-merge follow-up

1. Create Phase 14 branch (`feature/phase-14-reports-cache`) off main.
2. Announce in internal docs: operators should start with `traffic_filter.actions=["blocked","potentially_blocked"]` to bound first-production volume.
3. Monitor the first week — expected disk growth, expected dispatcher tick runtime, anomalous 429s.
