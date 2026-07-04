---
title: Event Rules
audience: [operator, security]
version: 4.1.0
last_verified: 2026-06-26
verified_against:
  - src/analyzer.py
  - src/report/rules_engine.py
  - src/report/rules/
  - src/events/
  - src/report/analysis/
---

# Event Rules — illumio-ops v4.1.0

> This document explains the **rule logic** and **analysis methods** inside illumio-ops: how the system decides what to raise an alert on, and how it analyzes traffic flows and security posture. It lists the rules that are **actually implemented, verified line-by-line against the source code** — anything not implemented is omitted.
>
> Glossary terms (PCE, VEN, Workload, Service, Port, Policy, Ruleset, flow, policy_decision, draft_policy_decision, etc.) are kept in their original English.

---

## 1. Overview: Two Decision Systems + One Event Pipeline

Inside illumio-ops there are **two independent rule decision engines**, plus one **event processing pipeline**:

| System | Code location | Trigger | Evaluates | Output |
|------|----------|----------|----------|------|
| **Real-time Monitor Rule Engine** | `src/analyzer.py` | Every monitoring cycle (every 300 s by default; the scheduler triggers `Analyzer.run_analysis()`) | PCE audit **events** + live **traffic flows** | Dispatches alerts (event / traffic / metric / health alert) to each channel |
| **Report Security Rule Engine** | `src/report/rules_engine.py` + `src/report/rules/` | When a report is generated (`ReportGenerator._run_pipeline`) | The flows aggregated into a single "unified DataFrame" | A set of `Finding` objects (the list of rule hits), feeding the Module 12 summary and the HTML/Excel export |
| **Event Pipeline** | `src/events/` | Called during the event stage of the real-time monitor engine | Raw PCE events | Normalization, dedup, throttling, classification (known/unknown), shadow comparison, statistics |

### Fundamental difference between the two engines

- The **Real-time Monitor Rule Engine** is a "condition match + threshold + cooldown" type: each rule is a configuration dictionary (stored in `config/alerts.json`) describing the event type / flow conditions to match, the threshold value, and the operator. When a rule matches and exceeds its threshold, an alert is dispatched. Rules are user-defined or come from applying the "best-practice" default set.
- The **Report Security Rule Engine** is a "programmatic detection logic" type: each rule (the B/L/R series) is a hard-coded Python detection function that runs over the aggregated flow DataFrame and determines **severity** based on the network context (cross-subnet, cross-env, whether allowed), attaching a MITRE ATT&CK mapping and a recommendation. There are **24** implemented rules in total.

### Rule count at a glance (counted directly from source)

| Category | Implemented IDs | Count |
|------|---------|------|
| Real-time monitor rule "types" | event / traffic / bandwidth / volume / system | 5 types |
| Default factory alert rules | `config/alerts.json` ID 18–34 (`apply_best_practices`) | 16 event + 1 traffic = 17 rules |
| Report B series (ransomware / coverage) | B001–B009 | 9 |
| Report L series (lateral movement / exfiltration) | L001–L010 | 10 |
| Report R series (Draft policy alignment) | R01–R05 | 5 |
| **Report security rules total** | | **24** |

> **"24 rules" verification result: correct.** B series 9 + L series 10 + R series 5 = 24, consistent with the audit claim. Although the header comment of the report rules engine reads "B001–B009, L001–L010", the R series is stored separately under `src/report/rules/`; the three together sum to exactly 24.

---

## 2. Real-time Monitor Rules

Core code: the `Analyzer` class in `src/analyzer.py`. One monitoring cycle, `run_analysis()`, runs the following in order:

1. `_run_health_check()` — system / `pce_health` rules
2. `_run_event_analysis()` — event rules
3. `_fetch_traffic()` + `_run_rule_engine()` — traffic / bandwidth / volume rules
4. `_dispatch_alerts()` — dispatch traffic-type alerts
5. `save_state()` — persist the watermark, history, and cooldown state

All rules are stored in the `rules` array of `config/alerts.json`; each has a `type` field distinguishing the five types.

### 2.1 The five rule types and their trigger operators

| `type` | Trigger metric source | Threshold operator | Aggregation across flows | Dispatch method |
|--------|--------------|------------|--------------------|----------|
| `event` | Number of matched events | `count_val >= threshold_count` (and `> 0`) | `immediate`: matches in the current batch; `count`: historical matches within the sliding window of `threshold_window` minutes (`_event_count_in_window`) | `reporter.add_event_alert` |
| `traffic` | Connection count `num_connections` | `val >= threshold_count` | **Sum** | `reporter.add_traffic_alert` |
| `volume` | Data volume (MB, `calculate_volume_mb`) | `val >= threshold_count` | **Sum** | `reporter.add_metric_alert` |
| `bandwidth` | Bandwidth (Mbps, `calculate_mbps`) | `bw_val > threshold_count` (**strictly greater than**) | **Max**; triggered if any single flow exceeds the threshold | `reporter.add_metric_alert` |
| `system` | PCE health status code | Triggered when health status **≠ 200** | — (calls `api.check_health()`) | `reporter.add_health_alert` |

> The operator difference is made explicit by `_build_criteria_str` and `_dispatch_alerts`: **bandwidth uses `>`, traffic/volume use `>=`**. `calculate_mbps` prefers delta bytes/`ddms` (Interval), falling back to total bytes/`tdms` (Avg); `calculate_volume_mb` works the same way (Interval → Total).

> Beyond the polled `system` health-status check above, the PCE itself also emits `system_health` events roughly every minute — logged at **INFO** severity while the cluster is healthy, escalating to **Warning / Error / Fatal** only when system metrics (CPU, memory, disk) cross their thresholds. The Illumio best practice is to monitor these events filtered to **severity Warning or higher**. (Source: Illumio "Events Described — Recommended Events to Monitor".)

### 2.2 Flow matching: `check_flow_match`

Each traffic/bandwidth/volume rule calls `check_flow_match(rule, f, start_time_limit)` for every flow, checking in order:

1. **Sliding window**: the flow is excluded if its `timestamp` (or `timestamp_range.last_detected/first_detected`) is earlier than `now - threshold_window`.
2. **policy_decision (`pd`)**: the flow's `pd` is numericalized as `0=allowed`, `1=potentially_blocked`, `2=blocked` (inferred from the `policy_decision` string when there is no `pd` field). A rule's `pd` defaults to `-1` (event-type) or `3` (traffic-type); **both `-1` and `3` mean "any PD"**, while any other value must match exactly to hit. (Note: this `3` is a tool-internal sentinel for "any PD" and is **distinct** from Illumio's raw traffic data, where a flow `pd` of `3` means **"Unknown"** — e.g. traffic reported by idle VENs in snapshot state, or flows uploaded via the bulk-upload API. Source: Illumio "Traffic Flow Summaries".)
3. **Port / Proto**: `rule.port` and `rule.proto` must equal the flow's `dst_port`/`service.port` and `proto`/`service.proto`.
4. **Label / IP inclusion filters**: `src_label`, `dst_label` (both `key=value` and `key:value` separators are supported), `src_ip_in`, `dst_ip_in` (matched against the IP or the ip_list name).
5. **Any-side inclusion**: `any_label`, `any_ip` — a match on **either** src or dst is sufficient.
6. **Exclusion filters**: `ex_port`, `ex_src_label`, `ex_dst_label`, `ex_src_ip`, `ex_dst_ip`, plus the any-side exclusions `ex_any_label`, `ex_any_ip`.

`_run_rule_engine` computes `bw_val`, `vol_val`, and `conn_val` per flow, then aggregates them into each rule's `max_val` and `top_matches` according to type; `_dispatch_alerts` sorts and takes the Top 10, builds the criteria string, and dispatches.

### 2.3 Event matching: `matches_event_rule` (`src/events/matcher.py`)

Event rules match the event type using `filter_value`, supporting a rich set of operators:

- **Multiple patterns**: `filter_value` is a comma-separated list of patterns; a match on any one of them counts.
- **Wildcard**: `*` / `any` / `all` / empty string → always matches.
- **Pipe alternation**: `a|b|c` (when not a regex pattern) → matches if it belongs to the set.
- **Regular expression**: patterns containing `^ $ * + ? [ ] ( ) { } \` or `.* .+ .?` are matched anchored as `^pattern$`.
- **Negation**: a leading `!` → inverts the match.
- It also matches `filter_status` (e.g. `failure`) and `filter_severity`, plus `match_fields` (nested-field dot-path).

### 2.4 Cooldown and throttling: `_check_cooldown`

Crossing the threshold does not dispatch immediately; the alert must pass through two gates:

1. **Cooldown**: `cooldown_minutes` (defaults to `threshold_window`, which in turn defaults to 10 minutes). If less than the cooldown time has passed since the last alert for the same rule → suppressed (recorded as a `cooldown` suppression).
2. **Throttle** (`AlertThrottler.allow`, `src/events/throttle.py`): the rule's `throttle` field is `"count/period[unit]"` (unit: `s`/`m`/`h`/`d`, defaulting to `m` when omitted). Once `count` alerts have already been dispatched within the sliding window `period` → suppressed (recorded as a `throttle` suppression).

### 2.5 Default factory rules (Best-Practice Rule Set)

Generated by `_best_practice_rules()` in `src/config.py` (applied by `apply_best_practices`) and persisted to `config/alerts.json` (ID 18–34). There are **16 event rules + 1 traffic rule** in total:

| ID | name_key | filter_value (event type) | Threshold type | count | window (min) | cooldown (min) | throttle | Filter |
|----|----------|---------------------------|--------|-------|-----------|--------------|----------|------|
| 18 | `rule_agent_tampering` | `agent.tampering` | immediate | 1 | 10 | 30 | — | VEN agent tampered with |
| 19 | `rule_agent_suspend` | `agent.suspend` | immediate | 1 | 10 | 30 | — | Agent suspended (enforcement stopped) |
| 20 | `rule_agent_clone` | `agent.clone_detected` | immediate | 1 | 10 | 30 | — | Cloned agent detected |
| 21 | `rule_agent_heartbeat` | `system_task.agent_missed_heartbeats_check` | count | 3 | 30 | 60 | `1/30m` | Missed heartbeats |
| 22 | `rule_agent_offline` | `system_task.agent_offline_check` | count | 3 | 30 | 60 | `1/30m` | Agent offline |
| 23 | `rule_lost_agent` | `lost_agent.found` | immediate | 1 | 10 | 60 | — | Lost-agent recovered |
| 24 | `rule_login_failed` | `user.sign_in,user.login` | count | 5 | 10 | 30 | `1/15m` | `filter_status=failure`; login failure |
| 25 | `rule_api_auth_failed` | `request.authentication_failed` | count | 5 | 10 | 30 | `1/15m` | API authentication failure |
| 26 | `rule_policy_fail` | `agent.refresh_policy` | immediate | 1 | 10 | 30 | — | `filter_status=failure`; Policy refresh failure |
| 27 | `rule_ruleset_change` | `rule_set.create,rule_set.update,rule_set.delete` | immediate | 1 | 10 | 60 | — | Ruleset change |
| 28 | `rule_policy_provision` | `sec_policy.create` | immediate | 1 | 10 | 60 | — | Security Policy provisioning |
| 29 | `rule_api_authz_failed` | `request.authorization_failed` | count | 3 | 10 | 30 | `1/15m` | API authorization failure |
| 30 | `rule_api_key_change` | `api_key.create,api_key.delete` | immediate | 1 | 10 | 60 | — | API key created/deleted |
| 31 | `rule_sec_rule_change` | `sec_rule.create,sec_rule.update,sec_rule.delete` | immediate | 1 | 10 | 60 | — | Security Rule change |
| 32 | `rule_bulk_unpair` | `workloads.unpair,agents.unpair` | immediate | 1 | 10 | 60 | — | Bulk unpair (large-scale de-enforcement) |
| 33 | `rule_auth_settings_change` | `authentication_settings.update` | immediate | 1 | 10 | 60 | — | Authentication settings change |
| 34 | `rule_high_blocked` | (traffic, `pd=2`) | count | 25 | 10 | 30 | `1/15m` | High Blocked traffic |

> **On rule 20 (`agent.clone_detected`)**: beyond detecting the clone, Illumio natively supports **automatic cloned-VEN remediation** for on-prem Windows domain-joined workloads — it detects changes to the workload's domain SID and remediates the cloned VEN automatically. (Source: Illumio "Events Described — Automatic Cloned VEN Remediation".)

> **i18n key storage**: each rule persists `name_key`/`desc_key`/`rec_key` (i18n keys), **not** the translated text. `_write_alerts_file` strips the rendered `name`/`desc`/`rec` before writing to disk; on `load()`, `_resolve_rule_keys()` re-renders them in the current language via `t(key, lang=lang)`. `_LEGACY_FILTER_TO_NAME_KEY` (16 entries) maps legacy rules — which were keyed by `filter_value` — back to the canonical `name_key`, for migrating old `alerts.json` files.

---

## 3. Event Pipeline — `src/events/`

Event processing has seven stages: **poll → normalize → dedup → throttle → classify (known/unknown) → shadow-compare → stats**. The package docstring describes itself as "inspired by illumio-pretty-cool-events". (`runbooks.py` is not a processing stage — it provides an event_type → remediation mapping (`runbook_for`) that the alert reporter can surface; see §3.7.)

### 3.1 Poll + Dedup (`poller.py`)

- `EventPoller(api_client, max_results=5000, overlap_seconds=60, subscriber=None)`.
- `fetch_batch(watermark, seen_events)`: uses `watermark - overlap_seconds` (**a 60-second overlap**, to re-catch late-arriving events) as the query start point, calling `api.fetch_events_strict(...)`.
- **Deduplication happens here**: `event_identity(event)` is the dedup key — it uses the `href` directly if present, otherwise it takes a `sha1` fingerprint over `event_type/timestamp/status/severity/created_by/resource/message`; anything already in `seen` is skipped.
- **Overflow risk**: `overflow_risk = raw_count >= max_results` (≥ 5000 means the window may have been truncated).
- `next_watermark` is `max(poll_started_at, watermark, latest_event_ts)`, **monotonic and never moving backward**.
- When a `subscriber` is set, it switches to the SQLite cache path (`poll_new_rows`).

### 3.2 Normalize + classification tagging (`normalizer.py`)

`normalize_event(event)` flattens a raw PCE event into a stable dictionary, with fields including `event_id, href, timestamp, event_type, category (prefix before the first .), verb (last segment), status, severity, known_event_type, actor, actor_type, source_ip, target_*, resource_*, action_*, workloads_affected, parser_notes`, and others. **`known_event_type = is_known_event_type(event_type)`** is stamped here. `_build_parser_notes` adds diagnostic tags (such as `unknown_event_type`, `action_unresolved`, `principal_unresolved`, etc.). `_RESOURCE_TYPE_PRIORITY` (20 resource types) determines the primary resource.

### 3.3 Throttle (`throttle.py`)

`parse_throttle` parses `count/period[unit]` (unit multipliers `s=1, m=60, h=3600, d=86400`, default `m`). `AlertThrottler.allow` is a **sliding-window rate limit** of at most `count` per `period` seconds; `prune` keeps 24 hours (86400 seconds) by default. (The real-time engine performs throttle suppression through this class, as described in §2.4.)

### 3.4 Classify known / unknown (`catalog.py`)

- The file header describes itself as "**Vendor-derived PCE event catalog … based on alexgoller/illumio-pretty-cool-events**", serving as the baseline for detecting unknown / newly appearing event types.
- **`KNOWN_EVENT_TYPES`**: 285 vendor event types + 3 in `LOCAL_EXTENSION_EVENT_TYPES` = **288 known types**.
- **`KNOWN_RESOURCE_PREFIXES`** (69 resource-family prefixes) is the second line of defense: new actions on existing resources in PCE 25.x+ can be leniently treated as known.
- `is_known_event_type(event_type, lenient=False, *, resource_type=None)`: the normalizer calls it in **non-lenient** mode, so anything not in the 288-member set is marked `known_event_type=False` and tagged `unknown_event_type`.
- `classify_unknown_event_type(...)`: assigns an unknown type to a resource family or marks it `unclassified`.
- The real-time engine's `_update_parser_observability` accumulates unknown types into `state["unknown_events"]` (capped at 100 entries); at startup, `load_state` clears out old unknown entries that are now covered by the newer catalog.

### 3.5 Shadow-compare (`shadow.py`)

**A diagnostic tool, not the production matching logic.** `matches_event_rule_legacy` implements the original/simplified semantics (comma-separated exact matching only, no regex/negation/pipe/nesting); `compare_event_rules` runs both the "current" and "legacy" matchers, compares the difference in their hit sets, and labels it `same / mixed / current_more / legacy_more`, for use by the GUI's `shadow_compare` and `rule_test` endpoints. **Production dispatch always uses `matches_event_rule`.**

### 3.6 Stats (`stats.py`)

`StatsTracker` (`timeline_limit=100`, `dispatch_limit=50`) records `dispatch_history`, `event_timeline`, and `pce_stats` (including `health_status`, `event_poll_status`, `consecutive_failures`, `last_batch_total/unknown/notes/overflow`, etc.). It provides `record_pce_success/error`, `record_event_batch`, `record_rule_trigger`, `record_suppression`, and `record_dispatch`.

### 3.7 Runbooks (`runbooks.py`)

`RUNBOOK_CATEGORIES` maps event types to operational guidance, **16 categories** in total, each containing `patterns` (the event types covered), `runbook_url` (a docs.illumio.com link), `severity_hint`, and a multi-line `response` playbook. `runbook_for(event_type)` looks up the matching category. The categories with `severity_hint=critical` are: `security-auth-failure`, `agent-tampering`, `auth-config`, `server-errors`.

> There is also `reference.py`: an `EventRef` (category/description/severity/remediation/doc_url) backed by `docs/_meta/illumio-event-reference.json`, cached with `lru_cache`.

---

## 4. Report Security Rules — B / L / R

Code: `src/report/rules_engine.py` (the B/L series built-in functions) + `src/report/rules/r01..r05` (the R series modules). `RulesEngine.evaluate(df)` first runs the built-in B/L rules, then the R series (`_eval_draft_pd`), and finally sorts by severity and attaches MITRE techniques via `annotate_techniques`.

### 4.1 Common model

- `Finding` (`src/report/rules/_base.py`): `rule_id, rule_name, severity, category, description, recommendation, evidence, technique_ids`.
- **Severity ordering**: `CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3, INFO=4`.
- **Source of risk ports / thresholds**: `config/report_config.yaml` (`ransomware_risk_ports`, `lateral_movement_ports`, `thresholds`).
- `description`/`recommendation` are localized via `t(key, lang=...)` (the key is persisted, not the text).

#### Risk port configuration (`report_config.yaml`, used by B001–B003 and Module 4)

| Level | Ports (service) |
|------|------------------|
| critical | 135 RPC, 445 SMB, 3389 RDP, 5985/5986 WinRM |
| high | 5938 TeamViewer, 5900 VNC, 137/138/139 NetBIOS |
| medium | 22 SSH, 2049 NFS, 20/21 FTP, 5353 mDNS, 5355 LLMNR, 80 HTTP, 3702 WSD, 1900 SSDP, 23 Telnet |
| low | 110 POP3, 1723 PPTP, 111 SunRPC, 4444 Metasploit |

`lateral_movement_ports` (used by B006, L006): `3389, 5900, 22, 445, 5985, 5986, 5938, 23`.

### 4.2 B series (ransomware risk / coverage / behavioral anomaly) — 9 rules

| ID | Name | Severity | Detection logic (hit condition) | Key threshold | MITRE |
|----|------|--------|----------------------|----------|-------|
| **B001** | Ransomware Risk Port — Contextual Analysis | **Context-dependent**: CRITICAL / HIGH / MEDIUM / INFO | Flows on critical risk ports with `policy_decision != blocked`, graded by **network proximity** (see below) | Risk port set | T1486, T1021.002 |
| B002 | Ransomware Risk Port (High) | HIGH | high risk port and `policy_decision == allowed` | — | T1486, T1219 |
| B003 | Ransomware Risk Port (Medium) — Uncovered | MEDIUM | medium risk port and `policy_decision == potentially_blocked` | — | T1486 |
| B004 | Unmanaged Source High Activity | MEDIUM | Number of flows with `src_managed == False` > threshold | `unmanaged_connection_threshold=50` | T1046 |
| B005 | Low Policy Coverage | MEDIUM | allowed share < threshold% | `min_policy_coverage_pct=30` | (governance, not mapped) |
| B006 | High Lateral Movement | HIGH / MEDIUM | On lateral ports (not blocked), the number of unique dsts reached by a single src > threshold; HIGH if **allowed** flows drive the fan-out, otherwise (PB only) MEDIUM | `lateral_movement_outbound_dst=10` | T1021 |
| B007 | Single User High Destinations | HIGH | Number of unique dsts reached by a single `user_name` > threshold | `user_destination_threshold=20` | T1078 |
| B008 | High Bandwidth Anomaly | MEDIUM | Flows whose `bytes_total` exceeds the 95th percentile | `high_bytes_percentile=95` | T1048 |
| B009 | Cross-Env Flow Volume | INFO | Number of cross-env flows (`src_env != dst_env`) > threshold | `cross_env_connection_threshold=100` | (informational, not mapped) |

**B001's cross-subnet scoped counting (the core severity logic)**: first the matched flows are tagged `_same_subnet` (same /24 if the first three octets of the src/dst IP are identical) and `_cross_env`, then evaluated in order:

1. **CRITICAL** — a cross-env flow exists (e.g. Dev → Prod over SMB/RDP).
2. **HIGH** — there are cross-subnet flows and the **allowed count within the cross-subnet subset** > 0.
3. **MEDIUM** — the cross-subnet flows are all `potentially_blocked` (test-mode).
4. **INFO** — all within the same /24 and all PB.
5. **MEDIUM** (fallback) — same /24 but containing allowed flows (legitimate management traffic, still recorded).

> The key point: severity is driven by the allowed/PB ratio **within the cross-subnet subset** (`n_cross_subnet_allowed`, `n_cross_subnet_pb`), not by the global allowed/PB counts — this avoids misclassifying same-subnet management traffic as high risk.

#### Port groups used by the L series (`rules_engine.py` constants)

`_DB_PORTS = {1433,3306,5432,1521,27017,6379,9200,5984,50000}`; `_IDENTITY_PORTS = {88,389,636,3268,3269,464}`; `_CLEARTEXT_PORTS = {23,20,21}`; `_DISCOVERY_PORTS = {137,138,5353,5355,1900,3702}`; `_WINDOWS_MGMT_PORTS = {135,445,5985,5986,47001}`.

### 4.3 L series (lateral movement / exfiltration) — 10 rules

| ID | Name | Severity | Detection logic | Threshold | MITRE |
|----|------|--------|----------|------|-------|
| L001 | Cleartext Protocol in Use | HIGH / MEDIUM | Flows on Telnet/FTP (23/20/21); HIGH if allowed flows are present, otherwise MEDIUM | — | T1040 |
| L002 | Network Discovery Protocol Exposure | MEDIUM | Number of non-blocked NetBIOS/mDNS/LLMNR/SSDP/WSD flows ≥ threshold | `discovery_protocol_threshold=10` | T1557.001 |
| L003 | Database Port Wide Exposure | HIGH | For allowed flows on DB ports, the number of unique `src_app` per single (dst_ip,port) > threshold | `db_unique_src_app_threshold=5` | T1210 |
| L004 | Cross-Environment Database Access | HIGH | DB port, cross-env, and allowed | — | T1210 |
| L005 | Identity Infrastructure Wide Exposure | HIGH / MEDIUM | Non-blocked Kerberos/LDAP/GC, number of unique `src_app` > threshold; HIGH if allowed flows drive it | `identity_unique_src_threshold=3` | T1558 |
| L006 | High Blast-Radius Lateral Movement Path | HIGH | Builds an app→app directed graph over lateral ports (allowed) and uses **BFS** to compute each node's reachable count ≥ threshold | `blast_radius_threshold=5` | T1021 |
| L007 | Unmanaged Host Accessing Critical Services | HIGH | Number of non-blocked flows from `src_managed==False` to DB/Identity/WinMgmt ports ≥ threshold | `unmanaged_critical_threshold=5` | T1210 |
| L008 | Lateral Ports in Test Mode (PB) | HIGH | Number of `potentially_blocked` flows on lateral/WinMgmt/DB/Identity ports ≥ threshold (enforcement gap) | `pb_lateral_threshold=10` | (governance, not mapped) |
| L009 | Data Exfiltration Pattern (Outbound to Unmanaged) | HIGH | managed src → unmanaged dst, allowed, `bytes_total>0`, with total volume ≥ threshold MB | `exfil_bytes_threshold_mb=100` | T1048 |
| L010 | Cross-Environment Lateral Port Access | **CRITICAL** | lateral/WinMgmt port, cross-env, and allowed, with flow count ≥ threshold | `cross_env_lateral_threshold=5` | T1021, T1570 |

> L006's methodology borrows from Illumio MCP's `detect-lateral-movement-paths` (BFS reachability); the overall MITRE mapping for L001–L010 lives in `src/report/analysis/mitre_map.py`. Governance-type rules (B005, B009, L008, R01–R05) are deliberately **not mapped** to MITRE, to avoid misleading the SOC.

### 4.4 R series (Draft Policy alignment) — 5 rules

The R series is only evaluated when the unified DataFrame carries a **`draft_policy_decision`** column (`_DraftPdRuleMixin._has_draft`); without the column, the whole batch is a no-op. They all belong to the `DraftPolicy` category.

| ID | Name | Severity | Hit condition (draft_policy_decision) |
|----|------|--------|----------------------------------|
| R01 | Draft Deny Detected | HIGH | `policy_decision==allowed` but draft ∈ {`blocked_by_boundary`,`blocked_by_override_deny`} (currently allowed, but the draft would block it) |
| R02 | Override Deny Detected | HIGH | draft ends with `_override_deny` (an override deny rule that no allow can override) |
| R03 | Visibility Boundary Breach | MEDIUM | `policy_decision==potentially_blocked` and draft==`potentially_blocked_by_boundary` (the VEN is in visibility/test mode and there is a draft deny boundary) |
| R04 | Allowed Across Boundary | LOW | draft==`allowed_across_boundary` (an allow rule overrides a regular deny boundary; confirm whether this is intentional) |
| R05 | Draft Reported Mismatch | INFO | `policy_decision==allowed` but draft starts with `blocked_` (aggregates the workload pairs that are reported=allowed but that the draft recommends blocking) |

#### Activation status of the R series (read this accurately)

- **The engine is wired up**: `RulesEngine.evaluate` runs R01–R05 when the DataFrame carries a `draft_policy_decision` column; that column is produced by `compute_draft` at query time (PCE `update_rules`).
- **The data is confirmed available**: tested against a LIVE PCE on 2026-06-26, when the traffic query is run with `compute_draft` (`update_rules`), the PCE **does return `draft_policy_decision` for every flow**.
- **But full production activation is constrained by an "on-demand gate"**: `ruleset_needs_draft_pd(DRAFT_PD_RULES)` is **effectively always True** because R01–R05 all have `needs_draft_pd()=True`. Although `report_generator.py` accordingly stuffs `requires_draft_pd=True` into the filters, the **standard report fetch path** `fetch_traffic_for_report → execute_traffic_query_stream` **does not pass `compute_draft` (which defaults to False)**, and the **cache path (`read_flows_df`) has no draft column to begin with**. As a result, the DataFrames for ordinary reports and for cache-hit reports both **lack** `draft_policy_decision`, so the R series is a no-op.
- Wiring `compute_draft` into every report fetch would make every report pay the cost of a PCE `update_rules` call (measured at about 12 seconds).
- **Conclusion (honest labeling)**: the R series is "**engine-ready + data confirmed available, but activated on demand**" — it belongs to a dedicated draft-policy analysis / draft-report mode and **does not run on every report**.

---

## 5. Report Analysis Modules

Registry: `TRAFFIC_MODULES` in `src/report/analysis/__init__.py`, dynamically loaded by `_run_modules`. Module 12 (executive_summary) runs last, aggregating the results of the other modules. **mod05 (Remote Access) has been merged into mod15.**

### 5.1 Traffic analysis modules (mod01–mod15)

| Module | Title | Analysis content (key outputs) |
|------|------|----------------------|
| mod01 | Traffic Overview | KPI overview: `total_flows`, `total_connections`, unique src/dst IPs, `total_bytes`, `policy_coverage_pct` (allowed%), allowed/blocked/PB/unknown counts, `src_managed_pct`/`dst_managed_pct`, Top ports/protocols |
| mod02 | Policy Decision Breakdown | Broken down by `policy_decision`; for each category, top app→app flows, top ports, the inbound/outbound split, and port coverage |
| mod03 | Uncovered Flows (coverage gap) | **Three-tier coverage**: Enforced (allowed/total), Staged (PB/total — the rule exists but the workload is in test/visibility), True Gap ((blocked+unknown)/total). Uncovered flows are classified as `unmanaged_source`/`intra_app`/`cross_app`, with per-port and per-service gap rankings plus in/outbound coverage |
| mod04 | Ransomware Exposure | Tags flows with the `report_config` risk ports (4 levels) and outputs A) a per-level summary, B) per-port detail (allowed/blocked/PB), C) the PD distribution, D) a host exposure ranking (the dsts exposing the most risk ports), E) investigation targets (hosts with allowed flows on critical/high ports). `risk_flows_total` feeds into the mod12 maturity score |
| mod05 | (merged into mod15) | — |
| mod06 | User & Process Activity | Flows with `user_name`/`process_name`: top users, the user→app matrix, top processes |
| mod07 | Cross-Label Flow Matrix | Builds a src×dst traffic matrix from the four label keys `env/app/role/loc` |
| mod08 | Unmanaged Host Analysis | Traffic involving unmanaged hosts: per dst_app, per (port,proto), and src-port detail |
| mod09 | Traffic Distribution | Traffic distribution per label (env/app/role/loc) and top talkers |
| mod10 | Allowed Traffic | Top app→app, ports, and services for `policy_decision==allowed` |
| mod11 | Bandwidth & Volume | Volume/bandwidth analysis: top by bytes, top by Mbps, with the 95th percentile of per-connection bytes as the anomaly threshold |
| mod12 | Executive Summary | Aggregated summary + the **Microsegmentation Maturity Score** (see 5.2), the three-tier coverage KPIs, the Action Matrix, and Key Findings |
| mod13 | Enforcement Readiness | Per-app(env) **readiness score** (see 5.3), including attack-posture items and prioritized recommendations |
| mod14 | Infrastructure Scoring | Scores the app(env) graph by **betweenness centrality**; uses `_DB_PORTS` and `_IDENTITY_PORTS` to detect critical assets; assigns tiers and produces posture items |
| mod15 | Lateral Movement Risk | See 5.4 |

### 5.2 mod12 Microsegmentation Maturity Score (maturity, 0–100)

`_compute_maturity_score` is a five-dimension weighting (summing to 100):

| Dimension | Weight | Ratio formula |
|------|------|----------|
| enforcement_coverage | 40 | `min(100, enforced% + 0.5×staged%)/100` |
| policy_coverage | 25 | `enforced%/100` (allowed/total) |
| lateral_movement_control | 15 | `1 - min(lateral_pct,30)/30` (lateral_pct comes from mod15) |
| managed_asset_ratio | 10 | `1 - min(unmanaged%,50)/50` |
| risk_port_control | 10 | `1 - min(risk_ratio×5, 1)` (risk_ratio = mod04 risk_flows/total; 20% means 0 points) |

Outputs `maturity_score`, `maturity_grade`, and the per-dimension `maturity_dimensions`.

### 5.3 mod13 Enforcement Readiness (per-app(env) readiness score, 0–100)

`_WEIGHTS`: policy_coverage **35**, ringfence_maturity **20**, enforcement_mode **20**, staged_readiness **15**, remote_app_coverage **10**.

- policy_coverage: the allowed ratio; ringfence_maturity: the `src_key==dst_key` (within-the-same-app) ratio; enforcement_mode: the managed-flag ratio (falling back to the global workload enforcement ratio when absent); staged_readiness: = the allowed ratio (PB does **not** count); remote_app_coverage: the allowed ratio on remote ports `{22,3389,5900,5901,5938,3283}` (treated as 1.0 when there are no remote flows).
- Grades: A≥90, B≥75, C≥60, D≥45, F.
- Produces attack-posture items from the ratios: `enforcement_gap` (allowed<0.75), `boundary_breach` (ringfence<0.5 or remote_coverage<0.85), `suspicious_pivot` (blocked>0.2). Severity via `_severity_from_ratio`: ≥0.75 CRITICAL, ≥0.45 HIGH, otherwise MEDIUM.

### 5.4 mod15 Lateral Movement Risk (graph-theoretic lateral movement)

- Lateral port table (16 ports): 445 SMB, 135 RPC, 139 NetBIOS, 3389 RDP, 22 SSH, 5985/5986 WinRM, 23 Telnet, 2049 NFS, 111 RPC Portmapper, 389 LDAP, 636 LDAPS, 88 Kerberos, 1433 MSSQL, 3306 MySQL, 5432 PostgreSQL.
- `lateral_pct = lateral flows / all flows × 100` (fed back into mod12 dimension 3).
- Builds an app|env graph from the traversable (allowed + PB) lateral flows, computing: **Tarjan articulation points (articulation/bridge nodes)** and each node's **BFS reachability** (`max_depth=4`).
- `reach_score = reach_count/max_reach×100`; `bridge_score = (60 if articulation point else 0) + reach_score×0.4`; Risk Level: ≥85 Critical, ≥60 High, ≥35 Medium.
- attack-posture items: `suspicious_pivot` (articulation point and reach≥2; CRITICAL when reach≥6, otherwise HIGH), `blast_radius` (reach≥4, HIGH), `blind_spot` (unmanaged and traversable; ≥3 HIGH, otherwise MEDIUM).
- Outputs service_summary, fan-out sources, attack_paths, bridge_nodes, top_reachable_nodes, source_risk_scores, and the network-graph chart_spec.

### 5.5 Posture sub-scores (`src/report/posture.py`)

`compute_posture(kpis)` computes the dashboard posture score from the report snapshot (the mod12 output); it is a **pure function**:

```
score = round(coverage×0.3 + readiness×0.3 + risk_health×0.4)   (weights are re-normalized if any item is missing)
```

- **coverage**: `enforced_coverage_pct` (policy enforcement %).
- **readiness**: `maturity_score` (microsegmentation maturity).
- **risk_health** = `100 - penalty`, where `penalty = min(100, ransomware_pts + lateral_pts + uncovered_pts)`:
  - `ransomware_pts = min(40, ransomware_apps×5)` (5 points per exposed app, capped at 40)
  - `lateral_pts = round((1 - lateral_control_ratio)×30)` (30 points when fully uncontrolled)
  - `uncovered_pts = min(30, uncovered_pct×0.5)` (60% gap = 30 points)
- The three risk sub-scores: `ransomware_containment` = `100×(1-ransomware_pts/40)`, `lateral_containment` = `100×(1-lateral_pts/30)`, `flow_coverage` = `100×(1-uncovered_pts/30)`.

### 5.6 Attack-posture data layer (`attack_posture.py`)

The deterministic posture layer shared by mod13/mod14/mod15: `make_posture_item` (scope/framework/app_env_key/finding_kind/attack_stage/confidence/recommended_action_code/severity/evidence), `rank_posture_items` (sorted by severity → confidence → attack_stage → finding_kind), `resolve_recommendation` (12 action codes mapped to `rpt_action_*` i18n keys), and `summarize_attack_posture` (aggregates boundary_breaches/suspicious_pivot/blast_radius/blind_spots + the action_matrix).

### 5.7 Draft and other auxiliary modules

- **`mod_draft_summary`**: when the `draft_policy_decision` column is present, it counts the **7 sub-types** (allowed, potentially_blocked, blocked_by_boundary, blocked_by_override_deny, potentially_blocked_by_boundary, potentially_blocked_by_override_deny, allowed_across_boundary) and the top workload pairs for each type; skipped when the column is absent.
- **`mod_draft_actions`**: actionable analysis — the top pairs and remediation/review workflows for `override_deny`, `potentially_blocked_by_override_deny`, and `allowed_across_boundary`, plus a `what_if_summary` (the `would_change_share` where reported and draft differ).
- **`ransomware_posture`**: a PCE-native (not flow-based) ransomware posture — cross-references a workload's `risk_summary.ransomware` (exposure severity, protection %) with its `open_service_ports`, outputting KPIs (the count at each exposure level, avg protection %), a per-VEN view, and a list of high-risk open ports.
- **`mod_ringfence`**: per-app dependency profile + candidate allow rules + boundary deny candidates.
- **`mod_drift`**: baseline drift — the app→app connection pairs added/disappeared compared with the previous run (a pure signature comparison). Noise signatures (ICMP, port 0, ephemeral ports ≥49152) and `(unlabeled)→(unlabeled)` pairs are excluded from both tables and their counts (the latter collapsed into a single summary line instead). When the previous baseline carries metadata (window/data_source/profile) and this run's window differs materially from it, the comparison is refused outright (a fresh baseline is still saved) to avoid reporting a whole-baseline swap as false disappearances; baselines saved before this metadata existed are compared exactly as before (no refusal, no warning).
- **`mod_change_impact`**: compares KPIs against the previous snapshot; `LOWER_BETTER=(pb_uncovered_exposure, high_risk_lateral_paths, blocked_flows)`, `HIGHER_BETTER=(active_allow_coverage, microsegmentation_maturity)`.
- **Trend deltas (`trend_store`)**: the traffic/audit/policy_usage/VEN reports each save a per-run KPI snapshot and render a delta vs. the previous one (`load_previous` reads the latest snapshot on disk, since save happens right after — deltas are available from the very next run, not the one after that). Snapshots also carry window/data_source/profile metadata; when it differs from the previous snapshot's, the Trend section shows a caveat naming the differing fields instead of silently comparing unlike periods. Snapshots saved before this metadata existed compare exactly as before (no caveat).

---

## 6. Data sources (Cache vs Live, how Draft-PD is obtained)

Both engines run on a "unified DataFrame / flow stream", whose source can be either a **LIVE PCE** or the **SQLite `pce_cache`**:

- **Report fetching** (`ReportGenerator._fetch_traffic_df`) uses a cache-aware hybrid strategy:
  - cache **fully covers** the range → read everything from the cache (`read_flows_df`, vectorized).
  - **partial coverage** → the API fills the leading gap and the cache fills the rest (source labeled `mixed` or `cache`).
  - no coverage, or `use_cache=False` → a pure LIVE API call.
- **Real-time monitor fetching** (`Analyzer._fetch_query_flows`) uses the same hybrid logic (`cover_state` decides full/partial/miss).
- **Source of policy_decision**: the PCE flow's `policy_decision` (allowed / potentially_blocked / blocked). `potentially_blocked` means "a rule would block it, but the workload is still in visibility/test mode".
- **Obtaining draft_policy_decision**: only when the traffic query carries `compute_draft=True` does the API call the PCE's `…/update_rules` (PUT) to compute the draft result, returning it with `include_draft_policy=True` on the CSV download; **the cache does not contain this column**. This is the root reason for the on-demand activation of the R series in §4.4 (the `update_rules` call was measured at about 12 seconds).

---

## 7. How to add / adjust rules

### 7.1 Real-time monitor alert rules

- **GUI / CLI**: add or overwrite via `ConfigManager.add_or_update_rule()` (rules with the same `type` and the same event `filter_value` / traffic `name` are treated as the same rule). The rule is written to `config/alerts.json`.
- **Applying best practices**: `apply_best_practices(mode="append_missing" | "replace")`. `append_missing` deduplicates by `_rule_signature` and fills in what is missing; `replace` replaces everything (and automatically backs up to `rule_backups`, capped at 10).
- **Adjustable fields**: `threshold_type` (immediate/count), `threshold_count`, `threshold_window` (minutes), `cooldown_minutes`, `throttle` (`count/period[unit]`), `pd`, `port`/`proto`, and the various label/ip inclusion and exclusion filters.

### 7.2 Report rule thresholds and risk ports

Edit `config/report_config.yaml` directly:

- `ransomware_risk_ports` (the levels and ports for B001–B003 and mod04).
- `lateral_movement_ports` (B006, L006).
- `thresholds` (the numeric threshold for each B/L rule, tabulated in §4.2/§4.3).

> The severity branches (such as B001's cross-subnet scoped counting) are written inside the rule functions, not as configuration values; changing the decision logic requires editing `rules_engine.py`/`src/report/rules/`. To add a report rule: add a `_bNNN`/`_lNNN` method in `rules_engine.py` (or add and register a new module class under `src/report/rules/`), and map it to MITRE in `mitre_map.py`.

### 7.3 Schedulers

The repository has three independent schedulers; do not confuse them:

- **The monitoring loop** (`src/scheduler/`): periodically triggers `Analyzer.run_analysis()` according to `rule_scheduler.check_interval_seconds` in `config.json` (default **300 seconds**), evaluating the §2 alert rules in real time.
- **ReportScheduler** (`src/report_scheduler.py`): generates reports on a schedule.
- **Illumio Rule Scheduler / `ScheduleEngine`** (`src/rule_scheduler.py`, configured via `config/rule_schedules.json`): this is a **separate feature** — it toggles the enabled state of Rulesets/sec_rules/deny_rules on the PCE according to time windows (recurring/one_time), and is unrelated to the alert rules.

### 7.4 i18n keys (desc_key / rec_key)

- Monitor rules persist `name_key`/`desc_key`/`rec_key`, rendered on read by `_resolve_rule_keys()` via `t(key, lang)`; new rules should supply an i18n key rather than hard-coded text, with the text defined in `src/i18n_en.json`/`src/i18n_zh_TW.json`.
- Report `Finding` objects and the analysis modules are likewise localized at read (render) time via `t(key, lang=...)`; what is persisted/snapshotted is the key, so switching languages re-translates instantly.

### Appendix: honestly flagged code gaps

- **"24 rules"**: consistent with the source code (B 9 + L 10 + R 5). The `rules_engine.py` header only lists "B001–B009, L001–L010"; the R series is kept separately under `src/report/rules/`.
- **R series (R01–R05)**: the engine is wired up and a LIVE test confirmed the PCE can return `draft_policy_decision`, but the standard/cache report paths do not include the column (`fetch_traffic_for_report` does not pass `compute_draft`), so it is **activated on demand** and does not run on every report (see §4.4, §6).
- **mod04 risk port count**: the module docstring says "20 high-risk ports", but `report_config.yaml` actually lists 24 distinct ports (critical 5 + high 5 + medium 10 + low 4). This document follows the actual configuration file.
