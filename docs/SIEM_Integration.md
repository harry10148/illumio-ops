# SIEM Integration Guide

illumio_ops emits structured JSON logs when the loguru JSON sink is enabled.
This document shows how to ship those logs to Splunk / Elastic / QRadar / Sentinel.

## Option E — Built-in Forwarder (Recommended for On-Box Push)

illumio_ops v3.11+ includes a native SIEM forwarder that pushes PCE audit events and traffic flows directly to your SIEM over UDP, TCP, TCP+TLS, or Splunk HEC — no sidecar required.

**Advantages over file-based options (A–D):**
- Pushes PCE API data (not just app logs): audit events, traffic flows, policy decisions
- Built-in DLQ with replay — no events lost during SIEM downtime
- CEF 0.1 and JSON Lines format with optional RFC5424 syslog envelope
- Rate-limited ingestor respects the PCE 500 req/min budget

**Quick start:** See [`docs/SIEM_Forwarder.md`](SIEM_Forwarder.md).

---

## 1. Enable the JSON sink

In `config/config.json`, set:

```json
{
  "logging": {
    "level": "INFO",
    "json_sink": true,
    "rotation": "50 MB",
    "retention": 30
  }
}
```

Restart the daemon. The JSON log file appears at `logs/illumio_ops.json.log`.
Each line is a valid JSON object:

```json
{"text": "...", "record": {"time": {"timestamp": 1700000000.0}, "level": {"name": "INFO"}, "name": "monitor", "message": "Monitor cycle complete", "extra": {}}}
```

## 2. Forwarding options

### Option A — Filebeat (Elastic Stack)

See `deploy/filebeat.illumio_ops.yml` for a ready-to-use input configuration.

```bash
# Copy and edit the sample
cp deploy/filebeat.illumio_ops.yml /etc/filebeat/conf.d/illumio_ops.yml
# Update output.elasticsearch.hosts to your cluster
filebeat test config && systemctl restart filebeat
```

### Option B — Logstash pipeline

See `deploy/logstash.illumio_ops.conf` for a complete input-filter-output pipeline.

```bash
cp deploy/logstash.illumio_ops.conf /etc/logstash/conf.d/
# Update output.elasticsearch.hosts to your cluster
systemctl restart logstash
```

### Option C — rsyslog (syslog-based SIEMs, e.g. QRadar, ArcSight)

See `deploy/rsyslog.illumio_ops.conf` for a `imfile`-based forwarding configuration.

```bash
cp deploy/rsyslog.illumio_ops.conf /etc/rsyslog.d/90-illumio_ops.conf
# Update Target and Port to your SIEM's syslog receiver
systemctl restart rsyslog
```

### Option D — Splunk Universal Forwarder

Add a monitor stanza to `$SPLUNK_HOME/etc/system/local/inputs.conf`:

```ini
[monitor:///opt/illumio-ops/logs/illumio_ops.json.log]
sourcetype = _json
index = illumio_ops
```

Then restart the forwarder:

```bash
$SPLUNK_HOME/bin/splunk restart
```

## 3. Useful search queries

### Elastic / Kibana

```
record.level.name: "ERROR"
record.message: *RateLimit*
record.message: *MonitorCycle*
```

### Splunk

```spl
source="/opt/illumio-ops/logs/illumio_ops.json.log" record.level.name="ERROR"
| spath record.message | search record.message="*RateLimit*"
```

### QRadar (AQL)

```sql
SELECT "record.message", "record.time.timestamp"
FROM events
WHERE devicetype=<illumio_ops_device_id>
  AND "record.level.name" = 'ERROR'
LAST 24 HOURS
```

## 4. Key log event types

| record.message prefix | Meaning |
|---|---|
| `Monitor cycle complete` | Periodic analysis run finished normally |
| `Monitor cycle failed` | Analysis error — check `record.exception` |
| `[Scheduler] Triggering schedule` | Report schedule fired |
| `[Scheduler] Running schedule` | Report generation started |
| `RateLimit` | PCE API throttling detected |
| `AsyncJob` | Long-running API query in progress |
| `[RuleScheduler]` | Rule schedule evaluation result |

## 5. Alerting recommendations

- Alert on `record.level.name = "ERROR"` within any 5-minute window
- Alert on repeated `RateLimit` messages (>10 in 1 hour indicates credential or concurrency issue)
- Alert on absence of `Monitor cycle complete` for >2× the configured interval
