"""Verify utils.py public API still works after rich migration.

These tests are the safety net for the wrapper strategy: every
existing caller (446 occurrences across 10 files) uses Colors.X,
draw_panel(), Spinner, safe_input — the names and semantics must
survive the rich rewrite.
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from src.utils import Colors, draw_panel, Spinner


def test_colors_constants_still_exist():
    """Every Color used in the codebase must still be importable."""
    # Sampled from grep: Colors.FAIL, .WARNING, .CYAN, .GREEN, .BLUE,
    # .BOLD, .ENDC, .DARK_GRAY are in hot paths.
    for name in ("FAIL", "WARNING", "CYAN", "GREEN", "BLUE",
                 "BOLD", "ENDC", "DARK_GRAY", "RED"):
        assert hasattr(Colors, name), f"Colors.{name} missing after migration"


def test_colors_values_are_strings():
    """Colors.X must still be usable in f-strings: f'{Colors.FAIL}x{Colors.ENDC}'."""
    for name in ("FAIL", "WARNING", "GREEN", "ENDC"):
        assert isinstance(getattr(Colors, name), str)


def test_draw_panel_renders_title_and_lines(capsys):
    """draw_panel must print title + all given lines to stdout."""
    draw_panel("Test Title", ["line one", "line two", "line three"])
    captured = capsys.readouterr()
    assert "Test Title" in captured.out
    assert "line one" in captured.out
    assert "line two" in captured.out
    assert "line three" in captured.out


def test_draw_panel_handles_empty_lines(capsys):
    """Empty line list still renders a panel with the title."""
    draw_panel("Empty", [])
    captured = capsys.readouterr()
    assert "Empty" in captured.out


def test_draw_panel_honors_separator_marker(capsys):
    """'-' as a line marker is used across the codebase as a divider."""
    draw_panel("With Divider", ["top", "-", "bottom"])
    captured = capsys.readouterr()
    assert "top" in captured.out
    assert "bottom" in captured.out


def test_spinner_enters_and_exits_cleanly():
    """Spinner must be usable as a context manager without raising."""
    with Spinner("working..."):
        pass  # should not raise


def test_safe_input_returns_stripped_str():
    """safe_input with str type returns stripped input."""
    from src.utils import safe_input
    with patch("builtins.input", return_value="  hello  "):
        result = safe_input("prompt", str)
    assert result == "hello"


def test_safe_input_returns_int_from_valid_input():
    """safe_input with int type + range validates input."""
    from src.utils import safe_input
    with patch("builtins.input", return_value="3"):
        result = safe_input("prompt", int, range(0, 10))
    assert result == 3


def test_safe_input_returns_none_on_empty_with_int_type():
    """Empty int input returns None with action='empty' so callers can apply defaults."""
    from src.utils import get_last_input_action, safe_input
    with patch("builtins.input", return_value=""):
        result = safe_input("prompt", int, range(0, 10))
    assert result is None
    assert get_last_input_action() == "empty"


def test_spinner_update_does_not_raise():
    """Spinner.update() is a post-plan enhancement; must be safe to call."""
    from src.utils import Spinner
    with Spinner("initial") as s:
        # update() should accept a new message without raising
        s.update("in progress")
        s.update("still working")


def test_colors_fail_is_non_empty_when_tty(monkeypatch):
    """Regression: _ansi/_make_ansi_codes must produce SGR bytes when stdout is a TTY.

    This guards against a silent rich private API break — tests run non-TTY
    where Colors.FAIL is legitimately empty, so a broken _ansi would still
    pass all other tests.
    """
    from rich.style import Style as _RichStyle
    # _ansi/_stdout_is_tty live in src.cli._render after the L8 refactor;
    # src.utils still re-exports them for back-compat.
    import src.cli._render as render_mod
    # Bypass the Colors class and test _ansi directly with a TTY mock
    with patch.object(render_mod, "_stdout_is_tty", return_value=True):
        result = render_mod._ansi(_RichStyle(color="red"))
    assert result != "", "_ansi returned empty even when TTY — _make_ansi_codes broken"
    assert "\033[" in result, f"expected ANSI SGR, got {result!r}"
