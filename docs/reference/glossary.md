---
title: Glossary
audience: [operator, developer, api, security]
last_verified: 2026-06-26
verified_against:
  - src/i18n/data/zh_explicit.json
  - docs/Glossary.md (legacy, audited)
  - commit 838ee40
related_docs:
  - ../INDEX.md
  - i18n-contract.md
  - ../user-guide/dashboard.md
  - ../contributing/i18n-workflow.md
---

> 🌐 **[English](glossary.md)** | **[繁體中文](glossary_zh.md)**
> 📍 [INDEX](../INDEX.md) › Reference › Glossary
> 🔍 Last verified **2026-05-15** against commit `838ee40` — see frontmatter for sources

# Glossary

This page is a quick reference for newcomers. Each entry is self-contained: read just one entry to get the gist, then follow the cross-reference for the full picture.

---

## Illumio core terms

**Application Group** — A logical grouping of workloads that share the same `app` label value, representing one business service (e.g. `HRM`, `Payments`). Rulesets are often scoped to an Application Group.

**Enforcement Boundary** — A scoped deny statement separate from regular rules. Defines a "blast wall" between groups of workloads; in Selective enforcement mode the VEN blocks only flows that violate a boundary.

**Enforcement Mode** — The operating state of a VEN: *Idle* (no enforcement, but the VEN still reports network traffic ~every 10 min and OS compatibility ~every 4 h), *Visibility Only* (passive monitoring only), *Selective* (enforcement applies only to the services/ports covered by enforcement boundaries, on inbound traffic only), or *Full* (default-deny / zero-trust, allow-list only). Full is the production target for microsegmentation. Unmanaged workloads and workloads managed via NENs (Network Enforcement Nodes) cannot use Selective enforcement.

**Environment** — The `env` label dimension, recording the SDLC stage of a workload (e.g. `production`, `staging`, `dev`). Used in rulesets to scope rules to a lifecycle stage.

**Heartbeat** — The VEN's periodic check-in with the PCE (every 5 minutes for status, every 10 minutes for summarized flow logs). Also used as a fallback channel for policy updates.

**IP List** — A named set of IP addresses or CIDR ranges, used as a provider or consumer in rules to express traffic to/from non-workload endpoints (e.g. external partners, internet egress).

**Label** — Key-value metadata attached to workloads. Illumio uses four dimensions: `role`, `app`, `env`, `loc`. Rules target labels rather than IPs, so policy follows workloads automatically.

**Label Group** — A named collection of label values from the same dimension, used to write one rule that applies to several environments or applications without duplication.

**Location** — The `loc` label dimension, recording the geography or infrastructure zone of a workload (e.g. `aws-east1`, `on-prem-nyc`).

**Pairing Profile** — A PCE object that bundles the configuration (labels, enforcement mode, visibility level) applied to a workload when a VEN is installed and paired. Generates a one-time pairing key.

**PCE (Policy Compute Engine)** — The server-side brain of the Illumio platform. Computes per-workload security policy and pushes it to every paired VEN. Internally spans four service tiers: Front End, Processing, Service/Caching, Persistence.

**Policy Lifecycle** — The three-stage pipeline every policy change passes through: *Draft* (invisible to VEN, in-progress edit), *Pending* (batched for review and impact analysis), *Active* (provisioned and pushed to VENs).

**Rule** — A single allow/deny statement inside a Ruleset, expressed as `provider × consumer × service`. Both provider and consumer are usually label selectors.

**Ruleset** — A scoped container that groups related security Rules and applies them to a set of workloads (typically defined by `app`+`env` labels). The unit of write/provision in the policy lifecycle.

**Scope** — The label selector attached to a Ruleset or Enforcement Boundary that determines which workloads it governs. A scope of `app=HRM, env=production` applies the ruleset only to production HRM workloads.

**Service** — A reusable definition of one or more `protocol+port` combinations (e.g. `tcp/443, tcp/80`) referenced by rules instead of inlining ports.

**Service Account** — A non-human PCE identity used by automated tools (scripts, CI/CD pipelines) to authenticate to the PCE API via an API key, without tying access to a user account.

**VEN (Virtual Enforcement Node)** — A lightweight agent installed on each managed workload. Programs the host's native firewall (`iptables`/`nftables`, WFP), collects flow telemetry, and applies policy received from the PCE over TLS on TCP 8443/8444.

**Visibility Level** — Under Full enforcement, controls how much traffic the VEN logs: *Off*, *Blocked*, *Blocked + Allowed*, or *Enhanced Data Collection*.

**Workload** — A managed compute resource tracked by the PCE. Three subtypes: *Managed* (VEN paired, live telemetry), *Unmanaged* (labelled IP-only, no VEN), *Container* (Kubernetes/OpenShift pod via Kubelink).

---

## illumio-ops-specific terms

**Action Matrix** — The configuration table in `config/config.json` that maps alert rule severities and categories to notification channels (Email, LINE, Webhook, Telegram, Teams). Determines how each alert fires and where it is routed.

**Alert Rule** — A named detection definition in illumio-ops that watches PCE events or metrics for a pattern. When triggered, the alert engine evaluates the Action Matrix and dispatches notifications.

**Backfill** — A historical date-range fill triggered with `illumio-ops cache backfill`. Writes directly into `pce_events` / `pce_traffic_flows_raw`, bypassing the watermark. Used to populate the cache after first enable.

**DLQ (Dead Letter Queue)** — The `dead_letter` table in the PCE Cache. Holds SIEM dispatches that exhausted all retries, quarantined for 30 days for operator inspection without blocking the live queue.

**Draft Policy Alignment (R-series)** — The R01–R05 detection rules implemented by `compute_draft`. Read Draft-state rules from the PCE and flag gaps (e.g. workloads in Idle/Visibility Only in production) before provisioning.

**Hub Apps** — The set of first-party feature modules bundled in the illumio-ops web UI (Dashboard, Reports, Alerts, Settings, SIEM). Each Hub App is a self-contained Flask Blueprint.

**Ingestor** — A background poller (one per data source: `events`, `traffic`) that pulls new rows from the PCE API into the PCE Cache on a fixed schedule, subject to a shared token-bucket rate limiter.

**Multi-PCE Profile** — A named configuration slot in `config/config.json` holding credentials and endpoint settings for one PCE. Allows a single illumio-ops install to target multiple PCEs.

**PCE Cache** — A local SQLite (WAL) database at `data/pce_cache.sqlite` that stores a rolling window of PCE audit events and traffic flows, acting as a shared buffer for the SIEM forwarder, report modules, and alert loop.

**Rule Scheduler** — The APScheduler-based job runner inside illumio-ops that executes ingestors, alert evaluations, SIEM dispatch ticks, and report generation on configured intervals.

**SIEM Dispatch** — The `siem_dispatch` outbound queue table. The SIEM forwarder reads from this queue, sends events to syslog/Splunk/Elastic, and removes successfully delivered rows; failures are moved to the DLQ.

**Watermark** — A per-ingestor cursor in the `ingestion_watermarks` table recording the last successfully fetched timestamp. Survives restarts so polling resumes without gaps or duplicates.

---

## i18n terms

**`desc_key`** — The i18n key convention for a field's human-readable description string. Used in zh_explicit.json entries such as `alert_field_desc` to provide a translated tooltip or help text.

**`label_key`** — The i18n key convention for a field's display label in the UI (e.g. `alert_field_action` → `動作`). Distinguished from `name_key` (entity name) and `desc_key` (description).

**`name_key`** — The i18n key convention for an entity's display name. Separate from `label_key` (form label) and `desc_key` (description), allowing each surface to be translated independently.

**`rec_key`** — The i18n key convention for a recommendation string shown alongside an alert or validation error (e.g. `alert_rec_agent_offline_check`). Short, actionable, operator-facing.

**`t()` function** — The Python runtime translation helper in illumio-ops. Resolves an i18n key against the active locale's JSON file, falling back to `zh_explicit.json` if the key is not found in the base locale.

**zh_explicit** — The file `src/i18n/data/zh_explicit.json`. The primary source of approved zh_TW translations for all Illumio-domain and illumio-ops UI strings. Overrides the base `src/i18n_zh_TW.json` catalog for product-specific terminology.

**zh_explicit override** — The lookup priority rule: a key found in `zh_explicit.json` always wins over the same key in the base `src/i18n_zh_TW.json`. Ensures approved, product-accurate translations for alert messages, field labels, and recommendation strings.

---

## Compliance / audit terms

**Audit Event** — A structured log entry emitted by the PCE for every create/update/delete/auth action on a policy object or user session. Stored in `pce_events` and forwarded to SIEM as CEF or JSON Lines.

**Audit Log** — The full historical stream of Audit Events exported from the PCE via `/api/v2/auditable_events`. illumio-ops polls this endpoint to populate the PCE Cache and drive alert evaluation.

**Event Type** — The PCE-assigned category string on each Audit Event (e.g. `workload.create`, `ruleset.update`, `user.sign_in`). Used as a filter dimension in alert rules and SIEM queries.

**SIEM Forwarding** — The pipeline that delivers PCE events and traffic flows out of illumio-ops to an external security platform (Splunk, Elastic, QRadar). Supports CEF-over-syslog (UDP/TCP/TLS) and Splunk HEC (HTTPS).

---

## Acronyms

**CEF** — Common Event Format. A syslog-compatible structured log standard used by illumio-ops to forward audit events to SIEM platforms over UDP/TCP/TLS.

**CSR** — Certificate Signing Request. A file submitted to a CA to obtain a TLS certificate, used when configuring TLS transport for SIEM forwarding or PCE API mutual TLS.

**CSV** — Comma-Separated Values. Export format produced by illumio-ops report modules for workload inventory, traffic flow summaries, and policy gap reports.

**HEC** — HTTP Event Collector. The Splunk HTTPS ingestion endpoint supported by the illumio-ops SIEM forwarder (`transport: hec`).

**NSSM** — Non-Sucking Service Manager. The Windows service wrapper used to run illumio-ops as a background service on Windows hosts.

**PCE** — Policy Compute Engine. See [Illumio core terms → PCE](#illumio-core-terms).

**REST** — Representational State Transfer. The architectural style of the Illumio PCE API. illumio-ops uses the PCE REST API (v2) for all data ingestion and policy reads.

**RFC 5424** — The syslog protocol standard defining message format (PRI, VERSION, TIMESTAMP, HOSTNAME, APP-NAME, MSGID, STRUCTURED-DATA). illumio-ops emits RFC 5424-compliant headers on CEF syslog messages.

**TLS** — Transport Layer Security. Used to encrypt PCE API traffic (TCP 8443/8444) and optionally SIEM syslog forwarding when `transport: tls` is configured.

**VEN** — Virtual Enforcement Node. See [Illumio core terms → VEN](#illumio-core-terms).

---

## Related Docs

- [INDEX](../INDEX.md) — full doc map
- [i18n Contract](i18n-contract.md) — how terms get translated at runtime
- [Operations Manual](../operations-manual_zh.md) — Web GUI walkthrough (§3) where many of these terms surface (繁體中文)
- [i18n Workflow](../contributing/i18n-workflow.md) — adding new translatable terms
