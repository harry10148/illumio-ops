"""Phase 5 精簡計劃 Task 4（spec J1）：PU unused 卡片 HTML 上限 50 列。

cap 只加在 `_mod03_html` 呼叫 `_rule_cards_html` 前（unused_df.head(50)）；
`_rule_cards_html` 本身共用於 mod02 hit 卡片，hit 卡片不受影響（反例驗證）。
"""
import pandas as pd
import pytest


def _make_unused_df(n: int) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Ruleset": "default",
            "No": i,
            "Rule ID": f"unused-{i:03d}",
            "Type": "Allow",
            "Description": "old broad allow",
            "Source": "Any",
            "Destination": "Any",
            "Services": "All Services",
            "Enabled": True,
            "Created At": "2026-01-01",
            "Observed Hit Ports": "None in lookback",
        }
        for i in range(1, n + 1)
    ])


def _make_hit_df(n: int) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Ruleset": "default",
            "No": i,
            "Rule ID": f"hit-{i:03d}",
            "Type": "Allow",
            "Description": "allow web to db",
            "Source": "web",
            "Destination": "db",
            "Services": "TCP/443",
            "Enabled": True,
            "Hit Count": 100 + i,
            "Top Hit Ports": "443/tcp",
        }
        for i in range(1, n + 1)
    ])


@pytest.fixture
def exporter_factory():
    from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter

    def _make(results: dict):
        return PolicyUsageHtmlExporter(results, lang="en")

    return _make


def test_mod03_html_caps_unused_cards_at_50(exporter_factory):
    """60 列 unused_df：HTML 只含前 50 列的 rule id，第 51 筆不在，truncated 註記含 60。"""
    unused_df = _make_unused_df(60)
    exporter = exporter_factory({
        "mod03": {"unused_df": unused_df, "record_count": 60, "caveat": ""},
    })
    html = exporter._mod03_html()

    assert "unused-001" in html
    assert "unused-050" in html
    assert "unused-051" not in html
    assert "unused-060" not in html
    assert "Showing first 50 of 60" in html


def test_mod03_html_keeps_original_note_at_or_below_50(exporter_factory):
    """<=50 列時維持原「{count} rows」註記，不出現 truncated 文案。"""
    unused_df = _make_unused_df(10)
    exporter = exporter_factory({
        "mod03": {"unused_df": unused_df, "record_count": 10, "caveat": ""},
    })
    html = exporter._mod03_html()

    assert "unused-001" in html
    assert "unused-010" in html
    assert "10 rows" in html
    assert "Showing first 50 of" not in html


def test_mod02_html_renders_all_hit_cards_without_cap(exporter_factory):
    """反例：mod02 hit 卡片共用 `_rule_cards_html`，60 列全渲染，不受 unused cap 影響。"""
    hit_df = _make_hit_df(60)
    exporter = exporter_factory({
        "mod02": {"hit_df": hit_df, "top_ports_df": None, "record_count": 60},
    })
    html = exporter._mod02_html()

    assert "hit-001" in html
    assert "hit-050" in html
    assert "hit-051" in html
    assert "hit-060" in html
