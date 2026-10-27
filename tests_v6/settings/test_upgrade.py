"""Settings files written by an older v6 load through an in-memory version upgrade."""
import json
import os

import pytest

from illumio_ops.settings.schema import SCHEMA_VERSION, default_settings
from illumio_ops.settings.store import SettingsInvalid, SettingsStore, validate_settings
from illumio_ops.settings.upgrade import upgrade

from .conftest import HASH, KEY


def _v1(tmp_path):
    """A settings file exactly as P1 (schema 1) wrote it: no collection section."""
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 1
    del d["collection"]
    del d["lateral"]
    del d["alerts"]
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(d, indent=2))
    p.chmod(0o600)
    return p


def _locs(e):
    return [loc for loc, _ in e.value.errors]


def test_v1_file_loads_as_v2_in_memory(tmp_path):
    p = _v1(tmp_path)
    before, mtime = p.read_bytes(), os.stat(p).st_mtime_ns
    s = SettingsStore(p).load()
    assert s.schema_version == SCHEMA_VERSION == 6
    assert s.collection.traffic_interval_seconds == 600
    assert s.collection.retention.baseline_days == 30
    assert p.read_bytes() == before and os.stat(p).st_mtime_ns == mtime


def test_invalid_v1_file_still_writes_nothing(tmp_path):
    p = _v1(tmp_path)
    d = json.loads(p.read_text())
    d["web"]["bogus"] = 1
    p.write_text(json.dumps(d))
    before = p.read_bytes()
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(p).load()
    assert "web.bogus" in _locs(e)
    assert p.read_bytes() == before


def test_first_update_after_upgrade_writes_current_version_without_conflict(tmp_path):
    p = _v1(tmp_path)
    store = SettingsStore(p)
    s = store.load()
    new = store.update(s.revision, lambda d: d["display"].__setitem__("language", "zh_TW"))
    on_disk = json.loads(p.read_text())
    assert on_disk["schema_version"] == SCHEMA_VERSION
    assert on_disk["collection"]["traffic_interval_seconds"] == 600
    assert on_disk["lateral"]["graph_hops"] == 3
    assert new.revision == s.revision + 1


def test_newer_schema_version_is_refused(tmp_path):
    p = _v1(tmp_path)
    d = json.loads(p.read_text())
    d["schema_version"] = SCHEMA_VERSION + 1
    p.write_text(json.dumps(d))
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(p).load()
    assert "schema_version" in _locs(e)


def test_upgrade_leaves_current_version_untouched():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    assert upgrade(d) == d


def test_upgrade_passes_non_dict_through_to_validation():
    with pytest.raises(SettingsInvalid):
        validate_settings(["not", "a", "dict"])


def _v2(tmp_path):
    """A settings file exactly as P2 (schema 2) wrote it: no lateral section."""
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 2
    del d["lateral"]
    del d["alerts"]
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(d, indent=2))
    p.chmod(0o600)
    return p


def test_v2_file_loads_as_current_with_default_lateral(tmp_path):
    p = _v2(tmp_path)
    before, mtime = p.read_bytes(), os.stat(p).st_mtime_ns
    s = SettingsStore(p).load()
    assert s.schema_version == SCHEMA_VERSION
    assert s.lateral.graph_hops == 3 and s.lateral.observation_days == 30
    assert s.lateral.detectors.fanout_targets == 10
    assert p.read_bytes() == before and os.stat(p).st_mtime_ns == mtime


def test_v3_file_upgrades_to_v4_with_pack(tmp_path):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 3
    del d["alerts"]
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(d))
    p.chmod(0o600)
    s = SettingsStore(p).load()
    assert s.schema_version == SCHEMA_VERSION and len(s.alerts.rules) == 30 and all(r.notify for r in s.alerts.rules)
    assert not s.alerts.channels.smtp.enabled


def _v4_dict():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 4
    lat = d["lateral"]
    for k in ("peer_group_keys", "directory_servers", "directory_server_ips", "suspicious_tools"):
        del lat[k]
    for k in ("peer_min_group", "volume_surge_factor", "volume_min_connections", "volume_min_mb",
              "directory_min_connections", "account_history_days", "process_history_days", "directory_min_sources",
              "directory_followup_minutes"):
        del lat["detectors"][k]
    lat["extra_admin_ports"] = [{"port": 8443, "proto": 6}]
    lat["removed_admin_ports"] = [{"port": 23, "proto": None}]
    lat["detectors"]["fanout_targets"] = 12
    return d


def test_v4_file_upgrades_to_v5_keeping_values():
    s = validate_settings(upgrade(_v4_dict()))
    assert s.schema_version == SCHEMA_VERSION == 6
    lat = s.lateral
    assert lat.detectors.fanout_targets == 12
    assert lat.extra_admin_ports[0].category == "remote" and lat.removed_admin_ports[0].port == 23
    assert lat.peer_group_keys == ("app", "role")
    assert lat.detectors.directory_min_sources == 3 and lat.detectors.peer_min_group == 5
    assert "psexec.exe" in lat.suspicious_tools and lat.directory_server_ips == ()


def test_v4_upgrade_adds_anomaly_rules_record_only():
    """An install upgraded to v5 gets the anomaly rules recording only; the operator turns each on (P4.5)."""
    d = _v4_dict()
    d["alerts"]["rules"] = [r for r in d["alerts"]["rules"] if not str(r.get("pack_key")).startswith("rule_anomaly")]
    kept = len(d["alerts"]["rules"])
    s = validate_settings(upgrade(d))
    added = [r for r in s.alerts.rules if r.pack_key.startswith("rule_anomaly")]
    assert len(s.alerts.rules) == kept + 5 and len(added) == 5 and not any(r.notify for r in added)
    again = validate_settings(upgrade(_v4_dict()))  # already has them: nothing is added twice
    assert len(again.alerts.rules) == 30


def test_v4_at_the_old_rule_limit_still_loads_after_the_anomaly_rules_join():
    """Review: 300 rules (the v4 limit) plus the five anomaly rules must not make the file invalid."""
    d = _v4_dict()
    d["alerts"]["rules"] = [r for r in d["alerts"]["rules"] if not str(r.get("pack_key")).startswith("rule_anomaly")]
    template = next(r for r in d["alerts"]["rules"] if r["type"] == "event")
    while len(d["alerts"]["rules"]) < 300:
        d["alerts"]["rules"].append({**template, "id": f"{len(d['alerts']['rules']):032x}", "pack_key": None,
                                       "name": f"r{len(d['alerts']['rules'])}"})
    assert len(validate_settings(upgrade(d)).alerts.rules) == 305


def test_v5_file_upgrades_to_v6_with_reports():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 5
    del d["reports"]
    s = validate_settings(upgrade(d))
    assert s.schema_version == SCHEMA_VERSION == 6
    assert s.reports.retention_days == 90
