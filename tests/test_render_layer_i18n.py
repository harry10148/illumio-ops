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


def test_mod14_html_translates_tier_and_role_in_zh():
    """End-to-end: mod14 HTML output contains zh tier/role/asset_type labels in zh_TW."""
    import pandas as pd
    from src.report.exporters.html_exporter import HtmlExporter
    from src.report.exporters.report_i18n import STRINGS as _STRINGS

    # Two scored apps exercising every value-i18n column at once.
    scored = pd.DataFrame([
        {
            "app_env_key": "alpha|prod",
            "tier": "Tier-1 Critical",
            "role": "Identity",
            "asset_type": "Identity Infrastructure",
            "infrastructure_score": 90,
        },
        {
            "app_env_key": "beta|dev",
            "tier": "Tier-3 Shared",
            "role": "Provider",
            "asset_type": "",
            "infrastructure_score": 40,
        },
    ])
    role_summary = pd.DataFrame({"Tier": ["Tier-1 Critical"], "Count": [1]})
    fake_report = {
        "mod14": {
            "total_apps": 2,
            "total_edges": 0,
            "role_summary": role_summary,
            "hub_apps": scored,
            "top_apps": scored,
            "top_edges": pd.DataFrame(),
        },
    }

    exporter = HtmlExporter(fake_report, lang="zh_TW")
    # `_mod14_html` reads `self._s`; mirror what `_build()` would set.
    exporter._s = lambda k: _STRINGS[k].get("zh_TW") or _STRINGS[k]["en"]
    html = exporter._mod14_html()

    # Every value-i18n column gets translated.
    assert "Tier-1 重大" in html, "TIER value did not translate to zh_TW"
    assert "身分" in html, "ROLE 'Identity' did not translate to zh_TW"
    assert "身分基礎架構" in html, "ASSET_TYPE 'Identity Infrastructure' did not translate"
    # English originals must NOT leak when in zh_TW.
    assert "Tier-1 Critical" not in html
    assert "Identity Infrastructure" not in html


def test_mod13_html_translates_severity_in_zh():
    """mod13 recommendations table shows zh severity labels in zh_TW."""
    import pandas as pd
    from src.report.exporters.html_exporter import HtmlExporter
    from src.report.exporters.report_i18n import STRINGS as _STRINGS

    fake_report = {
        "mod13": {
            "total_score": 0,
            "grade": "F",
            "factor_table": pd.DataFrame(),
            "app_env_scores": pd.DataFrame(),
            "enforcement_mode_distribution": {},
            "recommendations": pd.DataFrame([
                {
                    "Priority": "P1",
                    "App (Env)": "alpha|prod",
                    "App Env Key": "alpha|prod",
                    "Issue": "Low Coverage",
                    "Action": "Tighten enforcement",
                    "Action Code": "ACT_001",
                    "Severity": "CRITICAL",
                },
            ]),
        },
    }

    exporter = HtmlExporter(fake_report, lang="zh_TW")
    # `_mod13_html` reads `self._s`; mirror what `_build()` would set.
    exporter._s = lambda k: _STRINGS[k].get("zh_TW") or _STRINGS[k]["en"]
    html = exporter._mod13_html()

    # Severity zh label present, English absent in cell content
    assert "嚴重" in html, "SEVERITY 'CRITICAL' did not translate to zh_TW"
    # Don't leak as visible cell value (header may still say Severity → 嚴重度)
    assert ">CRITICAL<" not in html, "raw English CRITICAL leaked into cell text"
    # Badge styling must still be keyed off the original English token.
    assert "badge-CRITICAL" in html, "severity badge class lost after translation"
