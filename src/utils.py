"""Backwards-compatibility shim for legacy `from src.utils import X`.

The real homes are now:
- src/cli/_render.py — TUI/terminal helpers (Colors, safe_input, draw_panel,
  draw_table, Spinner, format_unit, progress_bar, etc.)
- src/loguru_config.py — logger setup (setup_logger / setup_loguru)
- loguru.logger — logger instance

This module re-exports the public names so existing call sites (~20 files
across src/ and tests/) keep working without churn. Direct-import migration
to the new modules is deferred to a follow-up.
"""
from __future__ import annotations

import sys  # re-exported: tests do monkeypatch.setattr(utils.sys, ...)

from loguru import logger  # re-exported: many call sites import logger from src.utils

# Public TUI helpers (formerly defined here, now in src.cli._render).
from src.cli._render import (  # noqa: F401
    ANSI_ESCAPE,
    Colors,
    Spinner,
    draw_panel,
    draw_table,
    format_unit,
    get_last_input_action,
    get_terminal_width,
    get_visible_width,
    pad_string,
    progress_bar,
    safe_input,
)

# Private helpers a couple of tests reach for via the src.utils namespace
# (test_utils_rich_backed.py patches utils_mod._stdout_is_tty / _ansi).
from src.cli._render import (  # noqa: F401
    _ansi,
    _set_last_input_action,
    _stdout_is_tty,
)

# Logger setup (formerly defined here, now in src.loguru_config).
from src.loguru_config import setup_logger  # noqa: F401

__all__ = [
    "ANSI_ESCAPE",
    "Colors",
    "Spinner",
    "draw_panel",
    "draw_table",
    "format_unit",
    "get_last_input_action",
    "get_terminal_width",
    "get_visible_width",
    "logger",
    "pad_string",
    "progress_bar",
    "safe_input",
    "setup_logger",
    "sys",
]
