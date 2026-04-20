# SIEM Forwarder

## Architecture

```
PCE API
  └─► EventsIngestor / TrafficIngestor
           │  (rate-limited, watermarked)
           ▼
      pce_cache.sqlite
           │
     siem_dispatch table
           │
      SiemDispatcher (tick every 5s)
           │
      ┌────┴───────────────────┐
      │         Formatter      │
      │  CEF 0.1 / JSON Lines  │
      │  + RFC5424 syslog hdr  │
      └────┬───────────────────┘
           │
      ┌────┴───────────────────┐
      │       Transport        │
      │  UDP / TCP / TLS / HEC │
      └────────────────────────┘
           │  (failure → DLQ)
           ▼
      SIEM / Splunk / Elastic
```

## Prerequisites

PCE cache must be enabled first (`pce_cache.enabled: true`).

## Enabling

Add to `config/config.json`:

```json
"siem": {
  "enabled": true,
  "destinations": [
    {
      "name": "splunk-hec",
      "transport": "hec",
      "format": "json",
      "endpoint": "https://splunk.example.com:8088",
      "hec_token": "your-hec-token-here",
      "source_types": ["audit", "traffic"],
      "max_retries": 10
    }
  ]
}
```

## Destination Config Schema

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Unique identifier (1–64 chars) |
| `transport` | udp\|tcp\|tls\|hec | required | Wire protocol |
| `format` | cef\|json\|syslog_cef\|syslog_json | `cef` | Log line format |
| `endpoint` | string | required | `host:port` for syslog; full URL for HEC |
| `tls_verify` | bool | `true` | Verify TLS certificate (disable only for dev) |
| `tls_ca_bundle` | string | null | Path to CA bundle for custom PKI |
| `hec_token` | string | null | Splunk HEC token (required for `transport: hec`) |
| `batch_size` | int | 100 | Rows per dispatcher tick |
| `source_types` | list | `["audit","traffic"]` | Which data to forward |
| `max_retries` | int | 10 | Retries before quarantine |

## Format Samples

**CEF (audit event):**
```
CEF:0|Illumio|PCE|3.11|policy.update|policy.update|3|rt=1745049600000 dvchost=pce.example.com externalId=uuid-abc outcome=success
```

**JSON Lines (traffic flow):**
```json
{"src_ip":"10.0.0.1","dst_ip":"10.0.0.2","port":443,"protocol":"tcp","action":"blocked","flow_count":5}
```

**RFC5424 syslog envelope (wraps any format):**
```
<14>1 2026-04-19T10:00:00.000Z pce.example.com illumio-ops - - - CEF:0|Illumio|PCE|...
```

Use `format: syslog_cef` or `format: syslog_json` to enable the RFC5424 wrapper.

## Testing a Destination

```bash
illumio-ops siem test splunk-hec
```

Sends one synthetic `siem.test` event and reports success or failure with the error message.

## DLQ Operator Guide

When a destination fails `max_retries` times, the dispatch row moves to the `dead_letter` table. Inspect with:

```bash
illumio-ops siem dlq --dest splunk-hec
```

After fixing the root cause (bad token, network partition, etc.), replay:

```bash
illumio-ops siem replay --dest splunk-hec --limit 1000
```

Purge old entries that are no longer needed:

```bash
illumio-ops siem purge --dest splunk-hec --older-than 30
```

## Transport Selection Guide

| Transport | Delivery | Ordering | Encryption | Use case |
|---|---|---|---|---|
| UDP | Best-effort | No | No | Low-value, high-volume; fire-and-forget |
| TCP | At-least-once | Yes | No | Internal network, no TLS required |
| TLS | At-least-once | Yes | Yes | **Recommended** for production |
| HEC | At-least-once | Yes | Yes (HTTPS) | Splunk environments |

UDP is available but **not recommended for production** — the GUI will show a warning banner when you configure a UDP destination.

## Backoff Schedule

Failed sends are retried with exponential backoff capped at 1 hour:

| Retry | Wait |
|---|---|
| 1 | 10s |
| 2 | 20s |
| 3 | 40s |
| 4 | 80s |
| 5 | 160s |
| 6 | 320s |
| 7 | 640s |
| 8 | 1280s |
| 9 | 2560s |
| 10 | 3600s (cap) |
