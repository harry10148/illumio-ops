"""This product's own events in every format (P7 Task 2)."""
import json
import re
from datetime import UTC, datetime

import pytest

from illumio_ops import __version__
from illumio_ops.domain.values import Severity, SiemFormat
from illumio_ops.siem.formatters.factory import formatter_for
from illumio_ops.siem.formatters.ops import CS_LIMIT
from illumio_ops.siem.records import Endpoint, SiemRecord

T0 = datetime(2026, 10, 31, 3, 4, 5, 123000, tzinfo=UTC)
WEB = Endpoint(ip="10.0.0.5", host="web01", href="/orgs/1/workloads/w1", labels={"app": "shop", "env": "prod"})
DB = Endpoint(ip="10.0.0.9", host="db01", href="/orgs/1/workloads/w2", labels={"app": "shop", "role": "db"})


def detection(**kw):
    base = dict(kind="detection", record_id=42, time=T0, signature="detection.fanout", name="SSH fan-out",
                severity=Severity.HIGH, summary="web01 reached 12 hosts on 22/TCP in 60 minutes", src=WEB, port=22,
                proto=6, first_seen=T0, last_seen=T0, facts={"targets": 12, "occurrences": 1},
                pce_fqdn="pce.lab.local")
    base.update(kw)
    return SiemRecord(**base)


def new_connection():
    return SiemRecord(kind="new_connection", record_id=7, time=T0, signature="new_connection.allowed",
                      name="New connection", summary="web01 → db01 5432/TCP first seen", src=WEB, dst=DB, port=5432,
                      proto=6, decision="allowed", first_seen=T0, pce_fqdn="pce.lab.local")


def ext_keys(line: str) -> dict[str, str]:
    ext = line.split("|", 7)[7]
    parts = re.split(r"(?<!\\) (?=[A-Za-z0-9_]+=)", ext)
    return dict(p.split("=", 1) for p in parts)


def test_detection_cef_names_illumio_ops_as_the_device():
    line = formatter_for(SiemFormat.CEF).format_record(detection())
    assert line.startswith(f"CEF:0|Illumio|illumio-ops|{__version__}|detection.fanout|SSH fan-out|8|")
    kv = ext_keys(line)
    assert kv["rt"] == str(int(T0.timestamp() * 1000))  # epoch ms: no zone suffix for Graylog to drop
    assert kv["externalId"] == "detection:42" and kv["cat"] == "illumio_ops_detection"
    assert kv["src"] == "10.0.0.5" and kv["shost"] == "web01" and kv["dpt"] == "22" and kv["proto"] == "tcp"
    assert json.loads(kv["cs1"]) == {"app": "shop", "env": "prod"} and kv["cs1Label"] == "src_labels"
    assert json.loads(kv["cs5"]) == {"targets": 12, "occurrences": 1}
    assert kv["dvchost"] == "pce.lab.local"


def test_cef_pce_relays_audit_as_the_pce_but_its_own_events_as_illumio_ops():
    fmt = formatter_for(SiemFormat.CEF_PCE, pce_fqdn="pce.lab.local", pce_version="26.2.20")
    audit = SiemRecord(kind="audit", record_id=1, time=T0, event={
        "event_type": "user.sign_in", "status": "success", "severity": "info", "timestamp": "2026-10-31T03:04:05Z",
        "href": "/orgs/1/events/abc"})
    assert fmt.format_record(audit).startswith("CEF:0|Illumio|PCE|26.2.20|user.sign_in.success|")
    alert = detection(kind="alert", signature="alert.lateral", name="Lateral movement")
    assert fmt.format_record(alert).startswith(f"CEF:0|Illumio|illumio-ops|{__version__}|alert.lateral|")


def test_new_connection_carries_no_counts_or_bytes():
    rec = new_connection()
    for f in SiemFormat:
        line = formatter_for(f).format_record(rec)
        assert not re.search(r"\b(cnt|in|out|num_connections|bytes|dst_dbi|dst_dbo|count)\b[=\":]", line), f
    kv = ext_keys(formatter_for(SiemFormat.CEF).format_record(rec))
    assert kv["act"] == "allowed" and kv["dst"] == "10.0.0.9" and kv["dhost"] == "db01" and kv["dpt"] == "5432"
    assert kv["start"] == str(int(T0.timestamp() * 1000))


def test_json_is_one_flat_object_with_nested_labels_and_no_empty_values():
    out = json.loads(formatter_for(SiemFormat.JSON).format_record(new_connection()))
    assert out["source"] == "illumio-ops" and out["kind"] == "new_connection" and out["id"] == 7
    assert out["time"] == "2026-10-31T03:04:05.123000Z" and out["proto"] == "tcp" and out["decision"] == "allowed"
    assert out["src_labels"] == {"app": "shop", "env": "prod"} and out["dst_host"] == "db01"
    assert "severity" not in out and "facts" not in out and "last_seen" not in out


def test_cef_escapes_what_would_break_a_key_or_the_line():
    rec = detection(summary="a=b c\\d\nnext", name="x|y")
    line = formatter_for(SiemFormat.CEF).format_record(rec)
    assert "\n" not in line and "|x\\|y|" in line
    assert "msg=a\\=b c\\\\d\\nnext" in line


def test_long_facts_are_cut_and_the_cut_is_said():
    rec = detection(facts={"sample_targets": ["host-%04d" % i for i in range(1000)]})
    kv = ext_keys(formatter_for(SiemFormat.CEF).format_record(rec))
    assert len(kv["cs5"].replace("\\=", "=")) <= CS_LIMIT and kv["cs6"] == "true" and kv["cs6Label"] == "facts_truncated"
    assert "cs6" not in ext_keys(formatter_for(SiemFormat.CEF).format_record(detection()))


@pytest.mark.parametrize("fmt", [SiemFormat.SYSLOG_CEF, SiemFormat.SYSLOG_JSON, SiemFormat.SYSLOG_CEF_PCE])
def test_syslog_wraps_own_events_with_the_forwarder_host_and_the_record_time(fmt):
    line = formatter_for(fmt, host="ops-v6").format_record(detection())
    assert line.startswith("<11>1 2026-10-31T03:04:05.123Z ops-v6 illumio-ops - - - ")  # user.err: high


@pytest.mark.parametrize(("fmt", "starts"), [(SiemFormat.CEF, "CEF:0|"), (SiemFormat.CEF_PCE, "CEF:0|"),
                                             (SiemFormat.JSON, "{"), (SiemFormat.SYSLOG_CEF, "<"),
                                             (SiemFormat.SYSLOG_JSON, "<"), (SiemFormat.SYSLOG_CEF_PCE, "<")])
def test_every_format_has_a_formatter(fmt, starts):
    assert formatter_for(fmt).format_record(detection()).startswith(starts)
