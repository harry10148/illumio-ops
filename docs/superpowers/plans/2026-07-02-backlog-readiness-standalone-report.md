# Backlog: Enforcement 就緒度獨立報表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Backlog 狀態：** 產品方向項目 —— 先等報表拆分 Phase 2（Security 精簡）上線、
> 收過一輪使用回饋再排入。**排入的前置確認：使用者/客戶回饋確實需要獨立的
> enforcement 推進視角**（若 Security 報表精簡後 readiness 章已夠用，本案取消）。
> 執行前以當時程式碼 refresh。

**Goal:** 把 Enforcement 就緒度（mod13）從 Security 報表的一個章節升級為獨立報表：「哪個 app（env）下一步可以安全開 enforcement、還缺什麼」，服務微分段導入專案的每週推進會議。

**Architecture:** 重用 `mod13_readiness.enforcement_readiness()`（5 因子加權、A-F 等第、P1-P5 建議）為分析核心，新增薄的 generator + exporter（沿用 audit/ven 的 generator 模式：fetch → analyze → export html/csv/xlsx + trend snapshot）。不 fork mod13 —— Security 報表章節與獨立報表共用同一分析函式。

**Tech Stack:** Python 3.12、pandas、click、pytest。

## 現況事實（2026-07-02 盤點）

- `src/report/analysis/mod13_readiness.py`：`enforcement_readiness(df, workloads=None, top_n, lang)`
  —— 5 因子（policy_coverage 35 / ringfence 20 / enforcement_mode 20 / staged 15 /
  remote_app 10）、per app|env 分數與等第、`recommendations`（P1-P5）、
  `factor_table`、attack_posture_items。目前 `workloads=None` 呼叫
  （enforcement_mode 因子從 flow 欄位推斷）。
- Security 報表的 readiness 章（`html_exporter._mod13_html`）呈現分數構成、
  app 排名、修復建議三塊。
- 報表家族既有模式：generator（`generate_from_api` → `export`）+
  `trend_store` 快照 + CLI 子命令 + 排程 `report_type` dispatch
  （`src/report_scheduler.py:_generate_report`）。

## Global Constraints

- Commit：英文 conventional commits。無 emoji。i18n en/zh_TW 同步。
- mod13 分析邏輯單一來源：獨立報表與 Security 章節共用，禁止複製演算法。
- 新報表必須含列印/PDF 按鈕與 print-fit 表格（spec N）。
- 趨勢快照 report_type 用 `readiness`（獨立鍵，不与 traffic 系列混用）。

## 報表內容（單一問題：下一步開哪裡）

| 章節 | 內容 |
|---|---|
| 1. 執行摘要 | 總就緒分數與等第、可立即推進的 app 數（等第 A/B）、阻塞中的 app 數、與前次比較 |
| 2. 推進佇列 | app（env）依就緒分數排序：等第、目前 enforcement mode、阻塞因子（得分最低的因子）、建議動作 |
| 3. 因子解讀 | 5 因子組織層平均 + 白話說明（每分數一句「怎麼算、怎麼讀」，對齊拆分案 B6） |
| 4. 修復建議 | P1-P5 清單（沿用 mod13 recommendations），每項掛影響的 app 數 |
| 5. 趨勢 | 就緒分數與可推進 app 數的期別變化（trend_store） |

不含：攻擊摘要、成熟度、任何 mod13 以外的安全分析。

---

### Task 1: mod13 workloads 增強（enforcement mode 實測值）

**Files:**
- Modify: `src/report/analysis/mod13_readiness.py`（僅呼叫參數，演算法不動）
- Modify: 呼叫端 `src/report/analysis/__init__.py` 的 `_call_readiness` adapter
- Test: mod13 既有測試擴充

**Interfaces:**
- 獨立報表以 `api.fetch_managed_workloads()` 傳入 `workloads`，enforcement_mode
  因子改用 PCE 實際 mode（mod13 已支援該參數，僅 Security 管線傳 None）。
  Security 章節行為不變（仍傳 None，避免額外 API 成本）。

- [ ] Step 1-4: TDD 循環 + commit `feat(readiness): standalone report feeds real workload modes to mod13`

---### Task 2: ReadinessReportGenerator

**Files:**
- Create: `src/report/readiness_report.py`（generator：fetch flows(cache 優先) +
  workloads → mod13 → module_results；模式抄 `ven_status_generator.py` 的骨架）
- Test: `tests/test_readiness_report.py`（新檔）

**Interfaces:**
- Produces: `ReadinessReportGenerator(cm, api_client, cache_reader).generate(days=7, lang)`
  → result（record_count、module_results：`readiness`、`queue_df`、`kpis`）；
  `export(result, fmt, output_dir, lang) -> list[str]`。
- 推進佇列 `queue_df` 欄位：App / Env / Score / Grade / Current Mode /
  Blocking Factor / Recommended Action —— 由 mod13 的 `app_env_scores` +
  workloads mode 合成，佇列邏輯放 generator（不進 mod13）。

**Test strategy:** 合成 flows + workloads → 佇列排序正確、阻塞因子＝最低分因子、
A/B 等第計數正確；空資料回 record_count=0。

- [ ] Step 1-5: TDD 循環 + commit `feat(readiness): standalone readiness report generator`

---

### Task 3: HTML/CSV exporter 與趨勢

**Files:**
- Create: `src/report/exporters/readiness_html_exporter.py`（版型抄 ven exporter；
  含列印按鈕、print-fit 表格）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（章節、欄位、因子白話說明各 key）
- Test: `tests/test_readiness_html_exporter.py`（新檔）

**Interfaces:**
- 檔名 `Illumio_Readiness_Report_<ts>.html`；trend_store report_type=`readiness`。
- 因子白話說明 i18n key 命名 `rpt_readiness_factor_<name>_explain`（5 個），
  與拆分案 Phase 2 B6 的 Security 章說明共用同一組 key（先到者建立）。

- [ ] Step 1-5: TDD 循環 + commit `feat(readiness): readiness html/csv exporter with trend`

---

### Task 4: CLI 與排程接線

**Files:**
- Modify: `src/cli/report.py`（`report readiness` 子命令 + `generate-readiness` alias）
- Modify: `src/report_scheduler.py`（`report_type == "readiness"` dispatch 分支）
- Modify: `README.md`、`README_zh.md`、operations manual、`CHANGELOG.md`
- Test: `tests/test_cli_report_commands.py` 擴充

**Interfaces:**
- `illumio-ops report readiness [--days N] [--format html|csv|xlsx|all] [--output-dir]`。
- 排程設定 `report_schedules[].type` 支援 `readiness`。

- [ ] Step 1-5: TDD 循環 + 煙霧測試（lab PCE）+ commit `feat(cli): report readiness subcommand and scheduler dispatch`

---

## 完成定義

- `report readiness` 一分鐘內產出（cache-only）；佇列頁直接回答「下一步開哪裡」。
- Security 報表 readiness 章與獨立報表數字一致（同一 mod13）。
- pytest 全綠；文件（README 英中、ops manual）已列新報表。
