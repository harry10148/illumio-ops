"""Contract: install.sh must install a /usr/local/bin/illumio-ops wrapper that
execs the bundled Python (system python3 on old distros has SQLite < 3.35 and
breaks INSERT ... RETURNING), and uninstall.sh must remove it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_install_creates_cli_wrapper():
    src = (ROOT / "scripts" / "install.sh").read_text()
    assert "/usr/local/bin/illumio-ops" in src
    assert 'exec "$INSTALL_ROOT/python/bin/python3"' in src
    # The wrapper must cd to the install root first: relative paths from
    # config (db_path "data/pce_cache.sqlite", logs/, reports/) resolve
    # against the process cwd, so an un-cd'd wrapper run from e.g. /root
    # would silently create a second DB at /root/data/.
    assert 'cd "$INSTALL_ROOT" || exit 1' in src


def test_uninstall_removes_cli_wrapper():
    src = (ROOT / "scripts" / "uninstall.sh").read_text()
    assert "rm -f /usr/local/bin/illumio-ops" in src
