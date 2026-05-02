"""Golden-output snapshot test for the H6 refactor.

Compares catalog constants from src.settings against a baseline captured
before the refactor. Deleted in Task 12 once the refactor is verified complete.
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

_BASELINE_PATH = Path(__file__).parent / "_settings_catalog_baseline.json"


def _baseline() -> dict:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("symbol", [
    "FULL_EVENT_CATALOG",
    "ACTION_EVENTS",
    "SEVERITY_FILTER_EVENTS",
    "DISCOVERY_EVENTS",
    "EVENT_DESCRIPTION_KEYS",
    "EVENT_TIPS_KEYS",
])
def test_catalog_symbol_matches_baseline(symbol):
    from src import settings as s
    actual = getattr(s, symbol)
    expected = _baseline()[symbol]
    if isinstance(expected, dict):
        drifted = {k for k in set(expected) | set(actual) if expected.get(k) != actual.get(k)}
        assert not drifted, (
            f"{symbol} drifted from baseline on keys: {list(drifted)[:5]}"
        )
    else:
        assert actual == expected, (
            f"{symbol} drifted: got {len(actual)} items, expected {len(expected)}"
        )
