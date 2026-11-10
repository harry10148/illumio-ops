"""install.sh --upgrade-from, end to end without systemd: a bundle whose interpreter is this test run's (pip is
skipped: the dependencies are already here), a 5.x tree shaped like .106's."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.migrate.test_v5_handover import EVENTS, _db

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "migrate" / "fixtures"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    b = tmp_path_factory.mktemp("bundle")
    for f in ("install.sh", "rollback.sh", "restore-previous.sh", "uninstall.sh", "preflight.sh", "illumio-ops.service.in"):
        shutil.copy(REPO / "scripts" / f, b / f)
    (b / "requirements.lock").write_text("")
    (b / "wheels").mkdir()
    (b / "python" / "bin").mkdir(parents=True)
    py = b / "python" / "bin" / "python3"
    py.write_text(f'#!/bin/sh\nfor a in "$@"; do [ "$a" = pip ] && exit 0; done\nexec {sys.executable} "$@"\n')
    py.chmod(0o755)
    shutil.copytree(REPO / "illumio_ops", b / "illumio_ops", ignore=shutil.ignore_patterns("__pycache__"))
    return b


@pytest.fixture
def v5(tmp_path):
    root = tmp_path / "opt" / "illumio-ops"
    (root / "config" / "tls").mkdir(parents=True)
    raw = json.loads((FIXTURES / "v5_2_x_config_106_redacted.json").read_text())
    raw["pce_cache"]["db_path"] = "data/pce_cache.sqlite"
    (root / "config" / "config.json").write_text(json.dumps(raw))
    (root / "config" / "tls" / "self_signed.pem").write_text("CERT")
    (root / "illumio-ops.py").write_text("# 5.x")
    _db(root, EVENTS, [(1, "redacted-25", "sent")])
    return root


def _install(bundle, *args):
    return subprocess.run(["bash", str(bundle / "install.sh"), "--no-systemd", *map(str, args)], capture_output=True,
                          text=True, timeout=300, check=False, stdin=subprocess.DEVNULL,
                          env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})


def _tree(p):
    return sorted(str(x.relative_to(p)) for x in p.rglob("*"))


def test_report_only_shows_the_report_and_changes_nothing(bundle, v5, tmp_path):
    before = _tree(tmp_path)
    r = _install(bundle, "--upgrade-from", v5, "--prefix", tmp_path / "v6", "--report-only")
    assert r.returncode == 0, r.stderr
    assert "siem.destinations[0]" in r.stdout
    assert _tree(tmp_path) == before


def test_without_a_terminal_the_report_must_be_accepted(bundle, v5, tmp_path):
    before = _tree(tmp_path)
    r = _install(bundle, "--upgrade-from", v5, "--prefix", tmp_path / "v6")
    assert r.returncode != 0 and "--accept-report" in r.stderr
    assert _tree(tmp_path) == before


def test_upgrade_into_another_directory_leaves_5x_where_it_is(bundle, v5, tmp_path):
    before = {p: p.read_bytes() for p in v5.rglob("*") if p.is_file()}
    prefix = tmp_path / "v6"
    r = _install(bundle, "--upgrade-from", v5, "--prefix", prefix, "--accept-report")
    assert r.returncode == 0, r.stderr
    assert "redacted-25" in r.stdout
    assert json.loads((prefix / "config" / "settings.json").read_text())["siem"]["destinations"][0]["name"] == \
        "redacted-25"
    assert (prefix / "logs" / "migration-report.txt").is_file() and (prefix / "rollback.sh").is_file()
    assert {p: p.read_bytes() for p in v5.rglob("*") if p.is_file()} == before


def test_upgrade_in_place_moves_5x_aside_and_rollback_brings_it_back(bundle, v5):
    r = _install(bundle, "--prefix", v5, "--accept-report")  # the prefix holds 5.x: found without --upgrade-from
    assert r.returncode == 0, r.stderr
    moved = [p for p in v5.parent.iterdir() if p.name.startswith("illumio-ops.5x-")]
    assert len(moved) == 1 and (moved[0] / "illumio-ops.py").is_file()
    assert (v5 / "config" / "settings.json").is_file() and not (v5 / "illumio-ops.py").exists()
    back = subprocess.run(["bash", str(v5 / "rollback.sh")], capture_output=True, text=True, timeout=60, check=False)
    assert back.returncode == 0, back.stderr
    assert (v5 / "illumio-ops.py").is_file() and not (v5 / "config" / "settings.json").exists()
    [kept] = [p for p in v5.parent.iterdir() if p.name.startswith("illumio-ops.v6-rolled-back-")]
    assert (kept / "config" / "settings.json").is_file()
    again = _install(bundle, "--prefix", v5, "--accept-report")  # a second upgrade starts clean
    assert again.returncode == 0, again.stderr


def test_a_directory_that_is_not_5x_is_refused(bundle, tmp_path):
    r = _install(bundle, "--upgrade-from", tmp_path, "--prefix", tmp_path / "v6", "--report-only")
    assert r.returncode != 0 and "not an illumio-ops 5.x installation" in r.stderr


def test_upgrade_with_a_port_writes_it_and_names_it(bundle, v5):
    r = _install(bundle, "--prefix", v5, "--accept-report", "--port", "8443")
    assert r.returncode == 0, r.stderr
    assert json.loads((v5 / "config" / "settings.json").read_text())["web"]["port"] == 8443
    assert "https://<this host>:8443/" in r.stdout and ":5001/" not in r.stdout


def test_install_over_kept_settings_names_the_port_they_hold(bundle, v5):
    assert _install(bundle, "--prefix", v5, "--accept-report", "--port", "8443").returncode == 0
    again = _install(bundle, "--prefix", v5, "--accept-report")  # v6 over v6: the settings stay, and so does the port
    assert again.returncode == 0, again.stderr
    assert "https://<this host>:8443/" in again.stdout and ":5001/" not in again.stdout


def test_rollback_restores_5x_when_the_v6_unit_is_not_there(bundle, v5, tmp_path):
    assert _install(bundle, "--prefix", v5, "--accept-report").returncode == 0
    env_file = v5 / "rollback" / "rollback.env"
    env_file.write_text(env_file.read_text().replace("NO_SYSTEMD=1", "NO_SYSTEMD=0")
                        .replace("SERVICE=illumio-ops\n", "SERVICE=illumio-ops-test-absent\n"))
    assert "NO_SYSTEMD=0" in env_file.read_text() and "SERVICE=illumio-ops-test-absent" in env_file.read_text()
    fake = tmp_path / "bin"
    fake.mkdir()
    calls = tmp_path / "systemctl.calls"
    # As systemd answers for a unit it does not have: stop fails (5), is-active says inactive (3).
    (fake / "systemctl").write_text(f'#!/bin/sh\necho "$@" >> {calls}\ncase "$1" in stop) exit 5 ;; is-active) exit 3 ;; '
                                    'disable) exit 1 ;; esac\nexit 0\n')
    (fake / "id").write_text('#!/bin/sh\n[ "$1" = -u ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n')
    for f in fake.iterdir():
        f.chmod(0o755)
    back = subprocess.run(["bash", str(v5 / "rollback.sh")], capture_output=True, text=True, timeout=60, check=False,
                          env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
    assert back.returncode == 0, back.stderr
    assert (v5 / "illumio-ops.py").is_file() and not (v5 / "config" / "settings.json").exists()
    assert "stop illumio-ops-test-absent" in calls.read_text()


def test_rollback_changes_nothing_while_v6_is_still_running(bundle, v5, tmp_path):
    assert _install(bundle, "--prefix", v5, "--accept-report").returncode == 0
    env_file = v5 / "rollback" / "rollback.env"
    env_file.write_text(env_file.read_text().replace("NO_SYSTEMD=1", "NO_SYSTEMD=0")
                        .replace("SERVICE=illumio-ops\n", "SERVICE=illumio-ops-test-absent\n"))
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "systemctl").write_text('#!/bin/sh\ncase "$1" in stop) exit 1 ;; is-active) exit 0 ;; esac\nexit 0\n')
    (fake / "id").write_text('#!/bin/sh\n[ "$1" = -u ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n')
    for f in fake.iterdir():
        f.chmod(0o755)
    back = subprocess.run(["bash", str(v5 / "rollback.sh")], capture_output=True, text=True, timeout=60, check=False,
                          env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
    assert back.returncode != 0 and "still running" in back.stderr
    assert (v5 / "config" / "settings.json").is_file() and not (v5 / "illumio-ops.py").exists()
