"""5.x SIEM forwarding → v6 (P7 Task 8): .106's real shape, the v5.0.0 shape, legacy endpoint, traffic → new
connections, a destination v6 would refuse carried off, the HEC token carried but never in the report."""
import json
from pathlib import Path

from illumio_ops.domain.values import CollectionMode
from illumio_ops.migrate.report import render
from illumio_ops.migrate.v5 import migrate_v5
from illumio_ops.migrate.v5_siem import migrate_siem

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def by_source(items):
    out = {}
    for i in items:
        out.setdefault(i.source, []).append(i)
    return out


def test_the_106_destination_carries_with_traffic_as_new_connections():
    r = migrate_v5(_load("v5_2_x_config_106_redacted.json"))
    assert r.settings is not None
    s = r.settings.siem
    [d] = s.destinations
    assert s.enabled and s.tick_seconds == 10 and s.dlq_max_per_dest == 10_000 and s.backlog_warn_rows == 50_000
    assert d.transport.value == "tcp" and d.format.value == "cef_pce" and d.host == "192.0.2.1" and d.port == 5514
    assert [x.value for x in d.sources] == ["audit", "new_connections"] and d.verify_tls is True
    items = by_source(r.report.items)
    assert items["siem.destinations[0].source_types.traffic"][0].reason_key == "migrate_siem_traffic_to_new_connections"
    assert items["siem.dispatch_tick_seconds"][0].reason_key == "migrate_raised_to_minimum"  # 5.x ran every 5 s
    assert items["pce_cache.siem_pending_warn_rows"][0].target == "siem.backlog_warn_rows"
    assert not [i for i in r.report.items if i.reason_key == "migrate_arrives_in_phase"]


def test_the_v5_0_0_shape_forwards_nothing():
    r = migrate_v5(_load("v5_0_0_config.json"))
    assert r.settings is not None and not r.settings.siem.enabled and r.settings.siem.destinations == ()


def test_lightweight_installs_are_told_new_connections_need_alert_mode():
    raw = {"siem": {"enabled": True, "destinations": [{"name": "g", "host": "h", "port": 514}]}}
    _, items = migrate_siem(raw, mode=CollectionMode.LIGHTWEIGHT)
    assert any(i.reason_key == "migrate_siem_needs_alert_mode" for i in items)
    _, full = migrate_siem(raw, mode=CollectionMode.FULL)
    assert not any(i.reason_key == "migrate_siem_needs_alert_mode" for i in full)


def test_legacy_endpoint_and_hec_url():
    raw = {"siem": {"destinations": [
        {"name": "a", "transport": "tcp", "endpoint": "siem.example:6514", "source_types": ["audit"]},
        {"name": "b", "transport": "hec", "endpoint": "https://splunk.example:8089/x", "hec_token": "T",
         "source_types": ["audit"]}]}}
    out, _ = migrate_siem(raw, mode=CollectionMode.FULL)
    assert [(d["host"], d["port"]) for d in out["destinations"]] == [("siem.example", 6514), ("splunk.example", 8089)]


def test_a_destination_v6_would_refuse_is_carried_off_not_dropped():
    raw = {"siem": {"enabled": True, "destinations": [{"name": "h", "transport": "hec", "host": "s", "port": 8088}]}}
    out, items = migrate_siem(raw, mode=CollectionMode.FULL)
    [d] = out["destinations"]
    assert d["enabled"] is False
    assert any(i.reason_key == "migrate_siem_paused_incomplete" for i in items)


def test_dev_profile_without_verification_stays_unverified_and_profile_is_reported():
    raw = {"siem": {"destinations": [{"name": "t", "transport": "tls", "host": "s", "port": 6514, "profile": "dev",
                                      "tls_verify": False, "source_types": ["audit"]}]}}
    out, items = migrate_siem(raw, mode=CollectionMode.FULL)
    assert out["destinations"][0]["verify_tls"] is False
    reasons = {i.reason_key for i in items}
    assert {"migrate_siem_profile_dropped", "migrate_siem_tls_unverified"} <= reasons


def test_traffic_pd_follows_traffic_and_zero_retries_is_raised():
    raw = {"siem": {"destinations": [{"name": "t", "host": "s", "source_types": ["audit", "traffic"],
                                      "traffic_pd": ["blocked", "potentially_blocked"], "max_retries": 0}]}}
    out, items = migrate_siem(raw, mode=CollectionMode.FULL)
    d = out["destinations"][0]
    assert d["new_connection_decisions"] == ["blocked", "potentially_blocked"] and d["max_retries"] == 1
    assert any(i.reason_key == "migrate_siem_retries_raised" for i in items)


def test_duplicate_names_are_renamed_and_the_token_never_reaches_the_report():
    raw = {"siem": {"destinations": [
        {"name": "s", "transport": "hec", "host": "a", "port": 8088, "hec_token": "TOKEN-VALUE-1"},
        {"name": "s", "transport": "hec", "host": "b", "port": 8088, "hec_token": "TOKEN-VALUE-2"}]}}
    r = migrate_v5({**_load("v5_0_0_config.json"), **raw})
    assert r.settings is not None
    assert [d.name for d in r.settings.siem.destinations] == ["s", "s (2)"]
    assert r.settings.siem.destinations[1].hec_token == "TOKEN-VALUE-2"
    from illumio_ops.domain.values import Language
    text = render(r.report, Language.EN) + render(r.report, Language.ZH_TW)
    assert "TOKEN-VALUE" not in text and "siem.destinations[1].name" in text
