"""The audit report's tables printed their raw column ids in both languages.

Every one of these columns already had a translation — rpt_col_timestamp is
"時間", rpt_col_event_type is "事件類型" — but COL_I18N is keyed by display name
and the audit tables carry snake_case ids, so nothing ever matched and the zh
report showed TIMESTAMP / EVENT_TYPE / PARSER_NOTES beside its Chinese headings.

The fix is the mapping, not new strings.
"""
from __future__ import annotations

import pytest

from src.report.exporters.report_i18n import COL_I18N
from src.i18n import t

AUDIT_COLUMNS = [
    "timestamp", "event_type", "user", "actor", "src_ip", "action",
    "notification_detail", "severity", "parser_notes", "target_name",
    "resource_name", "agent_hostname", "status",
]


@pytest.mark.parametrize("column", AUDIT_COLUMNS)
def test_audit_column_has_an_i18n_mapping(column):
    assert column in COL_I18N, f"{column} falls through to its raw id"


@pytest.mark.parametrize("column", AUDIT_COLUMNS)
def test_the_mapped_key_resolves_in_both_languages(column):
    """A mapping pointing at a missing key would render the humanised key name."""
    key = COL_I18N[column]
    for lang in ("en", "zh_TW"):
        value = t(key, lang=lang)
        assert value and value != key
        # the humanise fallback turns rpt_col_event_type into "Rpt Col Event Type"
        assert not value.startswith("Rpt Col")
