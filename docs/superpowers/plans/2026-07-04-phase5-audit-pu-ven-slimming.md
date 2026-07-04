# Phase 5：Audit / Policy Usage / VEN 報表精簡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 spec I/J/K 節精簡三份報表：Audit 近期事件 HTML 砍 10 筆（完整清單補進 XLSX、CSV 已天然完整）、KPI 標籤真正中文化、SVG 去 metadata；PU unused 卡片 HTML 砍 50、mod05 三張同構表合併加風險類型欄；VEN Online 章改計數+版本分布（明細只留 offline/失聯桶；XLSX/CSV 全列保留）。

**Architecture:** 全部遵循「HTML 給結論、明細給 CSV/XLSX」原則：HTML 端只動渲染層 cap 與章節形式；資料層（builder 上限、_analyze 桶、XLSX sheet）除 audit XLSX 補 recent 外一律不動。K1 已由 XLSX 統一案完成，本期只做 K2 且僅 HTML。

**Tech Stack:** Python / pytest / matplotlib(SVG)。

**Spec:** `docs/superpowers/specs/2026-07-02-traffic-security-report-split-design.md` I（3 項）/J（2 項）/K2。

## Global Constraints

- 註解繁中、無 emoji；commit 英文 conventional-commits；每 task 一個 commit；surgical；TDD。
- **環境三道防線**：每個 Bash 命令 `cd <worktree 絕對路徑> && ` 開頭；commit 前 rev-parse 驗證、後 log+branch 確認；禁主 checkout 寫操作；**commit 用明確檔案清單，禁 `git add -A`**。
- **趨勢/快照穩定性**：audit mod00 builder 的英文 `label` 不動（trend canonicalize 相依）——中文化只在顯示層（_exec_summary 解析順序 + XLSX label 取值）。
- **明細層不動**：mod03(PU) `_MAX_ROWS=1000`、audit recent builder `.head(50)`、VEN `_analyze` 桶與 XLSX/CSV 輸出（audit XLSX 補 recent 除外）。
- i18n 兩 json en/zh 同步、檔尾單一 newline；glossary 合規。
- `render_matplotlib_svg` 是共用函式——I3 改動影響所有 SVG 報表，回歸以既有 chart 測試 + 全套鎖定。
- 定位以程式碼內容為準（行號會漂移）。

## 現況地圖（盤點 @1c4c68c，實作者速查）

| 對象 | 事實 |
|---|---|
| I1 recent | 三 builder `.head(50)`：audit_mod01_health.py:110-111、mod02_users:128-133、mod03_policy:166-167（**builder 不動**）；HTML 全列渲染：audit_html_exporter.py:381/:424/:486（`_df_to_html(m.get("recent"), ...)`）；i18n `rpt_au_recent`（兩 json :2775，「(up to 50)/（最多 50 筆）」）；CSV 已含 per-module recent + raw_events 全量（audit_generator.py:752-760 + csv_exporter 遞迴）；**XLSX 無 recent**（generate_audit_xlsx :808-862 只有 summary 類 sheet） |
| I2 KPI | mod00 kpis 每項已帶 `label_key`（rpt_au_kpi_* ×12，兩 json 皆備）+ 英文 `label`；渲染走 `render_exec_summary_html` → `_exec_summary.py:13-22 _resolve_label` **優先取 label（英文）**；audit_html_exporter :180-191 的 `_kpi_label`+`kpi_cards` 是死碼（從未拼進 body）；XLSX Attention sheet 用 `k.get("label")` 英文（audit_generator.py:831-833）；metadata/trend 塞英文 label（:795、canonicalize :768-776——**不可動**） |
| I3 SVG | `chart_renderer.py:238-247 render_matplotlib_svg`：`fig.savefig(buf, format="svg")` 無 metadata 參數→輸出含 `<metadata>`（RDF/dc:date）；共用於 audit(:234/:419/:481 經 _chart_html)與其他 SVG 報表；測試 test_chart_static_svg.py 僅斷言含 `<svg` |
| J1 unused | builder cap 1000（pu_mod03:12/:45，**不動**）；HTML 卡片全列：policy_usage_html_exporter `_mod03_html` :478-507 → `_rule_cards_html`（:33-101，共用於 mod02 hit——**cap 加在 _mod03_html 呼叫端**）；CSV unused_rules = 同一 unused_df（cap 1000）；XLSX Unused sheet 同源 cap 1000（護欄測試 test_xlsx_content_policy_usage.py:77-85） |
| J2 mod05 | pu_mod05_draft_pd.py `pu_draft_pd_summary`：三同構 group（visibility_risk/draft_conflicts/draft_coverage，:38-40），各 `{total, by_subtype, top_pairs}`；top_pairs 欄位相同（Src/Dst/Port/Draft Decision/Connections，`most_common(20)` :60-63）；差異=風險類型維度（_GROUP_A/_B/group_c，:19-21/:28-34）；渲染 `_mod05_html` :289-349 三段近乎複製（表格 :310-313/:327-330/:344-347，同標題 key rpt_pu_draft_pd_top_pairs）；**零測試覆蓋**；XLSX 不含 mod05 |
| K2 | ven_html_exporter：Online 章 :184 全列明細（無 gate）；offline/lost 桶 :186-194（有 visible_in gate）；by_version 已在 Estate 段呈現（:294-309）；summary pills :229-246；`_analyze` 的 online DataFrame/XLSX Online sheet/CSV **全部保留**（「明細給 XLSX」原則，spec 原文佐證）；email/snapshot/dashboard 不消費 online 明細；**現無任何測試斷言 HTML Online 明細列** |

---

### Task 1: Audit 近期事件 HTML 10 筆 + XLSX 補 recent（spec I1）

**Files:**
- Modify: `src/report/exporters/audit_html_exporter.py`（三處 recent 渲染加 `.head(10)`）
- Modify: 兩 json（`rpt_au_recent` 文案改「最多顯示 10 筆，完整清單見 CSV/XLSX 匯出」/en 對應）
- Modify: `src/report/audit_generator.py`（`generate_audit_xlsx`：Health/Users/Policy Changes 三 sheet 改 `add_stacked_tables_sheet`（summary + recent 兩段），沿用 XU 共用 helper）
- Test: `tests/test_audit_slimming.py`（新檔）+ `tests/test_xlsx_content_audit.py`（增 recent 斷言）

**Interfaces:** builder 回傳零變更；XLSX 三 sheet 從單表變堆疊（summary 子表 + recent 子表，子標題沿用 `rpt_au_recent` 的 en 值與既有 audit 硬編慣例）。

- [ ] **Step 1: RED 測試**

`tests/test_audit_slimming.py`：
```python
"""Audit 近期事件精簡（spec I1）：HTML 10 筆、XLSX 完整 50 筆。"""
import pandas as pd
from src.report.exporters.audit_html_exporter import AuditHtmlExporter  # 以實際類名為準


def _recent_df(n=50):
    return pd.DataFrame([{"timestamp": f"2026-06-01T00:{i:02d}:00Z",
                          "event_type": f"evt.{i}", "severity": "info"} for i in range(n)])


def _results():
    return {"mod00": {"kpis": [], "attention_items": []},
            "mod01": {"summary": pd.DataFrame([{"Event Type": "x", "Count": 1}]),
                      "severity_breakdown": pd.DataFrame(), "connectivity_events": pd.DataFrame(),
                      "security_concerns": pd.DataFrame(), "recent": _recent_df(),
                      "total_health_events": 50, "security_concern_count": 0,
                      "connectivity_event_count": 0},
            "mod02": {}, "mod03": {}, "mod04": {}}


def test_html_recent_capped_at_10():
    html = AuditHtmlExporter(_results(), lang="en").build()   # 建構方式以既有測試為準
    assert html.count("evt.9") == 1 and "evt.10" not in html  # 第 11 筆不渲染
```
（建構最小化參考既有 audit exporter 測試 fixture；斷言方式若 evt.1X 子字串撞 evt.1 需調整為精確 cell 比對——實作時確保判別力。）
`tests/test_xlsx_content_audit.py` 增：Health sheet 含 recent 子表列（fixture 的 mod01 加 recent 3 列，斷言 sheet 內含其 event_type 值與 `rpt_au_recent` 子標題列）。

- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**——三處渲染改 `_df_to_html((m.get("recent") if m.get("recent") is None else m.get("recent").head(10)), ...)` 形式（以可讀方式寫：先取 `recent = m.get("recent")`，非空則 `recent = recent.head(10)`）；i18n 文案改值；`generate_audit_xlsx` 三 sheet 改 `add_stacked_tables_sheet(wb, title, [(summary_subtitle, summary_df), (recent_subtitle, recent_df)], ...)`（缺 key 容錯照舊）。
- [ ] **Step 4: 聚焦 + 全套**：`python3 -m pytest tests/test_audit_slimming.py tests/test_xlsx_content_audit.py -v && python3 -m pytest -q`
- [ ] **Step 5: Commit** `feat(audit): cap recent events at 10 in html, full list in xlsx`

---

### Task 2: Audit KPI 標籤中文化（spec I2）

落點裁決（盤點依據）：i18n key 已全備、缺口在顯示層解析順序。**builder 的英文 label 不動**（trend canonicalize 相依）。

**Files:**
- Modify: `src/report/exporters/_exec_summary.py`（`_resolve_label` 改為：label_key/i18n_key 可解析時優先、否則 fallback `label`）
- Modify: `src/report/audit_generator.py`（XLSX Attention sheet：`t(k["label_key"], lang=lang)` 優先、fallback label）
- Modify: `src/report/exporters/audit_html_exporter.py`（刪除死碼 `_kpi_label`/`kpi_cards` :180-191——本 task 的順手清理，記 commit body）
- Test: `tests/test_audit_kpi_i18n.py`（新檔）

**Interfaces:** `_resolve_label` 是全報表 exec summary 共用——mod12/ven/pu 的 kpis 各自形狀（mod12 label 已在地化且帶 label_key；ven 用 i18n_key）：新順序對它們輸出不變或更正確（實作時以三報表的 exec summary 輸出各寫一個回歸斷言）。

- [ ] **Step 1: RED 測試**

```python
"""Audit KPI 標籤中文化（spec I2）。"""
from src.report.exporters._exec_summary import _resolve_label


def test_audit_kpi_resolves_zh():
    kpi = {"label_key": "rpt_au_kpi_total_events", "label": "Total Events", "value": "12"}
    assert _resolve_label(kpi, lang="zh_TW") == "事件總數"


def test_fallback_to_label_when_key_missing():
    kpi = {"label_key": "rpt_no_such_key_xyz", "label": "Fallback", "value": "1"}
    assert _resolve_label(kpi, lang="zh_TW") == "Fallback"


def test_mod12_style_kpi_unchanged():
    # mod12 的 label 已在地化且 label_key 同值解析——輸出不變
    kpi = {"label_key": "mod12_kpi_total_flows", "label": "流量總數", "value": "9"}
    out = _resolve_label(kpi, lang="zh_TW")
    assert out  # 具體值以實際 i18n 值斷言（實作時填入，不可空殼）
```
（`_resolve_label` 現簽名以實檔為準——若不吃 lang 需加參數並更新唯一呼叫端 render_exec_summary_html；三報表回歸斷言在實作時補完。）

- [ ] **Step 2: 確認 FAIL**（現況回英文 label）
- [ ] **Step 3: 實作（GREEN）**——解析順序：`label_key`/`i18n_key` 經 t()/STRINGS 解析成功（回值 != key 名）→ 用之；否則 `label`；否則 key 名。XLSX Attention 同步。刪死碼段。
- [ ] **Step 4: 聚焦 + 全套**：`python3 -m pytest tests/test_audit_kpi_i18n.py tests/test_report_no_kpi_duplication.py tests/test_xlsx_content_audit.py -v && python3 -m pytest -q`（trend/metadata 相關測試必須綠——builder 未動的證明）
- [ ] **Step 5: Commit** `fix(audit): resolve kpi labels through i18n keys in display layers`

---

### Task 3: SVG 去 metadata 瘦身（spec I3）

**Files:**
- Modify: `src/report/exporters/chart_renderer.py`（`render_matplotlib_svg` 的 savefig 加 `metadata={"Date": None, "Creator": None}`；若實測 `<metadata>` 區塊仍在，改為輸出後字串移除 `<metadata>...</metadata>`——兩法擇實測有效者，報告記錄）
- Test: `tests/test_chart_static_svg.py`（增斷言）

- [ ] **Step 1: RED 測試**——增 `test_svg_has_no_metadata_block`：`render_matplotlib_svg(spec)` 輸出不含 `<metadata`、不含 `dc:date`。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**——共用函式改動；跑 `tests/test_chart_static_svg.py tests/test_html_exporter_static_charts.py tests/test_html_size.py` 確認全 SVG 消費者無回歸。
- [ ] **Step 4: 全套**
- [ ] **Step 5: Commit** `perf(report): strip metadata from embedded matplotlib svg`

---

### Task 4: PU unused 卡片 HTML 50 列（spec J1）

**Files:**
- Modify: `src/report/exporters/policy_usage_html_exporter.py`（`_mod03_html`：傳入 `_rule_cards_html` 前 `unused_df.head(50)`；`{count} rows` 註記改「顯示前 50 筆（共 {count} 筆，完整清單見 CSV/XLSX）」形式——超過 50 才顯示此形式，i18n 新 key）
- Modify: 兩 json（新 key `rpt_pu_unused_truncated`，en/zh）
- Test: `tests/test_pu_slimming.py`（新檔）

**約束**：cap 在 `_mod03_html` 呼叫端——mod02 hit 卡片（共用 `_rule_cards_html`）不受影響（測試鎖定）。builder cap 1000 不動；CSV/XLSX 同源護欄測試（xlsx :77-85）必須綠。

- [ ] **Step 1: RED 測試**——fixture unused_df 60 列：HTML 只含前 50 列的 rule id、第 51 筆不在、truncated 註記在；hit 卡片 60 列全渲染（反例）。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**
- [ ] **Step 4: 聚焦 + 全套**：含 test_xlsx_content_policy_usage.py（同源護欄）
- [ ] **Step 5: Commit** `feat(policy-usage): cap unused rule cards at 50 in html with full list note`

---

### Task 5: PU mod05 三表合併 + 風險類型欄（spec J2）

設計：**各自 Top 20 保留**（全域 Top 20 會被單一類型洗版——決策記 commit body），合併為一張表：新欄 `Risk Type`（值 = visibility_risk/draft_conflicts/draft_coverage 的 i18n 顯示名），列序 = 類型分組後各依 Connections 降序。分析端新增 `merged_top_pairs` key（三個既有 group key **保留**——向後相容），exporter 三段渲染改為單段（pills 保留三組 by_subtype 統計）。

**Files:**
- Modify: `src/report/analysis/policy_usage/pu_mod05_draft_pd.py`（新 `merged_top_pairs` 建構）
- Modify: `src/report/exporters/policy_usage_html_exporter.py`（`_mod05_html` :289-349 三段 → pills×3 + 單表）
- Modify: 兩 json（`Risk Type` 欄的三個類型顯示名 key + 表標題沿用 rpt_pu_draft_pd_top_pairs）
- Test: `tests/test_pu_mod05_merge.py`（新檔——本模組首個測試，含 builder 三 group 語意鎖定）

- [ ] **Step 1: RED 測試**——合成 rows 含三類 draft decision：`merged_top_pairs` 含 Risk Type 欄、各類列數 ≤20、類內 Connections 降序；三個既有 group key 原樣；HTML 單表渲染（rpt_pu_draft_pd_top_pairs 只出現一次）+ 三組 pills 仍在。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**
- [ ] **Step 4: 聚焦 + 全套**
- [ ] **Step 5: Commit** `feat(policy-usage): merge draft-pd top-pair tables with risk type column`

---

### Task 6: VEN Online 章改計數+版本分布（spec K2，HTML only）

範圍裁決（盤點+spec 原文）：「明細給 XLSX」——`_analyze` online DataFrame、XLSX Online sheet、CSV 全列**全部保留**；只改 HTML Online 章。

**Files:**
- Modify: `src/report/exporters/ven_html_exporter.py`（Online 章 :184：`_df_to_html(df_online)` 改為「計數摘要 + 版本分布小表（online 桶內的 version 分布，現場自 df_online['VEN Version'] value_counts——渲染層聚合，非新資料 key）+ 指向 XLSX 明細的 note」；offline/lost 三章不動；nav/pills 不動）
- Modify: 兩 json（新 key `rpt_ven_online_detail_note`：en "Per-host online detail is available in the XLSX/CSV export." / zh "Online 主機逐台明細見 XLSX/CSV 匯出。"）
- Test: `tests/test_ven_online_summary.py`（新檔）

**注意**：Estate 段已有全 estate 的 by_version（:294-309）——Online 章的版本分布是 **online 桶限定**（語意不同，實作時 subnote 註明「僅 Online 主機」）；若 df_online 無 `VEN Version` 欄（`_clean` 後欄名——盤點確認有）容錯空表。

- [ ] **Step 1: RED 測試**——fixture online 3 台兩種版本：HTML Online 章含計數與兩版本列、**不含** online 主機 hostname（明細移除的判別）；offline 章 hostname 仍在；note key 出現。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**
- [ ] **Step 4: 聚焦 + 全套**：含 tests/test_xlsx_content_ven.py（XLSX 全列保留護欄）、test_ven_report_compact.py（_analyze 不動）
- [ ] **Step 5: Commit** `feat(ven): online chapter shows counts and version split, detail stays in xlsx`

---

### Task 7: 樣本 E2E + CHANGELOG + 手冊

- [ ] **Step 1: E2E（專案 CLAUDE.md 硬性規則）**——合成資料產出 audit（60 事件驗 HTML recent=10/XLSX recent=50/KPI zh 中文/SVG 無 metadata）、policy usage（unused 60 驗 HTML 50+註記/XLSX 60；mod05 三類資料驗合併表）、ven（online 3 台驗計數+版本+無 hostname；XLSX Online 全列）三報表 en/zh，逐項 grep 證據；長輸出逐頁檢查截斷/溢出。
- [ ] **Step 2: 回歸**——全套 + naive-datetime。
- [ ] **Step 3: CHANGELOG（六點）+ 手冊 en/zh 同步（surgical）**。
- [ ] **Step 4: Commit** `docs: document audit/policy-usage/ven slimming (phase 5)`

---

## Self-Review 檢核

1. **Spec 覆蓋**：I1→T1；I2→T2；I3→T3；J1→T4；J2→T5；K2→T6；K1 已由 XLSX 統一案交付（ledger 引註）。
2. **相依**：T1-T6 相互獨立（T1/T2 同動 audit_generator/audit_html_exporter——按序執行避免 rebase 噪音）；T7 收尾。
3. **明細層鐵律**：builder caps/_analyze/XLSX 全列（audit recent 補進 XLSX 除外）逐 task 以護欄測試鎖定。
4. **共用面風險**：T2 `_resolve_label`（全報表 exec summary）與 T3 `render_matplotlib_svg`（全 SVG 報表）各要求三消費者回歸斷言。
5. **T5 為 mod05 首個測試**——builder 三 group 既有語意一併鎖定（不只新功能）。
