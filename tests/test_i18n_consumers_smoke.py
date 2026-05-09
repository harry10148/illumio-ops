"""Phase 1 smoke: every STRINGS consumer renders without error in en + zh_TW."""
from __future__ import annotations

import pandas as pd
import pytest

from src.report.exporters.report_i18n import STRINGS

CONSUMER_KEYS_TO_PROBE = [
    "rpt_generated",
    "rpt_kicker_traffic",
    "rpt_pill_flows",
    "rpt_col_action",
    "rpt_no_records",
    "rpt_table_hint",
]


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
@pytest.mark.parametrize("key", CONSUMER_KEYS_TO_PROBE)
def test_strings_subscript_get_pattern(key: str, lang: str) -> None:
    """The 9 consumer files use STRINGS[k].get(lang) or STRINGS[k]['en']."""
    entry = STRINGS[key]
    val = entry.get(lang) or entry["en"]
    assert isinstance(val, str) and val
    assert not val.startswith("[MISSING:"), f"{key} at {lang} returned MISSING marker"


def test_table_renderer_consumes_no_data_key() -> None:
    """table_renderer.py uses _STRINGS[no_data_key].get(lang) at line 25."""
    from src.report.exporters.table_renderer import render_df_table

    empty_df = pd.DataFrame()
    html_en = render_df_table(empty_df, col_i18n={}, no_data_key="rpt_no_records", lang="en")
    html_zh = render_df_table(empty_df, col_i18n={}, no_data_key="rpt_no_records", lang="zh_TW")
    assert "No records" in html_en
    assert "沒有記錄" in html_zh
