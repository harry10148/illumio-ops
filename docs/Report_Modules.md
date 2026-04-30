# Report Modules

<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| Installation | [Installation.md](./Installation.md) | [Installation_zh.md](./Installation_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Report Modules | [Report_Modules.md](./Report_Modules.md) | [Report_Modules_zh.md](./Report_Modules_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
| SIEM Integration | [SIEM_Integration.md](./SIEM_Integration.md) | [SIEM_Integration_zh.md](./SIEM_Integration_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| PCE Cache | [PCE_Cache.md](./PCE_Cache.md) | [PCE_Cache_zh.md](./PCE_Cache_zh.md) |
| API Cookbook | [API_Cookbook.md](./API_Cookbook.md) | [API_Cookbook_zh.md](./API_Cookbook_zh.md) |
| Glossary | [Glossary.md](./Glossary.md) | [Glossary_zh.md](./Glossary_zh.md) |
| Troubleshooting | [Troubleshooting.md](./Troubleshooting.md) | [Troubleshooting_zh.md](./Troubleshooting_zh.md) |
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
| Command line | `python illumio-ops.py --report --report-type traffic\|audit\|ven_status\|policy_usage` |

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
| `mod_ringfence` | Per-application dependency profile + candidate allow rules for micro-segmentation; top-app summary when no specific app is targeted | Flows DataFrame with `src_app` / `dst_app` labels | Per-app: intra-app flows, cross-app flows, cross-env flows, candidate allow rules; or top-20 apps list | — |

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

---

## Appendix A — Module-by-Module Reader Guidance (ZH)

A persona-based scoring of every report module — its practical value, the audience it serves (security/SOC, network ops, app owner, executive), and the narrative each section should provide ("what question does it answer", "what signals matter", "how to interpret", "what to do next") — is maintained in **Traditional Chinese** in the matching ZH document:

→ **[Report_Modules_zh.md §附錄 A](Report_Modules_zh.md#附錄-a--報表模組清單與導讀指南)**

The inventory uses a 5→1 practical-value scale and dispositions like `keep-main`, `keep-profile-specific`, `simplify`, `conditional`, `appendix`, `merge/remove`. It covers every Traffic Report module:

`mod01_traffic_overview`, `mod02_policy_decisions`, `mod03_uncovered_flows`, `mod04_ransomware_exposure`, `mod05_remote_access`, `mod06_user_process`, `mod07_cross_label_matrix`, `mod08_unmanaged_hosts`, `mod09_traffic_distribution`, `mod10_allowed_traffic`, `mod11_bandwidth`, `mod12_executive_summary`, `mod13_readiness`, `mod14_infrastructure`, `mod15_lateral_movement`

…plus the Audit, Policy Usage, and VEN Status modules.

It also splits the Traffic Report into two persona profiles:

- **Security Risk Traffic Report** — anomalies, lateral movement, ransomware-tier ports, PB exposure, blocked/denied patterns, exfiltration signals.
- **Network Inventory Traffic Report** — application dependencies, label matrices, candidate allow rules, shared/crown-jewel services, unmanaged/unknown dependencies, enforcement readiness.

When that material is translated to English (a planned follow-up), the canonical version will live here and the ZH document will become its translation. Until then, English readers may rely on the per-module descriptions in §3–§7 above plus the Security Findings catalog in [Security Rules Reference](Security_Rules_Reference.md).


## See also

- [User Manual](./User_Manual.md) — Execution modes, rule types, alert channels, and deployment
- [Security Rules Reference](./Security_Rules_Reference.md) — R-Series rules and `compute_draft` behaviour
- [Architecture](./Architecture.md) — System overview, module map, PCE Cache, REST API Cookbook
