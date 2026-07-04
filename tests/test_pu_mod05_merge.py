"""Phase 5 精簡計劃 Task 5（spec J2）：PU mod05 三表合併 + 風險類型欄。

本模組（pu_mod05_draft_pd.py）先前零測試——本檔同時鎖定既有三 group 過濾語意
（避免合併重構意外改變分類邏輯）與新增的 merged_top_pairs / 單表渲染行為。
"""
import pandas as pd
import pytest

from src.report.analysis.policy_usage.pu_mod05_draft_pd import pu_draft_pd_summary
from src.report.exporters.report_i18n import STRINGS


def _row(draft_pd, policy_decision="allowed", src="src-a", dst="dst-a", port=443, conns=1):
    return {
        "policy_decision": policy_decision,
        "draft_policy_decision": draft_pd,
        "src": {"workload": {"name": src}},
        "dst": {"workload": {"name": dst}},
        "service": {"port": port},
        "num_connections": conns,
    }


def _synthetic_rows():
    return [
        # visibility_risk（group A）：draft_policy_decision 為兩個 boundary/override 子型
        _row("potentially_blocked_by_boundary", src="vis-1", conns=5),
        _row("potentially_blocked_by_override_deny", src="vis-2", conns=3),
        # draft_conflicts（group B）
        _row("blocked_by_override_deny", src="conf-1", conns=7),
        _row("allowed_across_boundary", src="conf-2", conns=2),
        # draft_coverage（group C）：需 policy_decision=potentially_blocked 且 draft 落在 allowed/blocked_by_boundary
        _row("allowed", policy_decision="potentially_blocked", src="cov-1", conns=4),
        _row("blocked_by_boundary", policy_decision="potentially_blocked", src="cov-2", conns=6),
        # 應被排除：draft_policy_decision=allowed 但 policy_decision 不是 potentially_blocked
        _row("allowed", policy_decision="allowed", src="excluded-1", conns=99),
    ]


class TestGroupSemanticsLocked:
    """三 group 既有語意鎖定：合併重構不得改變既有過濾邏輯。"""

    def test_visibility_risk_group_membership(self):
        result = pu_draft_pd_summary(_synthetic_rows())
        assert result["visibility_risk"]["total"] == 2
        assert result["visibility_risk"]["by_subtype"] == {
            "potentially_blocked_by_boundary": 1,
            "potentially_blocked_by_override_deny": 1,
        }

    def test_draft_conflicts_group_membership(self):
        result = pu_draft_pd_summary(_synthetic_rows())
        assert result["draft_conflicts"]["total"] == 2
        assert result["draft_conflicts"]["by_subtype"] == {
            "blocked_by_override_deny": 1,
            "allowed_across_boundary": 1,
        }

    def test_draft_coverage_group_membership(self):
        result = pu_draft_pd_summary(_synthetic_rows())
        assert result["draft_coverage"]["total"] == 2
        assert result["draft_coverage"]["by_subtype"] == {
            "allowed": 1,
            "blocked_by_boundary": 1,
        }

    def test_excluded_row_not_counted_anywhere(self):
        """draft_policy_decision=allowed 但 policy_decision!=potentially_blocked：不屬於任何 group。"""
        result = pu_draft_pd_summary(_synthetic_rows())
        assert result["total"] == 6  # 7 筆合成資料扣掉 1 筆排除
        for group in ("visibility_risk", "draft_conflicts", "draft_coverage"):
            assert "excluded-1" not in result[group]["top_pairs"].get("Src", pd.Series(dtype=object)).values


class TestMergedTopPairs:
    def test_merged_top_pairs_has_risk_type_column(self):
        result = pu_draft_pd_summary(_synthetic_rows())
        merged = result["merged_top_pairs"]
        assert "Risk Type" in merged.columns
        assert set(merged.columns) == {"Risk Type", "Src", "Dst", "Port", "Draft Decision", "Connections"}

    def test_merged_top_pairs_labels_match_group(self):
        result = pu_draft_pd_summary(_synthetic_rows())
        merged = result["merged_top_pairs"]
        vis_rows = merged[merged["Risk Type"] == "Visibility Risk"]
        conf_rows = merged[merged["Risk Type"] == "Draft Conflict"]
        cov_rows = merged[merged["Risk Type"] == "Draft Coverage"]
        assert len(vis_rows) == 2
        assert len(conf_rows) == 2
        assert len(cov_rows) == 2
        assert set(vis_rows["Src"]) == {"vis-1", "vis-2"}
        assert set(conf_rows["Src"]) == {"conf-1", "conf-2"}
        assert set(cov_rows["Src"]) == {"cov-1", "cov-2"}

    def test_merged_top_pairs_each_type_capped_at_20(self):
        rows = [
            _row("blocked_by_override_deny", src=f"conf-{i}", conns=i + 1)
            for i in range(25)
        ]
        result = pu_draft_pd_summary(rows)
        merged = result["merged_top_pairs"]
        conf_rows = merged[merged["Risk Type"] == "Draft Conflict"]
        assert len(conf_rows) <= 20

    def test_merged_top_pairs_connections_descending_within_type(self):
        rows = [
            _row("potentially_blocked_by_boundary", src="vis-a", conns=3),
            _row("potentially_blocked_by_override_deny", src="vis-b", conns=9),
            _row("potentially_blocked_by_boundary", src="vis-c", conns=1),
        ]
        result = pu_draft_pd_summary(rows)
        merged = result["merged_top_pairs"]
        vis_conns = merged[merged["Risk Type"] == "Visibility Risk"]["Connections"].tolist()
        assert vis_conns == sorted(vis_conns, reverse=True)

    def test_existing_group_keys_kept_verbatim(self):
        """三個既有 group key 原樣保留（向後相容），shape 不變。"""
        result = pu_draft_pd_summary(_synthetic_rows())
        for key in ("visibility_risk", "draft_conflicts", "draft_coverage"):
            group = result[key]
            assert set(group.keys()) == {"total", "by_subtype", "top_pairs"}
            assert isinstance(group["top_pairs"], pd.DataFrame)


class TestMod05HtmlSingleMergedTable:
    @pytest.fixture
    def exporter_factory(self):
        from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter

        def _make(mod05: dict, lang: str = "en"):
            exporter = PolicyUsageHtmlExporter({"mod05": mod05}, lang=lang)
            # _mod05_html() reads self._s, which _build() normally wires up;
            # replicate that wiring here to exercise _mod05_html() in isolation.
            exporter._s = lambda k: STRINGS[k].get(lang) or STRINGS[k]["en"]
            return exporter

        return _make

    def test_single_merged_table_heading_appears_once(self, exporter_factory):
        result = pu_draft_pd_summary(_synthetic_rows())
        exporter = exporter_factory(result)
        html = exporter._mod05_html()
        assert html.count("Top At-Risk Flow Pairs") == 1

    def test_pills_for_three_groups_still_present(self, exporter_factory):
        result = pu_draft_pd_summary(_synthetic_rows())
        exporter = exporter_factory(result)
        html = exporter._mod05_html()
        assert "Enforcement Risk (Visibility Mode)" in html
        assert "Draft Policy Conflicts" in html
        assert "Newly Covered in Draft" in html
        assert html.count('class="summary-pill-row"') == 3

    def test_risk_type_values_rendered_in_zh(self, exporter_factory):
        result = pu_draft_pd_summary(_synthetic_rows())
        exporter = exporter_factory(result, lang="zh_TW")
        html = exporter._mod05_html()
        assert "可視性風險" in html
        assert "Draft 衝突" in html
        assert "Draft 覆蓋" in html
        assert "Visibility Risk" not in html
