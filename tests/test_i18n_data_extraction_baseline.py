"""Golden-output snapshot test for the H4 refactor.

Compares get_messages('en') and get_messages('zh_TW') against a baseline
captured from the pre-refactor src/i18n.py. Once H4 is complete and the
data has fully moved into src/i18n/data/*.json, this file is removed
(see Task 8). Until then, every refactor task must leave this test green.
"""
from __future__ import annotations
import json
from pathlib import Path

from src.i18n import get_messages

_BASELINE_PATH = Path(__file__).parent / "_i18n_baseline.json"


def _baseline() -> dict[str, dict[str, str]]:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def test_en_output_matches_baseline():
    expected = _baseline()["en"]
    actual = get_messages("en")
    diff = {
        k: (expected.get(k, "<missing>"), actual.get(k, "<missing>"))
        for k in set(expected) | set(actual)
        if expected.get(k) != actual.get(k)
    }
    assert not diff, f"en drift on {len(diff)} keys: {dict(list(diff.items())[:5])}"


def test_zh_tw_output_matches_baseline():
    expected = _baseline()["zh_TW"]
    actual = get_messages("zh_TW")
    diff = {
        k: (expected.get(k, "<missing>"), actual.get(k, "<missing>"))
        for k in set(expected) | set(actual)
        if expected.get(k) != actual.get(k)
    }
    assert not diff, f"zh_TW drift on {len(diff)} keys: {dict(list(diff.items())[:5])}"
