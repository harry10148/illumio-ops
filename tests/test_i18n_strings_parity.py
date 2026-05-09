"""Phase 1 contract: STRINGS and t() must agree for every shared key."""
from __future__ import annotations

import inspect

import pytest

from src.i18n import get_messages, t
from src.report.exporters.report_i18n import STRINGS
from src.i18n.engine import EN_MESSAGES


def _lookup_via_t(key: str, lang: str) -> str:
    """Resolve key via t() at the requested lang, race-free.

    Once Task 13 lands a `lang=` kwarg on t(), this prefers that path. Until
    then, falls back to get_messages(lang) which performs the same lookup
    without mutating global state.
    """
    if "lang" in inspect.signature(t).parameters:
        return t(key, lang=lang)
    return get_messages(lang).get(key, key)


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_strings_matches_t_for_all_shared_keys(lang: str) -> None:
    json_keys = set(EN_MESSAGES.keys())
    strings_keys = set(STRINGS.keys())
    shared = json_keys & strings_keys

    assert shared, (
        f"No shared keys between EN_MESSAGES ({len(json_keys)}) "
        f"and STRINGS ({len(strings_keys)}); possible import failure"
    )

    mismatches: list[tuple[str, str, str]] = []
    for key in shared:
        from_strings = STRINGS[key].get(lang) or STRINGS[key]["en"]
        from_t = _lookup_via_t(key, lang)
        if from_strings != from_t:
            mismatches.append((key, from_strings, from_t))

    assert not mismatches, (
        f"{len(mismatches)} keys disagree between STRINGS and t() at lang={lang}. "
        f"First 5: {mismatches[:5]}"
    )
