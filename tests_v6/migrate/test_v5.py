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
    _, report = migrate_v5(raw)
    sources = [i.source for i in report.items]
    assert sorted(sources) == sorted(leaf_keys(raw))
    assert len(sources) == len(set(sources))


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_migrated_settings_validate(name):
    raw = _load(name)
    s, _ = migrate_v5(raw)
    assert s.pce.url == raw["api"]["url"].rstrip("/")
    assert s.web.tls.mode == "self_signed" and s.web.tls.validity_days == raw["web_gui"]["tls"]["validity_days"]
    assert s.display.language is Language(raw["settings"]["language"])
    assert s.display.timezone == raw["settings"]["timezone"]
    assert s.logging.level == raw["logging"]["level"]


def test_argon2_hash_carried_verbatim():
    raw = _load("v5_0_0_config.json")
    s, report = migrate_v5(raw)
    assert s.web.password_hash == raw["web_gui"]["password"]
    item = next(i for i in report.items if i.source == "web_gui.password")
    assert (item.target, item.action) == ("web.password_hash", "carried")


def test_plaintext_password_is_hashed_and_marked_rewritten():
    raw = _load("v5_0_0_config.json")
    raw["web_gui"]["password"] = "legacy-plain-pass"
    s, report = migrate_v5(raw)
    assert verify_password("legacy-plain-pass", s.web.password_hash)
    item = next(i for i in report.items if i.source == "web_gui.password")
    assert item.action == "rewritten" and item.reason_key == "migrate_password_hashed"


def test_empty_password_becomes_the_5x_default():
    raw = _load("v5_0_0_config.json")
    raw["web_gui"]["password"] = ""
    s, report = migrate_v5(raw)
    assert verify_password("illumio", s.web.password_hash)
    assert next(i for i in report.items if i.source == "web_gui.password").reason_key == "migrate_password_default"


def test_deprecated_keys_dropped_with_reason():
    raw = _load("v5_0_0_config.json")
    raw["report"]["attack_surface"] = {"enabled": True}
    raw["web_gui"]["tls"]["http_redirect_port"] = 80
    raw["pce_profiles"] = [{"name": "x"}]
    raw["active_pce_id"] = 1
    raw["pce_cache"]["archive_review_max_days"] = 7
    _, report = migrate_v5(raw)
    dep = {i.source: i for i in report.items if i.reason_key == "migrate_deprecated_in_5x"}
    assert set(dep) >= {"report.attack_surface.enabled", "web_gui.tls.http_redirect_port", "pce_profiles",
                        "active_pce_id", "pce_cache.archive_review_max_days"}
    assert all(i.action == "dropped" for i in dep.values())


def test_unsupported_sections_name_their_phase():
    _, report = migrate_v5(_load("v5_2_x_config_106_redacted.json"))
    by_source = {i.source: i for i in report.items}
    assert by_source["smtp.host"].params == {"phase": "P3"} and by_source["smtp.host"].action == "unsupported"
    assert by_source["siem.enabled"].params == {"phase": "P4"}
    assert by_source["report_schedules"].params == {"phase": "P5"}
    assert by_source["pce_cache.enabled"].params == {"phase": "P2"}
    assert by_source["settings.theme"].reason_key == "migrate_not_in_v6"
    assert by_source["api.profile"].action == "dropped"


def test_render_never_contains_secret_values():
    raw = _load("v5_0_0_config.json")
    raw["api"]["secret"] = "SECRET-api-value-123"
    raw["smtp"]["password"] = "SECRET-smtp-value-456"
    raw["alerts"]["line_channel_access_token"] = "SECRET-line-789"
    _, report = migrate_v5(raw)
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
