# Phase 2：Security 報表呈現簡化與死碼清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 spec B 節簡化 Security 報表呈現（三層發現合併為「發現與行動」單章、攻擊態勢依主體合併並量化、橫向移動章 10 表砍 4、Policy 判定 <1% 摺疊、未覆蓋 4 表併 3、三種評分加白話說明），並清除 mod05/mod10 死碼。

**Architecture:** 所有安全專有「計算」全部保留（mod12/attack_posture 的產出結構不變動既有 key，僅新增欄位），變更集中在 (1) `attack_posture.py` 的聚合層（依主體合併、action_matrix 增補 severity/apps/flow_total）、(2) `html_exporter.py` 的渲染層（章節增刪與摺疊）、(3) mod02/mod03 分析端的小幅新增（audit_flags 遷入、合併表新增）。email brief（`report_generator.py:80-133`）與 trend snapshot 相依的 mod12 既有 key 一律不刪。

**Tech Stack:** Python 3 / pandas / pytest；i18n 雙層（見 Global Constraints）。

**Spec:** `docs/superpowers/specs/2026-07-02-traffic-security-report-split-design.md`（B 節全部 7 項；N 節版面約束沿用）

## Global Constraints

- 註解一律繁體中文、無 emoji；commit message 用英文 conventional-commits。
- 每個 task 一個 commit，只動該 task 相關的行（surgical）。
- 每個行為變更先寫 RED 測試重現，再實作（TDD）。
- **i18n 雙層結構**：exporter 的 `self._s(key)` 走 `src/report/exporters/report_i18n.py` 的 `STRINGS`（`{key: {"en": ..., "zh": ...}}`）；`t(key, lang=...)` 走 `src/i18n_en.json` / `src/i18n_zh_TW.json`。新增 key 前先看該 key 的消費端用哪條路，跟隨鄰近 key 的存放位置；刪除 key 前必須 `grep -rn "<key>" src/ tests/` 確認歸零（兩層與兩個 json 都查）。
- **不得變更的下游相依**：`report_generator.py:80-133`（email brief 透傳 mod12 的 `key_findings`/五區塊/`action_matrix`/`maturity_*`）；mod12 回傳 dict 既有 key 一律保留，只允許在 item 內「新增」欄位。
- **network_inventory 輸出不得改變**（spec C 屬 Phase 3）：hero 的 key_findings 區塊對 inventory 保留；`<1%` 摺疊只作用於 `security_risk`。
- **traffic profile 輸出不得改變**（Phase 1 已交付並上線）。
- spec N 版面約束沿用：列印/PDF 按鈕不得弄掉；新表格不得需要水平拖拉（寬內容換行或截斷）。
- 產報表類交付前，須用實際樣本資料跑一次完整輸出並逐頁檢查截斷/溢出（專案 CLAUDE.md 規則；Task 9 落實）。

## 現況地圖（實作者速查）

| 對象 | 位置 |
|---|---|
| 發現三層渲染 | `html_exporter.py:474-481`（key_findings + attack_summary 變數）、`:637-639`（`_findings_block`）、`:788-817`（`_attack_summary_html`）、`:698-701` + `:1210-1293`（findings 章 `_findings_html`） |
| attack posture 聚合 | `src/report/analysis/attack_posture.py:132-192`（`summarize_attack_posture`） |
| mod12 產出 | `src/report/analysis/mod12_executive_summary.py:171-310`（`executive_summary`）；email brief 透傳 `report_generator.py:80-133` |
| mod02 渲染 | `html_exporter.py:876-932`（基底 `_mod02_html`；`:918-925` 讀 mod10 audit_flags） |
| mod03 渲染 | `html_exporter.py:934-978`（`:971-976` 為 port gap 與 services 兩表） |
| mod15 渲染 | `html_exporter.py:1486-1541`（10 張表） |
| mod05 死碼 | `src/report/analysis/mod05_remote_access.py` 全檔；`html_exporter.py:1031-1043`（`_mod05_html`，無呼叫者） |
| mod10 | `src/report/analysis/mod10_allowed_traffic.py`；registry `analysis/__init__.py:69`；只有 `audit_flags`/`audit_flag_count` 被 `_mod02_html` 消費 |
| 評分渲染 | maturity `html_exporter.py:513-547` + `:626`；readiness `_mod13_html:1295-1385`（既有 `rpt_tr_readiness_subnote` 於 `:1372`）；infra `_mod14_html:1427-1484`（無 subnote） |
| XLSX（有真資料的路徑） | `report_generator.py:941+`（`generate_traffic_xlsx`；lateral sheet `:1017-1029` 目前只寫 `service_summary`） |
| 章節順序 | `SecurityRiskHtmlExporter._ordered_section_keys()` `html_exporter.py:1619-1621` |

---

### Task 1: 刪除 mod05 死碼（spec B7 前半）

**Files:**
- Delete: `src/report/analysis/mod05_remote_access.py`
- Modify: `src/report/exporters/html_exporter.py:1031-1043`（刪 `_mod05_html` 整個方法）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`、`src/report/exporters/report_i18n.py`（刪孤兒 key）

**Interfaces:**
- Consumes: 無（registry 早已無 mod05 條目，`analysis/__init__.py:64` 只剩註解，保留該註解不動）
- Produces: 無

- [ ] **Step 1: 確認死碼事實（不寫測試——刪除無行為變更，以 grep 證據代替 RED）**

Run:
```bash
grep -rn "mod05_remote_access\|host_to_host_protocol_analysis" src/ tests/ --include="*.py" | grep -v "analysis/mod05_remote_access.py"
grep -n "_mod05_html" src/report/exporters/html_exporter.py
```
Expected: 第一條零命中；第二條只命中 `def _mod05_html` 定義行本身（無呼叫點）。

- [ ] **Step 2: 刪除模組檔與死方法**

```bash
git rm src/report/analysis/mod05_remote_access.py
```
並在 `html_exporter.py` 刪除整段（現行 1031-1043 行）：
```python
    def _mod05_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod05', {})
        if not isinstance(m, dict) or m.get('total_lateral_flows', 0) == 0:
            return f'<p class="note">{_s("rpt_no_lateral")}</p>'
        return (
            self._subnote('rpt_tr_remote_services_subnote')
            + _df_to_html(m.get('by_service'), lang=_lang)
            + self._subnote('rpt_tr_remote_talkers_subnote')
            + f'<h3>{_s("rpt_tr_top_talkers")}</h3>'
            + _df_to_html(m.get('top_talkers'), lang=_lang)
        )
```

- [ ] **Step 3: 清孤兒 i18n key**

候選：`rpt_no_lateral`、`rpt_tr_remote_services_subnote`、`rpt_tr_remote_talkers_subnote`、`rpt_tr_top_talkers`、`rpt_chart_top_remote_access_ports`。逐一：
```bash
grep -rn "<key>" src/ tests/
```
只刪「Step 2 之後歸零」的 key（en json、zh_TW json、report_i18n.py STRINGS 三處同步）。注意 `rpt_xlsx_no_lateral` 是不同 key，勿動；若任何候選 key 仍有其他消費端（例如 dashboard），保留並在 commit message 註明。

- [ ] **Step 4: 全套測試綠燈**

Run: `python -m pytest -q`
Expected: 全綠（mod05 無任何測試相依，見盤點）。另跑 `python -m pytest tests/test_report_i18n_leakage.py tests/test_section_guidance_keys.py -q` 確認 i18n 清理無漏。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(report): drop dead mod05 remote-access module and renderer"
```

---

### Task 2: audit_flags 遷入 mod02、刪除 mod10（spec B7 後半）

前提事實（盤點結論）：mod10 的 `audit_flags`（allowed 且來源非受管的稽核清單）目前「顯示」在 mod02 章（`html_exporter.py:918-925`），但「資料」由 mod10 計算。spec 的刪除前提要成立，必須先把計算搬進 mod02。mod10 其餘輸出（`top_app_flows`/`top_allowed_ports`/`chart_spec`）exporter 從未使用，可直接消失。

**Files:**
- Modify: `src/report/analysis/mod02_policy_decisions.py`（新增 audit_flags 計算）
- Modify: `src/report/exporters/html_exporter.py:916-925`（改讀 mod02）
- Modify: `src/report/analysis/__init__.py:69`（刪 mod10 registry 條目）
- Delete: `src/report/analysis/mod10_allowed_traffic.py`、`tests/test_mod10_allowed_traffic.py`
- Modify: `tests/test_html_exporter_static_charts.py`、`tests/test_html_size.py`、`tests/test_traffic_profile_registry.py`、`tests/test_traffic_report_split.py`、`tests/test_audit_dashboard_i18n.py`、`tests/test_report_humanize.py`、`tests/test_report_print_layout.py`、`tests/test_traffic_flows_pipeline.py`、`tests/test_traffic_attack_refactor.py`（fixture 中 `mod10` → 併入 `mod02`）
- Test: `tests/test_mod02_audit_flags.py`（新檔）

**Interfaces:**
- Produces: `policy_decision_analysis()` 回傳 dict 新增 `'audit_flags': pd.DataFrame`（欄位 `Unmanaged Source`、`Destination`、`Port`、`Proto`(可省)、`Connections`）與 `'audit_flag_count': int`。Task 8 之前的所有 exporter 測試 fixture 改在 `mod02` dict 提供這兩個 key。

- [ ] **Step 1: RED 測試**

`tests/test_mod02_audit_flags.py`：
```python
"""mod02 稽核清單（allowed 且來源非受管）——自 mod10 遷入的回歸測試。"""
import pandas as pd
from src.report.analysis.mod02_policy_decisions import policy_decision_analysis


def _df():
    return pd.DataFrame([
        # allowed + 非受管來源 → 應入 audit_flags
        {"src_ip": "10.0.0.9", "dst_ip": "10.0.1.5", "port": 445, "proto": "TCP",
         "src_app": "unknown", "dst_app": "fileserver", "policy_decision": "allowed",
         "src_managed": False, "dst_managed": True, "num_connections": 7},
        # allowed + 受管來源 → 不入
        {"src_ip": "10.0.0.2", "dst_ip": "10.0.1.5", "port": 443, "proto": "TCP",
         "src_app": "web", "dst_app": "fileserver", "policy_decision": "allowed",
         "src_managed": True, "dst_managed": True, "num_connections": 3},
        # blocked + 非受管來源 → 不入（僅看 allowed）
        {"src_ip": "10.0.0.9", "dst_ip": "10.0.1.7", "port": 22, "proto": "TCP",
         "src_app": "unknown", "dst_app": "db", "policy_decision": "blocked",
         "src_managed": False, "dst_managed": True, "num_connections": 2},
    ])


def test_mod02_returns_audit_flags():
    out = policy_decision_analysis(_df())
    assert "audit_flags" in out
    assert "audit_flag_count" in out
    flags = out["audit_flags"]
    assert list(flags["Unmanaged Source"]) == ["10.0.0.9"]
    assert list(flags["Destination"]) == ["10.0.1.5"]
    assert int(flags["Port"].iloc[0]) == 445
    assert int(flags["Connections"].iloc[0]) == 7
    assert out["audit_flag_count"] == 1


def test_mod02_audit_flags_empty_when_all_managed():
    df = _df()
    df["src_managed"] = True
    out = policy_decision_analysis(df)
    assert out["audit_flag_count"] == 0
    assert out["audit_flags"].empty
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_mod02_audit_flags.py -v`
Expected: FAIL（`KeyError: 'audit_flags'` 或 assert 失敗）。

- [ ] **Step 3: 在 mod02 實作（GREEN）**

`mod02_policy_decisions.py`：在 `results['port_coverage'] = port_coverage`（現行 :70）之後插入（邏輯搬自 `mod10_allowed_traffic.py:29-45`，欄名與 dtype 完全一致以保 HTML 呈現不變）：
```python
    # 稽核清單：allowed 且來源非受管——自 mod10（Allowed Traffic）遷入，
    # 使「audit flags 由本章產生並呈現」成立（spec B7 前提）。
    allowed_df = df[df['policy_decision'] == 'allowed']
    audit_src = allowed_df[allowed_df['src_managed'] == False].copy()
    _audit_keys = (['src_ip', 'dst_ip', 'port', 'proto']
                   if 'proto' in audit_src.columns else ['src_ip', 'dst_ip', 'port'])
    if not audit_src.empty:
        audit_table = (audit_src.groupby(_audit_keys)['num_connections']
                       .sum().reset_index().nlargest(top_n, 'num_connections')
                       .rename(columns={'src_ip': 'Unmanaged Source',
                                        'dst_ip': 'Destination',
                                        'port': 'Port', 'proto': 'Proto',
                                        'num_connections': 'Connections'}))
        if 'Port' in audit_table.columns:
            audit_table['Port'] = audit_table['Port'].astype('Int64')
        if 'Connections' in audit_table.columns:
            audit_table['Connections'] = audit_table['Connections'].astype('Int64')
        if 'Proto' in audit_table.columns and audit_table['Proto'].astype(str).str.strip().eq('').all():
            audit_table = audit_table.drop(columns=['Proto'])
    else:
        audit_table = pd.DataFrame()
    results['audit_flags'] = audit_table
    results['audit_flag_count'] = len(audit_src)
```

- [ ] **Step 4: exporter 改讀 mod02**

`html_exporter.py` `_mod02_html`（現行 916-925 行）改為：
```python
        # 稽核清單（allowed 且來源非受管）——資料已由 mod02 自產（原 mod10 遷入）
        flags = m.get('audit_flags')
        if flags is not None and hasattr(flags, 'empty') and not flags.empty:
            table_html += (
                self._subnote('rpt_tr_audit_flags_subnote')
                + f'<h3>{_s("rpt_tr_audit_flags")} ({m.get("audit_flag_count", 0)})</h3>'
                + _df_to_html(flags, lang=_lang)
            )
```
（`rpt_tr_audit_flags` / `rpt_tr_audit_flags_subnote` 兩 key 保留不動。）

- [ ] **Step 5: 刪 mod10 與 registry 條目、修 fixture**

```bash
git rm src/report/analysis/mod10_allowed_traffic.py tests/test_mod10_allowed_traffic.py
```
- `src/report/analysis/__init__.py:69` 刪整行 `('mod10', 'src.report.analysis.mod10_allowed_traffic', 'allowed_traffic', _call_df_n, _SEC_INV),`
- `tests/test_traffic_profile_registry.py:20` 附近：斷言清單移除 `"mod10"`。
- 其餘測試檔：凡 fixture 提供 `results['mod10'] = {'audit_flags': ..., 'audit_flag_count': ...}` 者，把兩個 key 搬進 `results['mod02']`（保持值不變）；`test_html_exporter_static_charts.py::test_audit_flags_fold_into_policy_section` 的斷言目標（audit flags 折入 policy 章）不變，只改資料來源。
- 孤兒 i18n key 清理：`rpt_chart_top_allowed_ports` grep 歸零則刪（en/zh json 與 STRINGS）。

- [ ] **Step 6: 全套測試綠燈**

Run: `python -m pytest -q`
Expected: 全綠，含 `tests/test_mod02_audit_flags.py` 2 passed。

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(report): move allowed-unmanaged audit flags into mod02, drop mod10"
```

---

### Task 3: Policy 判定摘要 <1% 摺疊（spec B4）

設計決策：摺疊在「渲染層」做、以 `self._profile == 'security_risk'` 守門——分析端資料形狀不動（inventory/traffic 不受影響），且摺疊所需資訊（`% of Total` 欄）summary 表已有。僅當「≥2 個 decision 佔比 <1% 且至少留 1 個主要列」才摺疊（單一 minor 摺疊沒有簡化效果）。同時 per-decision 明細段跳過被摺疊的 decision。

**Files:**
- Modify: `src/report/exporters/html_exporter.py`（`_mod02_html`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（`t()` 路徑的 2 個新 key）
- Test: `tests/test_mod02_minor_fold.py`（新檔）

**Interfaces:**
- Consumes: mod02 `summary` DataFrame（欄位 `Decision`/`Flows`/`% of Total`/`Inbound`/`Outbound`，`mod02_policy_decisions.py:82-92`）
- Produces: 無新資料 key（純渲染變更）

- [ ] **Step 1: RED 測試**

`tests/test_mod02_minor_fold.py`：
```python
"""Policy 判定章 <1% decision 摺疊（僅 security_risk）。"""
import pandas as pd
from src.report.exporters.html_exporter import (
    SecurityRiskHtmlExporter, NetworkInventoryHtmlExporter,
)


def _results():
    summary = pd.DataFrame([
        {"Decision": "allowed", "Flows": 990, "% of Total": 97.1, "Inbound": 500, "Outbound": 490},
        {"Decision": "blocked", "Flows": 20, "% of Total": 2.0, "Inbound": 10, "Outbound": 10},
        {"Decision": "potentially_blocked", "Flows": 5, "% of Total": 0.5, "Inbound": 3, "Outbound": 2},
        {"Decision": "unknown", "Flows": 4, "% of Total": 0.4, "Inbound": 2, "Outbound": 2},
    ])
    return {
        "mod02": {
            "summary": summary,
            "allowed": {"count": 990, "pct_of_total": 97.1, "inbound_count": 500,
                        "outbound_count": 490, "top_app_flows": pd.DataFrame(),
                        "top_inbound_ports": pd.DataFrame(), "top_outbound_ports": pd.DataFrame()},
            "blocked": {"count": 20, "pct_of_total": 2.0, "inbound_count": 10,
                        "outbound_count": 10, "top_app_flows": pd.DataFrame(),
                        "top_inbound_ports": pd.DataFrame(), "top_outbound_ports": pd.DataFrame()},
            "potentially_blocked": {"count": 5, "pct_of_total": 0.5, "inbound_count": 3,
                                    "outbound_count": 2, "top_app_flows": pd.DataFrame(),
                                    "top_inbound_ports": pd.DataFrame(), "top_outbound_ports": pd.DataFrame()},
        },
        "mod12": {"kpis": [], "key_findings": []},
        "findings": [],
    }


def test_security_folds_minor_decisions():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    # 摺疊列出現、minor decision 的明細標題消失
    assert "Other (&lt;1% each)" in html or "Other (<1% each)" in html
    # potentially_blocked 明細段（heading 帶 0.5%）不應渲染
    assert "0.5%" not in html


def test_inventory_keeps_all_rows():
    html = NetworkInventoryHtmlExporter(_results(), lang="en").build()
    assert "Other (<1% each)" not in html and "Other (&lt;1% each)" not in html
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_mod02_minor_fold.py -v`
Expected: `test_security_folds_minor_decisions` FAIL（無摺疊列）。

- [ ] **Step 3: 實作（GREEN）**

`_mod02_html` 內，`table_html = self._subnote('rpt_tr_mod02_intro') + _df_to_html(m.get('summary'), lang=_lang)`（現行 :883）改為：
```python
        # <1% decision 摺疊（僅 security_risk；spec B4）：
        # ≥2 個 minor 且至少留 1 個主要列才摺疊，避免單列換單列的偽簡化。
        summary_df = m.get('summary')
        minor: list[str] = []
        if (self._profile == 'security_risk' and summary_df is not None
                and hasattr(summary_df, 'empty') and not summary_df.empty
                and '% of Total' in summary_df.columns):
            minor_mask = summary_df['% of Total'] < 1.0
            if int(minor_mask.sum()) >= 2 and int((~minor_mask).sum()) >= 1:
                minor = [str(x) for x in summary_df.loc[minor_mask, 'Decision']]
                folded = {
                    'Decision': t('rpt_mod02_minor_decisions', lang=_lang),
                    'Flows': int(summary_df.loc[minor_mask, 'Flows'].sum()),
                    '% of Total': round(float(summary_df.loc[minor_mask, '% of Total'].sum()), 1),
                    'Inbound': int(summary_df.loc[minor_mask, 'Inbound'].sum()),
                    'Outbound': int(summary_df.loc[minor_mask, 'Outbound'].sum()),
                }
                summary_df = pd.concat(
                    [summary_df.loc[~minor_mask], pd.DataFrame([folded])],
                    ignore_index=True,
                )
        table_html = self._subnote('rpt_tr_mod02_intro') + _df_to_html(summary_df, lang=_lang)
        if minor:
            table_html += (f'<p class="note" style="font-size:12px;">'
                           f'{t("rpt_mod02_minor_note", lang=_lang, names=", ".join(minor))}</p>')
```
per-decision 迴圈（現行 :887 `for d in ('allowed', 'blocked', 'potentially_blocked'):`）第一行加：
```python
            if d in minor:
                continue
```
i18n 新 key（json 兩檔）：
```json
"rpt_mod02_minor_decisions": "Other (<1% each)",
"rpt_mod02_minor_note": "Folded decisions below 1% of total: {names}. Full detail remains in the data export."
```
zh_TW：
```json
"rpt_mod02_minor_decisions": "其他判定（各 <1%）",
"rpt_mod02_minor_note": "佔比低於 1% 的判定已摺疊：{names}。完整明細仍在資料匯出中。"
```

- [ ] **Step 4: 測試綠燈**

Run: `python -m pytest tests/test_mod02_minor_fold.py tests/test_traffic_report_split.py tests/test_traffic_flows_html_exporter.py -v`
Expected: 全 PASS（traffic/inventory 回歸不受影響）。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(report): fold sub-1% policy decisions into a single summary row"
```

---

### Task 4: 未覆蓋章 port gap × services 合併（spec B5）

設計決策：合併表在「分析端」新增（合併需要原始 uncovered 的 per-app 分佈，光靠兩張 top-N 表拼不出來）；原 `uncovered_ports`/`uncovered_services` 兩個 key 照舊回傳（明細留給 XLSX 統一案），HTML 只渲染合併表 → 章內 4 表變 3 表。mod03 僅 security_risk 章節消費，無跨 profile 影響。

**Files:**
- Modify: `src/report/analysis/mod03_uncovered_flows.py`（新增 `_port_service_gap_ranking` 與回傳 key）
- Modify: `src/report/exporters/html_exporter.py:971-976`（兩表換一表）
- Modify: i18n 兩 json + `report_i18n.py`（新 2 key、刪 4 孤兒 key）
- Test: `tests/test_mod03_port_service_merge.py`（新檔）

**Interfaces:**
- Produces: `uncovered_flows()` 回傳新增 `'uncovered_port_services': pd.DataFrame`，欄位 = `_port_gap_ranking` 全欄（`Port`/`Proto`(可省)/`Total Flows`/`Uncovered Flows`/`Gap %`）+ `'Top Destination Apps'`（str，最多 3 個 app，逗號分隔，溢出以 ` +N` 表示）。空資料早退分支（`mod03_uncovered_flows.py:47-79`）同步加 `'uncovered_port_services': pd.DataFrame()`。

- [ ] **Step 1: RED 測試**

`tests/test_mod03_port_service_merge.py`：
```python
"""mod03 port gap 與 service gap 合併表。"""
import pandas as pd
from src.report.analysis.mod03_uncovered_flows import uncovered_flows


def _df():
    rows = []
    # port 445：兩個目的 app 的未覆蓋流量 + 一筆 allowed
    rows.append({"src_ip": "10.0.0.1", "dst_ip": "10.1.0.1", "port": 445, "proto": "TCP",
                 "src_app": "web", "dst_app": "fileserver", "policy_decision": "blocked",
                 "src_managed": True, "dst_managed": True, "num_connections": 30})
    rows.append({"src_ip": "10.0.0.2", "dst_ip": "10.1.0.2", "port": 445, "proto": "TCP",
                 "src_app": "web", "dst_app": "backup", "policy_decision": "potentially_blocked",
                 "src_managed": True, "dst_managed": True, "num_connections": 10})
    rows.append({"src_ip": "10.0.0.3", "dst_ip": "10.1.0.1", "port": 445, "proto": "TCP",
                 "src_app": "app", "dst_app": "fileserver", "policy_decision": "allowed",
                 "src_managed": True, "dst_managed": True, "num_connections": 60})
    return pd.DataFrame(rows)


def test_merged_table_present_with_top_apps():
    out = uncovered_flows(_df())
    merged = out["uncovered_port_services"]
    assert not merged.empty
    row = merged.iloc[0]
    assert int(row["Port"]) == 445
    assert int(row["Uncovered Flows"]) == 40
    # 依未覆蓋連線數排序：fileserver(30) 在 backup(10) 前
    assert row["Top Destination Apps"] == "fileserver, backup"
    # 原兩表照舊保留（供 XLSX 統一案使用）
    assert "uncovered_ports" in out and "uncovered_services" in out


def test_merged_table_empty_when_no_uncovered():
    df = _df()
    df["policy_decision"] = "allowed"
    out = uncovered_flows(df)
    assert out["uncovered_port_services"].empty
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_mod03_port_service_merge.py -v`
Expected: FAIL（`KeyError: 'uncovered_port_services'`）。

- [ ] **Step 3: 分析端實作（GREEN）**

`mod03_uncovered_flows.py` 檔尾新增：
```python
def _port_service_gap_ranking(df: pd.DataFrame, uncovered: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """(port, proto) 未覆蓋排行，附上該 port 未覆蓋連線數最高的目的 App——
    合併原 port gap 與 service gap 兩表供 HTML 呈現（spec B5）。"""
    base = _port_gap_ranking(df, uncovered, top_n=top_n)
    if base.empty:
        return base
    has_proto = 'Proto' in base.columns and 'proto' in uncovered.columns
    unc = uncovered[uncovered['port'] > 0]
    keys = ['port', 'proto'] if has_proto else ['port']
    per_app = (unc.groupby(keys + ['dst_app'])['num_connections'].sum().reset_index())

    def _top_apps(row) -> str:
        sel = per_app[per_app['port'] == row['Port']]
        if has_proto:
            sel = sel[sel['proto'] == row['Proto']]
        sel = sel.sort_values('num_connections', ascending=False)
        apps = [str(a) if str(a).strip() else '(unlabeled)' for a in sel['dst_app'].fillna('')]
        shown = apps[:3]
        extra = len(apps) - len(shown)
        return ', '.join(shown) + (f' +{extra}' if extra > 0 else '')

    base = base.copy()
    base['Top Destination Apps'] = base.apply(_top_apps, axis=1)
    return base
```
`uncovered_flows()` 主回傳（:157-158 之後）加：
```python
        'uncovered_port_services': _port_service_gap_ranking(df, uncovered, top_n=top_n),
```
空資料早退 dict（:63-64 附近）加 `'uncovered_port_services': pd.DataFrame(),`。

- [ ] **Step 4: exporter 兩表換一表**

`_mod03_html`（現行 971-976 行）整段改為：
```python
        ups = m.get('uncovered_port_services')
        if ups is not None and hasattr(ups, 'empty') and not ups.empty:
            out += (self._subnote('rpt_tr_port_service_gaps_subnote')
                    + f'<h3>{_s("rpt_tr_port_service_gaps")}</h3>'
                    + _df_to_html(ups, lang=_lang))
```
i18n 新 key（依 `rpt_tr_port_gaps` 現存位置決定放 STRINGS 或 json，兩語言同步）：
- `rpt_tr_port_service_gaps`: en "Uncovered Ports & Services" / zh "未覆蓋 Port 與服務"
- `rpt_tr_port_service_gaps_subnote`: en "Ports ranked by uncovered flows, with the destination apps that receive them — one view for both the port gap and the missing service rules." / zh "依未覆蓋流量排序的 Port，附主要目的 App——同一張表看 Port 缺口與缺規則的服務。"

孤兒清理：`rpt_tr_port_gaps`、`rpt_tr_port_gaps_subnote`、`rpt_tr_service_gaps`、`rpt_tr_service_gaps_subnote` grep 歸零後刪除。

- [ ] **Step 5: 測試綠燈**

Run: `python -m pytest tests/test_mod03_port_service_merge.py tests/test_pb_semantics.py -v && python -m pytest -q`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(report): merge uncovered port and service gap tables"
```

---

### Task 5: 橫向移動章 10 表砍 4、其餘下放 XLSX（spec B3）

保留：`service_summary`（service 檢視）、`fan_out_sources`、`allowed_lateral_flows`、`attack_paths`。
下放 XLSX：`ip_top_talkers`、`ip_top_pairs`、`bridge_nodes`、`top_reachable_nodes`、`app_chains`（spec 明列 5 項）+ `source_risk_scores`（spec 未列入保留清單、且由 bridge_nodes 衍生 → 一併下放，於 commit message 記錄此決策）。
模組回傳 key 全部不動（posture items 與 XLSX 都要用）。XLSX 落點是 `generate_traffic_xlsx()` 的 lateral sheet（`report_generator.py:1017-1029`）——這是目前唯一有真資料的 XLSX 路徑；一般 `--format xlsx` 空殼問題屬 backlog xlsx-unification 案，本 task 不碰。

**Files:**
- Modify: `src/report/exporters/html_exporter.py:1486-1541`（`_mod15_html`）
- Modify: `src/report/report_generator.py:1017-1029`（lateral sheet 增表）
- Modify: i18n（新 1 key：`rpt_tr_lateral_xlsx_note`；確認 6 個下放表的標題 key 在 json 存在供 `t()` 使用，缺則補）
- Test: `tests/test_mod15_html_trim.py`（新檔）、`tests/test_xlsx_content_traffic.py`（增斷言）

**Interfaces:**
- Consumes: mod15 回傳 dict（`mod15_lateral_movement.py:446-465`，key 見現況地圖）
- Produces: 無資料形狀變更

- [ ] **Step 1: RED 測試**

`tests/test_mod15_html_trim.py`：
```python
"""橫向移動章 HTML 只留 4 張表；主機層明細下放 XLSX。"""
import pandas as pd
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter


def _mod15():
    one = pd.DataFrame([{"A": 1}])
    return {
        "total_lateral_flows": 10, "lateral_pct": 5.0, "node_ips": {},
        "service_summary": pd.DataFrame([{"Service": "smb", "Connections": 9}]),
        "ip_top_talkers": one, "ip_top_pairs": one, "fan_out_sources": one,
        "app_chains": one, "bridge_nodes": one, "top_reachable_nodes": one,
        "attack_paths": pd.DataFrame([{"Path": "a→b"}]),
        "articulation_proxies": one, "source_risk_scores": one,
        "allowed_lateral_flows": one, "attack_posture_items": [],
    }


def _html():
    results = {"mod15": _mod15(), "mod12": {"kpis": [], "key_findings": []}, "findings": []}
    return SecurityRiskHtmlExporter(results, lang="en").build()


def test_kept_tables_render():
    html = _html()
    for key in ("rpt_tr_lateral_by_service", "rpt_tr_fan_out",
                "rpt_tr_allowed_lateral", "rpt_mod15_attack_paths"):
        # 以英文標題文字驗證（STRINGS 的 en 值），實作時以實際字串取代
        pass  # 見 Step 3 後補上實際標題斷言


def test_demoted_tables_absent():
    html = _html()
    from src.report.exporters.report_i18n import STRINGS
    for key in ("rpt_tr_ip_top_talkers", "rpt_tr_ip_top_pairs", "rpt_tr_top_risk_sources",
                "rpt_mod15_bridge_nodes", "rpt_mod15_top_reachable", "rpt_tr_app_chains"):
        title = STRINGS[key]["en"]
        assert title not in html, f"demoted table {key} still rendered"
```
（`test_kept_tables_render` 於 Step 3 依同一 STRINGS 查法補完斷言——保留表標題必須出現在 html 中。）

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_mod15_html_trim.py -v`
Expected: `test_demoted_tables_absent` FAIL（6 個標題目前都在）。

- [ ] **Step 3: `_mod15_html` 改寫（GREEN）**

整個方法（現行 1486-1541）改為：
```python
    def _mod15_html(self):
        m = self._r.get('mod15', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'
        _s = self._s
        _lang = self._lang
        total = m.get('total_lateral_flows', 0)
        pct = m.get('lateral_pct', 0)
        html = (
            self._subnote('rpt_tr_lateral_intro', 'Covers all lateral-movement analysis including IP-level host connection patterns and App(Env)-level graph risk scoring.')
            + f'<p>{_s("rpt_tr_lateral_flows")} <b>{total:,}</b> ({pct}% {_s("rpt_tr_lateral_pct")})</p>'
            + _render_chart_for_html(m.get('chart_spec'), lang=self._lang)
        )
        service_summary = m.get('service_summary')
        if service_summary is not None and not service_summary.empty:
            html += f'<h4>{_s("rpt_tr_lateral_by_service")}</h4>' + _df_to_html(service_summary, lang=_lang)
        fan_out = m.get('fan_out_sources')
        if fan_out is not None and not fan_out.empty:
            html += f'<h4>{_s("rpt_tr_fan_out")}</h4>' + _df_to_html(fan_out, lang=_lang)
        allowed_lateral = m.get('allowed_lateral_flows')
        if allowed_lateral is not None and not allowed_lateral.empty:
            html += f'<h4>{_s("rpt_tr_allowed_lateral")}</h4>' + _df_to_html(allowed_lateral, lang=_lang)
        attack_paths = m.get('attack_paths')
        if attack_paths is not None and not attack_paths.empty:
            _ap_drop = {"Source App Env Key", "Target App Env Key"}
            _ap = attack_paths[[c for c in attack_paths.columns if c not in _ap_drop]]
            html += f'<h4>{_s("rpt_mod15_attack_paths")}</h4>' + _df_to_html(_ap, lang=_lang)
        # 主機層明細（IP talkers/配對、橋接、可達、App 鏈、風險來源）已下放 XLSX（spec B3）
        html += self._subnote('rpt_tr_lateral_xlsx_note')
        return html
```
i18n 新 key `rpt_tr_lateral_xlsx_note`（放 STRINGS，比照 `rpt_tr_lateral_intro`）：
- en: "Host-level detail (IP top talkers, host pairs, bridge nodes, reachable nodes, app chains, risk sources) has moved to the XLSX export."
- zh: "主機層明細（IP Top Talkers、主機配對、橋接節點、可達節點、App 鏈、風險來源）已移至 XLSX 匯出。"

- [ ] **Step 4: XLSX lateral sheet 增表**

`report_generator.py` lateral sheet（現行 1020-1025 寫完 `service_summary` 之後、`else:` 之前）插入：
```python
        # 自 HTML 下放的主機層明細（spec B3）：每表前空一列 + 標題列
        _extra_tables = [
            ("rpt_tr_ip_top_talkers", lat.get("ip_top_talkers")),
            ("rpt_tr_ip_top_pairs", lat.get("ip_top_pairs")),
            ("rpt_tr_top_risk_sources", lat.get("source_risk_scores")),
            ("rpt_mod15_bridge_nodes", lat.get("bridge_nodes")),
            ("rpt_mod15_top_reachable", lat.get("top_reachable_nodes")),
            ("rpt_tr_app_chains", lat.get("app_chains")),
        ]
        for _title_key, _tbl in _extra_tables:
            if _tbl is None or not hasattr(_tbl, "empty") or _tbl.empty:
                continue
            ws.append([])
            ws.append([t(_title_key, lang=lang)])
            ws.append([str(c) for c in _tbl.columns])
            for _, _row in _tbl.iterrows():
                ws.append([str(v) for v in _row])
```
注意：`t()` 走 json——若上述 6 個 key 目前只存在 `report_i18n.STRINGS`，須把同名 key（en/zh 值照抄 STRINGS）補進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`，避免 t() 回退成 key 名。
`tests/test_xlsx_content_traffic.py` 增斷言：lateral sheet 的儲存格值包含 `IP Top Talkers`（或以 `t("rpt_tr_ip_top_talkers", lang="en")` 動態取）。

- [ ] **Step 5: 補完 Step 1 的保留表斷言後全套綠燈**

Run: `python -m pytest tests/test_mod15_html_trim.py tests/test_xlsx_content_traffic.py tests/test_traffic_attack_refactor.py -v && python -m pytest -q`
Expected: 全 PASS（`test_traffic_attack_refactor.py:111-118` 只驗模組回傳 key，不受影響）。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(report): trim lateral chapter to four tables, demote host detail to xlsx"
```

---

### Task 6: 三種評分加白話說明（spec B6）

**Files:**
- Modify: `src/report/exporters/html_exporter.py`（`_build` 的 `_maturity_block`、`_mod14_html` 開頭）
- Modify: `src/report/exporters/report_i18n.py` + 兩 json（新 2 key、改 1 key 文案）
- Test: `tests/test_score_explanations.py`（新檔）

**Interfaces:** 無資料變更，純渲染 + i18n。

- [ ] **Step 1: 先讀權重與級距事實**

實作前開檔核對數字（說明文案必須與程式一致，不可寫錯）：
- maturity 權重：`mod12_executive_summary.py:86-92`（enforcement_coverage 40 / policy_coverage 25 / lateral_movement_control 15 / managed_asset_ratio 10 / risk_port_control 10）；等級級距看 `:103-104` 的 `_compute_maturity_score` 實際 grade 邏輯。
- readiness 權重：`mod13_readiness.py:14-20`（policy_coverage 35 / ringfence_maturity 20 / enforcement_mode 20 / staged_readiness 15 / remote_app_coverage 10）。
- infra 公式與 Tier：`mod14_infrastructure.py:166`（provider 0.45 + consumer 0.35 + betweenness 0.2）、`:59-66`（≥80 Tier-1、≥60 Tier-2、≥40 Tier-3、其餘 Tier-4）。

- [ ] **Step 2: RED 測試**

`tests/test_score_explanations.py`：
```python
"""三種評分的白話說明句（spec B6）。"""
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
from src.report.exporters.report_i18n import STRINGS
import pandas as pd


def _results():
    return {
        "mod12": {"kpis": [], "key_findings": [], "maturity_score": 55,
                  "maturity_grade": "C", "maturity_dimensions": {}},
        "mod13": {"total_score": 60, "grade": "B", "factor_scores": {},
                  "factor_table": pd.DataFrame([{"Factor": "x", "Weight": 35, "Score": 20, "Ratio %": 57}])},
        "mod14": {"total_apps": 3, "total_edges": 5},
        "findings": [],
    }


def test_maturity_and_infra_subnotes_present():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    assert STRINGS["rpt_tr_maturity_subnote"]["en"] in html
    assert STRINGS["rpt_tr_infrastructure_subnote"]["en"] in html


def test_readiness_subnote_mentions_weights():
    # 既有 key 文案更新後必須提及五因子加權
    assert "35" in STRINGS["rpt_tr_readiness_subnote"]["en"]
```

- [ ] **Step 3: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_score_explanations.py -v`
Expected: FAIL（KeyError：新 key 不存在）。

- [ ] **Step 4: 實作（GREEN）**

1. `_maturity_block`（現行 :626）改為：
```python
        _maturity_block = ((f'<h2>{_s("rpt_tr_maturity_heading")}</h2>'
                            + self._subnote('rpt_tr_maturity_subnote')
                            + maturity_html)
                           if self._include_maturity() else '')
```
2. `_mod14_html` 開頭（現行 :1433 `html = (` 之前）改為讓說明句先出：
```python
        html = self._subnote('rpt_tr_infrastructure_subnote') + (
            f'<p>{_s("rpt_tr_apps_analysed")} <b>{m.get("total_apps", 0)}</b> · '
            f'{_s("rpt_tr_comm_edges")} <b>{m.get("total_edges", 0)}</b></p>'
        )
```
3. i18n（STRINGS + 兩 json 若該 key 走 t()；`rpt_tr_readiness_subnote` 為既有 key，就地改值）：
- `rpt_tr_maturity_subnote` en: "How to read: the maturity score (0-100) is the weighted sum of five dimensions — enforcement coverage 40, policy coverage 25, lateral-movement control 15, managed-asset ratio 10, risk-port control 10. Each bar shows points earned vs. the dimension's weight; higher is better." / zh: "怎麼讀：成熟度分數（0-100）為五個維度的加權總和——Enforcement 覆蓋 40、Policy 覆蓋 25、橫向移動管控 15、受管資產比 10、風險 Port 管控 10。每列長條為該維度得分對權重上限；愈高愈成熟。"
- `rpt_tr_infrastructure_subnote` en: "How to read: each app's infrastructure score = provider 45% + consumer 35% + betweenness 20%. Tier-1 (>=80) means highest blast radius — protect first; Tier-2 >=60, Tier-3 >=40, Tier-4 below." / zh: "怎麼讀：每個 App 的基礎架構分數 = Provider 45% + Consumer 35% + 中介性 20% 加權。Tier-1（>=80）牽動面最大、應優先保護；Tier-2 >=60、Tier-3 >=40，其餘為 Tier-4。"
- `rpt_tr_readiness_subnote` 改值 en: "How to read: readiness (0-100) is the weighted sum of five factors — policy coverage 35, ringfence maturity 20, enforcement mode 20, staged readiness 15, remote-app coverage 10. Higher means safer to tighten enforcement; the factor table below shows where points were lost." / zh: "怎麼讀：就緒度分數（0-100）為五因子加權總和——Policy 覆蓋 35、Ringfence 成熟度 20、Enforcement 模式 20、Staged 就緒 15、遠端 App 覆蓋 10。分數愈高代表愈可安全收緊 Enforcement；下方因子表可看出失分處。"
（若 Step 1 核對出的數字與上述不符，以程式碼為準改文案。）

- [ ] **Step 5: 測試綠燈**

Run: `python -m pytest tests/test_score_explanations.py tests/test_report_i18n_leakage.py -v && python -m pytest -q`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(report): add plain-language score explanations for maturity, readiness, infrastructure"
```

---

### Task 7: 攻擊態勢 item 依主體合併 + 量化文字（spec B2）

在 `summarize_attack_posture()` 內：每個區塊改「per app_env_key 合併」（同 app 多個 finding_kind 併一列、severity 取最高、數值 evidence 取大者），finding 文字改為「app: 標籤們 — 量化證據」格式，消除連續同句。item 對外欄位集合不變（severity/finding/action/app_env_key/action_code/evidence），下游（exporter `_rows`、email brief）零改動。

**Files:**
- Modify: `src/report/analysis/attack_posture.py`
- Modify: 兩 json（evidence 標籤 i18n key `rpt_ev_*`）
- Test: `tests/test_attack_posture_merge.py`（新檔）

**Interfaces:**
- Produces: 五區塊 item 形狀不變；`finding` 文字格式變為 `"{app_display}: {labels} — {quantified}"`（無 evidence 數值時省略 `— {quantified}`）。Task 8 依賴本 task 的 action_matrix 增補欄位（見 Step 4）。

- [ ] **Step 1: RED 測試**

`tests/test_attack_posture_merge.py`：
```python
"""攻擊態勢依主體合併與量化文字（spec B2）。"""
from src.report.analysis.attack_posture import make_posture_item, summarize_attack_posture


def _items():
    return [
        make_posture_item(scope="app", framework="readiness", app="web", env="prod",
                          finding_kind="blind_spot", attack_stage="exposure",
                          confidence="high", recommended_action_code="MOVE_TO_ENFORCEMENT",
                          severity="MEDIUM", evidence={"flow_count": 120, "allowed_ratio": 0.9}),
        make_posture_item(scope="app", framework="readiness", app="web", env="prod",
                          finding_kind="enforcement_gap", attack_stage="containment",
                          confidence="high", recommended_action_code="MOVE_TO_ENFORCEMENT",
                          severity="HIGH", evidence={"flow_count": 300}),
        make_posture_item(scope="app", framework="lateral", app="db", env="prod",
                          finding_kind="boundary_breach", attack_stage="initial_access",
                          confidence="high", recommended_action_code="LOCK_BOUNDARY_PORTS",
                          severity="HIGH", evidence={"reachability_count": 8}),
    ]


def test_same_app_merges_to_one_row():
    out = summarize_attack_posture(_items(), lang="en")
    blind = out["blind_spots"]
    # web(prod) 的 blind_spot + enforcement_gap 併成一列
    assert len(blind) == 1
    row = blind[0]
    assert row["severity"] == "HIGH"            # 取最高
    assert "web (prod)" in row["finding"]
    assert "300" in row["finding"]              # 數值 evidence 取大者且入文字


def test_findings_are_quantified():
    out = summarize_attack_posture(_items(), lang="en")
    bb = out["boundary_breaches"][0]
    assert "8" in bb["finding"]


def test_action_matrix_enriched():
    out = summarize_attack_posture(_items(), lang="en")
    am = {a["action_code"]: a for a in out["action_matrix"]}
    assert am["MOVE_TO_ENFORCEMENT"]["severity"] == "HIGH"
    assert am["MOVE_TO_ENFORCEMENT"]["count"] == 2
    assert "web (prod)" in am["MOVE_TO_ENFORCEMENT"]["apps"]
    assert am["MOVE_TO_ENFORCEMENT"]["flow_total"] == 420  # 120 + 300
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_attack_posture_merge.py -v`
Expected: `test_same_app_merges_to_one_row` FAIL（現況兩列）、`test_action_matrix_enriched` FAIL（無 severity/apps/flow_total 欄）。

- [ ] **Step 3: 五區塊合併實作（GREEN 前半）**

`attack_posture.py`：模組層新增（放在 `_ACTION_CODES` 之後）：
```python
# 量化證據的取用優先序：計數類在前、比率/分數類在後
_EVIDENCE_PRIORITY: tuple[str, ...] = (
    "flow_count", "blocked_or_pb_flow_count", "remote_flow_count",
    "unmanaged_traversable_flows", "reachability_count",
    "allowed_ratio", "ringfence_ratio", "blocked_ratio", "remote_allowed_ratio",
    "mixed_traffic_ratio", "betweenness_score", "bridge_score",
    "infrastructure_score", "max_depth",
)

# 只累加「流量計數」類欄位（供 action_matrix 的 flow_total）
_FLOW_COUNT_KEYS: tuple[str, ...] = (
    "flow_count", "blocked_or_pb_flow_count", "remote_flow_count",
    "unmanaged_traversable_flows",
)


def _quantify_evidence(evidence: dict[str, Any], lang: str, limit: int = 2) -> str:
    """依優先序取前 limit 個數值 evidence，渲染為在地化短語。"""
    parts: list[str] = []
    for key in _EVIDENCE_PRIORITY:
        if key not in evidence:
            continue
        val = evidence[key]
        if not isinstance(val, (int, float)):
            continue
        if isinstance(val, float):
            val = round(val, 2)
        label = t(f"rpt_ev_{key}", default=key.replace("_", " "), lang=lang)
        parts.append(f"{label} {val}")
        if len(parts) >= limit:
            break
    sep = t("rpt_ev_sep", default="; ", lang=lang)
    return sep.join(parts)
```
`summarize_attack_posture()` 內，把原本 `for item in ranked: ... grouped[section].append({...})`（現行 152-169 行）改為兩段式：
```python
    # 依（區塊, app）合併：同 app 的多個 finding_kind 併一列，
    # severity 取最高、數值 evidence 取大者（代表最嚴重面）。
    section_apps: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in ranked:
        kind = str(item.get("finding_kind", "")).lower()
        section = section_by_kind.get(kind)
        if not section:
            continue
        key = item.get("app_env_key", "")
        slot = section_apps[section].get(key)
        if slot is None:
            slot = {
                "severity": str(item.get("severity", "INFO")).upper(),
                "kinds": [],
                "action_code": item.get("recommended_action_code", ""),
                "evidence": {},
                "app_display": item.get("app_display", "unlabeled (unlabeled)"),
                "app_env_key": key,
            }
            section_apps[section][key] = slot
        if kind not in slot["kinds"]:
            slot["kinds"].append(kind)
        for ek, ev in (item.get("evidence") or {}).items():
            cur = slot["evidence"].get(ek)
            if isinstance(ev, (int, float)) and isinstance(cur, (int, float)):
                slot["evidence"][ek] = max(cur, ev)
            elif ek not in slot["evidence"]:
                slot["evidence"][ek] = ev
        if (SEVERITY_ORDER.get(str(item.get("severity", "")).upper(), 99)
                < SEVERITY_ORDER.get(slot["severity"], 99)):
            slot["severity"] = str(item.get("severity", "INFO")).upper()

    label_sep = t("rpt_ev_label_sep", default=" / ", lang=lang)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for section, apps in section_apps.items():
        rows: list[dict[str, Any]] = []
        for slot in apps.values():
            labels = label_sep.join(
                t(finding_label_keys.get(k, "rpt_finding_blind_spot"), lang=lang)
                for k in slot["kinds"]
            )
            app_display = slot["app_display"]
            if node_ips:
                app_display = _enrich_app_display(app_display, slot["app_env_key"], node_ips)
            quant = _quantify_evidence(slot["evidence"], lang)
            finding = f"{app_display}: {labels}" + (f" — {quant}" if quant else "")
            rows.append({
                "severity": slot["severity"],
                "finding": finding,
                "action": resolve_recommendation(str(slot["action_code"]), lang),
                "app_env_key": slot["app_env_key"],
                "action_code": slot["action_code"],
                "evidence": slot["evidence"],
            })
        rows.sort(key=lambda r: SEVERITY_ORDER.get(str(r["severity"]).upper(), 99))
        grouped[section] = rows
```
（回傳段的 `grouped.get(...)[:top_n]` 不變。）

- [ ] **Step 4: action_matrix 增補（GREEN 後半；Task 8 相依）**

原 `action_counter` 段（現行 171-184 行）改為：
```python
    # action_matrix 增補：severity（最高）、apps（去重前 5）、flow_total（計數類 evidence 加總）
    action_stats: dict[str, dict[str, Any]] = {}
    for item in ranked:
        code = str(item.get("recommended_action_code", "")).strip()
        if not code:
            continue
        st = action_stats.setdefault(code, {"count": 0, "severity": "INFO", "apps": [], "flow_total": 0})
        st["count"] += 1
        sev = str(item.get("severity", "INFO")).upper()
        if SEVERITY_ORDER.get(sev, 99) < SEVERITY_ORDER.get(st["severity"], 99):
            st["severity"] = sev
        disp = item.get("app_display", "")
        if disp and disp not in st["apps"]:
            st["apps"].append(disp)
        ev = item.get("evidence") or {}
        for k in _FLOW_COUNT_KEYS:
            v = ev.get(k)
            if isinstance(v, (int, float)):
                st["flow_total"] += int(v)
                break

    action_matrix = [
        {
            "action_code": code,
            "count": st["count"],
            "action": resolve_recommendation(code, lang),
            "severity": st["severity"],
            "apps": st["apps"][:5],
            "flow_total": st["flow_total"],
        }
        for code, st in sorted(
            action_stats.items(),
            key=lambda pair: (SEVERITY_ORDER.get(pair[1]["severity"], 99), -pair[1]["count"], pair[0]),
        )
    ][:top_n]
```
i18n 新 key（json 兩檔；`rpt_ev_*` 走 t()）：
```json
"rpt_ev_flow_count": "flows",
"rpt_ev_blocked_or_pb_flow_count": "blocked/PB flows",
"rpt_ev_remote_flow_count": "remote-access flows",
"rpt_ev_unmanaged_traversable_flows": "unmanaged-traversable flows",
"rpt_ev_reachability_count": "reachable nodes",
"rpt_ev_allowed_ratio": "allowed ratio",
"rpt_ev_ringfence_ratio": "ringfence ratio",
"rpt_ev_blocked_ratio": "blocked ratio",
"rpt_ev_remote_allowed_ratio": "remote allowed ratio",
"rpt_ev_mixed_traffic_ratio": "mixed-traffic ratio",
"rpt_ev_betweenness_score": "betweenness",
"rpt_ev_bridge_score": "bridge score",
"rpt_ev_infrastructure_score": "infrastructure score",
"rpt_ev_max_depth": "max path depth",
"rpt_ev_sep": "; ",
"rpt_ev_label_sep": " / "
```
zh_TW 對應：流量數 / 被擋或 PB 流量 / 遠端存取流量 / 可穿越非受管流量 / 可達節點 / allowed 佔比 / ringfence 佔比 / blocked 佔比 / 遠端 allowed 佔比 / 混流佔比 / 中介性 / 橋接分數 / 基礎架構分數 / 最大路徑深度 / 「、」 / 「／」。

- [ ] **Step 5: 測試綠燈（含相依回歸）**

Run: `python -m pytest tests/test_attack_posture_merge.py tests/test_traffic_attack_refactor.py tests/test_pb_semantics.py -v && python -m pytest -q`
Expected: 全 PASS（item 欄位集合未變，`test_executive_summary_contains_attack_sections` 不受影響）。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(report): merge attack posture items by subject with quantified evidence text"
```

---

### Task 8: 三層發現合併為「發現與行動」單章（spec B1）

移除（僅 security_risk 的 HTML 呈現層）：hero 的 key_findings 區塊、attack summary 五區塊章、獨立 findings 章的三層並立。新增：單一「發現與行動」章（沿用 section id=`findings`，錨點測試不破），以行動矩陣表為主軸（severity + 行動 + 量化證據 + 影響範圍），規則發現卡片（含 rule_id/evidence/建議）依 category 併於其後。mod12 產出 key 全部保留（email brief 相依）；network_inventory hero 的 key_findings 保留（spec C 屬 Phase 3）。

**Files:**
- Modify: `src/report/exporters/html_exporter.py`：
  - `_build` 的 `key_findings_html`（:474-480）與 `attack_summary_html`（:481）與 `_findings_block`（:637-639）
  - 刪 `_attack_summary_html`（:788-817）
  - `'findings'` section（:698-701）改用新方法
  - 新增 `_findings_actions_html`
  - `SecurityRiskHtmlExporter` 覆寫 `_hero_includes_findings() -> False`；`HtmlExporter` shim 覆寫為 `self._profile == 'network_inventory'`… 注意：shim 的 security 路徑也要拿掉 hero findings，因此覆寫為 `return self._profile == 'network_inventory'`
- Modify: `report_i18n.py`/json（新章 key；`rpt_tr_nav_findings` 文案改「發現與行動 / Findings & Actions」；`rpt_tr_sec_findings` 保留給舊值 grep 決定去留）
- Modify: `tests/test_traffic_attack_refactor.py:139-169`（改斷言新章）
- Test: `tests/test_findings_actions_chapter.py`（新檔）

**Interfaces:**
- Consumes: Task 7 的 enriched action_matrix（`severity`/`apps`/`flow_total`/`count`/`action_code`/`action`）、mod12 `key_findings`（`severity`/`finding`/`action`）、`self._r['findings']`（rules engine finding 物件）
- Produces: 新渲染方法 `_findings_actions_html(self) -> str`

- [ ] **Step 1: RED 測試**

`tests/test_findings_actions_chapter.py`：
```python
"""發現與行動單章（spec B1）：行動矩陣為主軸、三層舊章移除。"""
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
from src.report.exporters.report_i18n import STRINGS


def _results():
    return {
        "mod12": {
            "kpis": [],
            "key_findings": [{"severity": "HIGH", "finding": "Coverage 40% (gap 12%)",
                              "action": "Prioritise policy authoring"}],
            "action_matrix": [{"action_code": "LOCK_BOUNDARY_PORTS", "count": 3,
                               "action": "Lock down boundary ports", "severity": "CRITICAL",
                               "apps": ["web (prod)", "db (prod)"], "flow_total": 450}],
            "boundary_breaches": [{"severity": "CRITICAL", "finding": "x", "action": "y"}],
            "suspicious_pivot_behavior": [], "blast_radius": [], "blind_spots": [],
        },
        "findings": [],
    }


def test_single_actions_chapter_renders():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    assert 'id="findings"' in html                       # 錨點沿用
    assert STRINGS["rpt_tr_findings_actions"]["en"] in html
    assert "LOCK_BOUNDARY_PORTS" in html
    assert "CRITICAL" in html                            # severity 掛在行動列
    assert "web (prod)" in html                          # 影響範圍
    assert "450" in html                                 # 量化證據
    assert "Coverage 40%" in html                        # key_findings 併入為行動列


def test_old_three_layers_gone():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    assert STRINGS["rpt_tr_attack_summary"]["en"] not in html      # 五區塊章移除
    assert STRINGS["rpt_key_findings"]["en"] not in html           # hero 關鍵發現移除
```

- [ ] **Step 2: 跑測試確認 FAIL**

Run: `python -m pytest tests/test_findings_actions_chapter.py -v`
Expected: 兩測試皆 FAIL。

- [ ] **Step 3: 實作（GREEN）**

1. `SecurityRiskHtmlExporter` 加：
```python
    def _hero_includes_findings(self) -> bool:
        # spec B1：關鍵發現/攻擊摘要移出 hero，併入「發現與行動」章
        return False
```
`HtmlExporter` shim 加：
```python
    def _hero_includes_findings(self) -> bool:
        return self._profile == 'network_inventory'
```
2. `_build` 內：`attack_summary_html = self._attack_summary_html(mod12) if profile == 'security_risk' else ''`（:481）整行刪除；`_findings_block`（:637-639）改為：
```python
        _findings_block = ((f'<h2>{_s("rpt_key_findings")}</h2>' + key_findings_html)
                           if self._hero_includes_findings() else '')
```
（`key_findings_html` 保留——inventory hero 仍用。）
3. 刪除 `_attack_summary_html` 方法（:788-817）。
4. `'findings'` section（:698-701）改為：
```python
            'findings': (
                '<section id="findings" class="card">'
                f'<h2>{_s("rpt_tr_findings_actions")} ({n_findings})</h2>'
                + self._findings_actions_html() + '</section>\n'),
```
注意：inventory 的 `_ordered_section_keys` 不含 `findings`，此變更僅 security 可見。
5. 新方法（放在 `_findings_html` 之前）：
```python
    def _findings_actions_html(self):
        """發現與行動（spec B1）：行動矩陣為主軸，每列掛嚴重度與量化證據；
        規則發現卡片（rule id / evidence / 建議）依 category 併於其後。"""
        _s = self._s
        mod12 = self._r.get('mod12', {})

        rows_html = ''
        for item in mod12.get('action_matrix', []) or []:
            sev = str(item.get('severity', 'INFO')).upper()
            apps = item.get('apps') or []
            apps_str = ', '.join(html.escape(str(a)) for a in apps[:5])
            flow_total = item.get('flow_total', 0)
            evidence_bits = [f"{item.get('count', 0)} {_s('rpt_fa_items_unit')}"]
            if flow_total:
                evidence_bits.append(f"{human_number(flow_total)} {_s('rpt_fa_flows_unit')}")
            rows_html += (
                '<tr>'
                f'<td><span class="badge badge-{sev}">{sev}</span></td>'
                f'<td><b>{html.escape(str(item.get("action_code", "")))}</b><br>'
                f'{html.escape(str(item.get("action", "")))}</td>'
                f'<td>{" · ".join(evidence_bits)}</td>'
                f'<td>{apps_str}</td>'
                '</tr>'
            )
        # 關鍵發現（coverage/ransomware/lateral/unmanaged/data volume 門檻觸發）併為行動列
        for kf in mod12.get('key_findings', []) or []:
            sev = str(kf.get('severity', 'INFO')).upper()
            rows_html += (
                '<tr>'
                f'<td><span class="badge badge-{sev}">{sev}</span></td>'
                f'<td>{html.escape(kf.get("action", ""))}</td>'
                f'<td>{html.escape(kf.get("finding", ""))}</td>'
                f'<td></td>'
                '</tr>'
            )
        action_table = (
            '<div class="report-table-wrap"><table class="report-table"><thead><tr>'
            f'<th>{_s("rpt_fa_col_severity")}</th><th>{_s("rpt_fa_col_action")}</th>'
            f'<th>{_s("rpt_fa_col_evidence")}</th><th>{_s("rpt_fa_col_scope")}</th>'
            '</tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>'
        ) if rows_html else f'<p class="note">{_s("rpt_no_data")}</p>'
        return (
            self._subnote('rpt_fa_subnote')
            + action_table
            + f'<h3>{_s("rpt_fa_rule_findings")}</h3>'
            + self._findings_html()
        )
```
6. i18n 新 key（STRINGS，比照鄰近 `rpt_tr_sec_findings`；nav key 走 STRINGS 就地改值）：
- `rpt_tr_findings_actions`: en "Findings & Actions" / zh "發現與行動"
- `rpt_fa_subnote`: en "One consolidated view: each action carries its severity, quantified evidence and affected scope. Rule-check details follow below." / zh "單一整併檢視：每個行動掛嚴重度、量化證據與影響範圍；規則檢查明細併列於後。"
- `rpt_fa_col_severity`: en "Severity" / zh "嚴重度"
- `rpt_fa_col_action`: en "Action" / zh "行動"
- `rpt_fa_col_evidence`: en "Evidence" / zh "量化證據"
- `rpt_fa_col_scope`: en "Affected Scope" / zh "影響範圍"
- `rpt_fa_items_unit`: en "source findings" / zh "項來源發現"
- `rpt_fa_flows_unit`: en "flows" / zh "條流量"
- `rpt_fa_rule_findings`: en "Rule Check Details" / zh "規則檢查明細"
- `rpt_tr_nav_findings` 值改為 en "Findings & Actions" / zh "發現與行動"
7. 孤兒清理（grep 歸零才刪）：`rpt_tr_attack_summary`、`rpt_tr_boundary_breaches`、`rpt_tr_suspicious_pivot_behavior`、`rpt_tr_blast_radius`、`rpt_tr_blind_spots`、`rpt_tr_action_matrix`、`rpt_tr_sec_findings`。注意 dashboard/email 若有引用（盤點顯示 email brief 只透傳資料不用這些 key），保留有引用者。
8. `tests/test_traffic_attack_refactor.py::test_html_exporter_renders_attack_summary_sections`（:139-169）改為驗證新章：html 含 `STRINGS["rpt_tr_findings_actions"]["en"]` 且不含 `"Boundary Breaches"`。

- [ ] **Step 4: 測試綠燈**

Run: `python -m pytest tests/test_findings_actions_chapter.py tests/test_traffic_attack_refactor.py tests/test_traffic_report_split.py -v && python -m pytest -q`
Expected: 全 PASS（`test_security_renders_maturity_and_readiness` 斷言的 `id="findings"` 錨點沿用故不破）。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(report): consolidate findings layers into single findings-and-actions chapter"
```

---

### Task 9: 樣本 E2E 驗證 + CHANGELOG + 文件

**Files:**
- Create: 臨時腳本（scratchpad，不入版控）
- Modify: `CHANGELOG.md`、`docs/operations-manual.md`、`docs/operations-manual_zh.md`（Security 報表章節描述更新）

- [ ] **Step 1: 用實際樣本產出完整 Security 報表（專案 CLAUDE.md 規則）**

寫一個 scratchpad 腳本：以 500+ 列合成 flows DataFrame（涵蓋四種 policy_decision、managed/unmanaged、多 app/env、port/proto 多樣）跑完整 `ReportGenerator` 管線產出 security_risk HTML 與 `generate_traffic_xlsx` XLSX，逐頁檢查：
- 新「發現與行動」章存在且行動列有 severity/證據/範圍；三層舊章不存在
- lateral 章恰 4 表 + XLSX 下放註記；XLSX lateral sheet 含下放表
- policy 章 <1% 摺疊列與註記；audit_flags 表仍在
- uncovered 章 3 表（合併表含 Top Destination Apps）
- 三個評分區塊的白話說明句
- 無表格水平溢出、列印按鈕存在（`window.print()`）
- zh_TW 再產一份，檢查無 i18n 洩漏（key 名直出）與過長截斷
檢查結果（逐項通過/問題）附在回報與 commit message 中。

- [ ] **Step 2: 回歸全綠 + naive datetime 檢查**

Run: `python -m pytest -q && python scripts/check_no_naive_datetime.py`
Expected: 全綠。

- [ ] **Step 3: CHANGELOG 與操作手冊**

`CHANGELOG.md` 加 Unreleased 條目（英文，格式比照 Phase 1 條目）：Security report simplification —— consolidated findings/actions chapter, subject-merged attack posture with quantified text, lateral chapter trimmed to 4 tables (host detail in XLSX), sub-1% decision folding, merged uncovered port/service view, plain-language score explanations, removed dead mod05/mod10。
`docs/operations-manual.md` 與 `_zh.md`：Security 報表章節清單同步（發現與行動單章、lateral 4 表、XLSX 下放明細）。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: document security report simplification (phase 2)"
```

---

## Self-Review 檢核

1. **Spec 覆蓋**：B1 → Task 8；B2 → Task 7；B3 → Task 5；B4 → Task 3；B5 → Task 4；B6 → Task 6；B7 → Task 1 + Task 2。B 節 7 項全對應。N 節（列印按鈕/不水平捲動）由 Global Constraints + Task 9 驗證涵蓋。
2. **相依順序**：Task 1-6 相互獨立；Task 8 依賴 Task 7 的 enriched action_matrix，必須按序。Task 2 的 fixture 搬移在 Task 8 改測試前完成，避免交叉。
3. **型別一致**：`audit_flags`/`audit_flag_count` 名稱沿用 mod10 原名（exporter 讀法只換來源 dict）；`uncovered_port_services` 於分析端與 exporter 兩處拼字一致；action_matrix 新欄位 `severity`/`apps`/`flow_total` 在 Task 7 產出與 Task 8 消費一致。
4. **不破壞下游**：mod12 回傳 key 零刪除；email brief（`report_generator.py:80-133`）透傳的所有 key 仍存在；inventory/traffic 兩 profile 渲染路徑逐 task 以回歸測試鎖定。
