# Phase 2B — 報表視覺重構 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 10 型 HTML 報表的視覺殼統一改為 `design/v2/reports/shell.css` 的新設計：`report_css.py` 依 shell.css 重寫、抽出共用殼 renderer（章節模型沿用 `design/v2/tools/reskin_report.py` 原型）、11 型 exporter 逐批套殼，最終在測試機以真資料重產全部報表並完成雙寬度＋PDF 逐頁親驗。

**Architecture:** 產品端不走原型的「事後 BeautifulSoup 改寫」路線，而是讓 exporter **原生輸出新殼**：新增 `src/report/exporters/report_shell.py`（`SHELL_CSS` 常數＋`ShellCover`/`ShellSection` 資料模型＋`build_shell_document()` 組版函式），各 exporter 把「nav/骨架 f-string 拼接」改為「組 `ShellSection` 清單交給 renderer」，章節內容函式（`_modNN_html()` 等）全部保留不動。遷移期間新舊殼並存（未遷移 exporter 繼續用 `build_css()`），末批完成後刪除舊 CSS 常數與雙封面機制。內容守恆由「遷移前基準快照 → 遷移後 conservation 比對」守門測試保證（思路照抄 `reskin_report.py` 的 `conservation_diff`）。

**Tech Stack:** Python f-string 組版（沿用既有慣例，無 template engine）、CSS 內嵌單檔 HTML（離線可開）、matplotlib inline SVG 圖表（不動）、BeautifulSoup（**僅測試側**，requirements-dev.txt:10 既有）、Playwright（真機驗證）。

## 現況事實摘要（動工前須重驗，見 Global Constraints 第 1 條）

**11 型報表註冊表**（唯一權威：`src/report_scheduler.py:678-690` 的 `_REPORT_PREFIXES`）：

| # | report_type | Exporter 類別 | HTML 殼 | 所在檔 |
|---|---|---|---|---|
| 1 | `traffic` | `TrafficFlowsHtmlExporter` | 是 | `src/report/exporters/html_exporter.py` |
| 2 | `security_risk` | `SecurityRiskHtmlExporter` | 是 | 同上 |
| 3 | `network_inventory` | `NetworkInventoryHtmlExporter` | 是 | 同上 |
| 4 | `audit` | `AuditHtmlExporter` | 是 | `audit_html_exporter.py` |
| 5 | `ven_status` | `VenHtmlExporter` | 是 | `ven_html_exporter.py` |
| 6 | `policy_usage` | `PolicyUsageHtmlExporter` | 是 | `policy_usage_html_exporter.py` |
| 7 | `policy_diff` | `PolicyDiffHtmlExporter` | 是 | `policy_diff_html_exporter.py` |
| 8 | `app_summary` | `AppSummaryHtmlExporter` | 是 | `app_summary_html_exporter.py` |
| 9 | `rule_hit_count` | `RuleHitCountHtmlExporter` | 是 | `rule_hit_count_html_exporter.py` |
| 10 | `readiness` | `ReadinessHtmlExporter` | 是 | `readiness_html_exporter.py` |
| 11 | `policy_resolver` | `PolicyResolverExporter` | **否**（僅 JSON/CSV，無 `_build()`/`report_css`） | `policy_resolver_exporter.py` |

→ **視覺套殼對象＝10 型 HTML**（roadmap 寫「11 型 exporter 套殼」，實為 11 型註冊、10 型有 HTML；`policy_resolver` 在末任務仍要重產以確認未受波及）。另 `HtmlExporter`（html_exporter.py:1796）是 back-compat shim、`draft_policy` 是 traffic 家族的 `compute_draft=True` 變體（CLI `report draft-policy`），皆隨 traffic 家族一併處理。

**舊殼結構**（8 個 HTML exporter 一致）：`cover_page.build_cover_page()` 雙封面（screen/print）→ `div.report-shell` → `aside.report-toc` + `main.report-main` → `TABLE_JS`。CSS 由 `report_css.build_css(exporter_type)`（report_css.py:585-596，回傳含 `<style>` 標籤）於各 exporter 模組層一次性求值。PDF 無伺服端轉檔——唯一路徑是報表內建 `<button class="print-btn" onclick="window.print()">` ＋ `@media print` 規則。

**與 reskin 原型的刻意偏差**（實作時不可自行「補齊」原型行為）：

1. **print 按鈕保留**：原型把 `print-btn` 列入 allowlist 移除；產品的 PDF 唯一入口就是它，新殼 nav 內必須保留（screen-only）。
2. **TABLE_JS 保留**：原型 docstring「互動排序/欄寬新殼不沿用」是靜態改版工具的限制；產品表格 class 結構不變，TABLE_JS 相容，保留互動排序。
3. **章序不重排**：原型 `chapter_order()` 把 finding 章移到最前；產品敘事順序是各 exporter 既有規格（如 SecurityRisk 的 B1），殼照 exporter 給定順序渲染。
4. **TOC 頁碼不回填**：原型的頁碼靠 Playwright+pdftotext 兩趟出圖；exporter 產出時無瀏覽器，`.toc-page` 維持空（螢幕本來就 `display:none`，列印無頁碼引導點線）。
5. **`lang` 屬性維持 `zh-TW`**（原型用 `zh-Hant`）；`data-report-title` 保留，且順手補齊 readiness/rule_hit_count 現況缺 `lang`/`data-report-title` 的不一致。

## Global Constraints（每任務隱含適用）

1. **執行時以當下原始碼為準**：本計畫引用的檔案結構、行號、函式簽名皆為撰寫日快照，動工前逐項重驗（`grep`/實際開檔），**禁止盲信行號**；發現漂移以現碼為準並記入任務回報。
2. **內容守恆——重排不得丟資料**：沿用 `design/v2/tools/reskin_report.py` 的 `conservation_diff` 思路（文字節點 NFKC normalize→集合→在新輸出攤平字串中逐段查存，label:value 拆分豁免、豁免清單須逐條列明理由）做守門測試；每批 exporter 遷移前先以舊碼產基準快照，遷移後 conservation diff 必須為空。表格/圖表數量前後相等另立不變量斷言。
3. **CLAUDE.md 報表硬規則（逐字）**：「產出報表、PDF、摘要文件前，先確認欄位與內容的長度上限與截斷邏輯（過長內容的處理方式要明確：換行、省略或分頁，不可無聲截斷）。」「交付前用實際樣本資料跑一次完整輸出，逐頁檢查有沒有被截斷或溢出，把檢查結果附在回報裡。」
4. **驗收閘門**：測試機（root@172.16.15.106:/root/illumio-ops）真資料重產全 11 型＋雙寬度（**1280/800**，專案慣例出處 `reskin_report.py --render`）Playwright 截圖＋PDF 逐頁親驗，全部通過才算交付（Task 7）。
5. **不引入離線 bundle 無法打包的相依**：不加新 runtime 相依（BeautifulSoup 僅限測試側，requirements-dev 既有）；不引入 CDN 資源；產出 HTML 維持單檔離線可開；維持 `tests/test_html_size.py` 的 5 MB 上限。
6. **i18n 新鍵遵守七層白名單鏈**（記憶：filter-key-chain-checklist）：新鍵一律用既有 `rpt_` 前綴（`rpt_shell_*`），寫入 `src/i18n_en.json` 與 `src/i18n_zh_TW.json` 成對（注意 JSON 在 `src/` 根，非 `src/i18n/`）；英文保留術語過 `src/i18n/data/glossary.json`；若前綴落入嚴格清單則同步 `strict_prefixes.json`；每任務結尾 `python3 scripts/audit_i18n_usage.py` 必須 0；`t()` 的 placeholder 不可命名 `{key}`（t() 首參即 key）。
7. **Commit 訊息一律英文 conventional commits**（repo 慣例，非 plan 樣板繁中）。
8. XSS 逃逸不得倒退：所有 PCE 來源值進殼前 `html.escape`（`tests/test_exporter_xss_escaping.py` 全程必綠）。
9. 每任務結尾：全套 `pytest -q` 綠＋audit_i18n 0＋乾淨 commit；子代理派發沿用硬規則（worktree 釘選驗證、commit 前 `git rev-parse --show-toplevel` 證據、共用 worktree 禁 stash）。

## File Structure（2B 全貌）

```
src/report/exporters/
  report_shell.py          # 新增：SHELL_CSS + ShellCover/ShellSection + build_shell_document()
  report_css.py            # T1-T5 期間保留舊常數供未遷移者；T6 刪 build_css/BASE_CSS 等全部舊殼
  cover_page.py            # T6 刪（封面併入 report_shell）
  table_renderer.py        # T2 增欄位語意（.num/.col-ts）＋寬表 hint/--landscape
  html_exporter.py         # T3 套殼（traffic 家族 3 型＋shim＋draft 變體）
  audit_html_exporter.py   # T4
  ven_html_exporter.py     # T4
  policy_usage_html_exporter.py  # T4
  policy_diff_html_exporter.py   # T5
  app_summary_html_exporter.py   # T5
  rule_hit_count_html_exporter.py # T5
  readiness_html_exporter.py     # T5
scripts/capture_report_baselines.py   # 新增：以「當下 HEAD 的舊碼」產守恆基準
scripts/verify_report_render.py       # T7 新增：真機 HTML→截圖/PDF/裁切量測（轉錄原型 verify 三函式）
tests/report_shell/
  __init__.py
  conservation.py          # 守恆 helper（轉錄 reskin_report.py 754-828）
  fixtures.py              # 10 型「型別→最小樣本 HTML builder」註冊表
  baselines/<type>.json    # 各批遷移前的文字基準（T3-T5 各自產生並 commit）
tests/test_report_shell_renderer.py   # T1：renderer 結構/逃逸/print 不變量
tests/test_report_shell_migration.py  # T3-T5 逐批擴充：守恆＋結構閘（parametrize by type）
```

---

### Task 1: 新殼 CSS 與共用 renderer（`report_shell.py`）

**Files:**
- Create: `src/report/exporters/report_shell.py`
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（新增 `rpt_shell_*` 鍵，見下）
- Test: `tests/test_report_shell_renderer.py`

**Interfaces:**
- Produces（T2-T6 全部依賴，簽名以此為準）:

```python
# src/report/exporters/report_shell.py
SHELL_CSS: str   # 自 design/v2/reports/shell.css 移植的產品版（見 Step 3 移植規則）

@dataclass(frozen=True)
class ShellCover:
    title: str                 # 報表完整標題（原 hero h1，非型別短標——原型 C1 事故教訓）
    doc_title: str             # <title> 逐字，不由其他欄位推導
    type_label: str            # 型別短標（原 cover-type）
    eyebrow: str = ""          # 產品名 kicker
    kicker: str = ""           # 副標
    grade: str = ""            # 成熟度等級（空字串=不渲染 grade chip）
    score: str = ""
    badges: tuple[tuple[str, str], ...] = ()   # ((text, tone), ...) tone∈ok|warn|crit|info|neutral
    meta: dict[str, str] = field(default_factory=dict)  # 已 i18n 的 label→value（PCE/org/範圍/產生時間）

@dataclass(frozen=True)
class ShellSection:
    id: str
    title: str                 # 純文字章名（已 i18n；renderer 負責 escape）
    html: str                  # 章內容（信任為已逃逸的既有渲染結果，不再 escape）
    kind: str = "detail"       # exec|finding|detail
    tone: str = "neutral"      # ok|warn|crit|info|neutral
    marks: dict[str, int] = field(default_factory=dict)  # {"CRITICAL": 2, ...} 全顯示不截斷

def build_shell_document(*, lang: str, cover: ShellCover, sections: Sequence[ShellSection],
                         appendix_html: str = "", rule_index: Sequence[tuple[str, str, str]] = (),
                         extra_head: str = "", include_table_js: bool = True) -> str
    # 回傳完整 <!DOCTYPE html> 文件：header.cover → section.exec(kind=exec 各章) → nav.toc
    #   （含 print-btn，screen-only）→ div.chapters>section.chapter → section.appendix → TABLE_JS
    # <html lang="zh-TW"|"en">、<body data-report-title="{cover.type_label}">
    # 附錄＝產出參數(cover.meta) dl ＋ 章節索引(自 sections) ＋ rule_index ol ＋ colophon(appendix_html)

def wide_table_attrs(n_cols: int, lang: str) -> tuple[str, str]
    # n_cols >= 10 → (" report-table-panel--landscape", '<p class="table-hint">…</p>')；否則 ("", "")
```

- 新 i18n 鍵（en/zh_TW 成對；zh 文案沿用原型與 shell.css 註解措辭）：`rpt_shell_toc_title`（Contents／目錄）、`rpt_shell_appendix_title`（Appendix／附錄）、`rpt_shell_appendix_params`（Generation parameters／產出參數）、`rpt_shell_appendix_chapters`（Chapter index／章節索引）、`rpt_shell_appendix_rules`（Rule index／規則索引）、`rpt_shell_kind_exec`（Executive summary／執行摘要）、`rpt_shell_kind_finding`（Findings／發現）、`rpt_shell_kind_detail`（Details／明細）、`rpt_shell_table_hint_wide`（"{cols}-column wide table · scroll horizontally on screen · prints in A4 landscape"／"{cols} 欄寬表 · 螢幕可左右捲動檢視全部欄位 · 列印自動轉為 A4 橫式頁"）。print 按鈕沿用既有 `rpt_nav_print_pdf`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_report_shell_renderer.py
import re
from bs4 import BeautifulSoup
from src.report.exporters.report_shell import (
    SHELL_CSS, ShellCover, ShellSection, build_shell_document, wide_table_attrs)

def _doc(**kw):
    cover = ShellCover(title="Illumio 資安與風險報表", doc_title="Illumio 流量報告",
                       type_label="安全風險分析", eyebrow="Illumio Ops",
                       grade="D", score="52", meta={"PCE": "pce.test", "資料範圍": "2026-01-01 – 2026-02-01"})
    sections = [
        ShellSection(id="exec-summary", title="執行摘要", kind="exec",
                     html='<div class="kpi-strip"><div class="kpi">100</div></div>'),
        ShellSection(id="findings", title="發現與行動", kind="finding", tone="crit",
                     marks={"CRITICAL": 2, "LOW": 5},
                     html='<p>lateral-movement finding narrative</p>'),
        ShellSection(id="overview", title="流量總覽", kind="detail",
                     html='<div class="report-table-panel"><table class="report-table"></table></div>'),
    ]
    return build_shell_document(lang="zh_TW", cover=cover, sections=sections,
                                appendix_html="<p>illumio-ops v9 產出</p>", **kw)

def test_document_skeleton_and_order():
    soup = BeautifulSoup(_doc(), "html.parser")
    doc = soup.select_one("div.sheet > div.doc")
    kids = [c.name + "." + " ".join(c.get("class", [])) for c in doc.find_all(recursive=False)]
    assert kids[0].startswith("header.cover")
    assert any(k.startswith("section.exec") for k in kids)
    assert any(k.startswith("nav.toc") for k in kids)
    assert kids[-1].startswith("section.appendix")

def test_toc_entries_match_sections_and_chapter_order_is_preserved():
    soup = BeautifulSoup(_doc(), "html.parser")
    toc_hrefs = [a["href"] for a in soup.select("nav.toc ol a")]
    assert toc_hrefs == ["#exec-summary", "#findings", "#overview"]  # 不重排
    chapters = [s["id"] for s in soup.select("div.chapters > section.chapter")]
    assert chapters == ["findings", "overview"]

def test_cover_uses_full_title_not_type_label():
    soup = BeautifulSoup(_doc(), "html.parser")
    assert soup.title.string == "Illumio 流量報告"          # doc_title 逐字
    assert soup.select_one("header.cover h1").get_text() == "Illumio 資安與風險報表"

def test_marks_are_all_rendered_never_capped():
    soup = BeautifulSoup(_doc(), "html.parser")
    chips = soup.select("#findings .chapter-marks .mark-chip")
    assert len(chips) == 2  # 原型教訓：chips[:3] 靜默截斷是 bug，全部顯示

def test_print_button_and_table_js_present():
    html = _doc()
    assert 'class="print-btn"' in html and "window.print()" in html
    assert "<script" in html  # TABLE_JS 保留
    assert "<script" not in _doc(include_table_js=False)

def test_escaping_of_untrusted_title():
    s = ShellSection(id="x", title='<script>alert(1)</script>', html="<p>ok</p>")
    cover = ShellCover(title="t", doc_title="d", type_label="x")
    out = build_shell_document(lang="en", cover=cover, sections=[s])
    assert "<script>alert(1)</script>" not in out and "&lt;script&gt;" in out

def test_shell_css_print_invariants():
    assert "size: A4 portrait" in SHELL_CSS
    assert "@page wide" in SHELL_CSS and "size: A4 landscape" in SHELL_CSS
    assert "page: wide" in SHELL_CSS                       # --landscape 取用
    assert "display: table-header-group" in SHELL_CSS      # 表頭每頁重複
    assert "content-visibility: visible" in SHELL_CSS      # cell-long 列印展開（PDF 文字層）
    assert re.search(r"\.chapter\s*\{[^}]*break-before:\s*page", SHELL_CSS)
    assert "prefers-color-scheme" not in SHELL_CSS         # 恆亮，無 dark 分支

def test_wide_table_attrs_threshold():
    cls, hint = wide_table_attrs(11, "zh_TW")
    assert "report-table-panel--landscape" in cls and "11" in hint and "table-hint" in hint
    assert wide_table_attrs(9, "zh_TW") == ("", "")
```

- [ ] **Step 2: 跑測試確認失敗** — `pytest tests/test_report_shell_renderer.py -q`，預期 `ModuleNotFoundError: report_shell`
- [ ] **Step 3: 實作 `report_shell.py`**。SHELL_CSS 移植規則（逐段照 `design/v2/reports/shell.css` 的 15 段搬入 Python 字串，非重新設計）：(a) 全文照搬 §1-§15，含 `:root` token 子集、`[data-tone]` 間接層（`--mark/--ink/--fill`）、print 段的 `@page`/`@page wide`/break 規則/寬表欄寬政策 a–e；(b) **刪除** §順序中「舊封面隱藏」（shell.css 997-1001）——產品端不再產雙封面，無須防禦性隱藏；(c) **新增** `.print-btn` 規則（screen-only、樣式比照 `.toc a` 的字級與 accent 色、`@media print { .print-btn { display:none } }`）；(d) 保留 `.finding-card,.concern-card,.audit-attn-item` 三 selector 共用組與 `.exec-summary`/`.kpi-strip` 去殼規則（既有 exporter 內容 class 不改名就能吃到新樣式）；(e) 檔頭注釋標明來源與同步義務（`design/v2/reports/shell.css` 為設計權威，產品側改動需回註記）。renderer 依 Interfaces 實作：`html.escape` 所有 cover/section 標量欄位；章號 `S{idx:02d}`（ASCII，原型 661-662 的 PDF 文字層教訓）；TOC 編號 `{i:02d}` 從 00 起算 exec+chapters；文件 tone＝任一章 crit 則 crit、否則第一章 tone、fallback neutral（原型 558-559）；TABLE_JS 自 `report_css.py` import（`from .report_css import TABLE_JS`，T6 時把 TABLE_JS 常數搬家至 report_shell.py）。i18n 鍵同步入兩份 JSON。
- [ ] **Step 4: 跑測試至綠** — `pytest tests/test_report_shell_renderer.py -q` PASS；`pytest -q` 全套綠；`python3 scripts/audit_i18n_usage.py` 0
- [ ] **Step 5: Commit** — `git add src/report/exporters/report_shell.py src/i18n_en.json src/i18n_zh_TW.json tests/test_report_shell_renderer.py && git commit -m "feat(report-shell): add v2 report shell renderer with shell.css port"`

---

### Task 2: 守恆守門 harness＋表格欄位語意

**Files:**
- Create: `tests/report_shell/__init__.py`、`tests/report_shell/conservation.py`、`tests/report_shell/fixtures.py`
- Create: `scripts/capture_report_baselines.py`
- Modify: `src/report/exporters/table_renderer.py`（`render_df_table` 增欄位語意與寬表 hint）
- Test: `tests/test_report_shell_conservation_unit.py`、既有 `tests/test_report_tables.py` 擴充

**Interfaces:**
- Consumes: T1 的 `wide_table_attrs(n_cols, lang)`
- Produces:

```python
# tests/report_shell/conservation.py —— 轉錄 design/v2/tools/reskin_report.py:754-828，行為等價
def norm(text: str) -> str                     # NFKC → 去全部空白 → casefold
def conservation_text(html: str) -> tuple[set[str], str]
    # decompose script/style/svg → (>=4字元文字節點集合（濾 Comment/Doctype/PI/CData/Declaration）, 攤平字串)
def conservation_diff(old_html: str, new_html: str,
                      allowlist: frozenset[str] = frozenset()) -> list[str]
    # old 的每段 leaf 須在 new 的 flat 中找到；label:value 拆分豁免（兩半各自都要找到）；回傳未保全清單
def label_value_preserved(text: str, flat: str) -> bool
    # 上述拆分豁免的單段判定（轉錄原型 _conservation_preserved 791-807），供 migration 測試直接 import

# tests/report_shell/fixtures.py
BUILDERS: dict[str, Callable[[], str]]         # report_type → 以最小樣本資料呼叫該型 exporter 的 _build()/_render_html()
# 10 個 key = 上表 #1-#10 的 report_type；樣本資料轉錄自各型既有測試（來源檔逐型標注）：
#   traffic → tests/test_traffic_flows_html_exporter.py 的 fixture
#   security_risk → tests/test_e2e_report_html_redesign.py::_make_traffic ＋ profile="security_risk"
#   network_inventory → tests/test_report_print_layout.py::_minimal_results ＋ NetworkInventoryHtmlExporter
#   audit → tests/test_print_button_all_exporters.py 的 audit fixture
#   ven_status/policy_usage/policy_diff/app_summary/rule_hit_count/readiness →
#     分別轉錄 tests/test_ven_report_compact.py、test_policy_usage_report.py、
#     test_policy_diff_html_exporter.py、test_app_summary_report.py、
#     test_rule_hit_count_html_exporter.py、test_readiness_html_exporter.py 的最小建構
# （轉錄=複製既有測試的資料 dict 與建構呼叫；若實名有異以現碼為準——Global Constraint 1）
```

```
# scripts/capture_report_baselines.py 用法（在「尚未改 exporter 的 commit」上執行）
python3 scripts/capture_report_baselines.py --types traffic,security_risk,network_inventory
# → 對每型呼叫 BUILDERS[type]() 產 HTML，寫 tests/report_shell/baselines/<type>.json：
#   {"report_type": ..., "captured_at_commit": "<git rev-parse HEAD>",
#    "leaves": sorted(conservation_text(html)[0]),
#    "table_count": N, "chart_count": M}    # table=len(select(".report-table"))、chart=len(select("figure.chart-static"))
```

- `render_df_table` 追加行為（既有簽名 `render_df_table(df, col_i18n, no_data_key, render_cell, value_i18n_maps, lang, …)` 不變，內部增強）：(a) 數值 dtype 欄的 th/td 加 class `num`；(b) 欄名（原始英文名）匹配 `re.search(r"(timestamp|_at$|_time$|^time$)", col, re.I)` 的欄加 class `col-ts`，儲存格在日期與時間之間插 `<wbr/>`；(c) 欄數 ≥ `WIDE_COL_THRESHOLD` 時沿用既有 `--wide`，欄數 ≥10 時再經 `wide_table_attrs()` 追加 `--landscape` class 並在 panel 首插入 hint（**hint 屬版面提示非資料**，加入 conservation allowlist，理由：純導覽文案、非 PCE 資料，且為新增而非移除——conservation 只驗舊→新方向，新增內容本不受限，此條僅為文件化）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_report_shell_conservation_unit.py —— 對照原型 tests/design_v2/test_reskin_report.py:351-386 的四案例
from tests.report_shell.conservation import conservation_diff, conservation_text, norm

OLD = "<main><h2>Lateral movement</h2><p>📅 資料範圍: 2026-01-01 – 2026-02-01</p><p>abc</p></main>"

def test_mechanism_catches_a_dropped_heading():
    assert conservation_diff(OLD, "<div><p>資料範圍: 2026-01-01 – 2026-02-01</p></div>") \
        == [norm("Lateral movement")]

def test_icon_label_value_split_is_tolerated_but_value_swap_is_not():
    ok = "<dl><dt>資料範圍</dt><dd>2026-01-01 – 2026-02-01</dd><p>lateral movement</p></dl>"
    assert conservation_diff(OLD, ok) == []
    swapped = "<dl><dt>資料範圍</dt><dd>（無資料）</dd><p>lateral movement</p></dl>"
    assert conservation_diff(OLD, swapped) != []

def test_short_strings_and_script_style_svg_are_out_of_scope():
    leaves, _ = conservation_text("<p>abc</p><script>var x='longlonglong'</script><svg><text>in-svg-text</text></svg>")
    assert leaves == set()   # abc <4 字元；script/svg 整棵剔除

def test_allowlist_exempts_exact_normalized_entry():
    old = "<button class='print-btn'>列印 / PDF</button><p>real content here</p>"
    assert conservation_diff(old, "<p>real content here</p>",
                             allowlist=frozenset({norm("列印 / PDF")})) == []
```

```python
# tests/test_report_tables.py 追加
def test_numeric_and_ts_columns_get_semantic_classes():
    df = pd.DataFrame({"Flows": [1, 2], "Last Seen Timestamp": ["2026-01-01 10:00", "2026-01-02 11:00"]})
    html = render_df_table(df, lang="en")
    soup = BeautifulSoup(html, "html.parser")
    assert "num" in soup.select("thead th")[0].get("class", [])
    assert "col-ts" in soup.select("thead th")[1].get("class", [])
    assert "<wbr/>" in html or "<wbr>" in html

def test_ten_plus_columns_get_landscape_and_hint():
    df = pd.DataFrame({f"c{i}": [1] for i in range(11)})
    html = render_df_table(df, lang="zh_TW")
    assert "report-table-panel--landscape" in html and 'class="table-hint"' in html
```

- [ ] **Step 2: 跑測試確認失敗**（conservation module 不存在；table classes 未加）
- [ ] **Step 3: 實作** — conservation.py 逐函式轉錄原型（含 774-778 濾 Doctype 假陽性注解、791-807「label/value 兩半都要找到」語意）；fixtures.py＋capture script；table_renderer 增強（dtype 判斷用 `pandas.api.types.is_numeric_dtype`）。
- [ ] **Step 4: 跑測試至綠**；全套 pytest 綠（既有 test_report_tables/test_render_layer_i18n 不得回歸）；audit_i18n 0
- [ ] **Step 5: Commit** — `git commit -m "feat(report-tables): semantic column classes and conservation test harness"`

---

### Task 3: traffic 家族套殼（traffic / security_risk / network_inventory，含 draft 變體與 shim）

**Files:**
- Modify: `src/report/exporters/html_exporter.py`（`_TrafficReportBase._build()` 撰寫日座標 L512-841；nav/_nav_spec L640-683；骨架 L829-841；cover 分支 L796-828）
- Create: `tests/report_shell/baselines/{traffic,security_risk,network_inventory}.json`
- Test: `tests/test_report_shell_migration.py`（新檔，後續批次 parametrize 擴充）

**Interfaces:**
- Consumes: T1 `ShellCover/ShellSection/build_shell_document`；T2 `conservation_diff`＋`BUILDERS`＋baselines
- Produces: 三型輸出改為新殼 DOM（`div.sheet>div.doc`），章節內容 class（`.report-table-panel`/`.chart-static`/`.finding-card` 等）不變；`REPORT_KIND`/`_ordered_section_keys()`/`_include_maturity()`/`_hero_includes_findings()` 四個子類 hook 與 `_filename()` 全部不動（檔名 prefix 是 scheduler 對帳鍵，report_scheduler.py:669-690）

- [ ] **Step 1: 產基準（改碼前）** — `python3 scripts/capture_report_baselines.py --types traffic,security_risk,network_inventory`；commit `test(report-shell): capture pre-reskin baselines for traffic family`
- [ ] **Step 2: 寫失敗測試**

```python
# tests/test_report_shell_migration.py
import json, pathlib, pytest
from bs4 import BeautifulSoup
from tests.report_shell.conservation import conservation_text, label_value_preserved
from tests.report_shell.fixtures import BUILDERS

BASELINES = pathlib.Path(__file__).parent / "report_shell" / "baselines"
MIGRATED = ["traffic", "security_risk", "network_inventory"]   # T4/T5 逐批追加
# 豁免清單：逐條附理由，禁止批次塞入
ALLOWLIST = {
    # 舊 aside.report-toc 的章節錨點文字：新殼 TOC 由 sections 重新產生同文案；
    # 若此條造成漏網（文案真的消失），結構閘的 toc==sections 斷言會補抓
}

@pytest.mark.parametrize("rtype", MIGRATED)
def test_conservation_against_baseline(rtype):
    base = json.loads((BASELINES / f"{rtype}.json").read_text())
    html = BUILDERS[rtype]()
    _, flat = conservation_text(html)
    lost = [t for t in base["leaves"]
            if t not in ALLOWLIST.get(rtype, frozenset())
            and t not in flat
            and not label_value_preserved(t, flat)]   # 與 conservation_diff 同一豁免邏輯，自 conservation.py import
    assert lost == [], f"{rtype} 遺失 {len(lost)} 段內容: {lost[:10]}"

@pytest.mark.parametrize("rtype", MIGRATED)
def test_table_and_chart_counts_conserved(rtype):
    base = json.loads((BASELINES / f"{rtype}.json").read_text())
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    assert len(soup.select("table.report-table")) == base["table_count"]
    assert len(soup.select("figure.chart-static")) == base["chart_count"]

@pytest.mark.parametrize("rtype", MIGRATED)
def test_new_shell_structure(rtype):
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    assert soup.select_one("div.sheet > div.doc")
    assert soup.select_one("header.cover h1")
    toc = [a["href"].lstrip("#") for a in soup.select("nav.toc ol a")]
    body_ids = [s["id"] for s in soup.select("section.exec[id], div.chapters > section.chapter")]
    assert toc == body_ids                       # 無聲消失章節在此炸掉（原型 417-424 教訓）
    assert soup.select_one("div.report-shell") is None    # 舊殼容器不得殘留
    assert soup.select_one("aside.report-toc") is None
    assert 'class="print-btn"' in str(soup)
```

- [ ] **Step 3: 跑測試確認失敗**（三型仍輸出舊殼 → structure 測試 FAIL）
- [ ] **Step 4: 實作** — `_TrafficReportBase._build()` 重構：
  - **cover**：`ShellCover(title=t("rpt_tr_title"…hero h1 同源鍵), doc_title=<title> 同源字串, type_label=cover-type 既有字串, grade/score=maturity（`_include_maturity()` 為真時）, badges=profile badge＋draft pill（`compute_draft` 時，沿用 `rpt_hdr_draft_enabled`）, meta={PCE, org, date_range, generated_at})`——三個文案（doc_title/hero h1/type_label）各自獨立來源，禁止互相推導（原型 C1 事故）
  - **exec**：`render_exec_summary_html()` 輸出包成 `ShellSection(id="exec-summary", kind="exec")`
  - **summary 章**：原 `_hero` 內容**除 kicker/h1/subtitle（移入 cover）外全數保留**（pills/maturity block/trend/findings block/cap banner）作為第一個 detail 章的開頭，接原 `_sec["summary"]` 內容
  - **各章**：`_sec` dict 的每個 key → `ShellSection(id, title=同 _nav_spec 的 i18n 文案, html=既有 _section() 內容去掉外層 nav 依賴, kind="finding" if key=="findings" else "detail", tone/marks=自該章 findings 的 severity 統計（`_findings_block` 既有資料），順序照 `_ordered_section_keys()`)`
  - **appendix_html**：原 `<footer>` 內容；**rule_index**：findings 的 (rule_id, title, severity) 清單（SecurityRisk 有、TrafficFlows/NetworkInventory 空）
  - 刪除 `_nav_link`/`_nav_spec`/nav_html 組裝與 L829-841 舊骨架；`_CSS = build_css('traffic')` 模組層求值移除（此檔不再用 build_css；`_HIGHLIGHT_CSS` 改經 `extra_head` 傳入）
- [ ] **Step 5: 跑測試至綠** — migration 測試 3 型全綠；既有 traffic 家族測試（test_traffic_report_split、test_traffic_flows_html_exporter、test_html_draft_pill、test_mod15_html_trim、test_html_size、test_report_no_kpi_duplication 的 traffic 案例、test_e2e_report_html_redesign）依新殼 DOM 修正選擇器但**斷言語意不得弱化**（每檔修正前後斷言數記入任務回報）；全套 pytest 綠；audit_i18n 0
- [ ] **Step 6: Commit** — `git commit -m "feat(reports): migrate traffic family to v2 shell"`

---

### Task 4: audit / ven_status / policy_usage 套殼

**Files:**
- Modify: `src/report/exporters/audit_html_exporter.py`（`_build()` L177-279、硬編 nav L185-198）
- Modify: `src/report/exporters/ven_html_exporter.py`（`_build()` L96-287、nav L104-118、`_section()` L511-531）
- Modify: `src/report/exporters/policy_usage_html_exporter.py`（`_build()` L172-278、nav L188-201）
- Create: `tests/report_shell/baselines/{audit,ven_status,policy_usage}.json`
- Test: `tests/test_report_shell_migration.py`（`MIGRATED += ["audit", "ven_status", "policy_usage"]`）

**Interfaces:**
- Consumes: 同 T3（`ShellCover/ShellSection/build_shell_document`、conservation harness）
- Produces: 三型新殼輸出；`STRINGS`/`_s` lambda i18n 模式不動；`_attention_section()`（audit）的 `.audit-attn-item` 卡片 class 不改名（shell.css 396-398 三 selector 共用組直接吃到）

- [ ] **Step 1: 產基準（改碼前）** — `python3 scripts/capture_report_baselines.py --types audit,ven_status,policy_usage`；commit `test(report-shell): capture pre-reskin baselines for audit/ven/policy-usage`
- [ ] **Step 2: 失敗測試** — `MIGRATED` 追加三型，跑 `pytest tests/test_report_shell_migration.py -q` 確認新增 9 個案例 FAIL（structure）
- [ ] **Step 3: 實作** — 三檔各自把「硬編 nav 清單＋`_section()` 串接＋骨架 f-string」改為 ShellSection 清單：
  - audit：5 章（summary/health/users/policy/correlation；policy 章保留既有 `visible_in` 條件——條件為假時該章不進 sections，TOC 自動一致）；hero 的 `_attention_section()`＋`_severity_dist_html()`＋trend 留在 summary 章；tone/marks 自 severity 分布統計；kind：summary 含 attention cards → "finding"，其餘 "detail"
  - ven_status：6 章；`_section()` 的 `(count)` 章名字尾保留在 title 字串內；`_estate_inventory_section()`/`_ransomware_posture_section()` 內容原樣入章
  - policy_usage：6 章；`_reconciled_mod00()`＋`_execution_html()`＋`_attention_html()` 留 summary 章
  - 三檔的 `<footer>` → appendix_html；`_HIGHLIGHT_CSS` → extra_head；模組層 `build_css()` 求值移除
- [ ] **Step 4: 跑測試至綠** — migration 6 型全綠；既有 audit/ven/policy_usage 測試選擇器修正（test_report_no_kpi_duplication 的三型案例、test_ven_report_compact/_estate/_ransomware、test_policy_usage_report、test_audit_kpi_i18n 等以 grep 實測為準）；全套綠；audit_i18n 0
- [ ] **Step 5: Commit** — `git commit -m "feat(reports): migrate audit, ven-status and policy-usage to v2 shell"`

---

### Task 5: policy_diff / app_summary / rule_hit_count / readiness 套殼

**Files:**
- Modify: `src/report/exporters/policy_diff_html_exporter.py`（`_render_html()` L118-176）
- Modify: `src/report/exporters/app_summary_html_exporter.py`（`_render_html()` L131-188，含空資料分支 L143-147）
- Modify: `src/report/exporters/rule_hit_count_html_exporter.py`（`_render_html()` L142-178）
- Modify: `src/report/exporters/readiness_html_exporter.py`（`_render_html()` L145-183）
- Create: `tests/report_shell/baselines/{policy_diff,app_summary,rule_hit_count,readiness}.json`
- Test: `tests/test_report_shell_migration.py`（`MIGRATED` 補滿 10 型）

**Interfaces:**
- Consumes: 同 T3
- Produces: 四型新殼輸出。此四型現況**無 TOC、部分無 footer、readiness/rhc 無 `lang`/`data-report-title`**——新殼一律補齊（TOC 由 sections 自動產生；`data-report-title` 由 cover.type_label 帶入）；此為「新增」非「移除」，不觸守恆

- [ ] **Step 1: 產基準（改碼前）** — `python3 scripts/capture_report_baselines.py --types policy_diff,app_summary,rule_hit_count,readiness`；commit `test(report-shell): capture pre-reskin baselines for remaining four types`
- [ ] **Step 2: 失敗測試** — `MIGRATED` 補滿 10 型，確認新增 12 個案例 FAIL
- [ ] **Step 3: 實作**：
  - policy_diff：KPI row → exec 章；ruleset-changes/rule-changes/3 個物件章（迴圈）＋attribution note → detail 章；自有 `_table()` 維持（欄數少，不接 wide hint）
  - app_summary：空資料分支也走新殼（cover＋單一「無資料」detail 章，敘事文字原樣保留）；`_trunc_note()` 的截斷附註文案原樣入章（CLAUDE.md 截斷邏輯明確之既有實作，不得順手刪）
  - rule_hit_count：KPI row → exec；`_notes()` ＋ 3 章 tuple list → detail 章
  - readiness：sections tuple list（L153-167）直接映射 ShellSection；`readiness-summary` 為 exec、其餘 detail
  - 四檔模組層 `build_css()` 求值移除
- [ ] **Step 4: 跑測試至綠** — migration 10 型全綠；既有四型測試選擇器修正（test_policy_diff_html_exporter、test_app_summary_report、test_rule_hit_count_html_exporter、test_readiness_html_exporter、test_print_button_all_exporters）；全套綠；audit_i18n 0
- [ ] **Step 5: Commit** — `git commit -m "feat(reports): migrate policy-diff, app-summary, rule-hit-count and readiness to v2 shell"`

---

### Task 6: 舊殼移除＋跨檔測試收斂

**Files:**
- Modify: `src/report/exporters/report_css.py` → 刪 `FONT_LINK`/`_FONT_FILES`/`_font_face_css()`/`REPORT_FONT_FACE_CSS`/`BASE_CSS`/`TRAFFIC_CSS`/`AUDIT_CSS`/`VEN_CSS`/`POLICY_USAGE_CSS`/`POLICY_DIFF_CSS`/`MODERN_SHELL_CSS`/`EXEC_SUMMARY_CSS`/`build_css()`；`TABLE_JS` 搬至 `report_shell.py` 後**整檔刪除** `report_css.py`
- Delete: `src/report/exporters/cover_page.py`（雙封面由 shell cover 取代；10 型皆已不引用後才可刪）
- Modify: 殘餘引用清理（動工時以 `grep -rn "build_css\|cover_page\|BASE_CSS\|REPORT_FONT_FACE_CSS\|report_css" src/ tests/` 實測為準；已知消費者：`tests/test_report_print_layout.py`、`test_report_toc_contrast.py`、`test_trend_meta.py:166-168`、`test_phase34_attack_summaries.py:211`、`test_report_cover_page.py`、`test_exporter_print_button.py`）
- Test: 上述測試逐檔重寫為新殼等價斷言

**Interfaces:**
- Consumes: T3-T5 完成（10 型皆不再 import report_css/cover_page）
- Produces: `report_shell.SHELL_CSS`/`TABLE_JS` 為唯一報表樣式/腳本來源；repo 內 `git grep -l "report-shell\|report-toc\|build_css" src/` 為空

- [ ] **Step 1: 失敗測試（守門先行）** — 在 `tests/test_report_shell_renderer.py` 追加：

```python
def test_no_legacy_shell_remnants_in_src():
    import subprocess
    out = subprocess.run(["git", "grep", "-l", "-E",
                          r"class=\"report-shell\"|report-cover-block|build_css\(",
                          "--", "src/"], capture_output=True, text=True).stdout
    assert out.strip() == "", f"legacy shell remnants: {out}"
```

- [ ] **Step 2: 逐檔遷移測試**——每檔「舊斷言→新斷言」對照表記入任務回報，斷言語意不得弱化：
  - `test_report_print_layout.py` → 改斷言 `SHELL_CSS`：`@page wide`、`break-before: page`（.chapter）、`table-header-group`、`.cell-long::details-content`、tri-grid 列印兩欄；刪除 `.report-cover` 相關案例（雙封面已不存在），新增 cover `break-after: page` 案例
  - `test_report_toc_contrast.py` → 對 `SHELL_CSS` 的 `.toc a` 色彩對比重寫
  - `test_report_cover_page.py` → 斷言 `header.cover` 單封面含 PCE/org/date（build_shell_document 輸出）
  - `test_trend_meta.py:166-168` → 刪 data-URI 字型斷言，改斷言 `SHELL_CSS` 使用系統字體堆疊（`"Noto Sans"` in SHELL_CSS 且 `data:font` not in）——字型內嵌移除是 shell.css 設計決定（系統字體堆疊，檔案大幅縮小）
  - `test_exporter_print_button.py` → 源碼掃描對象由「每個 *html_exporter.py 檔含 print-btn」改為「report_shell.py 含 print-btn ＋ 10 型 BUILDERS 輸出各含 print-btn」（輸出面的 test_print_button_all_exporters 保持原樣繼續守）
- [ ] **Step 3: 刪碼至綠** — 刪 report_css.py 與 cover_page.py、TABLE_JS 搬家、殘餘 import 清理；`pytest -q` 全套綠；`test_html_size.py` 確認 traffic HTML 顯著縮小（字型 base64 移除）並把前後大小記入回報；audit_i18n 0（被孤兒化的舊殼 i18n 鍵——如雙封面專用鍵——一併清出 JSON，清單記入回報）
- [ ] **Step 4: Commit** — `git commit -m "refactor(reports): remove legacy report shell, css and dual cover"`

---

### Task 7: 測試機真資料重產全 11 型＋雙寬度/PDF 視覺驗證（驗收閘門）

**Files:**
- Create: `scripts/verify_report_render.py`（轉錄 `design/v2/tools/reskin_report.py` 三個 verify 函式，改為對任意已產出報表 HTML 操作）
- Create: `tmp/phase2b-verification.md`（驗證報告，gitignored 目錄）
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: T1-T6 全部；測試機 root@172.16.15.106:/root/illumio-ops

```
# scripts/verify_report_render.py <report.html> [--out-dir tmp/phase2b-shots]
# 對單一報表檔執行：
#  1. Playwright 開檔 → 1280 與 800 兩寬度整頁截圖（PNG，PIL 量化 256 色防爆量——原型 _shrink_png）
#  2. page.pdf(format="A4") 產 PDF
#  3. no-truncation：HTML 文字節點（>=4 字元，跳過 details.cell-long 整格）逐段在 pdftotext 文字層查存
#  4. print-clipping：列印模擬下量 table.scrollWidth > panel.clientWidth+1，
#     直式 695px / 橫式 1035px（原型 PRINT_WIDTH_PORTRAIT/LANDSCAPE）
# exit 非 0 = 任一項失敗；輸出逐項統計行
```

- [ ] **Step 1: 部署** — 測試機 `git pull --ff-only && systemctl restart illumio-ops`；`git rev-parse HEAD` 兩端一致證據記入報告
- [ ] **Step 2: 真資料重產全 11 型** — 測試機上逐一執行（以當下 CLI 為準，撰寫日對照 `src/cli/report.py` 的 12 個子指令）：

```bash
python3 illumio-ops.py report traffic
python3 illumio-ops.py report security
python3 illumio-ops.py report inventory
python3 illumio-ops.py report draft-policy          # traffic 家族 draft 變體（cover 須見 draft badge）
python3 illumio-ops.py report audit
python3 illumio-ops.py report ven-status
python3 illumio-ops.py report policy-usage
python3 illumio-ops.py report rule-hit-count
python3 illumio-ops.py report app-summary
python3 illumio-ops.py report readiness
python3 illumio-ops.py report policy-diff
python3 illumio-ops.py report resolve               # 非 HTML，僅確認 JSON/CSV 產出不炸
```
  兩語系各跑一輪（config 切 zh_TW/en 或 CLI lang 參數，以現碼為準）；metadata sidecar 逐檔確認仍成對產出（`ls reports/*.metadata.json`）
- [ ] **Step 3: 機械驗證** — 對 10 型 HTML（＋draft 變體共 11 份×2 語系）逐檔跑 `scripts/verify_report_render.py`：no-truncation 0 缺、print-clipping 0 表、雙寬度截圖產出
- [ ] **Step 4: 逐頁親驗（CLAUDE.md 硬規則，不可委派給機械斷言）** — 每份 PDF 逐頁人工檢視＋1280/800 截圖親看：封面三文案正確（完整標題非型別短標）、TOC 與章節一致、寬表 A4 橫式無裁切（特別驗 ≥10 欄表與 tri-grid 數字完整——原型「966,315→966,31」案例）、長文欄 PDF 文字層完整、CJK 無豆腐字、mark chips 全顯示；檢查結果逐型逐頁記入 `tmp/phase2b-verification.md`（型別×語系×頁的核對矩陣＋截圖清單＋verify 輸出全文）
- [ ] **Step 5: 真機 e2e** — `ILLUMIO_OPS_E2E_BASE_URL=https://172.16.15.106:5001 pytest tests/test_gui_app_report_generate.py tests/test_reports_async_generate.py -q`（GUI 產報流程對新殼無回歸；檔案清單頁能列出新產報表）
- [ ] **Step 6: Commit** — `git add CHANGELOG.md scripts/verify_report_render.py && git commit -m "docs: phase 2b report reskin verification evidence"`（驗證報告要點入 CHANGELOG；tmp/ 報告全文交使用者）

---

## Self-Review 紀錄

- **Roadmap 2B 承諾對照**：`report_css.py` 依 shell.css 重寫＝T1（SHELL_CSS）＋T6（舊常數刪除）；「11 型 exporter 逐一套統一殼」＝T3-T5（HTML 實為 10 型，第 11 型 policy_resolver 無 HTML，T7 Step 2 仍重產確認）；reskin_report.py 章節模型為原型＝T1 ShellSection/ShellCover＋T2 conservation 轉錄；測試機真資料重產全 11 型＝T7 Step 2；雙寬度＋PDF 逐頁親驗（CLAUDE.md 硬規則）＝T7 Step 3-4 ✓
- **前置**：roadmap 標 2B 前置=2A 合併（token 來源）；實查 shell.css 自帶列印安全 token 子集（§1，行 19-95），與 GUI tokens.css 無檔案級依賴——2A 未合併亦可動工，但仍依 roadmap 排序執行 ✓
- **佔位掃描**：無 TBD/「適當處理」；fixtures 轉錄與測試選擇器修正均標注具體來源測試檔名（來源指引非佔位，2A 體例先例）；T6 grep 清單標「以實測為準」＋已列已知六檔 ✓
- **介面命名一致**：`ShellCover/ShellSection/build_shell_document/wide_table_attrs/SHELL_CSS/conservation_diff/conservation_text/norm/BUILDERS/MIGRATED/ALLOWLIST` 貫穿 T1-T7 同名 ✓
- **守恆例外透明**：允許的移除僅「雙封面防禦性隱藏規則」與「章名去重（title 相同才移）」；print-btn/TABLE_JS/章序/截斷附註明文保留；hint 等新增內容不觸舊→新守恆方向 ✓
- **額度切點**：7 任務各自獨立 commit＋CI 綠；T3-T5 各批含自己的基準與守門，撞額度可停在任一批 ✓
