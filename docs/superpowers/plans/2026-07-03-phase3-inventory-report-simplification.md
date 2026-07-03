# Phase 3：Inventory 盤點報表精簡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 spec C 節聚焦 Inventory 報表於「資產與標籤治理」：移除三個流量章、跨 Label 矩陣只留 ENV/APP（ROLE/LOC 下放 XLSX）、Unmanaged 章 6 表併 3、修日期範圍 N/A→N/A 與變更影響章（含其實際上永遠不渲染 delta 的接線 bug）。

**Architecture:** 三章移除為 render-only（mod01/09/11 模組續跑——mod12 KPI、dashboard 快照、趨勢快照都直接讀模組結果）；矩陣與 unmanaged 的分析端資料 key 全保留、只動渲染與新增合併 builder；變更影響修根因（KPI 來源接錯 + 方向名單過期）並抽共用 helper 讓快照寫入端與渲染端單一事實來源。

**Tech Stack:** Python 3 / pandas / pytest；i18n 雙層（同 Phase 2）。

**Spec:** `docs/superpowers/specs/2026-07-02-traffic-security-report-split-design.md` C 節全部 4 項。

## Global Constraints

- 註解一律繁體中文、無 emoji；commit message 英文 conventional-commits；每 task 一個 commit；surgical。
- 每個行為變更先寫 RED 測試（TDD）。
- **subagent 環境釘選**：開工與 commit 前驗證 `pwd` 為 worktree、`git branch --show-current` 為預期分支；controller 收 SHA 後以 `git branch --contains` 驗證。
- i18n 雙層：`self._s()` 走 report_i18n `STRINGS`（runtime overlay，實體在兩個 json）；`t()` 走 `src/i18n_en.json`/`src/i18n_zh_TW.json`。刪 key 前 grep src/ tests/ 歸零；json 檔尾單一 newline。
- **security_risk 與 traffic 兩 profile 輸出不得改變**（Phase 2 已交付上線）。traffic 的 `_mod08_html` 有獨立覆寫（html_exporter.py:1722）、security 不含 unmanaged/matrix/change_impact 章——各 task 以測試鎖定。
- **分析模組回傳 key 一律不刪**；mod08 的 `unique_unmanaged_src`/`top_unmanaged_src` 為 dashboard 快照相依（report_generator.py:123-124）、`unique_unmanaged_src` 為 mod12 key_finding 相依（mod12_executive_summary.py:243）。
- 定位以程式碼內容為準，行號會漂移。
- 產報表交付前用實際樣本跑完整輸出逐頁檢查（專案 CLAUDE.md 規則；Task 6 落實）。

## 現況地圖（實作者速查）

| 對象 | 位置 |
|---|---|
| inventory 章節清單 | `NetworkInventoryHtmlExporter._ordered_section_keys()` html_exporter.py:1640-1642：`['summary','overview','labels','policy','matrix','unmanaged','distribution','bandwidth','ringfence','change_impact']` |
| mod07 | `src/report/analysis/mod07_cross_label_matrix.py`（`LABEL_KEYS=('env','app','role','loc')` :6；回傳 `{'matrices': {dim: {'same_value_flows','cross_value_flows','matrix','top_cross_pairs'} 或 {'note':...}}, 'chart_spec'}` :89）；渲染 `_mod07_html` html_exporter.py:1037-1050（無條件遍歷全維度） |
| mod08 | `src/report/analysis/mod08_unmanaged_hosts.py`（6 表：top_unmanaged_src :23-33、top_unmanaged_dst :36-42（exporter 未渲染）、managed_hosts_targeted_by_unmanaged :45-54、per_dst_app :57、per_port_proto :60、src_port_detail :63）；基底 `_mod08_html` html_exporter.py:1052-1078 現渲染 5 表 |
| mod01 date_range | `src/report/analysis/mod01_traffic_overview.py:67-69`（naive min/max + "N/A → N/A"）；同檔 `_safe_parse_min/_safe_parse_max` :10-23 已存在（coerce 容錯）但生產路徑未用 |
| change impact | 渲染 `_mod_change_impact_html` html_exporter.py:1568-1608（:1573 讀 `mod12['kpis']` 是 list → 恆走 no_kpi note，delta 表為死路）；快照 KPI dict 組裝 report_generator.py:629-636（posture 頂層 key）；`compare()` mod_change_impact.py:10-37（自動跳過非數值）；`_direction` 名單 :6-7 與快照 key 全對不上（恆 neutral） |
| XLSX 下放模式 | report_generator.py:1028-1045（Phase 2 lateral：空列 + `t(標題key)` 列 + 欄名列 + 資料列）；sheet 順序 :953-1064，`wb.save` :1066 |
| 測試錨點 | tests/test_traffic_report_split.py:41,43（inventory 斷言 `id="distribution"`/`id="overview"` 存在——Task 1 需更新）；tests/test_traffic_profile_split.py:36-43（matrix 錨點）；tests/test_traffic_flows_html_exporter.py:70（traffic unmanaged 錨點，不可破） |

---

### Task 1: Inventory 移除流量三章（spec C1）

**Files:**
- Modify: `src/report/exporters/html_exporter.py`（`NetworkInventoryHtmlExporter._ordered_section_keys`）
- Modify: `tests/test_traffic_report_split.py`
- Test: `tests/test_inventory_sections_trim.py`（新檔）

**Interfaces:**
- Consumes: 現行章節清單（現況地圖）。mod01/mod09/mod11 模組續跑（registry `_TRAFFIC_TOO` 標記不動）——mod12 KPI、`_build_snapshot`、趨勢快照、XLSX 泛用 sheet 都直接讀模組結果，與渲染無關（盤點已逐一確認）。
- Produces: inventory 章節清單變為 `['summary','labels','policy','matrix','unmanaged','ringfence','change_impact']`。

- [ ] **Step 1: RED 測試**

`tests/test_inventory_sections_trim.py`：
```python
"""Inventory 報表移除流量三章（spec C1）：overview/distribution/bandwidth。"""
from src.report.exporters.html_exporter import (
    NetworkInventoryHtmlExporter, SecurityRiskHtmlExporter,
)


def _results():
    return {
        "mod12": {"kpis": [], "key_findings": []},
        "mod01": {"total_flows": 10, "date_range": "2026-01-01 → 2026-01-02"},
        "mod09": {"label_distribution": {}},
        "mod11": {"bytes_data_available": False},
        "findings": [],
    }


def test_inventory_drops_traffic_chapters():
    html = NetworkInventoryHtmlExporter(_results(), lang="en").build()
    for anchor in ('id="overview"', 'id="distribution"', 'id="bandwidth"'):
        assert anchor not in html, f"{anchor} 應已自 inventory 移除"
    for anchor in ('id="labels"', 'id="policy"', 'id="unmanaged"'):
        assert anchor in html


def test_security_keeps_overview():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    assert 'id="overview"' in html
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_inventory_sections_trim.py -v`
Expected: `test_inventory_drops_traffic_chapters` FAIL（三錨點目前都在）。

- [ ] **Step 3: 實作（GREEN）**

`NetworkInventoryHtmlExporter._ordered_section_keys()` 改為：
```python
    def _ordered_section_keys(self) -> list[str]:
        # spec C1：流量總覽/流量分布/頻寬歸 Traffic 報表，inventory 聚焦資產與標籤治理
        return ['summary', 'labels', 'policy', 'matrix', 'unmanaged',
                'ringfence', 'change_impact']
```
nav 條目由清單自動決定（html_exporter.py:605），`_nav_spec`/`_sec` dict 條目保留（security/traffic 仍用）。

- [ ] **Step 4: 更新既有錨點測試**

`tests/test_traffic_report_split.py` 的 `test_inventory_omits_maturity_and_readiness`（:34-43）：`assert 'id="distribution"' in html`（:41）與 `assert 'id="overview"' in html`（:43 前半）改為斷言不存在；`id="policy"` 斷言保留。保留測試原意（inventory 無 maturity/readiness）不動。

- [ ] **Step 5: 全套綠燈**

Run: `python -m pytest tests/test_inventory_sections_trim.py tests/test_traffic_report_split.py tests/test_traffic_profile_split.py -v && python -m pytest -q`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(report): drop traffic chapters from inventory profile"
```

---

### Task 2: 跨 Label 矩陣只留 ENV/APP，ROLE/LOC 下放 XLSX（spec C2）

**Files:**
- Modify: `src/report/exporters/html_exporter.py`（`_mod07_html`）
- Modify: `src/report/report_generator.py`（`generate_traffic_xlsx` 新 sheet）
- Modify: 兩 json（新 2 key）
- Test: `tests/test_mod07_matrix_trim.py`（新檔）、`tests/test_xlsx_content_traffic.py`（增斷言）

**Interfaces:**
- Consumes: mod07 回傳結構（現況地圖）；模組與 `matrices` key 全部不動。
- Produces: HTML 只渲染 env/app 兩維度；XLSX 新 sheet `rpt_xlsx_sheet_cross_label` 含 role/loc 的 top_cross_pairs。

- [ ] **Step 1: RED 測試**

`tests/test_mod07_matrix_trim.py`：
```python
"""跨 Label 矩陣 HTML 只留 ENV/APP（spec C2）。"""
import pandas as pd
from src.report.exporters.html_exporter import NetworkInventoryHtmlExporter


def _mod07():
    def _dim(n):
        return {"same_value_flows": n, "cross_value_flows": n + 1,
                "matrix": pd.DataFrame([{"a": 1}]),
                "top_cross_pairs": pd.DataFrame([{"Src X": "a", "Dst X": "b", "Connections": n}])}
    return {"matrices": {"env": _dim(1), "app": _dim(2), "role": _dim(3), "loc": _dim(4)}}


def _html():
    results = {"mod07": _mod07(), "mod12": {"kpis": [], "key_findings": []}, "findings": []}
    return NetworkInventoryHtmlExporter(results, lang="en").build()


def test_only_env_app_rendered():
    html = _html()
    assert "ENV" in html and "APP" in html
    assert "ROLE" not in html
    # 注意 LOC 三字母可能出現於其他詞——用維度標題的完整片段斷言
    assert "Label Key: LOC" not in html and "LOC</h3>" not in html


def test_xlsx_demotion_note_present():
    html = _html()
    from src.report.exporters.report_i18n import STRINGS
    assert STRINGS["rpt_tr_matrix_xlsx_note"]["en"] in html
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_mod07_matrix_trim.py -v`
Expected: 兩測試 FAIL。

- [ ] **Step 3: `_mod07_html` 改寫（GREEN 前半）**

現行方法（html_exporter.py:1037-1050）把 `for key, data in m.get('matrices', {}).items()` 改為固定兩維度，其餘結構照舊：
```python
    def _mod07_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod07', {})
        out = _render_chart_for_html(m.get('chart_spec'), lang=self._lang)
        # spec C2：HTML 只呈現 ENV/APP 兩維；ROLE/LOC 明細下放 XLSX
        for key in ('env', 'app'):
            data = m.get('matrices', {}).get(key)
            if not data:
                continue
            out += f'<h3>{_s("rpt_tr_label_key")} {key.upper()}</h3>'
            if 'note' in data:
                out += f'<p class="note">{data["note"]}</p>'
                continue
            out += (f'<p>{_s("rpt_tr_same_value")} <b>{data.get("same_value_flows", 0)}</b> · '
                    f'{_s("rpt_tr_cross_value")} <b>{data.get("cross_value_flows", 0)}</b></p>')
            out += _df_to_html(data.get('top_cross_pairs'), lang=_lang)
        out += self._subnote('rpt_tr_matrix_xlsx_note')
        return out or f'<p class="note">{_s("rpt_no_matrix")}</p>'
```
（以現行方法實文為準改寫——若現行渲染還有其他元素（如每維度的 note/fallback 寫法不同），保留原寫法、只改遍歷集合與加 subnote。）

- [ ] **Step 4: XLSX 新 sheet（GREEN 後半）**

`generate_traffic_xlsx()`（report_generator.py）在 Top Talkers sheet 段之後、`wb.save` 之前插入（沿用 Phase 2 lateral 下放模式）：
```python
    # --- Cross-Label Matrix（role/loc 自 HTML 下放；spec C2）---
    ws = wb.create_sheet(t("rpt_xlsx_sheet_cross_label", lang=lang))
    try:
        from src.report.analysis.mod07_cross_label_matrix import cross_label_flow_matrix
        m07 = cross_label_flow_matrix(flows, top_n=top_n)
        _wrote_any_m07 = False
        for _dim in ('role', 'loc'):
            _data = (m07.get('matrices') or {}).get(_dim) or {}
            _tbl = _data.get('top_cross_pairs')
            if _tbl is None or not hasattr(_tbl, 'empty') or _tbl.empty:
                continue
            ws.append([])
            ws.append([f"{t('rpt_tr_label_key', lang=lang)} {_dim.upper()}"])
            ws.append([str(c) for c in _tbl.columns])
            for _, _row in _tbl.iterrows():
                ws.append([str(v) for v in _row])
            _wrote_any_m07 = True
        if not _wrote_any_m07:
            ws.append([t("rpt_xlsx_col_note", lang=lang), t("rpt_no_matrix", lang=lang)])
    except Exception:
        ws.append([t("rpt_xlsx_col_note", lang=lang), t("rpt_no_matrix", lang=lang)])
```
i18n 新 key（兩 json）：
- `rpt_xlsx_sheet_cross_label`: en "Cross-Label Matrix" / zh "跨 Label 矩陣"
- `rpt_tr_matrix_xlsx_note`: en "ROLE and LOC dimension detail has moved to the XLSX export." / zh "ROLE 與 LOC 維度明細已移至 XLSX 匯出。"
確認 `rpt_tr_label_key`、`rpt_no_matrix` 在 json 可被 `t()` 解析（盤點：i18n_en.json:3570/3265 已在）。
`tests/test_xlsx_content_traffic.py` 增測試：monkeypatch `cross_label_flow_matrix`（比照該檔 lateral 測試模式）回傳含 role/loc top_cross_pairs 的 dict，斷言新 sheet 存在且含 role 表內容。

- [ ] **Step 5: 全套綠燈**

Run: `python -m pytest tests/test_mod07_matrix_trim.py tests/test_xlsx_content_traffic.py tests/test_traffic_profile_split.py -v && python -m pytest -q`
Expected: 全 PASS（test_traffic_profile_split 的 matrix 錨點斷言不受影響——章仍在，只是維度變少）。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(report): matrix chapter keeps env/app dims, demote role/loc to xlsx"
```

---

### Task 3: Unmanaged 章 6 表併 3（spec C3）

設計：三張目標表 = ①來源排行 `top_unmanaged_src`（原樣）②目標 App `per_dst_app`（原樣）③暴露 port 合併版 `exposed_ports_merged`（新 builder：`per_port_proto` 全欄 + `Top Unmanaged Sources` 欄，吸收 `src_port_detail` 的來源×port 資訊）。`managed_hosts_targeted_by_unmanaged`（IP 粒度，與 per_dst_app 重疊）與 `src_port_detail` 停止渲染；`top_unmanaged_dst` 本來就沒渲染。**模組回傳 key 全部保留**（快照/mod12 相依）。基底 `_mod08_html` 只有 inventory 消費（security 無此章、traffic 有覆寫）——不需 profile 守門。

**Files:**
- Modify: `src/report/analysis/mod08_unmanaged_hosts.py`（新 builder + 回傳 key）
- Modify: `src/report/exporters/html_exporter.py`（基底 `_mod08_html`）
- Modify: 兩 json + `report_i18n.py` 欄位翻譯（若有 per-column 翻譯表）
- Test: `tests/test_mod08_merge.py`（新檔）

**Interfaces:**
- Produces: mod08 回傳新增 `'exposed_ports_merged': pd.DataFrame`（欄位 = per_port_proto 全欄 + `'Top Unmanaged Sources'` str 欄：最多 3 個 IP 逗號分隔、溢出 ` +N`、NaN src_ip 顯示 `(unknown)`）。

- [ ] **Step 1: RED 測試**

`tests/test_mod08_merge.py`：
```python
"""Unmanaged 章 6 表併 3（spec C3）：exposed_ports_merged builder 與渲染。"""
import pandas as pd
from src.report.analysis.mod08_unmanaged_hosts import unmanaged_traffic
from src.report.exporters.html_exporter import NetworkInventoryHtmlExporter


def _df():
    rows = []
    for i, (src, conns) in enumerate([("10.9.0.1", 30), ("10.9.0.2", 20), ("10.9.0.3", 10), ("10.9.0.4", 5)]):
        rows.append({"src_ip": src, "dst_ip": f"10.1.0.{i}", "port": 445, "proto": "TCP",
                     "src_app": "", "dst_app": "fileserver", "policy_decision": "allowed",
                     "src_managed": False, "dst_managed": True,
                     "num_connections": conns, "bytes_total": 1000, "dst_hostname": f"h{i}"})
    # 一筆 managed 流量作對照
    rows.append({"src_ip": "10.0.0.1", "dst_ip": "10.1.0.9", "port": 443, "proto": "TCP",
                 "src_app": "web", "dst_app": "api", "policy_decision": "allowed",
                 "src_managed": True, "dst_managed": True,
                 "num_connections": 9, "bytes_total": 500, "dst_hostname": "h9"})
    return pd.DataFrame(rows)


def test_exposed_ports_merged_shape():
    out = unmanaged_traffic(_df())
    merged = out["exposed_ports_merged"]
    assert not merged.empty
    row = merged[merged["Port"] == 445].iloc[0]
    # top 3 + 溢出標記
    assert row["Top Unmanaged Sources"] == "10.9.0.1, 10.9.0.2, 10.9.0.3 +1"
    # 原 6 key 照舊保留
    for k in ("top_unmanaged_src", "top_unmanaged_dst", "managed_hosts_targeted_by_unmanaged",
              "per_dst_app", "per_port_proto", "src_port_detail"):
        assert k in out


def test_inventory_renders_three_tables():
    results = {"mod08": unmanaged_traffic(_df()), "mod12": {"kpis": [], "key_findings": []}, "findings": []}
    html = NetworkInventoryHtmlExporter(results, lang="en").build()
    from src.report.exporters.report_i18n import STRINGS
    assert STRINGS["rpt_tr_top_unmanaged"]["en"] in html
    assert STRINGS["rpt_tr_managed_apps_unmanaged"]["en"] in html
    assert STRINGS["rpt_tr_exposed_ports_merged"]["en"] in html
    # 停止渲染的兩表標題消失
    for gone in ("rpt_tr_unmanaged_src_port", "rpt_tr_managed_targeted", "rpt_tr_exposed_ports_proto"):
        # key 可能已刪——直接以舊英文標題文字斷言不在
        pass  # 見 Step 3 註：以刪除前的英文標題字面值填入斷言
```
（`test_inventory_renders_three_tables` 最後的斷言：實作前先 `git grep` 三個舊 key 的 en 值，把字面值寫進 `assert "<舊標題>" not in html`——不可留空 pass。）

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_mod08_merge.py -v`
Expected: FAIL（`KeyError: 'exposed_ports_merged'`）。

- [ ] **Step 3: 分析端 builder（GREEN 前半）**

`mod08_unmanaged_hosts.py` 檔尾新增（`unmanaged` 一詞以檔內實際的「非受管來源流量」frame 變數為準——即建 `top_unmanaged_src` 的那個 frame）：
```python
def _exposed_ports_merged(unmanaged: pd.DataFrame, per_port: pd.DataFrame) -> pd.DataFrame:
    """暴露 port 合併版（spec C3）：per_port_proto 全欄 + 該 port 的
    未受管來源 Top 3——吸收 src_port_detail 的來源×port 資訊供 HTML 單表呈現。"""
    if per_port is None or per_port.empty:
        return pd.DataFrame()
    has_proto = 'proto' in unmanaged.columns and 'Protocol' in per_port.columns
    keys = ['port', 'proto'] if has_proto else ['port']
    src_series = unmanaged['src_ip'].fillna('(unknown)')
    base = unmanaged.assign(src_ip=src_series)
    per_src = (base[base['port'] > 0]
               .groupby(keys + ['src_ip'], dropna=False)['num_connections'].sum().reset_index())

    def _top_sources(row) -> str:
        sel = per_src[per_src['port'] == row['Port']]
        if has_proto:
            sel = sel[sel['proto'] == row['Protocol']]
        sel = sel.sort_values('num_connections', ascending=False)
        ips = [str(s) for s in sel['src_ip']]
        shown = ips[:3]
        extra = len(ips) - len(shown)
        return ', '.join(shown) + (f' +{extra}' if extra > 0 else '')

    merged = per_port.copy()
    merged['Top Unmanaged Sources'] = merged.apply(_top_sources, axis=1)
    return merged
```
`unmanaged_traffic()` 回傳 dict（per_port_proto 之後）加：
```python
        'exposed_ports_merged': _exposed_ports_merged(unmanaged, per_port_proto),
```
（`per_port_proto` 以檔內實際變數名為準。）

- [ ] **Step 4: exporter 5 表 → 3 表（GREEN 後半）**

基底 `_mod08_html`（html_exporter.py:1052-1078）：KPI strip 與 `rpt_tr_unmanaged_subnote` 不動；表格段改為只渲染三張：
```python
        out += f'<h3>{_s("rpt_tr_top_unmanaged")}</h3>' + _df_to_html(m.get('top_unmanaged_src'), lang=_lang)
        pda = m.get('per_dst_app')
        if pda is not None and hasattr(pda, 'empty') and not pda.empty:
            out += f'<h3>{_s("rpt_tr_managed_apps_unmanaged")}</h3>' + _df_to_html(pda, lang=_lang)
        epm = m.get('exposed_ports_merged')
        if epm is not None and hasattr(epm, 'empty') and not epm.empty:
            out += (self._subnote('rpt_tr_exposed_ports_merged_subnote')
                    + f'<h3>{_s("rpt_tr_exposed_ports_merged")}</h3>' + _df_to_html(epm, lang=_lang))
        return out
```
（以現行方法實文為基礎改——KPI/subnote 之前的段落逐字保留；被移除的三段渲染為 per_port_proto、src_port_detail、managed_hosts_targeted_by_unmanaged。）
i18n 新 key（兩 json）：
- `rpt_tr_exposed_ports_merged`: en "Exposed Ports (with top unmanaged sources)" / zh "暴露的 Ports（含主要 Unmanaged 來源）"
- `rpt_tr_exposed_ports_merged_subnote`: en "One view per port: connection volume, destination apps and the unmanaged sources driving it." / zh "每個 Port 一列：連線量、目的 App 與主要未受管來源。"
孤兒清理（grep 歸零才刪）：`rpt_tr_exposed_ports_proto`、`rpt_tr_unmanaged_src_port`、`rpt_tr_managed_targeted`。若 `report_i18n.py`/json 有 DataFrame 欄位翻譯表（盤點：report_i18n.py:238/348 模式），為 `Top Unmanaged Sources` 欄補 en/zh 翻譯，跟隨既有欄位 key 命名。

- [ ] **Step 5: 全套綠燈**

Run: `python -m pytest tests/test_mod08_merge.py tests/test_traffic_flows_html_exporter.py tests/test_traffic_flows_pipeline.py -v && python -m pytest -q`
Expected: 全 PASS（traffic 覆寫路徑與 pipeline mod08 存在性不受影響）。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(report): merge unmanaged chapter to three tables with exposed-ports view"
```

---

### Task 4: mod01 日期範圍 N/A→N/A 修正（spec C4b）

根因（盤點確認）：`traffic_overview()`（mod01_traffic_overview.py:67-69）用 naive `.min()/.max()` + 逐端 N/A 字串；同檔 `_safe_parse_min/_safe_parse_max`（:10-23，coerce 容錯）已存在但未接上。修法：生產路徑改用 safe parser；兩端皆缺時輸出單一 `'N/A'`（不再出現 "N/A → N/A"）。下游（exporter `_mod01_summary_table`、mod12 KPI）為字串透傳，無需改。

**Files:**
- Modify: `src/report/analysis/mod01_traffic_overview.py`
- Test: `tests/test_mod01_date_range.py`（新檔）

- [ ] **Step 1: RED 測試**

`tests/test_mod01_date_range.py`：
```python
"""mod01 date_range 容錯（spec C4）：字串時間戳可解析、全缺時單一 N/A。"""
import pandas as pd
from src.report.analysis.mod01_traffic_overview import traffic_overview


def _base_row(**kw):
    row = {"src_ip": "10.0.0.1", "dst_ip": "10.1.0.1", "port": 443, "proto": "TCP",
           "src_app": "web", "dst_app": "api", "policy_decision": "allowed",
           "src_managed": True, "dst_managed": True,
           "num_connections": 3, "bytes_total": 100,
           "first_detected": pd.NaT, "last_detected": pd.NaT}
    row.update(kw)
    return row


def test_string_timestamps_parse():
    df = pd.DataFrame([
        _base_row(first_detected="2026-01-01T00:00:00Z", last_detected="2026-01-02T00:00:00Z"),
        _base_row(first_detected="2026-01-03T00:00:00Z", last_detected="2026-01-04T00:00:00Z"),
    ])
    out = traffic_overview(df)
    assert out["date_range"] == "2026-01-01 → 2026-01-04"


def test_all_missing_yields_single_na():
    df = pd.DataFrame([_base_row(), _base_row()])
    out = traffic_overview(df)
    assert out["date_range"] == "N/A"
    assert "N/A → N/A" not in out["date_range"]


def test_datetime_path_unchanged():
    df = pd.DataFrame([
        _base_row(first_detected=pd.Timestamp("2026-02-01"), last_detected=pd.Timestamp("2026-02-03")),
    ])
    out = traffic_overview(df)
    assert out["date_range"] == "2026-02-01 → 2026-02-03"
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_mod01_date_range.py -v`
Expected: `test_string_timestamps_parse`（object dtype 的 naive min 行為）與 `test_all_missing_yields_single_na`（現輸出 "N/A → N/A"）FAIL。

- [ ] **Step 3: 實作（GREEN）**

`traffic_overview()` 的 date range 段（現行 :66-69）改為：
```python
    # Date range — 用 coerce 容錯解析（沿用 _safe_parse_* helper）；
    # 完全無有效時間戳時顯示單一 N/A，不再出現「N/A → N/A」（spec C4）
    start_iso = _safe_parse_min(df['first_detected'] if 'first_detected' in df.columns else None)
    end_iso = _safe_parse_max(df['last_detected'] if 'last_detected' in df.columns else None)
    if start_iso or end_iso:
        date_range = f"{start_iso[:10] if start_iso else 'N/A'} → {end_iso[:10] if end_iso else 'N/A'}"
    else:
        date_range = 'N/A'
```

- [ ] **Step 4: 全套綠燈**

Run: `python -m pytest tests/test_mod01_date_range.py tests/test_date_range_fallback.py -v && python -m pytest -q`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(report): robust mod01 date range parsing with single N/A fallback"
```

---

### Task 5: 變更影響章接線修正（spec C4a 根因版）

盤點發現的實況：spec 假設「首次產出空章節、之後正常」——實際上章節**永遠**不渲染 delta：(a) exporter :1573 讀 `mod12['kpis']`（list）→ 恆走 no_kpi note；(b) `_direction` 名單（mod_change_impact.py:6-7）的 key 名與快照實際 key（report_generator.py:629-636）完全對不上 → 即使接通也恆 neutral。首次執行的 empty-state note（`rpt_change_impact_no_previous`，:1579）其實已存在。本 task 修根因：抽共用 `collect_current_kpis()` helper（快照寫入端與渲染端單一事實來源）+ 方向名單對齊實際 key。

**Files:**
- Modify: `src/report/analysis/mod_change_impact.py`（helper + 方向名單）
- Modify: `src/report/report_generator.py`（快照組裝改用 helper）
- Modify: `src/report/exporters/html_exporter.py`（`_mod_change_impact_html` :1573 改用 helper）
- Modify: `tests/test_mod_change_impact.py`（方向名單 key 更新，保留測試意圖）
- Test: `tests/test_change_impact_render.py`（新檔）

**Interfaces:**
- Produces: `collect_current_kpis(module_results: dict) -> dict`——posture 頂層 key（`enforced_coverage_pct`/`staged_coverage_pct`/`true_gap_pct`/`maturity_score`/`maturity_grade`/`maturity_dimensions`/`enforcement_mode_distribution`）+ `risk_flows_total`（mod04→mod15→mod12 首見）。快照 dict 內容與現行 inline 組裝完全等價（dashboard posture 讀 maturity_score/grade，不可變）。

- [ ] **Step 1: RED 測試**

`tests/test_change_impact_render.py`：
```python
"""變更影響章端到端渲染（spec C4a）：首次 note、次次 delta 表。"""
import pandas as pd
from src.report.exporters.html_exporter import NetworkInventoryHtmlExporter
from src.report.analysis.mod_change_impact import collect_current_kpis


def _results():
    return {
        "mod12": {"kpis": [{"label": "x", "value": 1}],  # 顯示用 list（現況）
                  "key_findings": [],
                  "enforced_coverage_pct": 60.0, "true_gap_pct": 10.0,
                  "maturity_score": 55},
        "mod04": {"risk_flows_total": 7},
        "findings": [],
    }


def test_collect_current_kpis():
    kpis = collect_current_kpis(_results())
    assert kpis["enforced_coverage_pct"] == 60.0
    assert kpis["risk_flows_total"] == 7


def test_first_run_shows_note(monkeypatch):
    import src.report.exporters.html_exporter as he
    monkeypatch.setattr("src.report.snapshot_store.read_latest", lambda *a, **k: None)
    html = NetworkInventoryHtmlExporter(_results(), lang="en").build()
    assert "No previous snapshot" in html or "無先前快照" in html


def test_second_run_renders_delta_table(monkeypatch):
    prev = {"kpis": {"enforced_coverage_pct": 50.0, "true_gap_pct": 15.0,
                     "maturity_score": 50, "risk_flows_total": 9},
            "generated_at": "2026-07-01T00:00:00+00:00"}
    monkeypatch.setattr("src.report.snapshot_store.read_latest", lambda *a, **k: prev)
    html = NetworkInventoryHtmlExporter(_results(), lang="en").build()
    assert "enforced_coverage_pct" in html          # delta 表列
    assert "IMPROVED" in html                        # coverage 上升 + gap 下降 → improved
```
注意 monkeypatch 目標：exporter 內是 function-local `from src.report.snapshot_store import read_latest`（:1570），每次呼叫重新解析——patch `src.report.snapshot_store.read_latest` 有效（同 Phase 2 xlsx 測試的先例）。

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_change_impact_render.py -v`
Expected: `test_collect_current_kpis`（ImportError）與 `test_second_run_renders_delta_table`（現況恆 no_kpi note）FAIL。

- [ ] **Step 3: helper 與方向名單（GREEN 之一）**

`mod_change_impact.py`：
```python
_POSTURE_KEYS = ('enforced_coverage_pct', 'staged_coverage_pct', 'true_gap_pct',
                 'maturity_score', 'maturity_grade', 'maturity_dimensions',
                 'enforcement_mode_distribution')


def collect_current_kpis(module_results: dict) -> dict:
    """自 module_results 收集 Change Impact／快照共用的 posture KPI dict。

    mod12 的顯示用 'kpis' 是 list；可比較的 posture 值住在 mod12 頂層 key。
    此函式是快照寫入端（report_generator）與章節渲染端（html_exporter）的
    單一事實來源——兩端 key 集合由此保持一致。
    """
    mod12 = module_results.get('mod12', {}) or {}
    kpis = {k: mod12[k] for k in _POSTURE_KEYS if k in mod12}
    for mid in ('mod04', 'mod15', 'mod12'):
        m = module_results.get(mid, {})
        if isinstance(m, dict) and 'risk_flows_total' in m and 'risk_flows_total' not in kpis:
            kpis['risk_flows_total'] = m['risk_flows_total']
    return kpis
```
方向名單（:6-7）改為對齊實際快照 key（原名單 key 全庫零生產者，屬過期殘留）：
```python
LOWER_BETTER = ("true_gap_pct", "risk_flows_total")
HIGHER_BETTER = ("enforced_coverage_pct", "maturity_score")
```
（`staged_coverage_pct` 語意雙向——staged→enforced 轉換使其下降是好事、新缺口使其上升是壞事——維持 neutral，加一行繁中註解記錄此決策。）

- [ ] **Step 4: 兩端接上 helper（GREEN 之二）**

1. `report_generator.py` 快照組裝（:625-636）：`_posture_keys` inline 段整段改為
```python
            from src.report.analysis.mod_change_impact import collect_current_kpis
            kpis_dict = collect_current_kpis(result.module_results)
```
（保留其後 `if isinstance(kpis_dict, dict) and kpis_dict:` 與 snap 組裝不動。）
2. `_mod_change_impact_html`（html_exporter.py:1572-1575）改為：
```python
        from src.report.analysis.mod_change_impact import collect_current_kpis
        current_kpis = collect_current_kpis(self._r)
        if not current_kpis:
            return f'<p class="note">{_s("rpt_mod_change_impact_no_kpi")}</p>'
```
3. `tests/test_mod_change_impact.py` 的方向測試改用新 key（例：improvement 用 `enforced_coverage_pct` 上升、regression 用 `true_gap_pct` 上升），測試意圖不變；`test_returns_skipped_when_no_previous` 不動。

- [ ] **Step 5: 全套綠燈**

Run: `python -m pytest tests/test_change_impact_render.py tests/test_mod_change_impact.py tests/test_snapshot_store.py tests/test_posture.py -v && python -m pytest -q`
Expected: 全 PASS（快照 dict 內容等價，dashboard posture 消費不受影響——`test_posture.py` 鎖定）。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "fix(report): wire change impact chapter to real posture kpis with aligned directions"
```

---

### Task 6: 樣本 E2E 驗證 + CHANGELOG + 文件

**Files:**
- Create: scratchpad 腳本（不入版控）
- Modify: `CHANGELOG.md`、`docs/operations-manual.md`、`docs/operations-manual_zh.md`

- [ ] **Step 1: 實際樣本 E2E（專案 CLAUDE.md 規則）**

比照 Phase 2 Task 9 腳本：500+ 列合成 flows（含 unmanaged 來源、四 label 維度、字串與缺失時間戳混合）跑真實管線產出 **network_inventory** HTML（en/zh）與 XLSX，逐項檢查：
1. inventory 章節恰為 7 章（無 overview/distribution/bandwidth 錨點與 nav）
2. matrix 章只有 ENV/APP 兩維 + XLSX 下放註記；XLSX 有 Cross-Label sheet 含 role/loc
3. unmanaged 章恰 3 表（合併表含 Top Unmanaged Sources 欄）
4. 變更影響章：首次跑顯示「無先前快照」note；同 profile 再跑第二次顯示 delta 表（非 no_kpi note）
5. 全缺時間戳樣本的 date_range 顯示單一 N/A（mod12 KPI 卡與 overview 表——後者只在 security 報表驗）
6. security_risk 報表同樣本產一份，spot-check Phase 2 結構未變（發現與行動章、lateral 4 表）
7. 無表格水平溢出、print 按鈕在、zh 無裸 key
檢查結果逐項記錄在報告與 commit body；HTML 留 scratchpad 供 controller 抽查。

- [ ] **Step 2: 回歸**

Run: `python -m pytest -q && python3 scripts/check_no_naive_datetime.py`
Expected: 全綠。

- [ ] **Step 3: CHANGELOG + 操作手冊**

CHANGELOG Unreleased 條目（英文，比照 Phase 2 條目格式）：inventory refocus on asset/label governance — dropped 3 traffic chapters, matrix env/app only (role/loc in XLSX), unmanaged merged to 3 tables, date-range N/A fix, change-impact chapter now renders real deltas。
操作手冊 en/zh：inventory 報表章節清單同步（7 章）、變更影響章行為描述。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: document inventory report simplification (phase 3)"
```

---

## Self-Review 檢核

1. **Spec 覆蓋**：C1 → Task 1；C2 → Task 2；C3 → Task 3；C4（日期）→ Task 4；C4（變更影響空章節）→ Task 5（含根因修正，超出 spec 字面但為其前提成立所必需，rationale 記錄於 task 開頭）。
2. **相依**：Task 1-5 相互獨立，任意順序；Task 6 收尾。建議按號序執行。
3. **型別/名稱一致**：`exposed_ports_merged` 在分析端與 exporter 拼字一致；`collect_current_kpis` 在三個消費點簽名一致；`rpt_tr_matrix_xlsx_note`/`rpt_xlsx_sheet_cross_label`/`rpt_tr_exposed_ports_merged(+_subnote)` 各僅一處定義來源。
4. **不破壞下游**：mod01/09/11 續跑（Task 1 rationale）；mod08 六 key 全保留（快照/mod12 相依明列）；快照 dict 內容經 helper 等價重構（dashboard posture 相依由 test_posture.py 鎖）；security/traffic 輸出由各 task 回歸測試鎖定。
5. **Placeholder 檢查**：Task 3 Step 1 測試檔尾的 `pass` 為明確標記的「實作前補字面值」指令（grep 舊 key en 值填入）——implementer 必須完成，reviewer 需驗證非空殼。
