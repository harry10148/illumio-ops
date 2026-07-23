"""filter key 七層鏈跨層一致性守門（2026-07-23）。

背景：filter key 的傳遞是多層手寫白名單架構（filter-bar.js → actions.py →
analyzer.query_flows → traffic_query capability/殘餘比對 → rules._RULE_FB_KEYS
→ report_generator._obj_filter_keys → object_picker），斷鏈 bug 已重演兩次
（label_group 斷在 actions.py、service/port 斷在 _RULE_FB_KEYS/_OBJECT_FILTER_KEYS）。
本檔以「FilterBar 可序列化的 key 必須在每層存活或有明文豁免」為不變量整鏈鎖死：
未來新增 key 漏接任何一層，這裡直接紅。

豁免集合皆引用程式碼註解出處；改動豁免前先讀該出處確認語意仍成立。
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


# ── 各層抽取器 ──────────────────────────────────────────────────────────────

def _slice(src: str, start_pat: str, end_pat: str) -> str:
    m = re.search(start_pat, src)
    assert m, f"anchor not found: {start_pat}"
    rest = src[m.end():]
    e = re.search(end_pat, rest)
    return rest[:e.start()] if e else rest


def filterbar_serialize_keys() -> set:
    """_objfbSerialize 可產出的 key 全集（結構化展開：cat×dir×neg）。

    展開表對照 filter-bar.js:119-152 的組字規則；下方 sanity 斷言確保
    JS 改了組字規則（新家族/新方向）時這裡會醒來。
    """
    out: set[str] = set()
    for k in ("services", "ports", "process_name", "windows_service_name", "transmission"):
        out |= {k, f"ex_{k}"}
    for k in ("any_label", "any_iplist", "any_workload", "any_ip"):
        out |= {k, f"ex_{k}"}
    for d in ("src", "dst"):
        for fam in ("labels", "label_groups", "iplists", "workloads"):
            out |= {f"{d}_{fam}", f"ex_{d}_{fam}"}
        out |= {f"{d}_ip_in", f"ex_{d}_ip"}
    return out


def actions_params_keys() -> set:
    src = (_ROOT / "src/gui/routes/actions.py").read_text(encoding="utf-8")
    body = _slice(src, r"def api_quarantine_search\(", r"\n    @bp\.route")
    keys = set(re.findall(r'd\.get\("([a-z_]+)"', body))
    return keys - {"source", "mins", "policy_decision", "lang"}


def query_flows_whitelist() -> set:
    src = (_ROOT / "src/analyzer.py").read_text(encoding="utf-8")
    body = _slice(src, r"def query_flows\(", r"\n    def ")
    return set(re.findall(r'params\.get\("([a-z_]+)"', body))


def flow_matches_referenced_keys() -> set:
    """_flow_matches_filters 原始碼中引用到的 key 字串（含 tuple 字面值迴圈）。"""
    from src.api.traffic_query import TrafficQueryBuilder
    src = inspect.getsource(TrafficQueryBuilder._flow_matches_filters)
    return set(re.findall(r"['\"]([a-z_]{3,40})['\"]", src))


def capability_map() -> dict:
    from src.api.traffic_query import _TRAFFIC_FILTER_CAPABILITIES
    return dict(_TRAFFIC_FILTER_CAPABILITIES)


def report_generator_obj_keys() -> set:
    src = (_ROOT / "src/report/report_generator.py").read_text(encoding="utf-8")
    body = _slice(src, r"_obj_filter_keys = \(", r"\)")
    return set(re.findall(r'"([a-z_]+)"', body))


def picker_keys() -> set:
    from src.cli.object_picker import _ANY_FILTER_KEYS
    out: set[str] = set(_ANY_FILTER_KEYS)
    for prefix in ("src", "dst", "ex_src", "ex_dst"):
        out |= {f"{prefix}_labels", f"{prefix}_iplists", f"{prefix}_workloads"}
    out |= {"src_ip_in", "dst_ip_in", "ex_src_ip", "ex_dst_ip",
            "services", "ex_services", "ports", "ex_ports"}
    return out


# ── sanity：展開表沒有偏離 JS 實作 ──────────────────────────────────────────

def test_serialize_expansion_matches_js_source():
    """展開表的每個家族片段必須出現在 _objfbSerialize 原始碼中——JS 改了
    組字規則（family 更名等）時這裡要醒。方向性 key 是 template literal
    （`${ex}${d}_labels`），故比對片段而非完整 key。"""
    src = (_ROOT / "src/static/js/filter-bar.js").read_text(encoding="utf-8")
    body = _slice(src, r"function _objfbSerialize\(", r"\nfunction ")
    fragments = {"_labels", "_label_groups", "_iplists", "_workloads", "_ip_in",
                 "services", "ports", "process_name", "windows_service_name",
                 "transmission", "any_label", "any_iplist", "any_workload", "any_ip"}
    missing = {f for f in fragments if f not in body}
    assert not missing, f"_objfbSerialize 找不到家族片段：{missing}（組字規則變了？同步更新展開表）"
    assert len(filterbar_serialize_keys()) == 38


# ── 不變量 1-8 ─────────────────────────────────────────────────────────────

def test_serialize_keys_survive_actions_whitelist():
    """[1] FilterBar 可序列化的 key 必須全部被 /api/quarantine/search 轉發。"""
    dropped = filterbar_serialize_keys() - actions_params_keys()
    assert not dropped, f"actions.py params dict 靜默丟棄：{sorted(dropped)}"


def test_actions_keys_survive_query_flows_whitelist():
    """[2] actions 轉發的 filter key 必須全部進 analyzer.query_flows 白名單。"""
    dropped = actions_params_keys() - query_flows_whitelist()
    assert not dropped, f"query_flows 白名單靜默丟棄：{sorted(dropped)}"


def test_serialize_keys_all_registered_in_capability_matrix():
    """[3] FilterBar key 必須全部登錄 _TRAFFIC_FILTER_CAPABILITIES
    （未登錄的 key 會落到預設 fallback，語意未經驗證）。"""
    unregistered = filterbar_serialize_keys() - set(capability_map())
    assert not unregistered, f"capability matrix 未登錄：{sorted(unregistered)}"


def test_fallback_capabilities_covered_by_residual_matcher():
    """[4] execution=fallback 的 key 只能靠 _flow_matches_filters 生效——
    殘餘比對沒引用到的 fallback key 等於整條靜默失效。"""
    caps = capability_map()
    fallback = {k for k, v in caps.items() if v.get("execution") == "fallback"}
    # report_only 類（search/sort_by/page…）由報表層處理，不在殘餘比對
    report_only = {k for k, v in caps.items() if v.get("execution") == "report_only"}
    uncovered = fallback - flow_matches_referenced_keys() - report_only
    assert not uncovered, f"fallback key 未被殘餘比對引用：{sorted(uncovered)}"


def test_serialize_keys_accepted_or_explicitly_rejected_by_rules():
    """[5] 規則路徑：每個可序列化 key 要嘛在 _RULE_FB_KEYS（存檔），要嘛在
    _RULE_REJECTED_KEYS（明確 400）——不得靜默消失。label_group 4 key 走
    rejected 是明文設計（rules.py:22-24：規則共用未過濾 stream、無成員展開）。"""
    from src.gui.routes.rules import _RULE_FB_KEYS, _RULE_REJECTED_KEYS
    lost = filterbar_serialize_keys() - set(_RULE_FB_KEYS) - set(_RULE_REJECTED_KEYS)
    assert not lost, f"規則路徑靜默丟棄：{sorted(lost)}"


def test_report_expand_gate_keys_subset_of_object_filter_keys():
    """[6] report_generator._obj_filter_keys（df 展開閘門）必須是
    analyzer._OBJECT_FILTER_KEYS 的子集——閘門認得比對器不認得的 key
    代表展開了卻沒人比對。"""
    from src.analyzer import _OBJECT_FILTER_KEYS
    orphan = report_generator_obj_keys() - set(_OBJECT_FILTER_KEYS)
    assert not orphan, f"df 展開閘門 key 不在物件比對投影中：{sorted(orphan)}"


def test_picker_keys_accepted_by_rules_store():
    """[7] CLI picker 產出的 key 必須全部被規則存檔白名單接受。"""
    from src.gui.routes.rules import _RULE_FB_KEYS
    lost = picker_keys() - set(_RULE_FB_KEYS)
    assert not lost, f"picker 產出 key 不被規則存檔接受：{sorted(lost)}"


def test_cache_unevaluable_keys_match_rules_rejected_keys():
    """[8] label_group 家族兩處聯動：cache-bypass 集合（analyzer）與規則
    拒收集合（rules）必須相等——只改一邊代表另一邊靜默漏。"""
    from src.analyzer import _CACHE_UNEVALUABLE_FILTER_KEYS
    from src.gui.routes.rules import _RULE_REJECTED_KEYS
    diff = set(_CACHE_UNEVALUABLE_FILTER_KEYS) ^ set(_RULE_REJECTED_KEYS)
    assert not diff, f"cache-bypass 與規則拒收集合不同步：{sorted(diff)}"
