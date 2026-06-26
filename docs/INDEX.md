---
title: illumio-ops Documentation
audience: [operator, developer, api, security]
last_verified: 2026-06-26
verified_against:
  - README.md
  - docs/operations-manual_zh.md
  - docs/event-rules_zh.md
  - reports/audit/2026-06-26-static-findings.md
---

> 🌐 **[English](INDEX.md)** | **[繁體中文](INDEX_zh.md)**
> 📍 You are here — the documentation hub.
> 🔍 Last verified **2026-06-26**

# illumio-ops Documentation

Start with the project **[README](../README.md)** (**[繁體中文](../README_zh.md)**) for the overview,
architecture diagram, quick start, and security notes. The two core manuals below go deeper;
reference and contributing material follows.

## Core docs

| Doc | What it covers |
|-----|----------------|
| **[操作手冊 — Operations Manual](operations-manual_zh.md)** | Install, deploy (systemd / NSSM / offline bundle), configure, run, and operate illumio-ops end to end. 繁體中文. |
| **[事件規則說明 — Event Rules](event-rules_zh.md)** | The real-time monitor rule engine, the B/L/R report rule engine (R01–R05 included), and the event pipeline — audited line-by-line against the source. 繁體中文. |
| **[Getting Started](getting-started.md)** / **[（繁體中文）](getting-started_zh.md)** | First install, first connection, and upgrade. |

## Reference

| Topic | EN | 中文 |
|-------|----|----|
| CLI | [reference/cli.md](reference/cli.md) | [reference/cli_zh.md](reference/cli_zh.md) |
| Glossary | [reference/glossary.md](reference/glossary.md) | [reference/glossary_zh.md](reference/glossary_zh.md) |
| REST API | [reference/rest-api.md](reference/rest-api.md) | [reference/rest-api_zh.md](reference/rest-api_zh.md) |

## Contributing

| Topic | EN | 中文 |
|-------|----|----|
| Dev Setup | [contributing/dev-setup.md](contributing/dev-setup.md) | [contributing/dev-setup_zh.md](contributing/dev-setup_zh.md) |
| i18n Workflow | [contributing/i18n-workflow.md](contributing/i18n-workflow.md) | [contributing/i18n-workflow_zh.md](contributing/i18n-workflow_zh.md) |
| Release Process | [contributing/release-process.md](contributing/release-process.md) | [contributing/release-process_zh.md](contributing/release-process_zh.md) |

## Audit & history

- **Latest audit:** `reports/audit/2026-06-26-static-findings.md` — the 2026-06-26 static review. All 11 HIGH-severity findings were resolved on this branch.
- **Historical / superseded docs** — the previous `user-guide/` and `architecture/` sets, the UX reviews, the 2026-05-22 security audit, and the session handoffs — are archived under **`docs/_archive/`**.

## How docs are kept fresh

Each doc carries `last_verified` / `verified_against` frontmatter. Run `python3 scripts/docs_check.py --all`
to audit bilingual coverage, freshness, frontmatter, and internal links. The two core manuals are
intentionally **繁體中文-first** (no English sibling), so `--bilingual` flags them by design.
