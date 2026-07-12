"""Contract: install.sh upgrades must be deterministic.

- python/ is rsynced with --delete: restores a pristine bundled runtime
  (including its site-packages), so the following pip install from bundle
  wheels yields exactly the bundle's package set — no stale versions
  (range specs like `requests>=2.31,<3.0` would otherwise let pip skip
  already-satisfied packages), no orphaned packages (e.g. removed plotly).
- app rsync on upgrade uses --delete with operator/runtime dirs excluded,
  so renamed/deleted src modules cannot linger as importable zombies.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _install_sh() -> str:
    return (ROOT / "scripts" / "install.sh").read_text()


def test_python_runtime_rsync_restores_pristine():
    assert 'rsync -a --delete "$SRC/python/" "$INSTALL_ROOT/python/"' in _install_sh()


def test_upgrade_app_rsync_deletes_stale_files_with_guards():
    src = _install_sh()
    # upgrade 分支必須帶 --delete，且逐一排除 operator/runtime 目錄
    assert "rsync -a --delete \\" in src
    # Excludes must be anchored (leading /) to the transfer root; unanchored
    # patterns match at any depth and would freeze app-tree dirs like src/i18n/data/
    for excl in ("/config/", "/data/", "/logs/", "/reports/", "/python/",
                 "/MIGRATED_FROM", "/uninstall.sh"):
        assert f"--exclude='{excl}'" in src, f"missing anchored --exclude for {excl}"
