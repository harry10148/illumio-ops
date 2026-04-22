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
    "rpt_tr_maturity_heading": _entry("Microsegmentation Maturity", "微分段成熟度"),
    "rpt_tr_maturity_score": _entry("Maturity Score", "成熟度分數"),
    "rpt_tr_trend_heading": _entry("Trend vs Previous Report", "與前次報表比較"),
    "rpt_tr_trend_empty": _entry(
        "No previous snapshot — trend will appear from the next report onward.",
        "首次產出此報表，下次起會與本次比較顯示趨勢變化。",
    ),
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
    "rpt_tr_top_ports": _entry("Top Ports", "熱門 Port"),
    "rpt_tr_top_uncovered": _entry("Top Uncovered Flows", "未覆蓋流量排行"),
    "rpt_tr_port_coverage": _entry("Per-Port Coverage", "依 Port 覆蓋率"),
    "rpt_tr_inbound_coverage": _entry("Inbound Coverage", "Inbound 覆蓋率"),
    "rpt_tr_outbound_coverage": _entry("Outbound Coverage", "Outbound 覆蓋率"),
    "rpt_tr_overall_coverage": _entry("Overall Coverage", "整體覆蓋率"),
    "rpt_tr_enforced_coverage": _entry("Enforced Coverage", "已強制執行覆蓋率"),
    "rpt_tr_staged_coverage": _entry("Staged Coverage", "已就位待強制覆蓋率"),
    "rpt_tr_true_gap": _entry("True Gap", "真實缺口"),
    "rpt_tr_port_gaps": _entry("Port Gap Ranking", "Port 缺口排行"),
    "rpt_tr_service_gaps": _entry("Uncovered Services (App + Port)", "未覆蓋 Service（App + Port）"),
    "rpt_tr_by_rec": _entry("By Recommendation Category", "依建議類別"),
    "rpt_tr_risk_flows": _entry("Total risk flows:", "高風險流量總數："),
    "rpt_tr_risk_summary": _entry("Risk Level Summary", "風險等級摘要"),
    "rpt_tr_per_port": _entry("Per-Port Detail", "Port 明細"),
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
    "rpt_tr_exposed_ports_proto": _entry("Exposed Ports / Protocols", "暴露的 Port / Protocol"),
    "rpt_tr_unmanaged_src_port": _entry("Unmanaged Source Port Detail", "unmanaged 來源 Port 明細"),
    "rpt_tr_managed_targeted": _entry("Managed Hosts Targeted by Unmanaged Sources", "被 unmanaged 來源鎖定的 managed 主機"),
    "rpt_tr_port_dist": _entry("Port Distribution", "Port 分布"),
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
    "rpt_tr_enforcement_dist": _entry("Enforcement Mode Distribution", "Enforcement Mode 分佈"),
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
    "rpt_tr_lateral_by_service": _entry("Lateral Port Activity by Service", "依 Service 檢視 lateral Port 活動"),
    "rpt_tr_ip_top_talkers": _entry("IP Top Talkers (Host-Level)", "IP Top Talkers（主機層級）"),
    "rpt_tr_ip_top_pairs": _entry("Top Host Pairs", "主機連線配對排行"),
    "rpt_tr_fan_out": _entry("Fan-out Sources (Potential Scanner / Worm)", "Fan-out 來源（疑似掃描器 / Worm）"),
    "rpt_tr_allowed_lateral": _entry("Explicitly Allowed Lateral Flows (Highest Risk)", "明確 Allowed 的 lateral 流量（高風險）"),
    "rpt_tr_top_risk_sources": _entry("Top High-Risk Sources", "高風險來源排行"),
    "rpt_tr_app_chains": _entry("Lateral Movement App Chains (BFS Paths)", "lateral movement App 鏈（BFS Paths）"),
    "rpt_tr_top_app_flows": _entry("Top App Flows", "熱門 App 流向"),
    "rpt_tr_footer": _entry("Illumio PCE Ops Traffic Flow Report", "Illumio PCE Ops 流量分析報表"),
    "rpt_tr_mod01_intro": _entry(
        "This summary frames traffic scale, Policy coverage, and observation period so the rest of the report has context.",
        "這張摘要表先交代流量規模、Policy 覆蓋率與觀測期間，方便你建立本次報表的整體背景。",
    ),
    "rpt_tr_top_ports_subnote": _entry(
        "Top Ports shows which Services dominate the environment and helps spot unexpected activity.",
        "熱門 Port 表可快速看出目前環境最常出現的 Service，並判斷是否有不符合預期的活動。",
    ),
    "rpt_tr_mod02_intro": _entry(
        "Start with the decision breakdown to see how much traffic is Allowed vs Blocked vs Potentially Blocked.",
        "先看整體決策分佈，理解目前流量有多少被 Allow、Blocked 或仍停留在 Potentially Blocked。",
    ),
    "rpt_tr_port_coverage_subnote": _entry(
        "Per-Port Coverage surfaces which Services already have solid Policy and which still have gaps.",
        "各 Port 覆蓋率可用來找出哪些 Service 已具備較完整的 Policy，哪些仍有明顯缺口。",
    ),
    "rpt_tr_top_uncovered_subnote": _entry(
        "Top uncovered flows highlight where Policy most urgently needs filling, usually by volume or sensitivity.",
        "未覆蓋流量排行用來指出目前最需要補 Policy 的流向，通常應優先處理量大或敏感度高的 Service。",
    ),
    "rpt_tr_port_gaps_subnote": _entry(
        "The Port gap ranking helps you inventory gaps by Service and turn them directly into a remediation list.",
        "Port 缺口排行有助於從 Service 面向盤點缺口，適合直接轉成補強清單。",
    ),
    "rpt_tr_service_gaps_subnote": _entry(
        "Uncovered Services tie apps and Ports together, making a better input for future Policy design.",
        "未覆蓋 Service 把應用與 Port 綁在一起看，更適合做為後續 Policy 設計的輸入。",
    ),
    "rpt_tr_remote_services_subnote": _entry(
        "Service-level activity in remote-management scenarios shows which protocols are most used for ops or remote sessions.",
        "先看各 Service 在遠端管理情境下的活動量，判斷哪些協定最常被拿來做維運或遠端連線。",
    ),
    "rpt_tr_remote_talkers_subnote": _entry(
        "Top Talkers surfaces the most active sources or destinations so you can cross-check against known admin nodes.",
        "Top Talkers 用來找出最常參與這些連線的來源或目的端，適合核對是否為已知管理節點。",
    ),
    "rpt_tr_top_users_subnote": _entry(
        "Top Users identifies which accounts appear most often in this traffic, helping confirm whether behaviour matches existing patterns.",
        "使用者排行用來辨識哪些帳號最常出現在這批流量中，可協助判斷是否符合既有操作模式。",
    ),
    "rpt_tr_top_processes_subnote": _entry(
        "Top Processes narrows down the binaries that initiated connections, separating normal services from background processes worth investigating.",
        "程序排行可協助釐清實際發起連線的程式，方便區分正常服務與值得追查的背景程序。",
    ),
    "rpt_tr_unmanaged_subnote": _entry(
        "Start with the scale of unmanaged traffic, then drill into which sources are most active and which managed Services they target.",
        "先看非受管流量的整體規模，再往下確認哪些來源最活躍，以及它們主要打到哪些受管 Service。",
    ),
    "rpt_tr_distribution_subnote": _entry(
        "Distribution tables are mainly for shape — good for spotting concentration around a single Service or sudden spikes in a protocol.",
        "流量分佈表主要用來看整體結構，適合確認是否存在過度集中的 Service 或突然升高的協定活動。",
    ),
    "rpt_tr_allowed_flows_subnote": _entry(
        "Focus on explicitly Allowed top flows and verify they are required business paths.",
        "先看目前被明確 Allow 的主要應用流向，確認哪些是業務必要路徑。",
    ),
    "rpt_tr_audit_flags_subnote": _entry(
        "Audit Flags lists traffic that is Allowed but still worth a human review.",
        "Audit Flags 會列出雖然已被 Allow，但仍值得再人工檢視的流量。",
    ),
    "rpt_tr_bandwidth_subnote": _entry(
        "Start from total volume and peak bandwidth to size overall data movement, then drill into which flows to inspect first.",
        "先從總傳輸量與峰值頻寬掌握整體資料移動規模，再往下看哪些流量最值得優先檢查。",
    ),
    "rpt_tr_readiness_subnote": _entry(
        "The readiness score estimates how ready the environment is to tighten Enforcement; a higher score usually means tighter convergence.",
        "readiness 分數用來評估目前環境是否適合進一步提高 Enforcement 強度，分數越高通常代表收斂程度越好。",
    ),
    "rpt_tr_lateral_intro": _entry(
        "Covers all lateral-movement analysis including IP-level host connection patterns and App(Env)-level graph risk scoring.",
        "本區涵蓋所有與橫向移動有關的分析，包含 IP 層級的主機連線模式與 App(Env) 層級的圖論風險評估。",
    ),
    "rpt_tr_lateral_talkers_subnote": _entry(
        "IP Top Talkers finds the hosts most active in lateral traffic, handy for checking whether they match known admin nodes.",
        "IP Top Talkers 用來找出最常參與橫向移動連線的來源主機，適合核對是否為已知管理節點。",
    ),
    "rpt_tr_sec_overview_intro": _entry(
        "Start from overall traffic scale, Policy coverage, and top Ports to set a baseline for reading the rest of the report.",
        "先從整體流量規模、Policy 覆蓋率與熱門 Port 建立基準視角，方便後續判讀各模組結果。",
    ),
    "rpt_tr_sec_policy_intro": _entry(
        "Break down the ratios and details of Allowed, Blocked, and Potentially Blocked to gauge how Policy is actually landing.",
        "拆解 Allow、Blocked 與 Potentially Blocked 的比例與細節，用來判斷目前 Policy 的實際落地程度。",
    ),
    "rpt_tr_sec_uncovered_intro": _entry(
        "Focus on traffic not yet covered by effective Policy, helping prioritise which Services and directions to tighten first.",
        "聚焦尚未被有效 Policy 覆蓋的流量，協助找出應優先補強的 Service 與通訊方向。",
    ),
    "rpt_tr_sec_ransomware_intro": _entry(
        "Check high-risk Ports, Allowed flows, and host exposure commonly tied to ransomware attack chains.",
        "檢查與勒索軟體常見攻擊鏈相關的高風險 Port、Allow 流量與主機曝露情況。",
    ),
    "rpt_tr_sec_user_intro": _entry(
        "Add user and process context to traffic to judge whether these connections match existing operational patterns.",
        "從使用者與程序視角補充流量背景，協助判斷這些連線是否符合既有操作模式。",
    ),
    "rpt_tr_sec_matrix_intro": _entry(
        "Observe cross-group communication by Label dimension, useful for surfacing segments that should not interact frequently.",
        "以 Label 維度觀察跨群組互通情況，適合用來找出原本不應頻繁互動的區段。",
    ),
    "rpt_tr_sec_unmanaged_intro": _entry(
        "Inventory traffic involving hosts not managed by VEN; these typically sit outside the visibility and control boundary.",
        "盤點未受 VEN 管理的主機流量，這些主機通常位於可視性與控管邊界之外。",
    ),
    "rpt_tr_sec_distribution_intro": _entry(
        "Observe how overall traffic is distributed across Ports and protocols to quickly spot concentration or unexpected highs.",
        "觀察整體流量在 Port 與協定上的分佈，快速辨識高集中度或異常偏高的類型。",
    ),
    "rpt_tr_sec_allowed_intro": _entry(
        "Focus on explicitly Allowed traffic to confirm which are required business paths and which still deserve an audit.",
        "聚焦目前被明確 Allow 的流量，確認哪些是業務必要路徑，哪些則應再做稽核。",
    ),
    "rpt_tr_sec_bandwidth_intro": _entry(
        "Review high-volume flows by bandwidth and data volume to identify large backups, batch jobs, or suspected exfiltration.",
        "從頻寬與資料量角度檢視高傳輸流量，用來辨識大型備份、批次作業或疑似資料外流。",
    ),
    "rpt_tr_sec_readiness_intro": _entry(
        "Aggregate multiple signals into a readiness score to help assess whether it is safe to tighten Enforcement.",
        "將多個訊號彙整成 readiness 分數，協助評估是否適合提高 Enforcement 強度。",
    ),
    "rpt_tr_sec_infrastructure_intro": _entry(
        "Identify critical nodes and infrastructure roles with large blast radius from application communication patterns.",
        "從應用通訊關係辨識關鍵節點與高影響範圍的基礎架構角色。",
    ),
    "rpt_tr_sec_lateral_intro": _entry(
        "Focus on paths, Services, and sources tied to lateral movement to surface spread risk.",
        "專門觀察與橫向移動有關的路徑、Service 與來源，協助辨識擴散風險。",
    ),
    "rpt_tr_investigation_note": _entry(
        "The following destination hosts have Allowed traffic on critical or high-risk Ports. Verify or consider blocking.",
        "以下目標主機在重大或高風險 Port 上有被 Allow 的流量，應進行驗證或考慮封鎖。",
    ),
    "rpt_tr_investigation_title_text": _entry(
        "⚠ Destination Hosts Requiring Investigation",
        "⚠ 需要調查的目標主機",
    ),
    "rpt_tr_no_investigation_text": _entry(
        "✅ No Allowed traffic on critical/high-risk Ports detected.",
        "✅ 未發現重大/高風險 Port 上的 Allow 流量。",
    ),
    "rpt_tr_host_exposure_subnote": _entry(
        "Destination hosts ranked by number of risk-Port touches, across all decisions including blocks.",
        "依接觸風險 Port 數量排序的目標主機，包含所有決策（含阻斷）。",
    ),
    "rpt_tr_anomalies_subnote": _entry(
        "Flows whose bytes-per-connection exceed P95 (only where connection count > 1); candidates for large transfers or exfiltration.",
        "每連線傳輸量高於 P95 的流量（僅計算連線數 &gt; 1），可能為大量傳輸或資料外洩候選項目。",
    ),
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
    "rpt_au_rule_changes": _entry("Rule Changes (Draft):", "Draft 規則變更："),
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
    "rpt_au_draft_section": _entry("Draft Rule Changes", "Draft 規則變更"),
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
        "<b>建議做法：</b>對範圍廣泛的規則變更與大規模 Provision 要特別審視，避免一次影響大量資產。",
    ),
    "rpt_au_change_detail_note": _entry(
        "<b>Change Tracking:</b> Use change details to review before/after differences for sensitive objects.",
        "<b>變更追蹤：</b>可透過 change detail 比對前後差異，特別適合檢查敏感物件是否被誤改。",
    ),
    "rpt_au_nav_correlation": _entry("4 Event Correlation", "4 事件時序關聯"),
    "rpt_au_sec_correlation": _entry("4 Event Correlation", "4 事件時序關聯"),
    "rpt_au_corr_summary": _entry("Correlated Sequences:", "關聯序列："),
    "rpt_au_brute_force": _entry("Brute Force Detections:", "暴力破解偵測："),
    "rpt_au_off_hours": _entry("Off-Hours Operations:", "非上班時段操作："),
    "rpt_au_corr_sequences": _entry("Correlated Attack Sequences", "關聯攻擊序列"),
    "rpt_au_corr_desc": _entry(
        "Events from the same actor or IP that form suspicious temporal patterns. "
        "Auth Failure → Policy Change is a strong indicator of credential compromise.",
        "同一操作者或 IP 產生的可疑時序模式。驗證失敗後緊接 Policy 異動是憑證遭入侵的強力指標。",
    ),
    "rpt_au_brute_section": _entry("Brute Force Detections", "暴力破解偵測"),
    "rpt_au_brute_desc": _entry(
        "Source IPs with ≥5 authentication failures within the correlation window.",
        "在關聯時間窗口內發生 ≥5 次驗證失敗的來源 IP。",
    ),
    "rpt_au_offhours_section": _entry("Off-Hours High-Risk Operations", "非上班時段高風險操作"),
    "rpt_au_offhours_desc": _entry(
        "High-risk policy changes outside business hours (08:00–19:00 UTC). "
        "These warrant verification with the actor.",
        "上班時間（UTC 08:00–19:00）以外的高風險 Policy 變更，建議向操作者確認。",
    ),
    "rpt_au_no_correlation": _entry("No suspicious temporal patterns detected.", "未偵測到可疑的事件時序模式。"),
    "rpt_au_footer": _entry("Illumio PCE Ops Audit Report", "Illumio PCE Ops 稽核報表"),
    "rpt_au_mod01_intro": _entry(
        "This section covers platform health, agent connectivity issues, and host-level security events. Cross-reference actor, target, source IP, and parser notes to decide if an event needs deeper investigation.",
        "本節聚焦於平台健康狀況、Agent 連線問題與主機層級安全事件。建議將 actor、target、來源 IP 與 parser notes 合併參照，以確認事件是否需要進一步調查。",
    ),
    "rpt_au_connectivity_subnote": _entry(
        "Connectivity events list agents that stopped sending heartbeats, were removed from Policy, or need re-pairing. Use target and resource columns to quickly identify the affected Workload.",
        "連線事件會列出停止回報心跳、已從 Policy 移除或需要重新配對的 Agent。可透過 target 與 resource 欄位快速辨識受影響的 Workload。",
    ),
    "rpt_au_mod02_intro": _entry(
        "User activity analysis focuses on parsed principal and action. The report prefers the affected user account as the primary identity, falling back to the actor field when the target cannot be resolved.",
        "使用者活動分析以解析後的 principal 與動作為主。報表優先使用受影響的使用者帳號作為主要身分，若目標無法取得則改用 actor 欄位。",
    ),
    "rpt_au_failed_detail_subnote": _entry(
        "Failed login records include the parsed target user, source IP, supplied username, and action path. Cross-check by user or source IP to spot repeated-failure patterns.",
        "登入失敗記錄已補充解析後的目標使用者、來源 IP、提供的帳號與動作路徑。建議依使用者或來源 IP 交叉確認是否有重複失敗的模式。",
    ),
    "rpt_au_mod03_intro": _entry(
        "Policy events now expose the parsed actor, target, resource, action, and change summary together, making it easier to separate Draft edits from Provision operations that actually affect Workloads.",
        "Policy 事件現在會同時呈現解析後的 actor、target、resource、動作與變更摘要，方便區分 Draft 編輯與實際影響 Workload 的 Provision 操作。",
    ),
    "rpt_au_provision_subnote": _entry(
        "Provision records show deployment impact directly. Cross-reference workloads affected, actor, source IP, resource name, and change detail to confirm that large Policy changes are expected.",
        "Provision 記錄會直接顯示部署影響範圍。建議同時對照 workloads affected、actor、來源 IP、resource 名稱與 change detail，確認大型 Policy 變更是否符合預期。",
    ),
    "rpt_au_provision_change_detail_note": _entry(
        "The <b>change_detail</b> summary shows commit messages, versions, and counts of changed and affected resources for Provision events.",
        "<b>change_detail</b> 摘要列出 Provision 事件的 commit 訊息、版本、異動物件數量與受影響資源。",
    ),
    "rpt_au_draft_subnote": _entry(
        "Draft changes are edits that have not been provisioned yet. Before the next Provision, review target, resource, action, and change detail to confirm scope.",
        "Draft 變更代表尚未 Provision 的編輯內容。在下次 Provision 前，建議透過 target、resource、動作與 change detail 確認變更範圍是否適當。",
    ),
    "rpt_au_draft_change_detail_note": _entry(
        "The <b>change_detail</b> summary aggregates field-level before/after differences for Draft edits, so auditors can verify scope and intent without opening raw JSON.",
        "<b>change_detail</b> 彙整 Draft 編輯的欄位層級前後差異，方便稽核人員不必開啟原始 JSON 就能確認變更範圍與意圖。",
    ),
    "rpt_au_per_user_policy_subnote": _entry(
        "This table aggregates Policy activity by parsed actor, separating admin operations, system tasks, and actions initiated by the Agent itself.",
        "此表依解析後的 actor 彙整 Policy 活動，方便區分管理員操作、系統任務與 Agent 主動觸發的動作。",
    ),
    "rpt_au_mod04_intro": _entry(
        "This section analyses temporal correlation between events, detecting typical attack-chain patterns such as Policy changes after auth failures, brute-force attempts, and high-risk off-hours operations.",
        "本區分析事件之間的時序關聯，偵測典型攻擊鏈模式，例如驗證失敗後的 Policy 異動、暴力破解嘗試、以及非上班時段的高風險操作。",
    ),
    "rpt_au_mod04_window_prefix": _entry("Correlation window:", "關聯時間窗口："),
    "rpt_au_mod04_window_suffix": _entry("minutes", "分鐘"),
    "rpt_ven_title": _entry("Illumio VEN Status Inventory Report", "Illumio VEN 狀態盤點報表"),
    "rpt_ven_nav_summary": _entry("Executive Summary", "摘要"),
    "rpt_ven_nav_online": _entry("Online VENs", "Online VEN"),
    "rpt_ven_nav_offline": _entry("Offline VENs", "Offline VEN"),
    "rpt_ven_nav_lost_today": _entry("Lost Today (<24h)", "今日失聯（<24h）"),
    "rpt_ven_nav_lost_yest": _entry("Lost Yesterday", "昨日失聯"),
    "rpt_ven_footer": _entry("Illumio PCE Ops VEN Status Report", "Illumio PCE Ops VEN 狀態報表"),
    "rpt_ven_kpi_total": _entry("Total VENs", "VEN 總數"),
    "rpt_ven_kpi_online": _entry("Online", "在線"),
    "rpt_ven_kpi_offline": _entry("Offline", "離線"),
    "rpt_ven_kpi_lost_24h": _entry("Lost in Last 24h", "近 24 小時失聯"),
    "rpt_ven_kpi_lost_48h": _entry("Lost 24-48h Ago", "24-48 小時前失聯"),
    "rpt_ven_sec_online_intro": _entry(
        "Workloads that keep sending heartbeats and can receive Policy updates. Use this list to confirm the healthy VEN inventory and agent versions.",
        "目前持續回報心跳且可正常套用 Policy 的 Workload。這張表適合拿來確認健康 VEN 清單與版本狀態。",
    ),
    "rpt_ven_sec_offline_intro": _entry(
        "Workloads that are not reporting. Check network, agent status, or whether they were decommissioned. Usually the first stop for asset-visibility issues.",
        "目前未正常回報的 Workload，請檢查連線、Agent 狀態或是否已除役。這張表通常是排查資產可視性問題的起點。",
    ),
    "rpt_ven_sec_lost_today_intro": _entry(
        "Lost heartbeat within the last 24 hours — investigate first. These usually map to recent network, agent, or host incidents.",
        "近 24 小時內失聯，建議優先排查。這些通常最有機會對應到新發生的網路、Agent 或主機異常。",
    ),
    "rpt_ven_sec_lost_yest_intro": _entry(
        "Lost heartbeat for more than a day but still recent. Confirm root cause before they become stale assets. Useful for tracking mid-term outages.",
        "已失聯超過一天，但仍屬近期事件，建議在成為陳舊資產前完成確認。這張表可用來追蹤持續未恢復的中短期異常。",
    ),
    "rpt_ven_sec_online_title": _entry("Online VENs", "Online VEN"),
    "rpt_ven_sec_offline_title": _entry("Offline VENs", "Offline VEN"),
    "rpt_ven_sec_lost_today_title": _entry("Lost Connection in Last 24h", "近 24 小時失聯"),
    "rpt_ven_sec_lost_yest_title": _entry("Lost Connection 24-48h Ago", "24-48 小時前失聯"),
    "rpt_pu_title": _entry("Illumio Policy Usage Report", "Illumio Policy 使用報表"),
    "rpt_pu_nav_summary": _entry("Executive Summary", "摘要"),
    "rpt_pu_nav_overview": _entry("1 Usage Overview", "1 使用總覽"),
    "rpt_pu_nav_hit": _entry("2 Hit Rules", "2 Hit Rules"),
    "rpt_pu_nav_unused": _entry("3 Unused Rules", "3 未使用 Rules"),
    "rpt_pu_nav_deny": _entry("4 Deny Effectiveness", "4 Deny 有效性"),
    "rpt_pu_sec_deny": _entry("4 Deny Rule Effectiveness", "4 Deny 規則有效性分析"),
    "rpt_pu_deny_total": _entry("Total Deny Rules", "Deny 規則總數"),
    "rpt_pu_deny_hit": _entry("Hit", "已命中"),
    "rpt_pu_deny_unused": _entry("Unused", "未使用"),
    "rpt_pu_deny_hit_rate": _entry("Hit Rate", "命中率"),
    "rpt_pu_override_deny": _entry("Override Deny Rules:", "覆寫式 Deny 規則："),
    "rpt_pu_deny_detail": _entry("Deny Rule Details", "Deny 規則明細"),
    "rpt_pu_no_deny": _entry("No deny rules found in the active policy.", "目前 Active Policy 中沒有 Deny 規則。"),
    "rpt_pu_footer": _entry("Illumio PCE Ops Policy Usage Report", "Illumio PCE Ops Policy 使用報表"),
    "rpt_pu_total_rules": _entry("Total Active Rules", "啟用中的規則總數"),
    "rpt_pu_hit_rules": _entry("Hit Rules", "Hit Rules"),
    "rpt_pu_unused_rules": _entry("Unused Rules", "未使用 Rules"),
    "rpt_pu_hit_rate": _entry("Hit Rate", "命中率"),
    "rpt_pu_attention": _entry("Top Rulesets by Unused Rules", "未使用 Rules 最多的 Rulesets"),
    "rpt_pu_caveat_title": _entry("Retention Period Caveat", "Retention 區間提醒"),
    "rpt_pu_caveat_body": _entry(
        "Rules with zero traffic hits in the analysed period may still have older hits outside the retention window. Review carefully before removal.",
        "在本次分析區間內沒有流量命中的 Rules，仍可能在更早的 retention 區間外有歷史命中紀錄，移除前請再確認。",
    ),
    "rpt_pu_no_hit_rules": _entry("No rules were hit during this period.", "此期間沒有任何規則被命中。"),
    "rpt_pu_no_unused_rules": _entry("All rules had traffic hits; no unused rules found.", "所有規則都有流量命中，沒有發現未使用的規則。"),
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
    "flows": ("Flows", "Flows"),
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
    "unique_ports": ("Unique Ports", "唯一 Port 數"),
    "unique_dst_hosts": ("Unique Dst Hosts", "唯一目的端主機數"),
    "unique_src_ips": ("Unique Src IPs", "唯一來源 IP 數"),
    "unique_dst_ips": ("Unique Dst IPs", "唯一目的端 IP 數"),
    "unique_src": ("Unique Src", "唯一來源"),
    "unique_dst": ("Unique Dst", "唯一目的端"),
    "unique_destinations": ("Unique Destinations", "唯一目的端數"),
    "unique_sources": ("Unique Sources", "唯一來源數"),
    "unique_risk_ports": ("Unique Risk Ports", "唯一風險 Port 數"),
    "unique_source_apps": ("Unique Source Apps", "唯一來源 App 數"),
    "unique_unmanaged_src": ("Unique Unmanaged Src", "唯一 unmanaged 來源"),
    "unique_unmanaged_sources": ("Unique Unmanaged Sources", "唯一 unmanaged 來源"),
    "destination_ip": ("Destination IP", "目的端 IP"),
    "destination_app": ("Destination App", "目的端 App"),
    "destination": ("Destination", "目的端"),
    "target_ip": ("Target IP", "目標 IP"),
    "exposed_ports": ("Exposed Ports", "暴露 Port"),
    "exposed_services": ("Exposed Services", "暴露 Service"),
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
    "L007": "Unmanaged 主機存取關鍵 Service",
    "L008": "Lateral Port 處於 Test Mode — Policy 尚未 Enforce",
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

for key, pair in {
    "rpt_tr_attack_summary": ("Attack Summary", "攻擊摘要"),
    "rpt_tr_boundary_breaches": ("Boundary Breaches", "邊界突破"),
    "rpt_tr_suspicious_pivot_behavior": ("Suspicious Pivot Behavior", "可疑橫向樞紐行為"),
    "rpt_tr_blast_radius": ("Blast Radius", "擴散半徑"),
    "rpt_tr_blind_spots": ("Blind Spots", "盲點"),
    "rpt_tr_action_matrix": ("Action Matrix", "行動矩陣"),
}.items():
    STRINGS[key] = _entry(pair[0], pair[1])

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
    var zhVisible = _lang === 'zh_TW';
    document.querySelectorAll('.zh-only').forEach(function(el) {{
      el.style.display = zhVisible ? '' : 'none';
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
