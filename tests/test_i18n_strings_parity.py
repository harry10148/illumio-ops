"""Phase 1 contract: STRINGS and t() must agree for every shared key."""
from __future__ import annotations

import pytest

from src.i18n import t
from src.report.exporters.report_i18n import STRINGS


@pytest.mark.xfail(reason="Phase 1 migration in progress; removed in Task 7", strict=False)
@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_strings_matches_t_for_all_shared_keys(lang: str) -> None:
    from src.i18n.engine import EN_MESSAGES

    json_keys = set(EN_MESSAGES.keys())
    strings_keys = set(STRINGS.keys())
    shared = json_keys & strings_keys

    mismatches: list[tuple[str, str, str]] = []
    for key in shared:
        from_strings = STRINGS[key].get(lang) or STRINGS[key]["en"]
        # t() in main today does NOT accept a `lang` kwarg yet (added in Task 13).
        # Use set_language()/get_language() if needed, but minimize global mutation.
        # For this baseline test, we only need to compare current behavior.
        if "lang" in t.__code__.co_varnames:
            from_t = t(key, lang=lang)
        else:
            from src.i18n import set_language, get_language
            _prev = get_language()
            try:
                set_language(lang)
                from_t = t(key)
            finally:
                set_language(_prev)
        if from_strings != from_t:
            mismatches.append((key, from_strings, from_t))

    assert not mismatches, (
        f"{len(mismatches)} keys disagree between STRINGS and t() at lang={lang}. "
        f"First 5: {mismatches[:5]}"
    )
