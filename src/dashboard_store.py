"""Durable store for dashboard summary data (VEN health / OS distribution / enforcement).

Written by background jobs (run_ven_summary).
Read cheaply by the overview API (/api/dashboard/overview).
The analyzer's monitor cycle never touches this file, so writes from background
jobs are never stomped.
"""
from __future__ import annotations

import json
import os
import tempfile

from loguru import logger


def _dashboard_file() -> str:
    """Return the absolute path to logs/dashboard_summary.json.

    Resolved the same way state_store resolves logs/state.json:
    relative to the project root (two directories above this file).
    """
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(pkg_dir)
    return os.path.join(root_dir, "logs", "dashboard_summary.json")


def read_dashboard_summary() -> dict:
    """Return the stored dashboard summary dict, or {} if missing/invalid."""
    path = _dashboard_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to read dashboard summary {}: {}", path, exc)
        return {}


def write_dashboard_summary(updater) -> dict:
    """Atomically update the dashboard summary file.

    ``updater`` is either:
    - a callable(existing: dict) -> dict, or
    - a plain dict (merged into the existing data).

    Creates logs/ if needed.  Uses tempfile + os.replace for atomicity.
    Returns the written dict.
    """
    path = _dashboard_file()
    logs_dir = os.path.dirname(path)
    os.makedirs(logs_dir, exist_ok=True)

    current = read_dashboard_summary()
    if callable(updater):
        updated = updater(dict(current))
    else:
        updated = {**current, **updater}

    if not isinstance(updated, dict):
        raise ValueError("Dashboard summary updater must return a dict")

    fd, tmp_path = tempfile.mkstemp(dir=logs_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        # Owner + group readable (NOT world-readable). In production the writer
        # (background job) and reader (overview API) are the same service user,
        # so this is effectively 0600; the group bit only helps if an operator
        # places both users in a shared group. This holds infrastructure posture
        # data, so it must not be world-readable.
        os.chmod(tmp_path, 0o640)
        os.replace(tmp_path, path)
        # fsync parent dir for metadata durability (Linux only; harmless on other POSIX)
        try:
            dirfd = os.open(logs_dir, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except OSError:
            pass  # best-effort
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return updated
