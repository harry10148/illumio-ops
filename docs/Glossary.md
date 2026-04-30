# Glossary

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

> [English](Glossary.md) | [繁體中文](Glossary_zh.md)

---

This page is a quick reference for newcomers. Each entry is self-contained: read just one entry to get the gist, then follow the cross-reference for the full picture.

## Illumio Platform Terms

- **PCE (Policy Compute Engine)** — The server-side brain of the Illumio platform. It computes per-workload security policy and pushes it to every paired enforcement agent. Internally it spans four service tiers (Front End, Processing, Service/Caching, Persistence). See [Architecture §Background.1](./Architecture.md#background1-pce-and-ven) for the full description.

- **VEN (Virtual Enforcement Node)** — A lightweight agent that runs on each managed workload (bare-metal, VM, or container host). It programs the host's native firewall (`iptables`/`nftables` on Linux, WFP on Windows, etc.), collects flow telemetry, and applies policy received from the PCE. Communicates with the PCE over TLS on TCP 8443/8444 (or 443 on SaaS). See [Architecture §Background.1](./Architecture.md#background1-pce-and-ven).

- **Workload (Managed / Unmanaged / Container)** — The PCE's three categories of network entity. *Managed* = has a paired VEN and reports live traffic. *Unmanaged* = a labelled IP-only entity (laptops, appliances, PKI/Kerberos endpoints) with no VEN. *Container* = a Kubernetes/OpenShift pod monitored via Illumio Kubelink, with a single VEN on the host node. See [Architecture §Background.3](./Architecture.md#background3-workload-types).

- **Label / Label dimension** — Key-value metadata attached to workloads. Illumio uses four dimensions: `role` (function within an app, e.g. `web`, `database`), `app` (business service, e.g. `HRM`), `env` (SDLC stage, e.g. `production`), `loc` (geography, e.g. `aws-east1`). Rules target labels rather than IPs, so a `role=web, env=production` rule applies wherever those labels are assigned. See [Architecture §Background.2](./Architecture.md#background2-label-dimensions).

- **Ruleset** — A scoped container that groups related security rules and applies them to a set of workloads (typically defined by `app`+`env` labels). The unit of write/provision in the policy lifecycle.

- **Rule** — A single allow/deny statement inside a ruleset, expressed as `provider × consumer × service`. Both sides are usually label selectors.

- **Service** — A reusable definition of one or more `protocol+port` combinations (e.g. `tcp/443, tcp/80`) referenced by rules instead of inlining ports.

- **IP List** — A named set of IP addresses or CIDR ranges, used as a provider or consumer in rules to express traffic to/from non-workload endpoints (e.g. external partners, internet egress points).

- **Label Group** — A named collection of label values from the same dimension, used to write one rule that applies to several environments or applications without duplicating it.

- **Enforcement Boundary** — A scoped deny statement separate from regular rules. Defines a "blast wall" between groups of workloads; in Selective enforcement mode the VEN blocks only flows that violate a boundary.

- **Policy lifecycle: Draft to Pending to Active** — Every write to a policy object lands first in **Draft** (invisible to the VEN), batches into **Pending** for review and impact analysis, and only takes effect on workloads after an explicit provisioning action promotes it to **Active**. The PCE then recomputes the policy graph and pushes new firewall rules to every affected VEN. See [Architecture §Background.4](./Architecture.md#background4-policy-lifecycle) for the full lifecycle.

- **Enforcement modes: Idle / Visibility Only / Selective / Full** — The four states a VEN can be in. *Idle* = enforcement off, no logging. *Visibility Only* = passive monitoring, no blocking. *Selective* = block only flows violating an Enforcement Boundary. *Full* = default-deny / zero-trust, allow-list only. Full is the target state for production microsegmentation. See [Architecture §Background.5](./Architecture.md#background5-enforcement-modes).

- **Heartbeat** — The VEN's periodic check-in with the PCE (every 5 minutes for status, every 10 minutes for summarized flow logs). The PCE also uses heartbeats as a fallback channel for policy updates when the long-lived lightning-bolt channel is unavailable.

- **`policy_decision` vs `draft_policy_decision`** — Two fields attached to every traffic flow. `policy_decision` is the *historical* verdict the VEN recorded at flow time (always one of `allowed`, `potentially_blocked`, `blocked`). `draft_policy_decision` is *dynamically recalculated* against current active + draft rules after a `PUT {job_href}/update_rules` call, so it reflects what would happen if drafts were provisioned today. See [Security Rules Reference §Policy Decision Fields](./Security_Rules_Reference.md#policy-decision-fields) for the full value table.

## Tool-Specific Terms (illumio-ops)

- **PCE Cache** — An optional local SQLite (WAL) database that stores a rolling window of PCE audit events and traffic flows. Acts as a shared buffer feeding the SIEM forwarder, report modules, and the alert/monitor loop, so they avoid hammering the PCE's 500 req/min rate limit. Disabled by default; enable via `pce_cache.enabled` in `config/config.json`. See [PCE Cache](./PCE_Cache.md).

- **Ingestor** — A background poller (one per data source: `events`, `traffic`) that pulls new rows from the PCE API into the cache on a fixed schedule. Ingestors share a global token-bucket rate limiter (default 400/min) so the daemon never exceeds the PCE budget.

- **Watermark** — A per-ingestor cursor stored in the `ingestion_watermarks` table marking the last successfully fetched timestamp for each source. Survives restarts so polling resumes without gaps or duplicates. The `cache_lag_monitor` job watches `last_sync_at` to detect stalled ingestors.

- **Backfill** — A historical date-range fill triggered manually with `illumio-ops cache backfill --source {events|traffic} --since YYYY-MM-DD [--until YYYY-MM-DD]`. Writes directly into `pce_events` / `pce_traffic_flows_raw`, bypassing the watermark. Useful for populating the cache after enabling it on an existing deployment. See [PCE Cache §Backfill](./PCE_Cache.md#backfill).

- **DLQ (Dead Letter Queue)** — The `dead_letter` table in the cache. Holds SIEM dispatches that failed every retry attempt, quarantined for 30 days so an operator can inspect failures without blocking the live queue.

- **SIEM dispatch** — The `siem_dispatch` outbound queue table. The SIEM forwarder reads from this queue, sends events off-box to syslog/Splunk/Elastic, and removes successfully delivered rows; persistent failures are moved to the DLQ.

- **Draft policy alignment (R-series)** — The R01–R05 detection rules in [Security Rules Reference](./Security_Rules_Reference.md), implemented by `compute_draft`. They read Draft-state rules from the PCE and flag gaps (e.g. workloads still in Idle / Visibility Only in production) before changes reach Active state.

- **Multi-PCE Profile** — A configuration slot in `config/config.json` that holds a complete set of credentials and endpoint settings for one PCE. The user can switch the active profile (e.g. lab vs. production) without re-entering credentials, so a single illumio-ops install can target several PCEs.

- **`must_change_password` / `_initial_password`** — Web GUI auth force-change mechanism. When an admin (re)provisions a user, `_initial_password` carries the temporary password and `must_change_password` is set; on first login the user is forced through the password-reset flow before any other action is allowed.

## See also

- [Architecture](./Architecture.md) Background — full Illumio platform context (PCE/VEN, labels, workload types, policy lifecycle, enforcement modes)
- [Security Rules Reference](./Security_Rules_Reference.md) §Policy Decision Fields — full value tables for `policy_decision` and `draft_policy_decision`
- [PCE Cache](./PCE_Cache.md) — schema, retention, backfill, and operator CLI
