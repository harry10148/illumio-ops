# Enforcement 就緒度獨立報表 Implementation Plan（2026-07-11 refresh）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本檔為 `2026-07-02-backlog-readiness-standalone-report.md` 的 refresh 版**（原 plan 自帶條款「執行前以當時程式碼 refresh」）。所有檔案/行號/介面已對現行 main（570c52b，2026-07-11）逐條重新核實；各 task 開頭一行註明「refresh 變更點」。行號可能漂移——一律以符號/內容定位。

**Goal:** 把 Enforcement 就緒度（mod13）從 Security 報表的一個章節升級為獨立報表：「哪個 app（env）下一步可以安全開 enforcement、還缺什麼」，服務微分段導入專案的每週推進會議。

**Architecture:** 重用 `mod13_readiness.enforcement_readiness()`（5 因子加權、A-F 等第、P1-P5 建議）為分析核心，新增薄的 generator + exporter（generator 照 `AppSummaryReport` 的 facade 模式重用 `ReportGenerator.fetch_traffic_df`；exporter 照 `RuleHitCountHtmlExporter` 的 facade contract）。不 fork mod13——Security 報表章節（`html_exporter._mod13_html`）與獨立報表共用同一分析函式。

**Tech Stack:** Python 3.12、pandas、click、pytest、Flask（GUI route）、vanilla JS（dashboard.js）。

## Refresh 差異總覽（對 2026-07-02 原 plan）

1. **原 Task 1（mod13 workloads 增強）整個取消**：mod13 已原生支援 `workloads` 參數並回傳 `enforcement_mode_distribution`；`_call_readiness` adapter（`src/report/analysis/__init__.py:54`）維持 `workloads=None` 不動，獨立報表由 generator 直接呼叫 `enforcement_readiness(df, workloads=...)`。
2. **接線清單大幅擴增**：2026-07-02 之後 GUI 報表卡三分拆＋sidecar `report_type` 機制、`_REPORT_PREFIXES` 保留清理、GUI generate route rate limit 已上線——新報表型別必須接滿七處（generator sidecar、scheduler dispatch、`_REPORT_PREFIXES`、CLI、GUI route、GUI 前端卡片/modal/排程選項、i18n），接線樣板照 RHC 案（`2026-07-05-rule-hit-count-report.md`）。
3. **i18n 從兩檔改三檔流程**：`i18n_zh_TW.json` 現為 precompute 產物，不可手改（見 Global Constraints）。
4. **因子白話說明不建新 key**：原 plan 的 `rpt_readiness_factor_<name>_explain` 從未建立；拆分案 B6 已交付為 `rpt_mod13_col_guide_*`（`src/i18n_en.json:3300-3309`），直接重用。
5. **新事實——mod13 的 `app_env_scores` 會被 `.head(top_n)`（預設 20）截斷**：推進佇列須涵蓋全 estate，generator 必須傳大 `top_n`。
6. **xlsx 降為 v1 非目標**：沿 RHC v1 慣例（html/csv/all；xlsx 統一案的 `add_df_sheet` helpers 可後補）。原 plan 的 `generate-readiness` alias 也取消（verb alias 僅為既有命令回溯相容，RHC 未建）。

## 現況事實（2026-07-11 盤點，main @570c52b）

- `src/report/analysis/mod13_readiness.py:70`：`enforcement_readiness(df: pd.DataFrame, workloads: list | None = None, top_n: int = 20, *, lang: str = "en") -> dict`。回傳 keys：`total_score`、`grade`（`_score_to_grade`：A≥90/B≥75/C≥60/D≥45/其餘 F）、`factor_scores`、`factor_table`（DataFrame）、`recommendations`（DataFrame，欄位 `Priority/App (Env)/App Env Key/Issue/Action/Action Code/Severity`，P1-P5 已排序）、`app_env_scores`（DataFrame，**`.head(top_n)` 截斷**，含每 app|env 的 5 個 `*_ratio`/`*_score`、`flow_count`、`pb_uncovered_count`）、`enforcement_mode_distribution`、`ready_to_enforce_share`、`pb_uncovered_count`、`chart_spec`。空 df 回 `{"error": ...}`。
- 呼叫點僅兩處：Security 管線 `src/report/analysis/__init__.py:70`（經 `_call_readiness`，`workloads=None`）與 mod13 自身的 `analyze()` alias（:321）。
- app|env key 正規化（`_normalize_key_series`）：lower + strip、空值 → `unlabeled`，格式 `app|env`——generator 比對 workload labels 時必須套同樣規則。
- 流量抓取重用模式：`AppSummaryReport`（`src/report/app_summary_report.py`）以 `ReportGenerator(config_manager, api_client, config_dir, cache_reader).fetch_traffic_df(start_date, end_date, filters, use_cache, cache_workload_hrefs)` 取得 estate df；GUI 日期為 bare `YYYY-MM-DD`，須正規化為完整 ISO（`_iso_window` 模式），否則 PCE 查詢回零 flow。
- workloads：`ApiClient.fetch_managed_workloads(max_results=10000)`（`src/api_client.py:684`），每筆含 `enforcement_mode` 與 `labels` 清單。
- trend_store（`src/report/trend_store.py`）：呼叫序永遠「先 `load_previous` 後 `save_snapshot`」；`build_kpi_dict_from_metadata(kpis)`（偏好 `label_key`/`i18n_key`）、`canonicalize_legacy_keys`、`compute_deltas(current, previous)`（回 `metric/current/previous/delta/delta_pct/direction`）、`snapshot_mismatch(meta, prev)`；VEN 範本在 `ven_status_generator.generate()`:138-152。快照目錄鍵用 report_type=`readiness`（獨立鍵，不與 traffic 系列混用）。
- exporter facade contract（RHC 範本 `src/report/exporters/rule_hit_count_html_exporter.py`）：`__init__(result, lang="en", pce_url="", org_name="")` + `export(output_dir) -> path`；`build_css("readiness")`（未知型別 → base styling）、`build_cover_page(title, report_type, date_range, pce_url, org_name, lang, *, maturity_grade)`、`TABLE_JS`（sortable 表格）；截斷慣例 `_CELL_MAX = 160`、超長格 159 字 + `…` + 完整值進 `title` 屬性。
- 列印/PDF 慣例（VEN 範本 `ven_html_exporter.py:98-110`）：`<aside class="report-toc screen-only">` 目錄 + `<button class="print-btn" onclick="window.print()">{rpt_nav_print_pdf}</button>`；`report_css.py` 內建 `@media print` print-fit。
- metadata sidecar：generator 對每個輸出檔寫 `<path>.metadata.json`（含 `report_type`）；`/api/reports`（`src/gui/routes/reports.py:126`）讀 sidecar 的 `report_type` 回給前端；`dashboard.js` rcard 的 last-run 靠 `rp.report_type` 分組（traffic 家族因 sidecar 硬編 `traffic` 才需要檔名 prefix 覆寫——**readiness sidecar 直接寫 `readiness`，不需檔名覆寫**）。
- CSV 匯出：`CsvExporter(export_data, report_label='Readiness').export(output_dir)` → `Illumio_Readiness_Report_<ts>_raw.zip`（與 HTML 同 prefix，保留清理可共用一條 prefix）。
- scheduler：`_generate_report`（`src/report_scheduler.py:311`）依 `report_type` dispatch，`rule_hit_count` 分支（:414）之後、`else` 之前插入；`_REPORT_PREFIXES`（:607）供 `_prune_by_count` 保留清理；email 標題 map 在 `_send_report_email`（:446-454）。
- GUI route 慣例：`/api/<type>_report/generate` POST + `@limiter.limit("10 per hour")`；`_data_source_from_payload(payload, cache_available(cm))` → `(use_cache, clip_to_cache, warning)`；fmt 白名單 `_ALLOWED_REPORT_FORMATS`（`src/gui/_helpers.py:276`）。
- GUI 前端接點（dashboard.js）：`renderSchedules` 的 `typeLabels`（:324 一帶）、`openReportGenModal` 的 `meta` map（:654 一帶）、`confirmReportGen` 的 `typeLabels` 與 dispatch 分支（:754-768）、data-source 列的 `supportsCache` 判斷（:699 一帶）；index.html 的 rcard 區（rule_hit_count 卡 :1412-1423，之後、policy_diff 卡 :1425 之前插入）與排程型別下拉（:1567 `rule_hit_count` option 之後）。
- FilterBar（Phase 4a）只接 traffic 三卡（`TRAFFIC_PROFILE_TYPES`）的報表 modal——readiness modal **不接** FilterBar（mod13 吃全 estate flows）。
- CLI：canonical 短名子命令 + `_alias` 產生的 `generate-*` 舊名 alias（僅既有命令）；錯誤處理樣板見 `report_ven_status`（:595-622）。

## Global Constraints

- **TDD**：先寫失敗測試再實作（superpowers:test-driven-development）。
- **CLAUDE.md 報表截斷規範**：欄位長度上限與截斷邏輯必須明確——本報表沿 RHC 慣例 `_CELL_MAX = 160`，超長格 HTML 顯示前 159 字 + `…`、完整值放 `title` 屬性；CSV 匯出永遠完整值；不可無聲截斷。交付前用實際樣本資料跑完整輸出，逐頁檢查截斷與溢出，檢查結果附在回報裡（Task 6 末段）。
- **i18n 新鍵三檔流程**：`src/i18n_en.json` 加 en 值＋`src/i18n/data/zh_explicit.json` 加 zh 值＋跑 `python3 -m scripts.precompute_zh_translations --write` 重生 `src/i18n_zh_TW.json`（三檔一起 commit）。**絕不手改 `i18n_zh_TW.json`**。
- **glossary 禁譯**：zh 譯文遵守 `src/i18n/data/glossary.json` 禁譯規則（PCE/VEN/Service/Policy/Ruleset/Enforcement 等保留英文，禁用「服務」「政策」等替代字）。
- **報表 i18n 雙語**：所有報表字串 en/zh_TW 同步，經 `t()`（`src.i18n`）取值，不硬編。
- **mod13 分析邏輯單一來源**：獨立報表與 Security 章節共用 `enforcement_readiness()`，禁止複製演算法；佇列合成邏輯放 generator，不進 mod13。
- **列印/PDF**：新報表必須含列印/PDF 按鈕（`rpt_nav_print_pdf`）與 print-fit 表格（`report_css` 既有 `@media print`）。
- **趨勢快照** report_type 用 `readiness`（獨立鍵，不與 traffic 系列混用）。
- 每 task 後：聚焦測試 GREEN → 收尾跑全套 `python3 -m pytest -q` 全綠；`ruff check` 對改動檔零新增 violations。本機無 `python`，一律 `python3 -m pytest ...`。
- Commit message 英文 conventional commits；一切輸出（含註解、i18n 值）不用 emoji。
- 執行時依 superpowers:using-git-worktrees 在隔離 worktree 進行；subagent dispatch prompt 須明文驗證 pwd/分支。
- v1 非目標：xlsx 匯出、dashboard summary 卡、FilterBar 過濾、email 附件之外的通知管道、mod13 演算法任何變更。

## 報表內容（單一問題：下一步開哪裡）

| 章節 | 內容 | 資料來源 |
|---|---|---|
| 1. 執行摘要 | 總就緒分數與等第、可立即推進的 app 數（等第 A/B）、阻塞中的 app 數（等第 D/F）、PB 未覆蓋 flow 數、與前次比較（trend deltas） | mod13 `total_score/grade` + queue 統計 + `_trend_deltas` |
| 2. 推進佇列 | app（env）依就緒分數**由高到低**排序：分數、等第、目前 enforcement mode（workload 實測分布）、阻塞因子（比率最低的因子）、建議動作 | `app_env_scores` + workloads + `recommendations` 合成 |
| 3. 因子解讀 | 5 因子組織層 factor_table + 欄位白話說明（重用 `rpt_mod13_col_guide_*`） | mod13 `factor_table` |
| 4. 修復建議 | P1-P5 清單（沿用 mod13 `recommendations`），前置一張 per-Action 影響 app 數彙總表 | mod13 `recommendations` |
| 5. 趨勢 | 就緒 KPI 的期別變化表（trend_store 快照 delta） | `_trend_deltas` |

不含：攻擊摘要、成熟度、任何 mod13 以外的安全分析。

## 檔案結構

| 檔案 | 動作 | 職責 |
|---|---|---|
| `src/report/readiness_report.py` | 新建 | `ReadinessResult` + `ReadinessReportGenerator`（fetch → mod13 → queue/kpis → trend → export/sidecar） |
| `src/report/exporters/readiness_html_exporter.py` | 新建 | HTML exporter（cover + toc/print + KPI + 5 章 + 截斷） |
| `src/report_scheduler.py` | 修改 | `readiness` dispatch 分支（:414 `rule_hit_count` 後）+ `_REPORT_PREFIXES`（:607）+ email 標題 map（:454） |
| `src/cli/report.py` | 修改 | `generate_readiness_report` helper + `report readiness` 指令 |
| `src/gui/routes/reports.py` | 修改 | `POST /api/readiness_report/generate` route |
| `src/templates/index.html` | 修改 | rcard 卡片（rule_hit_count 卡後、policy_diff 卡前）+ 排程下拉選項（:1567 後） |
| `src/static/js/dashboard.js` | 修改 | typeLabels ×2、modal meta、supportsCache、dispatch 分支、`_doGenerateReadiness` |
| `src/i18n_en.json`、`src/i18n/data/zh_explicit.json` | 修改 | `rpt_readiness_*` 與 `gui_*readiness*` keys（＋precompute 重生 `i18n_zh_TW.json`） |
| `README.md`、`README_zh.md`、`CHANGELOG.md`、ops manual | 修改 | 新報表文件（Task 6 末段） |
| `tests/test_readiness_report.py` | 新建 | generator：佇列、KPI、trend、空資料 |
| `tests/test_readiness_html_exporter.py` | 新建 | 渲染、5 章、截斷 + title、print 按鈕 |
| `tests/test_readiness_scheduler_dispatch.py` | 新建 | dispatch、零資料 skip、prefix |
| `tests/test_cli_report_commands.py` | 擴充 | `report readiness` 轉呼叫 |
| `tests/test_gui_readiness_generate.py` | 新建 | route 行為（成功/零資料/格式白名單） |

---

### Task 1: ReadinessReportGenerator（分析核心 + 推進佇列 + 趨勢快照）

**Refresh 變更點：** 原 Task 1（mod13 workloads 增強／`_call_readiness` 調整）取消——mod13 與 Security 管線一行不動；本 task 改為 generator 直接呼叫 `enforcement_readiness(df, workloads=...)`。新事實納入：`app_env_scores` 被 `.head(top_n)` 截斷 → 傳 `top_n=100_000`；佇列排序改為分數**由高到低**（原 plan 未明定方向，「下一步開哪裡」應把最就緒的排最上面）；等第重用 mod13 的 `_score_to_grade`（單一來源，模組私有但直接 import 並註記）。

**Files:**
- Create: `src/report/readiness_report.py`
- Test: `tests/test_readiness_report.py`（新檔）

**Interfaces:**
- Produces: `ReadinessResult`（dataclass：`record_count`、`module_results`、`dataframe`、`generated_at`、`date_range`）。
- Produces: `ReadinessReportGenerator(config_manager, api_client=None, config_dir='config', cache_reader=None)`：
  - `generate_from_api(start_date=None, end_date=None, lang='en', use_cache=True, output_dir='reports') -> ReadinessResult`
  - `export(...)` 於 Task 3 補上。
- `module_results` keys：`readiness`（mod13 原始 dict）、`queue_df`（欄位 `app_display / app_env_key / readiness_score / grade / current_mode / blocking_factor / blocking_factor_key / recommended_action / flow_count / pb_uncovered_count`）、`kpis`（list[dict]，`i18n_key/label/value`）、`_trend_deltas`、`_trend_mismatch`。
- Consumes: `ReportGenerator.fetch_traffic_df`、`ApiClient.fetch_managed_workloads`、`enforcement_readiness`、trend_store 全套。
- 佇列規則：阻塞因子＝5 個 `*_ratio` 中最小者（i18n 顯示名 `rpt_factor_<name>`）；`current_mode`＝該 app|env 的 workload mode 計數字串（如 `full×3, visibility_only×5`，無 workload → `-`）；`recommended_action`＝`recommendations` 中該 `App Env Key` 的第一筆（最高優先）`Action`，無則 `-`。
- workload → app|env key 比對必須套 mod13 同樣正規化（lower/strip/空 → `unlabeled`）。

- [ ] **Step 1: 寫失敗測試（RED）**——新檔 `tests/test_readiness_report.py`：

```python
"""Enforcement Readiness standalone report generator tests."""
from __future__ import annotations

import pandas as pd
import pytest

from src.report.readiness_report import ReadinessReportGenerator, ReadinessResult


def _flows_df():
    # appA|prod: all allowed + ringfenced -> high score
    # appB|prod: all potentially_blocked -> low score, blocking factor = policy_coverage
    rows = []
    for _ in range(6):
        rows.append({"src_app": "appA", "src_env": "prod", "dst_app": "appA",
                     "dst_env": "prod", "policy_decision": "allowed",
                     "port": 443, "num_connections": 2,
                     "src_managed": True, "dst_managed": True})
    for _ in range(6):
        rows.append({"src_app": "appB", "src_env": "prod", "dst_app": "other",
                     "dst_env": "prod", "policy_decision": "potentially_blocked",
                     "port": 443, "num_connections": 1,
                     "src_managed": False, "dst_managed": False})
    return pd.DataFrame(rows)


def _workloads():
    return [
        {"href": "/w/1", "enforcement_mode": "full",
         "labels": [{"key": "app", "value": "appA"}, {"key": "env", "value": "Prod"}]},
        {"href": "/w/2", "enforcement_mode": "visibility_only",
         "labels": [{"key": "app", "value": "appB"}, {"key": "env", "value": "prod"}]},
    ]


def _gen(monkeypatch, df, workloads):
    gen = ReadinessReportGenerator(config_manager=None, api_client=None)
    monkeypatch.setattr(gen, "_fetch_estate_df", lambda *a, **k: df)
    monkeypatch.setattr(gen, "_fetch_workloads", lambda: workloads)
    return gen


def test_empty_flows_returns_zero_records(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, pd.DataFrame(), None)
    result = gen.generate_from_api(output_dir=str(tmp_path))
    assert isinstance(result, ReadinessResult)
    assert result.record_count == 0


def test_queue_sorted_ready_first(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    result = gen.generate_from_api(output_dir=str(tmp_path))
    q = result.module_results["queue_df"]
    assert list(q["app_env_key"])[0] == "appa|prod"          # highest score first
    assert q["readiness_score"].is_monotonic_decreasing


def test_blocking_factor_is_lowest_ratio(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    q = gen.generate_from_api(output_dir=str(tmp_path)).module_results["queue_df"]
    row = q[q["app_env_key"] == "appb|prod"].iloc[0]
    # appB has zero allowed flows -> policy_coverage ratio 0 is the minimum
    assert row["blocking_factor_key"] == "policy_coverage"


def test_current_mode_from_workloads_with_key_normalization(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    q = gen.generate_from_api(output_dir=str(tmp_path)).module_results["queue_df"]
    # 'Prod' label must normalize to 'prod' to match the flow-derived key
    assert q[q["app_env_key"] == "appa|prod"].iloc[0]["current_mode"] == "full×1"
    assert q[q["app_env_key"] == "appb|prod"].iloc[0]["current_mode"] == "visibility_only×1"


def test_kpis_count_ready_and_blocked(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    kpis = gen.generate_from_api(output_dir=str(tmp_path)).module_results["kpis"]
    by_key = {k["i18n_key"]: k["value"] for k in kpis}
    q = gen.generate_from_api(output_dir=str(tmp_path)).module_results["queue_df"]
    assert by_key["rpt_readiness_kpi_ready"] == int(q["grade"].isin(["A", "B"]).sum())
    assert by_key["rpt_readiness_kpi_blocked"] == int(q["grade"].isin(["D", "F"]).sum())
    assert "rpt_readiness_kpi_score" in by_key and "rpt_readiness_kpi_grade" in by_key


def test_trend_snapshot_saved_and_deltas_on_second_run(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    r1 = gen.generate_from_api(output_dir=str(tmp_path))
    assert (tmp_path / "history" / "readiness").is_dir()
    assert r1.module_results["_trend_deltas"] == []
    r2 = gen.generate_from_api(output_dir=str(tmp_path))
    metrics = {d["metric"] for d in r2.module_results["_trend_deltas"]}
    assert "rpt_readiness_kpi_score" in metrics
```

執行 `python3 -m pytest tests/test_readiness_report.py -q` 確認 RED（module 不存在）。

- [ ] **Step 2: 實作 `src/report/readiness_report.py`（GREEN）**：

```python
"""Enforcement Readiness standalone report — generator facade.

Thin wrapper over the SHARED mod13 analysis (single source of truth with the
Security report's readiness chapter): fetch the estate traffic DataFrame
(cache-aware, via ReportGenerator.fetch_traffic_df) plus managed workloads,
run enforcement_readiness(), and synthesize the advancement queue that answers
"which app (env) can we safely move to enforcement next".
"""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
from loguru import logger

from src.i18n import t
# _score_to_grade is module-private in mod13 but intentionally imported here:
# grade thresholds must stay a single source of truth with the Security chapter.
from src.report.analysis.mod13_readiness import _score_to_grade, enforcement_readiness

_QUEUE_FACTORS = [
    ("policy_coverage", "policy_coverage_ratio"),
    ("ringfence_maturity", "ringfence_maturity_ratio"),
    ("enforcement_mode", "enforcement_mode_ratio"),
    ("staged_readiness", "staged_readiness_ratio"),
    ("remote_app_coverage", "remote_app_coverage_ratio"),
]
_QUEUE_COLS = ["app_display", "app_env_key", "readiness_score", "grade",
               "current_mode", "blocking_factor", "blocking_factor_key",
               "recommended_action", "flow_count", "pb_uncovered_count"]
# mod13 truncates app_env_scores with .head(top_n) (default 20); the standalone
# queue must rank the WHOLE estate, so pass an effectively unbounded top_n.
_ALL_APPS = 100_000
_MODE_ORDER = {"full": 0, "selective": 1, "visibility_only": 2, "idle": 3}


def _iso_window(value, *, end_of_day):
    """Normalize bare 'YYYY-MM-DD' (GUI date pickers) to full ISO-8601 —
    a date-only value makes the PCE traffic query return zero flows
    (same guard as AppSummaryReport.build)."""
    if not value or not isinstance(value, str) or "T" in value:
        return value
    try:
        parsed = datetime.datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%dT" + ("23:59:59Z" if end_of_day else "00:00:00Z"))


def _workload_app_env_key(w: dict) -> str:
    """app|env key for a workload, normalized EXACTLY like mod13's
    _normalize_key_series (lower/strip, empty -> 'unlabeled')."""
    app = env = ""
    for lbl in (w.get("labels") or []):
        if lbl.get("key") == "app":
            app = str(lbl.get("value") or "")
        elif lbl.get("key") == "env":
            env = str(lbl.get("value") or "")
    app = app.strip().lower() or "unlabeled"
    env = env.strip().lower() or "unlabeled"
    return f"{app}|{env}"


def _mode_summary(modes: dict[str, int]) -> str:
    if not modes:
        return "-"
    parts = sorted(modes.items(), key=lambda kv: (_MODE_ORDER.get(kv[0], 9), kv[0]))
    return ", ".join(f"{mode}×{count}" for mode, count in parts)


@dataclasses.dataclass
class ReadinessResult:
    record_count: int
    module_results: dict
    dataframe: pd.DataFrame | None = None
    generated_at: datetime.datetime = dataclasses.field(
        default_factory=datetime.datetime.now)
    date_range: tuple = ("", "")


class ReadinessReportGenerator:
    def __init__(self, config_manager, api_client=None, config_dir: str = "config",
                 cache_reader=None):
        self.cm = config_manager
        self.api = api_client
        self._config_dir = config_dir
        self._cache = cache_reader
        self._lang = "en"

    # ── Fetch ────────────────────────────────────────────────────────────
    def _fetch_estate_df(self, start_date, end_date, *, use_cache: bool = True):
        from src.report.report_generator import ReportGenerator
        gen = ReportGenerator(config_manager=self.cm, api_client=self.api,
                              config_dir=self._config_dir, cache_reader=self._cache)
        return gen.fetch_traffic_df(
            start_date=_iso_window(start_date, end_of_day=False),
            end_date=_iso_window(end_date, end_of_day=True),
            use_cache=use_cache)

    def _fetch_workloads(self) -> list | None:
        if not self.api:
            return None
        try:
            return self.api.fetch_managed_workloads()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Readiness] workloads fetch failed: {} — "
                           "enforcement-mode factor falls back to flow inference", exc)
            return None

    # ── Generate ─────────────────────────────────────────────────────────
    def generate_from_api(self, start_date=None, end_date=None, lang: str = "en",
                          use_cache: bool = True,
                          output_dir: str = "reports") -> ReadinessResult:
        self._lang = lang
        date_range = (start_date or "", end_date or "")
        df = self._fetch_estate_df(start_date, end_date, use_cache=use_cache)
        if df is None or df.empty:
            return ReadinessResult(record_count=0, module_results={},
                                   date_range=date_range)
        workloads = self._fetch_workloads()
        readiness = enforcement_readiness(df, workloads=workloads,
                                          top_n=_ALL_APPS, lang=lang)
        module_results: dict = {"readiness": readiness}
        result = ReadinessResult(record_count=len(df), module_results=module_results,
                                 dataframe=df, date_range=date_range)
        if "error" in readiness:
            return result
        queue_df = self._build_queue(readiness, workloads)
        module_results["queue_df"] = queue_df
        module_results["kpis"] = self._build_kpis(readiness, queue_df, lang)
        self._attach_trend(result, output_dir)
        return result

    # ── Queue synthesis (generator-side; NOT in mod13) ───────────────────
    def _build_queue(self, readiness: dict, workloads: list | None) -> pd.DataFrame:
        scores = readiness.get("app_env_scores")
        if scores is None or scores.empty:
            return pd.DataFrame(columns=_QUEUE_COLS)
        modes_by_key: dict[str, dict[str, int]] = {}
        for w in (workloads or []):
            key = _workload_app_env_key(w)
            mode = str(w.get("enforcement_mode", "unknown")).lower().strip() or "unknown"
            bucket = modes_by_key.setdefault(key, {})
            bucket[mode] = bucket.get(mode, 0) + 1
        action_by_key: dict[str, str] = {}
        recs = readiness.get("recommendations")
        if recs is not None and not recs.empty and "App Env Key" in recs.columns:
            # recommendations are pre-ranked P1..P5 — keep the FIRST per app.
            for _, r in recs.iterrows():
                action_by_key.setdefault(str(r["App Env Key"]), str(r["Action"]))
        rows = []
        for _, s in scores.iterrows():
            ratios = {name: float(s.get(col, 0.0)) for name, col in _QUEUE_FACTORS}
            blocking = min(ratios, key=ratios.get)
            key = str(s["app_env_key"])
            score = float(s["readiness_score"])
            rows.append({
                "app_display": s.get("app_display", key),
                "app_env_key": key,
                "readiness_score": score,
                "grade": _score_to_grade(score),
                "current_mode": _mode_summary(modes_by_key.get(key, {})),
                "blocking_factor": t(f"rpt_factor_{blocking}", lang=self._lang),
                "blocking_factor_key": blocking,
                "recommended_action": action_by_key.get(key, "-"),
                "flow_count": int(s.get("flow_count", 0)),
                "pb_uncovered_count": int(s.get("pb_uncovered_count", 0)),
            })
        # Ready-first: the next app to enforce sits on top.
        return pd.DataFrame(rows, columns=_QUEUE_COLS).sort_values(
            by=["readiness_score", "app_env_key"], ascending=[False, True]
        ).reset_index(drop=True)

    @staticmethod
    def _build_kpis(readiness: dict, queue_df: pd.DataFrame, lang: str) -> list[dict]:
        ready = int(queue_df["grade"].isin(["A", "B"]).sum()) if not queue_df.empty else 0
        blocked = int(queue_df["grade"].isin(["D", "F"]).sum()) if not queue_df.empty else 0
        def _kpi(key: str, value):
            return {"i18n_key": key, "label": t(key, lang=lang), "value": value}
        return [
            _kpi("rpt_readiness_kpi_score", readiness.get("total_score", 0)),
            _kpi("rpt_readiness_kpi_grade", readiness.get("grade", "?")),
            _kpi("rpt_readiness_kpi_ready", ready),
            _kpi("rpt_readiness_kpi_blocked", blocked),
            _kpi("rpt_readiness_kpi_pb_uncovered", readiness.get("pb_uncovered_count", 0)),
        ]

    # ── Trend snapshot (load BEFORE save — trend_store contract) ─────────
    def _attach_trend(self, result: ReadinessResult, output_dir: str) -> None:
        from src.report.trend_store import (
            build_kpi_dict_from_metadata, canonicalize_legacy_keys, compute_deltas,
            load_previous, save_snapshot, snapshot_mismatch,
        )
        try:
            kpi_dict = build_kpi_dict_from_metadata(result.module_results.get("kpis", []))
            prev = load_previous(output_dir, "readiness")
            prev = canonicalize_legacy_keys(prev, candidate_keys=list(kpi_dict.keys()))
            meta = {"profile": "readiness",
                    "window": [result.date_range[0], result.date_range[1]]}
            save_snapshot(output_dir, "readiness", kpi_dict,
                          generated_at=result.generated_at.isoformat(timespec="seconds"),
                          meta=meta)
            result.module_results["_trend_deltas"] = compute_deltas(kpi_dict, prev) if prev else []
            result.module_results["_trend_mismatch"] = snapshot_mismatch(meta, prev) if prev else []
        except Exception as e:  # noqa: BLE001
            logger.warning("Readiness trend delta skipped: {}", e)
            result.module_results["_trend_deltas"] = []
```

注意：KPI 的 i18n keys 在 Task 2 才進 i18n 檔——本 task 測試不驗 label 文案（`t()` 對缺 key 回 key 本身，不會炸）。

- [ ] **Step 3: 驗證 GREEN**：`python3 -m pytest tests/test_readiness_report.py -q` 全綠。
- [ ] **Step 4: 全套 + lint**：`python3 -m pytest -q` 全綠；`ruff check src/report/readiness_report.py tests/test_readiness_report.py` 零新增。
- [ ] **Step 5: Commit** `feat(readiness): standalone readiness report generator with advancement queue`

---

### Task 2: HTML exporter（5 章 + 列印 + 截斷）+ 報表 i18n keys

**Refresh 變更點：** 因子白話說明改為重用既有 `rpt_mod13_col_guide_*`（i18n_en.json:3300-3309，B6 已交付），不建原 plan 的 `rpt_readiness_factor_*_explain`；i18n 走三檔 precompute 流程（原 plan 寫「改 en/zh_TW 兩檔」已失效）；截斷規則對齊 RHC `_CELL_MAX=160` 慣例（原 plan 未定截斷數值）；exporter contract 對齊 RHC facade（`__init__(result, lang, pce_url, org_name)` + `export(output_dir)`）。

**Files:**
- Create: `src/report/exporters/readiness_html_exporter.py`
- Modify: `src/i18n_en.json`、`src/i18n/data/zh_explicit.json`（＋precompute 重生 `src/i18n_zh_TW.json`）
- Test: `tests/test_readiness_html_exporter.py`（新檔）

**Interfaces:**
- Produces: `ReadinessHtmlExporter(result, lang="en", pce_url="", org_name="").export(output_dir) -> path`；檔名 `Illumio_Readiness_Report_<YYYY-MM-DD_HHMM>.html`。
- 版面：`build_cover_page(..., maturity_grade=grade)` 封面 → `<aside class="report-toc screen-only">` 5 章目錄 + `print-btn`（VEN 慣例）→ `<main class="report-main">` KPI row + 5 章；表格用 `report-table sortable` + `TABLE_JS`。
- 截斷：`_TRUNC_COLS = {"app_display", "current_mode", "recommended_action"}`（佇列表）與 recommendations 的 `Action`；`_CELL_MAX = 160`，超長 → 159 字 + `…` + 完整值 `title` 屬性。
- 修復建議章：先渲染 per-Action 彙總表（Action Code → 影響 app 數 = distinct `App Env Key` 數），再渲染 P1-P5 明細表。
- 趨勢章：`_trend_deltas` 表（metric 經 `t()` 本地化、current/previous/delta、方向箭頭用文字 `↑/↓/→`——非 emoji）。無前次快照 → `rpt_readiness_trend_first_run` 一句話。

**新 i18n keys（en 進 `i18n_en.json`、zh 進 `zh_explicit.json`；glossary 禁譯——Enforcement/PCE/VEN/Policy 保留英文）：**

| key | en |
|---|---|
| `rpt_readiness_report_title` | Enforcement Readiness Report |
| `rpt_readiness_cover_type` | Enforcement Readiness |
| `rpt_readiness_subnote` | Answers one question: which app (env) can safely move to enforcement next, and what is blocking the rest. Scores come from the same mod13 analysis as the Security report's readiness chapter. |
| `rpt_readiness_kpi_score` | Readiness Score |
| `rpt_readiness_kpi_grade` | Grade |
| `rpt_readiness_kpi_ready` | Apps Ready (A/B) |
| `rpt_readiness_kpi_blocked` | Apps Blocked (D/F) |
| `rpt_readiness_kpi_pb_uncovered` | PB Uncovered Flows |
| `rpt_readiness_sec_summary` | Executive Summary |
| `rpt_readiness_sec_queue` | Advancement Queue |
| `rpt_readiness_sec_factors` | Factor Breakdown |
| `rpt_readiness_sec_recommendations` | Remediation Recommendations |
| `rpt_readiness_sec_trend` | Trend |
| `rpt_readiness_col_app` | App (Env) |
| `rpt_readiness_col_score` | Score |
| `rpt_readiness_col_grade` | Grade |
| `rpt_readiness_col_mode` | Current Mode |
| `rpt_readiness_col_blocking` | Blocking Factor |
| `rpt_readiness_col_action` | Recommended Action |
| `rpt_readiness_col_flows` | Flows |
| `rpt_readiness_col_pb` | PB Flows |
| `rpt_readiness_rollup_action` | Action |
| `rpt_readiness_rollup_apps` | Affected Apps |
| `rpt_readiness_no_rows` | No rows. |
| `rpt_readiness_trend_first_run` | First run — trend deltas will appear from the next report onward. |
| `rpt_readiness_trend_col_metric` | Metric |
| `rpt_readiness_trend_col_current` | Current |
| `rpt_readiness_trend_col_previous` | Previous |
| `rpt_readiness_trend_col_delta` | Change |
| `rpt_readiness_html_saved` | Readiness report saved: {path} |
| `rpt_readiness_csv_saved` | Readiness CSV saved: {path} |

**重用（不得重建）：** `rpt_factor_policy_coverage` 等 5 個因子名、`rpt_mod13_col_guide_*`（欄位白話說明 legend）、`rpt_nav_contents`、`rpt_nav_print_pdf`、`rpt_mod_err_no_data`。

- [ ] **Step 1: 寫失敗測試（RED）**——新檔 `tests/test_readiness_html_exporter.py`：

```python
"""Readiness HTML exporter — sections, truncation, print affordance."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from src.report.readiness_report import ReadinessResult
from src.report.exporters.readiness_html_exporter import ReadinessHtmlExporter


def _result(long_action: str = "act"):
    queue_df = pd.DataFrame([{
        "app_display": "appA (prod)", "app_env_key": "appa|prod",
        "readiness_score": 91.0, "grade": "A", "current_mode": "full×2",
        "blocking_factor": "Ringfence Maturity", "blocking_factor_key": "ringfence_maturity",
        "recommended_action": long_action, "flow_count": 6, "pb_uncovered_count": 0,
    }])
    factor_table = pd.DataFrame([{"Factor": "Policy Coverage", "Weight": 35,
                                  "Score": 30.0, "Ratio %": 85.0}])
    recs = pd.DataFrame([{"Priority": "P2", "App (Env)": "appB (prod)",
                          "App Env Key": "appb|prod", "Issue": "Enforcement Gap",
                          "Action": "Move to enforcement", "Action Code": "MOVE_TO_ENFORCEMENT",
                          "Severity": "HIGH"}])
    readiness = {"total_score": 78.5, "grade": "B",
                 "factor_table": factor_table, "recommendations": recs,
                 "enforcement_mode_distribution": {"full": 2}}
    return ReadinessResult(
        record_count=12,
        module_results={"readiness": readiness, "queue_df": queue_df,
                        "kpis": [{"i18n_key": "rpt_readiness_kpi_score",
                                  "label": "Readiness Score", "value": 78.5}],
                        "_trend_deltas": []},
        date_range=("2026-07-01", "2026-07-08"))


def _render(tmp_path, result, lang="en"):
    path = ReadinessHtmlExporter(result, lang=lang).export(str(tmp_path))
    with open(path, encoding="utf-8") as fh:
        return path, fh.read()


def test_export_writes_prefixed_file_with_sections(tmp_path):
    path, html = _render(tmp_path, _result())
    assert os.path.basename(path).startswith("Illumio_Readiness_Report_")
    for anchor in ("readiness-summary", "readiness-queue", "readiness-factors",
                   "readiness-recommendations", "readiness-trend"):
        assert f'id="{anchor}"' in html


def test_print_button_present(tmp_path):
    _, html = _render(tmp_path, _result())
    assert "window.print()" in html and "print-btn" in html


def test_long_action_truncated_with_title_attr(tmp_path):
    long_action = "x" * 200
    _, html = _render(tmp_path, _result(long_action=long_action))
    assert long_action not in html.replace(f'title="{long_action}"', "")
    assert f'title="{long_action}"' in html
    assert ("x" * 159 + "…") in html


def test_trend_first_run_note(tmp_path):
    _, html = _render(tmp_path, _result())
    from src.i18n import t
    assert t("rpt_readiness_trend_first_run", lang="en") in html


def test_zh_render_has_no_missing_keys(tmp_path):
    _, html = _render(tmp_path, _result(), lang="zh_TW")
    assert "rpt_readiness_sec_queue" not in html  # key leaked = missing translation
```

執行確認 RED。

- [ ] **Step 2: 加 i18n keys（三檔流程）**：`src/i18n_en.json` 加上表 en 值；`src/i18n/data/zh_explicit.json` 加對應 zh 值（禁譯詞保留英文，例：`rpt_readiness_kpi_score` → `就緒分數`、`rpt_readiness_col_mode` → `目前 Enforcement Mode`、`rpt_readiness_sec_queue` → `推進佇列`）；跑 `python3 -m scripts.precompute_zh_translations --write` 重生 `src/i18n_zh_TW.json`，確認無 glossary violations 輸出。三檔一起進 commit。

- [ ] **Step 3: 實作 exporter（GREEN）**——`src/report/exporters/readiness_html_exporter.py`，骨架照 `rule_hit_count_html_exporter.py`：

```python
"""Enforcement Readiness HTML exporter.

Facade contract: __init__(result, lang, pce_url, org_name) + export(output_dir).
Long-cell policy (CLAUDE.md): cells in _TRUNC_COLS longer than _CELL_MAX chars
are truncated to _CELL_MAX-1 chars + ellipsis; the FULL value is preserved in
the cell's title attribute and in the CSV export. Never silent.
"""
from __future__ import annotations

import datetime
import html as _html
import os

from src.i18n import t
from src.report.exporters.cover_page import build_cover_page as _build_cover_page
from src.report.exporters.report_css import TABLE_JS, build_css

_CSS = build_css("readiness")  # unknown type -> base styling (incl. @media print)
_CELL_MAX = 160

_QUEUE_COLS = ["app_display", "readiness_score", "grade", "current_mode",
               "blocking_factor", "recommended_action", "flow_count",
               "pb_uncovered_count"]
_QUEUE_COL_I18N = {
    "app_display": "rpt_readiness_col_app",
    "readiness_score": "rpt_readiness_col_score",
    "grade": "rpt_readiness_col_grade",
    "current_mode": "rpt_readiness_col_mode",
    "blocking_factor": "rpt_readiness_col_blocking",
    "recommended_action": "rpt_readiness_col_action",
    "flow_count": "rpt_readiness_col_flows",
    "pb_uncovered_count": "rpt_readiness_col_pb",
}
_TRUNC_COLS = {"app_display", "current_mode", "recommended_action", "Action"}
_DIR_ARROW = {"up": "↑", "down": "↓", "flat": "→"}


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(value, label) -> str:
    return ('<div class="kpi-card">'
            f'<div class="kpi-label">{_esc(label)}</div>'
            f'<div class="kpi-value">{_esc(value)}</div></div>')


class ReadinessHtmlExporter:
    def __init__(self, result, lang: str = "en", pce_url: str = "", org_name: str = ""):
        self._result = result
        self._lang = lang
        self._pce_url = pce_url
        self._org_name = org_name

    # ── cells / tables ────────────────────────────────────────────────
    def _cell(self, col: str, value) -> str:
        text = "" if value is None else str(value)
        if col in _TRUNC_COLS and len(text) > _CELL_MAX:
            shown = text[:_CELL_MAX - 1] + "…"
            return f'<td title="{_esc(text)}">{_esc(shown)}</td>'
        return f"<td>{_esc(text)}</td>"

    def _table(self, df, cols: list[str], header_of) -> str:
        if df is None or df.empty:
            return f'<p class="note">{_esc(t("rpt_readiness_no_rows", lang=self._lang))}</p>'
        use = [c for c in cols if c in df.columns]
        head = "".join(f"<th>{_esc(header_of(c))}</th>" for c in use)
        body = "".join(
            "<tr>" + "".join(self._cell(c, row.get(c, "")) for c in use) + "</tr>"
            for _, row in df.iterrows())
        return ('<div class="report-table-wrap"><table class="report-table sortable">'
                f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

    # ── sections ──────────────────────────────────────────────────────
    def _summary(self, readiness, kpis) -> str:
        lang = self._lang
        kpi_row = '<div class="kpi-row">' + "".join(
            _kpi(k.get("value", ""), k.get("label", k.get("i18n_key", ""))) for k in kpis
        ) + "</div>"
        return (f'<p class="note">{_esc(t("rpt_readiness_subnote", lang=lang))}</p>'
                + kpi_row)

    def _factor_legend(self) -> str:
        lang = self._lang
        rows = "".join(
            f'<li><b>{_esc(t(f"rpt_factor_{name}", lang=lang))}</b> — '
            f'{t(f"rpt_mod13_col_guide_{guide}", lang=lang)}</li>'
            for name, guide in [("policy_coverage", "policy"),
                                ("ringfence_maturity", "ringfence"),
                                ("enforcement_mode", "enforcement"),
                                ("staged_readiness", "staged"),
                                ("remote_app_coverage", "remote")])
        return f'<ul class="note">{rows}</ul>'

    def _recommendations(self, recs) -> str:
        lang = self._lang
        if recs is None or recs.empty:
            return f'<p class="note">{_esc(t("rpt_readiness_no_rows", lang=lang))}</p>'
        rollup = (recs.groupby("Action")["App Env Key"].nunique()
                  .sort_values(ascending=False).reset_index())
        rollup.columns = [t("rpt_readiness_rollup_action", lang=lang),
                          t("rpt_readiness_rollup_apps", lang=lang)]
        rollup_html = self._table(rollup, list(rollup.columns), lambda c: c)
        detail_cols = ["Priority", "App (Env)", "Issue", "Action", "Severity"]
        detail_html = self._table(recs, detail_cols, lambda c: c)
        return rollup_html + detail_html

    def _trend(self, deltas) -> str:
        lang = self._lang
        if not deltas:
            return f'<p class="note">{_esc(t("rpt_readiness_trend_first_run", lang=lang))}</p>'
        head = "".join(f"<th>{_esc(t(k, lang=lang))}</th>" for k in
                       ("rpt_readiness_trend_col_metric", "rpt_readiness_trend_col_current",
                        "rpt_readiness_trend_col_previous", "rpt_readiness_trend_col_delta"))
        body = "".join(
            "<tr>"
            f"<td>{_esc(t(d.get('metric', ''), lang=lang))}</td>"
            f"<td>{_esc(d.get('current', ''))}</td>"
            f"<td>{_esc(d.get('previous', ''))}</td>"
            f"<td>{_DIR_ARROW.get(d.get('direction', 'flat'), '→')} {_esc(d.get('delta', ''))}</td>"
            "</tr>" for d in deltas)
        return ('<div class="report-table-wrap"><table class="report-table">'
                f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

    # ── document ──────────────────────────────────────────────────────
    def _render_html(self) -> str:
        lang = self._lang
        mr = self._result.module_results or {}
        readiness = mr.get("readiness", {})
        cover = _build_cover_page(
            t("rpt_readiness_report_title", lang=lang),
            t("rpt_readiness_cover_type", lang=lang),
            date_range=self._result.date_range,
            pce_url=self._pce_url, org_name=self._org_name, lang=lang,
            maturity_grade=readiness.get("grade"))
        sections = [
            ("readiness-summary", t("rpt_readiness_sec_summary", lang=lang),
             self._summary(readiness, mr.get("kpis", []))),
            ("readiness-queue", t("rpt_readiness_sec_queue", lang=lang),
             self._table(mr.get("queue_df"), _QUEUE_COLS,
                         lambda c: t(_QUEUE_COL_I18N.get(c, c), lang=lang))),
            ("readiness-factors", t("rpt_readiness_sec_factors", lang=lang),
             self._factor_legend()
             + self._table(readiness.get("factor_table"),
                           list(getattr(readiness.get("factor_table"), "columns", [])),
                           lambda c: c)),
            ("readiness-recommendations", t("rpt_readiness_sec_recommendations", lang=lang),
             self._recommendations(readiness.get("recommendations"))),
            ("readiness-trend", t("rpt_readiness_sec_trend", lang=lang),
             self._trend(mr.get("_trend_deltas", []))),
        ]
        toc = ("<aside class=\"report-toc screen-only\">"
               f"<h3>{_esc(t('rpt_nav_contents', lang=lang))}</h3><ol>"
               + "".join(f'<li><a href="#{sid}">{_esc(title)}</a></li>'
                         for sid, title, _ in sections)
               + "</ol>"
               f"<button class=\"print-btn\" onclick=\"window.print()\">"
               f"{_esc(t('rpt_nav_print_pdf', lang=lang))}</button></aside>")
        body = "".join(
            f'<section id="{sid}" class="card"><h2>{_esc(title)}</h2>{content}</section>'
            for sid, title, content in sections)
        return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>{_esc(t('rpt_readiness_report_title', lang=lang))}</title>{_CSS}</head>"
                f"<body>{cover}<div class='report-shell'>{toc}"
                f"<main class='report-main'>{body}</main></div>{TABLE_JS}</body></html>")

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_Readiness_Report_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._render_html())
        return path
```

- [ ] **Step 4: 驗證 GREEN + 全套 + lint**：`python3 -m pytest tests/test_readiness_html_exporter.py -q`；`python3 -m pytest -q`；`ruff check` 改動檔零新增。
- [ ] **Step 5: Commit** `feat(readiness): readiness html exporter with print affordance and i18n`

---

### Task 3: generator.export()（html/csv/metadata sidecar）

**Refresh 變更點：** metadata sidecar 是 2026-07-05 GUI 報表卡機制後的**新必要接線**（原 plan 無此項）：`/api/reports` 讀 `<path>.metadata.json` 的 `report_type` 供 rcard last-run 分組，readiness sidecar 直接寫 `readiness`（不像 traffic 家族需要檔名 prefix 覆寫）。xlsx 降為非目標（沿 RHC v1）；CSV 用共用 `CsvExporter`（`report_label='Readiness'` 自動產生與 HTML 同 prefix 的 zip）。

**Files:**
- Modify: `src/report/readiness_report.py`（加 `export` + `_write_report_metadata`）
- Test: `tests/test_readiness_report.py` 擴充

**Interfaces:**
- Produces: `export(result, fmt='html', output_dir='reports', lang=None) -> list[str]`；`fmt in ('html','csv','all')`（其他值照 RHC 慣例產出空清單——GUI/CLI 各自有白名單守門）。
- 每個輸出檔寫 `<path>.metadata.json`：`report_type="readiness"`、`file_format`、`generated_at`、`record_count`、`date_range`、`kpis`（list 原樣——`/api/reports` 與 dashboard 直接透傳）。
- CSV 內容（完整值，是 HTML 截斷的復原路徑）：`queue`（queue_df）、`factor_table`、`recommendations`。

- [ ] **Step 1: 寫失敗測試（RED）**——`tests/test_readiness_report.py` 加：

```python
def test_export_html_writes_sidecar_with_report_type(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    result = gen.generate_from_api(output_dir=str(tmp_path))
    paths = gen.export(result, fmt="html", output_dir=str(tmp_path))
    assert len(paths) == 1 and paths[0].endswith(".html")
    import json
    with open(paths[0] + ".metadata.json", encoding="utf-8") as fh:
        meta = json.load(fh)
    assert meta["report_type"] == "readiness"
    assert meta["record_count"] == result.record_count


def test_export_all_writes_html_and_csv_zip(monkeypatch, tmp_path):
    gen = _gen(monkeypatch, _flows_df(), _workloads())
    result = gen.generate_from_api(output_dir=str(tmp_path))
    paths = gen.export(result, fmt="all", output_dir=str(tmp_path))
    exts = sorted(p.rsplit(".", 1)[-1] for p in paths)
    assert exts == ["html", "zip"]
    import os
    assert all(os.path.basename(p).startswith("Illumio_Readiness_Report_") for p in paths)
```

- [ ] **Step 2: 實作（GREEN）**——`ReadinessReportGenerator` 加（並在模組頂部補 `import json`、`import os`——Task 1 未用到，此時才加，避免 ruff F401）：

```python
    def export(self, result: ReadinessResult, fmt: str = 'html',
               output_dir: str = 'reports', lang: str | None = None) -> list[str]:
        from src.report.exporters.readiness_html_exporter import ReadinessHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter
        lang = lang or self._lang
        os.makedirs(output_dir, exist_ok=True)
        paths: list[str] = []
        mr = result.module_results or {}
        if fmt in ('html', 'all'):
            path = ReadinessHtmlExporter(result, lang=lang).export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, result, file_format='html')
            print(t("rpt_readiness_html_saved", path=path, lang=lang))
        if fmt in ('csv', 'all'):
            readiness = mr.get("readiness", {})
            # CSV carries FULL untruncated values (recovery path for the
            # HTML _CELL_MAX truncation).
            export_data = {}
            if mr.get("queue_df") is not None:
                export_data["queue"] = mr["queue_df"]
            for key in ("factor_table", "recommendations"):
                df = readiness.get(key)
                if df is not None and not getattr(df, "empty", True):
                    export_data[key] = df
            if export_data:
                path = CsvExporter(export_data, report_label='Readiness').export(output_dir)
                paths.append(path)
                self._write_report_metadata(path, result, file_format='csv')
                print(t("rpt_readiness_csv_saved", path=path, lang=lang))
        return paths

    def _write_report_metadata(self, report_path: str, result: ReadinessResult,
                               file_format: str) -> None:
        payload = {
            "report_type": "readiness",
            "file_format": file_format,
            "generated_at": result.generated_at.isoformat(),
            "record_count": int(result.record_count or 0),
            "date_range": list(result.date_range or ("", "")),
            "kpis": (result.module_results or {}).get("kpis", []),
        }
        with open(report_path + ".metadata.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
```

- [ ] **Step 3: 驗證 GREEN + 全套 + lint**。
- [ ] **Step 4: Commit** `feat(readiness): export html/csv with report_type sidecar`

---

### Task 4: Scheduler dispatch + 保留清理 prefix + email 標題

**Refresh 變更點：** `_REPORT_PREFIXES` 與 metadata sidecar 保留清理（`_prune_by_count` 以 report unit 計數）是原 plan 之後才存在的機制，必須註冊 `"readiness": "Illumio_Readiness_Report_"`（HTML 與 CSV zip 同 prefix，一條即可）；dispatch 分支位置改為 `rule_hit_count` 分支（:414）之後、`else` 之前；email 標題 map（`_send_report_email` :454）補 `readiness`（RHC 當時漏接，本案不重蹈）。

**Files:**
- Modify: `src/report_scheduler.py`
- Test: `tests/test_readiness_scheduler_dispatch.py`（新檔，樣式照 `tests/test_rule_hit_count_scheduler_dispatch.py`）

**Interfaces:**
- `report_schedules[].report_type` 支援 `readiness`；分支呼叫 `generate_from_api(start_date, end_date, lang, output_dir=output_dir)`（trend 快照寫進排程輸出目錄）＋ `export(result, fmt, output_dir)`；`record_count == 0` → warning + skip（家族慣例）。

- [ ] **Step 1: 寫失敗測試（RED）**——新檔 `tests/test_readiness_scheduler_dispatch.py`：

```python
"""Scheduler dispatch for the readiness report type."""
from __future__ import annotations

from src.report_scheduler import ReportScheduler


class _DummyConfigManager:
    def __init__(self):
        self.config = {"report": {"output_dir": "reports"}, "settings": {}}

    def load(self):
        pass


def _make_scheduler():
    return ReportScheduler(_DummyConfigManager(), reporter=None)


def test_generate_report_dispatches_readiness(monkeypatch, tmp_path):
    sched = _make_scheduler()
    calls = {}

    class _FakeResult:
        record_count = 9

    class _FakeGen:
        def __init__(self, cm, api_client=None, config_dir="config", cache_reader=None):
            calls["init"] = True

        def generate_from_api(self, start_date=None, end_date=None, lang="en",
                              use_cache=True, output_dir="reports"):
            calls["lang"] = lang
            calls["trend_out"] = output_dir
            return _FakeResult()

        def export(self, result, fmt="html", output_dir="reports", lang=None):
            calls["fmt"] = fmt
            return [str(tmp_path / "Illumio_Readiness_Report_x.html")]

    import src.report.readiness_report as mod
    monkeypatch.setattr(mod, "ReadinessReportGenerator", _FakeGen)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="readiness", api=object(), fmt="html",
        output_dir=str(tmp_path), start_date="2026-07-01T00:00:00Z",
        end_date="2026-07-08T23:59:59Z", name="Readiness", lang="zh_TW")

    assert calls["lang"] == "zh_TW"
    assert calls["trend_out"] == str(tmp_path)
    assert result.record_count == 9
    assert paths == [str(tmp_path / "Illumio_Readiness_Report_x.html")]


def test_zero_records_skips_export(monkeypatch, tmp_path):
    sched = _make_scheduler()

    class _FakeGen:
        def __init__(self, cm, api_client=None, config_dir="config", cache_reader=None):
            pass

        def generate_from_api(self, **kw):
            class _R:
                record_count = 0
            return _R()

    import src.report.readiness_report as mod
    monkeypatch.setattr(mod, "ReadinessReportGenerator", _FakeGen)
    monkeypatch.setattr("src.main._make_cache_reader", lambda cm: None)

    result, paths = sched._generate_report(
        report_type="readiness", api=object(), fmt="html",
        output_dir=str(tmp_path), start_date=None, end_date=None,
        name="Readiness empty", lang="en")
    assert result is None and paths == []


def test_readiness_prefix_registered():
    assert ReportScheduler._REPORT_PREFIXES["readiness"] == "Illumio_Readiness_Report_"
```

- [ ] **Step 2: 實作（GREEN）**——`src/report_scheduler.py`：

`rule_hit_count` 分支之後、`else` 之前插入：

```python
        elif report_type == "readiness":
            from src.report.readiness_report import ReadinessReportGenerator
            gen = ReadinessReportGenerator(self.cm, api_client=api, config_dir=self._config_dir,
                                           cache_reader=_make_cache_reader(self.cm))
            result = gen.generate_from_api(start_date=start_date, end_date=end_date,
                                           lang=lang, output_dir=output_dir)
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no traffic data — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir)
            return result, paths
```

`_REPORT_PREFIXES` 加一行（`rule_hit_count` 條目後）：

```python
        "readiness":         "Illumio_Readiness_Report_",
```

`_send_report_email` 的 `type_label` map 加：

```python
                      "readiness": t("rpt_readiness_report_title", lang=lang),
```

- [ ] **Step 3: 驗證 GREEN + 全套 + lint**。
- [ ] **Step 4: Commit** `feat(readiness): scheduler dispatch, prune prefix, and email title`

---

### Task 5: CLI `report readiness`

**Refresh 變更點：** 取消原 plan 的 `generate-readiness` alias（verb alias 僅為既有命令回溯相容；RHC 慣例新命令不建 alias）。`--days N` 改為家族一致的 `--start-date/--end-date`；`--format` 限 `html|csv|all`（xlsx 非目標）；加共用 `--data-source`（`_data_source_options`，cache-aware fetch）。

**Files:**
- Modify: `src/cli/report.py`（helper `generate_readiness_report` + `@report_group.command("readiness")`）
- Test: `tests/test_cli_report_commands.py` 擴充

**Interfaces:**
- `illumio-ops report readiness [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--format html|csv|all] [--output-dir DIR] [--data-source hybrid|live|cache-only]`。
- helper 簽章：`generate_readiness_report(*, start_date=None, end_date=None, fmt='html', output_dir=None, data_source=None, use_cache=True) -> list[str]`；`record_count == 0` → `click.ClickException(t("cli_report_no_data"))`。
- `fetch_traffic_df` 無 `clip_to_cache` 參數——`resolve_data_source` 的 clip 旗標捨棄（同 App Summary GUI 慣例），只取 `use_cache`。

- [ ] **Step 1: 寫失敗測試（RED）**——`tests/test_cli_report_commands.py` 加：

```python
def test_report_readiness_subcommand_dispatches_helper():
    from src.cli.root import cli

    runner = CliRunner()
    with patch("src.cli.report.generate_readiness_report",
               return_value=["/tmp/readiness.html"]) as mock_gen:
        result = runner.invoke(
            cli,
            ["report", "readiness", "--start-date", "2026-07-01",
             "--end-date", "2026-07-08", "--format", "csv"],
        )

    assert result.exit_code == 0
    assert "/tmp/readiness.html" in result.output
    mock_gen.assert_called_once_with(
        start_date="2026-07-01",
        end_date="2026-07-08",
        fmt="csv",
        output_dir=None,
        data_source=None,
        use_cache=True,
    )
```

- [ ] **Step 2: 實作（GREEN）**——`src/cli/report.py`。helper（放 `generate_rule_hit_count_report` 之後）：

```python
def generate_readiness_report(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
    data_source: str | None = None,
    use_cache: bool = True,
) -> list[str]:
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.main import _make_cache_reader
    from src.report.cache_support import cache_available, resolve_data_source
    from src.report.readiness_report import ReadinessReportGenerator

    cm = ConfigManager()
    api = ApiClient(cm)
    lang = _resolve_lang(cm)
    eff_ds = data_source if data_source is not None else ("cache" if use_cache else "no-cache")
    # fetch_traffic_df has no clip_to_cache knob — only use_cache applies here.
    use_cache, _clip, _ds_warn = resolve_data_source(eff_ds, cache_available(cm))
    if _ds_warn:
        click.echo(t("cli_report_data_source_warning", msg=_ds_warn, lang=lang), err=True)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    gen = ReadinessReportGenerator(cm, api_client=api, config_dir=config_dir,
                                   cache_reader=_make_cache_reader(cm))
    result = gen.generate_from_api(
        start_date=_iso_date(start_date, end_of_day=False),
        end_date=_iso_date(end_date, end_of_day=True),
        lang=lang, use_cache=use_cache, output_dir=out)
    if result.record_count == 0:
        raise click.ClickException(t("cli_report_no_data", lang=lang))
    return gen.export(result, fmt=fmt, output_dir=out, lang=lang)
```

指令（錯誤處理樣板照 `report_ven_status`）：

```python
@report_group.command("readiness")
@click.option("--start-date", default=None, help="Start date (YYYY-MM-DD).")
@click.option("--end-date", default=None, help="End date (YYYY-MM-DD).")
@click.option("--format", "fmt", type=click.Choice(["html", "csv", "all"]), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@_data_source_options
@click.pass_context
def report_readiness(ctx: click.Context, start_date: str | None, end_date: str | None,
                     fmt: str, output_dir, data_source, legacy_cache) -> None:
    """Generate the Enforcement Readiness report (which app to enforce next)."""
    data_source, use_cache = _resolve_cli_data_source(data_source, legacy_cache)
    try:
        paths = generate_readiness_report(start_date=start_date, end_date=end_date,
                                          fmt=fmt, output_dir=output_dir,
                                          data_source=data_source, use_cache=use_cache)
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("readiness report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)
```

注意：helper 內 `_iso_date`（`src/cli/report.py:38` 既有）已處理 bare date → ISO；generator 的 `_iso_window` 對已是 ISO 的值是 no-op，雙保險不衝突。

- [ ] **Step 3: 驗證 GREEN + 全套 + lint**。
- [ ] **Step 4: Commit** `feat(cli): report readiness subcommand`

---

### Task 6: GUI 接線（route + 卡片 + modal + 排程選項）+ 端到端樣本驗證

**Refresh 變更點：** 原 plan 完全沒有 GUI task——GUI 報表卡三分拆（2026-07-05 013ed6b）後，新報表型別必須接前端全鏈：rcard 卡片、`openReportGenModal` meta、`confirmReportGen` dispatch、`_doGenerateReadiness`、排程下拉選項、`typeLabels` ×2、data-source 支援名單；GUI generate route 帶 `@limiter.limit("10 per hour")`（報表 rate limit 機制為新慣例）。rcard last-run 不需檔名 prefix 覆寫（sidecar `report_type` 已正確為 `readiness`）。FilterBar 不接（僅 traffic 三卡適用）。末段執行 CLAUDE.md 實際樣本逐頁檢查與文件更新。

**Files:**
- Modify: `src/gui/routes/reports.py`（`POST /api/readiness_report/generate`，插在 rule_hit_count 三 route 之後）
- Modify: `src/templates/index.html`（rcard：`rule_hit_count` 卡（:1412-1423）後、`policy_diff` 卡（:1425）前；排程選項：:1567 `rule_hit_count` option 後）
- Modify: `src/static/js/dashboard.js`（見 Interfaces）
- Modify: `src/i18n_en.json`、`src/i18n/data/zh_explicit.json`（GUI keys ＋ precompute）
- Modify: `README.md`、`README_zh.md`、`CHANGELOG.md`、ops manual（新報表條目）
- Test: `tests/test_gui_readiness_generate.py`（新檔，樣式照 `tests/test_gui_rule_hit_count_generate.py`）

**Interfaces:**
- Route：`POST /api/readiness_report/generate`，payload `{start_date, end_date, format, lang, data_source?}`；`@limiter.limit("10 per hour")`；`_data_source_from_payload(d, cache_available(cm))` 取 `use_cache`（clip 捨棄）；`record_count == 0` → `{"ok": False, "error": t("gui_no_traffic_data", lang)}`；成功回 `{"ok": True, "files": [...], "record_count", "kpis"}`。
- dashboard.js 接點（全部照 RHC 對應位置）：
  1. `renderSchedules` `typeLabels` 加 `readiness: _t('gui_sched_rt_readiness')`。
  2. `openReportGenModal` `meta` 加 `readiness: { titleKey: 'gui_gen_readiness_title', icon: '#icon-shield', dates: true }`（走既有 else 分支：無 source row、無 filters、顯示日期）。
  3. `openReportGenModal` 的 `supportsCache` 判斷（`dsRow` 一段）改為 `(TRAFFIC_PROFILE_TYPES.includes(type) || type === 'app_summary' || type === 'readiness')`——readiness 經 `fetch_traffic_df` 是 cache-capable。（`toggleTrafficSource` 內的同名判斷不用改：readiness 無 source row，不會經過該路徑。）
  4. `confirmReportGen` `typeLabels` 加 `readiness: _t('gui_gen_readiness_title')`；dispatch 加 `else if (_genReportType === 'readiness') await _doGenerateReadiness();`。
  5. 新函式 `_doGenerateReadiness()`：payload 組裝如下，成功/失敗處理與進度 helpers **照 `_doGenerateVen` 逐行同構**（僅 endpoint 與 payload 不同）：

```js
async function _doGenerateReadiness() {
  const fmtEl = document.getElementById('m-gen-format');
  const langEl = document.getElementById('m-gen-lang');
  const payload = {
    format: fmtEl ? fmtEl.value : 'html',
    lang: langEl ? langEl.value : 'en',
    start_date: $('m-gen-start').value,
    end_date: $('m-gen-end').value,
  };
  const dsRow = $('m-gen-data-source-row');
  const dsSel = $('m-gen-data-source');
  if (dsSel && dsRow && dsRow.style.display !== 'none') payload.data_source = dsSel.value;
  _updateGenStep(_t('gui_gen_step_fetching'));
  // ...成功/失敗處理照 _doGenerateVen（post('/api/readiness_report/generate', payload)）
}
```

- **GUI i18n keys（三檔流程，同 Task 2 規則）：**

| key | en |
|---|---|
| `gui_rcard_readiness_title` | Enforcement Readiness Report |
| `gui_rcard_readiness_desc` | Which app (env) can safely move to enforcement next — readiness score, blocking factors, and remediation queue. |
| `gui_gen_readiness_title` | Generate Enforcement Readiness Report |
| `gui_sched_rt_readiness` | Enforcement Readiness |

- index.html rcard（`data-action`/結構照 rule_hit_count 卡逐行同構）：

```html
<div class="rcard" data-rtype="readiness">
<div class="rcard-icon"><svg class="icon" aria-hidden="true"><use href="#icon-shield"></use></svg></div>
<div class="rcard-body">
<h3 data-i18n="gui_rcard_readiness_title">Enforcement Readiness Report</h3>
<p data-i18n="gui_rcard_readiness_desc">Which app (env) can safely move to enforcement next — readiness score, blocking factors, and remediation queue.</p>
<div class="rcard-meta"><span class="rcard-meta-last"></span><span class="rcard-meta-sched"></span></div>
</div>
<div class="rcard-actions">
<button class="btn btn-primary btn-sm" id="btn-gen-readiness" data-action="openReportGenModal" data-args='["readiness"]'>
<svg class="icon" aria-hidden="true"><use href="#icon-play"></use></svg> <span data-i18n="gui_rcard_generate">Generate</span></button>
</div>
</div>
```

（`rcard-actions` 按鈕列的實際 class/結構以 rule_hit_count 卡現貌為準——複製後只改 id/data-args/i18n keys。）

- 排程下拉（:1567 後）：

```html
<option value="readiness" data-i18n="gui_sched_rt_readiness">Enforcement Readiness</option>
```

- [ ] **Step 1: 寫失敗測試（RED）**——新檔 `tests/test_gui_readiness_generate.py`（共用 conftest 的 `client` fixture；login/CSRF/patch 慣例照 `tests/test_gui_rule_hit_count_generate.py`）：

```python
"""GUI endpoint tests for the readiness report generation route."""
from unittest.mock import MagicMock, patch

from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def _fake_result(count=5):
    r = MagicMock()
    r.record_count = count
    r.module_results = {"kpis": [{"i18n_key": "rpt_readiness_kpi_score",
                                  "label": "Readiness Score", "value": 80}]}
    return r


def test_generate_readiness_returns_files(client):
    csrf_token = _login(client)
    with patch("src.report.readiness_report.ReadinessReportGenerator") as MockGen:
        MockGen.return_value.generate_from_api.return_value = _fake_result()
        MockGen.return_value.export.return_value = [
            "/tmp/x/Illumio_Readiness_Report_x.html"]
        r = client.post(
            "/api/readiness_report/generate",
            json={"start_date": "2026-07-01", "end_date": "2026-07-08",
                  "format": "html", "lang": "zh_TW", "data_source": "live"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is True
    assert body["files"] == ["Illumio_Readiness_Report_x.html"]
    assert body["record_count"] == 5
    kw = MockGen.return_value.generate_from_api.call_args.kwargs
    assert kw["lang"] == "zh_TW"
    assert kw["use_cache"] is False   # data_source=live


def test_generate_readiness_zero_records_returns_error(client):
    csrf_token = _login(client)
    with patch("src.report.readiness_report.ReadinessReportGenerator") as MockGen:
        MockGen.return_value.generate_from_api.return_value = _fake_result(count=0)
        r = client.post(
            "/api/readiness_report/generate", json={"lang": "en"},
            headers={"X-CSRF-Token": csrf_token},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] is False and body.get("error")
    MockGen.return_value.export.assert_not_called()
```

- [ ] **Step 2: 實作 route（GREEN）**——`src/gui/routes/reports.py`（rule_hit_count 三 route 後插入；helpers 皆為檔內既有）：

```python
    @bp.route('/api/readiness_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_readiness_report():
        d = request.json or {}
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.api_client import ApiClient
            from src.main import _make_cache_reader
            from src.report.readiness_report import ReadinessReportGenerator
            cm.load()
            api = ApiClient(cm)
            use_cache, _clip, _ds_warn = _data_source_from_payload(d, cache_available(cm))
            gen = ReadinessReportGenerator(cm, api_client=api,
                                           cache_reader=_make_cache_reader(cm))
            output_dir = _resolve_reports_dir(cm)
            result = gen.generate_from_api(start_date=d.get('start_date'),
                                           end_date=d.get('end_date'),
                                           lang=lang, use_cache=use_cache,
                                           output_dir=output_dir)
            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_traffic_data", lang=lang)})
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'html'
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, lang=lang)
            return jsonify({"ok": True,
                            "files": [os.path.basename(p) for p in paths],
                            "record_count": result.record_count,
                            "kpis": result.module_results.get('kpis', [])})
        except Exception as e:
            return _err_with_log("report_readiness_generate", e, lang=lang)
```

- [ ] **Step 3: 前端接線**——依 Interfaces 清單完成 index.html 與 dashboard.js 六處修改；GUI i18n keys 走三檔流程（en + zh_explicit + `python3 -m scripts.precompute_zh_translations --write`）。跑 `python3 -m pytest tests/test_gui_readiness_generate.py -q` GREEN；另跑既有 i18n 守門測試（`python3 -m pytest -q -k i18n`）確認 JS/HTML 引用的 keys 都存在。
- [ ] **Step 4: 端到端樣本驗證（CLAUDE.md 報表規範，必做）**：
  - 用實際樣本資料（lab PCE 或既有 flows cache）跑 `python3 illumio-ops.py report readiness --format all`（en 與 zh_TW 各一次，zh 用 config 語言切換）。
  - 逐頁檢查：封面、5 章目錄錨點、推進佇列長 `recommended_action`/`current_mode` 的截斷＋`title` hover、`@media print` 列印預覽不溢出、zh 版無殘留英文 key。
  - 連跑兩次確認趨勢章出現 delta。
  - GUI 手動煙霧：報表卡出現、last-run 顯示、modal 產出成功、排程建立 `readiness` 型別成功。
  - **檢查結果（每頁確認清單）附在完成回報裡。**
- [ ] **Step 5: 文件**：`README.md`／`README_zh.md` 報表清單加 Enforcement Readiness；`CHANGELOG.md` 加條目；ops manual（`docs/` 下營運手冊）補新報表一節。
- [ ] **Step 6: 全套 + lint**：`python3 -m pytest -q` 全綠；`ruff check` 改動檔零新增。
- [ ] **Step 7: Commit** `feat(gui): readiness report card, generate route, and schedule wiring`

---

## 完成定義

- `report readiness` cache-only 一分鐘內產出；推進佇列直接回答「下一步開哪裡」（最就緒在最上）。
- Security 報表 readiness 章與獨立報表分數一致（同一 `enforcement_readiness`，同 df 同 workloads 條件下）。
- 七處接線全通：sidecar `report_type=readiness`、scheduler dispatch、`_REPORT_PREFIXES`、CLI、GUI route、GUI 前端（卡片/modal/排程）、i18n en+zh。
- pytest 全綠、ruff 零新增；README（英中）、CHANGELOG、ops manual 已列新報表。
- CLAUDE.md 逐頁檢查結果已附在回報。

## Self-Review 紀錄（refresh 自檢）

- 型別一致：`enforcement_readiness` 簽章、`fetch_traffic_df`、`fetch_managed_workloads`、trend_store 六個函式、`CsvExporter`、`build_cover_page`、`_data_source_from_payload`、scheduler `_generate_report` 簽章皆已對 main @570c52b 原始碼逐一核實（非憑記憶）。
- `_score_to_grade`／`_normalize_key_series` 為 mod13 模組私有；本 plan 選擇 import 私有函式換取等第/正規化單一來源，已在程式碼註解標明理由。
- 無 placeholder：所有測試與實作程式碼完整可執行；僅 `_doGenerateReadiness` 的進度/錯誤 boilerplate 與 rcard 按鈕列結構明確指向「照 `_doGenerateVen`／rule_hit_count 卡逐行同構」的既有範本。
- 已知風險：`recommendations` 的 `Action` 欄為已本地化字串（mod13 以 `lang` 產生），佇列 `recommended_action` 因此隨報表語言一致——符合預期，不需雙語欄。
