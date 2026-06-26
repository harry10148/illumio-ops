---
title: SIEM Integration
audience: [operator, security]
last_verified: 2026-05-15
verified_against:
  - src/siem/
  - src/siem/formatters/
  - src/siem/transports/
  - python illumio-ops.py siem --help
  - python illumio-ops.py siem status --help
  - commit c792c93
related_docs:
  - ../architecture/siem-pipeline.md
  - alerts-and-quarantine.md
  - tls-and-certificates.md
  - ../reference/rest-api.md
---

> 🌐 **[English](siem-integration.md)** | **[繁體中文](siem-integration_zh.md)**
> 📍 [INDEX](../INDEX.md) › User Guide › SIEM Integration
> 🔍 Last verified **2026-05-15** against commit `c792c93` — see frontmatter for sources

# SIEM Integration

illumio-ops can forward PCE audit events and traffic flow records to any
syslog-compatible SIEM, Splunk via HTTP Event Collector (HEC), or a local
JSON sink file.  Forwarding is persistent: events are queued in a local
SQLite dispatch table and retried with back-off before entering a dead-letter
queue (DLQ).

---

## Supported destinations

Four wire-protocol transports are available, verified in `src/siem/transports/`:

| Transport key | Module | Protocol | Default port | Notes |
|---|---|---|---|---|
| `udp` | `syslog_udp.py` | Syslog UDP | 514 | Low-overhead; no delivery guarantee |
| `tcp` | `syslog_tcp.py` | Syslog TCP | 514 | Persistent connection; auto-reconnects |
| `tls` | `syslog_tls.py` | Syslog TCP + TLS | 6514 | TLS 1.2+; custom CA bundle supported |
| `hec` | `splunk_hec.py` | Splunk HTTP Event Collector (HTTPS) | 8088 | JSON auto-indexed by Splunk natively |

> **Note:** There is no plain-HTTP HEC transport. The `hec` transport always
> connects over HTTPS (`https://host:port`). Set `tls_verify: false` only in
> development environments.

---

## Configuring a destination

### Via the Web UI

1. Navigate to **Settings → Integrations → SIEM**.
2. Click **Add destination** to open the destination modal.
3. Fill in the fields:
   - **Name** — unique label (1–64 characters).
   - **Transport** — `udp`, `tcp`, `tls`, or `hec`.
   - **Host** and **Port** — entered as separate fields (post-redesign UX,
     commit `7035f50`).  Default port is `514` for syslog and `8088` for HEC.
   - **Format** — see [Formatter choices](#formatter-choices).
   - **HEC Token** — required when transport is `hec`.
   - **TLS options** — visible when transport is `tls`; see
     [TLS configuration for syslog](#tls-configuration-for-syslog).
   - **Source types** — `audit`, `traffic`, or both.
4. Click **Save**, then use the **Test** button to send a synthetic `siem.test`
   event and verify connectivity.

### Via the CLI / config file

Destinations are stored in `config/config.json` under `siem.destinations`.
The full field schema (verified against `src/config_models.py`):

```json
{
  "name":          "splunk-prod",
  "transport":     "hec",
  "format":        "json",
  "host":          "splunk.example.com",
  "port":          8088,
  "hec_token":     "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tls_verify":    true,
  "tls_ca_bundle": null,
  "batch_size":    100,
  "source_types":  ["audit", "traffic"],
  "max_retries":   10
}
```

**Field reference:**

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Unique identifier |
| `transport` | `udp`\|`tcp`\|`tls`\|`hec` | `udp` | Wire protocol |
| `format` | `cef`\|`json`\|`syslog_cef`\|`syslog_json` | `cef` | Log line format |
| `host` | string | required | Destination hostname or IP |
| `port` | int (1–65535) | `514` | Destination port |
| `tls_verify` | bool | `true` | Verify TLS certificate |
| `tls_ca_bundle` | string\|null | `null` | Path to custom CA bundle |
| `hec_token` | string\|null | `null` | Splunk HEC token (required for `hec`) |
| `batch_size` | int (1–10000) | `100` | Rows per dispatcher tick |
| `source_types` | list | `["audit","traffic"]` | Which data to forward |
| `max_retries` | int | `10` | Retries before DLQ quarantine |

> **Legacy migration:** If your config still uses a single `endpoint: "host:port"`
> field, the model validator auto-splits it into `host` + `port` on load.

---

## Event types forwarded

Two source tables feed the SIEM dispatch queue (verified in
`src/siem/dispatcher.py`):

| `source_types` value | Source table | Content |
|---|---|---|
| `audit` | `pce_events` | PCE audit log — policy changes, login events, API calls, workload operations |
| `traffic` | `pce_traffic_flows_raw` | Traffic flow summaries — src/dst IP, port, protocol, policy decision |

Events are enqueued inline as each ingestor writes a new cache row.  A
safety-net backfill also re-scans both tables on startup to catch any rows
the ingestors missed.

The dispatcher runs every 5 seconds (`siem.dispatch_tick_seconds`).  On
persistent transport failures the row is retried up to `max_retries` times,
then moved to the dead-letter queue (DLQ).

> **Cross-reference:** For the full event schema (all fields per event type),
> see [SIEM Pipeline — Architecture](../architecture/siem-pipeline.md) (B2
> deliverable). Quarantine-trigger events are documented in
> [Alerts & Quarantine](alerts-and-quarantine.md).

---

## Formatter choices

Four format values are supported, verified in `src/siem/formatters/`:

| `format` value | Class | Output | Best for |
|---|---|---|---|
| `cef` | `CEFFormatter` (`cef.py`) | ArcSight CEF 0.1 — one line per event | ArcSight, QRadar, any CEF-aware SIEM |
| `syslog_cef` | `SyslogWrappedFormatter(CEFFormatter())` | CEF line wrapped in RFC5424 syslog header | Syslog servers that require proper RFC5424 framing around CEF |
| `json` | `NormalizedJSONFormatter` (`normalized_json.py`) | Flat JSON object — official Illumio field names, no nested keys | Splunk HEC (auto-indexed), Elastic, Logstash, file sinks |
| `syslog_json` | `SyslogWrappedFormatter(NormalizedJSONFormatter())` | Flat JSON wrapped in RFC5424 syslog header | rsyslog / syslog-ng receivers that expect RFC5424 + JSON body |

**When to use which:**

- Use **`cef`** when your SIEM has a native CEF parser (ArcSight, QRadar,
  Splunk `syslog` sourcetype with `TRANSFORMS-cef`).
- Use **`syslog_cef`** when your syslog receiver requires the RFC5424
  `<priority>VERSION TIMESTAMP HOSTNAME APPNAME` header before the CEF line.
- Use **`json`** (with transport `hec`) for Splunk — the HEC transport
  auto-detects JSON payloads and sends them as structured objects so all
  fields are natively indexed without `spath`.
- Use **`syslog_json`** for rsyslog or syslog-ng pipelines that accept JSON
  bodies inside RFC5424 framing (e.g. `mmjsonparse` module).

**RFC5424 severity mapping** (implemented in `syslog_wrapped.py`):

| Event severity | Syslog numeric |
|---|---|
| `info` | 6 |
| `warning` / `warn` | 4 |
| `error` / `err` | 3 |
| `critical` / `crit` | 2 |

**Sample output — CEF audit event:**
```
CEF:0|Illumio|PCE|3.11|policy.update|policy.update|3|rt=1745049600000 dvchost=pce.example.com externalId=uuid-abc outcome=success
```

**Sample output — RFC5424 syslog envelope:**
```
<14>1 2026-04-19T10:00:00.000Z pce.example.com illumio-ops - - - CEF:0|Illumio|PCE|...
```

---

## TLS configuration for syslog

Use transport `tls` for encrypted syslog delivery.  The TLS transport
(`src/siem/transports/syslog_tls.py`) wraps a TCP socket with Python's
`ssl.create_default_context()`.

**Config fields:**

| Field | Purpose |
|---|---|
| `tls_verify: true` | *(default)* Validates server certificate chain and hostname |
| `tls_verify: false` | Disables certificate validation — **development/lab only** |
| `tls_ca_bundle: "/path/to/ca.pem"` | Load custom CA bundle for private PKI |

**Example destination (syslog TLS to Graylog):**
```json
{
  "name":          "graylog-tls",
  "transport":     "tls",
  "format":        "syslog_cef",
  "host":          "graylog.corp.example.com",
  "port":          6514,
  "tls_verify":    true,
  "tls_ca_bundle": "/etc/illumio-ops/ca-bundle.pem"
}
```

**Reconnect behaviour:** The TLS transport holds a persistent connection.
On `BrokenPipeError`, `ConnectionResetError`, or `SSLError`, it automatically
closes and re-opens the socket before retrying the failed send.

For issuing and rotating the CA bundle, see
[TLS & Certificates](tls-and-certificates.md).

---

## Testing & status

### Test a destination

Send a synthetic `siem.test` event to verify connectivity before any real
events are queued:

```bash
illumio-ops siem test <destination-name>
# e.g.
illumio-ops siem test splunk-prod
```

The tester builds the configured formatter + transport, sends a minimal
`siem.test` event, and reports latency in milliseconds.  A non-zero exit
code and error message are printed on failure.

### Check dispatch status

```bash
illumio-ops siem status
```

Shows a per-destination table of pending / sent / failed counts and DLQ
depth.  The destination set is the union of (a) configured destinations from
`cm.models.siem.destinations` and (b) any destinations seen in the
`SiemDispatch` DB table — matching the WebUI Integrations tab view (UX Review
§11.2, commits `d217646` / `4577c7b`).

**Empty-state hint:** If no destinations are configured *and* the dispatch
table is empty, the command prints a setup hint instead of an empty table
(restored in `4577c7b`).

### Manage the dead-letter queue

```bash
illumio-ops siem dlq   --dest <name> [--limit N]   # list DLQ entries
illumio-ops siem replay --dest <name> [--limit N]  # requeue as pending
illumio-ops siem purge  --dest <name> [--older-than N]  # delete (default 30 days)
```

> **Note:** There is no `siem flush` subcommand. The dispatcher drains
> automatically on its tick interval (default 5 s).

---

## Compliance & audit forwarding

This section is the entry point for Security / Compliance Auditors (per
`docs/INDEX.md` §Security).

All PCE audit events (`event_type: policy.update`, login events, API calls,
workload state changes, etc.) are forwarded when `source_types` includes
`"audit"`.  Key properties for compliance use:

- **Tamper-evident delivery:** Events are written to the local dispatch queue
  before being sent.  If transmission fails, they are retried up to
  `max_retries` times then held in the DLQ — they are never silently dropped.
- **Event identity:** Every forwarded audit event carries `pce_event_id`
  (falls back to `uuid` then `href` when the raw PCE JSON format is used).
- **Actor attribution:** The `suser` / `created_by` field identifies the
  user or service account that triggered each event.
- **Timestamp:** ISO-8601 UTC timestamp on every event.

**Recommended config for compliance forwarding:**
```json
{
  "name":         "audit-siem",
  "transport":    "tls",
  "format":       "syslog_cef",
  "host":         "siem.corp.example.com",
  "port":         6514,
  "tls_verify":   true,
  "source_types": ["audit"],
  "max_retries":  10
}
```

> For the full audit event field schema, see
> [SIEM Pipeline (architecture)](../architecture/siem-pipeline.md).

---

## Related Docs
- [SIEM Pipeline (architecture)](../architecture/siem-pipeline.md) — internal event flow + schema (B2)
- [Alerts & Quarantine](alerts-and-quarantine.md) — sources of forwarded events
- [TLS & Certificates](tls-and-certificates.md) — for syslog-TLS deployments
- [REST API](../reference/rest-api.md) — programmatic destination management (B2)
