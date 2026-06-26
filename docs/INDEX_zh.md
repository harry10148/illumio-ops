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

> 🌐 [English](INDEX.md) | **[繁體中文](INDEX_zh.md)**
> 📍 您在這裡 — 文件總覽入口。
> 🔍 最後驗證 **2026-06-26**

# illumio-ops 文件

請先閱讀專案 **[README](../README.md)**（**[繁體中文](../README_zh.md)**），了解總覽、架構圖、快速開始與安全注意事項。
下方兩份核心手冊提供更深入的內容；其後為參考（Reference）與貢獻指引（Contributing）。

## 核心文件

| 文件 | 內容 |
|------|------|
| **[操作手冊（Operations Manual）](operations-manual_zh.md)** | 安裝、部署（systemd / NSSM / 離線 bundle）、設定、執行與維運 illumio-ops 的完整流程。繁體中文。 |
| **[事件規則說明（Event Rules）](event-rules_zh.md)** | 即時監控規則引擎、B/L/R 報表規則引擎（含 R01–R05），以及事件管線——逐條對照原始碼。繁體中文。 |
| **[快速上手（Getting Started）](getting-started.md)** / **[（English）](getting-started_zh.md)** | 首次安裝、首次連線與升級。 |

## 參考（Reference）

| 主題 | EN | 中文 |
|------|----|----|
| CLI | [reference/cli.md](reference/cli.md) | [reference/cli_zh.md](reference/cli_zh.md) |
| 詞彙表 | [reference/glossary.md](reference/glossary.md) | [reference/glossary_zh.md](reference/glossary_zh.md) |
| REST API | [reference/rest-api.md](reference/rest-api.md) | [reference/rest-api_zh.md](reference/rest-api_zh.md) |

## 貢獻指引（Contributing）

| 主題 | EN | 中文 |
|------|----|----|
| 開發環境設定 | [contributing/dev-setup.md](contributing/dev-setup.md) | [contributing/dev-setup_zh.md](contributing/dev-setup_zh.md) |
| i18n 工作流程 | [contributing/i18n-workflow.md](contributing/i18n-workflow.md) | [contributing/i18n-workflow_zh.md](contributing/i18n-workflow_zh.md) |
| 發佈流程 | [contributing/release-process.md](contributing/release-process.md) | [contributing/release-process_zh.md](contributing/release-process_zh.md) |

## 稽核與歷史

- **最新稽核：** `reports/audit/2026-06-26-static-findings.md` — 2026-06-26 靜態審查。本分支已解決全部 11 項 HIGH 嚴重度發現。
- **歷史／已被取代的文件** — 先前的 `user-guide/` 與 `architecture/`、UX 審查、2026-05-22 安全稽核，以及 session handoff——皆已歸檔於 **`docs/_archive/`**。

## 文件保鮮機制

每份文件均包含 `last_verified` / `verified_against` frontmatter。執行 `python3 scripts/docs_check.py --all`
可稽核雙語完整性、freshness、frontmatter 與內部連結。兩份核心手冊刻意採 **繁體中文優先**（無英文對照），
因此 `--bilingual` 會依設計將其標示出來。
