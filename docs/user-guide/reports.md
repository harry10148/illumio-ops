---
title: Reports
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/report/
  - src/report/rules/
  - src/report/exporters/
  - src/report/analysis/
  - src/report/rules_engine.py
  - python illumio-ops.py report --help
  - python illumio-ops.py report traffic --help
  - python illumio-ops.py report audit --help
  - python illumio-ops.py report ven-status --help
  - python illumio-ops.py report policy-usage --help
  - commit e7722ba
related_docs:
  - ../architecture/report-engine.md
  - ../reference/cli.md
  - alerts-and-quarantine.md
  - siem-integration.md
---

> 🌐 **[English](reports.md)** | **[繁體中文](reports_zh.md)**
> 📍 [INDEX](../INDEX.md) › User Guide › Reports
> 🔍 Last verified **2026-05-15** against commit `e7722ba` — see frontmatter for sources

# Reports

Illumio PCE Ops generates four types of reports from live PCE data or cached datasets.
Reports are saved under `reports/` as `.html` and optionally as `.csv` / `.xlsx` raw-data archives.

---

## Report types overview

| Report type | CLI subcommand | Primary data source | Purpose |
|:---|:---|:---|:---|
| **Traffic** | `report traffic` | PCE async query or CSV | Comprehensive traffic security analysis — policy decisions, ransomware exposure, lateral movement risk, enforcement readiness |
| **Audit** | `report audit` | PCE events API | System health, user activity, and policy-change audit log |
| **VEN Status** | `report ven-status` | PCE workloads API | VEN inventory with online/offline/unmanaged classification |
| **Policy Usage** | `report policy-usage` | PCE rulesets + traffic queries or Workloader CSV | Per-rule traffic hit analysis; identify unused rules |

---

## Running a report

### Traffic report

```bash
python3 illumio-ops.py report traffic [OPTIONS]
```

| Flag | Values | Default | Notes |
|:---|:---|:---|:---|
| `--source` | `api` \| `csv` | `api` | Pull live data from PCE or read from a CSV file |
| `--file PATH` | path | — | Required when `--source csv` |
| `--format` | `html` \| `csv` \| `pdf` \| `xlsx` \| `all` | `html` | Output format(s); `pdf` produces print-ready HTML (see [Print layout](#print-layout--html-export)) |
| `--output-dir PATH` | path | `reports/` | Destination directory |
| `--email` | flag | off | Send report email after generation |
| `--profile` | `security_risk` \| `network_inventory` | `security_risk` | Report focus profile |

### Audit report

```bash
python3 illumio-ops.py report audit [OPTIONS]
```

| Flag | Values | Notes |
|:---|:---|:---|
| `--format` | `html` \| `csv` \| `pdf` \| `xlsx` \| `all` | Output format(s) |
| `--output-dir PATH` | path | Destination directory |

### VEN status report

```bash
python3 illumio-ops.py report ven-status [OPTIONS]
```

| Flag | Values | Notes |
|:---|:---|:---|
| `--format` | `html` \| `csv` \| `pdf` \| `xlsx` \| `all` | Output format(s) |
| `--output-dir PATH` | path | Destination directory |

### Policy usage report

```bash
python3 illumio-ops.py report policy-usage [OPTIONS]
```

| Flag | Values | Notes |
|:---|:---|:---|
| `--source` | `api` \| `csv` | Data source |
| `--file PATH` | path | Required when `--source csv` |
| `--format` | `html` \| `csv` \| `pdf` \| `xlsx` \| `all` | Output format(s) |
| `--output-dir PATH` | path | Destination directory |

### Command aliases

All four subcommands have `generate-*` aliases for backwards compatibility:

| Preferred | Alias |
|:---|:---|
| `report traffic` | `report generate-traffic` |
| `report audit` | `report generate-audit` |
| `report ven-status` | `report generate-ven-status` |
| `report policy-usage` | `report generate-policy-usage` |

> For the full flag matrix including date-range and PCE-profile flags, see [CLI Reference](../reference/cli.md).

---

## Report modules

The **traffic report** is built from 15 analytical modules plus a security findings pass.
The other report types each use a dedicated generator.

### Traffic report modules (src/report/analysis/)

- **mod01 — Traffic Overview**: Total flow counts, allowed/blocked/potentially-blocked breakdown, top ports
- **mod02 — Policy Decisions**: Per-decision breakdown with inbound/outbound split and per-port coverage %
- **mod03 — Uncovered Flows**: Flows without a matching allow rule; port gap ranking; uncovered services (app + port)
- **mod04 — Ransomware Exposure**: Destination hosts with ALLOWED traffic on critical/high-risk ports; per-port detail; host exposure ranking
- **mod05 — Remote Access**: SSH, RDP, VNC, and TeamViewer traffic analysis
- **mod06 — User & Process**: User accounts and process names appearing in flow records
- **mod07 — Cross-Label Matrix**: Traffic matrix between environment / app / role label combinations
- **mod08 — Unmanaged Hosts**: Traffic from/to non-PCE-managed hosts; per-app and per-port detail
- **mod09 — Traffic Distribution**: Port and protocol distribution charts
- **mod10 — Allowed Traffic**: Top allowed flows with audit flags
- **mod11 — Bandwidth & Volume**: Top flows by bytes; max/avg/P95 stat cards; anomaly detection on multi-connection flows
- **mod12 — Executive Summary**: KPI cards (total flows, policy coverage %, top findings); also used as the email body
- **mod13 — Enforcement Readiness**: Score 0–100 with factor breakdown and remediation recommendations
- **mod14 — Infrastructure Scoring**: Node centrality scoring to identify critical services (in-degree, out-degree, betweenness)
- **mod15 — Lateral Movement Risk**: Lateral movement pattern analysis and high-risk pivot paths

### Additional analysis modules (src/report/)

- **attack_posture**: Attack posture scoring aggregated across module results
- **mod_change_impact**: Delta analysis for change-impact reports
- **mod_draft_actions**: Recommended actions derived from draft policy decisions
- **mod_draft_summary**: Summary metrics for draft policy state
- **mod_ringfence**: Ring-fence boundary validation

### Parsers (src/report/parsers/)

- **api_parser**: Normalises PCE API traffic-query responses into the internal flow schema
- **csv_parser**: Parses CSV exports (from PCE or Workloader) into the same flow schema
- **validators**: Input validation for flow records before analysis

> Full report-engine internals: [Architecture › Report Engine](../architecture/report-engine.md) (B2 deliverable).

---

## Security rules — quick reference

Security findings run automatically on every traffic report. 24 rules are grouped into three series.

### Series overview

| Series | Rule IDs | Focus |
|:---|:---|:---|
| **B-series** (Baseline) | B001–B009 | Ransomware exposure, policy coverage gaps, behavioural anomalies |
| **L-series** (Lateral Movement) | L001–L010 | Attacker pivoting, credential theft, blast-radius paths, exfiltration |
| **R-series** (Draft Policy Decision) | R01–R05 | Conflicts between live policy state and draft (unprovisioned) rules |

### B-series — Baseline rules

| Rule ID | Name | Severity | Trigger condition |
|:---|:---|:---|:---|
| B001 | Ransomware Risk Port — Contextual Analysis | CRITICAL / HIGH / MEDIUM / INFO | Allowed traffic on critical ransomware ports (SMB 445, RDP 3389, RPC 135, WinRM 5985/5986); severity depends on cross-env / cross-subnet context |
| B002 | Ransomware Risk Port (High) | HIGH | Allowed traffic on high-tier ports (TeamViewer 5938, VNC 5900, NetBIOS 137–139) |
| B003 | Ransomware Risk Port (Medium) — Uncovered | MEDIUM | Uncovered flows on medium-tier ports (SSH 22, FTP 20/21, Telnet 23, NFS 2049, mDNS 5353, etc.) |
| B004 | Unmanaged Source High Activity | MEDIUM | Unmanaged source hosts exceeding flow-count threshold (default: 50 flows) |
| B005 | Low Policy Coverage | MEDIUM | Policy coverage % falls below threshold (default: 30%) |
| B006 | High Lateral Movement (Fan-Out) | HIGH | Single source contacts more than N unique destinations (default: 10) |
| B007 | Single User High Destinations | HIGH | Single user account reaches more than N unique destinations (default: 20) |
| B008 | High Bandwidth Anomaly | MEDIUM | Flow bytes exceed Nth percentile of observed traffic (default: P95) |
| B009 | Cross-Env Flow Volume | INFO | Cross-environment flow count exceeds threshold (default: 100) |

### L-series — Lateral movement rules

| Rule ID | Name | Key focus |
|:---|:---|:---|
| L001 | Cleartext Protocol in Use | Telnet, FTP, HTTP on internal flows |
| L002 | Network Discovery Protocol Exposure | Unblocked discovery protocol flows (mDNS, LLMNR, SSDP, WSD) |
| L003 | Database Port Wide Exposure | Database ports (MySQL, MSSQL, PostgreSQL, etc.) reachable from many sources |
| L004 | Cross-Environment Database Access | Database traffic crossing environment boundaries |
| L005 | Identity Infrastructure Wide Exposure | LDAP/Kerberos/AD ports broadly reachable |
| L006 | High Blast-Radius Lateral Movement Path | Source with many reachable destinations via lateral ports |
| L007 | Unmanaged Host Accessing Critical Services | Unmanaged hosts reaching identity/database/admin services |
| L008 | Lateral Ports in Test Mode (PB) | Lateral-risk ports in Potentially Blocked (test mode) state |
| L009 | Data Exfiltration Pattern (Outbound to Unmanaged) | Managed workloads sending high data volume to unmanaged external hosts |
| L010 | Cross-Environment Lateral Port Access | SSH/Telnet/RDP crossing environment labels |

### R-series — Draft Policy Decision rules

| Rule ID | Name | When active |
|:---|:---|:---|
| R01 | Draft Deny Detected | Active ruleset uses `draft_pd`; flow would be denied under draft rules |
| R02 | Override Deny Detected | Draft deny overriding a live allow rule |
| R03 | Visibility Boundary Breach | Draft rules would expose flows across a visibility boundary |
| R04 | Allowed Across Boundary | Draft allows crossing a configured boundary |
| R05 | Draft/Reported Mismatch | `draft_policy_decision` differs from `policy_decision` |

> Full rule details and tunable thresholds: [CLI Reference](../reference/cli.md) and `src/report/rules_engine.py`.

---

## Print layout & HTML export

**PDF generation via ReportLab was removed** (commit `9acedda`). The `--format pdf` flag and the
GUI "PDF" option now produce a **print-ready HTML file** styled with `@media print` CSS.

Key behaviour:

- Selecting `--format pdf` outputs an `.html` file with `@media print` rules optimised for A4 paper.
- A **Print** button in the report nav bar triggers `window.print()` for browser-native PDF save.
- Print CSS features: A4 cover page (hidden on screen), overflow-safe table layout, chart clip fixes,
  high-contrast badges, and footer suppressed in print (cover page carries title/date).
- Wide tables are split into grouped sub-tables at print width (commit `f935717`).
- The `mod13` readiness table switches to a condensed 5-column layout in print mode while preserving
  the full 10-column layout on screen (commit `93f5efc`).

Export formats summary:

| Format value | Output | Notes |
|:---|:---|:---|
| `html` | `report_<date>.html` | Interactive report with charts and navigation sidebar |
| `csv` | `report_<date>_raw.zip` | Raw flow data as CSV; suitable for SIEM ingestion |
| `xlsx` | `report_<date>.xlsx` | Excel workbook with per-module sheets |
| `pdf` | `report_<date>_print.html` | Print-ready HTML; open in browser and print-to-PDF |
| `all` | All of the above | Generates HTML + CSV together |

---

## Email delivery

The traffic report supports email delivery via the `--email` flag (CLI) or the **Email** toggle in the
web GUI scheduler.

When enabled:
1. The report HTML file is attached to the outgoing message.
2. A compact HTML summary email is constructed from the executive summary module (mod12) — key metrics,
   top findings, and the action matrix table.
3. The email is sent via `reporter.send_report_email()`, which reads SMTP settings from the operator
   configuration.

**Daemon / scheduled mode**: Reports generated by the scheduler can be configured to email automatically.
See the web GUI › Settings › Report Schedule, or the CLI **2. Report Generation → 5. Report Schedule
Management** menu.

> SMTP configuration and event forwarding: [SIEM Integration](siem-integration.md).

---

## Related Docs

- [Report engine internals](../architecture/report-engine.md) — how reports are built (B2 deliverable)
- [CLI Reference](../reference/cli.md) — `report` subcommands and flags
- [Alerts & Quarantine](alerts-and-quarantine.md) — when reports drive alerts
- [SIEM Integration](siem-integration.md) — forwarding report-related events
