"""
Detail table for rules with zero observed traffic hits in the lookback period.
"""
from __future__ import annotations

from collections import Counter

from loguru import logger
import pandas as pd

from src.i18n import t
from src.report.analysis.policy_usage.pu_mod02_hit_detail import _resolve_actors, _resolve_services

_MAX_ROWS = 1000

_CAVEAT_EN = (
    "Rules listed here had no observed traffic hits in the selected lookback window. "
    "This does not automatically mean the rules are safe to remove because the PCE traffic "
    "retention window, low-frequency workloads, or exceptional failover paths may hide valid usage."
)

# 每筆規則的查詢結果狀態。查詢失敗/逾時的規則同樣「不在 hit 名單裡」，但那是
# 「不知道」而不是「沒用到」——不標記就會跟真正未使用的規則混在一起，操作者
# 會照著這張表刪掉實際上還在承載流量的規則。
_STATUS_UNUSED = "Unused"
_STATUS_FAILED = "Query Failed"
_STATUS_PENDING = "Query Pending"
_HIT_PORTS_UNKNOWN = "Usage unknown (traffic query did not complete)"

def _detail_hrefs(execution_stats: dict, key: str) -> set:
    return {
        str(item.get("rule_href", ""))
        for item in execution_stats.get(key, []) or []
        if isinstance(item, dict) and item.get("rule_href")
    }

def pu_unused_detail(
    baseline_rules: list,
    ruleset_map: dict,
    hit_rule_hrefs: set,
    execution_stats: dict | None = None,
    api_client=None,
    *,
    lang: str = "en",
) -> dict:
    """Build the unused-rules detail table."""
    execution_stats = execution_stats or {}
    hit_rule_port_details = {
        str(item.get("rule_href", "")): item
        for item in execution_stats.get("hit_rule_port_details", []) or []
        if item.get("rule_href")
    }
    failed_hrefs = _detail_hrefs(execution_stats, "failed_rule_details")
    pending_hrefs = _detail_hrefs(execution_stats, "pending_rule_details")

    rows = []
    unused_by_ruleset: Counter = Counter()
    indeterminate_count = 0
    for rule in baseline_rules:
        href = rule.get("href", "")
        if href in hit_rule_hrefs:
            continue
        if href in failed_hrefs:
            status = _STATUS_FAILED
        elif href in pending_hrefs:
            status = _STATUS_PENDING
        else:
            status = _STATUS_UNUSED
        row = _build_unused_row(rule, ruleset_map, hit_rule_port_details.get(href, {}),
                                api_client, status=status)
        if status == _STATUS_UNUSED:
            unused_by_ruleset[row.get("Ruleset", "")] += 1
        else:
            indeterminate_count += 1
        rows.append(row)

    rows.sort(key=lambda r: (r.get("Ruleset", ""), r.get("No", 0)))
    total_unused = len(rows)  # full count BEFORE the display/export cap
    rows = rows[:_MAX_ROWS]

    columns = [
        "Ruleset",
        "No",
        "Rule ID",
        "Type",
        "Status",
        "Description",
        "Destination",
        "Source",
        "Services",
        "Observed Hit Ports",
        "Enabled",
        "Created At",
    ]
    unused_df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)

    caveat = t("rpt_pu_unused_caveat", default=_CAVEAT_EN, lang=lang)
    if indeterminate_count:
        caveat = caveat + " " + t("rpt_pu_unused_indeterminate_note", lang=lang,
                                  n=indeterminate_count)

    return {
        "unused_df": unused_df,
        "record_count": len(rows),
        "total_unused": total_unused,  # full count for accurate truncation disclosure
        # 未截斷的每-ruleset 未使用規則計數：executive summary 的「Top rulesets」
        # 若改從截斷後的表格重數，字母序在後的 ruleset 會整個消失。
        "unused_by_ruleset": dict(unused_by_ruleset),
        "confirmed_unused": sum(unused_by_ruleset.values()),
        "indeterminate_count": indeterminate_count,
        "caveat": caveat,
    }

def _build_unused_row(rule: dict, ruleset_map: dict, port_detail: dict, api_client,
                      *, status: str = _STATUS_UNUSED) -> dict:
    rs_href = rule.get("_ruleset_href", "")
    rs_name = ruleset_map.get(rs_href, rule.get("_ruleset_name", rs_href))
    rs_id = rule.get("_ruleset_id", "")
    rule_id = rule.get("_rule_id", "")
    rule_no = rule.get("_rule_no", "")

    providers = _resolve_actors(rule.get("providers", []), api_client)
    consumers = _resolve_actors(rule.get("consumers", []), api_client)
    services = _resolve_services(rule.get("ingress_services", []), api_client)

    created_at = rule.get("created_at", "")
    if created_at and "T" in created_at:
        created_at = created_at[:10]

    desc = rule.get("description", "") or "No description"
    ruleset_label = f"{rs_name} ({rs_id})" if rs_id else rs_name
    observed_hit_ports = str(port_detail.get("top_hit_ports", "") or "").strip() or "None in lookback"
    if status != _STATUS_UNUSED:
        # 查詢沒跑完就沒有「觀測到 0 次命中」這回事，不可寫成 None in lookback。
        observed_hit_ports = _HIT_PORTS_UNKNOWN

    return {
        "No": rule_no,
        "Rule ID": rule_id,
        "Type": rule.get("_rule_type", "Allow"),
        "Status": status,
        "Description": desc,
        "Ruleset": ruleset_label,
        "Destination": providers,
        "Source": consumers,
        "Services": services,
        "Observed Hit Ports": observed_hit_ports,
        "Enabled": rule.get("enabled", True),
        "Created At": created_at,
    }
