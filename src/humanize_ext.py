"""humanize wrapper that follows the project's i18n language setting.

Falls back gracefully if humanize's zh_TW locale is not available
(humanize currently ships zh_CN; we map zh_TW → zh_CN at runtime).
"""
from __future__ import annotations

import datetime as _dt
import humanize as _humanize

from src.i18n import get_language


_LOCALE_MAP = {
    "en": None,        # default (no activate call)
    "zh_TW": "zh_CN",  # humanize has zh_CN; good enough for zh_TW readers
    "zh_CN": "zh_CN",
}


def _activate_locale() -> None:
    lang = get_language() or "en"
    locale = _LOCALE_MAP.get(lang)
    if locale is None:
        # humanize has no deactivate(); reload to reset
        _humanize.i18n.deactivate()
        return
    try:
        _humanize.i18n.activate(locale)
    except FileNotFoundError:
        # locale files missing; silently fall back to english
        pass


def human_size(n: int) -> str:
    """Format bytes as human-readable, e.g. '3.5 MB'."""
    if n == 0:
        return "0 Bytes"
    return _humanize.naturalsize(n)


def human_time_delta(delta: _dt.timedelta) -> str:
    """Format a timedelta, e.g. '2 hours', '5 minutes', '3 days'."""
    _activate_locale()
    return _humanize.naturaldelta(delta)


def human_number(n: int | float) -> str:
    """Format a number with thousands separator: 12345 -> '12,345'."""
    return _humanize.intcomma(n)


def human_time_ago(past: _dt.datetime) -> str:
    """Format a past datetime as 'X time ago'."""
    _activate_locale()
    now = _dt.datetime.now(past.tzinfo) if past.tzinfo else _dt.datetime.now()
    return _humanize.naturaltime(now - past)
