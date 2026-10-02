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


# Last parse, keyed on the file's identity. The fleet index makes this file
# several MB (5 MB at 20k workloads, 13 MB at 50k) and every VEN inventory
# request, plus three overview cards, parsed it again — 165 ms per parse at
# 50k. The file only changes when a background job rewrites it (os.replace,
# so mtime/size/inode change), which drops the cached copy.
_cache: tuple[tuple, dict] | None = None


def _read_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def read_dashboard_summary() -> dict:
    """Return the stored dashboard summary dict, or {} if missing/invalid.

    The returned dict is shared between callers: treat it as read-only. To
    change the file use write_dashboard_summary, which works on a fresh copy.
    """
    global _cache
    path = _dashboard_file()
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("Failed to read dashboard summary {}: {}", path, exc)
        return {}
    ident = (path, st.st_mtime_ns, st.st_size, st.st_ino)
    cached = _cache
    if cached is not None and cached[0] == ident:
        return cached[1]
    try:
        data = _read_file(path)
    except Exception as exc:
        logger.warning("Failed to read dashboard summary {}: {}", path, exc)
        return {}
    _cache = (ident, data)
    return data


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

    # A fresh parse, never the shared cached dict: updaters may mutate what
    # they are given, nested values included.
    try:
        current = _read_file(path) if os.path.exists(path) else {}
    except Exception as exc:
        logger.warning("Failed to read dashboard summary {}: {}", path, exc)
        current = {}
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
