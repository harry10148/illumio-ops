# Security Rules Reference

> **[English](Security_Rules_Reference.md)** | **[繁體中文](Security_Rules_Reference_zh.md)**

This document describes all built-in security detection rules included in Illumio PCE Ops's traffic report engine. Rules are evaluated automatically whenever a traffic report is generated and their results appear in the **Security Findings** section of every HTML report.

---

## Overview

Rules are split into three series:

| Series | Rules | Focus |
|:---|:---|:---|
| **B-series** (Baseline) | B001–B009 | Ransomware exposure, policy coverage gaps, behavioural anomalies |
| **L-series** (Lateral Movement) | L001–L010 | Attacker pivoting, credential theft, blast-radius paths, exfiltration |
| **R-series** (Draft Policy Decision) | R01–R05 | Conflicts between live policy state and draft (unprovisioned) rules |

All B-series and L-series thresholds are configurable in **`config/report_config.yaml`** under the `thresholds:` key. R-series rules require `draft_policy_decision` data and auto-enable `compute_draft` when present in the active ruleset (see [§ Configuration](#configuration)).

---

## Severity Levels

| Level | Meaning | Typical response |
|:---|:---|:---|
| **CRITICAL** | Confirmed or near-certain active attack path | Remediate within 24 hours |
| **HIGH** | Significant exposure enabling lateral movement or exfiltration | Remediate within 1 week |
| **MEDIUM** | Policy gap or elevated risk that should be addressed | Scheduled remediation |
| **LOW** | Informational risk, low probability of exploitation | Track and monitor |
| **INFO** | Environmental observation, no immediate action required | Review periodically |

---

## Policy Decision Fields

Understanding the two policy-decision fields is essential for correctly interpreting security rule findings.

### `policy_decision` — Historical snapshot

Recorded by the VEN at the time of each traffic flow. **Always exactly one of three values — no sub-types.**

| Value | Meaning |
|:---|:---|
| `allowed` | A matching allow rule exists and the flow is permitted. |
| `potentially_blocked` | **No allow or deny rule** covers this flow. The VEN is in visibility/test mode so traffic passes unrestricted. When the workload moves to enforced (whitelist) mode the default-deny will block it. |
| `blocked` | The flow is actively blocked — either by a deny rule in selective/full-enforcement mode, or by default-deny with no matching allow rule. |

> **Important:** `potentially_blocked` does **not** mean "a rule exists but isn't enforced." It means there is no matching rule at all. Rules engines that treat PB flows as already-regulated are wrong.

### `draft_policy_decision` — Dynamically recalculated

Returned by the async traffic query **after** a `PUT {job_href}/update_rules` call (available from Illumio Core 23.2.10+). The PCE re-evaluates **all** historical flow records against both active (provisioned) and draft rules, so `draft_policy_decision` is always current — even for flows recorded before a rule was created or provisioned.

| Value | VEN mode | Condition | Meaning |
|:---|:---|:---|:---|
| `allowed` | Any | Draft allow rule exists (unprovisioned) | Flow would be permitted if the draft allow rule were provisioned. |
| `potentially_blocked` | Any | No active or draft rule | Truly uncovered — no rule in any state. |
| `potentially_blocked_by_boundary` | Visibility | Draft regular deny (unprovisioned) | A deny rule exists in draft; VEN not enforcing yet, so block is potential. |
| `potentially_blocked_by_override_deny` | Visibility | Draft or active override deny | Override deny exists; VEN not enforcing yet, so block is potential. |
| `blocked_by_boundary` | Selective / Full | Regular deny exists (draft or active) | VEN will immediately block upon provisioning; or is already blocking new flows. |
| `blocked_by_override_deny` | Selective / Full | Override deny exists (draft or active) | Same as above but override deny — cannot be overridden by any allow rule. |
| `allowed_across_boundary` | Any | Active regular deny + allow rule wins | A deny rule exists but an allow rule takes precedence. Never appears with override deny. |

### Key behavioural rules

- **`policy_decision` is a frozen historical snapshot.** Old flows keep their original value even after rules change.
- **`draft_policy_decision` is always recalculated.** After calling `update_rules`, old flows get new values reflecting the current ruleset.
- **The `potentially_` prefix signals VEN enforcement mode.** Present = visibility/test mode (block is potential). Absent = selective/full enforcement (block is definitive).
- **`blocked_by_override_deny` vs `blocked_by_boundary`** — both indicate a deny rule will block, but override deny cannot be overridden by any allow rule.
- **Transition state after provisioning:** Immediately after a deny rule is provisioned in selective mode, data shows a mix — old flows with `pd=potentially_blocked` and new flows with `pd=blocked` — but all share the same `draft_pd=blocked_by_boundary` because `update_rules` re-evaluates everything with the current ruleset.

### Obtaining `draft_policy_decision`

```
1. POST /api/v2/orgs/{org}/traffic_flows/async_queries   → job_href
2. Poll GET job_href until status == "completed"
3. PUT  job_href/update_rules                             → 202
4. Poll GET job_href until rules.status == "completed"
5. GET  job_href/download                                 → JSON with draft_policy_decision column
```

---

## Ransomware Risk Port Tiers

The `report_config.yaml` defines four tiers of ransomware risk ports. These tiers are used by rules B001, B002, and B003.

| Tier | Ports | Used by |
|:---|:---|:---|
| **critical** | 135 (RPC), 445 (SMB), 3389 (RDP), 5985/5986 (WinRM) | B001 |
| **high** | 5938 (TeamViewer), 5900 (VNC), 137/138/139 (NetBIOS) | B002 |
| **medium** | 22 (SSH), 2049 (NFS), 20/21 (FTP), 5353 (mDNS), 5355 (LLMNR), 80 (HTTP), 3702 (WSD), 1900 (SSDP), 23 (Telnet) | B003 |
| **low** | 110 (POP3), 1723 (PPTP), 111 (SunRPC), 4444 (Metasploit) | Reserved for future rules |

---

## B-Series — Baseline Rules

### B001 · Ransomware Risk Port `CRITICAL / HIGH / MEDIUM / INFO`

**Category:** Ransomware

**What it checks:**
Scans for any non-blocked flow on the four most critical ransomware lateral-spread ports and applies **contextual severity** based on network proximity and traffic policy:

| Port | Protocol | Service |
|:---|:---|:---|
| 135 | TCP | Microsoft RPC (remote procedure calls) |
| 445 | TCP | SMB (Windows file sharing / EternalBlue vector) |
| 3389 | TCP/UDP | RDP (Remote Desktop Protocol) |
| 5985 / 5986 | TCP | WinRM (Windows Remote Management) |

**Why it matters:**
These are the exact ports used in EternalBlue, NotPetya, WannaCry, and the majority of modern ransomware campaigns for network-wide lateral spread. However, not all RDP/SMB flows are malicious — domain controllers, patch management servers, and jump hosts legitimately use these ports within the same subnet. Context is required to judge true risk.

**Contextual severity tiers:**

| Severity | Condition |
|:---|:---|
| **CRITICAL** | Any flow crosses **environment boundaries** (e.g., Dev->Prod, Test->Prod) |
| **HIGH** | Flow crosses a **/24 subnet boundary** and is explicitly `allowed` (not just test-mode) |
| **MEDIUM** | Flows are **within the same /24 subnet** *or* all are `potentially_blocked` (no allow rule; VEN in test mode) |
| **INFO** | All flows are same-subnet **AND** all are `potentially_blocked` — no allow rule written yet; flows only because VEN is in test mode |

**Trigger condition:**
At least one flow on ports {135, 445, 3389, 5985, 5986} with `policy_decision != 'blocked'`.

**Threshold key:** *(no threshold — triggers on any match; severity is contextual)*

**Recommended action:**
- **CRITICAL**: Immediately create environment-boundary deny rules — cross-env RPC/SMB/RDP is almost never legitimate
- **HIGH**: Investigate cross-subnet flows; confirm source is an authorised jump host or management system
- **MEDIUM**: Review test-mode workloads; consider moving to enforced mode; validate same-subnet admin access is intentional
- **INFO**: Likely benign same-subnet admin traffic — validate and document; consider closing to reduce noise

---

### B002 · Ransomware Risk Port (High) `HIGH`

**Category:** Ransomware

**What it checks:**
Detects allowed flows on secondary remote-access and persistence ports:

| Port | Protocol | Service |
|:---|:---|:---|
| 5938 | TCP/UDP | TeamViewer |
| 5900 | TCP/UDP | VNC (Virtual Network Computing) |
| 137 / 138 / 139 | UDP/TCP | NetBIOS Name Service / Datagram / Session |

**Why it matters:**
Ransomware operators and APT groups use TeamViewer, VNC, and NetBIOS extensively for persistent remote control and C2 communication after initial compromise.

**Trigger condition:**
At least one flow with `policy_decision = 'allowed'` on these ports.

**Threshold key:** *(no threshold — triggers on any match)*

**Recommended action:**
- Remove or tightly scope any allow rules for remote-access tools to known source IPs/ranges only
- Block NetBIOS globally unless required for legacy Windows environments
- Replace TeamViewer/VNC with a PAM (Privileged Access Management) solution

---

### B003 · Ransomware Risk Port (Medium) — Test Mode `MEDIUM`

**Category:** Ransomware

**What it checks:**
Detects medium-risk ports with `policy_decision = 'potentially_blocked'` — meaning **no allow rule covers this flow**. The VEN is in test/visibility mode so traffic passes through; once the workload moves to enforced mode, the default-deny whitelist will block it.

Monitored ports include: SSH (22), NFS (2049), FTP (20/21), mDNS (5353), LLMNR (5355), HTTP (80), WSD (3702), SSDP (1900), Telnet (23).

**Why it matters:**
`potentially_blocked` means there is **no allow or deny rule** for this flow — it is entirely uncovered by policy. The VEN is in test/visibility mode so traffic flows through unrestricted. This is a common cause of "we had micro-segmentation but still got breached" — workloads were never moved to enforced mode, so the default-deny whitelist never activated.

**Trigger condition:**
At least one flow with `policy_decision = 'potentially_blocked'` on medium-risk ports.

**Threshold key:** *(no threshold — triggers on any match)*

**Recommended action:**
- Move workloads from visibility/test mode to selective or full enforcement
- Prioritise workloads that handle medium-risk ports (SSH, FTP, HTTP)

---

### B004 · Unmanaged Source High Activity `MEDIUM`

**Category:** UnmanagedHost

**What it checks:**
Counts the total number of flows originating from hosts with `src_managed = False` (not enrolled in the PCE).

**Why it matters:**
Unmanaged hosts have no VEN agent and therefore no micro-segmentation enforcement. They sit outside the zero-trust boundary and represent an uncontrolled attack surface — whether they are shadow IT, contractor machines, or attacker-controlled hosts.

**Trigger condition:**
Total unmanaged-source flows exceed `unmanaged_connection_threshold` (default: **50**).

**Threshold key:** `unmanaged_connection_threshold`

**Recommended action:**
- Investigate and identify each unmanaged source IP
- Onboard legitimate hosts to the PCE or apply explicit deny rules
- Block unmanaged sources from accessing any sensitive port

---

### B005 · Low Policy Coverage `MEDIUM`

**Category:** Policy

**What it checks:**
Calculates `allowed_flows / total_flows x 100` as the policy coverage percentage. Triggers if this falls below the threshold.

**Why it matters:**
Low coverage means the majority of observed traffic is either uncontrolled (no explicit rule) or blocked by default. In either case, the segmentation policy is incomplete and large sections of the network have no micro-segmentation protection.

**Trigger condition:**
`coverage_pct < min_policy_coverage_pct` (default: **30%**).

**Threshold key:** `min_policy_coverage_pct`

**Recommended action:**
- Use the **Uncovered Flows** report section to identify the highest-volume uncovered paths
- Prioritise rule creation for production application tiers first
- Use Illumio's Rule Writing Wizard to generate rules from observed traffic

---

### B006 · High Lateral Movement (Fan-Out) `HIGH`

**Category:** LateralMovement

**What it checks:**
Groups flows on lateral movement ports (RDP 3389, VNC 5900, SSH 22, SMB 445, WinRM 5985/5986, TeamViewer 5938, Telnet 23) by source IP, and counts how many distinct destination IPs each source contacted.

**Why it matters:**
A single source contacting many destinations on lateral movement ports is the textbook indicator of worm propagation, network scanning, or an attacker systematically pivoting through the environment. This is the pattern exhibited by tools like Mimikatz + PsExec, BloodHound-guided movement, and ransomware self-propagation.

**Trigger condition:**
At least one source IP contacts more than `lateral_movement_outbound_dst` distinct destinations (default: **10**) on lateral ports.

**Threshold key:** `lateral_movement_outbound_dst`

**Recommended action:**
- Immediately isolate the offending source IPs for investigation
- Apply emergency quarantine labels via the PCE Quarantine feature
- Review all allowed rules that permit these source IPs to communicate on lateral ports

---

### B007 · Single User High Destinations `HIGH`

**Category:** UserActivity

**What it checks:**
For flows that include a `user_name` field, counts how many distinct destination IPs each user reached. Triggers if any user exceeds the threshold.

**Why it matters:**
A single user account reaching an unusually high number of unique destinations is a red flag for: compromised credentials used in automated scanning, a user performing unsanctioned data staging, or a service account that has been hijacked.

**Trigger condition:**
Any single user contacts more than `user_destination_threshold` distinct destination IPs (default: **20**).

**Threshold key:** `user_destination_threshold`

**Recommended action:**
- Review the flagged user accounts in the PCE event log
- Check whether the accounts have been used from unusual locations or at unusual times
- Reset credentials and apply MFA if compromise is suspected

---

### B008 · High Bandwidth Anomaly `MEDIUM`

**Category:** Bandwidth

**What it checks:**
Computes the `high_bytes_percentile`-th percentile of byte volume across all flows. Flags any flow that exceeds this threshold.

**Why it matters:**
Sudden high-volume transfers from unexpected sources are a key indicator of data staging (attacker collecting data before exfiltration), large unauthorised backups, or misconfigured applications generating excessive traffic.

**Trigger condition:**
Any flow's `bytes_total` exceeds the `high_bytes_percentile`-th percentile of the dataset (default: **95th percentile**).

**Threshold key:** `high_bytes_percentile`

**Recommended action:**
- Investigate the flagged source-destination pairs — are they legitimate?
- Check if the transfer aligns with scheduled backup windows
- Apply egress bandwidth controls or explicit deny rules for unexpected large-volume sources

---

### B009 · Cross-Environment Flow Volume `INFO`

**Category:** Policy

**What it checks:**
Counts flows where `src_env != dst_env` (e.g., Production -> Development, Staging -> Production), excluding flows with empty environment labels.

**Why it matters:**
Environment boundaries are your macro-segmentation layer. Excessive cross-environment traffic may indicate lateral movement from a compromised lower-security zone into production, or misconfigured applications bypassing environment isolation.

**Trigger condition:**
Cross-environment flow count exceeds `cross_env_connection_threshold` (default: **100**).

**Threshold key:** `cross_env_connection_threshold`

**Recommended action:**
- Review which application pairs are generating cross-env traffic
- Validate that all cross-env flows are intentional and documented
- Apply environment-boundary deny rules for any unexpected cross-env patterns

---

## L-Series — Lateral Movement Rules

These rules focus specifically on the **attacker kill-chain after initial compromise**: how an attacker moves laterally, escalates privileges, exfiltrates data, and evades detection. Methodology is based on analysis of real-world attack patterns and the Illumio MCP server security analysis framework.

---

### L001 · Cleartext Protocol in Use `HIGH / MEDIUM`

**Category:** LateralMovement

**What it checks:**
Detects any traffic on cleartext / legacy protocols:

| Port | Service | Risk |
|:---|:---|:---|
| 23 | Telnet | Credentials sent in plaintext |
| 20 / 21 | FTP | Credentials and data sent in plaintext |

**Why it matters:**
Any attacker with network access can perform ARP poisoning or a MITM attack and capture credentials directly from Telnet/FTP sessions without breaking any encryption. These captured credentials are then immediately usable for lateral movement to any system where the same password is reused.

**Trigger condition:**
At least one flow on ports {23, 20, 21} exists. Severity is **HIGH** if any such flows are explicitly `allowed`; **MEDIUM** if all are blocked or potentially_blocked.

**Threshold key:** *(no threshold — triggers on any match)*

**Recommended action:**
- Decommission all Telnet and FTP services immediately
- Replace with SSH (port 22) and SFTP
- Apply deny rules in Illumio for ports 20, 21, and 23 across all environments

---

### L002 · Network Discovery Protocol Exposure `MEDIUM`

**Category:** LateralMovement

**What it checks:**
Detects unblocked flows on broadcast/discovery protocols:

| Port | Protocol | Service |
|:---|:---|:---|
| 137 / 138 | UDP | NetBIOS Name Service / Datagram |
| 5353 | UDP | mDNS (Multicast DNS) |
| 5355 | UDP | LLMNR (Link-Local Multicast Name Resolution) |
| 1900 | UDP | SSDP (UPnP) |
| 3702 | UDP | WSD (Web Services Discovery) |

**Why it matters:**
Tools like **Responder** and **Inveigh** exploit LLMNR and NetBIOS poisoning to intercept name resolution requests and respond with attacker-controlled IPs. The victim's machine then sends NTLM authentication to the attacker, who captures the NTLMv2 hash — all without any user interaction. These hashes can be cracked offline or relayed directly to other systems.

**Trigger condition:**
More than `discovery_protocol_threshold` unblocked flows on these ports (default: **10**).

**Threshold key:** `discovery_protocol_threshold`

**Recommended action:**
- Block NetBIOS (137/138), LLMNR (5355), and SSDP (1900) at the Illumio policy level
- These protocols serve no legitimate purpose in modern micro-segmented environments
- Enable SMB signing on all Windows workloads to prevent hash relay attacks

---

### L003 · Database Port Wide Exposure `HIGH`

**Category:** LateralMovement

**What it checks:**
Checks whether database ports are reachable with `policy_decision = 'allowed'` from more than `db_unique_src_app_threshold` distinct source application labels:

| Port | Service |
|:---|:---|
| 1433 | Microsoft SQL Server |
| 3306 | MySQL / MariaDB |
| 5432 | PostgreSQL |
| 1521 | Oracle Database |
| 27017 | MongoDB |
| 6379 | Redis |
| 9200 | Elasticsearch |
| 5984 | CouchDB |
| 50000 | IBM DB2 |

**Why it matters:**
Databases should only be reachable from their direct application tier — typically 1-2 application labels. Wide exposure means an attacker who achieves lateral movement to any of those many source apps can directly query production databases, exfiltrate data via SQL queries, or escalate via stored procedures and xp_cmdshell.

**Trigger condition:**
Database ports reachable from more than `db_unique_src_app_threshold` unique source app labels (default: **5**).

**Threshold key:** `db_unique_src_app_threshold`

**Recommended action:**
- Create Illumio rule-sets that explicitly list which application labels may reach each database
- All other sources should have a default deny for database ports
- Review the top-listed source apps in evidence — remove any that don't have a business justification

---

### L004 · Cross-Environment Database Access `HIGH`

**Category:** LateralMovement

**What it checks:**
Detects `allowed` database flows (same port list as L003: 1433, 3306, 5432, 1521, 27017, 6379, 9200, 5984, 50000) where `src_env != dst_env`.

**Why it matters:**
Environment boundaries are the macro-segmentation layer protecting Production from Development and Staging. A Dev application reaching a Production database directly bypasses all environment-level controls and is a direct path for an attacker who has compromised a lower-security environment to pivot into production data stores.

**Trigger condition:**
At least one allowed database flow crossing environment boundaries.

**Threshold key:** *(no threshold — any cross-env DB flow triggers)*

**Recommended action:**
- No application in Development or Staging should directly access Production databases
- Use read replicas, API gateways, or data pipelines as the cross-environment interface
- Apply Illumio deny rules at environment boundaries for all database ports

---

### L005 · Identity Infrastructure Wide Exposure `HIGH`

**Category:** LateralMovement

**What it checks:**
Detects non-blocked flows on identity infrastructure ports from more than `identity_unique_src_threshold` distinct source applications:

| Port | Service |
|:---|:---|
| 88 | Kerberos (authentication) |
| 389 | LDAP |
| 636 | LDAPS (LDAP over TLS) |
| 3268 / 3269 | Active Directory Global Catalog |
| 464 | Kerberos Password Change |

**Why it matters:**
Active Directory is the master authentication authority for the entire Windows domain. Excessive access to these ports enables:
- **BloodHound** — domain enumeration to find attack paths to Domain Admin
- **Kerberoasting** — requesting service tickets for offline password cracking
- **AS-REP Roasting** — attacking accounts without Kerberos pre-auth
- **Golden Ticket / Silver Ticket** — forging Kerberos tickets for persistent domain access

**Trigger condition:**
More than `identity_unique_src_threshold` unique source apps have non-blocked flows on identity ports (default: **3**).

**Threshold key:** `identity_unique_src_threshold`

**Recommended action:**
- Restrict Kerberos and LDAP to domain-joined workloads only
- Applications should use service accounts that wrap LDAP calls — never expose raw LDAP to application tiers broadly
- Block LDAP from all non-production environments to AD

---

### L006 · High Blast-Radius Lateral Path `HIGH`

**Category:** LateralMovement

**What it checks:**
Builds a directed app→app communication graph using only `allowed` flows on lateral movement ports. Runs BFS (Breadth-First Search) from every application node to compute how many other applications each node can reach through a chain of lateral-port connections.

**Why it matters:**
This is a direct implementation of the **detect-lateral-movement-paths** methodology from the Illumio MCP server. An application with high BFS reachability is the highest-value target for an attacker: compromising it grants potential access to every application in its reachable subgraph. These are the nodes where a single breach has the largest blast radius.

**Trigger condition:**
At least one application node can reach >= `blast_radius_threshold` other apps via lateral ports (default: **5**).

**Threshold key:** `blast_radius_threshold`

**Recommended action:**
- Review the top pivot apps listed in evidence and determine whether those lateral-port connections are necessary
- Apply Illumio intra-scope rules to limit which apps can use lateral ports
- Target the highest-reachability apps for isolation first — they represent the largest risk reduction per rule added

---

### L007 · Unmanaged Host Accessing Critical Services `HIGH`

**Category:** LateralMovement

**What it checks:**
Detects non-blocked flows from unmanaged hosts (`src_managed = False`) on critical service ports:
- Database ports (L003 list: 1433, 3306, 5432, 1521, 27017, 6379, 9200, 5984, 50000)
- Identity ports (L005 list: 88, 389, 636, 3268, 3269, 464)
- Windows management ports: RPC (135), SMB (445), WinRM (5985/5986/47001)

**Why it matters:**
Unmanaged hosts have no VEN enforcement — they exist outside the zero-trust boundary. An unmanaged host reaching a database, Active Directory, or Windows management port may be: shadow IT running unsanctioned software, an attacker-controlled host that was never enrolled, or a contractor machine that bypasses your segmentation policy entirely.

**Trigger condition:**
More than `unmanaged_critical_threshold` non-blocked flows from unmanaged sources on critical ports (default: **5**).

**Threshold key:** `unmanaged_critical_threshold`

**Recommended action:**
- Identify each unmanaged source IP — is it a known asset?
- Onboard legitimate hosts to the PCE immediately
- Apply explicit deny rules for unmanaged-to-critical-service traffic
- For unknown IPs, treat as potentially compromised and investigate

---

### L008 · Lateral Ports in Test Mode (PB) `HIGH`

**Category:** LateralMovement

**What it checks:**
Identifies flows with `policy_decision = 'potentially_blocked'` on lateral movement ports, database ports, identity ports, and Windows management ports.

**Why it matters:**
`potentially_blocked` is the most critical policy gap in an Illumio deployment: **no allow rule covers these flows**, and the VEN is in test/visibility mode so traffic passes through unrestricted. Switching to enforced mode activates the default-deny whitelist — these flows would be blocked automatically. Until enforcement is active, these are live and unprotected attack paths.

**Trigger condition:**
More than `pb_lateral_threshold` potentially-blocked flows on critical ports (default: **10**).

**Threshold key:** `pb_lateral_threshold`

**Recommended action:**
- Review each `potentially_blocked` lateral-port flow — these have **no allow rule**; identify which are legitimate before enforcing
- Create allow rules for any legitimate lateral-port paths (e.g., jump host SSH, management VLAN)
- Move workloads from visibility/test mode to **selective** or **full** enforcement — default-deny will then block all uncovered flows automatically
- Review the destination apps listed in evidence — prioritise production workloads

---

### L009 · Data Exfiltration Pattern `HIGH`

**Category:** LateralMovement

**What it checks:**
Detects managed workloads (`src_managed = True`) with `policy_decision = 'allowed'` transferring significant byte volume to unmanaged (`dst_managed = False`) destination IPs.

**Why it matters:**
This is the **post-lateral-movement exfiltration phase**: the attacker has already pivoted to a high-value workload and is now staging or transferring data to an external Command & Control (C2) server or drop site. The pattern — managed-to-unmanaged, high bytes, allowed — is a strong signal because legitimate outbound traffic to external services should be explicitly allowed and scoped, not just passing through to arbitrary unmanaged IPs.

**Trigger condition:**
Total bytes transferred from managed to unmanaged destinations exceeds `exfil_bytes_threshold_mb` MB (default: **100 MB**).

**Threshold key:** `exfil_bytes_threshold_mb`

**Recommended action:**
- Investigate the top destination IPs in evidence — are they known CDN/API endpoints or unknown IPs?
- Implement outbound allowlist rules scoping internet-bound traffic to known IP ranges
- Apply egress controls: all traffic from production workloads to unmanaged IPs should require explicit justification

---

### L010 · Cross-Environment Lateral Port Access `CRITICAL`

**Category:** LateralMovement

**What it checks:**
Detects `allowed` flows on lateral movement ports and Windows management ports between workloads in **different environments** (`src_env != dst_env`).

Monitored ports: SSH (22), Telnet (23), RPC (135), SMB (445), RDP (3389), VNC (5900), WinRM (5985/5986), TeamViewer (5938), WinRM alternate (47001).

**Why it matters:**
This is rated **CRITICAL** because it represents a complete macro-segmentation failure. Environment boundaries (Production / Development / Staging / DMZ) are your top-level security domains. If lateral movement ports are allowed to cross these boundaries, an attacker who compromises a low-security Development workload can directly apply the exact same lateral movement techniques — PsExec, WMI, RDP — to reach Production systems. The entire purpose of environment segmentation is defeated.

**Trigger condition:**
More than `cross_env_lateral_threshold` allowed flows using lateral/management ports across environment boundaries (default: **5**).

**Threshold key:** `cross_env_lateral_threshold`

**Recommended action:**
- **Immediately** create Illumio deny rules blocking lateral ports at environment boundaries
- This is a P1 remediation — do not wait for a maintenance window
- Review each environment pair in the evidence and determine whether any cross-env management access is intentional (e.g., jump host infrastructure)
- If intentional, scope the allow rule to the specific authorised source IP only

---

## R-Series — Draft Policy Decision Rules

These rules evaluate the relationship between the **live** (provisioned) policy state and the **draft** (unprovisioned) policy state. They require the `draft_policy_decision` column in the traffic dataset, which is populated only when the async traffic query is submitted with `compute_draft=True` (see [§ Configuration — compute_draft auto-enable](#compute_draft-auto-enable)).

R-series rules are executed by the same rules engine as B-series and L-series rules. All findings appear in the **Security Findings** section of the HTML report under the category `DraftPolicy`.

> **PCE version requirement:** `draft_policy_decision` is available from **Illumio Core 23.2.10+**. On older PCEs the column is absent and all R-series rules return zero findings (no error is raised).

---

### R01 · Draft Deny Detected `HIGH`

Flows that are currently **allowed** by live policy but would be **blocked** once the draft rules are provisioned.

**Trigger condition:** One or more flows where `policy_decision == "allowed"` AND `draft_policy_decision` is either `"blocked_by_boundary"` or `"blocked_by_override_deny"`. The rule fires as a single aggregated finding covering all matched flows.

**Requires draft PD:** Yes

**Severity:** HIGH

**Finding row schema:**
- `rule_id`: `R01`
- `rule_name`: localised via i18n key `rule_r01_name`
- `severity`: `HIGH`
- `category`: `DraftPolicy`
- `description`: localised via i18n key `rule_r01_desc`
- `recommendation`: "Review and provision the draft deny rules, or add explicit allow rules before provisioning to avoid unexpected traffic disruption."
- `evidence_matching_flows`: integer — number of flows matched
- `evidence_draft_decisions`: string — `value_counts()` dict of `draft_policy_decision` values seen

**Sample finding:**

```
rule_id: R01
severity: HIGH
evidence_matching_flows: 47
evidence_draft_decisions: "{'blocked_by_boundary': 40, 'blocked_by_override_deny': 7}"
```

**Recommended remediation:** Before provisioning any new deny rules, use `docs/User_Manual.md §9.11` (Draft Policy Decision behaviour) to run a pre-provisioning impact assessment. Add explicit allow rules for any legitimate flows that appear in this finding, then re-query to verify they are no longer matched.

---

### R02 · Override Deny Detected `HIGH`

Flows with a **draft override deny** rule. Override deny rules take absolute precedence — they cannot be overridden by any allow rule, regardless of rule order or scope.

**Trigger condition:** One or more flows where `draft_policy_decision` ends with `"_override_deny"` (i.e., either `"blocked_by_override_deny"` or `"potentially_blocked_by_override_deny"`). Fires as a single aggregated finding.

**Requires draft PD:** Yes

**Severity:** HIGH

**Finding row schema:**
- `rule_id`: `R02`
- `rule_name`: localised via i18n key `rule_r02_name`
- `severity`: `HIGH`
- `category`: `DraftPolicy`
- `description`: localised via i18n key `rule_r02_desc`
- `recommendation`: "Override deny rules take precedence over all allow rules. Verify each override deny is intentional before provisioning."
- `evidence_matching_flows`: integer — number of flows matched
- `evidence_draft_decisions`: string — `value_counts()` dict of `draft_policy_decision` values seen

**Sample finding:**

```
rule_id: R02
severity: HIGH
evidence_matching_flows: 3
evidence_draft_decisions: "{'blocked_by_override_deny': 3}"
```

**Recommended remediation:** Locate each draft override deny ruleset in the PCE console. Confirm each is intentional and correctly scoped. Override deny rules should be rare and tightly targeted — they are operationally irreversible once provisioned (no allow rule can restore the flow). See `docs/User_Manual.md §9.10` for override deny rule management.

---

### R03 · Visibility Boundary Breach `MEDIUM`

Flows where the VEN is in **visibility/test mode** (so traffic passes unrestricted today) but a **draft deny boundary** rule exists for this flow. Once the workloads move to enforced mode the boundary deny will activate and block this traffic.

**Trigger condition:** One or more flows where `policy_decision == "potentially_blocked"` AND `draft_policy_decision == "potentially_blocked_by_boundary"`. The `potentially_` prefix on both values confirms the VEN is not yet enforcing.

**Requires draft PD:** Yes

**Severity:** MEDIUM

**Finding row schema:**
- `rule_id`: `R03`
- `rule_name`: localised via i18n key `rule_r03_name`
- `severity`: `MEDIUM`
- `category`: `DraftPolicy`
- `description`: localised via i18n key `rule_r03_desc`
- `recommendation`: "Move workloads to enforced mode to activate the boundary deny. Flows are currently traversable only because VENs are in test/visibility mode."
- `evidence_matching_flows`: integer — number of flows matched

**Sample finding:**

```
rule_id: R03
severity: MEDIUM
evidence_matching_flows: 12
```

**Recommended remediation:** This is a pre-enforcement gap. Before switching workloads to enforced mode, verify that all legitimate traffic on these paths has an explicit allow rule. See `docs/User_Manual.md §9.11` for the recommended enforcement readiness checklist.

---

### R04 · Allowed Across Boundary `LOW`

Flows where an **allow rule explicitly overrides a draft regular deny boundary**. The draft deny exists but an allow rule takes precedence — the flow is permitted across the boundary.

**Trigger condition:** One or more flows where `draft_policy_decision == "allowed_across_boundary"`. Note that this value never appears when an override deny is present — it is specific to regular (non-override) deny boundaries.

**Requires draft PD:** Yes

**Severity:** LOW

**Finding row schema:**
- `rule_id`: `R04`
- `rule_name`: localised via i18n key `rule_r04_name`
- `severity`: `LOW`
- `category`: `DraftPolicy`
- `description`: localised via i18n key `rule_r04_desc`
- `recommendation`: "Confirm that cross-boundary allow rules are intentional and tightly scoped. Consider whether a more restrictive rule can meet the business requirement."
- `evidence_matching_flows`: integer — number of flows matched

**Sample finding:**

```
rule_id: R04
severity: LOW
evidence_matching_flows: 8
```

**Recommended remediation:** Review each cross-boundary allow rule in the PCE console. Verify the source and destination scopes are as narrow as possible. If the business requirement no longer applies, remove the allow rule. LOW severity indicates this is intentional by design but warrants periodic review.

---

### R05 · Draft-Reported Mismatch `INFO`

An aggregated list of workload pairs where the **reported decision** (`policy_decision`) is `"allowed"` but the **draft decision** (`draft_policy_decision`) indicates a block. This is a superset view — it captures all allowed-but-draft-blocked pairs regardless of which specific block type applies, complementing the focused findings of R01.

**Trigger condition:** One or more flows where `policy_decision == "allowed"` AND `draft_policy_decision` starts with `"blocked_"`. The top 20 source-destination pairs are captured in evidence (using `src`/`src_ip` and `dst`/`dst_ip` columns as available).

**Requires draft PD:** Yes

**Severity:** INFO

**Finding row schema:**
- `rule_id`: `R05`
- `rule_name`: localised via i18n key `rule_r05_name`
- `severity`: `INFO`
- `category`: `DraftPolicy`
- `description`: localised via i18n key `rule_r05_desc`
- `recommendation`: "Review these workload pairs before provisioning draft rules. Currently-allowed traffic will be blocked once the draft is provisioned."
- `evidence_mismatch_count`: integer — total number of mismatched flows
- `evidence_top_pairs`: string — JSON-serialised list of up to 20 `{src, dst}` dicts

**Sample finding:**

```
rule_id: R05
severity: INFO
evidence_mismatch_count: 23
evidence_top_pairs: "[{'src': '10.0.1.5', 'dst': '10.0.2.8'}, ...]"
```

**Recommended remediation:** Use this as a pre-provisioning checklist. Cross-reference each pair with your approved change request before provisioning draft rules. INFO severity means no immediate action is required but the list should be reviewed and acknowledged. See `docs/User_Manual.md §9.11`.

---

## Analysis Modules (Non-Rule)

In addition to the B-series and L-series security rules, the traffic report includes three analysis modules that provide scoring and risk assessment. These modules do **not** generate `Finding` objects in the rules engine but appear as dedicated sections in the HTML report.

### Module 13 · Enforcement Readiness Score

Computes a 0-100 enforcement readiness score across five weighted factors:

| Factor | Weight | Description |
|:---|:---|:---|
| Policy Coverage | 35 | Percentage of flows with `policy_decision = 'allowed'` |
| Ringfence Maturity | 20 | Percentage of app-to-app flows where src and dst share the same app label |
| Enforcement Mode | 20 | Percentage of managed workloads in `enforced` mode |
| Staged Readiness | 15 | Penalises `potentially_blocked` flows — uncovered traffic with no allow rule; blocked by default-deny once workload moves to enforced mode |
| Remote App Coverage | 10 | Percentage of remote-access-port flows (SSH, RDP, VNC, TeamViewer) that are `allowed` |

Outputs a letter grade (A-F) and prioritised remediation recommendations.

### Module 14 · Infrastructure Scoring

Graph-based application criticality scoring using directed app-to-app communication analysis:

- **In-degree**: number of unique apps that depend on this app (provider criticality)
- **Out-degree**: number of unique apps this app communicates with (consumer blast radius)
- **Infra Score**: weighted combination (60% provider, 40% consumer)
- **Role classification**: Hub (high in+out), Provider, Consumer, Peer

Identifies the highest-value targets for segmentation prioritisation.

### Module 15 · Lateral Movement Risk Detection

Dedicated lateral movement analysis module providing:

- **Lateral port exposure summary**: flows on known lateral movement ports by service and policy decision
- **Fan-out detection**: sources communicating to many destinations on lateral ports (threshold: 5+ unique destinations)
- **App-level chain detection**: BFS reachability analysis up to 3 hops on allowed lateral-port connections
- **Articulation proxy detection**: IP nodes with both high in-degree and out-degree on lateral ports (chokepoints)
- **Per-source risk scoring**: 0-100 risk score per source IP based on connection volume, destination spread, port diversity, and blocked flow ratio

Lateral ports monitored by this module: SMB (445), RPC (135), NetBIOS (139), RDP (3389), SSH (22), WinRM (5985/5986), Telnet (23), NFS (2049), RPC Portmapper (111), LDAP (389), LDAPS (636), Kerberos (88), MSSQL (1433), MySQL (3306), PostgreSQL (5432).

---

## Threshold Configuration Reference

All thresholds are in `config/report_config.yaml` under the `thresholds:` key.

```yaml
thresholds:
  # -- B-series ----------------------------------------------------------
  min_policy_coverage_pct: 30         # B005: trigger if coverage % below this
  lateral_movement_outbound_dst: 10   # B006: trigger if src contacts > N unique dst
  user_destination_threshold: 20      # B007: trigger if user reaches > N unique dst
  unmanaged_connection_threshold: 50  # B004: trigger if unmanaged src flows > N
  high_bytes_percentile: 95           # B008: anomaly if bytes > Nth percentile
  high_bandwidth_percentile: 95       # bandwidth spike percentile (Module 11)
  cross_env_connection_threshold: 100 # B009: trigger if cross-env flows > N

  # -- L-series ----------------------------------------------------------
  discovery_protocol_threshold: 10    # L002: min unblocked discovery flows to trigger
  db_unique_src_app_threshold: 5      # L003: alert if db reachable from > N source apps
  identity_unique_src_threshold: 3    # L005: alert if LDAP/Kerberos from > N source apps
  blast_radius_threshold: 5           # L006: alert if app reaches > N apps via lateral ports
  unmanaged_critical_threshold: 5     # L007: min unmanaged-to-critical-port flows
  pb_lateral_threshold: 10            # L008: min PB flows on lateral ports to alert
  exfil_bytes_threshold_mb: 100       # L009: trigger if managed->unmanaged bytes > N MB
  cross_env_lateral_threshold: 5      # L010: min cross-env lateral flows to alert
```

### Tuning guidance

- **High false-positive environment** (e.g., flat Dev network with many cross-app flows): Increase L003 `db_unique_src_app_threshold` to 10-15 and L005 `identity_unique_src_threshold` to 8-10.
- **Mature segmentation environment** (most workloads enforced): Lower B005 `min_policy_coverage_pct` to 80 to alert only when mature environments regress.
- **Large data-transfer workloads** (backup servers, ETL): Increase `high_bytes_percentile` to 99 or increase `exfil_bytes_threshold_mb` to 500-1000.
- **Strict zero-tolerance environment**: Set `cross_env_lateral_threshold` to 1 so any cross-env lateral port flow triggers immediately.

---

## Port Reference

All port numbers referenced by the security rules and analysis modules:

| Port(s) | Service | Rules / Modules that reference it |
|:---|:---|:---|
| 20, 21 | FTP | B003, L001 |
| 22 | SSH | B003, B006, L010, Mod15 |
| 23 | Telnet | B003, B006, L001, L010, Mod15 |
| 80 | HTTP | B003 |
| 88 | Kerberos | L005, L007, L008, Mod15 |
| 110 | POP3 | config: low tier |
| 111 | SunRPC | config: low tier, Mod15 |
| 135 | RPC / DCOM | B001, L007, L008, L010, Mod15 |
| 137, 138 | NetBIOS NS/DGM | B002, L002 |
| 139 | NetBIOS Session | B002, Mod15 |
| 389 | LDAP | L005, L007, L008, Mod15 |
| 445 | SMB | B001, B006, L007, L008, L010, Mod15 |
| 464 | Kerberos Password | L005, L007, L008 |
| 636 | LDAPS | L005, L007, L008, Mod15 |
| 1433 | MSSQL | L003, L004, L007, L008, Mod15 |
| 1521 | Oracle | L003, L004, L007, L008 |
| 1723 | PPTP | config: low tier |
| 1900 | SSDP | B003, L002 |
| 2049 | NFS | B003, Mod15 |
| 3268, 3269 | AD Global Catalog | L005, L007, L008 |
| 3306 | MySQL | L003, L004, L007, L008, Mod15 |
| 3389 | RDP | B001, B006, L010, Mod15 |
| 3702 | WSD | B003, L002 |
| 4444 | Metasploit | config: low tier |
| 5353 | mDNS | B003, L002 |
| 5355 | LLMNR | B003, L002 |
| 5432 | PostgreSQL | L003, L004, L007, L008, Mod15 |
| 5900 | VNC | B002, B006, L010 |
| 5938 | TeamViewer | B002, B006, L010 |
| 5984 | CouchDB | L003, L004, L007, L008 |
| 5985, 5986 | WinRM | B001, B006, L007, L008, L010 |
| 6379 | Redis | L003, L004, L007, L008 |
| 9200 | Elasticsearch | L003, L004, L007, L008 |
| 27017 | MongoDB | L003, L004, L007, L008 |
| 47001 | WinRM alternate | L007, L008, L010 |
| 50000 | IBM DB2 | L003, L004, L007, L008 |

---

## Configuration

### compute_draft auto-enable {#compute_draft-auto-enable}

The `draft_policy_decision` column in a traffic flow dataset is expensive to populate: it requires the analyzer to issue a `PUT {job_href}/update_rules` call after the async query completes, which re-evaluates all historical flow records against both active and draft rules (see [§ Obtaining `draft_policy_decision`](#obtaining-draft_policy_decision)).

By default, `compute_draft` is **off** — the analyzer does not request draft policy data unless the operator explicitly opts in. However, when the active ruleset contains **any rule** whose `needs_draft_pd()` method returns `True` (all R01–R05 rules qualify), the analyzer automatically forces `compute_draft=True`, even if the operator did not pass the flag.

**Automatic escalation logic (from `src/analyzer.py`):**

```python
needs_draft = (
    bool(draft_pd_filter)                              # operator passed a draft PD filter
    or getattr(query_spec, "requires_draft_pd", False) # ruleset annotation
    or bool(params.get("requires_draft_pd", False))    # explicit query param
)
```

The function `ruleset_needs_draft_pd()` in `src/report/rules_engine.py` iterates the active ruleset and calls `needs_draft_pd()` on each rule instance. If any returns `True`, the result propagates to the analyzer.

**Practical effect:**

| Ruleset contains R-series rules? | `compute_draft` parameter | Actual behaviour |
|:---|:---|:---|
| No | False (default) | Draft data not requested; R-series rules return 0 findings |
| No | True (operator opt-in) | Draft data requested; R-series rules evaluate normally |
| Yes | False (default) | **Auto-escalated to True** — draft data requested automatically |
| Yes | True | Draft data requested (no change) |

**When `compute_draft` is forced on, a log entry is emitted** at INFO level using i18n key `rs_engine_needs_draft_pd` ("Rule requires draft_policy_decision; compute_draft forced on."). Operators can observe this in the application log to confirm the escalation occurred.

**Test coverage:** `tests/test_phase34_attack_summaries.py` — the `test_policy_usage_html_renders_draft_pd_section` test verifies that the Draft Policy section renders in the HTML report when `mod05` draft conflict data is present.

**Cross-references:**
- `docs/User_Manual.md §9.11` — Draft Policy Decision behaviour (end-user operator guide)
- `docs/Architecture.md §1.4` — Policy lifecycle: provisioned vs. draft state (added in Phase C)
