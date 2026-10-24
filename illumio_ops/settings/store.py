"""SettingsStore: the only reader and writer of config/settings.json.

Load is fail-closed (an invalid file is reported, never defaulted or
rewritten). Writes are optimistic-concurrency (revision), validated before
touching disk, atomic (temp file + fsync + rename) and 0600.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import ValidationError

from illumio_ops.settings.schema import Settings, default_settings


class SettingsInvalid(Exception):
    """errors: (dotted path, message); messages never contain the offending value."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{loc or '<root>'}: {msg}" for loc, msg in errors))


class SettingsConflict(Exception):
    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"settings revision is {actual}, expected {expected}")


def _errors(exc: ValidationError) -> list[tuple[str, str]]:
    out = []
    for e in exc.errors(include_input=False, include_url=False):
        # Union members add type tags to the location ("bool", "str"); keep field names only.
        loc = ".".join(str(p) for p in e["loc"] if not (isinstance(p, str) and p in {"bool", "str", "int"}))
        msg = e["msg"]
        if e["type"] == "value_error":
            msg = str(e.get("ctx", {}).get("error", msg))
        out.append((loc, msg))
    return out


def validate_settings(data: Any) -> Settings:
    """Settings from a plain dict, or SettingsInvalid with field paths (never values)."""
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise SettingsInvalid(_errors(exc)) from None


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._current: Settings | None = None

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Settings:
        raw = self._path.read_bytes()  # FileNotFoundError propagates: the caller decides
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SettingsInvalid([("", f"invalid JSON (line {exc.lineno}, column {exc.colno})")]) from None
        s = validate_settings(data)
        with self._lock:
            self._current = s
        return s

    def current(self) -> Settings:
        s = self._current
        if s is None:
            raise RuntimeError("settings not loaded")
        return s

    def update(self, expected_revision: int, mutate: Callable[[dict[str, Any]], None]) -> Settings:
        with self._lock:
            cur = self.current()
            if cur.revision != expected_revision:
                raise SettingsConflict(expected_revision, cur.revision)
            cand = cur.model_dump(mode="json")  # a fresh tree: mutate cannot reach cur
            mutate(cand)
            cand["revision"] = cur.revision + 1
            new = validate_settings(cand)
            self._write(new, replace=True)
            self._current = new  # the file now holds `new`: memory must follow it
            self._sync_dir()
            return new

    def create_initial(self, *, password_hash: str, secret_key: str, port: int = 5001) -> Settings:
        s = default_settings(password_hash=password_hash, secret_key=secret_key, port=port)
        with self._lock:
            self._write(s, replace=False)
            self._current = s
            self._sync_dir()
        return s

    def _write(self, s: Settings, *, replace: bool) -> None:
        body = (json.dumps(s.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n").encode()
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".settings.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            if replace:
                os.replace(tmp, self._path)
            else:
                os.link(tmp, self._path)  # FileExistsError instead of clobbering
                os.unlink(tmp)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _sync_dir(self) -> None:
        """Make the rename durable. By now the new file is in place and in memory, so a
        failure here is reported, not raised: raising would tell the caller the change
        did not happen when it did."""
        try:
            dfd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError as exc:
            logger.error("settings saved but the directory sync failed ({}); "
                         "the change may not survive a power loss", type(exc).__name__)
