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
    """Format bytes as human-readable, e.g. '3.5 MB'.

    進位方式：委派給 ``humanize.naturalsize``，預設是十進位（decimal, 1000 進位，
    例如 1500 bytes -> '1.5 kB'）。用於 GUI 樣板過濾器（見
    ``src/gui/__init__.py`` 的 ``human_size`` Jinja filter），不是給報表用的。

    這與下面的 ``fmt_bytes_auto``（二進位 1024 進位）刻意不統一：兩者的進位基底
    不同，換算結果會不一樣（例如 1500 bytes 這裡是 '1.5 kB'，
    fmt_bytes_auto 是 '1.5 KB'，數值相近但語意不同；到 GB/TB 級距時差異更明顯）。
    若把其中一方改成呼叫另一方，會改變既有輸出格式——GUI 頁面顯示的數字，或是
    mod12_executive_summary 報表既有測試釘住的 'GB'/'TB' 字串（見
    tests/test_report_humanize.py、tests/test_mod12_data_volume_format.py）。
    因此維持兩個獨立入口，僅在此註明差異，不做合併。
    """
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

def fmt_bytes_auto(value, *, input_unit: str = "bytes") -> str:
    """Auto-scale a byte (or MB) count to a human-readable string.

    進位方式：手寫二進位（binary, 1024 進位），供報表模組使用（見
    src/report/analysis/mod12_executive_summary.py 的資料量欄位）。與
    ``human_size``（naturalsize，十進位 1000 進位）刻意不統一，理由與差異說明見
    ``human_size`` 的 docstring。

    >>> fmt_bytes_auto(0)
    '0 B'
    >>> fmt_bytes_auto(1500)
    '1.5 KB'
    >>> fmt_bytes_auto(6062571061).endswith("GB")
    True
    """
    try:
        b = float(value)
    except (TypeError, ValueError):
        return "—"
    if b < 0:
        return "—"
    if input_unit.lower() == "mb":
        b = b * 1024 * 1024
    if b >= 1024 ** 4:
        return f"{b / 1024 ** 4:.2f} TB"
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.2f} GB"
    if b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{int(b)} B"


def human_time_ago(past: _dt.datetime) -> str:
    """Format a past datetime as 'X time ago'."""
    _activate_locale()
    now = _dt.datetime.now(past.tzinfo) if past.tzinfo else _dt.datetime.now()
    return _humanize.naturaltime(now - past)
