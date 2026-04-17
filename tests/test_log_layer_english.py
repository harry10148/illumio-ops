"""Regression tests (Phase 6): the log / low-level event layer must stay
English-only.

Per the project's i18n policy, `logger.*()` calls, exception messages, and
event-pipeline `print()` calls should not contain Chinese characters so that
log files and vendor integrations remain locale-neutral. UI-visible strings
belong in the GUI/report/CLI layers and should go through `t()` instead.

Two AST-walk checks:

- `logger.<level>(...)` anywhere in `src/` — first string argument must be
  CJK-free.
- `raise ExceptionType(...)` in `src/` — message argument must be CJK-free.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Files whose zh content is an intentional bilingual data resource
# (templates used for both EN and ZH downstream, not logs).
SKIP_FILES = {
    SRC / "i18n.py",
    SRC / "report" / "exporters" / "report_i18n.py",
    SRC / "report" / "analysis" / "attack_posture.py",
}

SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for path in SRC.rglob("*.py"):
        if not path.is_file():
            continue
        if path in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def _first_str_arg(call: ast.Call) -> tuple[str | None, int]:
    """Return (literal_value, lineno) of the first positional string arg.

    Handles bare strings, f-strings (Constant + FormattedValue parts), and
    string concatenation via ``+``. Returns (None, 0) if the first arg is
    something else (a variable, function call, etc.).
    """
    if not call.args:
        return None, 0
    first = call.args[0]
    return _flatten_str(first)


def _flatten_str(node: ast.AST) -> tuple[str | None, int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, node.lineno
    if isinstance(node, ast.JoinedStr):
        # f-string: concat the Constant literal parts; format placeholders
        # carry no static text we can inspect.
        pieces: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                pieces.append(part.value)
        return "".join(pieces), node.lineno
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, ll = _flatten_str(node.left)
        right, _ = _flatten_str(node.right)
        if left is not None and right is not None:
            return left + right, ll or node.lineno
        if left is not None:
            return left, ll
        if right is not None:
            return right, node.lineno
    return None, 0


def _collect_logger_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """Yield (lineno, message) for logger.*(...) / log.*(...) calls
    whose first argument is a static string literal containing CJK."""
    hits: list[tuple[int, str]] = []
    log_method_names = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match `logger.info(...)` / `log.error(...)` / `_log.debug(...)` /
        # `self._file_logger.info(...)` — any attribute call where the final
        # attribute is a standard log-level name.
        if not (isinstance(func, ast.Attribute) and func.attr in log_method_names):
            continue
        # Heuristic: the receiver chain should contain "log" somewhere so we
        # don't falsely match unrelated .error(...) methods.
        receiver_dump = ast.dump(func.value).lower()
        if "log" not in receiver_dump:
            continue
        text, lineno = _first_str_arg(node)
        if text and CJK_RE.search(text):
            hits.append((lineno, text))
    return hits


def _collect_raise_messages(tree: ast.AST) -> list[tuple[int, str]]:
    """Yield (lineno, message) for `raise SomeException(static_str)` where
    the static message contains CJK."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        exc = node.exc
        if not isinstance(exc, ast.Call):
            continue
        text, lineno = _first_str_arg(exc)
        if text and CJK_RE.search(text):
            hits.append((lineno or node.lineno, text))
    return hits


def _collect_events_print_calls(tree: ast.AST, rel_path: str) -> list[tuple[int, str]]:
    """Yield (lineno, message) for `print(...)` calls inside src/events/* —
    these are diagnostic traces for the event pipeline and must stay ASCII."""
    if "src/events/" not in rel_path.replace("\\", "/"):
        return []
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "print"):
            continue
        text, lineno = _first_str_arg(node)
        if text and CJK_RE.search(text):
            hits.append((lineno, text))
    return hits


def _scan_py(path: Path) -> list[tuple[str, int, str, str]]:
    """Return list of (kind, lineno, message, rel_path) for every violation."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    violations: list[tuple[str, int, str, str]] = []
    for line, msg in _collect_logger_calls(tree):
        violations.append(("logger", line, msg, rel))
    for line, msg in _collect_raise_messages(tree):
        violations.append(("raise", line, msg, rel))
    for line, msg in _collect_events_print_calls(tree, rel):
        violations.append(("events/print", line, msg, rel))
    return violations


def test_log_layer_is_english_only():
    """No CJK characters in logger.*(), raise Exception(...), or
    print() calls inside src/events/*.

    Motivation: logs and vendor-facing event metadata must be locale-neutral
    so grep, log aggregators, and SIEMs work regardless of UI language.
    """
    all_violations: list[tuple[str, int, str, str]] = []
    for path in _iter_py_files():
        all_violations.extend(_scan_py(path))

    if all_violations:
        lines = ["Log-layer CJK violations (use English + i18n instead):"]
        for kind, lineno, msg, rel in sorted(all_violations):
            clipped = msg[:80] + ("..." if len(msg) > 80 else "")
            lines.append(f"  [{kind}] {rel}:{lineno}  {clipped!r}")
        pytest.fail("\n".join(lines))
