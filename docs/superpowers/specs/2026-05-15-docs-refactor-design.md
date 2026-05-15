# Documentation Refactor — Design Spec

**Status**: Brainstorming complete, awaiting user spec review
**Date**: 2026-05-15
**Author**: Harry + Claude (brainstorming session)
**Supersedes**: `docs/superpowers/specs/2026-04-28-documentation-rebuild-design.md` (17 天前的舊稿，本次重構不沿用)
**Next step**: `writing-plans` skill → implementation plan (B1–B4)

---

## Goal

全面重構 illumio-ops 專案文件。現有 14 對雙語文件（`docs/*.md` + `*_zh.md`）部分過時，未反映近期重大架構變動（i18n R1–R4 重構、SIEM destination UX 改版、ReportLab 移除、TLS/CSR workflow、Header Operations 下拉、Phase 1.2/1.4/2.1/2.2 UI 重構）。舊內容**僅作為參考、不視為可信來源**。

交付狀態：
- 22 對雙語檔（44 個 `.md`）— EN 為 SoT、zh_TW 同步翻譯
- 5 層交叉連結（語言切換、Breadcrumb、Related Docs、inline、INDEX 角色入口）
- 每頁 `last_verified` + `verified_against` frontmatter（防再過時）
- 13 對舊文（26 個 `.md`）`git rm`；README 對保留檔名縮版改寫；稽核軌跡保留於 `docs/_meta/migration-audit.json`

## Architecture (Document System)

| 面向 | 設計 |
|---|---|
| 資訊架構 | 完全重新設計，依 `src/` 模組對應，非延用舊文題目 |
| 雙語策略 | 平鋪 `*_zh.md` siblings；EN-SoT；zh_TW 同步翻譯 |
| 交叉連結 | 5 層機制（見 §4） |
| 防過時機制 | YAML frontmatter `last_verified` / `verified_against` + `scripts/docs_check.py` 稽核腳本 |
| 舊文處置 | 全 `git rm`，靠 Git 歷史 + `migration-audit.json` 反查 |
| 工具鏈 | 純 GitHub Markdown，不引入 MkDocs / Sphinx |

## Tech Stack

- Markdown (GitHub-flavored, 直接於 GitHub render)
- YAML frontmatter（per-file metadata）
- Python 稽核腳本（stdlib only；可掛 `requirements-dev.txt` 已有的依賴）
- 不新增 build / publish 工具鏈

## Sub-skill Requirement

本 spec 由 `brainstorming` skill 產出。後續：

1. **下一步**：`writing-plans` skill 將本 spec 拆成可執行的 implementation plan（B1–B4 各一份子計畫）。
2. **實作執行**：B1–B4 四批彼此獨立，建議透過 `subagent-driven-development` skill 各派一個 subagent 並行處理；每批內單篇文件之間可序列。
3. **驗收**：每批完成後使用 `verification-before-completion` skill 跑 §8 成功指標清單。

---

## 1. Audience（4 種讀者全部支援）

| Profile | Primary entry |
|---|---|
| 👤 Operator | `getting-started.md` → `user-guide/*` |
| 🧰 Developer / Contributor | `contributing/dev-setup.md` → `architecture/*` |
| 🔌 API 使用者 / 整合方 | `reference/rest-api.md` → `user-guide/siem-integration.md` |
| 🛡️ Security / Compliance Auditor | `user-guide/tls-and-certificates.md` → 橫切章節彙整 |

Security/Auditor 不獨立目錄，由橫切章節（TLS、SIEM audit forwarding、Multi-PCE、architecture/overview#data-flow）服務；`INDEX.md` 為其提供導覽路徑。

## 2. Information Architecture（新 `docs/` 樹）

```text
docs/
  INDEX.md / INDEX_zh.md                 ← 唯一進入點、4 種讀者入口、doc-map
  getting-started.md / _zh.md            ← 安裝 + 首次連線 + 升級（取代 Installation + UPGRADE）

  user-guide/                            ← Operator 主場（9 對）
    dashboard.md / _zh.md
    reports.md / _zh.md                  ← 取代 Report_Modules + Security_Rules_Reference 使用者層
    alerts-and-quarantine.md / _zh.md
    rule-scheduler.md / _zh.md
    siem-integration.md / _zh.md
    multi-pce.md / _zh.md
    tls-and-certificates.md / _zh.md     ← 含 CSR generation + signed cert import
    settings-and-pce-cache.md / _zh.md   ← 取代 PCE_Cache + User_Manual 設定章節
    troubleshooting.md / _zh.md

  reference/                             ← API user / Integrator 主場（3 對）
    cli.md / _zh.md                      ← src/cli (30 檔) + alias map
    rest-api.md / _zh.md                 ← src/api (4 檔) endpoint 文件
    glossary.md / _zh.md

  architecture/                          ← Developer 主場（4 對）
    overview.md / _zh.md                 ← src/ 全模組地圖、Flask 結構、資料流
    report-engine.md / _zh.md            ← src/report (71 檔) 內部
    siem-pipeline.md / _zh.md            ← src/siem formatters/transports + event schema
    i18n-contract.md / _zh.md            ← src/i18n + zh_explicit.json 契約

  contributing/                          ← Developer/Contributor 主場（3 對）
    dev-setup.md / _zh.md                ← venv、執行、測試、lint
    i18n-workflow.md / _zh.md            ← 新增/翻譯 key 流程
    release-process.md / _zh.md          ← release + 服務升級 SOP

  _meta/
    migration-audit.json                 ← 舊 → 新文 claim 稽核軌跡
    glossary-terms.json                  ← 預留鉤子（本次不啟用名詞自動連結）
```

### 2.1 與 `src/` 模組的覆蓋對應

| `src/` 子模組 | py 檔數 | 主要對應到 |
|---|---|---|
| `report` | 71 | `user-guide/reports.md` + `architecture/report-engine.md` |
| `cli` | 30 | `reference/cli.md` |
| `siem` | 19 | `user-guide/siem-integration.md` + `architecture/siem-pipeline.md` |
| `pce_cache` | 15 | `user-guide/settings-and-pce-cache.md` |
| `gui` | 13 | `user-guide/dashboard.md` + `architecture/overview.md` |
| `events` | 8 | `user-guide/alerts-and-quarantine.md` + `architecture/overview.md` |
| `alerts` | 5 | `user-guide/alerts-and-quarantine.md` |
| `api` | 4 | `reference/rest-api.md` |
| `scheduler` | 2 | `user-guide/rule-scheduler.md` |
| `i18n` | 2 | `architecture/i18n-contract.md` + `contributing/i18n-workflow.md` |
| `settings` | 1 | `user-guide/settings-and-pce-cache.md` |

→ 11 / 11 模組 100% 涵蓋。

## 3. Page Template

### 3.1 EN 版範例

```markdown
---
title: Rule Scheduler
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/gui/routes/rule_scheduler.py
  - src/rule_scheduler_cli.py
  - illumio-ops rule-scheduler --help  (commit a164c97)
related_docs:
  - user-guide/alerts-and-quarantine.md
  - architecture/i18n-contract.md
  - reference/cli.md
---

> 🌐 **[English](rule-scheduler.md)** | **[繁體中文](rule-scheduler_zh.md)**
> 📍 [INDEX](../INDEX.md) › User Guide › Rule Scheduler
> 🔍 Last verified **2026-05-15** against commit `a164c97` — see frontmatter for sources

# Rule Scheduler

<正文>

---
## Related Docs
- [Alerts & Quarantine](alerts-and-quarantine.md) — 排程觸發的後續動作
- [i18n Contract](../architecture/i18n-contract.md) — 排程描述為何固定英文
- [CLI Reference](../reference/cli.md) — `illumio-ops rule-scheduler` 子命令
```

### 3.2 zh_TW 版差異
- 語言切換指向 `*.md`（去 `_zh` 後綴）
- Breadcrumb / Related Docs 描述全中文
- frontmatter 與 EN 版完全一致（共享 `last_verified` / `verified_against`）
- EN/zh_TW 段落結構 1:1，章節數與順序對等

## 4. 5-Layer Cross-Link Mechanism

| 層 | 位置 | 用途 | 密度 | 強制 |
|---|---|---|---|---|
| L1 語言切換 | 頁首第 1 行 | EN ↔ zh_TW 對等檔 | 1 | ✅ |
| L2 Breadcrumb | 頁首第 2 行 | 退回 INDEX 與所屬分區 | 2-3 | ✅ |
| L3 Related Docs | 頁尾 section | 手挑同主題的同類/對位文件 | 3-5 | ✅ |
| L4 內文 inline 連結 | 段落中 | 名詞首次出現連 Glossary、模組首次提到連 architecture | 視需要 | ⭐ |
| L5 INDEX 角色入口 | `INDEX.md` 頂部 | 4 種讀者「從這裡開始」清單 | 每讀者 3-4 | ✅ |

## 5. `INDEX.md` Structure

```markdown
# illumio-ops Documentation

> 🌐 [English](INDEX.md) | [繁體中文](INDEX_zh.md)

## Where to start
### 👤 Operator     1. getting-started → 2. dashboard → 3. reports → 4. alerts-and-quarantine
### 🧰 Developer   1. dev-setup → 2. architecture/overview → 3. i18n-contract
### 🔌 Integrator  1. reference/rest-api → 2. siem-integration → 3. siem-pipeline (event schema)
### 🛡️ Auditor    1. tls-and-certificates → 2. siem-integration (audit) → 3. multi-pce → 4. architecture/overview#data-flow

## Full document map
<!-- BEGIN:doc-map -->
| Area | Topic | EN | 中文 |
| ... 全 22 對列表 ... |
<!-- END:doc-map -->

## How docs are kept fresh
- 每頁 frontmatter `last_verified` / `verified_against`
- `scripts/docs_check.py` 可掃 90 天未驗證 / 死連結 / 雙語完整性
```

## 6. Legacy Migration

### 6.1 舊文 → 新文映射

| 舊檔 | 新位置 | 處理 |
|---|---|---|
| `README.md` | 縮版 `README.md` + `docs/INDEX.md` | 縮為 ≤ 100 行入口，doc-map 移入 INDEX |
| `docs/Installation.md` | `docs/getting-started.md` | 驗證後合併 |
| `docs/UPGRADE.md` | `docs/getting-started.md` "Upgrade" 章節 | 合併 |
| `docs/User_Manual.md` (44k+) | 拆至 `user-guide/*` | 拆分 |
| `docs/Report_Modules.md` (19k+) | `user-guide/reports.md` + `architecture/report-engine.md` | 拆分 |
| `docs/Security_Rules_Reference.md` (46k+) | `user-guide/reports.md` § Security rules + `reference/cli.md` | 拆分 |
| `docs/SIEM_Integration.md` | `user-guide/siem-integration.md` + `architecture/siem-pipeline.md` | 拆分 |
| `docs/Architecture.md` (55k+) | `architecture/overview.md` | **完全重寫**（最不可信） |
| `docs/PCE_Cache.md` | `user-guide/settings-and-pce-cache.md` | 合併 |
| `docs/API_Cookbook.md` (40k+) | `reference/rest-api.md` + `user-guide/*` 範例 | 拆分 |
| `docs/Glossary.md` | `reference/glossary.md` | 移檔 + 名詞重核 |
| `docs/Troubleshooting.md` | `user-guide/troubleshooting.md` | 驗證後重寫 |
| `docs/cli-command-map.md` | `reference/cli.md` alias 章節 | 合併 |
| `docs/fonts-vendoring.md` | `architecture/overview.md` 附錄 | 合併 |

### 6.2 `migration-audit.json` schema

```json
[
  {
    "source": "docs/Architecture.md",
    "target": "docs/architecture/overview.md",
    "audited_at": "2026-05-15",
    "claims": [
      {
        "claim": "Flask app initialises ConfigManager from /etc/illumio-ops/config.json",
        "verdict": "stale",
        "actual_source": "src/settings/manager.py reads ./config/, not /etc",
        "action": "rewrite"
      },
      {
        "claim": "i18n 用 gettext .po 檔",
        "verdict": "obsolete",
        "actual_source": "src/i18n/data/*.json — 自製字典、非 gettext",
        "action": "discard"
      }
    ]
  }
]
```

Verdict 列舉：`verified` / `stale` / `unknown` / `obsolete`
Action 列舉：`import` / `rewrite` / `flag-todo` / `discard`

### 6.3 單篇重寫 SOP

```
1. 讀 src/<對應模組>/                 → 列入 verified_against
2. 跑對應 CLI/API：illumio-ops <cmd> --help 或 curl /api/...
3. 拷貝頁面模板 (含 frontmatter + 5 層連結結構)
4. 寫 EN 正文 (SoT)
5. 翻譯 zh_TW (查 reference/glossary.md 與 src/i18n/data/zh_explicit.json)
6. 補 Related Docs (手挑 3-5 條)
7. 填 frontmatter:
     last_verified: <today>
     verified_against: [<src 路徑>, <CLI/API 證據>, commit SHA]
8. 跑 scripts/docs_check.py 自檢
9. 引用 migration-audit.json 標 verified 的舊內容；其他丟棄
```

## 7. Batch Strategy

每批一個 PR、可獨立合併進 main。

| Batch | 涵蓋 | 對數 | .md 數 |
|---|---|---|---|
| **B1 — 骨架 + Operator 主場** | `INDEX` + `getting-started` + 9 個 `user-guide/*` | 11 對 | 22 |
| **B2 — Reference + Architecture** | 3 個 `reference/*` + 4 個 `architecture/*` | 7 對 | 14 |
| **B3 — Contributing + 根 README** | 3 個 `contributing/*` + 縮版 `README.md` | 4 對 | 8 |
| **B4 — Polish & 稽核** | `scripts/docs_check.py`、inline link polishing、`migration-audit.json` 完整化、`git rm` 28 個舊檔 | — | 工具 + 清理 |

優先順序理由：
- B1 先做使用者面，先讓 Operator 有可信文件；舊文件還在 (deprecated banner) 可同時並存到 B4。
- B2 接著做 reference / architecture，為 API user 與 contributor 補上。
- B3 是 polishing。
- B4 才正式刪除 26 個舊檔（13 對，README 對不刪），確保新文已上線並驗證。

## 8. File Structure

### 8.1 NEW（建立 44 個 `.md` + 工具 + meta）

```
docs/
  INDEX.md
  INDEX_zh.md
  getting-started.md
  getting-started_zh.md
  user-guide/dashboard.md
  user-guide/dashboard_zh.md
  user-guide/reports.md
  user-guide/reports_zh.md
  user-guide/alerts-and-quarantine.md
  user-guide/alerts-and-quarantine_zh.md
  user-guide/rule-scheduler.md
  user-guide/rule-scheduler_zh.md
  user-guide/siem-integration.md
  user-guide/siem-integration_zh.md
  user-guide/multi-pce.md
  user-guide/multi-pce_zh.md
  user-guide/tls-and-certificates.md
  user-guide/tls-and-certificates_zh.md
  user-guide/settings-and-pce-cache.md
  user-guide/settings-and-pce-cache_zh.md
  user-guide/troubleshooting.md
  user-guide/troubleshooting_zh.md
  reference/cli.md
  reference/cli_zh.md
  reference/rest-api.md
  reference/rest-api_zh.md
  reference/glossary.md
  reference/glossary_zh.md
  architecture/overview.md
  architecture/overview_zh.md
  architecture/report-engine.md
  architecture/report-engine_zh.md
  architecture/siem-pipeline.md
  architecture/siem-pipeline_zh.md
  architecture/i18n-contract.md
  architecture/i18n-contract_zh.md
  contributing/dev-setup.md
  contributing/dev-setup_zh.md
  contributing/i18n-workflow.md
  contributing/i18n-workflow_zh.md
  contributing/release-process.md
  contributing/release-process_zh.md
  _meta/migration-audit.json
  _meta/glossary-terms.json

scripts/
  docs_check.py
```

### 8.2 MODIFIED

```
README.md      ← 縮為 ≤ 100 行，當 GitHub 入口
README_zh.md   ← 縮為 ≤ 100 行，當 GitHub 入口
```

### 8.3 DELETED（26 個舊 `.md` = 13 對，於 B4 執行；README 對不刪、僅縮版於 §8.2）

```
docs/Installation.md            docs/Installation_zh.md
docs/UPGRADE.md                 docs/UPGRADE_zh.md
docs/User_Manual.md             docs/User_Manual_zh.md
docs/Report_Modules.md          docs/Report_Modules_zh.md
docs/Security_Rules_Reference.md  docs/Security_Rules_Reference_zh.md
docs/SIEM_Integration.md        docs/SIEM_Integration_zh.md
docs/Architecture.md            docs/Architecture_zh.md
docs/PCE_Cache.md               docs/PCE_Cache_zh.md
docs/API_Cookbook.md            docs/API_Cookbook_zh.md
docs/Glossary.md                docs/Glossary_zh.md
docs/Troubleshooting.md         docs/Troubleshooting_zh.md
docs/cli-command-map.md         docs/cli-command-map_zh.md
docs/fonts-vendoring.md         docs/fonts-vendoring_zh.md
```

## 9. Success Criteria

| # | 指標 | 驗證 |
|---|---|---|
| 1 | 11 / 11 `src/` 子模組對應到至少一篇文件 | 對照本 spec §2.1 |
| 2 | 每個 EN `.md` 有對等 `_zh.md` | `scripts/docs_check.py --bilingual` |
| 3 | 每個 `.md` `last_verified` ≤ 30 天 | `scripts/docs_check.py --freshness 30` |
| 4 | `verified_against` ≥ 1 條 `src/` 路徑 + 1 個 commit SHA | 同上腳本 |
| 5 | 0 死內部連結 | `scripts/docs_check.py --links` |
| 6 | 每個 user-guide 文件 ≥ 3 條 Related Docs | 同上腳本 |
| 7 | `INDEX.md` 4 種讀者每種 ≥ 3 個入口 | 人工 |
| 8 | 26 個舊 `.md`（13 對）全部 `git rm` | `git ls-files docs/` 結果與 §8.3 不重疊 |
| 9 | `README.md` ≤ 100 行 | `wc -l README.md` |
| 10 | `migration-audit.json` 覆蓋 14 個舊文題目（28 個 `.md`，含 README 對） | 人工檢視 |

## 10. Risks & Mitigations

| # | 風險 | 機率 | 影響 | 緩解 |
|---|---|---|---|---|
| 1 | 範圍過大，後段失焦 | 高 | 中 | 4 批 PR 獨立交付 |
| 2 | 翻譯品質不一致 | 中 | 中 | 所有翻譯任務以 `src/i18n/data/zh_explicit.json` + 現有 `*_zh.md` 為查表來源；`reference/glossary.md`（B2）將術語彙整為正式 glossary |
| 3 | 「我以為對」但 src 已改 | 中 | 高 | frontmatter 強制 `verified_against` 列 src 路徑與 commit；docs_check 卡關 |
| 4 | 舊文資訊遺失 | 中 | 中 | `migration-audit.json` 在 `git rm` 前 commit |
| 5 | 規模超預期 | 中 | 中 | 硬上限：user-guide 800 行、architecture 1200 行、reference 2000 行；超過拆檔 |
| 6 | 重構中產品線改 src，文件做完就過期 | 高 | 中 | 接受不完美；frontmatter 記錄 verify 時點 |
| 7 | EN/zh_TW 結構漂移 | 中 | 低 | PR 強制兩個一起改；docs_check 比對章節數 |

## 11. Out of Scope (YAGNI)

- ❌ MkDocs / Sphinx / 任何文件網站建置
- ❌ 從 src docstring 自動生 API reference
- ❌ 多語言擴充（只做 EN + zh_TW；不開 zh_CN / ja）
- ❌ 名詞自動連 Glossary（保留 `glossary-terms.json` 鉤子，本次不實作）
- ❌ docs 與 codebase i18n 共用系統
- ❌ CI 強制 fail docs lint
- ❌ 截圖自動更新
- ❌ 翻譯記憶庫 / TMS 整合

## 12. Open Questions

無。Brainstorming 5 個關鍵變數（結構策略 / 讀者 / 雙語 / 舊文處置 / 連結機制）皆已收斂。

## 13. Related Documents

- 前一份 spec（被取代）: `docs/superpowers/specs/2026-04-28-documentation-rebuild-design.md`
- 近期重大變動 commits（影響重寫優先順序）:
  - i18n 架構 R1–R4: `ee363ee docs(plan): i18n architecture refactor plan (R1-R4, 22 tasks)`
  - SIEM destination UX 改版: `7035f50 docs: add SIEM destination UI/UX redesign spec`
  - Report print layout / ReportLab 移除: `4727992 docs: report print layout redesign spec`
  - TLS/CSR workflow: `86d550e feat(tls): add CSR generation and signed cert import workflow`
- 後續步驟（spec 核可後）: 將透過 `writing-plans` skill 產出 `docs/superpowers/plans/2026-05-15-docs-refactor.md`（單一主計畫，內含 B1–B4 子任務）
