"""Render-layer i18n: cell value translation in render_df_table."""
from __future__ import annotations

import pandas as pd

from src.report.exporters.report_i18n import STRINGS
from src.report.exporters.table_renderer import render_df_table


def test_value_i18n_maps_translates_zh_cell():
    """Stable English cell values resolve via i18n key in zh_TW."""
    STRINGS["rpt_test_tier_1"] = {"en": "Tier-1 Critical", "zh_TW": "Tier-1 重大"}
    df = pd.DataFrame({"Tier": ["Tier-1 Critical"]})
    html = render_df_table(
        df,
        col_i18n={},
        value_i18n_maps={"Tier": {"Tier-1 Critical": "rpt_test_tier_1"}},
        lang="zh_TW",
    )
    assert "Tier-1 重大" in html
    assert "Tier-1 Critical" not in html


def test_value_i18n_maps_passthrough_on_unknown_value():
    """Cell values not in the map render as-is (stable behavior for new enums)."""
    df = pd.DataFrame({"Tier": ["Tier-99 Unknown"]})
    html = render_df_table(
        df,
        col_i18n={},
        value_i18n_maps={"Tier": {"Tier-1 Critical": "rpt_test_tier_1"}},
        lang="zh_TW",
    )
    assert "Tier-99 Unknown" in html


def test_value_i18n_maps_falls_back_to_en_when_zh_missing():
    """If STRINGS entry has no zh_TW value, en value renders (matches existing col_i18n behavior)."""
    STRINGS["rpt_test_only_en"] = {"en": "Identity", "zh_TW": ""}
    df = pd.DataFrame({"Role": ["Identity"]})
    html = render_df_table(
        df,
        col_i18n={},
        value_i18n_maps={"Role": {"Identity": "rpt_test_only_en"}},
        lang="zh_TW",
    )
    assert "Identity" in html


def test_value_i18n_maps_does_not_affect_other_columns():
    """Translation only applies to columns listed in value_i18n_maps."""
    STRINGS["rpt_test_role_id"] = {"en": "Identity", "zh_TW": "身分"}
    df = pd.DataFrame({
        "Role": ["Identity"],
        "Other": ["Identity"],
    })
    html = render_df_table(
        df,
        col_i18n={},
        value_i18n_maps={"Role": {"Identity": "rpt_test_role_id"}},
        lang="zh_TW",
    )
    # Role cell translated; Other cell stays English
    assert "<td>身分</td>" in html
    assert "<td>Identity</td>" in html


def test_value_i18n_maps_optional_argument():
    """Existing callers (no value_i18n_maps) keep working — backwards compat."""
    df = pd.DataFrame({"x": [1]})
    html = render_df_table(df, col_i18n={}, lang="en")
    assert "<table" in html


def test_value_i18n_constants_resolve_to_real_strings():
    """Every map value must point to an existing STRINGS entry with non-empty en."""
    from src.report.exporters.report_i18n import (
        STRINGS,
        TIER_VALUE_I18N,
        ROLE_VALUE_I18N,
        ASSET_TYPE_VALUE_I18N,
        SEVERITY_VALUE_I18N,
        MOD01_METRIC_VALUE_I18N,
    )
    for label, name in [
        ("TIER", TIER_VALUE_I18N),
        ("ROLE", ROLE_VALUE_I18N),
        ("ASSET_TYPE", ASSET_TYPE_VALUE_I18N),
        ("SEVERITY", SEVERITY_VALUE_I18N),
        ("MOD01_METRIC", MOD01_METRIC_VALUE_I18N),
    ]:
        for stable_en, key in name.items():
            entry = STRINGS.get(key)
            assert entry is not None, f"{label} maps {stable_en!r} → missing key {key!r}"
            assert entry.get("en"), f"{label}.{key} has empty en value"
            assert entry.get("zh_TW"), f"{label}.{key} has empty zh_TW value"
