"""
Shared i18n helpers for HTML report exporters.
"""
from __future__ import annotations

import json


class _StringMap(dict):
    def __missing__(self, key: str) -> dict[str, str]:
        return {"en": key, "zh_TW": key}


def _entry(en: str, zh_tw: str | None = None) -> dict[str, str]:
    return {"en": en, "zh_TW": zh_tw or en}


STRINGS: _StringMap = _StringMap({
    "rpt_generated": _entry("Generated:", "產出時間："),
    "rpt_period": _entry("Period:", "期間："),
    "rpt_key_metrics": _entry("Key Metrics", "關鍵指標"),
    "rpt_key_findings": _entry("Key Findings", "關鍵發現"),
    "rpt_no_data": _entry("No data", "沒有資料"),
    "rpt_no_records": _entry("No records", "沒有記錄"),
    "rpt_no_findings": _entry("No key findings.", "本次分析沒有發現需要特別關注的重點。"),
    "rpt_no_findings_detail": _entry(
        "No security findings were triggered for this dataset. This may indicate good policy coverage or thresholds that need tuning.",
        "這批資料沒有觸發任何安全發現，通常代表 Policy 覆蓋狀況良好，或目前的門檻設定較保守。",
    ),
    "rpt_no_lateral": _entry("No lateral movement traffic found.", "沒有發現 lateral movement 流量。"),
    "rpt_no_user_proc": _entry("No user/process data.", "沒有使用者或程序資料。"),
    "rpt_no_matrix": _entry("No label matrix data.", "沒有 Label 矩陣資料。"),
    "rpt_table_hint": _entry("Sortable · Resize columns", "可排序、調整欄寬"),
    "rpt_yes": _entry("Yes", "是"),
    "rpt_no": _entry("No", "否"),
    "rpt_kicker_traffic": _entry("Traffic Analytics Report", "流量分析報表"),
    "rpt_kicker_audit": _entry("Audit & Event Report", "稽核與事件報表"),
    "rpt_kicker_policy": _entry("Policy Usage Report", "Policy 使用報表"),
    "rpt_kicker_ven": _entry("VEN Inventory Report", "VEN 資產狀態報表"),
    "rpt_pill_flows": _entry("Flows", "Flows"),
    "rpt_pill_findings": _entry("Findings", "發現數"),
    "rpt_pill_focus": _entry("Focus", "焦點"),
    "rpt_pill_period": _entry("Period", "期間"),
    "rpt_pill_attention": _entry("Attention", "重點關注"),
    "rpt_pill_lookback": _entry("Lookback", "回看區間"),
    "rpt_pill_online": _entry("Online", "Online"),
    "rpt_pill_offline": _entry("Offline", "Offline"),
    "rpt_pill_lost_24h": _entry("Lost <24h", "失聯 <24h"),
    "rpt_pill_lost_48h": _entry("Lost 24-48h", "失聯 24-48h"),
    "rpt_focus_traffic": _entry("Traffic Analytics", "Traffic Analytics"),
    "rpt_focus_audit": _entry("Audit & Events", "Audit & Events"),
    "rpt_focus_usage": _entry("Usage Posture", "Usage Posture"),
    "rpt_focus_inventory": _entry("VEN Connectivity", "VEN Connectivity"),
    "rpt_recommendation_label": _entry("Recommendation:", "建議："),
    "rpt_rule_check_label": _entry("What this rule checks:", "此規則在檢查："),
    "rpt_col_uncovered_flows": _entry("Uncovered Flows", "未覆蓋流量"),
    "rpt_tr_title": _entry("Illumio Traffic Flow Report", "Illumio 流量分析報表"),
    "rpt_tr_nav_summary": _entry("Executive Summary", "摘要"),
    "rpt_tr_nav_overview": _entry("1 Traffic Overview", "1 流量總覽"),
    "rpt_tr_nav_policy": _entry("2 Policy Decisions", "2 Policy 判定"),
    "rpt_tr_nav_uncovered": _entry("3 Uncovered Flows", "3 未覆蓋流量"),
    "rpt_tr_nav_ransomware": _entry("4 Ransomware Exposure", "4 勒索軟體風險"),
    "rpt_tr_nav_remote": _entry("5 Remote Access", "5 遠端存取"),
    "rpt_tr_nav_user": _entry("6 User & Process", "6 使用者與程序"),
    "rpt_tr_nav_matrix": _entry("7 Cross-Label Matrix", "7 跨 Label 矩陣"),
    "rpt_tr_nav_unmanaged": _entry("8 Unmanaged Hosts", "8 unmanaged 主機"),
    "rpt_tr_nav_distribution": _entry("9 Traffic Distribution", "9 流量分布"),
    "rpt_tr_nav_allowed": _entry("10 Allowed Traffic", "10 Allowed 流量"),
    "rpt_tr_nav_bandwidth": _entry("11 Bandwidth & Volume", "11 頻寬與流量"),
    "rpt_tr_nav_readiness": _entry("13 Enforcement Readiness", "13 Enforcement 就緒度"),
    "rpt_tr_nav_infrastructure": _entry("14 Infrastructure Scoring", "14 基礎架構評分"),
    "rpt_tr_nav_lateral": _entry("15 Lateral Movement", "15 lateral movement"),
    "rpt_tr_nav_findings": _entry("Findings", "發現總覽"),
    "rpt_tr_sec_findings": _entry("Security Findings", "安全發現"),
    "rpt_tr_policy_coverage": _entry("Policy Coverage", "Policy 覆蓋率"),
    "rpt_tr_flow_breakdown": _entry("Allowed / Blocked / Potentially Blocked", "Allowed / Blocked / Potentially Blocked"),
    "rpt_tr_total_data": _entry("Total Data", "資料總量"),
    "rpt_tr_date_range": _entry("Date Range", "日期範圍"),
    "rpt_tr_top_ports": _entry("Top Ports", "熱門連接埠"),
    "rpt_tr_top_uncovered": _entry("Top Uncovered Flows", "未覆蓋流量排行"),
    "rpt_tr_port_coverage": _entry("Per-Port Coverage", "依連接埠覆蓋率"),
    "rpt_tr_inbound_coverage": _entry("Inbound Coverage", "Inbound 覆蓋率"),
    "rpt_tr_outbound_coverage": _entry("Outbound Coverage", "Outbound 覆蓋率"),
    "rpt_tr_overall_coverage": _entry("Overall Coverage", "整體覆蓋率"),
    "rpt_tr_port_gaps": _entry("Port Gap Ranking", "連接埠缺口排行"),
    "rpt_tr_service_gaps": _entry("Uncovered Services (App + Port)", "未覆蓋服務（App + Port）"),
    "rpt_tr_by_rec": _entry("By Recommendation Category", "依建議類別"),
    "rpt_tr_risk_flows": _entry("Total risk flows:", "高風險流量總數："),
    "rpt_tr_risk_summary": _entry("Risk Level Summary", "風險等級摘要"),
    "rpt_tr_per_port": _entry("Per-Port Detail", "連接埠明細"),
    "rpt_tr_investigation_title": _entry("Hosts Requiring Investigation", "建議優先調查的主機"),
    "rpt_tr_investigation_desc": _entry(
        "The following destination hosts have allowed traffic on critical or high-risk ports. Verify whether this is expected, or block the traffic.",
        "以下目的端主機在關鍵或高風險連接埠上出現 Allowed 流量。請確認是否屬於預期行為，必要時應限制或阻擋。",
    ),
    "rpt_tr_no_investigation": _entry("No allowed traffic on critical/high-risk ports detected.", "未偵測到關鍵或高風險連接埠上的 Allowed 流量。"),
    "rpt_tr_host_exposure": _entry("Host Exposure Ranking", "主機暴露排行"),
    "rpt_tr_host_exposure_note": _entry(
        "Destination hosts ranked by the number of distinct risk ports contacted across all policy decisions.",
        "依照所有 Policy 判定下實際接觸到的高風險連接埠種類數，對目的端主機進行排序。",
    ),
    "rpt_tr_top_talkers": _entry("Top Talkers", "熱門通訊主機"),
    "rpt_tr_top_users": _entry("Top Users", "熱門使用者"),
    "rpt_tr_top_processes": _entry("Top Processes", "熱門程序"),
    "rpt_tr_label_key": _entry("Label Key:", "Label 說明："),
    "rpt_tr_same_value": _entry("Same-value:", "同值："),
    "rpt_tr_cross_value": _entry("Cross-value:", "交叉值："),
    "rpt_tr_unmanaged_flow_stat": _entry("Unmanaged Flows", "unmanaged 流量"),
    "rpt_tr_unique_unmanaged_src": _entry("Unique Unmanaged Src", "唯一 unmanaged 來源"),
    "rpt_tr_unique_unmanaged_dst": _entry("Unique Unmanaged Dst", "唯一 unmanaged 目的端"),
    "rpt_tr_top_unmanaged": _entry("Top Unmanaged Sources", "熱門 unmanaged 來源"),
    "rpt_tr_managed_apps_unmanaged": _entry("Managed Apps Receiving Unmanaged Traffic", "接收 unmanaged 流量的 managed App"),
    "rpt_tr_exposed_ports_proto": _entry("Exposed Ports / Protocols", "暴露的連接埠 / Protocol"),
    "rpt_tr_unmanaged_src_port": _entry("Unmanaged Source Port Detail", "unmanaged 來源連接埠明細"),
    "rpt_tr_managed_targeted": _entry("Managed Hosts Targeted by Unmanaged Sources", "被 unmanaged 來源鎖定的 managed 主機"),
    "rpt_tr_port_dist": _entry("Port Distribution", "連接埠分布"),
    "rpt_tr_proto_dist": _entry("Protocol Distribution", "Protocol 分布"),
    "rpt_tr_audit_flags": _entry("Audit Flags", "稽核標記"),
    "rpt_tr_total_volume": _entry("Total Volume", "總流量"),
    "rpt_tr_max_bw": _entry("Max Bandwidth", "最大頻寬"),
    "rpt_tr_avg_bw": _entry("Avg Bandwidth", "平均頻寬"),
    "rpt_tr_p95_bw": _entry("P95 Bandwidth", "P95 頻寬"),
    "rpt_tr_top_by_bytes": _entry("Top by Total Bytes", "依總傳輸量排序"),
    "rpt_tr_top_by_bw": _entry("Top by Bandwidth (Mbps)", "依頻寬排序（Mbps）"),
    "rpt_tr_anomalies": _entry("Anomalies (High Bytes/Conn)", "異常流量（高 Bytes/Conn）"),
    "rpt_tr_anomalies_note": _entry(
        "Flows whose bytes-per-connection ratio exceeds the dataset's P95 threshold, excluding one-off connections.",
        "此區塊列出每條連線的平均傳輸量高於資料集 P95 門檻的流量，並排除單次偶發連線，用於快速找出異常高傳輸模式。",
    ),
    "rpt_tr_readiness_score": _entry("Enforcement Readiness Score:", "Enforcement 就緒度分數："),
    "rpt_tr_score_breakdown": _entry("Score Breakdown by Factor", "分數構成"),
    "rpt_tr_remediation_rec": _entry("Remediation Recommendations", "修復建議"),
    "rpt_tr_apps_analysed": _entry("Applications analysed:", "分析的 Applications："),
    "rpt_tr_comm_edges": _entry("Communication edges:", "通訊邊數："),
    "rpt_tr_role_distribution": _entry("Role Distribution", "Role 分布"),
    "rpt_tr_hub_apps": _entry("Hub Applications (High Blast Radius)", "Hub Applications（高影響半徑）"),
    "rpt_tr_top_apps_infra": _entry("Top Applications by Infrastructure Score", "依基礎架構評分排序的 Applications"),
    "rpt_tr_top_comm_paths": _entry("Top Communication Paths (by Volume)", "依流量排序的主要通訊路徑"),
    "rpt_tr_lateral_flows": _entry("Lateral movement port flows:", "lateral movement 相關流量："),
    "rpt_tr_lateral_pct": _entry("of all flows", "占全部流量"),
    "rpt_tr_lateral_by_service": _entry("Lateral Port Activity by Service", "依服務檢視 lateral 連接埠活動"),
    "rpt_tr_fan_out": _entry("Fan-out Sources (Potential Scanner / Worm)", "Fan-out 來源（疑似掃描器 / Worm）"),
    "rpt_tr_allowed_lateral": _entry("Explicitly Allowed Lateral Flows (Highest Risk)", "明確 Allowed 的 lateral 流量（高風險）"),
    "rpt_tr_top_risk_sources": _entry("Top High-Risk Sources", "高風險來源排行"),
    "rpt_tr_app_chains": _entry("Lateral Movement App Chains (BFS Paths)", "lateral movement App 鏈（BFS Paths）"),
    "rpt_tr_top_app_flows": _entry("Top App Flows", "熱門 App 流向"),
    "rpt_tr_footer": _entry("Illumio PCE Ops Traffic Flow Report", "Illumio PCE Ops 流量分析報表"),
    "rpt_au_title": _entry("Illumio Audit & System Events Report", "Illumio 稽核與系統事件報表"),
    "rpt_au_nav_summary": _entry("Executive Summary", "摘要"),
    "rpt_au_nav_health": _entry("1 System Health", "1 系統健康"),
    "rpt_au_nav_users": _entry("2 User Activity", "2 使用者活動"),
    "rpt_au_nav_policy": _entry("3 Policy Changes", "3 Policy 變更"),
    "rpt_au_attention_title": _entry("Attention Required", "需要關注的事件"),
    "rpt_au_actor": _entry("Actor:", "操作者："),
    "rpt_au_rec": _entry("Recommendation:", "建議："),
    "rpt_au_sec_health": _entry("1 System Health & Agent", "1 系統健康與 Agent"),
    "rpt_au_sec_users": _entry("2 User Activity & Authentication", "2 使用者活動與驗證"),
    "rpt_au_sec_policy": _entry("3 Policy Modifications", "3 Policy 異動"),
    "rpt_au_top_events": _entry("Top Event Types", "主要事件類型"),
    "rpt_au_total_health": _entry("Total Health Events:", "健康事件總數："),
    "rpt_au_security_concerns": _entry("Security Concerns:", "安全疑慮："),
    "rpt_au_connectivity_issues": _entry("Agent Connectivity:", "Agent 連線問題："),
    "rpt_au_connectivity_title": _entry("Agent Connectivity Events", "Agent 連線事件"),
    "rpt_au_sec_concern_title": _entry("Security Concern Events", "安全疑慮事件"),
    "rpt_au_sec_concern_desc": _entry(
        "Tampering, suspend, or clone-related events may indicate compromise and should be reviewed immediately.",
        "Tampering、suspend 或 clone 相關事件，可能代表主機或 Agent 已遭異常操作，建議立即檢查。",
    ),
    "rpt_au_severity_breakdown": _entry("Severity Breakdown", "Severity 分布"),
    "rpt_au_summary_type": _entry("Summary by Event Type", "依事件類型彙整"),
    "rpt_au_recent": _entry("Recent Events (up to 50)", "近期事件（最多 50 筆）"),
    "rpt_au_total_user": _entry("Total User Events:", "使用者事件總數："),
    "rpt_au_failed_logins": _entry("Failed Logins:", "登入失敗次數："),
    "rpt_au_unique_src_ips": _entry("Unique Admin IPs:", "唯一管理來源 IP："),
    "rpt_au_failed_detail": _entry("Failed Login Details", "登入失敗明細"),
    "rpt_au_failed_detail_desc": _entry(
        "Includes source IP and notification context for suspicious login investigation.",
        "列出來源 IP 與通知內容，方便追查可疑登入行為。",
    ),
    "rpt_au_per_user": _entry("Activity by User", "依使用者檢視活動"),
    "rpt_au_total_policy": _entry("Total Policy Events:", "Policy 事件總數："),
    "rpt_au_provisions": _entry("Provisions:", "Provision 次數："),
    "rpt_au_rule_changes": _entry("Rule Changes (Draft):", "Draft Rule 變更："),
    "rpt_au_provision_impact_stat": _entry("Total Workloads Affected (all provisions):", "受所有 Provision 影響的 Workloads 總數："),
    "rpt_au_lifecycle_title": _entry("Illumio Policy Lifecycle: Draft vs Provision", "Illumio Policy 生命週期：Draft 與 Provision"),
    "rpt_au_lifecycle_draft_title": _entry("1 Draft Changes (Not Yet Enforced)", "1 Draft 變更（尚未正式套用）"),
    "rpt_au_lifecycle_draft_body": _entry(
        "Draft events represent policy edits that have not yet been provisioned to VENs.",
        "Draft 事件代表 Policy 已被修改，但尚未 Provision 到 VEN，因此還沒有正式生效。",
    ),
    "rpt_au_lifecycle_prov_title": _entry("2 Provision (Policy Goes Live)", "2 Provision（Policy 正式上線）"),
    "rpt_au_lifecycle_prov_body": _entry(
        "Provision events package draft changes into a new active policy version and push them to workloads.",
        "Provision 事件會把 Draft 變更整理成新的有效 Policy 版本，並推送到相關 Workloads。",
    ),
    "rpt_au_high_impact_title": _entry("High-Impact Provisions", "高影響 Provision"),
    "rpt_au_high_impact_desc": _entry(
        "The following provision events affected an unusually large number of workloads.",
        "以下 Provision 事件一次影響了較大量的 Workloads，建議優先確認是否符合預期。",
    ),
    "rpt_au_workloads_affected": _entry("Workloads Affected", "受影響 Workloads"),
    "rpt_au_provision_title": _entry("Policy Provision Events", "Policy Provision 事件"),
    "rpt_au_provision_desc": _entry(
        "Provision events push draft changes into active enforcement. Review the impact carefully.",
        "Provision 事件代表 Draft 變更已正式進入 Enforcement，請仔細評估影響範圍。",
    ),
    "rpt_au_draft_section": _entry("Draft Rule Changes", "Draft Rule 變更"),
    "rpt_au_draft_desc": _entry(
        "These events show policy edits that have not yet taken effect.",
        "這些事件代表 Policy 已被修改，但尚未正式生效。",
    ),
    "rpt_au_per_user_policy": _entry("Changes by User", "依使用者檢視變更"),
    "rpt_au_severity_dist": _entry("Severity Distribution", "Severity 分布"),
    "rpt_au_bp_health": _entry(
        "<b>Best Practice:</b> Monitor health events for agent tampering, suspension, and heartbeat degradation.",
        "<b>建議做法：</b>持續追蹤 Agent tampering、suspension 與 heartbeat 異常，及早掌握健康狀態退化。",
    ),
    "rpt_au_bp_users": _entry(
        "<b>Best Practice:</b> Track repeated login failures and unusual authentication spikes.",
        "<b>建議做法：</b>持續觀察重複登入失敗與異常驗證高峰，快速找出可疑帳號活動。",
    ),
    "rpt_au_src_ip_note": _entry(
        "<b>Source IP Tracking:</b> Unexpected source IPs may indicate compromised credentials or insider threats.",
        "<b>來源 IP 追蹤：</b>若出現不預期的來源 IP，可能代表帳密遭濫用或內部風險。",
    ),
    "rpt_au_bp_policy": _entry(
        "<b>Best Practice:</b> Review broad-scoped rule changes and large provision blasts carefully.",
        "<b>建議做法：</b>對範圍廣泛的 Rule 變更與大規模 Provision 要特別審視，避免一次影響大量資產。",
    ),
    "rpt_au_change_detail_note": _entry(
        "<b>Change Tracking:</b> Use change details to review before/after differences for sensitive objects.",
        "<b>變更追蹤：</b>可透過 change detail 比對前後差異，特別適合檢查敏感物件是否被誤改。",
    ),
    "rpt_au_footer": _entry("Illumio PCE Ops Audit Report", "Illumio PCE Ops 稽核報表"),
    "rpt_ven_title": _entry("Illumio VEN Status Inventory Report", "Illumio VEN 狀態盤點報表"),
    "rpt_ven_nav_summary": _entry("Executive Summary", "摘要"),
    "rpt_ven_nav_online": _entry("Online VENs", "Online VEN"),
    "rpt_ven_nav_offline": _entry("Offline VENs", "Offline VEN"),
    "rpt_ven_nav_lost_today": _entry("Lost Today (<24h)", "今日失聯（<24h）"),
    "rpt_ven_nav_lost_yest": _entry("Lost Yesterday", "昨日失聯"),
    "rpt_ven_footer": _entry("Illumio PCE Ops VEN Status Report", "Illumio PCE Ops VEN 狀態報表"),
    "rpt_pu_title": _entry("Illumio Policy Usage Report", "Illumio Policy 使用報表"),
    "rpt_pu_nav_summary": _entry("Executive Summary", "摘要"),
    "rpt_pu_nav_overview": _entry("1 Usage Overview", "1 使用總覽"),
    "rpt_pu_nav_hit": _entry("2 Hit Rules", "2 Hit Rules"),
    "rpt_pu_nav_unused": _entry("3 Unused Rules", "3 未使用 Rules"),
    "rpt_pu_footer": _entry("Illumio PCE Ops Policy Usage Report", "Illumio PCE Ops Policy 使用報表"),
    "rpt_pu_total_rules": _entry("Total Active Rules", "啟用中的 Rule 總數"),
    "rpt_pu_hit_rules": _entry("Hit Rules", "Hit Rules"),
    "rpt_pu_unused_rules": _entry("Unused Rules", "未使用 Rules"),
    "rpt_pu_hit_rate": _entry("Hit Rate", "命中率"),
    "rpt_pu_attention": _entry("Top Rulesets by Unused Rules", "未使用 Rules 最多的 Rulesets"),
    "rpt_pu_caveat_title": _entry("Retention Period Caveat", "Retention 區間提醒"),
    "rpt_pu_caveat_body": _entry(
        "Rules with zero traffic hits in the analysed period may still have older hits outside the retention window. Review carefully before removal.",
        "在本次分析區間內沒有流量命中的 Rules，仍可能在更早的 retention 區間外有歷史命中紀錄，移除前請再確認。",
    ),
    "rpt_pu_no_hit_rules": _entry("No rules were hit during this period.", "此期間沒有任何 Rule 被命中。"),
    "rpt_pu_no_unused_rules": _entry("All rules had traffic hits; no unused rules found.", "所有 Rules 都有流量命中，沒有發現未使用的 Rule。"),
    "rpt_email_traffic_subject": _entry("Illumio Traffic Flow Report", "Illumio 流量分析報表"),
    "rpt_email_audit_subject": _entry("Illumio Audit & System Events Report", "Illumio 稽核與系統事件報表"),
    "rpt_email_ven_subject": _entry("Illumio VEN Status Report", "Illumio VEN 狀態報表"),
    "rpt_email_policy_usage_subject": _entry("Illumio Policy Usage Report", "Illumio Policy 使用報表"),
    "rpt_email_pu_subject": _entry("Illumio Policy Usage Report", "Illumio Policy 使用報表"),
})


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
        "unmanaged 主機",
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
}.items():
    name_en, name_zh, desc_en, desc_zh = pair
    STRINGS[f"rpt_cat_{key}_name"] = _entry(name_en, name_zh)
    STRINGS[f"rpt_cat_{key}_desc"] = _entry(desc_en, desc_zh)


for key, zh_text in {
    "B001": "檢查 SMB、RPC、RDP、WinRM 等高風險管理連接埠是否暴露，並優先鎖定高風險目的端。",
    "B002": "檢查 TeamViewer、VNC、NetBIOS 等遠端控制或舊式管理協定的暴露情況。",
    "B003": "檢查測試或可視性用途的流量是否仍停留在生產環境中，避免形成長期例外。",
    "B004": "檢查尚未納入 PCE/VEN Enforcement 的主機與其對外通訊，找出管理盲區。",
    "B005": "檢查跨區段或高風險服務是否已被明確 Allow，避免例外規則長期存在。",
    "B006": "檢查 lateral movement 常見連接埠的主要來源、目的端與服務組合。",
    "B007": "檢查高風險來源與使用者活動，找出可疑主機或帳號。",
    "B008": "檢查 Bytes/Conn 顯著偏高的流量，快速辨識異常大量傳輸。",
    "B009": "檢查跨環境流量，例如 Production 與 Development 之間的非預期互通。",
    "L001": "檢查常見遠端存取服務，例如 Telnet、FTP 等是否仍在使用。",
    "L002": "檢查 NetBIOS、DNS、LLMNR、SSDP 等容易被用於探索環境的協定。",
    "L003": "檢查高風險管理連接埠在來源、目的端與服務上的分布。",
    "L004": "檢查已被明確 Allow 的遠端管理流量，確認是否仍有必要。",
    "L005": "檢查 Kerberos、LDAP 等身份驗證與目錄服務的可視範圍是否合理。",
    "L006": "檢查 lateral reachability 是否過高，找出過度互通的 App。",
    "L007": "檢查 unmanaged 主機對 managed 資產的主動連線行為。",
    "L008": "檢查 test mode 下 Potentially Blocked 的 lateral 連接埠活動。",
    "L009": "檢查未受管理來源是否能接觸到關鍵 managed 目的端。",
    "L010": "檢查已明確 Allow 的 lateral movement 風險連接埠。",
}.items():
    STRINGS[f"rpt_rule_{key}_how"] = _entry("Rule detail", zh_text)


for suffix, pair in {
    "hostname": ("Hostname", "主機名稱"),
    "ip": ("IP", "IP"),
    "labels": ("Labels", "Labels"),
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
    "services": ("Services", "服務"),
    "hit_count": ("Hit Count", "命中次數"),
    "enabled": ("Enabled", "啟用"),
    "created_at": ("Created At", "建立時間"),
    "status": ("Status", "狀態"),
    "percentage": ("Percentage", "百分比"),
    "event_type": ("Event Type", "事件類型"),
    "count": ("Count", "數量"),
    "severity": ("Severity", "Severity"),
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
    "port": ("Port", "連接埠"),
    "protocol": ("Protocol", "Protocol"),
    "proto": ("Proto", "Protocol"),
    "connections": ("Connections", "連線數"),
    "flow_count": ("Flow Count", "Flow 數量"),
    "flows": ("Flows", "Flows"),
    "decision": ("Decision", "判定"),
    "risk_level": ("Risk Level", "風險等級"),
    "service": ("Service", "服務"),
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
    "unique_ports": ("Unique Ports", "唯一連接埠數"),
    "unique_dst_hosts": ("Unique Dst Hosts", "唯一目的端主機數"),
    "unique_src_ips": ("Unique Src IPs", "唯一來源 IP 數"),
    "unique_dst_ips": ("Unique Dst IPs", "唯一目的端 IP 數"),
    "unique_src": ("Unique Src", "唯一來源"),
    "unique_dst": ("Unique Dst", "唯一目的端"),
    "unique_destinations": ("Unique Destinations", "唯一目的端數"),
    "unique_sources": ("Unique Sources", "唯一來源數"),
    "unique_risk_ports": ("Unique Risk Ports", "唯一風險連接埠數"),
    "unique_source_apps": ("Unique Source Apps", "唯一來源 App 數"),
    "unique_unmanaged_src": ("Unique Unmanaged Src", "唯一 unmanaged 來源"),
    "unique_unmanaged_sources": ("Unique Unmanaged Sources", "唯一 unmanaged 來源"),
    "destination_ip": ("Destination IP", "目的端 IP"),
    "destination_app": ("Destination App", "目的端 App"),
    "destination": ("Destination", "目的端"),
    "target_ip": ("Target IP", "目標 IP"),
    "exposed_ports": ("Exposed Ports", "暴露連接埠"),
    "exposed_services": ("Exposed Services", "暴露服務"),
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
    "unmanaged_source_ip": ("Unmanaged Source IP", "unmanaged 來源 IP"),
    "unmanaged_dst_ip": ("Unmanaged Dst IP", "unmanaged 目的端 IP"),
    "unmanaged_source": ("Unmanaged Source", "unmanaged 來源"),
    "managed_dest_ip": ("Managed Destination IP", "managed 目的端 IP"),
    "conn_from_unmanaged": ("Connections from Unmanaged Src", "來自 unmanaged 來源的連線"),
    "src_env": ("Src Env", "來源環境"),
    "dst_env": ("Dst Env", "目的環境"),
    "src_app": ("Src App", "來源 App"),
    "dst_app": ("Dst App", "目的 App"),
    "src_role": ("Src Role", "來源 Role"),
    "dst_role": ("Dst Role", "目的 Role"),
    "src_loc": ("Src Loc", "來源位置"),
    "dst_loc": ("Dst Loc", "目的位置"),
}.items():
    STRINGS[f"rpt_col_{suffix}"] = _entry(*pair)


def make_i18n_js() -> str:
    strings_json = json.dumps(STRINGS, ensure_ascii=False, indent=2)
    return f"""<script>
(function(){{
  var _T = {strings_json};
  var _lang = localStorage.getItem('illumioReportLang') || 'zh_TW';
  function applyI18n() {{
    document.querySelectorAll('[data-i18n]').forEach(function(el) {{
      var k = el.getAttribute('data-i18n');
      if (_T[k] && _T[k][_lang]) el.textContent = _T[k][_lang];
    }});
    document.querySelectorAll('[data-i18n-html]').forEach(function(el) {{
      var k = el.getAttribute('data-i18n-html');
      if (_T[k] && _T[k][_lang]) el.innerHTML = _T[k][_lang];
    }});
    var btn = document.getElementById('_langBtn');
    if (btn) btn.textContent = _lang === 'zh_TW' ? 'EN' : '中文';
  }}
  window._toggleReportLang = function() {{
    _lang = _lang === 'zh_TW' ? 'en' : 'zh_TW';
    localStorage.setItem('illumioReportLang', _lang);
    applyI18n();
  }};
  document.addEventListener('DOMContentLoaded', applyI18n);
}})();
</script>"""


COL_I18N: dict[str, str] = {
    value.get("en", ""): key
    for key, value in STRINGS.items()
    if key.startswith("rpt_col_") and value.get("en")
}


def lang_btn_html() -> str:
    return (
        '<button id="_langBtn" onclick="_toggleReportLang()" '
        'style="position:fixed;top:10px;right:12px;z-index:999;padding:4px 10px;'
        'background:#2b6cb0;color:white;border:none;border-radius:4px;'
        'cursor:pointer;font-size:12px;">中文</button>'
    )
