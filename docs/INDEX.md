---
title: illumio-ops Documentation
audience: [operator, developer, api, security]
last_verified: 2026-05-15
verified_against:
  - docs/superpowers/specs/2026-05-15-docs-refactor-design.md
  - commit 05196a2
related_docs:
  - getting-started.md
  - reference/glossary.md
---

> 🌐 **[English](INDEX.md)** | **[繁體中文](INDEX_zh.md)**
> 📍 You are here.
> 🔍 Last verified **2026-05-15** — see frontmatter for sources

# illumio-ops Documentation

## Where to start

### 👤 Operator — using the dashboard / CLI to monitor PCE
1. [Getting Started](getting-started.md)
2. [Dashboard](user-guide/dashboard.md)
3. [Reports](user-guide/reports.md)
4. [Alerts & Quarantine](user-guide/alerts-and-quarantine.md)

### 🧰 Developer / Contributor
1. [Dev Setup](contributing/dev-setup.md)
2. [Architecture Overview](architecture/overview.md)
3. [i18n Contract](architecture/i18n-contract.md)

### 🔌 API user / Integrator
1. [REST API](reference/rest-api.md)
2. [SIEM Integration](user-guide/siem-integration.md)
3. [SIEM Pipeline (event schema)](architecture/siem-pipeline.md)

### 🛡️ Security / Compliance Auditor
1. [TLS & Certificates](user-guide/tls-and-certificates.md)
2. [SIEM Integration (audit forwarding)](user-guide/siem-integration.md)
3. [Multi-PCE](user-guide/multi-pce.md)
4. [Architecture Overview — Data flow](architecture/overview.md#data-flow)

## Full document map

<!-- BEGIN:doc-map -->
| Area | Topic | EN | 中文 |
|------|-------|----|----|
| Index | Entry point | [INDEX.md](INDEX.md) | [INDEX_zh.md](INDEX_zh.md) |
| Onboarding | Install + first run + upgrade | [getting-started.md](getting-started.md) | [getting-started_zh.md](getting-started_zh.md) |
| User Guide | Dashboard | [user-guide/dashboard.md](user-guide/dashboard.md) | [user-guide/dashboard_zh.md](user-guide/dashboard_zh.md) |
| User Guide | Reports | [user-guide/reports.md](user-guide/reports.md) | [user-guide/reports_zh.md](user-guide/reports_zh.md) |
| User Guide | Alerts & Quarantine | [user-guide/alerts-and-quarantine.md](user-guide/alerts-and-quarantine.md) | [user-guide/alerts-and-quarantine_zh.md](user-guide/alerts-and-quarantine_zh.md) |
| User Guide | Rule Scheduler | [user-guide/rule-scheduler.md](user-guide/rule-scheduler.md) | [user-guide/rule-scheduler_zh.md](user-guide/rule-scheduler_zh.md) |
| User Guide | SIEM Integration | [user-guide/siem-integration.md](user-guide/siem-integration.md) | [user-guide/siem-integration_zh.md](user-guide/siem-integration_zh.md) |
| User Guide | Multi-PCE | [user-guide/multi-pce.md](user-guide/multi-pce.md) | [user-guide/multi-pce_zh.md](user-guide/multi-pce_zh.md) |
| User Guide | TLS & Certificates | [user-guide/tls-and-certificates.md](user-guide/tls-and-certificates.md) | [user-guide/tls-and-certificates_zh.md](user-guide/tls-and-certificates_zh.md) |
| User Guide | Settings & PCE Cache | [user-guide/settings-and-pce-cache.md](user-guide/settings-and-pce-cache.md) | [user-guide/settings-and-pce-cache_zh.md](user-guide/settings-and-pce-cache_zh.md) |
| User Guide | Troubleshooting | [user-guide/troubleshooting.md](user-guide/troubleshooting.md) | [user-guide/troubleshooting_zh.md](user-guide/troubleshooting_zh.md) |
| Reference | Glossary | [reference/glossary.md](reference/glossary.md) | [reference/glossary_zh.md](reference/glossary_zh.md) |
| Reference | CLI | [reference/cli.md](reference/cli.md) | [reference/cli_zh.md](reference/cli_zh.md) |
| Reference | REST API | [reference/rest-api.md](reference/rest-api.md) | [reference/rest-api_zh.md](reference/rest-api_zh.md) |
| Architecture | Overview | [architecture/overview.md](architecture/overview.md) | [architecture/overview_zh.md](architecture/overview_zh.md) |
| Architecture | Report Engine | [architecture/report-engine.md](architecture/report-engine.md) | [architecture/report-engine_zh.md](architecture/report-engine_zh.md) |
| Architecture | SIEM Pipeline | [architecture/siem-pipeline.md](architecture/siem-pipeline.md) | [architecture/siem-pipeline_zh.md](architecture/siem-pipeline_zh.md) |
| Architecture | i18n Contract | [architecture/i18n-contract.md](architecture/i18n-contract.md) | [architecture/i18n-contract_zh.md](architecture/i18n-contract_zh.md) |
<!-- END:doc-map -->

> _Additional rows are appended at the end of each batch (B1 → B2 → B3)._

## How docs are kept fresh

Every doc carries `last_verified` and `verified_against` frontmatter. Run `python scripts/docs_check.py --all` to audit:
- bilingual coverage (every EN `.md` has a `_zh.md` sibling)
- `last_verified` ≤ 30 days
- no broken internal links
- frontmatter completeness

---
## Related Docs
- [Getting Started](getting-started.md) — first install and connection
- [Glossary](reference/glossary.md) — Illumio terminology (added in B2)
