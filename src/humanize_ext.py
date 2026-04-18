"""humanize wrapper that follows the project's i18n language setting.

Falls back gracefully if a locale is not available
(humanize ships zh_HK for traditional Chinese; we map zh_TW → zh_HK at runtime).
"""
from __future__ import annotations

import datetime as _dt
import humanize as _humanize

from src.i18n import get_language

_LOCALE_MAP = {
    "en": None,        # default (no activate call)
    "zh_TW": "zh_HK",  # humanize has zh_HK with traditional characters ("2 小時")
    "zh_CN": "zh_CN",  # simplified characters ("2小时")
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
