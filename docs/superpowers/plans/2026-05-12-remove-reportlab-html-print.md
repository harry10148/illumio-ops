# Remove ReportLab + HTML Print CSS + Fix mod10 Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 ReportLab PDF 二進位產出，改以 `@media print` CSS 讓 HTML 報告可直接列印為 PDF，同時修正 mod10 圖表類型錯誤。

**Architecture:** `fmt='pdf'` 改為等同 `fmt='html'`（輸出 print-ready HTML）；`@media print` CSS 擴充至涵蓋分頁、色彩、隱藏互動元素；ReportLab 依賴完全移除。HTML 加入 Print 按鈕讓使用者一鍵進入列印對話框。

**Tech Stack:** Python 3.12, HTML/CSS (`@media print`), Plotly (HTML 圖表), pytest

---

## 檔案異動清單

| 操作 | 路徑 | 說明 |
|------|------|------|
| Modify | `src/report/analysis/mod10_allowed_traffic.py` | chart type `line→bar`、資料鍵 `x/y→labels/values`、標題修正 |
| Modify | `src/report/exporters/report_css.py` | 擴充 `@media print` block、加 `.print-btn` 樣式 |
| Modify | `src/report/exporters/html_exporter.py` | nav 裡加 Print 按鈕 |
| Modify | `src/report/report_generator.py` | `fmt='pdf'` → HTML；移除 PDF export block |
| Modify | `src/report/ven_status_generator.py` | 同上 |
| Modify | `src/report/policy_usage_generator.py` | 同上 |
| Modify | `src/report/audit_generator.py` | 同上 |
| Modify | `requirements.txt` | 移除 `reportlab>=4.0,<5.0` |
| Modify | `requirements-offline.txt` | 移除 `reportlab>=4.0,<5.0` |
| Delete | `src/report/exporters/pdf_exporter.py` | 整個刪除 |
| Modify | `src/report/exporters/report_i18n.py` | 加 `rpt_chart_top_allowed_ports` 至 STRINGS |
| Modify | `src/i18n_en.json` | 更新 `rpt_chart_allowed_traffic_timeline` 鍵值 |
| Modify | `src/i18n_zh_TW.json` | 同上 |

---

## Task 1：修正 mod10 圖表類型與標題

**問題：** `mod10_allowed_traffic.py` 的 `chart_spec` 用 `type: "line"` 顯示 Port 排名，
同時資料鍵是 `data.x` / `data.y`（line chart 格式），但 bar chart 需要 `data.labels` / `data.values`。
標題 "Allowed Traffic Timeline" 誤導讀者以為是時間序列圖。

**Files:**
- Modify: `src/report/analysis/mod10_allowed_traffic.py`（最後 `return` block）
- Modify: `src/report/exporters/report_i18n.py`（STRINGS dict）
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`
- Test: `tests/report/test_mod10_allowed_traffic.py`

- [ ] **Step 1.1: 寫失敗測試**

```python
# tests/report/test_mod10_allowed_traffic.py
import pandas as pd
import pytest
from src.report.analysis.mod10_allowed_traffic import allowed_traffic

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'policy_decision': ['allowed'] * 5,
        'src_app': ['app_a'] * 5,
        'dst_app': ['app_b'] * 5,
        'port': [80, 443, 53, 80, 443],
        'num_connections': [100, 200, 50, 150, 250],
        'src_managed': [True] * 5,
    })

def test_chart_type_is_bar(sample_df):
    result = allowed_traffic(sample_df, top_n=10)
    assert result['chart_spec']['type'] == 'bar'

def test_chart_data_uses_labels_values_keys(sample_df):
    result = allowed_traffic(sample_df, top_n=10)
    data = result['chart_spec']['data']
    assert 'labels' in data
    assert 'values' in data
    assert 'x' not in data
    assert 'y' not in data

def test_chart_title_key_is_top_allowed_ports(sample_df):
    result = allowed_traffic(sample_df, top_n=10)
    assert result['chart_spec']['title_key'] == 'rpt_chart_top_allowed_ports'
```

- [ ] **Step 1.2: 執行確認失敗**

```bash
cd /home/harry/rd/illumio-ops
python -m pytest tests/report/test_mod10_allowed_traffic.py -v 2>&1 | tail -20
```

預期：3 個 FAIL。

- [ ] **Step 1.3: 修改 mod10 chart_spec**

在 `src/report/analysis/mod10_allowed_traffic.py` 找到最後的 `return {` block，將 `chart_spec` 改為：

```python
    return {
        'total_allowed': len(allowed),
        'top_app_flows': top_app_flows,
        'audit_flags': audit_table,
        'audit_flag_count': len(audit_flags),
        'top_allowed_ports': top_ports,
        'chart_spec': {
            'type': 'bar',
            'title': 'Top Allowed Ports',
            'title_key': 'rpt_chart_top_allowed_ports',
            'x_label': 'Port',
            'x_label_key': 'rpt_chart_axis_port',
            'y_label': 'Connections',
            'y_label_key': 'rpt_chart_axis_connections',
            'data': {
                'labels': port_labels,
                'values': port_values,
            },
            'i18n': {'lang': get_language()},
        },
    }
```

- [ ] **Step 1.4: 加 i18n key 到 report_i18n.py**

在 `src/report/exporters/report_i18n.py` 找到 `STRINGS` dict，在其中加入（找一個合適的位置，例如其他 `rpt_chart_` 附近，若無則加在 dict 末尾之前）：

```python
    "rpt_chart_top_allowed_ports": {"en": "Top Allowed Ports", "zh_TW": "Top Allowed Ports"},
```

- [ ] **Step 1.5: 更新 i18n_en.json 和 i18n_zh_TW.json**

在 `src/i18n_en.json` 找到 `"rpt_chart_allowed_traffic_timeline"` 並改鍵名：

```json
"rpt_chart_top_allowed_ports": "Top Allowed Ports",
```

在 `src/i18n_zh_TW.json` 找到同一鍵（若存在）並同步更新：

```json
"rpt_chart_top_allowed_ports": "Top Allowed Ports",
```

> 注意：舊鍵 `rpt_chart_allowed_traffic_timeline` 可同時保留（不刪），避免影響其他可能參照它的地方。只需新增新鍵。

- [ ] **Step 1.6: 執行確認通過**

```bash
python -m pytest tests/report/test_mod10_allowed_traffic.py -v 2>&1 | tail -10
```

預期：3 個 PASS。

- [ ] **Step 1.7: Commit**

```bash
git add src/report/analysis/mod10_allowed_traffic.py \
        src/report/exporters/report_i18n.py \
        src/i18n_en.json src/i18n_zh_TW.json \
        tests/report/test_mod10_allowed_traffic.py
git commit -m "fix(mod10): bar chart for top allowed ports, fix misleading timeline title"
```

---

## Task 2：擴充 @media print CSS + 加 Print 按鈕

**背景：** `report_css.py` 的 `@media print` block（約 line 252）已有基本隱藏 nav 和 margin reset，但缺少：分頁符號、色彩保留指令、Print 按鈕樣式。`html_exporter.py` 的 nav 也需要加 Print 按鈕。

**Files:**
- Modify: `src/report/exporters/report_css.py`（`@media print` block）
- Modify: `src/report/exporters/html_exporter.py`（nav_html 組成處）

- [ ] **Step 2.1: 擴充 report_css.py 的 @media print block**

找到現有的 `@media print {` block（line ~252），將整個 block 替換為：

```python
  @media print {
    nav { display: none; }
    .print-btn { display: none; }
    main { margin-left: 0; padding: 12px; }
    body { font-size: 10pt; }
    * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
    .card { box-shadow: none; border: 1px solid var(--slate-20); page-break-inside: avoid; }
    .report-table-panel { box-shadow: none; }
    .report-table-panel--wide::after { display: none; }
    .report-table-panel--wide .report-table thead th:first-child,
    .report-table-panel--wide .report-table tbody td:first-child { position: static; box-shadow: none; }
    section { page-break-before: always; }
    section#summary { page-break-before: avoid; }
    .chart-container { page-break-inside: avoid; }
    .finding-card { page-break-inside: avoid; }
    footer { page-break-before: avoid; }
  }
```

同時，在 `BASE_CSS` 或適當位置（非 print block 內）加入 `.print-btn` 的一般樣式：

在現有 `nav a` 規則附近加入：

```css
  .print-btn { display: block; margin: 12px 16px 0; padding: 7px 16px; background: var(--orange); color: #fff; border: none; border-radius: 4px; font-size: 12px; cursor: pointer; text-align: center; width: calc(100% - 32px); }
  .print-btn:hover { background: var(--orange-dark, #cc4400); }
```

- [ ] **Step 2.2: 在 html_exporter.py nav 中加 Print 按鈕**

找到 `html_exporter.py` 中組成 `nav_html` 的地方（約 line 541–578），在 `nav_html` 的結束 `</nav>` 之前插入 Print 按鈕。

找到：
```python
        nav_html = '<nav>' + ''.join(_nav_links) + '</nav>'
```

改為：
```python
        nav_html = '<nav>' + ''.join(_nav_links) + '<button class="print-btn" onclick="window.print()">🖨 Print / PDF</button></nav>'
```

> 注意：這行在兩個 if/else 分支裡都出現（profile == 'security_risk' 和 else），兩處都要改。用 `replace_all=True` 的 Edit 一次處理。

- [ ] **Step 2.3: 人工驗證**

```bash
# 從測試機複製最新 HTML 報告到本機
scp root@172.16.15.106:/root/illumio-ops/reports/Illumio_Traffic_Report_SecurityRisk_2026-05-11_1557.html /tmp/test_print.html
```

用瀏覽器開啟 `/tmp/test_print.html`，確認：
- Print 按鈕出現在 nav 底部
- 按下 Print（或 Ctrl+P）後列印預覽正確：nav 不見、各 section 分頁、圖表有色彩

- [ ] **Step 2.4: Commit**

```bash
git add src/report/exporters/report_css.py src/report/exporters/html_exporter.py
git commit -m "feat(html): expand @media print CSS and add Print button to nav"
```

---

## Task 3：移除 4 個 Generator 的 PDF export block

**背景：** 4 個 generator 都有 `if fmt in ('pdf', 'all'):` block 呼叫 `export_report_pdf`。要改成：
1. 移除整個 pdf block
2. 將 `'pdf'` 加入 HTML export 的條件，讓 `fmt='pdf'` 輸出 HTML

**Files:**
- Modify: `src/report/report_generator.py`（HTML block line ~344，PDF block line ~357）
- Modify: `src/report/ven_status_generator.py`（PDF block line ~84）
- Modify: `src/report/policy_usage_generator.py`（PDF block line ~260）
- Modify: `src/report/audit_generator.py`（PDF block line ~702）

- [ ] **Step 3.1: 修改 report_generator.py**

找到：
```python
        if fmt in ('html', 'all'):
```
改為：
```python
        if fmt in ('html', 'pdf', 'all'):
```

然後找到並**完整刪除**以下 block（約 lines 357–379）：
```python
        if fmt in ('pdf', 'all'):
            try:
                from src.report.exporters.pdf_exporter import export_report_pdf
                ...
                self.last_export_errors['pdf'] = str(exc) or exc.__class__.__name__
```

- [ ] **Step 3.2: 修改 ven_status_generator.py**

同 Step 3.1 的模式：
1. 找 `if fmt in ('html', 'all'):` → 改為 `if fmt in ('html', 'pdf', 'all'):`
2. 刪除 `if fmt in ('pdf', 'all'):` block（lines ~84–103）

- [ ] **Step 3.3: 修改 policy_usage_generator.py**

同上模式：
1. 找 `if fmt in ('html', 'all'):` → 加入 `'pdf'`
2. 刪除 `if fmt in ('pdf', 'all'):` block（lines ~260–280）

- [ ] **Step 3.4: 修改 audit_generator.py**

同上模式：
1. 找 `if fmt in ('html', 'all'):` → 加入 `'pdf'`
2. 刪除 `if fmt in ('pdf', 'all'):` block（lines ~702–725）

- [ ] **Step 3.5: 驗證 import 沒有殘留**

```bash
grep -rn 'pdf_exporter\|export_report_pdf\|reportlab' \
  src/report/report_generator.py \
  src/report/ven_status_generator.py \
  src/report/policy_usage_generator.py \
  src/report/audit_generator.py
```

預期：無任何輸出。

- [ ] **Step 3.6: 跑既有測試確認沒有 regression**

```bash
python -m pytest tests/ -x -q --ignore=tests/gui 2>&1 | tail -20
```

預期：全部通過（或只有原本就 skip 的）。

- [ ] **Step 3.7: Commit**

```bash
git add src/report/report_generator.py \
        src/report/ven_status_generator.py \
        src/report/policy_usage_generator.py \
        src/report/audit_generator.py
git commit -m "feat(report): fmt=pdf now outputs print-ready HTML, remove ReportLab PDF generation"
```

---

## Task 4：移除 ReportLab 依賴

**Files:**
- Delete: `src/report/exporters/pdf_exporter.py`
- Modify: `requirements.txt`（line 46）
- Modify: `requirements-offline.txt`（line 47）

- [ ] **Step 4.1: 確認 pdf_exporter.py 無其他使用者**

```bash
grep -rn 'pdf_exporter' src/ tests/ --include='*.py' | grep -v '__pycache__'
```

預期：零結果（Task 3 完成後應已清空）。

- [ ] **Step 4.2: 刪除 pdf_exporter.py**

```bash
git rm src/report/exporters/pdf_exporter.py
```

- [ ] **Step 4.3: 移除 requirements.txt 中的 reportlab**

找到 `requirements.txt` 第 46 行：
```
reportlab>=4.0,<5.0
```
刪除該行。

- [ ] **Step 4.4: 移除 requirements-offline.txt 中的 reportlab**

找到 `requirements-offline.txt` 第 47 行：
```
reportlab>=4.0,<5.0
```
刪除該行。

- [ ] **Step 4.5: 確認 reportlab 無殘留引用**

```bash
grep -rn 'reportlab\|pdf_exporter' src/ tests/ requirements*.txt --include='*.py' --include='*.txt' | grep -v '__pycache__'
```

預期：零結果。

- [ ] **Step 4.6: 跑全部測試**

```bash
python -m pytest tests/ -x -q --ignore=tests/gui 2>&1 | tail -20
```

預期：全部通過。

- [ ] **Step 4.7: Commit**

```bash
git add requirements.txt requirements-offline.txt
git commit -m "chore: remove reportlab dependency, delete pdf_exporter.py"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] HTML 加 `@media print` CSS → Task 2
- [x] 加 Print 按鈕 → Task 2
- [x] 移除 ReportLab → Task 4
- [x] `fmt='pdf'` 輸出 HTML → Task 3
- [x] mod10 chart type 修正 → Task 1
- [x] mod10 標題修正 → Task 1

**Placeholder scan:** 無 TBD / TODO / placeholder。

**Type consistency:**
- `port_labels` / `port_values` 在 Task 1 定義，chart_spec 中的 `labels` / `values` 鍵與 `chart_renderer.py` 的 `data.get("labels", [])` / `data.get("values", [])` 一致。
- `rpt_chart_top_allowed_ports` 在 Task 1.4（STRINGS）和 Task 1.3（chart_spec title_key）一致。
