import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from illumio_ops.domain.values import Language
from illumio_ops.migrate.report import render
from illumio_ops.migrate.v5 import leaf_keys, migrate_v5, read_v5
from illumio_ops.settings.secrets import verify_password

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]
FIXTURE_NAMES = ("v5_0_0_config.json", "v5_2_x_config_106_redacted.json")


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_report_covers_every_input_leaf_key(name):
    raw = _load(name)
    report = migrate_v5(raw).report
    sources = [i.source for i in report.items]
    assert sorted(sources) == sorted(leaf_keys(raw))
    assert len(sources) == len(set(sources))


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_migrated_settings_validate(name):
    raw = _load(name)
    s = migrate_v5(raw).settings
    assert s.pce.url == raw["api"]["url"].rstrip("/")
    assert s.web.tls.mode == "self_signed" and s.web.tls.validity_days == raw["web_gui"]["tls"]["validity_days"]
    assert s.display.language is Language(raw["settings"]["language"])
    assert s.display.timezone == raw["settings"]["timezone"]
    assert s.logging.level == raw["logging"]["level"]


def test_argon2_hash_carried_verbatim():
    raw = _load("v5_0_0_config.json")
    result = migrate_v5(raw)
    s, report = result.settings, result.report
    assert s.web.password_hash == raw["web_gui"]["password"]
    item = next(i for i in report.items if i.source == "web_gui.password")
    assert (item.target, item.action) == ("web.password_hash", "carried")


def test_plaintext_password_is_hashed_and_marked_rewritten():
    raw = _load("v5_0_0_config.json")
    raw["web_gui"]["password"] = "legacy-plain-pass"
    result = migrate_v5(raw)
    s, report = result.settings, result.report
    assert verify_password("legacy-plain-pass", s.web.password_hash)
    item = next(i for i in report.items if i.source == "web_gui.password")
    assert item.action == "rewritten" and item.reason_key == "migrate_password_hashed"


def test_empty_password_becomes_the_5x_default():
    raw = _load("v5_0_0_config.json")
    raw["web_gui"]["password"] = ""
    result = migrate_v5(raw)
    s, report = result.settings, result.report
    assert verify_password("illumio", s.web.password_hash)
    assert next(i for i in report.items if i.source == "web_gui.password").reason_key == "migrate_password_default"


def test_deprecated_keys_dropped_with_reason():
    raw = _load("v5_0_0_config.json")
    raw["report"]["attack_surface"] = {"enabled": True}
    raw["web_gui"]["tls"]["http_redirect_port"] = 80
    raw["pce_profiles"] = [{"name": "x"}]
    raw["active_pce_id"] = 1
    raw["pce_cache"]["archive_review_max_days"] = 7
    report = migrate_v5(raw).report
    dep = {i.source: i for i in report.items if i.reason_key == "migrate_deprecated_in_5x"}
    assert set(dep) >= {"report.attack_surface.enabled", "web_gui.tls.http_redirect_port", "pce_profiles",
                        "active_pce_id", "pce_cache.archive_review_max_days"}
    assert all(i.action == "dropped" for i in dep.values())


def test_phase_labels_follow_revised_roadmap():
    report = migrate_v5(_load("v5_2_x_config_106_redacted.json")).report
    by_source = {i.source: i for i in report.items}
    assert by_source["smtp.host"].params == {"phase": "P4"} and by_source["smtp.host"].action == "unsupported"
    assert by_source["siem.enabled"].params == {"phase": "P7"}
    assert by_source["report_schedules"].params == {"phase": "P5"}
    assert by_source["pce_cache.siem_pending_warn_rows"].params == {"phase": "P7"}
    assert by_source["settings.theme"].reason_key == "migrate_not_in_v6"
    assert by_source["api.profile"].action == "dropped"
    raw = _base()
    raw["web_gui"]["public_url"] = "https://ops.example.com"
    item = next(i for i in migrate_v5(raw).report.items if i.source == "web_gui.public_url")
    assert item.params == {"phase": "P5"}
    assert not any(i.params.get("phase") in ("P2", "P3") for i in report.items)


def _with_cache(**values):
    raw = _base()
    raw["pce_cache"] = dict(values)
    return raw


def _cache_item(result, source):
    return next(i for i in result.report.items if i.source == source)


def test_pce_cache_carried_and_rewritten():
    r = migrate_v5(_with_cache(enabled=True, traffic_poll_interval_seconds=3600, events_poll_interval_seconds=20 * 60,
                               rate_limit_per_minute=300, events_retention_days=120, disk_free_warn_gb=25))
    c = r.settings.collection
    assert (c.enabled, c.traffic_interval_seconds, c.events_interval_seconds, c.rate_limit_per_minute) == (
        True, 600, 1200, 300)
    assert (c.retention.event_days, c.disk_free_warn_gb) == (120, 25)
    item = _cache_item(r, "pce_cache.traffic_poll_interval_seconds")
    assert (item.target, item.action, item.reason_key) == (
        "collection.traffic_interval_seconds", "rewritten", "migrate_v6_default_interval")
    assert _cache_item(r, "pce_cache.events_poll_interval_seconds").action == "carried"
    r = migrate_v5(_with_cache(traffic_poll_interval_seconds=1800, events_poll_interval_seconds=30))
    assert r.settings.collection.traffic_interval_seconds == 1800
    assert _cache_item(r, "pce_cache.traffic_poll_interval_seconds").action == "carried"
    assert r.settings.collection.events_interval_seconds == 60  # 5.x allowed 30 s
    assert _cache_item(r, "pce_cache.events_poll_interval_seconds").reason_key == "migrate_raised_to_minimum"


def test_raw_retention_raised_to_baseline():
    r = migrate_v5(_with_cache(traffic_raw_retention_days=7, traffic_agg_retention_days=20))
    ret = r.settings.collection.retention
    assert (ret.flow_days, ret.rollup_days) == (35, 35)
    for key in ("traffic_raw_retention_days", "traffic_agg_retention_days"):
        assert _cache_item(r, f"pce_cache.{key}").reason_key == "migrate_raised_to_baseline"
    r = migrate_v5(_with_cache(traffic_raw_retention_days=60, traffic_agg_retention_days=400))
    assert (r.settings.collection.retention.flow_days, r.settings.collection.retention.rollup_days) == (60, 400)


def test_archive_retention_raised_to_outlive_raw_data():
    r = migrate_v5(_with_cache(archive_enabled=True, archive_retention_days=30, events_retention_days=90))
    assert r.settings.collection.archive.retention_days == 90
    assert _cache_item(r, "pce_cache.archive_retention_days").reason_key == "migrate_raised_for_archive"
    r = migrate_v5(_with_cache(archive_enabled=True, archive_retention_days=0))
    assert r.settings.collection.archive.retention_days == 0  # keep forever


def test_filter_and_sampling_dropped_with_reason():
    raw = _with_cache(traffic_filter={"actions": ["blocked"], "ports": [445]},
                      traffic_sampling={"sample_ratio_allowed": 5}, db_path="data/x.sqlite", flow_delta_enabled=True)
    report = migrate_v5(raw).report
    for source in ("pce_cache.traffic_filter.actions", "pce_cache.traffic_filter.ports",
                   "pce_cache.traffic_sampling.sample_ratio_allowed"):
        item = next(i for i in report.items if i.source == source)
        assert (item.action, item.reason_key) == ("dropped", "migrate_no_sampling")
    assert next(i for i in report.items if i.source == "pce_cache.db_path").reason_key == "migrate_fixed_path"
    assert next(i for i in report.items if i.source == "pce_cache.flow_delta_enabled").action == "dropped"


def test_cache_off_becomes_events_only():
    r = migrate_v5(_with_cache(enabled=False))
    assert (r.settings.collection.enabled, r.settings.collection.mode) == (True, "events_only")
    item = _cache_item(r, "pce_cache.enabled")
    assert (item.target, item.action, item.reason_key) == (
        "collection.mode", "rewritten", "migrate_cache_off_events_only")
    r = migrate_v5(_with_cache(enabled=True))
    assert r.settings.collection.mode == "full"
    assert _cache_item(r, "pce_cache.enabled").reason_key == "migrate_cache_on_full"
    raw = _base()
    raw.pop("pce_cache", None)
    assert migrate_v5(raw).settings.collection.mode == "events_only"  # 5.x kept no traffic


def test_106_pce_cache_every_leaf_accounted_for():
    raw = _load("v5_2_x_config_106_redacted.json")
    result = migrate_v5(raw)
    items = [i for i in result.report.items if i.source.startswith("pce_cache.")]
    assert sorted(i.source for i in items) == sorted(k for k in leaf_keys(raw) if k.startswith("pce_cache."))
    assert not [i for i in items if i.reason_key == "migrate_unknown_key" or i.params.get("phase") == "P2"]
    c = result.settings.collection
    assert (c.mode, c.traffic_interval_seconds, c.archive.enabled, c.archive.retention_days) == ("full", 300, True, 365)


def test_render_never_contains_secret_values():
    raw = _load("v5_0_0_config.json")
    raw["api"]["secret"] = "SECRET-api-value-123"
    raw["smtp"]["password"] = "SECRET-smtp-value-456"
    raw["alerts"]["line_channel_access_token"] = "SECRET-line-789"
    report = migrate_v5(raw).report
    for lang in Language:
        text = render(report, lang)
        assert "SECRET" not in text and raw["web_gui"]["password"] not in text and raw["web_gui"]["secret_key"] not in text
        assert "smtp.password" in text  # key names are shown, values never


def test_read_v5_rejects_non_5x_files(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text('{"schema_version": 1}')
    with pytest.raises(ValueError):
        read_v5(tmp_path)


def test_report_only_writes_nothing(tmp_path):
    v5 = tmp_path / "v5"
    (v5 / "config").mkdir(parents=True)
    (v5 / "config" / "config.json").write_text((FIXTURES / "v5_0_0_config.json").read_text())
    work = tmp_path / "cwd"
    work.mkdir()
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    r = subprocess.run([sys.executable, "-m", "illumio_ops.migrate", "--from", str(v5), "--report-only",
                        "--lang", "zh_TW"], capture_output=True, text=True, timeout=120, cwd=work, check=False,
                       env=os.environ | {"PYTHONPATH": str(REPO)})
    assert r.returncode == 0, r.stderr
    assert "api.secret" in r.stdout and "fake-secret" not in r.stdout
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


# ── 5.x semantics (adversarial review of Task 12) ─────────────────────────

def _base():
    return _load("v5_0_0_config.json")


def _item(report, source):
    return next(i for i in report.items if i.source == source)


def test_5x_normalisation_strips_and_coerces():
    raw = _base()
    raw["api"]["verify_ssl"] = "true"
    raw["api"]["key"] = " FAKE_KEY "
    raw["web_gui"]["password"] = " legacy-password "
    result = migrate_v5(raw)
    s = result.settings
    assert s.pce.verify_tls is True and s.pce.api_key == "FAKE_KEY"
    assert verify_password("legacy-password", s.web.password_hash)
    assert _item(result.report, "api.verify_ssl").action == "rewritten"
    assert _item(result.report, "api.key").action == "rewritten"


def test_provided_cert_paths_win_over_self_signed_flag():
    raw = _base()
    raw["web_gui"]["tls"].update(self_signed=True, cert_file="/etc/pki/c.pem", key_file="/etc/pki/k.pem")
    s = migrate_v5(raw).settings
    assert s.web.tls.mode == "provided" and s.web.tls.cert_file == "/etc/pki/c.pem"
    raw["web_gui"]["tls"].update(self_signed="false", cert_file="", key_file="")
    assert migrate_v5(raw).settings.web.tls.mode == "self_signed"  # 5.x: enabled without files


def test_missing_keys_take_the_5x_defaults():
    raw = _base()
    del raw["api"]["org_id"]
    del raw["web_gui"]
    result = migrate_v5(raw)
    assert result.settings.pce.org_id == "1"
    assert result.settings.web.username == "illumio"


@pytest.mark.parametrize(("path", "value", "expected"), [
    ("web_gui.session_lifetime_seconds", 30, 60),
    ("settings.timezone", "", "local"),
    ("settings.timezone", "Mars/Olympus", "UTC"),
    ("web_gui.tls.min_version", "TLSv1.1", "TLSv1.2"),
    ("web_gui.tls.key_algorithm", "rsa-4096", "ecdsa-p256"),
    ("logging.level", "CRITICAL", "CRITICAL"),
    ("api.url", "https://pce.example.com:8443/", "https://pce.example.com:8443"),
    ("web_gui.tls.enabled", "false", False),
])
def test_5x_values_become_their_effective_v6_value(path, value, expected):
    raw = _base()
    *parents, leaf = path.split(".")
    node = raw
    for p in parents:
        node = node[p]
    node[leaf] = value
    result = migrate_v5(raw)
    target = result.settings.model_dump(mode="json")
    for part in _item(result.report, path).target.split("."):
        target = target[part]
    assert target == expected
    assert _item(result.report, path).action == ("carried" if value == expected else "rewritten")


def test_non_numeric_org_id_blocks_but_the_report_is_complete():
    raw = _base()
    raw["api"]["org_id"] = "tenant-a"
    result = migrate_v5(raw)
    assert result.settings is None and [p for p, _ in result.blocking] == ["api.org_id"]
    assert sorted(i.source for i in result.report.items) == sorted(leaf_keys(raw))


def test_dotted_extra_keys_stay_distinct():
    raw = _base()
    raw["web_gui"]["audit"] = {"destination": 1}
    raw["web_gui"]["audit.destination"] = 2
    sources = [i.source for i in migrate_v5(raw).report.items]
    assert len(sources) == len(set(sources)) == len(leaf_keys(raw))


def test_allowlist_entries_5x_ignored_are_dropped_and_reported():
    raw = _base()
    raw["web_gui"]["allowed_ips"] = ["10.0.0.0/8", "localhost", "::ffff:192.168.1.5"]
    result = migrate_v5(raw)
    assert result.settings.web.allowed_ips == ("10.0.0.0/8", "::ffff:192.168.1.5")
    item = _item(result.report, "web_gui.allowed_ips")
    assert item.action == "rewritten" and item.reason_key == "migrate_5x_effective_value"


def test_allowlist_with_no_valid_entry_blocks_instead_of_opening_up():
    raw = _base()
    raw["web_gui"]["allowed_ips"] = ["localhost", "server.example"]  # 5.x refused everyone
    result = migrate_v5(raw)
    assert result.settings is None and [p for p, _ in result.blocking] == ["web_gui.allowed_ips"]
    assert sorted(i.source for i in result.report.items) == sorted(leaf_keys(raw))



@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_migrator_output_has_default_lateral(name):
    s = migrate_v5(_load(name)).settings
    assert s.schema_version == 3
    assert s.lateral.graph_hops == 3 and s.lateral.critical_assets == () and s.lateral.environment_label_key == "env"
