# SIEM Integration Guide

This file is intentionally kept in English because existing tests and external links reference `docs/SIEM_Integration.md`. The main operations manual is now `docs/User_Manual_zh.md`.

The built-in SIEM forwarder is currently **Preview**. Existing deployments can keep using it for compatibility. New production deployments should validate throughput, TLS, retry, and DLQ behavior before relying on it as a primary pipeline.

## Option E — Built-in Forwarder (Recommended for On-Box Push)

The built-in forwarder reads cached audit/traffic records, formats them as CEF/JSON/syslog, and sends them to configured destinations.

Supported transports:

- UDP
- TCP
- TLS
- Splunk HEC

Supported formats:

- CEF
- JSON line
- syslog CEF
- syslog JSON

Example destination:

```json
{
  "name": "soc",
  "enabled": true,
  "transport": "tls",
  "format": "cef",
  "endpoint": "siem.example.com:6514",
  "tls_verify": true,
  "batch_size": 100,
  "source_types": ["audit", "traffic"],
  "max_retries": 10
}
```

CLI:

```bash
python illumio_ops.py siem status
python illumio_ops.py siem test soc
python illumio_ops.py siem dlq --dest soc
python illumio_ops.py siem replay --dest soc --limit 100
python illumio_ops.py siem purge --dest soc --older-than 30
```

Web API:

- `GET /api/siem/destinations`
- `POST /api/siem/destinations`
- `PUT /api/siem/destinations/<name>`
- `DELETE /api/siem/destinations/<name>`
- `POST /api/siem/destinations/<name>/test`
- `GET /api/siem/status`
- `GET /api/siem/dlq`
- `POST /api/siem/dlq/replay`
- `POST /api/siem/dlq/purge`
- `GET /api/siem/dlq/export`

## 1. Enable the JSON Sink

For file-based collection, enable structured JSON logs:

```json
{
  "logging": {
    "json_sink": true,
    "level": "INFO"
  }
}
```

This writes JSON lines to `logs/illumio_ops.json.log`.

## 2. Forwarding Options

### Option A — Filebeat (Elastic Stack)

Use `deploy/filebeat.illumio_ops.yml`.

```bash
cp deploy/filebeat.illumio_ops.yml /etc/filebeat/conf.d/illumio_ops.yml
# Update output.elasticsearch.hosts to your cluster
systemctl restart filebeat
```

### Option B — Logstash Pipeline

Use `deploy/logstash.illumio_ops.conf`.

```bash
cp deploy/logstash.illumio_ops.conf /etc/logstash/conf.d/illumio_ops.conf
# Update output.elasticsearch.hosts to your cluster
systemctl restart logstash
```

### Option C — rsyslog

Use `deploy/rsyslog.illumio_ops.conf`.

```bash
cp deploy/rsyslog.illumio_ops.conf /etc/rsyslog.d/50-illumio-ops.conf
# Update Target and Port to your SIEM syslog receiver
systemctl restart rsyslog
```

### Option D — Splunk Universal Forwarder

Monitor either:

- `logs/illumio_ops.log`
- `logs/illumio_ops.json.log`
- built-in HEC destination from Option E

## 3. Useful Search Queries

### Elastic / Kibana

```text
event.module:"illumio_ops" AND severity:("HIGH" OR "CRITICAL")
```

### Splunk

```text
index=illumio_ops (severity=HIGH OR severity=CRITICAL)
```

### QRadar AQL

```sql
SELECT * FROM events
WHERE UTF8(payload) ILIKE '%illumio_ops%'
LAST 24 HOURS
```

## 4. Key Event Types

Common event categories:

- PCE health and connectivity.
- Agent missed heartbeat / offline / tampering.
- Login and API authentication failures.
- Ruleset and security policy changes.
- Traffic findings from reports.
- SIEM dispatcher / DLQ events.

## 5. Alerting Recommendations

- Alert immediately on `CRITICAL` and `HIGH` findings.
- Treat cross-environment lateral ports and unmanaged-to-critical-services as priority incidents.
- Monitor DLQ growth per destination.
- Alert when SIEM pending rows grow continuously while sent rows do not increase.
- Keep cache lag monitoring enabled when using SIEM Preview, because the forwarder depends on cached records.

## 6. DLQ Operator Guide

Use DLQ when destination delivery fails after retry or when payload preparation fails.

Recommended flow:

1. Check destination status.
2. Fix network, TLS, token, or receiver-side issue.
3. Replay DLQ for the destination.
4. Purge old DLQ entries only after confirming replay is unnecessary.

```bash
python illumio_ops.py siem status
python illumio_ops.py siem dlq --dest soc --limit 50
python illumio_ops.py siem replay --dest soc --limit 100
python illumio_ops.py siem purge --dest soc --older-than 30
```
