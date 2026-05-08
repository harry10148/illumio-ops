"""Regression guard: every best-practice event_type maps to a non-default rec.

Failing test means: a new rule was added to src/config.py:_best_practice_rules()
without a corresponding `_REC_I18N_KEYS` entry in src/reporter.py — alerts for
that event_type will silently fall back to alert_rec_default ("Open the Web
GUI to review full event context.") instead of an actionable recommendation.
"""
from __future__ import annotations

import re
from pathlib import Path


def _parse_event_specs() -> list[tuple[str, str]]:
    src = (Path(__file__).resolve().parent.parent / "src" / "config.py").read_text()
    blob = re.search(r"event_specs\s*=\s*\[(.*?)\]\s*\n\s*for", src, re.DOTALL)
    assert blob, "event_specs block not found in src/config.py"
    return re.findall(r'"(rule_[a-z_]+)",\s*"([a-z_,.]+)"', blob.group(1))


def test_all_best_practice_event_types_have_rec_mapping():
    from src.reporter import Reporter

    specs = _parse_event_specs()
    assert specs, "no event_specs parsed — regex/source structure changed?"

    missing: list[tuple[str, str]] = []
    for rule_name, etypes_csv in specs:
        for et in etypes_csv.split(","):
            if et not in Reporter._REC_I18N_KEYS:
                missing.append((rule_name, et))

    assert not missing, (
        f"event_types missing from _REC_I18N_KEYS: {missing}. "
        "Add to src/reporter.py:_REC_I18N_KEYS — otherwise alerts fall back "
        "to alert_rec_default and lose their actionable recommendation."
    )


def test_all_rec_i18n_keys_resolve_to_non_marker_strings():
    """Each _REC_I18N_KEYS value resolves to actual translated text (en + zh)."""
    from src.i18n import t, set_language
    from src.reporter import Reporter

    for lang in ("en", "zh_TW"):
        set_language(lang)
        for event_type, key in Reporter._REC_I18N_KEYS.items():
            value = t(key)
            assert value, f"{lang} {key} ({event_type}) resolved to empty"
            assert not value.startswith("[MISSING:"), (
                f"{lang} {key} ({event_type}) → {value!r}"
            )
