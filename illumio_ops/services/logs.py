"""Reading the service log for System › Logs: newest first, filtered, bounded.

The log file is written by loguru in its default format:
  2026-10-24 18:36:34.694 | INFO     | illumio_ops.pce.collections:_fn:93 - message
Continuation lines (tracebacks) belong to the entry above them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

LEVELS = {"TRACE": 5, "DEBUG": 10, "INFO": 20, "SUCCESS": 25, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \| (\w+)\s*\| ([^:\s]+)[^ ]* - (.*)$")
TAIL_BYTES_PER_FILE = 2 * 1024 * 1024
MAX_FILES = 5


@dataclass(frozen=True)
class LogEntry:
    ts: str
    level: str
    module: str
    message: str


def _files(logs_dir: Path) -> list[Path]:
    current = logs_dir / "illumio-ops.log"
    rotated = sorted(logs_dir.glob("illumio-ops.*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return ([current] if current.exists() else []) + rotated[: MAX_FILES - 1]


def _entries(path: Path) -> list[LogEntry]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > TAIL_BYTES_PER_FILE:
            fh.seek(size - TAIL_BYTES_PER_FILE)
            fh.readline()  # drop the partial first line
        text = fh.read().decode("utf-8", errors="replace")
    out: list[LogEntry] = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            out.append(LogEntry(ts=m.group(1), level=m.group(2), module=m.group(3), message=m.group(4)))
        elif out:
            last = out[-1]
            out[-1] = LogEntry(last.ts, last.level, last.module, f"{last.message}\n{line}")
    return out


def tail(logs_dir: Path, *, level: str | None, module: str | None, contains: str | None,
         limit: int) -> tuple[list[LogEntry], bool]:
    """Newest-first matching entries and whether more matched than limit."""
    floor = LEVELS.get(level or "", 0)
    needle = contains.lower() if contains else None
    matched: list[LogEntry] = []
    for path in _files(logs_dir):
        for e in reversed(_entries(path)):
            if LEVELS.get(e.level, 0) < floor:
                continue
            if module and not e.module.startswith(module):
                continue
            if needle and needle not in e.message.lower():
                continue
            matched.append(e)
            if len(matched) > limit:
                return matched[:limit], True
    return matched, False
