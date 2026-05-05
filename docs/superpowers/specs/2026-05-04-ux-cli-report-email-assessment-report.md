---
Title: UX / CLI / Report / Email 全域評估報告
Source spec: docs/superpowers/specs/2026-05-04-ux-cli-report-email-assessment-design.md
Status: in-progress (Phase 0 complete, 後續 Phase A-H 填入)
Generated: 2026-05-04
---

# UX / CLI / Report / Email 全域評估報告

> 本檔依 design spec 結構鏡像產出。每個 §X.Y 對應 design spec 同編號章節的「填入結果」。
> 方法學 / rubric 定義皆引用 design spec，不在此重複。

---

## §1 Scope & Assumptions

### §1.0 文件定位（如何閱讀本 spec）

_（評估執行階段尚未填入）_

### §1.1 涵蓋

_（評估執行階段尚未填入）_

### §1.2 Persona 排序

_（評估執行階段尚未填入）_

### §1.3 硬約束

_（評估執行階段尚未填入）_

### §1.4 不在範圍

_（評估執行階段尚未填入）_

### §1.5 評估維度

_（評估執行階段尚未填入）_

---

## §2 Methodology

### §2.1 量化指標

_（評估執行階段尚未填入）_

### §2.2 痛點優先級評分公式

_（評估執行階段尚未填入）_

#### 門檻

_（評估執行階段尚未填入）_

### §2.3 GUI UX rubric（採 ui-ux-pro-max 10 類，0-3 分）

_（評估執行階段尚未填入）_

### §2.4 Visual Identity rubric（採 frontend-design 5 維度，0-3 分）

_（評估執行階段尚未填入）_

### §2.5 CLI-specific rubric（TTY 12 條，0-3 分）

_（評估執行階段尚未填入）_

### §2.6 重構 vs 優化判定 — 5 個 Gate

_（評估執行階段尚未填入）_

### §2.7 Evidence collection 規範

_（評估執行階段尚未填入）_

---

## §3 Subsystem Assessments（上半）

### §3.1 Frontend GUI

#### §3.1.0 Pre-conditions（先解再談優化）

##### a6 — HTTPS 啟用後 layout 破版

_（評估執行階段尚未填入）_

##### a7 — UI 依賴 external resources（違反 C1）

違規清單（掃描填入）：

| 檔案 | 行 | URL | 資源類型（CSS/JS/font/img/icon） | 是否被 HTTPS 阻擋 | 替代本地 asset 建議 |
|---|---|---|---|---|---|
| _TBD by scan_ | | | | | |

#### §3.1.1 整體現況量化

_（評估執行階段尚未填入）_

#### §3.1.2 UX rubric 結果（10 類）

_（評估執行階段尚未填入）_

#### §3.1.3 Visual Identity 現況評估

_（評估執行階段尚未填入）_

#### §3.1.4 可選方向

##### Aesthetic axis（視覺方向）

| 候選 | 描述 | 適用 persona |
|---|---|---|
| A. 維持現狀 | （baseline） | — |
| B. industrial-editorial | 高密度、tabular figures、editorial 字體層級、克制配色 | P1 + P2 |
| C. modern-saas | Linear/Vercel 風、generic | (不推薦 — 過於 cookie-cutter) |
| D. dark-ops 終端感 | Bloomberg / 終端機暗色、monospace 為核 | P2 SOC |

_（每候選 9 欄 spec sheet 評估執行階段填入）_

##### Framework axis

| 候選 | offline 友善 | touch | risk | 推薦條件 |
|---|---|---|---|---|
| Stay Vanilla + Design System | ✅ | 中 | 低 | 默認推薦 |
| HTMX + Alpine.js | ✅（vendor 化） | 中 | 中 | 若需強化 server-rendered + 局部互動 |
| Vue 3 + Vite | ⚠ build pipeline 進 offline bundle | 大 | 高 | 若 a1 在前面 phase 仍解不掉 |
| Lit + Web Components | ✅ | 中 | 中 | 若需 component 化但避 framework lock-in |

_（每候選跑 §2.6 五 Gate 評估執行階段填入）_

##### Backend axis

| 候選 | offline (wheels) | UX 直接收益 | 推薦條件 |
|---|---|---|---|
| Flask（現狀） | ✅ | 0 | 默認 |
| FastAPI + Uvicorn | ✅ | 中（async + SSE 釋放長任務） | 若需 SSE 進度推送 / async DB |
| Starlette | ✅ | 中 | 同上但更輕 |
| Litestar | ⚠ 需確認 wheel | 中 | 若需強型別 OpenAPI |

_（每候選跑 §2.6 五 Gate 評估執行階段填入）_

#### §3.1.5 推薦組合

_（評估執行階段尚未填入）_

---

### §3.2 CLI

#### §3.2.1 Command Inventory

攤平表（掃描填入）：

| 入口 | 命令 | verb | noun | flags | 輸出格式 | exit codes | isatty 處理 | --json | menu 也露出？ |
|---|---|---|---|---|---|---|---|---|---|
| _TBD by scan_ | | | | | | | | | |

#### §3.2.2 Consistency Matrix

_（評估執行階段尚未填入）_

#### §3.2.3 Interaction Model Audit（互動 menu 專屬）

_（評估執行階段尚未填入）_

#### §3.2.4 Rubric 打分

_（評估執行階段尚未填入）_

#### §3.2.5 可選方向

| 候選 | 描述 | offline | touch | risk |
|---|---|---|---|---|
| 維持現狀 + 補強 | 純文案 / 錯誤訊息修補 | ✅ | 小 | 低 |
| L2 抽出共享輸出層 | 顏色 / 表格 / spinner / exit code 共享 helper | ✅ | 中 | 低 |
| L3 統一入口 | 單一 `illumio-ops` 根命令含 3 支 CLI；menu 變 `shell` mode | ✅ | 大 | 中 |
| L4 Click + Rich + Typer 完整重寫 | 重新設計命令樹、bash/zsh/fish completion | ✅ | 最大 | 高 |

_（評估執行階段填入推薦結果）_

#### §3.2.6 推薦組合

_（評估執行階段尚未填入）_

---

### §3.3 Report

#### §3.3.1 Report Inventory

| Report | Generator | Exporters | i18n keys 數 | 平均輸出大小 | 主要 sections |
|---|---|---|---|---|---|
| audit | `audit_generator.py` | `audit_html_exporter.py` + pdf + csv + xlsx | _TBD_ | _TBD_ | _TBD_ |
| policy_usage | `policy_usage_generator.py` | `policy_usage_html_exporter.py` + pdf + csv + xlsx | | | |
| ven_status | `ven_status_generator.py` | `ven_html_exporter.py` + pdf + csv + xlsx | | | |
| dashboard_summaries | `dashboard_summaries.py` | (內嵌至其他報告) | | | |
| (legacy?) | `report_generator.py` | `html_exporter.py` ⚠ | | | |
| 共用 | — | `pdf_exporter.py`、`chart_renderer.py`、`table_renderer.py`、`code_highlighter.py`、`report_css.py`、`report_i18n.py` | | | |

#### §3.3.2 Content Audit

_（評估執行階段尚未填入）_

#### §3.3.3 Visual Identity 現況評估（document context）

_（評估執行階段尚未填入）_

#### §3.3.4 可選方向

| 候選 | 描述 | 適用 P5 主管 |
|---|---|---|
| A. 維持現狀 | （baseline） | — |
| B. editorial-magazine | Hoefler 風 / WSJ 工程感、優雅閱讀 | 高 |
| C. data-journalism | NYT / FT / Reuters Graphics 風，圖表敘事為主 | 中（取決於資料密度） |
| D. corporate-formal | McKinsey / 法務 deck / 合規風 | 高（若 audience 含合規） |

_（每候選 spec sheet 評估執行階段填入）_

#### §3.3.5 痛點對應 finding

_（評估執行階段尚未填入）_

#### §3.3.6 推薦組合

_（評估執行階段尚未填入）_

---

### §3.4 Email / Notification

#### §3.4.1 Template Inventory

_（評估執行階段尚未填入）_

#### §3.4.2 Cross-client Compatibility Audit

渲染矩陣（known-issue checklist）：

| Client | 已知雷區 |
|---|---|
| Outlook (Win / Mac / 365) | VML for buttons、`<style>` quirks、`word-wrap`、不支援 flexbox/grid |
| Gmail (web / iOS / Android) | `<style>` 部分支援、可能移除 class、image proxy |
| Apple Mail | dark mode auto-invert |
| Thunderbird | CSS 限制 |

_（實測結果評估執行階段填入）_

#### §3.4.3 Visual Identity 評估

_（評估執行階段尚未填入）_

#### §3.4.4 Actionability Audit（命中 d3）

_（評估執行階段尚未填入）_

#### §3.4.5 痛點對應 finding

_（評估執行階段尚未填入）_

#### §3.4.6 推薦組合

| 候選 | 描述 | offline | touch | risk |
|---|---|---|---|---|
| 維持現狀 + 補強 | inline CSS + preheader + 文字版 fallback | ✅ | 小 | 低 |
| L3 模板系統化 | `templates/email/*.html.j2` + 共享 partials | ✅ | 中 | 中 |
| L4 MJML 預編譯 | MJML 寫 → cross-client safe HTML，產物進 vendor / 編譯產物 | ✅（編譯產物） | 中 | 中 |

_（評估執行階段填入推薦結果）_

---

## §4 Pain-point Cards（下半，16 張）

> Cards filled in Phase E（評估執行階段逐一填入）。
>
> 16 張卡：4.1 a1 / 4.2 a2 / 4.3 a6 / 4.4 a7 / 4.5 b1 / 4.6 b2 / 4.7 b3 / 4.8 b4 / 4.9 b5 / 4.10 b6 / 4.11 b7 / 4.12 b8 / 4.13 c1 / 4.14 c3 / 4.15 d2 / 4.16 d3

_（評估執行階段尚未填入）_

---

## §5 Cross-cutting Recommendations

### §5.1 共因識別（Mining）

| 共用重構 | 解的痛點 | Touch radius | Offline 友善 |
|---|---|---|---|
| Token 化 `app.css` + design system | a1 a2 c3 d2 + visual 一致性 | 中 | ✅ |
| 共享 CLI 輸出層 | b3 b4 b6 b7（+ b1 副作用） | 中 | ✅ |
| 統一 CLI 入口 | b1 b2 b5 b8 | 大 | ✅ |
| Email 模板系統化（MJML 預編譯） | d2 d3 | 中 | ✅ |
| 拆 `index.html` monolith | a1 a2（+ 開發體驗 spillover） | 大 | ✅ |
| Backend async + SSE（OQ-1 conditional） | a1 (loading via SSE)、c1 (long report progress) | 大 | ✅（FastAPI / Starlette） |
| Report exporter 整併（若 `html_exporter.py` 71 KB 是 legacy） | c1 c3 + 維護性 | 大 | ✅ |

_（評估執行階段依掃描結果驗證與更新）_

### §5.2 Bundled Refactor Tracks

_（評估執行階段尚未填入）_

### §5.3 推薦執行順序

_（評估執行階段尚未填入）_

---

## §6 Visual Identity Direction

### §6.1 GUI direction

候選評估表（評估執行階段用 frontend-design 5 維度逐項打分）：

| 候選 | Typography | Color | Motion | Spatial | Backgrounds | Distinct | 適用 P1 / P2 |
|---|---|---|---|---|---|---|---|
| A. 維持現狀 | _TBD_ | | | | | | |
| B. industrial-editorial | | | | | | | |
| C. modern-saas | | | | | | | |
| D. dark-ops 終端感 | | | | | | | |

#### Adopted Direction Spec Sheet

_（採用後評估執行階段填入）_

### §6.2 Report + Email direction

候選評估表（Typography 權重最高、Motion 權重最低）：

| 候選 | Typography | Color | Spatial | Backgrounds | Distinct | 適用 P5 |
|---|---|---|---|---|---|---|
| A. 維持現狀 | _TBD_ | | | | | |
| B. editorial-magazine | | | | | | |
| C. data-journalism | | | | | | |
| D. corporate-formal | | | | | | |

#### Adopted Direction Spec Sheet

_（採用後評估執行階段填入）_

### §6.3 跨兩套的共享 primitive（OQ-7 default）

_（評估執行階段尚未填入）_

---

## §7 Mockup Appendix

> Mockup 由 Visual Companion 產出 HTML 片段，評估執行階段填入 screenshot + 連結。

### M1 — GUI tab loading

| | Before | After |
|---|---|---|
| 描述 | 現況同步載入空白 + a6 破版（若可重現） | 套用 §6.1 後 skeleton + staggered reveal + token 配色 |
| 版本 | light + dark | light + dark |
| 觸及痛點 | a1 + a2（部分）+ a6 visualization | — |

_（評估執行階段尚未填入）_

### M4 — Report summary section

| | Before | After |
|---|---|---|
| 描述 | c1「太長 / 摘要不夠」段落 | 套用 §6.2 後 執行摘要區 + verdict 對照表 + chart 重畫 |
| 版本 | light only | light only |
| 觸及痛點 | c1 + c3 | — |

_（評估執行階段尚未填入）_

### M5 — Email HTML

| | Before | After |
|---|---|---|
| 描述 | mail_wrapper 直送的版型 | 套用 §6.2 子集 preheader + bulletproof CTA + dark-mode-safe |
| 版本 | light + dark | light + dark |
| 觸及痛點 | d2 + d3 | — |

_（評估執行階段尚未填入）_

---

## §8 Open Questions

| ID | 問題 | 狀態 | Default / 答案 |
|---|---|---|---|
| OQ-1 | 是否接受打破 Flask 換 FastAPI / Starlette / Litestar？ | **Resolved** | 可換，前提 = offline bundle 安裝（C1 仍硬） |
| OQ-2 | 是否接受打破既有 i18n keys 命名空間？ | **Resolved** | 可重組；deploy 期附 migration mapping |
| OQ-3 | GUI redesign Task 6 視覺驗證是否視為 §3.1.0 延伸 pre-condition？ | Open | Default：是，先收 Task 6 → 再啟動 GUI 實作 |
| OQ-4 | Mockup light/dark 兩版策略確認？ | Open | Default：M1 兩版 / M4 light only / M5 兩版 |
| OQ-5 | §3.4.2 Email 渲染矩陣是否需實測？ | Open | Default：spec 列 known-issue 矩陣，實測列為下游 implementation 任務 |
| OQ-6 | §3.2 CLI 的 L4「Click + Rich + Typer 完全重寫」是否上推薦清單？ | Open | Default：列出選項但默認不推薦，除非 Track C 過程經驗證需要 |
| OQ-7 | §6.1 GUI 與 §6.2 Report/Email 的兩套視覺方向是否共享 token primitive？ | Open | Default：共享色票 primitive；type-scale 與 spacing-scale 各自 |
| OQ-8 | spec 寫作期是否強制執行 §3.1.0 a7 掃描並填入違規清單？ | Open | Default：是，spec 不能空著 a7 表（這是唯一的 P0 hard-gate） |
| OQ-9 | 若推薦 Track E（Backend Async），是否同步切換到 ASGI server？ | Open | Default：是，FastAPI / Starlette + Uvicorn（offline wheel ready） |
| OQ-10 | Illumio 既有英文術語（Allowed/Blocked/Managed/Unmanaged/boundary 等）的留英 vs 譯中策略，是否要在本 spec 內定義「判定原則」？ | Open | Default：是，§3.3.2 內列「Illumio 工程術語留英、UI 動詞與狀態譯中」原則 |

_（評估執行階段逐一解決 Open 項目並更新狀態）_

---

## §9 Out-of-scope / Defer

### Reliability（不在 UX 評估範圍）

_（評估執行階段尚未填入）_

### i18n 資料補齊

_（評估執行階段尚未填入）_

### 進行中工作（本 spec 假設完成）

_（評估執行階段尚未填入）_

### 技術選型升級（值得獨立 spec）

_（評估執行階段尚未填入）_

### 效能 profiling（不在 UX 評估範圍）

_（評估執行階段尚未填入）_

---

## §10 Glossary

_（評估執行階段尚未填入）_

---

## §11 References

_（評估執行階段尚未填入）_

### 相關專案 spec / plan

_（評估執行階段尚未填入）_
