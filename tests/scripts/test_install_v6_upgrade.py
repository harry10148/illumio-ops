"""install.sh over a prefix that already holds v6: the installed version is replaced in place, settings and data stay,
the previous version is kept for restore-previous.sh, and an older bundle never goes over a newer installation.
Without systemd, against a bundle whose interpreter is this test run's (pip is skipped)."""
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from illumio_ops import __version__
from illumio_ops.store.db import _migrations
from illumio_ops.store.flowdb.db import MIGRATIONS_PACKAGE as FLOW_MIGRATIONS

REPO = Path(__file__).resolve().parents[2]
FLOW_LATEST = len(_migrations(FLOW_MIGRATIONS))


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    b = tmp_path_factory.mktemp("bundle")
    for f in ("install.sh", "rollback.sh", "restore-previous.sh", "illumio-ops.service.in"):
        shutil.copy(REPO / "scripts" / f, b / f)
    (b / "requirements.lock").write_text("")
    (b / "wheels").mkdir()
    (b / "python" / "bin").mkdir(parents=True)
    py = b / "python" / "bin" / "python3"
    py.write_text(f'#!/bin/sh\nfor a in "$@"; do [ "$a" = pip ] && exit 0; done\nexec {sys.executable} "$@"\n')
    py.chmod(0o755)
    shutil.copytree(REPO / "illumio_ops", b / "illumio_ops", ignore=shutil.ignore_patterns("__pycache__"))
    return b


def _run(*cmd, stdin=subprocess.DEVNULL):
    return subprocess.run([*map(str, cmd)], capture_output=True, text=True, timeout=300, check=False, stdin=stdin,
                          env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})


def _install(bundle, *args):
    return _run("bash", bundle / "install.sh", "--no-systemd", *args)


def _set_version(prefix: Path, version: str) -> None:
    init = prefix / "illumio_ops" / "__init__.py"
    init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text()))


def _version(prefix: Path) -> str:
    return re.search(r'__version__ = "([^"]+)"', (prefix / "illumio_ops" / "__init__.py").read_text())[1]


def _db(path: Path, version: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS marker (v TEXT)")
        conn.execute("INSERT INTO marker VALUES ('kept')")
        conn.execute(f"PRAGMA user_version = {version}")


def _tree(p: Path) -> list[tuple[str, bytes]]:
    return sorted((str(x.relative_to(p)), x.read_bytes() if x.is_file() else b"") for x in p.rglob("*")
                  if "__pycache__" not in x.parts)


@pytest.fixture
def v6(bundle, tmp_path):
    """A v6 installation one version behind the bundle, with flows already at this program's schema."""
    prefix = tmp_path / "opt" / "illumio-ops"
    r = _install(bundle, "--prefix", prefix)
    assert r.returncode == 0, r.stderr
    _set_version(prefix, "6.0.0")
    _db(prefix / "data" / "flows.sqlite", FLOW_LATEST)
    (prefix / "reports" / "kept.html").write_text("report")
    return prefix


def test_a_v6_prefix_is_upgraded_in_place(bundle, v6):
    settings = (v6 / "config" / "settings.json").read_bytes()
    r = _install(bundle, "--prefix", v6, "--accept-report")
    assert r.returncode == 0, r.stderr
    assert f"from 6.0.0 to {__version__}" in r.stdout
    assert _version(v6) == __version__
    assert _version(v6 / "previous") == "6.0.0" and (v6 / "previous" / "python" / "bin" / "python3").exists()
    assert (v6 / "config" / "settings.json").read_bytes() == settings
    assert (v6 / "reports" / "kept.html").read_text() == "report"
    assert (v6 / "restore-previous.sh").exists()
    assert not (v6 / "previous" / "data" / "flows.sqlite").exists()  # no schema change: nothing to go back to


def test_restore_previous_brings_the_old_version_and_settings_back(bundle, v6):
    settings = (v6 / "config" / "settings.json").read_bytes()
    _db(v6 / "data" / "flows.sqlite", FLOW_LATEST - 1)  # the bundle migrates flows at its first start
    assert _install(bundle, "--prefix", v6, "--accept-report").returncode == 0
    assert (v6 / "previous" / "data" / "flows.sqlite").exists()
    _db(v6 / "data" / "flows.sqlite", FLOW_LATEST)  # what the new version's first start does
    (v6 / "config" / "settings.json").write_text("{}")
    r = _run("bash", v6 / "restore-previous.sh")
    assert r.returncode == 0, r.stderr
    assert _version(v6) == "6.0.0"
    assert (v6 / "config" / "settings.json").read_bytes() == settings
    with sqlite3.connect(v6 / "data" / "flows.sqlite") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == FLOW_LATEST - 1
    assert not (v6 / "previous").exists()
    assert _run("bash", v6 / "restore-previous.sh").returncode != 0  # once only


def test_an_older_bundle_is_not_installed_over_a_newer_installation(bundle, v6):
    _set_version(v6, "99.0.0")
    before = _tree(v6)
    r = _install(bundle, "--prefix", v6, "--accept-report")
    assert r.returncode != 0 and "newer than this bundle" in r.stderr
    assert _tree(v6) == before


def test_a_database_newer_than_the_bundle_is_refused(bundle, v6):
    _db(v6 / "data" / "flows.sqlite", FLOW_LATEST + 1)
    before = _tree(v6)
    r = _install(bundle, "--prefix", v6, "--accept-report")
    assert r.returncode != 0 and "newer than this program" in r.stderr
    assert _tree(v6) == before


def test_report_only_and_no_terminal_change_nothing(bundle, v6):
    before = _tree(v6)
    r = _install(bundle, "--prefix", v6, "--report-only")
    assert r.returncode == 0, r.stderr
    assert f"from 6.0.0 to {__version__}" in r.stdout
    r = _install(bundle, "--prefix", v6)
    assert r.returncode != 0 and "--accept-report" in r.stderr
    assert _tree(v6) == before


def test_settings_without_the_program_are_not_an_installation(bundle, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text("{}")
    r = _install(bundle, "--prefix", tmp_path, "--accept-report")
    assert r.returncode != 0 and "not a complete" in r.stderr
