# Dashboard i18n Audit

**Scope keys:** 231
**Findings:** 107

## Rule: mixed_language (37)

| Key | EN | ZH | Detail |
|---|---|---|---|
| `actmtx_staged_enforcement_reco` | Move workloads from test/visibility to selective or full enforcement. | 將 workload 從 test/visibility 模式移至 selective 或 full enforcement。 | non-glossary Latin tokens: ['workload', 'test', 'visibility', 'selective', 'full', 'enforcement'] |
| `gui_attack_summary_title` | Attack Summary | 攻擊摘要（Boundary/Pivot/Blast Radius/Blind Spots/行動） | non-glossary Latin tokens: ['Boundary', 'Pivot', 'Blast', 'Radius', 'Blind', 'Spots'] |
| `gui_card_suppressed_tooltip` | Cumulative alerts suppressed by cooldown or throttle rules. Counts the events th | 因 cooldown 或 throttle 規則被擋下、未派送的累積警示次數。代表事件確實命中規則但限流機制阻止它寄到 Email/LINE/Webhook，避 | non-glossary Latin tokens: ['cooldown', 'throttle', 'Email', 'LINE', 'Webhook'] |
| `gui_card_unknown_types_tooltip` | PCE event types that arrived but matched no configured monitoring rule. Capped a | PCE 傳來但沒有任何 monitoring 規則涵蓋的 event_type 種類數，上限 100 種。數字大表示規則覆蓋率不足、可能漏抓新型事件；至「事件檢 | non-glossary Latin tokens: ['monitoring', 'event_type'] |
| `gui_csv_required` | CSV file required | 請先選擇 CSV 檔案 | non-glossary Latin tokens: ['CSV'] |
| `gui_detailed_kpis_label` | Detailed metrics (12 KPIs) | 詳細指標（12 KPI） | non-glossary Latin tokens: ['KPI'] |
| `gui_err_no_csv` | No CSV file uploaded. | 未上傳 CSV 檔案。 | non-glossary Latin tokens: ['CSV'] |
| `gui_gen_policy_diff_title` | Generate Policy Diff Report | 產生 Policy Diff 報表 | non-glossary Latin tokens: ['Diff'] |
| `gui_gen_step_parsing` | Parsing CSV data... | 正在解析 CSV 資料... | non-glossary Latin tokens: ['CSV'] |
| `gui_ip_address` | IP Address | IP 位址 | non-glossary Latin tokens: ['IP'] |
| `gui_ov_eyebrow_security` | Security Posture | 安全體質 · Security Posture | non-glossary Latin tokens: ['Security', 'Posture'] |
| `gui_ov_os_dist` | OS Distribution | OS 分布 | non-glossary Latin tokens: ['OS'] |
| `gui_ov_posture_unavailable` | Run a Security Posture report to populate this section. | 請執行 Security Posture 報表以載入此區塊。 | non-glossary Latin tokens: ['Security', 'Posture'] |
| `gui_ov_risk_feed_title` | Top Risk Findings | Top 風險發現 | non-glossary Latin tokens: ['Top'] |
| `gui_query_flow` | Query Flow | 查詢 Flow | non-glossary Latin tokens: ['Flow'] |
| `gui_rank_bw` | Max Bandwidth (Mbps) | 最大頻寬（Mbps） | non-glossary Latin tokens: ['Mbps'] |
| `gui_snap_col_dst_ip` | Destination IP | 目的端 IP | non-glossary Latin tokens: ['IP'] |
| `gui_snap_col_flow_count` | Flow Count | Flow 數 | non-glossary Latin tokens: ['Flow'] |
| `gui_snap_col_src_ip` | Source IP | 來源 IP | non-glossary Latin tokens: ['IP'] |
| `gui_snap_top_ports` | Top 10 Ports (by flow count) | Top 10 Ports（依流量筆數） | non-glossary Latin tokens: ['Top'] |
| `gui_source_badge_api` | Data fetched live from the PCE API. | 資料即時來自 PCE API。 | non-glossary Latin tokens: ['API'] |
| `gui_source_badge_mixed` | Hybrid: API filled the gap before the cache window started; cache served the res | 混合:API 補快取區間之前的空檔,快取提供其後的部分。 | non-glossary Latin tokens: ['API'] |
| `gui_ta_query` | Traffic Analysis Query | 查詢 Flow | non-glossary Latin tokens: ['Flow'] |
| `gui_toast_policy_diff_done` | Policy Diff report generated. | Policy Diff 報表已產生。 | non-glossary Latin tokens: ['Diff'] |
| `gui_toast_policy_diff_fail` | Policy Diff report failed. | Policy Diff 報表產生失敗。 | non-glossary Latin tokens: ['Diff'] |
| `gui_top10_error` | Error querying data. | Top 10 查詢失敗 | non-glossary Latin tokens: ['Top'] |
| `gui_top10_loading` | Loading... | 正在載入 Top 10... | non-glossary Latin tokens: ['Top'] |
| `gui_top10_querying` | Querying... | 正在查詢 Top 10... | non-glossary Latin tokens: ['Top'] |
| `gui_top_actions_heading` | Top Actions | Top 3 行動建議 | non-glossary Latin tokens: ['Top'] |
| `gui_tw_kpi_dst_ips` | Unique destination IPs | 唯一目的 IP | non-glossary Latin tokens: ['IP'] |
| `gui_ws_col_ip` | IP Address | IP 位址 | non-glossary Latin tokens: ['IP'] |
| `gui_ws_col_management` | Management | Manage 狀態 | non-glossary Latin tokens: ['Manage'] |
| `pd_allowed_across_boundary` | Allowed Across Boundary | Allowed Across Boundary（越過邊界 Allow） | non-glossary Latin tokens: ['Across', 'Boundary'] |
| `pd_blocked_by_boundary` | Blocked by Boundary | Blocked by Boundary（邊界 Block） | non-glossary Latin tokens: ['by', 'Boundary'] |
| `pd_blocked_by_override_deny` | Blocked by Override Deny | Blocked by Override Deny（強制拒絕 Block） | non-glossary Latin tokens: ['by', 'Override', 'Deny'] |
| `pd_potentially_blocked_by_boundary` | Potentially Blocked by Boundary | Potentially Blocked by Boundary（潛在邊界 Block） | non-glossary Latin tokens: ['Potentially', 'by', 'Boundary'] |
| `pd_potentially_blocked_by_override_deny` | Potentially Blocked by Override Deny | Potentially Blocked by Override Deny（潛在強制拒絕 Block） | non-glossary Latin tokens: ['Potentially', 'by', 'Override', 'Deny'] |

## Rule: low_han_ratio (27)

| Key | EN | ZH | Detail |
|---|---|---|---|
| `actmtx_staged_enforcement_reco` | Move workloads from test/visibility to selective or full enforcement. | 將 workload 從 test/visibility 模式移至 selective 或 full enforcement。 | han_ratio=0.13 |
| `gui_attack_summary_title` | Attack Summary | 攻擊摘要（Boundary/Pivot/Blast Radius/Blind Spots/行動） | han_ratio=0.15 |
| `gui_card_health` | PCE Health | PCE 健康 | han_ratio=0.40 |
| `gui_gen_policy_diff_title` | Generate Policy Diff Report | 產生 Policy Diff 報表 | han_ratio=0.29 |
| `gui_ov_enforcement_modes` | Enforcement Modes | Enforcement 模式 | han_ratio=0.15 |
| `gui_ov_eyebrow_security` | Security Posture | 安全體質 · Security Posture | han_ratio=0.21 |
| `gui_ov_posture_unavailable` | Run a Security Posture report to populate this section. | 請執行 Security Posture 報表以載入此區塊。 | han_ratio=0.42 |
| `gui_ov_ven_title` | VEN Health | VEN 健康 | han_ratio=0.40 |
| `gui_policy_dec` | Policy Decision | Policy 判定 | han_ratio=0.25 |
| `gui_query_flow` | Query Flow | 查詢 Flow | han_ratio=0.33 |
| `gui_sched_rt_pu` | Policy Usage | Policy 使用報表 | han_ratio=0.40 |
| `gui_snap_col_flow_count` | Flow Count | Flow 數 | han_ratio=0.20 |
| `gui_snap_policy_breakdown` | Policy Decision Breakdown | Policy 判定分布 | han_ratio=0.40 |
| `gui_snap_top_ports` | Top 10 Ports (by flow count) | Top 10 Ports（依流量筆數） | han_ratio=0.38 |
| `gui_ta_query` | Traffic Analysis Query | 查詢 Flow | han_ratio=0.33 |
| `gui_toast_policy_diff_done` | Policy Diff report generated. | Policy Diff 報表已產生。 | han_ratio=0.33 |
| `gui_toast_policy_diff_fail` | Policy Diff report failed. | Policy Diff 報表產生失敗。 | han_ratio=0.38 |
| `gui_tw_trend_flagged_only` | Flagged only (hide Allowed) | 只看可疑（隱藏 Allowed） | han_ratio=0.46 |
| `gui_workload_name` | Workload Name | Workload 名稱 | han_ratio=0.20 |
| `gui_workload_search` | Workload Search | Workload 搜尋 | han_ratio=0.20 |
| `gui_ws_col_management` | Management | Manage 狀態 | han_ratio=0.25 |
| `gui_ws_search` | Workload Search | Workload 搜尋 | han_ratio=0.20 |
| `pd_allowed_across_boundary` | Allowed Across Boundary | Allowed Across Boundary（越過邊界 Allow） | han_ratio=0.13 |
| `pd_blocked_by_boundary` | Blocked by Boundary | Blocked by Boundary（邊界 Block） | han_ratio=0.08 |
| `pd_blocked_by_override_deny` | Blocked by Override Deny | Blocked by Override Deny（強制拒絕 Block） | han_ratio=0.13 |
| `pd_potentially_blocked_by_boundary` | Potentially Blocked by Boundary | Potentially Blocked by Boundary（潛在邊界 Block） | han_ratio=0.11 |
| `pd_potentially_blocked_by_override_deny` | Potentially Blocked by Override Deny | Potentially Blocked by Override Deny（潛在強制拒絕 Block） | han_ratio=0.14 |

## Rule: too_short_vs_english (33)

| Key | EN | ZH | Detail |
|---|---|---|---|
| `gui_btn_download` | Download | 下載 | en_len=8 zh_len=2 |
| `gui_delete_partial` | Some items failed to delete | 部分項目刪除失敗 | en_len=27 zh_len=8 |
| `gui_destination_identity` | Destination Identity | 目的端識別 | en_len=20 zh_len=5 |
| `gui_filter_details` | Filter Details | 查詢條件 | en_len=14 zh_len=4 |
| `gui_filter_settings` | Filter Settings | 篩選條件 | en_len=15 zh_len=4 |
| `gui_gen_audit_title` | Generate Audit Report | 產生稽核報表 | en_len=21 zh_len=6 |
| `gui_gen_fallback_title` | Generate report | 產生報表 | en_len=15 zh_len=4 |
| `gui_opt_connections` | Connections | 連線數 | en_len=11 zh_len=3 |
| `gui_opt_volume` | Total Volume | 總流量 | en_len=12 zh_len=3 |
| `gui_ov_eyebrow_ops` | Operations & Estate | 營運與估產 | en_len=19 zh_len=5 |
| `gui_param_guide` | Parameter Guide | 參數說明 | en_len=15 zh_len=4 |
| `gui_rank_conn` | Connections | 連線 | en_len=11 zh_len=2 |
| `gui_reports_empty` | Use the buttons above to generate your first report. | 請使用上方按鈕產生第一份報表。 | en_len=52 zh_len=15 |
| `gui_sched_day_of_month` | Day of month | 每月第 | en_len=12 zh_len=3 |
| `gui_sched_empty` | No report schedules configured. | 目前沒有報表排程。 | en_len=31 zh_len=9 |
| `gui_sched_save_failed` | Failed to save schedule. | 儲存排程失敗。 | en_len=24 zh_len=7 |
| `gui_snap_bw_title` | Traffic Summary | 流量摘要 | en_len=15 zh_len=4 |
| `gui_snap_col_action` | Recommended Action | 建議動作 | en_len=18 zh_len=4 |
| `gui_snap_col_connections` | Connections | 連線數 | en_len=11 zh_len=3 |
| `gui_snap_col_decision` | Decision | 判定 | en_len=8 zh_len=2 |
| `gui_snap_col_recommendation` | Recommendation | 建議 | en_len=14 zh_len=2 |
| `gui_snap_title` | Latest Traffic Report Summary | 最新流量報表摘要 | en_len=29 zh_len=8 |
| `gui_time_just_now` | just now | 剛剛 | en_len=8 zh_len=2 |
| `gui_toast_audit_fail` | Audit report generation failed | 產生稽核報表失敗 | en_len=30 zh_len=8 |
| `gui_toast_traffic_fail` | Traffic report generation failed | 產生流量報表失敗 | en_len=32 zh_len=8 |
| `gui_top10_no_records` | No records found. | 查無記錄。 | en_len=17 zh_len=5 |
| `gui_top10_title` | Ranking Summary | 排行統計 | en_len=15 zh_len=4 |
| `gui_traffic_analyzer` | Traffic Analyzer | 流量分析 | en_len=16 zh_len=4 |
| `gui_traffic_run_query_empty` | Run a query to view real-time traffic anomalies. | 執行查詢以檢視即時流量異常。 | en_len=48 zh_len=14 |
| `gui_tw_kpi_conns` | Total Connections | 總連線 | en_len=17 zh_len=3 |
| `gui_tw_kpi_flows` | Total Flows | 總流量 | en_len=11 zh_len=3 |
| `gui_tw_kpi_peak_bw` | Peak bandwidth | 尖峰頻寬 | en_len=14 zh_len=4 |
| `gui_window_min` | Window (min) | 分鐘 | en_len=12 zh_len=2 |

## Rule: untranslated (10)

| Key | EN | ZH | Detail |
|---|---|---|---|
| `gui_ov_posture_score_label` | Posture Score | Posture Score | zh equals en (case-insensitive) |
| `gui_pd_allowed` | Allowed | Allowed | zh equals en (case-insensitive) |
| `gui_pd_blocked` | Blocked | Blocked | zh equals en (case-insensitive) |
| `gui_service_port` | Service | Service | zh equals en (case-insensitive) |
| `gui_snap_col_flows` | Flows | Flows | zh equals en (case-insensitive) |
| `gui_snap_col_port` | Port | Port | zh equals en (case-insensitive) |
| `gui_tw_trend_allowed` | Allowed | Allowed | zh equals en (case-insensitive) |
| `gui_tw_trend_blocked` | Blocked | Blocked | zh equals en (case-insensitive) |
| `gui_tw_trend_potential` | Potentially Blocked | Potentially Blocked | zh equals en (case-insensitive) |
| `gui_ws_col_labels` | Labels | Labels | zh equals en (case-insensitive) |
