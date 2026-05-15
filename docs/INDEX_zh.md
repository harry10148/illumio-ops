---
title: illumio-ops Documentation
audience: [operator, developer, api, security]
last_verified: 2026-05-15
verified_against:
  - docs/superpowers/specs/2026-05-15-docs-refactor-design.md
  - commit a9ae661
related_docs:
  - getting-started.md
  - reference/glossary.md
---

> 🌐 [English](INDEX.md) | **[繁體中文](INDEX_zh.md)**
> 📍 您在這裡。
> 🔍 最後驗證 **2026-05-15** — 詳見 frontmatter

# illumio-ops 文件

## 從這裡開始

### 👤 維運人員 — 使用儀表板 / CLI 監控 PCE
1. [快速上手](getting-started.md)
2. [儀表板](user-guide/dashboard.md)
3. [報告](user-guide/reports.md)
4. [警示與隔離](user-guide/alerts-and-quarantine.md)

### 🧰 開發者 / 貢獻者
1. [開發環境設定](contributing/dev-setup.md)
2. [架構總覽](architecture/overview.md)
3. [i18n 介面契約](architecture/i18n-contract.md)

### 🔌 API 使用者 / 整合方
1. [REST API](reference/rest-api.md)
2. [SIEM 整合](user-guide/siem-integration.md)
3. [SIEM 管線（事件結構）](architecture/siem-pipeline.md)

### 🛡️ 資安 / 合規稽核人員
1. [TLS 與憑證](user-guide/tls-and-certificates.md)
2. [SIEM 整合（稽核轉送）](user-guide/siem-integration.md)
3. [多 PCE](user-guide/multi-pce.md)
4. [架構總覽 — 資料流](architecture/overview.md#data-flow)

## 完整文件對照表

<!-- BEGIN:doc-map -->
| 分區 | 主題 | EN | 中文 |
|------|------|----|----|
| 索引 | 進入點 | [INDEX.md](INDEX.md) | [INDEX_zh.md](INDEX_zh.md) |
| 上手 | 安裝 + 首次執行 + 升級 | [getting-started.md](getting-started.md) | [getting-started_zh.md](getting-started_zh.md) |
<!-- END:doc-map -->

> _後續每批（B1 → B2 → B3）完成時將逐步補充列。_

## 文件保鮮機制

每份文件均包含 `last_verified` 與 `verified_against` frontmatter。執行 `python scripts/docs_check.py --all` 可稽核：
- 雙語完整性（每份 EN `.md` 是否有對應的 `_zh.md`）
- `last_verified` 距今 ≤ 30 天
- 無損壞的內部連結
- frontmatter 完整性

---
## 相關文件
- [快速上手](getting-started.md) — 首次安裝與連線
- [術語表](reference/glossary.md) — Illumio 術語說明（B2 新增）
