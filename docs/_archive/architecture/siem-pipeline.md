---
title: SIEM Pipeline Architecture
audience: [developer, api, security]
last_verified: 2026-05-15
verified_against:
  - src/siem/
  - src/siem/formatters/
  - src/siem/transports/
  - commit 21b7740
related_docs:
  - overview.md
  - ../user-guide/siem-integration.md
  - ../reference/rest-api.md
  - ../user-guide/alerts-and-quarantine.md
---

> 🌐 **[English](siem-pipeline.md)** | **[繁體中文](siem-pipeline_zh.md)**
> 📍 [INDEX](../INDEX.md) › Architecture › SIEM Pipeline
> 🔍 Last verified **2026-05-15** against commit `21b7740` — see frontmatter for sources

# SIEM Pipeline Architecture

This document describes the internal architecture of the SIEM forwarding
pipeline: how events enter the pipeline, how they are normalized and
formatted, how they are delivered to external SIEM systems, and how the
system handles failures.

---

## Event sources

Two source tables feed the SIEM pipeline. The dispatcher (`src/siem/dispatcher.py`)
reads from both tables using the same `SiemDispatch` queue mechanism.

### PCE audit events — `pce_events`

PCE audit events are ingested from the Illumio PCE API into the
`pce_events` SQLite table (defined in `src/pce_cache/models.py`).
Each row represents one PCE audit log entry: policy changes, workload
updates, user login events, API method calls, and so on.

- **Model class:** `PceEvent`
- **Source table name (used in `SiemDispatch.source_table`):** `pce_events`
- **Raw payload column:** `raw_json` — the original PCE API JSON blob

Ingestors call `siem.dispatcher.enqueue()` in the same transaction that
writes the cache row, so every ingested audit event is immediately queued
for all configured SIEM destinations.

### PCE traffic flows — `pce_traffic_flows_raw`

Network traffic flow records are ingested from the PCE traffic analysis
API into the `pce_traffic_flows_raw` table.

- **Model class:** `PceTrafficFlowRaw`
- **Source table name:** `pce_traffic_flows_raw`
- **Raw payload column:** `raw_json`

### Enqueue mechanism

```python
# src/siem/dispatcher.py
def enqueue(session_factory, source_table, source_id, destinations):
    """Create one siem_dispatch row per destination for a newly-ingested record."""
```

One `SiemDispatch` row is created per destination per source record.
A safety-net backfill function `enqueue_new_records()` catches any rows
that ingestors failed to enqueue inline.

---

## Event normalization

The pipeline does not define a rigid internal event model — formatters
receive the raw `dict` deserialized from `raw_json` and normalize on the
way out. The PCE API returns two distinct shapes:

| Shape | Description |
|---|---|
| **Nested PCE API format** | `src`, `dst`, `service` are nested dicts; `created_by` is a nested actor object |
| **Flat official log format** | Fields like `src_ip`, `dst_ip`, `dst_port` appear at the top level |

All formatters handle both shapes. The helper functions used for this
normalization live in `src/siem/formatters/cef.py` and are re-exported
for use by other formatters:

| Helper | Purpose |
|---|---|
| `_extract_actor(created_by)` | Extracts actor string from nested `created_by` dict |
| `_format_labels(labels)` | Formats Illumio label list into a compact string |
| `_format_resource_changes(rc)` | Summarizes resource change list into a human-readable string |
| `_proto_to_str(proto)` | Maps protocol number (6, 17, 1) to string (tcp, udp, icmp) |
| `_ts_to_epoch_ms(ts_str)` | Converts ISO8601 timestamp to epoch milliseconds |

These are imported by `NormalizedJSONFormatter` to avoid duplication.

---

## Formatters

All formatters live in `src/siem/formatters/`. The abstract base class is
`src/siem/formatters/base.py`:

```python
class Formatter(ABC):
    @abstractmethod
    def format_event(self, event: dict) -> str: ...

    @abstractmethod
    def format_flow(self, flow: dict) -> str: ...
```

Both methods receive a raw dict and return a UTF-8 string ready to hand
to a transport's `send()`.

The format key (configured per destination as `format:`) selects the
formatter at startup:

| Format key | Formatter class | Module |
|---|---|---|
| `cef` | `CEFFormatter` | `src/siem/formatters/cef.py` |
| `syslog_cef` | `SyslogWrappedFormatter(CEFFormatter())` | `src/siem/formatters/syslog_wrapped.py` |
| `syslog_json` | `SyslogWrappedFormatter(NormalizedJSONFormatter())` | `src/siem/formatters/syslog_wrapped.py` |
| `json` | `NormalizedJSONFormatter` | `src/siem/formatters/normalized_json.py` |

The internal `JSONLineFormatter` (`src/siem/formatters/json_line.py`) is
a raw pass-through of the original PCE JSON; it is **not** exposed as a
user-facing format key and is not used by the dispatcher.

### CEF

**Module:** `src/siem/formatters/cef.py`
**Tests:** `tests/test_cef_formatter.py`

Implements the ArcSight Common Event Format (CEF) version 0.

**Events (`format_event`):**

Input: PCE audit event dict. Output: CEF string.

```
CEF:0|Illumio|PCE|3.11|<event_type>|<event_type>|<severity>|rt=<epoch_ms> dvc=<pce_fqdn> ... suser=<actor>
```

Severity mapping from PCE severity strings to CEF integers:

| PCE severity | CEF integer |
|---|---|
| `info` | 3 |
| `warning` / `warn` | 6 |
| `error` / `err` | 8 |
| `critical` / `crit` | 10 |

Extension fields populated for events: `rt`, `dvc`, `deviceExternalId`,
`suser`, `src` (src_ip from action), `requestMethod`, `request`,
`cn1`/`cn1Label` (HTTP status code), `msg` (resource changes summary).

**Flows (`format_flow`):**

Input: PCE traffic flow dict (nested or flat). Output: CEF string.

```
CEF:0|Illumio|PCE|3.11|traffic.flow|traffic.flow|3|rt=<epoch_ms> src=<ip> dst=<ip> dpt=<port> proto=<proto> pd=<decision> ...
```

CEF standard fields carry the network 5-tuple (`src`, `dst`, `dpt`,
`proto`). Illumio-specific fields use original names: `pd`, `src_hostname`,
`src_href`, `src_labels`, `dst_hostname`, `dst_href`, `dst_labels`,
`process_name`, `num_connections`, `flow_count`, `interval_sec`.

CEF escaping is applied to all extension values: `\`, `|`, `=`, `\n`,
`\r` are backslash-escaped.

### syslog_cef

**Module:** `src/siem/formatters/syslog_wrapped.py` (wraps `CEFFormatter`)
**Tests:** `tests/test_json_formatter.py` (routing tests)

`SyslogWrappedFormatter` is a decorator: it calls the inner formatter,
then prepends an RFC5424 syslog header via `wrap_rfc5424()`
(`src/siem/formatters/syslog_header.py`).

```
<PRI>1 <TIMESTAMP> <pce_fqdn> illumio-ops - - - CEF:0|...
```

RFC5424 severity mapping:

| PCE severity | Syslog severity |
|---|---|
| `info` | 6 (informational) |
| `warning` / `warn` | 4 (warning) |
| `error` / `err` | 3 (error) |
| `critical` / `crit` | 2 (critical) |

Facility is always 1 (user-level messages). PRI = facility × 8 + severity.
`pce_fqdn` from the event/flow dict is used as the RFC5424 HOSTNAME field.

### syslog_json

**Module:** `src/siem/formatters/syslog_wrapped.py` (wraps `NormalizedJSONFormatter`)
**Tests:** `tests/test_json_formatter.py`

Same RFC5424 framing as `syslog_cef`, but the MSG portion is the flat
JSON output from `NormalizedJSONFormatter` rather than a CEF string.

```
<PRI>1 <TIMESTAMP> <pce_fqdn> illumio-ops - - - {"timestamp":"...","event_type":"..."}
```

### NormalizedJSON

**Module:** `src/siem/formatters/normalized_json.py`
**Tests:** `tests/test_json_formatter.py`

Outputs a flat single-level JSON object using official Illumio field names.
Handles both nested PCE API format and flat official log format. `None`
and empty-string values are omitted from output (`_omit_none()`).
Serialization uses `orjson` for performance.

This formatter was introduced in commit `edda47b` to fix the broken
Splunk HEC behavior where nested PCE JSON was indexed as an escaped string,
making fields unreachable without `spath`.

**Events (`format_event`):** output fields — see [Event schema](#event-schema).

**Flows (`format_flow`):** flat fields include `timestamp`, `pce_fqdn`,
`src_ip`, `dst_ip`, `dst_port`, `proto`, `pd` (policy decision),
`src_hostname`, `src_href`, `src_labels`, `dst_hostname`, `dst_href`,
`dst_labels`, `process_name`, `num_connections`, `flow_count`, `interval_sec`.

---

## Transports

All transports live in `src/siem/transports/`. The abstract base class is
`src/siem/transports/base.py`:

```python
class Transport(ABC):
    @abstractmethod
    def send(self, payload: str) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
```

Transport key (configured per destination as `transport:`) selects the
implementation at startup via `_transport_for()` in `src/siem/tester.py` /
`src/siem/dispatcher.py`.

### UDP syslog

**Module:** `src/siem/transports/syslog_udp.py`
**Tests:** `tests/test_transport_udp_tcp.py`

- Protocol: UDP datagram, no framing
- Default port: 514
- Connection: stateless, one `socket.SOCK_DGRAM` created at init
- Backpressure: none — fire and forget
- Retry: none — UDP has no delivery guarantee
- MTU warning: payloads exceeding 1 400 bytes trigger a `logger.warning`
  (fragmentation risk); delivery is still attempted

UDP is the lowest-overhead option but provides no delivery guarantee.
Use only where occasional event loss is acceptable.

### TCP syslog

**Module:** `src/siem/transports/syslog_tcp.py`
**Tests:** `tests/test_transport_udp_tcp.py`

- Protocol: TCP stream, newline-framed (`\n` appended to each payload)
- Default port: 514
- Connection: persistent; lazy-connected on first `send()`
- Thread safety: `threading.Lock()` guards the socket
- Reconnect: on `BrokenPipeError`, `ConnectionResetError`, or `OSError`,
  the socket is closed and a single reconnect is attempted before
  re-sending. If the reconnect fails, the exception propagates to the
  dispatcher (counted as a failed send, subject to retry/DLQ).
- Backpressure: none at the transport level — handled by the dispatcher

### TLS syslog

**Module:** `src/siem/transports/syslog_tls.py`
**Tests:** `tests/test_transport_tls.py`

- Protocol: TCP + TLS stream, newline-framed
- Default port: 6514
- TLS version: TLS 1.2+ (Python `ssl.create_default_context()` default)
- Custom CA: `ca_bundle` path passed to `ctx.load_verify_locations()`
- Verify disable: `tls_verify=False` sets `CERT_NONE` + disables hostname
  check; emits a `logger.warning`. Only for development.
- Connection / reconnect: identical pattern to TCP syslog — lazy connect,
  lock-guarded, single reconnect on `BrokenPipeError` / `ConnectionResetError` /
  `OSError` / `ssl.SSLError`
- Thread safety: `threading.Lock()`

### HEC

**Module:** `src/siem/transports/splunk_hec.py`
**Tests:** `tests/test_transport_hec.py`

- Protocol: HTTPS POST to Splunk HTTP Event Collector
- Default port: 8088
- Endpoint: `https://<host>:<port>/services/collector/event`
- Auth: `Authorization: Splunk <token>` header
- Sourcetype: `illumio_ops` (fixed)
- Timeout: 10 s per request

**JSON auto-detection:** if `payload` is valid JSON, `send()` passes
`event_data` as a dict so Splunk natively indexes all fields without
`spath`. Non-JSON payloads (e.g., CEF strings) are passed as a plain
string in the `event` field.

**Retry (urllib3 `Retry`):**

| Parameter | Value |
|---|---|
| `total` | 3 attempts |
| `backoff_factor` | 0.5 s |
| `status_forcelist` | 429, 500, 502, 503, 504 |
| `allowed_methods` | POST |

The session-level retry runs within a single `send()` call. If all 3
attempts fail, the exception propagates to the dispatcher.

---

## Retry & backpressure model

The dispatcher (`src/siem/dispatcher.py`) implements a persistent-queue
retry model on top of SQLite.

### Queue states

Each `SiemDispatch` row has a `status` field:

| Status | Meaning |
|---|---|
| `pending` | Ready to be dispatched on the next tick |
| `failed` | Exceeded `max_retries`; will not be retried automatically |

> **Note:** rows that exceed `max_retries` are moved to the `dead_letters`
> table (DLQ) — they do not stay as `failed` indefinitely.

### Retry loop

`DestinationDispatcher.tick()` is called on a timer (default: every
`dispatch_tick_seconds`, configurable via `SiemForwarderSettings`).
Each tick:

1. Selects up to `batch_size` pending rows whose `next_attempt_at` is in
   the past (or null).
2. Loads the source record from `pce_events` or `pce_traffic_flows_raw`.
3. Calls `formatter.format_event()` or `formatter.format_flow()`.
4. Calls `transport.send(payload)`.
5. On success: deletes the `SiemDispatch` row.
6. On failure:
   - Increments `retries`.
   - Sets `next_attempt_at = now + _backoff_seconds(retries)`.
   - Exponential backoff: `min(2^retries × 5, 3600)` seconds (capped at 1 h).
   - If `retries >= max_retries` (default 10): calls `_quarantine()`.

### Dead-letter queue (DLQ)

When a row is quarantined, the dispatcher:
1. Writes a `DeadLetter` row (table `dead_letters`) with `source_table`,
   `source_id`, `destination`, `retries`, `last_error`, `payload_preview`,
   and `quarantined_at`.
2. Deletes the `SiemDispatch` row.

DLQ management is exposed via `src/siem/dlq.py` (`DLQManager`):

- `list_entries(destination, limit)` — query DLQ for a destination
- `replay(destination, limit)` — requeue DLQ entries as new `pending` rows
- `purge(destination, older_than_days)` — delete old DLQ entries

The REST API (`src/siem/web.py`) exposes DLQ CSV export and replay
endpoints.

### Backpressure

There is no explicit backpressure signal from transports to the
dispatcher. Rate limiting is implicit:

- `batch_size` caps the number of rows processed per tick (default 100).
- `dispatch_tick_seconds` controls the minimum inter-tick interval.
- Exponential backoff prevents hammering a failing destination.

If the queue grows faster than it is drained, rows accumulate in
`siem_dispatch`. Monitor queue depth via the `/api/siem/queue` endpoint.

---

## Event schema

This is the canonical reference for the normalized internal event fields.
`user-guide/siem-integration.md` links here.

The pipeline receives raw PCE API dicts. The fields listed below are what
formatters extract and emit. All fields are optional unless marked
**required**.

### Audit event fields

| Field | Type | Source in raw dict | Meaning |
|---|---|---|---|
| `timestamp` | `str` (ISO8601) | `event.timestamp` | **Required.** Event occurrence time |
| `pce_fqdn` | `str` | `event.pce_fqdn` | **Required.** FQDN of the PCE that generated the event |
| `event_type` | `str` | `event.event_type` | **Required.** Dot-notation event type (e.g., `policy.rule.create`) |
| `severity` | `str` | `event.severity` | `info` / `warning` / `error` / `critical` |
| `status` | `str` | `event.status` | `success` / `failure` |
| `pce_event_id` | `str` | `event.pce_event_id` or `event.uuid` or `event.href` | Unique event identifier |
| `suser` | `str` | `event.created_by` (nested actor) | Actor who triggered the event (user email or service account) |
| `src_ip` | `str` | `event.action.src_ip` | Source IP of the API call |
| `request_method` | `str` | `event.action.api_method` | HTTP method of the API call (GET, POST, …) |
| `request` | `str` | `event.action.api_endpoint` | API endpoint path |
| `http_status_code` | `int` | `event.action.http_status_code` | HTTP response code |
| `resource_changes` | `str` | `event.resource_changes[]` | Human-readable summary of resource changes (formatted list) |

### Traffic flow fields

| Field | Type | Source in raw dict | Meaning |
|---|---|---|---|
| `timestamp` | `str` (ISO8601) | `flow.timestamp` or `flow.first_detected` or `flow.timestamp_range.first_detected` | **Required.** Flow detection time |
| `pce_fqdn` | `str` | `flow.pce_fqdn` | PCE that reported the flow |
| `src_ip` | `str` | `flow.src_ip` or `flow.src.ip` | Source IP address |
| `dst_ip` | `str` | `flow.dst_ip` or `flow.dst.ip` | Destination IP address |
| `dst_port` | `int` | `flow.dst_port` or `flow.port` or `flow.service.port` | Destination port |
| `proto` | `str` | `flow.proto` or `flow.protocol` or `flow.service.proto` | Protocol: `tcp`, `udp`, `icmp`, or numeric string |
| `pd` | `str` | `flow.pd` or `flow.policy_decision` | Policy decision: `allowed`, `blocked`, `potentially_blocked`, `unknown` |
| `src_hostname` | `str` | `flow.src_hostname` or `flow.src.workload.hostname` | Source workload hostname |
| `src_href` | `str` | `flow.src_href` or `flow.src.workload.href` | Source workload href |
| `src_labels` | `str` | `flow.src_labels` or `flow.src.workload.labels` | Formatted Illumio labels for source workload |
| `dst_hostname` | `str` | `flow.dst_hostname` or `flow.dst.workload.hostname` | Destination workload hostname |
| `dst_href` | `str` | `flow.dst_href` or `flow.dst.workload.href` | Destination workload href |
| `dst_labels` | `str` | `flow.dst_labels` or `flow.dst.workload.labels` | Formatted Illumio labels for destination workload |
| `process_name` | `str` | `flow.process_name` | Process name (if available) |
| `num_connections` | `int` | `flow.num_connections` | Connection count in the interval |
| `flow_count` | `int` | `flow.flow_count` | Flow count |
| `interval_sec` | `int` | `flow.interval_sec` | Aggregation interval in seconds |

### Notes on `proto` normalization

Protocol is normalized from numeric (IANA) to string by `_proto_to_str()`:

| Number | String |
|---|---|
| 1 | `icmp` |
| 6 | `tcp` |
| 17 | `udp` |
| other | numeric string (pass-through) |

### Notes on actor extraction (`suser`)

`_extract_actor(created_by)` checks, in order:
`created_by.user.username` → `created_by.service_account.name` →
`created_by.system_account` → falls back to empty string.

---

## Adding a new formatter

1. **Create** `src/siem/formatters/<name>.py`. Subclass `Formatter`
   (`src/siem/formatters/base.py`) and implement `format_event(event: dict) -> str`
   and `format_flow(flow: dict) -> str`.

2. **Register** the format key in `src/siem/tester.py` inside
   `_build_formatter(fmt: str)` — add an `if fmt == "<key>": return YourFormatter()` branch.

3. **Register** the same key in `src/siem/dispatcher.py` inside
   `_formatter_for(dest_cfg)` for production dispatcher use.

4. **Validate** the format key in `src/config_models.py` —
   `SiemDestinationSettings.format` should accept the new key
   (add it to the `Literal[...]` type or validator if one exists).

5. **Add tests** in `tests/test_<name>_formatter.py`. At minimum: one
   event test and one flow test; check that output round-trips through
   a syslog-wrapping if applicable.

---

## Adding a new transport

1. **Create** `src/siem/transports/<name>.py`. Subclass `Transport`
   (`src/siem/transports/base.py`) and implement `send(payload: str) -> None`
   and `close() -> None`. Use a `threading.Lock()` if the transport holds
   persistent state (socket, session).

2. **Register** the transport key in `src/siem/tester.py` inside
   `_build_transport(dest_cfg)` — add a branch for the new key.

3. **Register** the same key in `src/siem/dispatcher.py` inside
   `_transport_for(dest_cfg)` for production dispatcher use.

4. **Add any new config fields** needed (host, port, token, etc.) to
   `SiemDestinationSettings` in `src/config_models.py`.

5. **Add tests** in `tests/test_transport_<name>.py`. Cover: successful
   send, connection failure (verify exception propagates), and any
   transport-specific behavior (retry, TLS, MTU warning, etc.).

---

## Related Docs
- [Architecture Overview](overview.md) — bigger picture
- [SIEM Integration (operator)](../user-guide/siem-integration.md) — operator-level setup
- [REST API](../reference/rest-api.md) — destination management endpoints
- [Alerts & Quarantine](../user-guide/alerts-and-quarantine.md) — major event source
