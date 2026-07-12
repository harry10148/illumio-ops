"""Runtime environment guards for the app entry point.

Offline-bundle deployments always run on the bundled python-build-standalone
interpreter, whose SQLite is modern. These guards exist for the failure mode
where an operator bypasses the bundle and runs the app with the system
python3 — old enterprise distros (RHEL 8: SQLite 3.26, Ubuntu 20.04: 3.31)
lack INSERT ... RETURNING (needs >= 3.35.0) used by the ingestors.
"""
from __future__ import annotations

# INSERT ... RETURNING (src/pce_cache/ingestor_events.py,
# src/pce_cache/ingestor_traffic.py) requires SQLite >= 3.35.0.
# Keep in sync with the bash-side copy in scripts/preflight.sh.
MIN_SQLITE_VERSION = (3, 35, 0)


def sqlite_version_error() -> str | None:
    """Return a human-readable error when the linked SQLite is too old.

    Returns None when the runtime is acceptable. Plain English (no i18n):
    this runs before any app import, where the i18n engine may not even be
    importable under a broken interpreter.
    """
    import sqlite3

    if sqlite3.sqlite_version_info >= MIN_SQLITE_VERSION:
        return None
    want = ".".join(str(p) for p in MIN_SQLITE_VERSION)
    return (
        f"Error: this Python links SQLite {sqlite3.sqlite_version}, but "
        f"illumio-ops requires SQLite >= {want} (INSERT ... RETURNING).\n"
        "You are probably running the system python3 instead of the bundled "
        "runtime. Re-run with the bundle interpreter, e.g.:\n"
        "  /opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py"
    )
