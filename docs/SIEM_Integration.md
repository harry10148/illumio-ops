# SIEM Integration

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
| Glossary | [Glossary.md](./Glossary.md) | [Glossary_zh.md](./Glossary_zh.md) |
| Troubleshooting | [Troubleshooting.md](./Troubleshooting.md) | [Troubleshooting_zh.md](./Troubleshooting_zh.md) |
<!-- END:doc-map -->

---

## SIEM Forwarder

> [!WARNING]
> Status: **Preview** (2026-04-23).
> Existing deployments may continue to use SIEM forwarding for compatibility, but full production rollout should wait until runtime pipeline gaps are closed.
>
> Known gaps tracked in Task.md:
> - Runtime ingest path does not yet auto-enqueue SIEM dispatch rows.
> - Scheduler dispatch path is not yet wired to a full end-to-end consumer loop.
> - Payload-build failures can currently leave rows in persistent `pending` state.

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

## Global `siem` Config Block

The top-level `siem` section in `config.json` controls the forwarder runtime:

| Key | Type | Default | Description |
|---|---|---|---|
| `siem.enabled` | bool | `false` | Enable the SIEM forwarder |
| `siem.destinations` | list | `[]` | List of destination objects (see schema below) |
| `siem.dlq_max_per_dest` | int | `10000` | Maximum dead-letter queue depth per destination before oldest rows are evicted |
| `siem.dispatch_tick_seconds` | int | `5` | How often (in seconds) the dispatcher checks for pending rows |

**Operator commands:** `illumio-ops siem test <name>` (send synthetic event), `illumio-ops siem status` (show per-destination dispatch counts), `illumio-ops siem replay --dest <name>` (requeue DLQ entries), `illumio-ops siem dlq --dest <name>` (list dead-lettered events), `illumio-ops siem purge --dest <name>` (remove DLQ entries older than N days).

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

| Option | Transport | Delivery | Ordering | Encryption | Use case |
|---|---|---|---|---|---|
| Option A | UDP | Best-effort | No | No | Low-value, high-volume; fire-and-forget |
| Option B | TCP | At-least-once | Yes | No | Internal network, no TLS required |
| Option C | TLS | At-least-once | Yes | Yes | **Recommended** for production |
| Option D | HEC | At-least-once | Yes | Yes (HTTPS) | Splunk environments |

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


## CLI Reference

The `illumio-ops siem` subcommand group manages destinations and the dispatch queue. The table below summarises the subcommands shipped in `src/cli/siem.py`; for full option syntax see [User Manual §1.5](./User_Manual.md#illumio-ops-siem-subcommands).

| Command | Purpose |
|---|---|
| `illumio-ops siem test <name>` | Send a synthetic `siem.test` event to a configured destination and report latency |
| `illumio-ops siem status` | Show per-destination pending / sent / failed counts and DLQ depth |
| `illumio-ops siem dlq --dest <name>` | List dead-letter queue entries for a destination |
| `illumio-ops siem replay --dest <name>` | Requeue DLQ entries as pending dispatch rows |
| `illumio-ops siem purge --dest <name>` | Delete DLQ entries older than N days (default 30) |

> Note: there is no `siem flush` subcommand. The dispatcher drains the queue automatically on its `siem.dispatch_tick_seconds` interval (default 5 s).

Examples:

```bash
illumio-ops siem test splunk-hec
illumio-ops siem status
illumio-ops siem dlq --dest splunk-hec --limit 20
illumio-ops siem replay --dest splunk-hec --limit 500
illumio-ops siem purge --dest splunk-hec --older-than 7
```

## Receiver Examples

Sample receiver configurations for the most common SIEM / log platforms. Pair each receiver with a matching destination block in `config/config.json` (see [Destination Config Schema](#destination-config-schema)).

### Splunk HEC

In Splunk Web → Settings → Data inputs → HTTP Event Collector:

1. Create a new token with source type `_json` and index `illumio_ops`.
2. Note the token; place the URL in the destination's `endpoint` and the token in `hec_token`.

Verify with curl:

```bash
curl -k -H "Authorization: Splunk <TOKEN>" \
  https://splunk:8088/services/collector/event \
  -d '{"event":"test"}'
```

### Splunk via Syslog (UDP / TCP)

`inputs.conf`:

```conf
[udp://514]
sourcetype = cef
index = illumio_ops

[tcp://1514]
sourcetype = cef
index = illumio_ops
```

### Logstash (JSON line)

```conf
input {
  tcp { port => 5044  codec => json_lines }
}
filter {
  if [event_type] {
    mutate { add_tag => ["illumio_event"] }
  }
}
output {
  elasticsearch { hosts => ["es:9200"] index => "illumio-ops-%{+YYYY.MM.dd}" }
}
```

### rsyslog (CEF over UDP)

`/etc/rsyslog.d/illumio.conf`:

```conf
$ModLoad imudp
$UDPServerRun 514
:msg, contains, "CEF:0|Illumio" /var/log/illumio.log
& stop
```

### Filebeat (tail JSON sink file)

```yaml
filebeat.inputs:
  - type: log
    paths: ["/opt/illumio_ops/logs/illumio_ops.json.log"]
    json.keys_under_root: true
output.elasticsearch:
  hosts: ["es:9200"]
  index: "illumio-ops-%{+yyyy.MM.dd}"
```

## See also

- [User Manual §1.5 — `illumio-ops siem` subcommands](./User_Manual.md#illumio-ops-siem-subcommands) — full subcommand syntax and options
- [User Manual](./User_Manual.md) — Execution modes, alert channels, and advanced deployment
- [Architecture](./Architecture.md) — System overview, module map, PCE Cache, REST API Cookbook
- [README](../README.md) — Project entry and Quickstart
