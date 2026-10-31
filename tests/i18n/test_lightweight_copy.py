"""Lightweight mode is the default (spec §6.4, 2026-10-29): wherever it turns a feature off, the words say what
turns it on (反目標 1: a feature that is off never looks like one with nothing to show)."""
import json
from pathlib import Path

import pytest

I18N = Path(__file__).resolve().parents[2] / "illumio_ops" / "i18n"
KEYS = ("detector_state_collection_off", "detector_collection_off", "rule_status_collection_off",
        "focus_title_lightweight", "mode_lightweight_hint")


@pytest.mark.parametrize(("lang", "word"), [("en", "alert"), ("zh_TW", "告警")])
def test_off_features_name_alert_mode(lang, word):
    d = json.loads((I18N / f"{lang}.json").read_text())
    assert [k for k in KEYS if word not in d[k]] == []
