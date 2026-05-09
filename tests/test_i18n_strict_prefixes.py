"""Strict prefixes drive [MISSING:key] short-circuit; must load from JSON."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX_PATH = ROOT / "src" / "i18n" / "data" / "strict_prefixes.json"


def test_strict_prefixes_loads() -> None:
    data = json.loads(PREFIX_PATH.read_text(encoding="utf-8"))
    prefixes = set(data["prefixes"])
    assert "gui_" in prefixes
    assert "rpt_" in prefixes
    assert "rule_" in prefixes
    assert len(prefixes) >= 25


def test_strict_prefixes_used_by_engine() -> None:
    from src.i18n.engine import _is_strict_surface_key
    assert _is_strict_surface_key("gui_settings_save")
    assert _is_strict_surface_key("rpt_col_action")
    assert not _is_strict_surface_key("event_label_xyz")  # exception
    assert not _is_strict_surface_key("cat_unmanaged")    # exception
    assert not _is_strict_surface_key("random_key")       # not a strict prefix
