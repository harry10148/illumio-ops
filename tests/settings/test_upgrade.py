"""Settings files written by an older v6 load through an in-memory version upgrade."""
import json
import os

import pytest

from illumio_ops.domain.filter import EndpointFilter
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
    assert s.schema_version == SCHEMA_VERSION == 14
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
    assert s.schema_version == SCHEMA_VERSION and len(s.alerts.rules) == 35 and all(r.notify for r in s.alerts.rules)
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
    assert s.schema_version == SCHEMA_VERSION == 14
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
    assert len(s.alerts.rules) == kept + 9 and len(added) == 9 and not any(r.notify for r in added)
    again = validate_settings(upgrade(_v4_dict()))  # already has them: nothing is added twice
    assert len(again.alerts.rules) == 35


def test_v4_at_the_old_rule_limit_still_loads_after_the_anomaly_rules_join():
    """Review: 300 rules (the v4 limit) plus the anomaly rules must not make the file invalid."""
    d = _v4_dict()
    d["alerts"]["rules"] = [r for r in d["alerts"]["rules"] if not str(r.get("pack_key")).startswith("rule_anomaly")]
    template = next(r for r in d["alerts"]["rules"] if r["type"] == "event")
    while len(d["alerts"]["rules"]) < 300:
        d["alerts"]["rules"].append({**template, "id": f"{len(d['alerts']['rules']):032x}", "pack_key": None,
                                       "name": f"r{len(d['alerts']['rules'])}"})
    assert len(validate_settings(upgrade(d)).alerts.rules) == 309


def test_v12_at_the_old_rule_limit_still_loads_after_the_second_batch_joins():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 12
    d["alerts"]["rules"] = [r for r in d["alerts"]["rules"] if r.get("pack_key") not in BATCH2_RULES]
    template = next(r for r in d["alerts"]["rules"] if r["type"] == "event")
    while len(d["alerts"]["rules"]) < 360:
        d["alerts"]["rules"].append({**template, "id": f"{len(d['alerts']['rules']):032x}", "pack_key": None,
                                       "name": f"r{len(d['alerts']['rules'])}"})
    assert len(validate_settings(upgrade(d)).alerts.rules) == 364


def test_v5_file_upgrades_to_v6_with_reports():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 5
    del d["reports"]
    s = validate_settings(upgrade(d))
    assert s.schema_version == SCHEMA_VERSION == 14
    assert s.reports.retention_days == 90


def test_v6_file_upgrades_to_v7_with_rule_thresholds():
    """A file written by P5a (schema 6) has a reports section without rule_thresholds."""
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 6
    del d["reports"]["rule_thresholds"]
    d["reports"]["retention_days"] = 30
    s = validate_settings(upgrade(d))
    assert s.schema_version == SCHEMA_VERSION == 14
    assert s.reports.retention_days == 30 and s.reports.rule_thresholds.unmanaged_connection == 50


@pytest.mark.parametrize("mode", ["full", "alert"])
def test_upgrade_keeps_mode(mode):
    """Lightweight is the default for new installs only (spec §6.4, 2026-10-29): an installed v6 keeps its mode."""
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 7
    d["collection"]["mode"] = mode
    s = validate_settings(upgrade(d))
    assert s.schema_version == SCHEMA_VERSION == 14 and s.collection.mode.value == mode


def test_events_only_becomes_lightweight():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 7
    d["collection"]["mode"] = "events_only"
    assert validate_settings(upgrade(d)).collection.mode.value == "lightweight"


def _v11(*, exclude_public):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 11
    d["lateral"]["detectors"]["exclude_public"] = exclude_public
    for r in d["alerts"]["rules"]:
        r.pop("exclude", None)
    return d


def test_a_v11_file_moves_the_public_exclusion_to_its_lateral_rules():
    # User 2026-10-31: the exclusion is for alerts; what detection left out, every lateral rule now leaves out
    s = validate_settings(upgrade(_v11(exclude_public=True)))
    assert s.schema_version == SCHEMA_VERSION
    lateral = [r for r in s.alerts.rules if r.type == "lateral"]
    assert lateral and all(r.exclude == EndpointFilter(public=True) for r in lateral)
    assert not hasattr(s.lateral.detectors, "exclude_public")


def test_a_v11_file_that_detected_public_ends_alerts_on_them_still():
    s = validate_settings(upgrade(_v11(exclude_public=False)))
    assert all(r.exclude is None for r in s.alerts.rules if r.type == "lateral")


def test_a_lateral_rule_keeps_an_exclusion_it_already_has():
    d = _v11(exclude_public=True)
    rule = next(r for r in d["alerts"]["rules"] if r["type"] == "lateral")
    rule["exclude"] = {"ips": ["10.9.0.0/16"]}
    s = validate_settings(upgrade(d))
    assert next(r for r in s.alerts.rules if r.id == rule["id"]).exclude == EndpointFilter(ips=("10.9.0.0/16",))



BATCH2_DETECTORS = {"quiet_days": 7, "quiet_min_connections": 100, "staging_min_sources": 5, "staging_min_mb": 1024,
                    "off_hours_min_connections": 100, "off_hours_min_days": 5}


def test_v12_settings_gain_batch2_detector_defaults():
    """Spec §6.5.8 第二批: the new thresholds; what the file has stays as it is."""
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 12
    for key in BATCH2_DETECTORS:
        d["lateral"]["detectors"].pop(key, None)
    d["lateral"]["detectors"]["volume_min_connections"] = 4321
    s = validate_settings(upgrade(d))
    assert s.schema_version == SCHEMA_VERSION == 14
    assert {k: getattr(s.lateral.detectors, k) for k in BATCH2_DETECTORS} == BATCH2_DETECTORS
    assert s.lateral.detectors.volume_min_connections == 4321



BATCH2_RULES = {"rule_anomaly_direction", "rule_anomaly_pair_port", "rule_anomaly_quiet", "rule_anomaly_staging"}


def test_v12_settings_gain_batch2_rules_recording_only():
    """An upgraded install records the new anomaly rules and turns each on itself (as the first batch, v4 → v5)."""
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 12
    d["alerts"]["rules"] = [r for r in d["alerts"]["rules"] if r.get("pack_key") not in BATCH2_RULES]
    s = validate_settings(upgrade(d))
    added = [r for r in s.alerts.rules if r.pack_key in BATCH2_RULES]
    assert {r.pack_key for r in added} == BATCH2_RULES and not any(r.notify for r in added)


def test_v12_upgrade_does_not_add_a_rule_twice():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 12
    s = validate_settings(upgrade(d))
    assert sorted(r.pack_key for r in s.alerts.rules if r.pack_key in BATCH2_RULES) == sorted(BATCH2_RULES)


def test_new_installs_notify_on_batch2_rules():
    s = default_settings(password_hash=HASH, secret_key=KEY)
    added = [r for r in s.alerts.rules if r.pack_key in BATCH2_RULES]
    assert {r.pack_key for r in added} == BATCH2_RULES and all(r.notify for r in added)
    assert not any("off_hours" in str(r.pack_key) for r in s.alerts.rules)
    pair = next(r for r in added if r.pack_key == "rule_anomaly_pair_port")
    assert pair.min_severity.value == "medium"



def test_v12_upgrade_does_not_bring_back_a_deleted_first_batch_rule():
    """Codex: the v13 step adds the second batch only; a first-batch rule the operator deleted stays deleted."""
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 12
    d["alerts"]["rules"] = [r for r in d["alerts"]["rules"]
                            if r.get("pack_key") not in BATCH2_RULES | {"rule_anomaly_volume"}]
    s = validate_settings(upgrade(d))
    assert "rule_anomaly_volume" not in {r.pack_key for r in s.alerts.rules}


# ── v13 → v14 (UI redesign spec §9.2): Rule Hit Count is a chapter of the policy usage report, so a schedule for the
# old report becomes one for this: never lost, never doubled, never past the 30 days policy usage reads ──

def _schedule(sid, **over):
    base = {"id": sid * 32, "name": f"schedule {sid}", "enabled": True, "report_type": "rule_hit_count",
            "lookback_days": 90, "frequency": "weekly", "day_of_week": 0, "day_of_month": None, "hour": 8,
            "minute": 0, "formats": ["html", "xlsx"], "email": False, "recipients": [], "lang": None, "keep": 30,
            "filter": None, "custom_id": None}
    return base | over


def _v13(*schedules):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 13
    d["reports"]["schedules"] = list(schedules)
    return d


def _schedules(d):
    return [(s["id"][0], s["report_type"], s["lookback_days"]) for s in upgrade(d)["reports"]["schedules"]]


def test_a_rule_hit_count_schedule_becomes_a_policy_usage_one_of_at_most_30_days():
    d = _v13(_schedule("a"), _schedule("b", lookback_days=7), _schedule("c", report_type="traffic", lookback_days=90))
    assert _schedules(d) == [("a", "policy_usage", 30), ("b", "policy_usage", 7), ("c", "traffic", 90)]
    out = upgrade(d)
    assert out["schema_version"] == SCHEMA_VERSION
    kept = {k: v for k, v in out["reports"]["schedules"][0].items() if k not in ("report_type", "lookback_days")}
    assert kept == {k: v for k, v in _schedule("a").items() if k not in ("report_type", "lookback_days")}
    s = validate_settings(d)  # the whole upgraded file is a valid one
    assert [x.report_type.value for x in s.reports.schedules] == ["policy_usage", "policy_usage", "traffic"]
    assert d == _v13(_schedule("a"), _schedule("b", lookback_days=7),
                     _schedule("c", report_type="traffic", lookback_days=90))  # the caller's data is not changed


def test_the_upgraded_schedule_is_one_the_policy_usage_report_takes():
    """The step writes 30 itself (a settings step imports no service): it must be within what the report reads."""
    from illumio_ops.services.reports.generate import refusal
    from illumio_ops.services.reports.schedules import params_of
    s = validate_settings(_v13(_schedule("a"), _schedule("b", lookback_days=7)))
    assert [refusal(s, params_of(x)) for x in s.reports.schedules] == [None, None]


def test_a_schedule_the_same_as_another_after_the_change_is_kept_once():
    """Except for id and name: the one with the smaller id stays, whichever of the two it is."""
    usage = _schedule("b", report_type="policy_usage", lookback_days=30, name="Policy usage weekly")
    assert _schedules(_v13(_schedule("c"), usage)) == [("b", "policy_usage", 30)]
    assert _schedules(_v13(_schedule("a"), usage)) == [("a", "policy_usage", 30)]
    assert _schedules(_v13(_schedule("a"), _schedule("b"))) == [("a", "policy_usage", 30)]  # two of the old type
    # different in anything else: both stay
    assert _schedules(_v13(_schedule("c"), usage | {"hour": 9})) == [("c", "policy_usage", 30), ("b", "policy_usage", 30)]
    assert _schedules(_v13(_schedule("c", lookback_days=7), usage)) == [("c", "policy_usage", 7), ("b", "policy_usage", 30)]


def test_two_schedules_that_were_already_the_same_are_left_alone():
    """Only a schedule this step changed is compared: what the operator had twice, the operator still has twice."""
    twice = [_schedule("a", report_type="traffic"), _schedule("b", report_type="traffic")]
    assert _schedules(_v13(*twice)) == [("a", "traffic", 90), ("b", "traffic", 90)]
    assert _schedules(_v13(*twice, _schedule("c"))) == [("a", "traffic", 90), ("b", "traffic", 90),
                                                        ("c", "policy_usage", 30)]


def test_a_file_without_such_a_schedule_is_unchanged_but_for_its_version():
    d = _v13(_schedule("a", report_type="traffic"), _schedule("b", report_type="policy_usage", lookback_days=30))
    out = upgrade(d)
    assert out == d | {"schema_version": SCHEMA_VERSION}
    assert upgrade(_v13()) == _v13() | {"schema_version": SCHEMA_VERSION}


def test_running_the_step_again_on_its_own_output_changes_nothing():
    from illumio_ops.settings.upgrade import UPGRADES
    d = _v13(_schedule("c"), _schedule("b", report_type="policy_usage", lookback_days=30), _schedule("a", lookback_days=7),
             _schedule("d", report_type="traffic"))
    once = UPGRADES[13](json.loads(json.dumps(d)))
    twice = UPGRADES[13](json.loads(json.dumps(once)))
    assert once == twice and upgrade(upgrade(d)) == upgrade(d)
    assert [(s["id"][0], s["report_type"]) for s in once["reports"]["schedules"]] == [
        ("b", "policy_usage"), ("a", "policy_usage"), ("d", "traffic")]


def test_the_step_says_which_schedules_it_changed():
    from illumio_ops.settings.upgrade import ScheduleChange, rhc_schedule_changes
    usage = _schedule("b", report_type="policy_usage", lookback_days=30, name="Policy usage weekly")
    d = _v13(_schedule("c"), usage, _schedule("a", lookback_days=7), _schedule("d", report_type="traffic"))
    assert rhc_schedule_changes(d) == [
        ScheduleChange(id="c" * 32, name="schedule c", converted=True, lookback_before=90, lookback_after=30,
                       same_as=("b" * 32, "Policy usage weekly")),
        ScheduleChange(id="a" * 32, name="schedule a", converted=True, lookback_before=7, lookback_after=7,
                       same_as=None)]
    # a schedule of another type removed because the changed one has the smaller id is named too
    assert rhc_schedule_changes(_v13(_schedule("a"), usage)) == [
        ScheduleChange(id="a" * 32, name="schedule a", converted=True, lookback_before=90, lookback_after=30,
                       same_as=None),
        ScheduleChange(id="b" * 32, name="Policy usage weekly", converted=False, lookback_before=30,
                       lookback_after=30, same_as=("a" * 32, "schedule a"))]
    assert rhc_schedule_changes(_v13(_schedule("d", report_type="traffic"))) == []
    assert rhc_schedule_changes(upgrade(d)) == []  # a file at the current schema: nothing left to change
    assert rhc_schedule_changes(["not", "a", "dict"]) == [] and rhc_schedule_changes({"schema_version": 13}) == []


def test_the_step_neither_logs_nor_writes(tmp_path):
    """upgrade() runs on every load, in memory (the service, rescue, the installer's check): saying what it changed
    is the service start's, once (SettingsStore.persist_upgrade)."""
    from loguru import logger
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(_v13(_schedule("a"))))
    before, mtime = p.read_bytes(), os.stat(p).st_mtime_ns
    said: list[str] = []
    sink = logger.add(said.append, level="DEBUG")
    try:
        s = SettingsStore(p).load()
        upgrade(_v13(_schedule("a")))
    finally:
        logger.remove(sink)
    assert s.reports.schedules[0].report_type.value == "policy_usage"
    assert said == [] and p.read_bytes() == before and os.stat(p).st_mtime_ns == mtime


def _file(tmp_path, d):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(d, indent=2))
    p.chmod(0o600)
    return p


def test_the_service_start_writes_the_changed_schedules_back_once(tmp_path):
    p = _file(tmp_path, _v13(_schedule("a"), _schedule("b", report_type="traffic")))
    store = SettingsStore(p)
    s = store.load()
    changes = store.persist_upgrade()
    assert [(c.id[0], c.lookback_before, c.lookback_after) for c in changes] == [("a", 90, 30)]
    on_disk = json.loads(p.read_text())
    assert on_disk["schema_version"] == SCHEMA_VERSION and on_disk["revision"] == s.revision
    assert [(x["report_type"], x["lookback_days"]) for x in on_disk["reports"]["schedules"]] == [
        ("policy_usage", 30), ("traffic", 90)]
    assert os.stat(p).st_mode & 0o777 == 0o600
    assert store.persist_upgrade() == []  # said once
    again = SettingsStore(p)
    again.load()
    assert again.persist_upgrade() == []  # and not at the next start: the file holds it now
    # the next change from the pages is no conflict with the file just written
    new = store.update(s.revision, lambda d: d["display"].__setitem__("language", "zh_TW"))
    assert new.revision == s.revision + 1


def test_the_service_start_leaves_a_file_without_such_a_schedule_as_it_was(tmp_path):
    """An older file with nothing of the operator's changed keeps reaching disk on the next change, as before."""
    for d in (_v13(_schedule("b", report_type="traffic")), _v13()):
        p = _file(tmp_path, d)
        before, mtime = p.read_bytes(), os.stat(p).st_mtime_ns
        store = SettingsStore(p)
        store.load()
        assert store.persist_upgrade() == []
        assert p.read_bytes() == before and os.stat(p).st_mtime_ns == mtime


def test_a_file_changed_by_hand_since_it_was_read_is_not_overwritten(tmp_path):
    p = _file(tmp_path, _v13(_schedule("a")))
    store = SettingsStore(p)
    store.load()
    edited = json.dumps(_v13(_schedule("a", name="renamed by hand")))
    p.write_text(edited)
    assert store.persist_upgrade() == [] and p.read_text() == edited


def _said(run):
    from loguru import logger
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        run()
    finally:
        logger.remove(sink)
    return lines


def test_what_was_changed_is_logged_where_the_file_is_written_and_only_there(tmp_path):
    usage = _schedule("a", report_type="policy_usage", lookback_days=30, name="Usage weekly")
    p = _file(tmp_path, _v13(_schedule("b", name="Hits\nweekly {x}"), usage, _schedule("c", lookback_days=7)))
    store = SettingsStore(p)
    assert _said(store.load) == []
    lines = _said(store.persist_upgrade)
    assert len(lines) == 2 and _said(store.persist_upgrade) == []
    removed, kept = lines
    # the name is printed escaped (one schedule, one line), with what happened to it and to its reports
    assert "'Hits\\nweekly {x}'" in removed and "\n" not in removed and "b" * 32 in removed
    assert "lookback 90 -> 30 days" in removed and "'Usage weekly'" in removed and "removed" in removed
    assert "reports it made are kept" in removed
    assert "'schedule c'" in kept and "lookback 7 -> 7 days" in kept and "removed" not in kept


def test_a_change_from_the_pages_before_any_start_writes_and_says_it_too(tmp_path):
    """The rescue command, or a save from the pages of a service that could not write the file at its start: the
    first write of the upgraded file is where it is said, whichever write that is — and then never again."""
    p = _file(tmp_path, _v13(_schedule("a")))
    store = SettingsStore(p)
    s = store.load()
    lines = _said(lambda: store.update(s.revision, lambda d: d["display"].__setitem__("language", "zh_TW")))
    assert len(lines) == 1 and "'schedule a'" in lines[0] and "lookback 90 -> 30 days" in lines[0]
    assert json.loads(p.read_text())["reports"]["schedules"][0]["report_type"] == "policy_usage"
    assert _said(store.persist_upgrade) == []
    assert _said(lambda: store.update(s.revision + 1, lambda d: d["display"].__setitem__("language", "en"))) == []


def test_a_file_that_cannot_be_written_back_does_not_stop_the_start(tmp_path, monkeypatch):
    from illumio_ops.runtime import write_back_settings_upgrade
    p = _file(tmp_path, _v13(_schedule("a")))
    store = SettingsStore(p)
    store.load()
    before = p.read_bytes()

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(store, "_write", full)
    lines = _said(lambda: write_back_settings_upgrade(store))
    assert len(lines) == 1 and "could not be written back" in lines[0] and "No space left" in lines[0]
    assert p.read_bytes() == before and store.current().reports.schedules[0].report_type.value == "policy_usage"
    monkeypatch.undo()
    assert len(_said(lambda: write_back_settings_upgrade(store))) == 1  # tried again, written and said
