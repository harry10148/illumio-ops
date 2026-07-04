# Phase 4：顯示層修正 + PDF/表格版面一致性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 spec F 節（actor 顯示解析、GUI badge 移除、draftpolicy i18n、port 千分位）與 N 節（全報表列印按鈕、表格版面）完成顯示層一致性修正。

**Architecture:** 全部為顯示層/前端/CSS/i18n 變更：actor 解析只動顯示函式（API payload 契約零觸碰）；badge 只刪前端渲染（metadata 資料鏈全保留——email/summary/dashboard 多方共用）；port 豁免用欄名精確匹配（避免誤傷 "Unique Ports" 計數欄）；print 按鈕補到僅缺的兩個 exporter 並加守門掃描測試。

**Tech Stack:** Python / JS（vanilla）/ CSS / pytest。

**Spec:** `docs/superpowers/specs/2026-07-02-traffic-security-report-split-design.md` F 節全部 4 項 + N 節。

## Global Constraints

- 註解繁中、無 emoji；commit 英文 conventional-commits；每 task 一個 commit；surgical；TDD。
- **環境三道防線**：每一個 Bash 命令以 `cd <worktree 絕對路徑> && ` 開頭；commit 前 `git rev-parse --show-toplevel` 驗證、commit 後 log+branch 確認；禁止主 checkout 寫操作，誤操作停止回報。
- **API payload 契約零觸碰**：`traffic_query.py` 的 `{"actors":"ams"}` 產生、`labels.py:306-332` 的 filter 正規化、payload 契約測試（test_api_client.py:155/164）一律不動。
- **badge 資料鏈零觸碰**：`attack_summary_counts()`、metadata schema、email 渲染、dashboard_summaries、`rp.summary` 字串——只刪前端 badge 渲染。
- actor/service 顯示值慣例為英文硬編字面（"Any"/"All Services"）——"All Workloads" 同樣英文字面，不走 i18n。
- i18n 兩 json en/zh 同步、檔尾單一 newline；glossary 合規。
- **不在 BASE_CSS 內新增 `@media print` 區塊**（test_report_print_layout.py 以 `split('@media print')[1]` 取段，新增會位移斷言）。
- 定位以程式碼內容為準。

## 現況地圖（盤點 @ddd616c，實作者速查）

| 對象 | 事實 |
|---|---|
| F1 主函式 | `src/api/labels.py:446-459` `resolve_actor_str`：`{'actors':'ams'}` → `str()` 直印 "ams"（:458）；只認 label/ip_list/actors 三種 key，其他形狀**靜默丟棄**（無 else）；fallback 值慣例英文硬編（"Any"/"Label"/"IPList"） |
| F1 fallback | `src/report/analysis/policy_usage/pu_mod02_hit_detail.py:126-151` `_resolve_actors`：api_client 缺席時 :137/:150 `str(actor)` 直印 raw dict；:140 ams 印 "ams"；欄位鏈 `_build_row` :102-103 → "Destination"=providers、"Source"=consumers；pu_mod03 重用（:10/:75-76） |
| F1 測試現況 | `resolve_actor_str` 零單元測試；XLSX 測試用預建字串 row 不經解析——修改安全但需自建 regression |
| F2 badge | `src/static/js/dashboard.js:605-626` `_buildAttackSummaryMeta` + 呼叫點 :110-115；純 inline style 無專屬 CSS class；i18n `gui_attack_summary_title`（兩 json :1258 + dashboard_approved.json:11,17 + zh_explicit.json:286）；`tests/test_gui_dashboard.py:164` 斷言的是 API metadata 欄位（不可斷），非 badge DOM |
| F3 | `rpt_cat_draftpolicy_name/_desc` en/zh **皆不存在**；來源字典 `src/report/exporters/report_i18n.py:88-125`（6 個 category，缺 draftpolicy）；消費 `html_exporter.py:1262-1281`（`cat.lower()` → 全小寫 key）；DraftPolicy findings 由 R01-R05 產生（draft_policy 報表路徑） |
| F4 | 千分位：`html_exporter.py:324-325` `_INT_COL_KEYWORDS`（'port' 子字串）→ :360-362 int_cols → :383 `_fmt_int_cell`（:343 `f'{int(f):,}'`）；Port 欄來源 mod01/mod02（Int64）；**無測試鎖定千分位**；audit/pu exporter 不受影響（自帶 cell 渲染/字串 port） |
| N1 | print-btn 模式：`.report-toc screen-only` aside 內 `<button class="print-btn" onclick="window.print()">{rpt_nav_print_pdf}</button>`；有=Traffic 系列(:618/:746-748)/Audit(:177/:266-268)/VEN(:107/:220-222)/PU(:183/:253-255)；**缺=policy_diff(:143)/app_summary(:155)**（兩者無 aside、單欄 shell；CSS 已由 build_css 共用帶入）；守門：目前僅 test_traffic_flows_html_exporter.py:72 測 TrafficFlows 一家 |
| N2 | `report_css.py`：`.report-table-wrap`(:114 overflow:auto)、tbody td(:126) **無 word-break**（僅 print :304 有 overflow-wrap）；print 區塊 :288-333 已有 width100%/min-width0/break-word/7.5pt 寬表——print 無裁切已大致成立；MODERN_SHELL_CSS 第二 print 區塊 :510-514 隱藏 toc；test_html_size.py 約束 Traffic <5MB |

---

### Task 1: actor 顯示解析修正（spec F1）

**Files:**
- Modify: `src/api/labels.py`（`resolve_actor_str`）
- Modify: `src/report/analysis/policy_usage/pu_mod02_hit_detail.py`（`_resolve_actors` fallback）
- Test: `tests/test_actor_display.py`（新檔）

**Interfaces:**
- `resolve_actor_str` 對外簽名不變；行為變更：`{'actors':'ams'}` → `"All Workloads"`；新增 `label_group`/`workload` 解析（走 label_cache 同模式，fallback 字面 `"LabelGroup"`/`"Workload"`）；未知形狀 → `_readable_ref(a)`（href 尾段或 key 名，絕不印 raw dict）。
- `_resolve_actors` fallback 同步：ams → "All Workloads"；:137/:150 的 `str(actor)` 改為可讀形式（href 尾段 → 如 `ip_list:PCI-scope`，無 href 則 key 名）。

- [ ] **Step 1: RED 測試**

`tests/test_actor_display.py`：
```python
"""actor 顯示解析（spec F1）：ams 顯示 All Workloads、未知形狀不印 raw dict。"""
from src.report.analysis.policy_usage.pu_mod02_hit_detail import _resolve_actors


class _FakeClient:
    label_cache = {"/orgs/1/labels/7": "app:web", "/orgs/1/ip_lists/3": "PCI-scope"}


class _FakeApi:
    def __init__(self):
        self._c = _FakeClient()

    def resolve_actor_str(self, actors):
        from src.api.labels import LabelsApi  # 以實際類名為準（實作時確認）
        raise NotImplementedError  # Step 3 直接測 labels 層，見下


def test_ams_renders_all_workloads_via_labels_layer():
    # 直接建構 labels 模組的解析器（實作時以實際類/建構方式為準，最小化建構）
    from src.api import labels as labels_mod
    # ... 建 resolver 使其 label_cache 可注入（讀 labels.py 確認建構），斷言：
    # resolve_actor_str([{"actors": "ams"}]) == "All Workloads"
    # resolve_actor_str([{"label": {"href": "/orgs/1/labels/7"}}]) == "app:web"
    # resolve_actor_str([{"label_group": {"href": "/x/label_groups/9"}}]) 不含 "{'"


def test_fallback_no_raw_dict():
    out = _resolve_actors([{"ip_list": {"href": "/orgs/1/ip_lists/3"}},
                           {"actors": "ams"},
                           {"mystery": {"href": "/orgs/1/mystery/5"}}], api_client=None)
    assert "{'" not in out and '{"' not in out      # 絕不印 raw dict
    assert "All Workloads" in out
    assert "PCI-scope" in out or "ip_lists/3" in out or "ip_list:3" in out
```
（Step 1 的 labels 層測試骨架需在實作時依 `labels.py` 實際建構方式補完——resolver 是類方法，確認其 `self._client.label_cache` 注入途徑後寫出可執行斷言；**不可留 pass 空殼**。）

- [ ] **Step 2: 跑測試確認 FAIL**（現況印 "ams" 與 raw dict）
- [ ] **Step 3: 實作（GREEN）**

`labels.py` `resolve_actor_str` 改為：
```python
    def resolve_actor_str(self, actors):
        c = self._client
        if not actors:
            return "Any"
        names = []
        for a in actors:
            if not isinstance(a, dict):
                names.append(str(a))
            elif 'label' in a:
                names.append(c.label_cache.get(a['label']['href'], "Label"))
            elif 'label_group' in a:
                names.append(c.label_cache.get(a['label_group']['href'], "LabelGroup"))
            elif 'ip_list' in a:
                names.append(c.label_cache.get(a['ip_list']['href'], "IPList"))
            elif 'workload' in a:
                names.append(c.label_cache.get(a['workload']['href'], "Workload"))
            elif a.get('actors') == 'ams':
                # 顯示層對應：API payload 的 'ams' 一律呈現 All Workloads（spec F1）
                names.append("All Workloads")
            elif 'actors' in a:
                names.append(str(a.get('actors')))
            else:
                names.append(_readable_ref(a))
        return ", ".join(names)
```
模組層新增：
```python
def _readable_ref(actor: dict) -> str:
    """未知 actor 形狀的可讀 fallback：型別:href 尾段，絕不印 raw dict（spec F1）。"""
    for key, val in actor.items():
        if isinstance(val, dict) and val.get('href'):
            tail = str(val['href']).rstrip('/').rsplit('/', 1)[-1]
            return f"{key}:{tail}"
    return ", ".join(str(k) for k in actor.keys()) or "Unknown"
```
`pu_mod02_hit_detail.py` `_resolve_actors` fallback：:140 ams 分支改 append `"All Workloads"`；:137 與 :150 的 `str(actor)` 改呼叫同型 `_readable_ref`（自 labels import 或本地複製一份——**跟隨檔案既有 import 慣例**，若跨層 import 不妥則本地定義並註明來源）。

- [ ] **Step 4: 全套綠燈**：`python -m pytest tests/test_actor_display.py tests/test_api_client.py tests/test_policy_usage_report.py -v && python -m pytest -q`（payload 契約測試必須原樣綠）
- [ ] **Step 5: Commit** `fix(report): render ams as All Workloads and humanize actor fallbacks`

---

### Task 2: draftpolicy i18n + port 千分位豁免（spec F3+F4）

**Files:**
- Modify: `src/report/exporters/report_i18n.py`（category 字典 + 兩 json）
- Modify: `src/report/exporters/html_exporter.py`（port 欄豁免）
- Test: `tests/test_display_fixes.py`（新檔）

- [ ] **Step 1: RED 測試**

```python
"""spec F3（draftpolicy i18n）+ F4（port 欄不套千分位）。"""
import pandas as pd
from src.report.exporters.report_i18n import STRINGS


def test_draftpolicy_category_i18n_exists():
    assert STRINGS["rpt_cat_draftpolicy_name"]["en"]
    assert STRINGS["rpt_cat_draftpolicy_name"]["zh"]
    assert STRINGS["rpt_cat_draftpolicy_desc"]["en"]


def test_port_column_no_thousands_separator():
    from src.report.exporters.html_exporter import _df_to_html
    df = pd.DataFrame([{"Port": 8080, "Connections": 12345}]).astype({"Port": "Int64", "Connections": "Int64"})
    html = _df_to_html(df, lang="en")
    assert "8080" in html and "8,080" not in html      # Port 不分組
    assert "12,345" in html                             # 計數欄仍分組


def test_unique_ports_count_still_grouped():
    from src.report.exporters.html_exporter import _df_to_html
    df = pd.DataFrame([{"Unique Ports": 1234}]).astype("Int64")
    html = _df_to_html(df, lang="en")
    assert "1,234" in html                              # 含 port 字樣的計數欄不受豁免誤傷
```

- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**

1. `report_i18n.py` category 字典（:88-125）加：
```python
    "draftpolicy": (
        "Draft Policy",
        "草稿 Policy",
        "Findings from draft-policy simulation: draft deny hits, override denies, "
        "visibility-boundary breaches and draft-vs-reported mismatches.",
        "草稿 Policy 模擬產生的發現：draft deny 命中、override deny、"
        "可視性邊界穿越、draft 與實際回報不一致。",
    ),
```
（以字典實際 tuple 形狀為準——實作時讀現有 6 個條目的形狀照抄結構；兩 json 同步產生的 key `rpt_cat_draftpolicy_name/_desc`。）
2. `html_exporter.py` port 豁免（**欄名精確匹配**，不用子字串——避免誤傷 "Unique Ports"/"Top Hit Ports" 計數欄）：
```python
_PORT_EXACT_COLS = ('port', '連接埠')   # 值為 port 號本身的欄（精確匹配 _norm_col 後）
```
`int_cols` 建構處（:360-362）拆出 `port_cols = {col for col in df.columns if _norm_col(col) in _PORT_EXACT_COLS}`；`_render_cell`（:383）在 int 分派前加 `if col in port_cols: return _fmt_int_cell(val, group=False)`；`_fmt_int_cell`（:331-344）加 `group: bool = True` 參數，:343 依 group 選 `f'{int(f):,}'` 或 `str(int(f))`。

- [ ] **Step 4: 全套綠燈**（含 tests/test_report_i18n_leakage.py、test_section_guidance_keys.py）
- [ ] **Step 5: Commit** `fix(report): draftpolicy category i18n and no thousands separator on port columns`

---

### Task 3: GUI 報表頁 attack posture badge 移除（spec F2）

**Files:**
- Modify: `src/static/js/dashboard.js`（刪 `_buildAttackSummaryMeta` :605-626 與呼叫點 :110-115 的 attackMeta 邏輯）
- Modify: i18n（`gui_attack_summary_title` 若 grep 歸零則刪——注意 dashboard_approved.json/zh_explicit.json 同步）
- Test: 既有 tests/test_gui_dashboard.py 全綠（API 欄位不動）

**不可觸碰**：`attack_summary_counts()`/metadata schema/email 渲染/dashboard_summaries/`rp.summary`（多方消費，見現況地圖）。

- [ ] **Step 1: 前置確認**——grep `_buildAttackSummaryMeta` 呼叫點僅 :110-115 一處；讀 :107-115 現行組裝，確認移除 attackMeta 後 policy_usage/summary 顯示分支簡化方式（保留 `rp.summary` 與 `_buildPolicyUsageReportMeta` 原樣）。
- [ ] **Step 2: 實作**——刪函式與呼叫；`gui_attack_summary_title` grep（src/ 與 i18n data 檔）歸零則四處全刪（兩 json + dashboard_approved.json + zh_explicit.json），任一處仍有引用則保留並記報告。
- [ ] **Step 3: 驗證**——`python -m pytest tests/test_gui_dashboard.py tests/test_audit_dashboard_i18n.py -v && python -m pytest -q`；`grep -rn "_buildAttackSummaryMeta\|attack_summary_counts" src/static/` 前者歸零、後者不出現於 static（資料欄位仍由後端輸出，前端不再消費——`attack_summary_counts` 在 reports.py API 回傳保留，向後相容）。
- [ ] **Step 4: Commit** `feat(gui): remove attack posture badge from reports list`
（Controller 會在 final review 前做 Playwright 實機煙霧：報表頁渲染正常、console 零錯誤。）

---

### Task 4: policy_diff / app_summary 補列印按鈕 + 守門測試（spec N1）

**Files:**
- Modify: `src/report/exporters/policy_diff_html_exporter.py`（:143 shell 組裝）
- Modify: `src/report/exporters/app_summary_html_exporter.py`（:155 同）
- Test: `tests/test_print_button_all_exporters.py`（新檔，守門掃描）

- [ ] **Step 1: RED 守門測試**

```python
"""spec N1：所有 HTML exporter 輸出必含列印/PDF 按鈕（守門掃描）。"""
# 對 6 個 exporter 各以最小 fixture 產 HTML（比照各自既有測試的建構方式——
# 讀 tests/ 中各 exporter 的既有測試 fixture 抄最小建構），斷言每份 HTML 含：
#   'window.print()' 與 'class="print-btn"'
# 清單：SecurityRisk/TrafficFlows（html_exporter）、Audit、VEN、PolicyUsage、
#       PolicyDiff、AppSummary。
```
（實作時每個 exporter 寫一個真實斷言測試函式，不可用參數化跳過難建構者——policy_diff/app_summary 的最小建構參考其現有測試檔。）

- [ ] **Step 2: 確認 FAIL**（policy_diff/app_summary 兩個 FAIL、其餘綠）
- [ ] **Step 3: 實作**——兩個 exporter 的 shell 組裝處（`'<div class="report-shell"><main class="report-main">'`）改為比照 audit（audit_html_exporter.py:266-268 依樣）：
```python
        nav_html = (
            '<aside class="report-toc screen-only">'
            f'<button class="print-btn" onclick="window.print()">{t("rpt_nav_print_pdf", lang=lang)}</button>'
            '</aside>'
        )
        # shell：'<div class="report-shell">' + nav_html + '<main class="report-main">'
```
（無 TOC 清單只放按鈕——`.report-toc` 的 print/responsive 隱藏 CSS 已由共用 build_css 帶入；`t()` 的 lang 以各 exporter 現有 lang 變數為準；grid 兩欄版面由 MODERN_SHELL_CSS 處理，確認渲染後主欄寬度正常——測試斷言 + Task 6 E2E 目視。）

- [ ] **Step 4: 全套綠燈**
- [ ] **Step 5: Commit** `feat(report): print button on policy-diff and app-summary reports with exporter-wide guard test`

---

### Task 5: 表格螢幕版面收斂（spec N2 增量）

現況：print 版面（BASE_CSS :288-333）已達「A4 完整、break-word、寬表 7.5pt」要求；螢幕側 tbody td 無 word-break（長字串會撐寬觸發水平捲動）。本 task 為增量修正，**不動任何 @media print 區塊**。

**Files:**
- Modify: `src/report/exporters/report_css.py`（tbody td 一行）
- Test: `tests/test_report_print_layout.py`（增 2 斷言）

- [ ] **Step 1: RED 測試**——test_report_print_layout.py 加：
```python
def test_screen_td_breaks_long_words():
    from src.report.exporters.report_css import BASE_CSS
    screen_part = BASE_CSS.split('@media print')[0]
    td_rule = [ln for ln in screen_part.splitlines() if '.report-table tbody td' in ln]
    assert td_rule and 'overflow-wrap: break-word' in td_rule[0]
```
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作**——`report_css.py` :126 tbody td 加 `overflow-wrap: break-word;`（screen 側，避免長 URL/hostname 撐寬）。
- [ ] **Step 4: 既有 print layout 測試全綠 + 全套**（split-index 斷言不受影響——未新增 print 區塊）
- [ ] **Step 5: Commit** `fix(report): break long words in table cells on screen layout`

---

### Task 6: 樣本 E2E + CHANGELOG + 手冊

**Files:** scratchpad 腳本（不入版控）、`CHANGELOG.md`、`docs/operations-manual.md`、`_zh.md`

- [ ] **Step 1: E2E（專案 CLAUDE.md 硬性規則）**——合成資料產出：security_risk HTML（含 DraftPolicy findings 樣本驗 F3 卡片標題/描述、Port 欄 8080 無千分位、actor 欄含 All Workloads——若 fixture 可達）、policy_diff HTML、app_summary HTML（驗兩者 print-btn 與版面正常——grep + 目視結構）、policy usage HTML（Source/Destination 欄無 raw dict）。長字串樣本（120 字 hostname）驗螢幕 td 換行。逐項證據記報告。
- [ ] **Step 2: 回歸**——`python -m pytest -q` + `python3 scripts/check_no_naive_datetime.py`。
- [ ] **Step 3: CHANGELOG + 手冊**——Unreleased 條目（F1-F4、N1-N2 六點）；手冊若有報表按鈕/欄位描述則同步（surgical）。
- [ ] **Step 4: Commit** `docs: document display fixes and print layout consistency (phase 4)`

---

## Self-Review 檢核

1. **Spec 覆蓋**：F1→T1；F2→T3；F3+F4→T2；N1→T4；N2→T5（print 側經盤點已達標，增量只補 screen 側，rationale 記於 task 開頭）；T6 收尾。
2. **相依**：T1-T5 相互獨立；T6 收尾。建議按號序。
3. **契約保護**：payload 契約測試（test_api_client）在 T1 的聚焦清單強制驗證；badge 資料鏈以「不可觸碰」清單鎖定；print split-index 風險以「不新增 print 區塊」約束消除。
4. **T1 Step 1 的 labels 層測試骨架**與 **T4 Step 1 的守門測試**皆標記「實作時補完、不可留空殼」——reviewer 必驗。
5. **Playwright 煙霧**：T3 為 GUI JS 變更，controller 於 final review 前實機煙霧（比照批次 6 慣例）。
