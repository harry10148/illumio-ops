"""5.x alert rules, channels and SMTP → v6 (spec §7), against .106's 19 rules and the 5.0.0 shapes."""
import json
from pathlib import Path

from illumio_ops.domain.alertpack import pack_rule_id
from illumio_ops.domain.values import Language
from illumio_ops.migrate.report import render
from illumio_ops.migrate.v5 import migrate_v5
from illumio_ops.migrate.v5_alerts import migrate_alerts, read_v5_rules

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _106():
    return _load("v5_2_x_config_106_redacted.json"), _load("v5_106_alerts.json")["rules"]


def _items(items, prefix):
    return [i for i in items if i.source.startswith(prefix)]


def test_106_rules_all_accounted():
    raw, rules = _106()
    section, items = migrate_alerts(raw, rules, None)
    for i, rule in enumerate(rules):
        assert _items(items, f"alerts.json rules[{i}] "), (i, rule.get("name_key"))
    by_pack = {r["pack_key"]: r for r in section["rules"] if r["pack_key"]}
    events = [r for r in rules if r["type"] == "event"]
    # .106 fact: 15 event rules are the 5.x pack; the offline one was renamed in the GUI and lost its name_key.
    packed = [r for r in events if r.get("name_key")]
    assert len(events) == 16 and len(packed) == 15 and all(by_pack[r["name_key"]]["type"] == "event" for r in packed)
    [renamed] = [r for r in section["rules"] if r["name"] == "Agent 離線"]
    assert renamed["pack_key"] is None and renamed["event_types"] == ["system_task.agent_offline_check"]
    assert by_pack["rule_agent_tampering"]["id"] == pack_rule_id("rule_agent_tampering")


def test_106_traffic_rule_to_blocked_condition():
    raw, rules = _106()
    section, _ = migrate_alerts(raw, rules, None)
    [t] = [r for r in section["rules"] if r["type"] == "traffic"]
    assert t["condition"] == {"decisions": ["blocked"]} and t["threshold_connections"] == 25
    assert (t["window_minutes"], t["cooldown_minutes"], t["throttle"]) == (10, 30, {"count": 1, "period_minutes": 15})
    assert t["name"] == "高 Blocked 流量" and t["pack_key"] is None and t["enabled"]


def test_bandwidth_pd_minus_one_means_all():
    raw, rules = _106()
    section, _ = migrate_alerts(raw, rules, None)
    [b] = [r for r in section["rules"] if r["type"] == "bandwidth"]
    assert b["condition"] == {} and b["threshold_mbps"] == 999999.0 and b["enabled"] is False
    assert b["window_minutes"] == 60


def test_system_threshold_keys_dropped():
    raw, rules = _106()
    section, items = migrate_alerts(raw, rules, None)
    [s] = [r for r in section["rules"] if r["type"] == "system" and r["name"]]
    assert s["check"] == "pce_health" and s["enabled"] is False
    i = rules.index(next(r for r in rules if r["type"] == "system"))
    dropped = {it.source.split(" · ")[-1] for it in _items(items, f"alerts.json rules[{i}] ") if it.action == "dropped"}
    assert {"threshold_type", "threshold_count", "threshold_window", "match_fields"} <= dropped


def test_integer_ids_rewritten():
    raw, rules = _106()
    section, items = migrate_alerts(raw, rules, None)
    assert all(len(r["id"]) == 32 for r in section["rules"])
    assert any(i.reason_key == "migrate_rule_new_id" for i in items)


def rule(**kw):
    return {"type": "event", "name": "r", "filter_value": "agent.suspend"} | kw


def test_cooldown_defaults_to_window():
    section, _ = migrate_alerts({}, [rule(threshold_window=20)], None)
    assert section["rules"][0]["cooldown_minutes"] == 20


def test_threshold_alias():
    section, items = migrate_alerts({}, [rule(threshold_type="count", threshold=4)], None)
    assert section["rules"][0]["threshold_count"] == 4
    assert any(i.reason_key == "migrate_rule_threshold_alias" for i in items)


def test_throttle_dict_and_string():
    section, items = migrate_alerts({}, [rule(throttle="2/1h"), rule(alert_throttle={"count": 3, "period_seconds": 900}),
                                         rule(throttle="1/30d")], None)
    t = [r["throttle"] for r in section["rules"][:3]]
    assert t == [{"count": 2, "period_minutes": 60}, {"count": 3, "period_minutes": 15},
                 {"count": 1, "period_minutes": 10080}]
    assert any(i.reason_key == "migrate_rule_throttle_capped" for i in items)


def test_legacy_scalar_and_filterbar_keys():
    r = {"type": "traffic", "name": "x", "pd": 1, "src_label": "env:Prod", "dst_labels": ["app=Fin", "app=HR", "role=DB"],
         "src_ip_in": "10.0.0.1-10.0.0.6", "port": 22, "proto": 6, "ex_ports": ["135-139"], "threshold_count": 5,
         "threshold_window": 5}
    section, items = migrate_alerts({}, [r], None)
    c = section["rules"][0]["condition"]
    assert c["decisions"] == ["potentially_blocked"]
    assert c["src"]["labels"] == [{"key": "env", "values": ["Prod"]}]
    assert c["src"]["ips"] == ["10.0.0.1/32", "10.0.0.2/31", "10.0.0.4/31", "10.0.0.6/32"]
    assert c["dst"]["labels"] == [{"key": "app", "values": ["Fin", "HR"]}, {"key": "role", "values": ["DB"]}]
    assert c["ports"] == [{"port": 22, "proto": 6}] and c["exclude_ports"] == [{"port": 135, "to_port": 139}]
    assert section["rules"][0]["window_minutes"] == 10
    assert any(i.reason_key == "migrate_rule_window_raised" for i in items)


def test_unsupported_filterbar_key_disables_rule():
    r = {"type": "traffic", "name": "x", "pd": 2, "src_iplists": ["Corp"], "any_label": "env=Prod"}
    section, items = migrate_alerts({}, [r], None)
    assert section["rules"][0]["enabled"] is False
    lost = {i.source.split(" · ")[-1] for i in items if i.reason_key == "migrate_rule_filter_unsupported"}
    assert lost == {"src_iplists", "any_label"}


def test_invalid_regex_rule_disabled_not_blocking():
    section, items = migrate_alerts({}, [rule(filter_value="agent.(x"), rule(name="ok")], None)
    bad, ok = section["rules"][:2]
    assert bad["enabled"] is False and bad["event_types"] == ["*"] and ok["enabled"] is True
    assert any(i.reason_key == "migrate_rule_invalid" for i in items)


def test_old_alerts_json_channel_shape(tmp_path):
    (tmp_path / "config").mkdir()
    legacy = {"active": ["line"], "line_token": "T", "line_target_id": "U1"}
    (tmp_path / "config" / "alerts.json").write_text(json.dumps(legacy))
    rules, channels = read_v5_rules(tmp_path)
    assert rules is None and channels == legacy
    raw = {"rules": [rule()], "alerts": {"active": []}}
    section, items = migrate_alerts(raw, rules, channels)
    assert section["channels"]["line"] == {"enabled": True, "access_token": "T", "target_id": "U1"}
    assert len([r for r in section["rules"] if r["name"] == "r"]) == 1  # from config.json "rules"
    assert any(i.source == "alerts.json.line_token" and i.reason_key == "migrate_alias_key" for i in items)


def test_active_list_enables_channels():
    raw = {"alerts": {"active": ["mail", "webhook"], "webhook_url": "https://hook.example/x"},
           "email": {"sender": "ops@example.com", "recipients": ["sec@example.com"]},
           "smtp": {"host": "mail", "port": 587, "user": "ops", "password": "pw", "enable_auth": True, "enable_tls": True}}
    section, items = migrate_alerts(raw, [], None)
    ch = section["channels"]
    assert ch["smtp"]["enabled"] and ch["smtp"]["security"] == "starttls" and ch["smtp"]["username"] == "ops"
    assert ch["webhook"]["enabled"] and not ch["line"]["enabled"]
    assert any(i.source == "ILLUMIO_SMTP_PASSWORD" for i in items)


def test_incomplete_channel_disabled():
    raw = {"alerts": {"active": ["line", "teams"], "line_channel_access_token": "T", "teams_webhook_url": "http://x/y"}}
    section, items = migrate_alerts(raw, [], None)
    assert not section["channels"]["line"]["enabled"] and not section["channels"]["teams"]["enabled"]
    assert section["channels"]["teams"]["webhook_url"] == ""
    assert {i.reason_key for i in items} >= {"migrate_channel_incomplete", "migrate_channel_invalid"}


def test_new_lateral_defaults_not_notified():
    section, items = migrate_alerts({}, [], None)
    lateral = [r for r in section["rules"] if r["type"] == "lateral"]
    assert len(lateral) == 3 and not any(r["notify"] for r in lateral)
    assert all(r["notify"] for r in section["rules"] if r["type"] == "system")
    assert sum(i.reason_key == "migrate_new_default_quiet" for i in items) == 3


def test_report_never_contains_secret_values():
    raw, rules = _106()
    raw["smtp"]["password"] = "SECRET-smtp-1"
    raw["alerts"]["line_channel_access_token"] = "SECRET-line-2"
    raw["alerts"]["webhook_url"] = "https://hook.example/SECRET-path-3"
    result = migrate_v5(raw, rules=rules)
    for lang in Language:
        text = render(result.report, lang)
        assert "SECRET" not in text


def test_whole_106_migration_validates():
    raw, rules = _106()
    result = migrate_v5(raw, rules=rules)
    assert result.blocking == [] and result.settings is not None
    s = result.settings.alerts
    assert len([r for r in s.rules if r.type == "event"]) == 16 and s.channels.line.enabled
