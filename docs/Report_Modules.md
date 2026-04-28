# Report Modules

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
<!-- END:doc-map -->

---

> **Background — Illumio concepts used in reports:** Reports in this section use Illumio's four-dimension label system (Role, Application, Environment, Location) to group and filter traffic flows, and reference per-workload enforcement modes (Idle, Visibility Only, Selective, Full) to explain why traffic appears as "potentially blocked" rather than blocked. For definitions of label dimensions and enforcement modes see [docs/Architecture.md — Background — Illumio Platform](Architecture.md#background--illumio-platform).

## 1. Generating Reports

Reports can be triggered from three places:

| Location | How |
|:---|:---|
| Web GUI → Reports tab | Click **Traffic Report**, **Audit Summary**, **VEN Status**, or **Policy Usage** |
| CLI → **2. Report Generation** sub-menu items 1–4 | Select report type and date range |
| Daemon mode | Configure via CLI **2. Report Generation → 5. Report Schedule Management** — reports run automatically and can be emailed |
| Command line | `python illumio_ops.py --report --report-type traffic\|audit\|ven_status\|policy_usage` |

Reports are saved to the `reports/` directory as `.html` (formatted report) and/or `_raw.zip` (CSV raw data) depending on your format setting.

**Dependencies required:**
```bash
pip install pandas pyyaml
```

### Reporting from cached PCE data

When `pce_cache.enabled = true` in `config.json`, Audit and Traffic reports automatically read from the local SQLite cache when the requested date range falls within the retention window. This reduces PCE API load and speeds up report generation.

If the requested range is outside the retention window, the report falls back to the live PCE API transparently.

To import historical data outside the retention window, use the backfill command:

```bash
illumio-ops cache backfill --source events --since YYYY-MM-DD --until YYYY-MM-DD
```

See `docs/PCE_Cache.md` for full details.

## 2. Report Types Overview

| Report Type | Data Source | Modules | Description |
|:---|:---|:---|:---|
| **Traffic** | PCE async traffic query or CSV | 15 modules + 19 Security Findings | Comprehensive traffic security analysis |
| **Audit** | PCE events API | 4 modules | System health, user activity, policy changes |
| **VEN Status** | PCE workloads API | Single generator | VEN inventory with online/offline classification |
| **Policy Usage** | PCE rulesets + traffic queries, or Workloader CSV | 4 modules | Per-rule traffic hit analysis |

## 3. Report Sections (Traffic Report)

A traffic report contains **15 analytical modules** plus the Security Findings section:

| Section | Description |
|:---|:---|
| Executive Summary | KPI cards: total flows, policy coverage %, top findings |
| 1 - Traffic Overview | Total flows, allowed/blocked/PB breakdown, top ports |
| 2 - Policy Decisions | Per-decision breakdown with inbound/outbound split and per-port coverage % |
| 3 - Uncovered Flows | Flows without an allow rule; port gap ranking; uncovered services (app+port) |
| 4 - Ransomware Exposure | **Investigation targets** (destination hosts with ALLOWED traffic on critical/high ports) prominently highlighted; per-port detail; host exposure ranking |
| 5 - Remote Access | SSH/RDP/VNC/TeamViewer traffic analysis |
| 6 - User & Process | User accounts and processes appearing in flow records |
| 7 - Cross-Label Matrix | Traffic matrix between environment/app/role label combinations |
| 8 - Unmanaged Hosts | Traffic from/to non-PCE-managed hosts; per-app and per-port detail |
| 9 - Traffic Distribution | Port and protocol distribution |
| 10 - Allowed Traffic | Top allowed flows; audit flags |
| 11 - Bandwidth & Volume | Top flows by bytes + Bandwidth (auto-scaled units); Max/Avg/P95 stat cards; anomaly detection (P95 of multi-connection flows) |
| 13 - Enforcement Readiness | Score 0–100 with factor breakdown and remediation recommendations |
| 14 - Infrastructure Scoring | Node centrality scoring to identify critical services (in-degree, out-degree, betweenness) |
| 15 - Lateral Movement Risk | Lateral movement pattern analysis and high-risk paths |
| **Security Findings** | **Automated rule evaluation — see Section 9.5** |

## 4. Security Findings Rules

The Security Findings section runs **19 automated detection rules** against every traffic dataset and groups results by severity (CRITICAL → INFO) and category.

**Rule series overview:**

| Series | Rules | Focus |
|:---|:---|:---|
| **B-series** | B001–B009 | Ransomware exposure, policy coverage gaps, behavioural anomalies |
| **L-series** | L001–L010 | Lateral movement, credential theft, blast-radius paths, data exfiltration |

**Quick reference:**

| Rule | Severity | What it detects |
|:---|:---|:---|
| B001 | CRITICAL | Ransomware ports (SMB/RDP/WinRM/RPC) not blocked |
| B002 | HIGH | Remote-access tools (TeamViewer/VNC/NetBIOS) allowed |
| B003 | MEDIUM | Ransomware ports in test mode — block not enforced |
| B004 | MEDIUM | High volume from unmanaged (non-PCE) hosts |
| B005 | MEDIUM | Policy coverage below threshold |
| B006 | HIGH | Single source fan-out on lateral movement ports |
| B007 | HIGH | Single user reaching abnormally many destinations |
| B008 | MEDIUM | High bandwidth anomaly (potential exfiltration/backup) |
| B009 | INFO | Cross-environment traffic volume above threshold |
| L001 | HIGH | Cleartext protocols (Telnet/FTP) in use |
| L002 | MEDIUM | Network discovery protocols unblocked (LLMNR/NetBIOS/mDNS) |
| L003 | HIGH | Database ports reachable from too many application tiers |
| L004 | HIGH | Database flows crossing environment boundaries |
| L005 | HIGH | Kerberos/LDAP accessible from too many source applications |
| L006 | HIGH | High blast-radius lateral path (BFS graph analysis) |
| L007 | HIGH | Unmanaged hosts accessing database/identity/management ports |
| L008 | HIGH | Lateral ports in test mode — policies exist but not enforced |
| L009 | HIGH | Data exfiltration pattern (managed → unmanaged, high bytes) |
| L010 | CRITICAL | Lateral ports allowed across environment boundaries |

For full documentation of each rule — including trigger conditions, attack technique context, and tuning guidance — see **[Security Rules Reference](Security_Rules_Reference.md)**.

## 5. Audit Report Sections

The Audit Report contains **4 modules**:

| Module | Description |
|:---|:---|
| Executive Summary | Event counts by severity and category; top event types |
| 1 - System Health Events | `agent.tampering`, offline agents, heartbeat failures |
| 2 - User Activity | Authentication events, login failures, account changes |
| 3 - Policy Changes | Ruleset and rule create/update/delete, policy provisioning |

## 6. VEN Status Report

The VEN Status Report inventories all PCE-managed workloads and classifies VEN connectivity:

| Section | Description |
|:---|:---|
| KPI Summary | Total VENs, Online count, Offline count |
| Online VENs | VENs with active agent status **and** last heartbeat ≤ 1 hour ago |
| Offline VENs | VENs that are suspended/stopped, or active but heartbeat > 1 hour ago |
| Lost (last 24 h) | Offline VENs whose last heartbeat was within the past 24 hours |
| Lost (24–48 h ago) | Offline VENs whose last heartbeat was 24–48 hours ago |

Each row includes: hostname, IP, labels, VEN status, hours since last heartbeat, last heartbeat timestamp, policy received timestamp, VEN version.

> **Online detection**: The PCE's `agent.status.status = "active"` reflects **administrative** state only. A VEN can remain `"active"` while unreachable (no heartbeat). The report uses `hours_since_last_heartbeat` — a VEN is considered online only if its last heartbeat was ≤ 1 hour ago. This matches the PCE Web Console behaviour.

## 7. Policy Usage Report

The Policy Usage Report analyzes how actively each PCE security rule is being used by matching it against actual traffic flows.

| Module | Description |
|:---|:---|
| Executive Summary | Total rules, rules with traffic hits, coverage percentage |
| Overview | Enabled/disabled breakdown, active/draft status |
| Executive Summary (`pu_mod00_executive`) | Total rules, rules with traffic hits, coverage percentage |
| Overview (`pu_mod01_overview`) | Enabled/disabled breakdown, active/draft status |
| Hit Detail (`pu_mod02_hit_detail`) | Rules with matching traffic; top flows per rule |
| Unused Detail (`pu_mod03_unused_detail`) | Rules with zero traffic hits; candidates for cleanup |
| Deny Effectiveness (`pu_mod04_deny_effectiveness`) | Confirms deny/override-deny rules are actively blocking unwanted traffic |
| Draft Policy Decision (`pu_mod05_draft_pd`) | Per-rule draft policy decision risk — visibility risk, draft conflicts, and draft coverage gap across three lenses |

**Data Sources:**
- **API mode**: Fetches active rulesets from the PCE, then runs parallel async traffic queries for each rule to count matching flows
- **CSV mode**: Imports a Workloader CSV export with pre-computed flow counts (for offline analysis)

## 8. Tuning Security Rules

All detection thresholds are in `config/report_config.yaml`:

```yaml
thresholds:
  min_policy_coverage_pct: 30         # B005
  lateral_movement_outbound_dst: 10   # B006
  db_unique_src_app_threshold: 5      # L003
  blast_radius_threshold: 5           # L006
  exfil_bytes_threshold_mb: 100       # L009
  cross_env_lateral_threshold: 5      # L010
  # ... (see Security_Rules_Reference.md for complete list)
```

Edit this file and re-run a report to apply new thresholds — no restart required.

## 9. Report Schedules

Configure automated recurring reports via CLI **2. Report Generation → 5. Report Schedule Management** or Web GUI **Report Schedules** tab:

| Field | Description |
|:---|:---|
| Report Type | Traffic Flow / Audit / VEN Status / **Policy Usage** |
| Frequency | Daily / Weekly (day of week) / Monthly (day of month) |
| Time | Hour and minute — input in your **configured timezone** (automatically stored as UTC) |
| Lookback Days | How many days of traffic data to include |
| Output Format | HTML / CSV Raw ZIP / Both |
| Send by Email | Attach report to email using SMTP settings |
| Custom Recipients | Override default recipients for this schedule |

> **Timezone note**: The time fields in CLI and Web GUI always display in the timezone configured under Settings → Timezone. The underlying storage is UTC, so the schedule remains correct if you change the timezone setting.

The daemon loop checks schedules every 60 seconds and runs any schedule whose configured time has been reached.

After each successful run, old report files are automatically cleaned up according to the **retention policy** — see Section 11.3.

## 10. R3 Intelligence Modules

These modules run automatically as part of the Traffic Report pipeline and appear as dedicated sections in the HTML output.

| Module | Purpose | Input | Output | Related config |
|---|---|---|---|---|
| `mod_change_impact` | Compare current report KPIs to the previous snapshot; emit `improved` / `regressed` / `neutral` verdict per KPI | Current KPIs dict + previous JSON snapshot | Delta table + overall verdict + previous snapshot timestamp | `report.snapshot_retention_days` |
| `mod_draft_actions` | Actionable remediation suggestions for draft policy decision sub-categories that need human review: Override Deny, Allowed Across Boundary, what-if | Flows DataFrame with `draft_policy_decision` column | `override_deny` block, `allowed_across_boundary` block, `what_if_summary` | `report.draft_actions_enabled` |
| `mod_draft_summary` | Count all 7 draft policy decision subtypes and list top workload pairs per subtype | Flows DataFrame with `draft_policy_decision` column | `counts` dict (7 subtypes) + `top_pairs` per subtype | — |
| `mod_enforcement_rollout` | Rank applications by readiness score for moving to full enforcement | Flows DataFrame with app labels (`src_app` / `dst_app`) + optional draft / readiness summaries | Prioritized app list with score, `why_now` rationale, required allow rules, risk reduction | — |
| `mod_exfiltration_intel` | Flag managed-to-unmanaged flows with high byte volume; optionally join against a CSV of known-bad IPs for threat-match enrichment | Flows DataFrame with `src_managed` / `dst_managed` + optional `bytes` column | `high_volume_exfil` list, `managed_to_unmanaged_count`, `threat_intel_matches` | `report.threat_intel_csv_path` |
| `mod_ringfence` | Per-application dependency profile + candidate allow rules for micro-segmentation; top-app summary when no specific app is targeted | Flows DataFrame with `src_app` / `dst_app` labels | Per-app: intra-app flows, cross-app flows, cross-env flows, candidate allow rules; or top-20 apps list | — |

**Threat Intel CSV format (`mod_exfiltration_intel`):**

The optional `report.threat_intel_csv_path` file must contain at least one column named `ip` (the known-bad IP address). Any additional columns (e.g. `threat_category`, `confidence`, `source`) are preserved and surfaced in the threat-match output:

```csv
ip,threat_category,confidence,source
185.220.101.1,tor_exit_node,high,abuse.ch
203.0.113.45,c2_server,critical,custom_intel
```

Set the path in `config.json`:

```json
{
    "report": {
        "threat_intel_csv_path": "/opt/illumio_ops/data/threat_intel.csv"
    }
}
```

When no file is configured or the file does not exist, `mod_exfiltration_intel` still runs — it will report high-volume managed→unmanaged flows but return an empty `threat_intel_matches` list.

**Application Ringfence usage (`mod_ringfence`):**

Use this module to isolate a single application's dependency profile before authoring micro-segmentation rules:

1. Run a Traffic Report (the module generates a top-20 app summary by default).
2. Identify the target application from the top-apps list.
3. Re-run the report focused on one app — the module will return intra-app flows, cross-app flows, cross-environment flows, and a candidate allow-rule list.
4. Use the candidate allow-rule list as the basis for creating label-based rules in the PCE.

The module skips silently if neither `src_app` nor `dst_app` labels exist in the traffic dataset.

## 11. Draft Policy Decision Behaviour

**Auto-enable of `compute_draft`:** When a ruleset contains rules that use `requires_draft_pd` logic (i.e., the ruleset has pending draft changes), the reporting pipeline automatically enables draft policy decision computation for that ruleset's traffic flows.

**HTML report header pill:** When draft computation is active, the Traffic Report HTML header displays a "Draft Policy Active" indicator pill to make the draft scope visible at a glance.

**`draft_breakdown` cross-tab (from `mod_draft_summary`):** A 7-column cross-tabulation showing the count of flows for each draft policy decision subtype:

| Subtype | Meaning |
|---|---|
| `allowed` | Flow would be allowed by the draft ruleset |
| `potentially_blocked` | Flow has no matching draft rule; default-deny would block it |
| `blocked_by_boundary` | Blocked by a boundary rule in the draft |
| `blocked_by_override_deny` | Blocked by an Override Deny rule in the draft |
| `potentially_blocked_by_boundary` | On a visibility workload; draft boundary would block on enforcement |
| `potentially_blocked_by_override_deny` | On a visibility workload; draft override deny would block on enforcement |
| `allowed_across_boundary` | Allowed despite crossing an application boundary — review required |

**`draft_enforcement_gap` (from `mod_draft_summary` / `mod_draft_actions`):** The set of flows where `policy_decision = potentially_blocked` but the draft resolves to `allowed` or `blocked_by_boundary` — i.e., flows that currently have no rule but would be covered (or explicitly blocked) once the draft is provisioned. This gap quantifies the enforcement delta that will take effect at the next Provision.

## 12. Change Impact Workflow

The `mod_change_impact` module compares KPIs from the current report to the most recent saved snapshot. This enables trend tracking across report runs without manual diffing.

**How snapshots work:**

1. Each time a Traffic Report is generated, the engine saves a snapshot JSON containing the report's KPI values and a `generated_at` timestamp.
2. On the next report run, `mod_change_impact` loads the previous snapshot and computes per-KPI deltas.
3. Snapshots older than `report.snapshot_retention_days` (default 90) are pruned automatically.

**KPI direction semantics:**

| KPI | Direction | Better when |
|---|---|---|
| `pb_uncovered_exposure` | lower-is-better | Decreasing = fewer uncovered flows |
| `high_risk_lateral_paths` | lower-is-better | Decreasing = lateral risk reduced |
| `blocked_flows` | lower-is-better | Decreasing = fewer blocked/dropped flows |
| `active_allow_coverage` | higher-is-better | Increasing = more flows have an explicit allow rule |
| `microsegmentation_maturity` | higher-is-better | Increasing = closer to full enforcement |

**Verdict logic:**

| Verdict | Condition |
|---|---|
| `improved` | More KPIs improved than regressed |
| `regressed` | More KPIs regressed than improved |
| `neutral` | Equal count of improved and regressed KPIs |

When no previous snapshot exists (first report run), the module returns `skipped: true` with `reason: no_previous_snapshot`.

**Operational use:** Run reports on a consistent schedule (e.g., weekly) and monitor the `overall_verdict` trend. A sustained `regressed` verdict after a policy change indicates the change introduced new coverage gaps or enabled unwanted traffic patterns that should be investigated.

## 13. Enforcement Rollout Planning

The `mod_enforcement_rollout` module ranks every application found in the traffic dataset by its readiness score for moving to full enforcement mode in the PCE.

**Scoring formula:**

```
score = (allowed_flows / total_flows) - (potentially_blocked_flows / total_flows)
```

A high score means most flows are already covered by allow rules (high numerator) and few flows would be disrupted by enabling default-deny (low denominator). A score near 1.0 indicates the application is ready for enforcement with minimal operational risk.

**Output per application:**

| Field | Description |
|---|---|
| `app` | Application label value |
| `priority` | Rank order (1 = most ready) |
| `why_now` | Human-readable rationale for this ranking |
| `expected_default_deny_impact` | Number of `potentially_blocked` flows that would be dropped |
| `required_allow_rules` | Inferred list of port/source pairs that need allow rules before enforcement |
| `risk_reduction` | Estimated reduction in lateral-movement exposure after enforcement |

Use the priority list to build an enforcement roadmap: start with priority-1 apps (already fully covered), work down to lower-priority apps that need additional allow rules.


---

## Appendix A — Report Module Inventory

> Translated from `docs/report_module_inventory_zh.md` (ed20df0~1) — refresh in Phase B.

# Report Module Inventory And Reader Guidance

本文盤點 illumio_ops 既有報表模組的實務價值，並定義每個章節應補充的導讀內容。目標是讓報表讀者不只看到圖表和表格，而是能理解「這章在回答什麼問題」、「哪些現象需要注意」、「下一步該做什麼」。

## NotebookLM 佐證摘要

根據 Illumio 筆記本中的手冊、API guide 與微分段技術說明，Traffic / Flow Visibility 在微分段專案中通常同時服務多個角色：

- 資安/SOC：威脅獵捕、異常偵測、事件回應、橫向移動與資料外洩調查。
- 網管/平台團隊：掌握連線相依性、建立 label-based allow rules、排查未納管或未知依賴。
- DevOps / DevSecOps：理解服務間連線，避免 CI/CD 或微服務變更破壞安全策略。
- App Owner：確認應用上下游依賴，審核合理白名單需求。

因此 Traffic Report 不應只是一份大而全報表。建議拆成兩種 profile：

- Security Risk Traffic Report：聚焦異常、危險流量、橫向移動、勒索軟體高風險埠、PB exposure、blocked/denied patterns、外部威脅或外洩跡象。
- Network Inventory Traffic Report：聚焦應用相依性、label matrix、candidate allow rules、shared infrastructure usage、unmanaged/unknown dependencies、enforcement readiness。

NotebookLM 也建議每個章節採固定導讀格式：

- 本章目的：這章回答什麼業務或資安問題。
- 要注意的訊號：哪些值、趨勢、組合代表異常或需要處理。
- 判讀方式：如何理解圖表、Policy Decision、label matrix 或風險分數。
- 建議行動：讀者看完後應調查、建規則、修 label、隔離、清理規則或修 VEN。

## 評分標準

| 分數 | 意義 |
| ---: | --- |
| 5 | 直接支援風險降低、事件調查、規則制定、enforcement 推進或治理決策。 |
| 4 | 對特定 persona 很有價值，但應 profile-specific 或摘要化。 |
| 3 | 有背景價值，但主報表中需要簡化或只在有異常時顯示。 |
| 2 | 適合 appendix / XLSX / CSV，不適合作為主要章節。 |
| 1 | 實務價值低、重複或容易誤導，除非重新設計否則應移除。 |

建議處置：

- `keep-main`：保留為主章節。
- `keep-profile-specific`：依 Security Risk / Network Inventory profile 決定是否主顯示。
- `redesign`：保留目的，但重寫摘要、圖表或導讀。
- `simplify`：保留但縮短。
- `conditional`：只有資料存在或偵測到異常時顯示。
- `appendix`：移到附錄、XLSX 或 CSV。
- `merge/remove`：合併到其他章節或移除。

## Traffic Report 模組盤點

| Module | 實務價值 | 建議 | 主要受眾 | 章節應表達什麼 |
| --- | ---: | --- | --- | --- |
| `mod01_traffic_overview` | 3 | `simplify` | mixed | 說明資料範圍、流量規模、時間範圍與政策決策概況；不應變成主要決策章節。 |
| `mod02_policy_decisions` | 5 | `keep-profile-specific` | security/network | 說明 allowed / blocked / potentially_blocked 的真實比例。資安看未授權或危險流量；網管看規則覆蓋與 enforcement 影響。 |
| `mod03_uncovered_flows` | 5 | `keep-main` | security/network | 說明哪些流量缺乏 allow policy，進入 enforcement 後可能被 default-deny 影響。PB 必須被視為 gap，不是 staged coverage。 |
| `mod04_ransomware_exposure` | 5 | `keep-profile-specific` | security | 找出 SMB、RDP、SSH 等高風險橫向移動通道，協助資安優先調查或限制。 |
| `mod05_remote_access` | 2 | `merge/remove` | security | 已被 `mod15_lateral_movement` 整併，不建議恢復成獨立主章節，避免重複。 |
| `mod06_user_process` | 3 | `conditional` | security | 當 user/process 欄位存在時，找出異常執行程序、非預期使用者或可疑高活動行為。無資料時不應空顯示。 |
| `mod07_cross_label_matrix` | 4 | `keep-profile-specific` | network/app_owner | 把 observed flows 轉成 label-to-label 依賴矩陣，支援規則制定。資安版只應顯示 risky crossing。 |
| `mod08_unmanaged_hosts` | 5 | `keep-main` | security/network | 找出受管 workload 與 unknown/unmanaged destination 的連線。這同時是風險盲點與規則制定阻礙。 |
| `mod09_traffic_distribution` | 2 | `appendix` | network | Port/protocol 分布本身不是決策；只有出現異常集中、陌生服務或趨勢變化時才適合主顯示。 |
| `mod10_allowed_traffic` | 4 | `keep-profile-specific` | network/security | 網管用於建立 allow rules；資安只看 high-risk allowed paths 或跨區域高風險 allowed traffic。 |
| `mod11_bandwidth` | 3 | `conditional` | security/network | 高流量可用於外洩或容量判讀，但一般 Top Talkers 應進 appendix。 |
| `mod12_executive_summary` | 5 | `redesign` | executive/mixed | 應依 profile 產出不同摘要。風險版講 top risks/actions；盤點版講 rule readiness/dependency gaps。 |
| `mod13_readiness` | 5 | `keep-main` | network/executive | 評估哪些 app/env 可推 enforcement、哪些 label/rule/unknown dependency 還沒準備好。 |
| `mod14_infrastructure` | 5 | `keep-profile-specific` | security/network | 找出 DNS、AD、NTP、DB、proxy、backup、logging 等 shared/crown-jewel service 的暴露與依賴。 |
| `mod15_lateral_movement` | 5 | `keep-profile-specific` | security/network | 資安版用來看橫向移動與 blast radius；盤點版用來理解跨 app/env 依賴與 enforcement 邊界。 |
| `attack_posture.py` | 5 | `keep-supporting` | security/executive | 應作為風險評分與 Top Actions 來源，而不是再產生一個讀者不懂的獨立章節。 |

## Audit Report 模組盤點

| Module | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| `audit_mod00_executive` | 4 | `keep-main` | 說明 audit 期間是否有高風險操作、異常控制面活動、需立即關注的事件。 |
| `audit_mod01_health` | 4 | `keep-main` | 說明 PCE/API/audit 資料是否可信，是否有同步、健康或資料完整性問題。 |
| `audit_mod02_users` | 3 | `conditional` | 只在出現高權限、非預期、離峰或異常大量操作時主顯示；一般 top users 應 appendix。 |
| `audit_mod03_policy` | 5 | `keep-main` | 說明 policy/rule set 變更是否合理、是否過寬、是否可能造成風險或斷線。 |
| `audit_mod04_correlation` | 5 | `keep-main` | 把 auth failure、policy change、VEN change、provision 等事件串成可調查故事。 |
| `audit_risk.py` | 5 | `keep-supporting` | 支撐 audit risk scoring 與 attention required，不應讓讀者只看到分數但不知道原因。 |

## Policy Usage Report 模組盤點

| Module | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| `pu_mod00_executive` | 4 | `redesign` | 應說明可清理規則、有效 deny、過寬 allow 與查詢信心，而不是只列總數。 |
| `pu_mod01_overview` | 3 | `simplify` | 保留查詢範圍與資料品質，不應成為主要章節。 |
| `pu_mod02_hit_detail` | 4 | `appendix/main-summary` | Top hit rules 可主顯示；完整 hit detail 應進 XLSX/CSV。 |
| `pu_mod03_unused_detail` | 5 | `keep-main` | 直接支援規則清理與 policy hygiene，是高價值章節。 |
| `pu_mod04_deny_effectiveness` | 5 | `keep-main` | 證明 deny/override deny 是否有效阻擋不想要的流量，支援控制有效性。 |

## VEN Status Report 盤點

| Section | 實務價值 | 建議 | 章節應表達什麼 |
| --- | ---: | --- | --- |
| VEN summary | 5 | `keep-main` | 說明整體 agent 健康、enforcement 進度與 segmentation blind spots。 |
| Offline / lost heartbeat | 5 | `keep-main` | 失聯 workload 會造成控制盲點，應優先依 app/env/role 影響排序。 |
| Policy sync status | 5 | `keep-main` | Policy 未同步代表控制狀態可能與 PCE 不一致，應列出需修復對象。 |
| Enforcement mode | 5 | `keep-main` | 追蹤 visibility_only/selective/full 推進狀態，支援微分段專案進度管理。 |
| Online inventory | 2 | `appendix` | 完整線上清單適合 XLSX，不適合主報表。 |

## 建議章節導讀格式

每個主要章節都應在圖表或表格前加入導讀區塊。

```text
本章目的：
說明這章回答的問題，以及它和微分段/風險/規則制定的關係。

要注意的訊號：
列出應優先關注的數值、趨勢、異常組合或資料缺口。

判讀方式：
解釋圖表、Policy Decision、label matrix、風險分數或狀態欄位應如何解讀。

建議行動：
提供讀者下一步，例如調查、確認 App Owner、建立 allow rule、修 label、隔離主機、清理規則或修復 VEN。
```

## 高優先章節導讀範例

### Potentially Blocked / Uncovered Flows

本章目的：找出目前因 workload 尚未進入完整 enforcement 而仍可通過，但缺乏 matching allow rule 的流量。

要注意的訊號：PB 流量集中在核心服務、高風險 port、跨 env、跨 app、unmanaged destination，或在近期變更後突然上升。

判讀方式：`potentially_blocked` 不是「規則已準備好」，而是「目前沒有對應 allow/deny rule；若進入 default-deny enforcement，這類流量可能被阻擋」。

建議行動：與 App Owner 確認是否為合法依賴。合法流量應轉成 label-based allow rule；不合法或未知流量應保留為未來 enforcement 的阻擋候選。

### Application Dependency / Cross-Label Matrix

本章目的：把 observed east-west flows 轉成可制定微分段規則的 app/env/role/service 依賴。

要注意的訊號：Dev 到 Prod、跨 app 直連 DB、unknown destination、unmanaged dependency、過多 any-to-any 類型連線。

判讀方式：矩陣不是要展示所有流量，而是要幫網管和 App Owner 確認「哪些 label group 之間需要 allow rule」。

建議行動：將合法依賴整理成候選 allow rules；補齊缺失 label；將 unknown IP 建成 IP List 或 unmanaged workload；移除不符合架構的依賴。

### Lateral Movement

本章目的：找出可能擴大攻擊面或支援橫向移動的 east-west path。

要注意的訊號：SMB/RDP/SSH/WinRM 等高風險 port、單一來源連大量目的地、跨 zone/cross-env 通訊、連向 crown-jewel infrastructure。

判讀方式：節點和邊的數量代表 blast radius；高風險服務和跨邊界連線應比一般流量優先處理。

建議行動：對可疑來源啟動事件調查；對合法但高風險依賴建立最小權限規則；必要時 quarantine 或先以 deny/boundary 限縮。

### Draft Policy

本章目的：在 provision 前模擬規則變更對現有流量的影響。

要注意的訊號：Draft View 中關鍵業務流量仍為 not allowed / potentially blocked，或新規則 scope 過寬。

判讀方式：Reported View 是目前實際狀態；Draft View 是草稿規則生效後的預期狀態。兩者差異應被視為變更影響分析。

建議行動：Provision 前先確認必要流量已被 allow；縮小過寬規則；把仍會被阻擋的合法流量補成候選規則。

### VEN Status

本章目的：確認 segmentation control plane 是否能實際作用到 workload。

要注意的訊號：offline、lost heartbeat、degraded、policy not synced、host firewall tampering、長期停留 visibility_only。

判讀方式：沒有健康 VEN，就算 PCE 有正確 policy，也可能無法有效執行。VEN 問題應視為 segmentation blind spot。

建議行動：優先修復 crown-jewel 或高風險 app 的 VEN；檢查 PCE 連線、憑證、service 狀態與 policy sync；將健康且規則完整的 workload 推進 enforcement。


## See also

- [User Manual](./User_Manual.md) — Execution modes, rule types, alert channels, and deployment
- [Security Rules Reference](./Security_Rules_Reference.md) — R-Series rules and `compute_draft` behaviour
- [Architecture](./Architecture.md) — System overview, module map, PCE Cache, REST API Cookbook
