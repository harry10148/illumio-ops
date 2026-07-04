"""
Shared i18n helpers for HTML report exporters.

After Phase 1 migration, STRINGS is a _StringsView that:
  - Stores runtime overlay entries (dynamic writes from this module's bottom loops)
  - Falls back to get_messages() for any key not in the overlay
  - Preserves the dict-like API (subscript, .get, __setitem__, __delitem__,
    __contains__, keys()) that 9 exporter files depend on.
"""
from __future__ import annotations

import os
from typing import Iterator


class _StringsView:
    """Compatibility layer over a runtime overlay + get_messages()-backed JSON."""

    def __init__(self) -> None:
        self._overlay: dict[str, dict[str, str]] = {}

    def __getitem__(self, key: str) -> dict[str, str]:
        if key in self._overlay:
            return self._overlay[key]
        from src.i18n.engine import EN_MESSAGES, get_messages
        if os.getenv("ILLUMIO_OPS_I18N_STRICT") and key not in EN_MESSAGES:
            raise KeyError(f"Missing i18n key: {key}")
        return {
            "en": get_messages("en").get(key, key),
            "zh_TW": get_messages("zh_TW").get(key, key),
        }

    def __setitem__(self, key: str, value: dict[str, str]) -> None:
        self._overlay[key] = value

    def __delitem__(self, key: str) -> None:
        del self._overlay[key]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key in self._overlay:
            return True
        from src.i18n.engine import EN_MESSAGES
        return key in EN_MESSAGES

    def __len__(self) -> int:
        from src.i18n.engine import EN_MESSAGES
        return len(self._overlay) + sum(1 for k in EN_MESSAGES if k not in self._overlay)

    def get(self, key: str, default: dict[str, str] | None = None) -> dict[str, str] | None:
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> Iterator[str]:
        from src.i18n.engine import EN_MESSAGES
        seen: set[str] = set()
        for k in self._overlay:
            seen.add(k)
            yield k
        for k in EN_MESSAGES:
            if k not in seen:
                yield k

    def items(self) -> Iterator[tuple[str, dict[str, str]]]:
        for k in self.keys():
            yield k, self[k]

    def overlay_items(self) -> Iterator[tuple[str, dict[str, str]]]:
        """Yield only the dynamic-write overlay entries — not JSON-backed ones.

        Use this when iterating for prefix-filtering on overlay-resident keys
        (rpt_col_*, rpt_cat_*, rpt_rule_*) to avoid the ~2569-key JSON scan
        that items() does. ~60x faster at module load when callers only need
        overlay entries.
        """
        yield from self._overlay.items()


def _entry(en: str, zh_tw: str | None = None) -> dict[str, str]:
    return {"en": en, "zh_TW": zh_tw or en}


STRINGS: _StringsView = _StringsView()

for key, pair in {
    "ransomware": (
        "Ransomware Exposure",
        "勒索軟體曝險",
        "Traffic patterns related to ransomware propagation and remote control.",
        "聚焦可能與勒索軟體擴散、遠端控制或高風險服務暴露相關的流量模式。",
    ),
    "lateralmovement": (
        "Lateral Movement",
        "lateral movement",
        "Patterns indicating pivoting, discovery, identity abuse, or cross-segment expansion.",
        "聚焦橫向移動、資產探測、帳號濫用與跨區段擴散跡象。",
    ),
    "unmanagedhost": (
        "Unmanaged Hosts",
        "Unmanaged 主機",
        "Risks introduced by hosts operating outside VEN enforcement.",
        "聚焦未受 VEN 管控的主機與其帶來的可視性與控管風險。",
    ),
    "policy": (
        "Policy Coverage",
        "Policy 覆蓋",
        "Coverage gaps and segmentation weaknesses.",
        "聚焦 Policy 覆蓋缺口與分段控管弱點。",
    ),
    "useractivity": (
        "User Activity",
        "使用者活動",
        "Suspicious user behavior and authentication anomalies.",
        "聚焦可疑使用者活動、驗證異常與高風險存取行為。",
    ),
    "bandwidth": (
        "Bandwidth Anomaly",
        "頻寬異常",
        "Large transfer patterns that may indicate staging or exfiltration.",
        "聚焦異常大量傳輸與可能的資料暫存、外洩模式。",
    ),
    "draftpolicy": (
        "Draft Policy",
        "草稿 Policy",
        "Findings from draft-policy simulation: draft deny hits, override denies, "
        "visibility-boundary breaches and draft-vs-reported mismatches.",
        "草稿 Policy 模擬產生的發現：draft deny 命中、override deny、"
        "可視性邊界穿越、draft 與實際回報不一致。",
    ),
}.items():
    name_en, name_zh, desc_en, desc_zh = pair
    STRINGS[f"rpt_cat_{key}_name"] = _entry(name_en, name_zh)
    STRINGS[f"rpt_cat_{key}_desc"] = _entry(desc_en, desc_zh)

for key, zh_text in {
    "B001": "檢查 SMB、RPC、RDP、WinRM 等高風險管理 Port 是否暴露，並優先鎖定高風險目的端。",
    "B002": "檢查 TeamViewer、VNC、NetBIOS 等遠端控制或舊式管理協定的暴露情況。",
    "B003": "檢查測試或可視性用途的流量是否仍停留在生產環境中，避免形成長期例外。",
    "B004": "檢查尚未納入 PCE/VEN Enforcement 的主機與其對外通訊，找出管理盲區。",
    "B005": "檢查跨區段或高風險 Service 是否已被明確 Allow，避免例外規則長期存在。",
    "B006": "檢查 lateral movement 常見 Port 的主要來源、目的端與 Service 組合。",
    "B007": "檢查高風險來源與使用者活動，找出可疑主機或帳號。",
    "B008": "檢查 Bytes/Conn 顯著偏高的流量，快速辨識異常大量傳輸。",
    "B009": "檢查跨環境流量，例如 Production 與 Development 之間的非預期互通。",
    "L001": "檢查常見遠端存取 Service，例如 Telnet、FTP 等是否仍在使用。",
    "L002": "檢查 NetBIOS、DNS、LLMNR、SSDP 等容易被用於探索環境的協定。",
    "L003": "檢查高風險管理 Port 在來源、目的端與 Service 上的分布。",
    "L004": "檢查已被明確 Allow 的遠端管理流量，確認是否仍有必要。",
    "L005": "檢查 Kerberos、LDAP 等身份驗證與目錄 Service 的可視範圍是否合理。",
    "L006": "檢查 lateral reachability 是否過高，找出過度互通的 App。",
    "L007": "檢查 unmanaged 主機對 managed 資產的主動連線行為。",
    "L008": "檢查 test mode 下 Potentially Blocked 的 lateral Port 活動。",
    "L009": "檢查未受管理來源是否能接觸到關鍵 managed 目的端。",
    "L010": "檢查已明確 Allow 的 lateral movement 風險 Port。",
}.items():
    STRINGS[f"rpt_rule_{key}_how"] = _entry("Rule detail", zh_text)

for suffix, entry in {
    "hostname": ("Hostname", "主機名稱"),
    "ip": ("IP", "IP"),
    "role": ("Role", "Role"),
    "app": ("App", "App"),
    "env": ("Env", "Env"),
    "loc": ("Loc", "Loc"),
    "policy_sync": ("Policy Sync", "Policy 同步"),
    "last_heartbeat": ("Last Heartbeat", "最後 Heartbeat"),
    "policy_received": ("Policy Received", "收到 Policy"),
    "paired_at": ("Paired At", "配對時間"),
    "ven_version": ("VEN Version", "VEN 版本"),
    "rule_no": ("No", "序號"),
    "rule_name": ("Rule ID", "Rule ID"),
    "type": ("Type", "類型"),
    "description": ("Description", "說明"),
    "ruleset": ("Ruleset", "Ruleset"),
    "providers": ("Destination", "目的端"),
    "consumers": ("Source", "來源端"),
    "services": ("Services", "Services"),
    "hit_count": ("Hit Count", "命中次數"),
    "enabled": ("Enabled", "啟用"),
    "created_at": ("Created At", "建立時間"),
    "status": ("Status", "狀態"),
    "percentage": ("Percentage", "百分比"),
    "event_type": ("Event Type", "事件類型"),
    "count": ("Count", "數量"),
    "severity": ("Severity", "Severity"),
    "actor": ("Actor", "操作者"),
    "actor_type": ("Actor Type", "操作者類型"),
    "target_name": ("Target", "目標"),
    "target_type": ("Target Type", "目標類型"),
    "resource_name": ("Resource", "資源"),
    "resource_type": ("Resource Type", "資源類型"),
    "action": ("Action", "動作"),
    "action_path": ("API Path", "API 路徑"),
    "supplied_username": ("Supplied Username", "輸入帳號"),
    "known_event_type": ("Known Event", "已知事件"),
    "parser_notes": ("Parser Notes", "解析註記"),
    "parser_note_count": ("Parser Note Count", "解析註記數"),
    "pce_fqdn": ("PCE", "PCE"),
    "timestamp": ("Timestamp", "時間"),
    "user": ("User", "使用者"),
    "total_events": ("Total Events", "事件總數"),
    "failures": ("Failures", "失敗次數"),
    "source_ips": ("Source IPs", "來源 IP"),
    "notification_detail": ("Details", "內容"),
    "workloads_affected": ("Workloads Affected", "受影響 Workloads"),
    "change_detail": ("Change Detail", "變更明細"),
    "api_method": ("API Method", "API 方法"),
    "agent_hostname": ("Agent Host", "Agent 主機"),
    "src_ip": ("Source IP", "來源 IP"),
    "port": ("Port", "Port"),
    "protocol": ("Protocol", "Protocol"),
    "proto": ("Proto", "Protocol"),
    "connections": ("Connections", "連線數"),
    "flow_count": ("Flow Count", "Flow 數量"),
    "flows": ("Flows", "流量數"),
    "decision": ("Decision", "判定"),
    "risk_level": ("Risk Level", "風險等級"),
    "service": ("Service", "Service"),
    "control": ("Control", "控制"),
    "total_flows": ("Total Flows", "Flow 總數"),
    "allowed": ("Allowed", "Allowed"),
    "blocked": ("Blocked", "Blocked"),
    "potentially_blocked": ("Potentially Blocked", "Potentially Blocked"),
    "pct_of_total": ("% of Total", "占總量比例"),
    "inbound": ("Inbound", "Inbound"),
    "outbound": ("Outbound", "Outbound"),
    "coverage_pct": ("Coverage %", "覆蓋率 %"),
    "gap_pct": ("Gap %", "缺口 %"),
    "category": ("Category", "類別"),
    "recommendation": ("Recommendation", "建議"),
    "flow": ("Flow", "Flow"),
    "flow_app": ("Flow (src_app->dst_app)", "Flow（src_app -> dst_app）"),
    "unique_ports": ("Unique Ports", "唯一 Ports 數"),
    "unique_dst_hosts": ("Unique Dst Hosts", "唯一目的端主機數"),
    "unique_src_ips": ("Unique Src IPs", "唯一來源 IP 數"),
    "unique_dst_ips": ("Unique Dst IPs", "唯一目的端 IP 數"),
    "unique_src": ("Unique Src", "唯一來源"),
    "unique_dst": ("Unique Dst", "唯一目的端"),
    "unique_destinations": ("Unique Destinations", "唯一目的端數"),
    "unique_sources": ("Unique Sources", "唯一來源數"),
    "unique_risk_ports": ("Unique Risk Ports", "唯一風險 Ports 數"),
    "unique_source_apps": ("Unique Source Apps", "唯一來源 Apps 數"),
    "unique_unmanaged_src": ("Unique Unmanaged Src", "唯一 Unmanaged 來源"),
    "unique_unmanaged_sources": ("Unique Unmanaged Sources", "唯一 Unmanaged 來源"),
    "destination_ip": ("Destination IP", "目的端 IP"),
    "destination_app": ("Destination App", "目的端 App"),
    "destination": ("Destination", "目的端"),
    "target_ip": ("Target IP", "目標 IP"),
    "exposed_ports": ("Exposed Ports", "暴露 Ports"),
    "exposed_services": ("Exposed Services", "暴露 Services"),
    "allowed_flows": ("Allowed Flows", "Allowed Flows"),
    "uncovered_flows": ("Uncovered Flows", "未覆蓋 Flows"),
    "source_ip": ("Source IP", "來源 IP"),
    "src_host": ("Src Host", "來源主機"),
    "dst_host": ("Dst Host", "目的主機"),
    "host_pair": ("Host Pair", "主機配對"),
    "user_name": ("User Name", "使用者名稱"),
    "process": ("Process", "程序"),
    "bytes": ("Bytes", "傳輸量"),
    "bytes_total": ("Bytes Total", "總傳輸量"),
    "total_bytes": ("Total Bytes", "總 Bytes"),
    "bytes_conn": ("Bytes/Conn", "Bytes/Conn"),
    "bandwidth_mbps": ("Bandwidth (Mbps)", "頻寬（Mbps）"),
    "source_app": ("Source App", "來源 App"),
    "source_env": ("Source Env", "來源環境"),
    "enforcement_mode": ("Enforcement Mode", "Enforcement 模式"),
    "decision_types": ("Decision Types", "判定類型"),
    "dst_apps": ("Dst Apps", "目的端 Apps"),
    "unmanaged_source_ip": ("Unmanaged Source IP", "Unmanaged 來源 IP"),
    "unmanaged_dst_ip": ("Unmanaged Dst IP", "Unmanaged 目的端 IP"),
    "unmanaged_source": ("Unmanaged Source", "Unmanaged 來源"),
    "managed_dest_ip": ("Managed Destination IP", "Managed 目的端 IP"),
    "conn_from_unmanaged": ("Connections from Unmanaged Src", "來自 Unmanaged 來源的連線"),
    "src_env": ("Src Env", "來源環境"),
    "dst_env": ("Dst Env", "目的環境"),
    "src_app": ("Src App", "來源 App"),
    "dst_app": ("Dst App", "目的 App"),
    "src_role": ("Src Role", "來源 Role"),
    "dst_role": ("Dst Role", "目的 Role"),
    "src_loc": ("Src Loc", "來源位置"),
    "dst_loc": ("Dst Loc", "目的位置"),
    "missing_keys": ("Missing Keys", "缺少的 Label Keys"),
    "distinct_label_sets": ("Distinct Label Sets", "相異 Label Sets 數"),
    # evidence pill label keys (used by _format_evidence in html_exporter.py)
    "allowed_ratio": ("Allowed Ratio", "Allowed 比率"),
    "blocked_ratio": ("Blocked Ratio", "Blocked 比率"),
    "blocked_or_pb_flow_count": ("Block/PB Count", "Block/PB 流量數"),
    "ringfence_ratio": ("Ringfence Ratio", "Ringfence 比率"),
    "remote_flow_count": ("Remote Flow Count", "遠端 Flow 數"),
    "remote_allowed_ratio": ("Remote Allowed %", "遠端 Allowed 比率"),
    # mod13 Enforcement Readiness display columns
    "app_env": ("App (Env)", "App（環境）"),
    "readiness_score": ("Readiness Score", "就緒度分數"),
    "policy_coverage_pct": ("Policy Coverage %", "Policy 覆蓋率 %"),
    "ringfence_maturity_pct": ("Ringfence Maturity %", "Ringfence 成熟度 %"),
    "enforcement_mode_pct": ("Enforcement Mode %", "Enforcement 模式 %"),
    "staged_readiness_pct": ("Staged Readiness %", "Staged 就緒度 %"),
    "remote_app_coverage_pct": ("Remote-App Coverage %", "遠端 App 覆蓋率 %"),
    "grade": ("Grade", "等級"),
    # factor_table / recommendations shared columns
    "factor": ("Factor", "評估因素"),
    "weight": ("Weight", "權重"),
    "score": ("Score", "分數"),
    "ratio_pct": ("Ratio %", "佔比 %"),
    "priority": ("Priority", "優先級"),
    "issue": ("Issue", "問題"),
    "action_code": ("Action Code", "行動代碼"),
    # draft PD section
    "draft_decision": ("Draft Decision", "草稿判定"),
    # rules_engine Finding.evidence keys (B001–B009, L001–L010)
    "allowed_flows": ("Allowed Flows", "Allowed Flows"),
    "anomaly_count": ("Anomaly Count", "異常流量數"),
    "blast_radius_threshold": ("Blast Radius Threshold", "影響範圍門檻"),
    "cross_env_db_flows": ("Cross-Env DB Flows", "跨環境資料庫流量"),
    "cross_env_flows": ("Cross-Env Flows", "跨環境流量數"),
    "cross_env_lateral_flows": ("Cross-Env Lateral Flows", "跨環境橫向流量"),
    "cross_subnet_flows": ("Cross-Subnet Flows", "跨子網路流量"),
    "environments": ("Environments", "環境清單"),
    "explicitly_allowed": ("Explicitly Allowed", "Explicitly Allowed 流量"),
    "high_risk_nodes": ("High-Risk Nodes", "高風險節點"),
    "high_src_count": ("High Source Count", "高活動來源數"),
    "high_user_count": ("High User Count", "高活動使用者數"),
    "matched_flows": ("Matched Flows", "符合流量數"),
    "pb_flows": ("Potentially Blocked Flows", "Potentially Blocked 流量"),
    "pb_lateral_flows": ("PB Lateral Flows", "Potentially Blocked 橫向流量"),
    "percentile_threshold": ("Percentile Threshold", "百分位門檻"),
    "ports": ("Ports", "Ports"),
    "same_subnet_flows": ("Same-Subnet Flows", "同子網路流量"),
    "test_mode_only": ("Test-Mode Only", "僅 Test 模式"),
    "top_databases": ("Top Databases", "Top 資料庫"),
    "top_dst_apps": ("Top Destination Apps", "Top 目的端 Apps"),
    "top_dst_ips": ("Top Destination IPs", "Top 目的端 IP"),
    "top_env_pairs": ("Top Env Pairs", "Top 環境配對"),
    "top_flows": ("Top Flows", "Top 流量"),
    "top_pairs": ("Top Pairs", "Top 配對"),
    "top_pivot_apps": ("Top Pivot Apps", "Top Pivot Apps"),
    "top_ports": ("Top Ports", "Top Ports"),
    "top_protocols": ("Top Protocols", "Top Protocols"),
    "top_source_apps": ("Top Source Apps", "Top 來源 Apps"),
    "top_sources": ("Top Sources", "Top 來源"),
    "top_src_apps": ("Top Source Apps", "Top 來源 Apps"),
    "top_src_ips": ("Top Source IPs", "Top 來源 IP"),
    "top_suspicious_pairs": ("Top Suspicious Pairs", "Top 可疑配對"),
    "top_users": ("Top Users", "Top 使用者"),
    "total_anomaly_bytes": ("Total Anomaly Bytes", "異常流量總傳輸量"),
    "total_db_flows": ("Total DB Flows", "資料庫流量總數"),
    "total_lateral_flows": ("Total Lateral Flows", "橫向流量總數"),
    "total_transferred": ("Total Transferred", "總傳輸量"),
    "unblocked_flows": ("Unblocked Flows", "未阻擋流量"),
    "unique_managed_destinations": ("Unique Managed Destinations", "唯一 Managed 目的端"),
    "unique_src_apps": ("Unique Source Apps", "唯一來源 Apps 數"),
    "unique_src_apps_allowed": ("Unique Source Apps (Allowed)", "唯一 Allowed 來源 Apps"),
    "unique_unmanaged_dst": ("Unique Unmanaged Destinations", "唯一 Unmanaged 目的端"),
    "top_unmanaged_sources": ("Top Unmanaged Sources", "主要 Unmanaged 來源"),
    "total": ("Total", "總計"),
}.items():
    STRINGS[f"rpt_col_{suffix}"] = _entry(*entry)

for rule_id, zh_name in {
    "B001": "勒索軟體風險 Port — 情境分析",
    "B002": "勒索軟體高風險遠端存取 Port",
    "B003": "勒索軟體中風險 Port（未覆蓋）",
    "B004": "Unmanaged 來源高活動量",
    "B005": "Policy 覆蓋率不足",
    "B006": "高度 Lateral Movement 活動",
    "B007": "單一使用者大量目的端",
    "B008": "頻寬異常",
    "B009": "跨環境流量",
    "L001": "明文協定使用中（Telnet / FTP）",
    "L002": "網路探索協定暴露",
    "L003": "資料庫 Port 從多個 App 層可達",
    "L004": "跨環境資料庫存取",
    "L005": "身份驗證基礎架構大範圍暴露",
    "L006": "高擴散半徑 Lateral 路徑（Graph BFS）",
    "L007": "Unmanaged 主機存取關鍵 Services",
    "L008": "Lateral Ports 處於 Test Mode — Policy 尚未 Enforce",
    "L009": "資料外洩模式 — 流出至 Unmanaged 主機",
    "L010": "跨環境 Lateral Port 存取 — 邊界突破",
}.items():
    en_name = {
        "B001": "Ransomware Risk Port — Contextual Analysis",
        "B002": "Ransomware Risk Port (High)",
        "B003": "Ransomware Risk Port (Medium) — Uncovered",
        "B004": "Unmanaged Source High Activity",
        "B005": "Low Policy Coverage",
        "B006": "High Lateral Movement",
        "B007": "Single User High Destinations",
        "B008": "High Bandwidth Anomaly",
        "B009": "Cross-Environment Flow Volume",
        "L001": "Cleartext Protocol in Use (Telnet / FTP)",
        "L002": "Network Discovery Protocol Exposure",
        "L003": "Database Port Accessible from Many App Tiers",
        "L004": "Cross-Environment Database Access",
        "L005": "Identity Infrastructure Wide Exposure",
        "L006": "High Blast-Radius Lateral Path (Graph BFS)",
        "L007": "Unmanaged Host Accessing Critical Services",
        "L008": "Lateral Ports in Test Mode — Policy Not Enforced",
        "L009": "Data Exfiltration Pattern — Outbound to Unmanaged",
        "L010": "Cross-Environment Lateral Port Access — Boundary Break",
    }.get(rule_id, rule_id)
    STRINGS[f"rpt_rule_{rule_id}_name"] = _entry(en_name, zh_name)

for key, entry in {
    "rpt_tr_attack_summary": ("Attack Summary", "攻擊摘要"),
}.items():
    STRINGS[key] = _entry(entry[0], entry[1])

COL_I18N: dict[str, str] = {
    value.get("en", ""): key
    for key, value in STRINGS.overlay_items()
    if key.startswith("rpt_col_") and value.get("en")
}

# Render-layer value i18n maps. Pass these to render_df_table via
# value_i18n_maps={col_name: <map>}. Stable English keys; values are
# STRINGS lookup keys.

TIER_VALUE_I18N: dict[str, str] = {
    "Tier-1 Critical":   "rpt_tier_1_critical",
    "Tier-2 Important":  "rpt_tier_2_important",
    "Tier-3 Shared":     "rpt_tier_3_shared",
    "Tier-4 Peripheral": "rpt_tier_4_peripheral",
}

ROLE_VALUE_I18N: dict[str, str] = {
    "Identity": "rpt_role_identity",
    "Database": "rpt_role_database",
    "Provider": "rpt_role_provider",
    "Consumer": "rpt_role_consumer",
    "Bridge":   "rpt_role_bridge",
    "Peer":     "rpt_role_peer",
}

ASSET_TYPE_VALUE_I18N: dict[str, str] = {
    "Identity Infrastructure": "rpt_asset_type_identity_infra",
    "Database":                "rpt_asset_type_database",
}

SEVERITY_VALUE_I18N: dict[str, str] = {
    "CRITICAL": "rpt_severity_critical",
    "HIGH":     "rpt_severity_high",
    "MEDIUM":   "rpt_severity_medium",
    "LOW":      "rpt_severity_low",
    "INFO":     "rpt_severity_info",
}

MOD01_METRIC_VALUE_I18N: dict[str, str] = {
    "Policy Coverage":                       "rpt_metric_policy_coverage",
    "Allowed / Blocked / Potentially Blocked": "rpt_metric_allowed_blocked_potential",
    "Total Data":                            "rpt_metric_total_data",
    "Date Range":                            "rpt_metric_date_range",
}

def lang_btn_html() -> str:
    return ''
