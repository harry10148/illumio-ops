"""Unused-rules table 必須把「查詢沒跑完」與「確定未使用」分開，
executive summary 的 Top rulesets 必須用未截斷的計數。

Audit bug 1: batch_get_rule_traffic_counts 對查詢失敗/逾時的規則不會加進
hit_hrefs，pu_unused_detail 就把它們一律當成 unused 列出，操作者會照表刪掉
實際上還在承載流量的規則。
Audit bug 2: pu_executive_summary 從已截斷（_MAX_ROWS=1000、且按 Ruleset
字母序排過）的表格重數，字母序在後的 ruleset 會整個從排名消失。
"""
from __future__ import annotations

from src.report.analysis.policy_usage.pu_mod00_executive import pu_executive_summary
from src.report.analysis.policy_usage.pu_mod03_unused_detail import (
    _MAX_ROWS,
    pu_unused_detail,
)


def _rule(href, ruleset="RS-A", no=1):
    return {
        "href": href,
        "_ruleset_href": "/rule_sets/1",
        "_ruleset_name": ruleset,
        "_ruleset_id": "1",
        "_rule_id": href.rsplit("/", 1)[-1],
        "_rule_no": no,
        "_rule_type": "Allow",
        "providers": [],
        "consumers": [],
        "ingress_services": [],
    }


def test_failed_query_rule_is_not_reported_as_plain_unused():
    rules = [_rule("/sec_rules/1", no=1), _rule("/sec_rules/2", no=2)]
    stats = {"failed_rule_details": [{"rule_href": "/sec_rules/2"}]}
    out = pu_unused_detail(rules, {}, set(), stats, None)

    df = out["unused_df"]
    by_href = {r["Rule ID"]: r for r in df.to_dict("records")}
    assert by_href["1"]["Status"] == "Unused"
    assert by_href["2"]["Status"] == "Query Failed"
    assert "None in lookback" not in by_href["2"]["Observed Hit Ports"]
    assert out["indeterminate_count"] == 1
    assert out["confirmed_unused"] == 1
    assert out["unused_by_ruleset"] == {"RS-A (1)": 1}


def test_pending_query_rule_is_marked_pending():
    rules = [_rule("/sec_rules/1")]
    stats = {"pending_rule_details": [{"rule_href": "/sec_rules/1"}]}
    out = pu_unused_detail(rules, {}, set(), stats, None)
    assert out["unused_df"].iloc[0]["Status"] == "Query Pending"
    assert out["confirmed_unused"] == 0
    assert out["indeterminate_count"] == 1


def test_caveat_mentions_incomplete_queries_only_when_present():
    rules = [_rule("/sec_rules/1")]
    clean = pu_unused_detail(rules, {}, set(), {}, None)
    dirty = pu_unused_detail(
        rules, {}, set(), {"failed_rule_details": [{"rule_href": "/sec_rules/1"}]}, None)
    assert len(dirty["caveat"]) > len(clean["caveat"])


def test_top_rulesets_ranking_survives_the_row_cap():
    """ZZ-Legacy 的未使用規則最多，但字母序在最後、會被 _MAX_ROWS 截掉。"""
    rules = []
    for i in range(_MAX_ROWS + 10):
        rules.append(_rule(f"/sec_rules/a{i}", ruleset="AA-Sandbox", no=i))
    for i in range(50):
        rules.append(_rule(f"/sec_rules/z{i}", ruleset="ZZ-Legacy", no=i))

    mod03 = pu_unused_detail(rules, {}, set(), {}, None)
    assert len(mod03["unused_df"]) == _MAX_ROWS  # 表格仍截斷
    assert "ZZ-Legacy (1)" not in set(mod03["unused_df"]["Ruleset"])  # 被截掉

    summary = pu_executive_summary(
        {"mod01": {"total_rules": 2000, "hit_count": 940, "unused_count": 1060,
                   "hit_rate_pct": 47.0},
         "mod03": mod03,
         "meta": {"execution_stats": {}}},
        lookback_days=30,
    )
    top = summary["attention_items"][0]
    assert top["ruleset"] == "AA-Sandbox (1)"
    ranked = {item["ruleset"]: item["unused_count"] for item in summary["attention_items"]}
    assert ranked["ZZ-Legacy (1)"] == 50, "字母序在後的 ruleset 不得從排名消失"
    assert ranked["AA-Sandbox (1)"] == _MAX_ROWS + 10, "計數必須是截斷前的真值"


def test_indeterminate_rules_do_not_inflate_ruleset_ranking():
    rules = [_rule(f"/sec_rules/{i}", ruleset="RS-A", no=i) for i in range(5)]
    stats = {"failed_rule_details": [{"rule_href": "/sec_rules/0"},
                                     {"rule_href": "/sec_rules/1"}]}
    out = pu_unused_detail(rules, {}, set(), stats, None)
    assert out["unused_by_ruleset"] == {"RS-A (1)": 3}
