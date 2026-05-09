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
    # Role column localized; Other column passthrough
    assert html.count("身分") == 1
    assert html.count("Identity") == 1


def test_value_i18n_maps_optional_argument():
    """Existing callers (no value_i18n_maps) keep working — backwards compat."""
    df = pd.DataFrame({"x": [1]})
    html = render_df_table(df, col_i18n={}, lang="en")
    assert "<table" in html
