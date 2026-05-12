# Report Print Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全面改善 4 種報告的列印版面：修正長表格截斷問題、新增封面頁、實作版型 B/C（說明+圖表並排 / 表格+圖表並排）、每頁頁碼。

**Architecture:** CSS 層（`report_css.py`）加入 `@media print` 完整規則，包含版型 B/C class、封面樣式、`@page` 頁碼；`cover_page.py` 提供共用封面 HTML helper；4 個 exporter 各加入封面頁呼叫與 `data-report-title`。

**Tech Stack:** Python 3.12, HTML/CSS (`@media print`, `@page`), pytest

---

## 檔案異動清單

| 操作 | 路徑 | 說明 |
|------|------|------|
| Modify | `src/report/exporters/report_css.py` | 重寫 `@media print`、加 `.layout-b/.layout-c`、封面 CSS、`@page` 頁碼 |
| Create | `src/report/exporters/cover_page.py` | 封面頁 HTML helper |
| Modify | `src/report/exporters/report_i18n.py` | 加 `rpt_cover_*` keys 到 STRINGS |
| Modify | `src/i18n_en.json` | 加 `rpt_cover_*` keys |
| Modify | `src/i18n_zh_TW.json` | 加 `rpt_cover_*` keys |
| Modify | `src/report/exporters/html_exporter.py` | 封面頁、`date_range`/`pce_url`/`org_name` 參數、layout B/C 結構（mod02, mod10）、`data-report-title` |
| Modify | `src/report/exporters/audit_html_exporter.py` | 封面頁、新參數、`data-report-title` |
| Modify | `src/report/exporters/policy_usage_html_exporter.py` | 封面頁、新參數、`data-report-title` |
| Modify | `src/report/ven_status_generator.py` | 封面頁、新參數、`data-report-title` |
| Modify | `src/report/report_generator.py` | 傳遞 `pce_url`、`org_name`、`date_range` |
| Modify | `src/report/audit_generator.py` | 同上 |
| Modify | `src/report/policy_usage_generator.py` | 同上 |
| Test | `tests/test_report_print_layout.py` | 封面頁 + CSS class 驗證 |

---

## Task 1：重寫 @media print CSS + 封面樣式

**背景：** `report_css.py` 的 `BASE_CSS` 字串包含所有 CSS。目前 `@media print` 在 line 254–270。問題：`.card { page-break-inside: avoid }` 導致長表格整塊被推到下一頁。需要：移除該規則、加 `thead` 重複、`tr` 不截斷、版型 B/C、封面頁樣式、`@page` 頁碼。

**Files:**
- Modify: `src/report/exporters/report_css.py`（`@media print` block + `:root` 後加封面 CSS）
- Test: `tests/test_report_print_layout.py`

- [ ] **Step 1.1: 寫失敗測試**

```python
# tests/test_report_print_layout.py
from src.report.exporters.report_css import BASE_CSS

def test_card_no_longer_has_page_break_inside_avoid():
    # 新版不應對 .card 整體套 page-break-inside: avoid
    lines = [l.strip() for l in BASE_CSS.split('\n') if 'page-break-inside: avoid' in l]
    card_lines = [l for l in lines if l.startswith('.card')]
    assert card_lines == [], f"Found: {card_lines}"

def test_thead_display_table_header_group():
    assert 'thead { display: table-header-group' in BASE_CSS

def test_tr_page_break_inside_avoid():
    assert 'tr { page-break-inside: avoid' in BASE_CSS

def test_wide_table_font_size_in_print():
    assert '.report-table-panel--wide .report-table { font-size: 8pt' in BASE_CSS

def test_cover_page_css_present():
    assert '.report-cover {' in BASE_CSS

def test_page_counter_present():
    assert 'counter(page)' in BASE_CSS
```

- [ ] **Step 1.2: 執行確認失敗**

```bash
cd /home/harry/rd/illumio-ops
python -m pytest tests/test_report_print_layout.py -v 2>&1 | tail -15
```

預期：6 個 FAIL。

- [ ] **Step 1.3: 找到並替換 @media print block**

在 `src/report/exporters/report_css.py` 找到 line 254 的 `@media print {`，將整個 block（到 line 270 的 `}`）替換為：

```css
  @media print {
    nav { display: none; }
    .print-btn { display: none; }
    main { margin-left: 0; padding: 12px; }
    body { font-size: 10pt; }
    * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
    .card { box-shadow: none; border: 1px solid var(--slate-20); }
    thead { display: table-header-group; }
    tr { page-break-inside: avoid; }
    .report-table-panel--wide .report-table { font-size: 8pt; }
    .report-table-panel { box-shadow: none; }
    .report-table-panel--wide::after { display: none; }
    .report-table-panel--wide .report-table thead th:first-child,
    .report-table-panel--wide .report-table tbody td:first-child { position: static; box-shadow: none; }
    section { page-break-before: always; }
    section#summary { page-break-before: avoid; }
    section.report-cover { page-break-before: avoid !important; page-break-after: always; }
    .chart-container { page-break-inside: avoid; max-height: 185px; overflow: hidden; }
    .finding-card { page-break-inside: avoid; }
    footer { page-break-before: avoid; }
    .layout-b .section-top { display: flex; gap: 20px; align-items: flex-start; margin-bottom: 12px; }
    .layout-b .section-top > .section-intro { flex: 1; margin: 0; }
    .layout-b .section-top > .chart-container { flex: 1; max-height: 185px; overflow: hidden; }
    .layout-c .section-body { display: flex; gap: 16px; align-items: flex-start; }
    .layout-c .section-body > .report-table-panel { flex: 1; }
    .layout-c .section-body > .chart-container { flex: 1; max-height: none; }
  }
```

- [ ] **Step 1.4: 在 BASE_CSS 中加封面頁 CSS 和 @page 規則**

在 `BASE_CSS` 的 `@media print` block **之前**（約 line 252 附近），找到合適位置插入以下 CSS（在 `BASE_CSS` 字串內，注意縮排）：

```css
  @page {
    margin: 15mm 15mm 22mm;
  }
  @page :not(:first) {
    @bottom-right {
      content: counter(page) " / " counter(pages);
      font-size: 8pt;
      color: #888;
      font-family: sans-serif;
    }
  }
  .report-cover { background: linear-gradient(160deg, #1a3f4b 0%, #2a5b6b 60%, #1a3f4b 100%); color: #fff; padding: 40px 36px; display: flex; flex-direction: column; justify-content: space-between; min-height: 240mm; border: none !important; box-shadow: none !important; }
  .cover-eyebrow { font-size: 10pt; letter-spacing: 2px; opacity: 0.6; text-transform: uppercase; margin-bottom: 8px; }
  .cover-title { font-size: 28pt; font-weight: 700; line-height: 1.2; margin-bottom: 8px; }
  .cover-rule { width: 40px; height: 3px; background: var(--orange); margin: 16px 0; }
  .cover-type { display: inline-block; background: rgba(255,255,255,0.15); font-size: 10pt; padding: 4px 12px; border-radius: 12px; margin-bottom: 20px; }
  .cover-meta { font-size: 10pt; opacity: 0.8; line-height: 2; }
  .cover-footer { border-top: 1px solid rgba(255,255,255,0.2); padding-top: 16px; display: flex; justify-content: space-between; align-items: flex-end; margin-top: 24px; }
  .cover-org { font-size: 14pt; font-weight: 600; }
  .cover-generated { font-size: 10pt; opacity: 0.7; text-align: right; }
```

- [ ] **Step 1.5: 執行確認測試通過**

```bash
python -m pytest tests/test_report_print_layout.py -v 2>&1 | tail -10
```

預期：6 個 PASS。

- [ ] **Step 1.6: Commit**

```bash
git add src/report/exporters/report_css.py tests/test_report_print_layout.py
git commit -m "feat(css): print layout foundation — fix table truncation, add cover/layout CSS"
```

---

## Task 2：封面頁 Helper + i18n Keys

**背景：** 4 個 exporter 都需要同樣的封面頁 HTML。建立 `cover_page.py` 集中管理，避免重複。i18n key 存在 `report_i18n.py` STRINGS dict 和兩個 JSON 檔。

**Files:**
- Create: `src/report/exporters/cover_page.py`
- Modify: `src/report/exporters/report_i18n.py`（STRINGS dict）
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`
- Test: `tests/test_report_print_layout.py`

- [ ] **Step 2.1: 在 test_report_print_layout.py 加封面 helper 測試**

在 `tests/test_report_print_layout.py` 末尾加：

```python
from src.report.exporters.cover_page import build_cover_page

def test_cover_page_contains_title():
    html = build_cover_page(title="Traffic Security Report", report_type="Security Risk",
                             date_range=("2026-04-01", "2026-05-11"),
                             pce_url="pce.example.com", org_name="Acme Corp", lang="en")
    assert "Traffic Security Report" in html
    assert "pce.example.com" in html
    assert "Acme Corp" in html
    assert "report-cover" in html

def test_cover_page_zh_tw():
    html = build_cover_page(title="流量安全報告", report_type="",
                             date_range=("", ""), pce_url="", org_name="", lang="zh_TW")
    assert "流量安全報告" in html
    assert "產生時間" in html

def test_cover_page_empty_optional_fields():
    html = build_cover_page(title="Test", report_type="", date_range=("", ""),
                             pce_url="", org_name="", lang="en")
    # Empty fields should not render their wrapper divs
    assert "📅" not in html
    assert "🖥" not in html
```

- [ ] **Step 2.2: 執行確認失敗**

```bash
python -m pytest tests/test_report_print_layout.py -k "cover" -v 2>&1 | tail -10
```

預期：3 個 FAIL（`ModuleNotFoundError: cover_page`）。

- [ ] **Step 2.3: 建立 cover_page.py**

建立 `src/report/exporters/cover_page.py`：

```python
from __future__ import annotations
from datetime import datetime
from src.report.exporters.report_i18n import STRINGS


def _s(key: str, lang: str) -> str:
    entry = STRINGS.get(key, {})
    return entry.get(lang) or entry.get("en", key)


def build_cover_page(
    title: str,
    report_type: str,
    date_range: tuple[str, str] = ("", ""),
    pce_url: str = "",
    org_name: str = "",
    lang: str = "en",
) -> str:
    date_str = " – ".join(d for d in date_range if d)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    date_line = (
        f'<div>📅 {_s("rpt_cover_date_range", lang)}: {date_str}</div>'
        if date_str else ""
    )
    pce_line = (
        f'<div>🖥 {_s("rpt_cover_pce", lang)}: {pce_url}</div>'
        if pce_url else ""
    )
    type_badge = (
        f'<div class="cover-type">{report_type}</div>'
        if report_type else ""
    )
    org_html = (
        f'<div class="cover-org">{org_name}</div>'
        if org_name else '<div></div>'
    )

    return (
        '<section class="report-cover card" id="cover">'
        '<div>'
        '<div class="cover-eyebrow">Illumio Operations</div>'
        f'<div class="cover-title">{title}</div>'
        '<div class="cover-rule"></div>'
        f'{type_badge}'
        f'<div class="cover-meta">{date_line}{pce_line}</div>'
        '</div>'
        '<div class="cover-footer">'
        f'{org_html}'
        '<div class="cover-generated">'
        f'<div style="font-size:9pt;opacity:0.5;margin-bottom:2px">'
        f'{_s("rpt_cover_generated", lang)}</div>'
        f'<div>{now_str}</div>'
        '</div>'
        '</div>'
        '</section>'
    )
```

- [ ] **Step 2.4: 加 i18n keys 到 report_i18n.py**

在 `src/report/exporters/report_i18n.py` 的 `STRINGS` dict 中，找到其他 `rpt_` key 附近，加入：

```python
    "rpt_cover_date_range": {"en": "Data Range", "zh_TW": "資料範圍"},
    "rpt_cover_pce":        {"en": "PCE", "zh_TW": "PCE"},
    "rpt_cover_generated":  {"en": "Generated", "zh_TW": "產生時間"},
    "rpt_cover_type_security":   {"en": "Security Risk Profile", "zh_TW": "安全風險分析"},
    "rpt_cover_type_audit":      {"en": "Audit Report", "zh_TW": "稽核報告"},
    "rpt_cover_type_policy":     {"en": "Policy Usage Report", "zh_TW": "政策使用報告"},
    "rpt_cover_type_ven":        {"en": "VEN Status Report", "zh_TW": "VEN 狀態報告"},
```

- [ ] **Step 2.5: 加 i18n keys 到 JSON 檔**

在 `src/i18n_en.json` 找到 `"rpt_chart_top_allowed_ports"` 附近，加入（注意 JSON 逗號）：

```json
"rpt_cover_date_range": "Data Range",
"rpt_cover_pce": "PCE",
"rpt_cover_generated": "Generated",
"rpt_cover_type_security": "Security Risk Profile",
"rpt_cover_type_audit": "Audit Report",
"rpt_cover_type_policy": "Policy Usage Report",
"rpt_cover_type_ven": "VEN Status Report",
```

在 `src/i18n_zh_TW.json` 同位置加入：

```json
"rpt_cover_date_range": "資料範圍",
"rpt_cover_pce": "PCE",
"rpt_cover_generated": "產生時間",
"rpt_cover_type_security": "安全風險分析",
"rpt_cover_type_audit": "稽核報告",
"rpt_cover_type_policy": "政策使用報告",
"rpt_cover_type_ven": "VEN 狀態報告",
```

- [ ] **Step 2.6: 驗證 JSON 合法**

```bash
python3 -c "import json; json.load(open('src/i18n_en.json')); json.load(open('src/i18n_zh_TW.json')); print('OK')"
```

- [ ] **Step 2.7: 執行測試**

```bash
python -m pytest tests/test_report_print_layout.py -k "cover" -v 2>&1 | tail -10
```

預期：3 個 PASS。

- [ ] **Step 2.8: Commit**

```bash
git add src/report/exporters/cover_page.py \
        src/report/exporters/report_i18n.py \
        src/i18n_en.json src/i18n_zh_TW.json \
        tests/test_report_print_layout.py
git commit -m "feat(report): cover page helper and i18n keys"
```

---

## Task 3：Traffic/Security Report (html_exporter.py) 套用封面 + 版型 B/C

**背景：** `html_exporter.py` 的 `HtmlExporter` 目前 `__init__` 沒有 `date_range`、`pce_url`、`org_name`。`_build()` 在 line ~582 開始組裝 `<body>`。
- mod02 有 pie chart + 多個子表格 → 版型 B
- mod10 有 bar chart + port 表格（2欄）→ 版型 C

`_section()` method signature（line ~673）：
```python
def _section(self, id_: str, i18n_key: str, title: str, content: str,
             intro_key: str = '', intro_en: str = '') -> str:
```
回傳 `<section id="..." class="card">...</section>`。

**Files:**
- Modify: `src/report/exporters/html_exporter.py`
- Test: `tests/test_report_print_layout.py`

- [ ] **Step 3.1: 加封面 + body 屬性的測試**

在 `tests/test_report_print_layout.py` 加：

```python
from unittest.mock import patch
import pandas as pd
from src.report.exporters.html_exporter import HtmlExporter

def _minimal_results() -> dict:
    # 最小化的 module results，讓 HtmlExporter 不 crash
    return {k: {} for k in [
        "mod01", "mod02", "mod03", "mod04", "mod05", "mod06",
        "mod07", "mod08", "mod09", "mod10", "mod11", "mod12",
        "mod13", "mod14", "mod15",
    ]}

def test_html_exporter_cover_page():
    exp = HtmlExporter(
        _minimal_results(),
        pce_url="pce.test", org_name="TestOrg",
        date_range=("2026-01-01", "2026-05-01"), lang="en",
    )
    html = exp.build()
    assert 'class="report-cover' in html
    assert "pce.test" in html
    assert "TestOrg" in html

def test_html_exporter_data_report_title():
    exp = HtmlExporter(_minimal_results(), lang="en")
    html = exp.build()
    assert 'data-report-title=' in html
```

- [ ] **Step 3.2: 執行確認失敗**

```bash
python -m pytest tests/test_report_print_layout.py -k "html_exporter" -v 2>&1 | tail -10
```

預期：FAIL（`TypeError: unexpected keyword argument 'pce_url'` 或類似）。

- [ ] **Step 3.3: 擴充 HtmlExporter.__init__**

在 `src/report/exporters/html_exporter.py` 找到 `class HtmlExporter` 的 `__init__`（約 line 390），在現有參數後加入三個選填參數：

找到：
```python
def __init__(self, results: dict, data_source: str = "",
             profile: str = "security_risk", detail_level: str = _REPORT_DETAIL_LEVEL,
             compute_draft: bool = False, lang: str = "en"):
    self._r = results
    self._data_source = data_source
```

改為：
```python
def __init__(self, results: dict, data_source: str = "",
             profile: str = "security_risk", detail_level: str = _REPORT_DETAIL_LEVEL,
             compute_draft: bool = False, lang: str = "en",
             date_range: tuple[str, str] = ("", ""),
             pce_url: str = "", org_name: str = ""):
    self._r = results
    self._data_source = data_source
    self._date_range = date_range
    self._pce_url = pce_url
    self._org_name = org_name
```

- [ ] **Step 3.4: 在 _build() 裡加封面頁 + data-report-title**

在 `html_exporter.py` 找到 `_build()` 方法（約 line 420）。

找到組裝 `<body>` 的地方：
```python
'<body>' + nav_html + '<main>' + body + '</main>'
```

改為：
```python
'<body data-report-title="' + _report_title + '">' + cover_html + nav_html + '<main>' + body + '</main>'
```

在 `_build()` 方法的開頭（import 部分之後，在 `_s = lambda ...` 定義之後）加入：

```python
from src.report.exporters.cover_page import build_cover_page as _build_cover

_report_title = _s("rpt_cover_type_security") if profile == "security_risk" else _s("rpt_cover_type_security")
cover_html = _build_cover(
    title=_report_title,
    report_type=_report_title,
    date_range=self._date_range,
    pce_url=self._pce_url,
    org_name=self._org_name,
    lang=self._lang,
)
```

> 注意：`from` import 應移至檔案頂部（`import` 區段），不要放在函式內。

- [ ] **Step 3.5: 擴充 _section() 支援 layout 參數**

找到 `_section()` 方法（約 line 673）：
```python
def _section(self, id_: str, i18n_key: str, title: str, content: str,
             intro_key: str = '', intro_en: str = '') -> str:
```

在 `intro_en: str = ''` 後加 `layout: str = ''`，並修改 `return` 中的 class：

```python
def _section(self, id_: str, i18n_key: str, title: str, content: str,
             intro_key: str = '', intro_en: str = '', layout: str = '') -> str:
    h2_text = self._s(i18n_key)
    if h2_text == i18n_key:
        h2_text = title
    intro_html = ''
    if intro_key:
        intro_text = self._s(intro_key)
        if intro_text == intro_key:
            intro_text = intro_en
        intro_html = f'<p class="section-intro">{intro_text}</p>'
    card_class = f'card {layout}'.strip() if layout else 'card'
    return (
        f'<section id="{id_}" class="{card_class}">'
        f'<h2>{h2_text}</h2>'
        f'{intro_html}{content}</section>'
    )
```

- [ ] **Step 3.6: 重構 mod10 section 為版型 C**

在 `html_exporter.py` 找到 mod10 的 section 建構（搜尋 `mod10` 或 `allowed_traffic`）。找到組裝 content 的地方，將 `chart_html` 和 `table_html` 包進版型 C 結構：

找到（大致）：
```python
content = chart_html + table_html
return self._section('allowed', 'rpt_tr_sec_allowed', 'Allowed Traffic', content, ...)
```

改為：
```python
content = (
    f'<div class="section-body">'
    f'{table_html}'
    f'{chart_html}'
    f'</div>'
)
return self._section('allowed', 'rpt_tr_sec_allowed', 'Allowed Traffic', content,
                     ..., layout='layout-c')
```

> 實作時先 `grep -n "rpt_tr_sec_allowed\|mod10\|allowed_traffic" src/report/exporters/html_exporter.py` 找到確切行號。

- [ ] **Step 3.7: 重構 mod02 section 為版型 B**

類似 Step 3.6，找 mod02 的 section 建構（搜尋 `rpt_tr_sec_policy\|mod02\|policy_decision`）。

將說明文字和 pie chart 包進 `section-top`，表格包進 `section-bottom`：

```python
content = (
    f'<div class="section-top">'
    f'<p class="section-intro">{intro_text}</p>'
    f'{chart_html}'
    f'</div>'
    f'<div class="section-bottom">{table_html}</div>'
)
return self._section('policy', 'rpt_tr_sec_policy', 'Policy Decisions', content,
                     layout='layout-b')
```

> 注意：mod02 若原本在 `_section()` 的 `intro_key` 參數傳入說明，需改為手動在 content 裡放 intro，不要透過 `_section` 的 `intro_key`。

- [ ] **Step 3.8: 執行測試**

```bash
python -m pytest tests/test_report_print_layout.py -v 2>&1 | tail -15
python -m pytest tests/ -q --ignore=tests/gui \
  --ignore=tests/test_api_client_label_cache_ttl.py \
  --ignore=tests/test_api_client_request_contract.py \
  --ignore=tests/test_api_client_retry_adapter.py \
  --ignore=tests/test_cron_schedule.py \
  --ignore=tests/test_transport_hec.py \
  2>&1 | tail -5
```

預期：print layout 測試全 PASS，無 regression。

- [ ] **Step 3.9: Commit**

```bash
git add src/report/exporters/html_exporter.py tests/test_report_print_layout.py
git commit -m "feat(html-exporter): cover page, layout B/C for mod02/mod10, data-report-title"
```

---

## Task 4：Audit Report (audit_html_exporter.py) 套用封面

**背景：** `AuditHtmlExporter.__init__` 已有 `date_range: tuple = ("", "")`，需加 `pce_url` 和 `org_name`。`_build()` 在 line ~159 組裝 HTML。封面頁加在 `<body>` 開頭，nav 之前。

**Files:**
- Modify: `src/report/exporters/audit_html_exporter.py`
- Modify: `src/report/audit_generator.py`（傳遞新參數）

- [ ] **Step 4.1: 擴充 AuditHtmlExporter.__init__**

找到 `__init__` 定義，在 `data_source: str = ""` 後加：

```python
def __init__(self, results: dict, df=None, date_range: tuple = ("", ""),
             data_source: str = "", profile: str = "security_risk",
             detail_level: str = _REPORT_DETAIL_LEVEL, lang: str = "en",
             pce_url: str = "", org_name: str = ""):
    ...
    self._pce_url = pce_url
    self._org_name = org_name
```

- [ ] **Step 4.2: 加封面頁到 _build()**

在 `audit_html_exporter.py` 的 `_build()` 方法裡，找到 `<body>` 組裝處，加入：

在 `_build()` 開頭（`_s` 定義後）加：
```python
from src.report.exporters.cover_page import build_cover_page as _build_cover  # 移到檔頭
_cover_title = _s("rpt_cover_type_audit")
cover_html = _build_cover(
    title=_cover_title,
    report_type=_cover_title,
    date_range=self._date_range,
    pce_url=self._pce_url,
    org_name=self._org_name,
    lang=self._lang,
)
```

找到：
```python
"<body>" + nav_html + ...
```
改為：
```python
f'<body data-report-title="{_cover_title}">' + cover_html + nav_html + ...
```

- [ ] **Step 4.3: 更新 audit_generator.py 傳遞新參數**

在 `src/report/audit_generator.py` 找到呼叫 `AuditHtmlExporter(...)` 的地方，加入 `pce_url` 和 `org_name`。

搜尋：`grep -n "AuditHtmlExporter" src/report/audit_generator.py`

找到呼叫後，在現有參數後加：
```python
pce_url=getattr(self, '_pce_url', '') or '',
org_name=getattr(self, '_org_name', '') or '',
```

> 注意：如果 `audit_generator.py` 的 class 有 `self._pce_url` 屬性（可能從 ConfigManager 取得），直接用；若無，先傳空字串，之後再補。

- [ ] **Step 4.4: 跑測試確認**

```bash
python -m pytest tests/ -q --ignore=tests/gui \
  --ignore=tests/test_api_client_label_cache_ttl.py \
  --ignore=tests/test_api_client_request_contract.py \
  --ignore=tests/test_api_client_retry_adapter.py \
  --ignore=tests/test_cron_schedule.py \
  --ignore=tests/test_transport_hec.py \
  2>&1 | tail -5
```

- [ ] **Step 4.5: Commit**

```bash
git add src/report/exporters/audit_html_exporter.py src/report/audit_generator.py
git commit -m "feat(audit): cover page and data-report-title"
```

---

## Task 5：Policy Usage Report (policy_usage_html_exporter.py) 套用封面

**背景：** 同 Task 4 的模式，`PolicyUsageHtmlExporter` 已有 `date_range`，需加 `pce_url`、`org_name`。

**Files:**
- Modify: `src/report/exporters/policy_usage_html_exporter.py`
- Modify: `src/report/policy_usage_generator.py`

- [ ] **Step 5.1: 擴充 PolicyUsageHtmlExporter.__init__**

找到 `__init__`，在 `lang: str = "en"` 後加：
```python
pce_url: str = "", org_name: str = ""):
    ...
    self._pce_url = pce_url
    self._org_name = org_name
```

- [ ] **Step 5.2: 加封面頁到 _build()**

與 Task 4 Step 4.2 相同模式，使用 `_s("rpt_cover_type_policy")` 當標題。

找到 `<body>` 組裝處加入 `cover_html` 和 `data-report-title`。

- [ ] **Step 5.3: 更新 policy_usage_generator.py**

`grep -n "PolicyUsageHtmlExporter" src/report/policy_usage_generator.py`

在呼叫處加 `pce_url=...`, `org_name=...`。

- [ ] **Step 5.4: 跑測試確認**

```bash
python -m pytest tests/ -q --ignore=tests/gui \
  --ignore=tests/test_api_client_label_cache_ttl.py \
  --ignore=tests/test_api_client_request_contract.py \
  --ignore=tests/test_api_client_retry_adapter.py \
  --ignore=tests/test_cron_schedule.py \
  --ignore=tests/test_transport_hec.py \
  2>&1 | tail -5
```

- [ ] **Step 5.5: Commit**

```bash
git add src/report/exporters/policy_usage_html_exporter.py src/report/policy_usage_generator.py
git commit -m "feat(policy-usage): cover page and data-report-title"
```

---

## Task 6：VEN Status Report 套用封面

**背景：** VEN Status 的 HTML 在 `src/report/ven_status_generator.py` 組裝（不是獨立 exporter 檔）。搜尋 `<!DOCTYPE html>` 找到 HTML 組裝函式。需找到 `<body>` 所在行，在前面加封面頁。

**Files:**
- Modify: `src/report/ven_status_generator.py`

- [ ] **Step 6.1: 找到 HTML 組裝位置**

```bash
grep -n "DOCTYPE\|<body\|pce_url\|org_name\|date_range" src/report/ven_status_generator.py | head -20
```

確認 `<body>` 的確切行號和 class/constructor 位置。

- [ ] **Step 6.2: 加封面頁**

找到 VEN Status HTML 組裝的 class（可能是 `VenHtmlExporter` 或類似）。

在 `__init__` 加入 `pce_url: str = "", org_name: str = ""` 參數（`date_range` 可能已存在或需加入）。

在 `<body>` 組裝處加：
```python
from src.report.exporters.cover_page import build_cover_page as _build_cover

cover_html = _build_cover(
    title=_s("rpt_cover_type_ven"),
    report_type=_s("rpt_cover_type_ven"),
    date_range=getattr(self, '_date_range', ("", "")),
    pce_url=getattr(self, '_pce_url', ""),
    org_name=getattr(self, '_org_name', ""),
    lang=self._lang,
)
```

將 `"<body>"` 改為 `f'<body data-report-title="{_s("rpt_cover_type_ven")}">'`，並在 `<body>` 後插入 `cover_html`。

- [ ] **Step 6.3: 跑全部測試**

```bash
python -m pytest tests/ -q --ignore=tests/gui \
  --ignore=tests/test_api_client_label_cache_ttl.py \
  --ignore=tests/test_api_client_request_contract.py \
  --ignore=tests/test_api_client_retry_adapter.py \
  --ignore=tests/test_cron_schedule.py \
  --ignore=tests/test_transport_hec.py \
  2>&1 | tail -5
```

預期：全部通過，無 regression。

- [ ] **Step 6.4: Commit**

```bash
git add src/report/ven_status_generator.py
git commit -m "feat(ven-status): cover page and data-report-title"
```

---

## Task 7：人工驗證（測試機）

**背景：** CSS `@page counter(pages)` 和 `max-height: 185px` 在瀏覽器列印預覽中才能驗證，自動測試無法覆蓋。

**Files:** 無異動

- [ ] **Step 7.1: 在測試機產生各報告**

```bash
ssh root@172.16.15.106
cd /root/illumio-ops
git pull origin feat/e2e-playwright-gui-tests
source venv/bin/activate
# 用 GUI 或 CLI 各產一份報告（Traffic、Audit、Policy Usage、VEN Status）
```

- [ ] **Step 7.2: 在瀏覽器驗證列印預覽**

開啟各報告 HTML，按 `Ctrl+P` 確認：
- [ ] 第 1 頁為封面（深色漸層背景）
- [ ] 封面顯示報告標題、PCE 位址（若有設定）、生成時間
- [ ] 第 2 頁起每頁右下角有頁碼（`1 / N`）
- [ ] 長表格（> 1 頁）每頁重複表頭
- [ ] 表格不在行中間截斷
- [ ] VEN Status 8 欄表格字體縮小至 8pt，未超出頁寬
- [ ] mod10 section：port 表格與 bar chart 左右並排
- [ ] 圖表不超過 ¼ 頁高

- [ ] **Step 7.3: Commit（若有微調）**

若驗證中發現需微調 CSS 數值（如 `max-height`、padding），直接修改 `report_css.py` 並：
```bash
git add src/report/exporters/report_css.py
git commit -m "fix(css): print layout visual adjustments from browser verification"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] 表格不截斷（`thead` + `tr page-break-inside: avoid`）→ Task 1
- [x] 寬表格 8pt → Task 1
- [x] 版型 B（說明+圖表並排）→ Task 1 CSS + Task 3 mod02
- [x] 版型 C（表格+圖表並排）→ Task 1 CSS + Task 3 mod10
- [x] 封面頁 helper → Task 2
- [x] i18n keys → Task 2
- [x] 封面套用到 4 個報告 → Task 3–6
- [x] 頁碼 `@page counter` → Task 1
- [x] `data-report-title` → Task 3–6
- [x] 人工驗證 → Task 7

**Placeholder scan:** 無 TBD/TODO。Step 3.6 和 3.7 有「大致」說明，但提供了 `grep` 指令讓執行者自行確認行號。

**Type consistency:**
- `build_cover_page()` 在 Task 2 定義，Task 3–6 呼叫，參數名稱一致。
- `layout` 參數在 Task 3 加入 `_section()`，Tasks 3.6/3.7 使用 `layout='layout-b'`/`'layout-c'`，與 CSS class 名稱一致。
