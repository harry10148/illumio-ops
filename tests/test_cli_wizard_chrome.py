"""Phase 2C Tasks 11-13 — the wizards redraw their frame at every step.

DD-1: before this, a wizard printed its step label into whatever the previous
screen had left behind, so by step four the terminal held four screens of
history and the operator had no fixed reference for where they were. Passing
`path` to _wizard_step redraws the chrome above the label.

The path is the breadcrumb, so it also answers "which wizard am I in" — the
question a half-scrolled terminal cannot.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from src import i18n

WIZARDS = [
    "src/cli/menus/event.py",
    "src/cli/menus/traffic.py",
    "src/cli/menus/bandwidth.py",
    "src/cli/menus/system_health.py",
    "src/cli/menus/report_schedule.py",
]


@pytest.fixture(autouse=True)
def _english_ui():
    prev = i18n.get_language()
    i18n.set_language("en")
    yield
    i18n.set_language(prev)


def _wizard_step_calls(path: str):
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "_wizard_step"]


@pytest.mark.parametrize("path", WIZARDS)
def test_every_wizard_step_passes_a_path(path):
    calls = _wizard_step_calls(path)
    assert calls, f"{path} has no _wizard_step calls to check"
    missing = [c.lineno for c in calls
               if not any(kw.arg == "path" for kw in c.keywords)]
    assert missing == [], f"{path}: _wizard_step without path at lines {missing}"


def test_wizard_step_without_path_still_works():
    """Un-migrated callers elsewhere must keep their old behaviour."""
    import src.cli.menus._helpers as helpers
    sig = inspect.signature(helpers._wizard_step)
    assert sig.parameters["path"].default is None
