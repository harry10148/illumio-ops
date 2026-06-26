# UI / 安全報表檢視缺失改善計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復 2026-06-11 WebUI/報表實測檢視（Playwright 實機操作 + 報表內容逐節分析）發現的缺失：趨勢比較失效、i18n 洩漏、數字格式、Policy Diff 報表內容缺口、GUI 小修，並把 Policy Diff 報表接進 GUI。

**Architecture:** 三個獨立可交付的 Phase。Phase 1 修報表引擎正確性 bug（trend canonical key、exec summary 格式、findings i18n）；Phase 2 補強 Policy Diff 報表內容（風險分級、友善名稱、歸因窗口）；Phase 3 GUI 修正與 Policy Diff 報表入口。每個 Phase 結束都是可出貨狀態。

**Tech Stack:** Python 3.10 / Flask / pandas / pytest；前端 vanilla JS（無框架）；i18n 採 `src/i18n_en.json` + `src/i18n_zh_TW.json` 雙檔同步 + `t(key, lang=...)`。

**檢視報告出處：** 本計劃的缺失清單來自 2026-06-11 session 的實測（lab PCE 實際產生 SecurityRisk / Policy Diff 報表並逐節檢視）。截圖存於 `/tmp/ui-review/`。

---

## 已驗證的缺失總表

| # | 缺失 | 證據 | Phase |
|---|------|------|-------|
| 1 | Trend 比較永遠顯示 "No previous snapshot"：snapshot 以**本地化標籤**為 key（6/3 中文 `流量總數` vs 6/11 英文 `Total Flows`），跨語言對不上 | `reports/history/traffic/20260603_225138.json` vs `20260611_133628.json` key 比對 | 1 |
| 2 | Exec Summary Key Findings 顯示 "Total data volume: 438821219 MB" 未格式化（同數據 B008 finding 正確顯示 418.5 TB） | `mod12_executive_summary.py:230` 傳 raw `mb`；`i18n_en.json:2365` 模板 `{mb:.0f} MB` | 1 |
| 3 | 英文報表 findings 證據表格混入中文標籤（「Flow 總數」「唯一 Unmanaged 來源」）：`_format_evidence` 用 process-global `get_language()` 而非報表 lang | `html_exporter.py:161` | 1 |
| 4 | Policy Diff 報表無風險分級：「Quarantine ruleset enabled True→False」（停用隔離 ruleset！）只是普通 modified 列 | 6/11 實測產出的 Policy Diff HTML | 2 |
| 5 | Policy Diff rule 變更顯示原始 href（`svc:/orgs/1/sec_policy/draft/services/9`）而非友善名稱 | 同上 | 2 |
| 6 | Policy Diff 操作者/最後變更時間全空，且空白無說明（歸因窗口固定 30 天、超窗者留白） | 同上；`policy_diff_report.py:18` `_DEFAULT_WINDOW_DAYS=30` | 2 |
| 7 | `?tab=integrations` 深層連結無效：`validTabs` 漏列 `integrations` | `utils.js:321` | 3 |
| 8 | 產生報表成功後，報表卡片「Last:」不更新（只刷新清單） | `dashboard.js:929-934` 成功 handler 只呼叫 `loadReports()` | 3 |
| 9 | 報表語言預設未跟 UI 語言：`syncReportLangToUi()` 依賴 `window._uiLang`（由 `/api/status` 非同步設定），race 時 fallback 'en' | `dashboard.js:626-631`、實測 zh_TW UI 開對話框預設 English | 3 |
| 10 | rate-limiter snapshot 目錄不存在時每分鐘 WARNING 洗版；目錄建立後又污染 git status（`config/limiter/` 不在 .gitignore） | `src/gui/__init__.py:336` log；實測 log | 3 |
| 11 | favicon.ico 404 | 實測 console | 3 |
| 12 | GUI 報表頁只有 4 種報表；Policy Diff（P2 已合併）只能 CLI 產生 | 實測報表頁 | 3 |

---

## 檔案結構（異動地圖）

```
src/report/trend_store.py                      # T1: canonical key + legacy 標籤遷移
src/report/analysis/mod12_executive_summary.py # T1: enforcement KPI 補 label_key；T2: data volume 格式化
src/report/ven_status_generator.py             # T1: 移除 label 正規化 hack（改由 trend_store 處理）
src/report/exporters/html_exporter.py          # T1: trend metric 渲染時本地化；T3: _format_evidence 接 lang
src/i18n_en.json, src/i18n_zh_TW.json          # T2: data volume 模板改 {vol}；T8/T9: 新 GUI 字串
src/report/analysis/policy_diff/risk.py        # T4: 新檔 — 變更風險分級（純函式）
src/report/analysis/policy_diff/diff_engine.py # T5: _summarize_actors 接受 href→name 對照表
src/report/policy_diff_report.py               # T4/T5/T6: 接 risk、name map、attribution_days 參數
src/report/exporters/policy_diff_html_exporter.py # T4: 風險欄位 + 高風險置頂
src/cli/report.py（policy-diff 子命令所在檔）   # T6: --attribution-days 選項
src/static/js/utils.js                         # T7: validTabs 補 integrations
src/static/js/dashboard.js                     # T8: 產生成功後刷新卡片；T9: 語言 fallback；T12: policy diff 產生流程
src/templates/index.html                       # T11: favicon link；T12: Policy Diff 報表卡
src/templates/login.html                       # T11: favicon link
src/gui/__init__.py                            # T10: limiter mkdir
src/gui/routes/reports.py                      # T12: POST /api/policy_diff_report/generate
.gitignore                                     # T10: config/limiter/
tests/test_trend_store_canonical.py            # T1 新測試
tests/test_policy_diff_risk.py                 # T4 新測試
tests/test_policy_diff_engine.py               # T5 增測試
tests/test_gui_policy_diff_generate.py         # T12 新測試
```

執行所有測試的指令（本 repo 慣例）：`./venv/bin/python -m pytest tests/ -x -q`（單檔跑法見各任務）。

---

# Phase 1 — 報表引擎正確性

### Task 1: Trend snapshot 改用 canonical key（修缺失 #1）

KPI dict 目前以 `kpi["label"]`（本地化文字）為 key 存檔。mod12 的 KPI 已帶 `label_key`（`mod12_executive_summary.py:170-184`）、VEN 的帶 `i18n_key`。改成優先用穩定 key 存檔；舊 snapshot（本地化 key）以 i18n 反查表遷移比對；渲染時把 canonical key 翻回當前語言。

**Files:**
- Modify: `src/report/trend_store.py:121-126`
- Modify: `src/report/analysis/mod12_executive_summary.py:193`
- Modify: `src/report/ven_status_generator.py:143-146`
- Modify: `src/report/exporters/html_exporter.py:233`
- Test: `tests/test_trend_store_canonical.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_trend_store_canonical.py
"""Trend snapshots must use stable canonical keys, not localized labels."""
import json

from src.report.trend_store import (
    build_kpi_dict_from_metadata,
    canonicalize_legacy_keys,
    compute_deltas,
    load_previous,
    save_snapshot,
)


def test_build_kpi_dict_prefers_label_key():
    kpis = [
        {"label_key": "mod12_kpi_total_flows", "label": "流量總數", "value": "22,620"},
        {"i18n_key": "rpt_ven_kpi_online", "label": "Online VENs", "value": 18},
        {"label": "Legacy Only", "value": 5},  # 無 key 時退回 label
    ]
    d = build_kpi_dict_from_metadata(kpis)
    assert d == {
        "mod12_kpi_total_flows": "22,620",
        "rpt_ven_kpi_online": 18,
        "Legacy Only": 5,
    }


def test_canonicalize_legacy_keys_maps_zh_and_en_labels():
    # 舊 snapshot 用本地化標籤當 key（zh 與 en 都可能存在）
    legacy = {"_generated_at": "x", "流量總數": "20,282", "Total Connections": "16,171,812"}
    canon = canonicalize_legacy_keys(
        legacy, candidate_keys=["mod12_kpi_total_flows", "mod12_kpi_total_connections"]
    )
    assert canon["mod12_kpi_total_flows"] == "20,282"
    assert canon["mod12_kpi_total_connections"] == "16,171,812"
    assert canon["_generated_at"] == "x"


def test_cross_language_snapshots_now_produce_deltas(tmp_path):
    out = str(tmp_path)
    # 模擬：前一份報表以 zh_TW 產生（舊格式：本地化 key）
    save_snapshot(out, "traffic", {"流量總數": "100"}, generated_at="2026-06-01T00:00:00")
    # 本次報表以 en 產生（新格式：canonical key）
    current = build_kpi_dict_from_metadata(
        [{"label_key": "mod12_kpi_total_flows", "label": "Total Flows", "value": "150"}]
    )
    save_snapshot(out, "traffic", current, generated_at="2026-06-02T00:00:00")
    prev = load_previous(out, "traffic")
    prev = canonicalize_legacy_keys(prev, candidate_keys=list(current.keys()))
    deltas = compute_deltas(current, prev)
    assert len(deltas) == 1
    assert deltas[0]["metric"] == "mod12_kpi_total_flows"
    assert deltas[0]["delta"] == 50.0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_trend_store_canonical.py -v`
Expected: FAIL — `ImportError: cannot import name 'canonicalize_legacy_keys'`

- [ ] **Step 3: 實作 trend_store 變更**

`src/report/trend_store.py` — 取代 `build_kpi_dict_from_metadata`（原 121-126 行）並新增 `canonicalize_legacy_keys`：

```python
def build_kpi_dict_from_metadata(kpis: list[dict]) -> dict[str, Any]:
    """Convert the KPI list from metadata.json format to a flat dict.

    Keys prefer the stable i18n key (``label_key`` / ``i18n_key``) so that
    snapshots written under different report languages stay comparable.
    Falls back to the localized ``label`` for KPIs that carry no key.
    """
    out: dict[str, Any] = {}
    for kpi in kpis:
        if "value" not in kpi:
            continue
        key = kpi.get("label_key") or kpi.get("i18n_key") or kpi.get("label")
        if key:
            out[key] = kpi["value"]
    return out


def canonicalize_legacy_keys(
    snapshot: dict[str, Any] | None,
    candidate_keys: list[str],
) -> dict[str, Any] | None:
    """Migrate a legacy snapshot whose keys are localized labels.

    Pre-fix snapshots used t(label_key, lang) display text as dict keys.
    For each canonical candidate key, look up its en / zh_TW rendering and,
    if the legacy snapshot used that text, rename it to the canonical key.
    Canonical keys already present pass through untouched.
    """
    if not snapshot:
        return snapshot
    from src.i18n import t

    label_to_key: dict[str, str] = {}
    for key in candidate_keys:
        if key.startswith("_"):
            continue
        for lang in ("en", "zh_TW"):
            label = t(key, lang=lang, default="")
            if label and label != key:
                label_to_key[label] = key
    return {label_to_key.get(k, k): v for k, v in snapshot.items()}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_trend_store_canonical.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 接上四個呼叫端**

(a) `src/report/report_generator.py:454-461` — 在 `load_previous` 後加一行遷移：

```python
            from src.report.trend_store import save_snapshot, load_previous, compute_deltas, build_kpi_dict_from_metadata, canonicalize_legacy_keys
            # ...existing kpi_dict build...
            prev = load_previous(output_dir, "traffic")
            prev = canonicalize_legacy_keys(prev, candidate_keys=list(kpi_dict.keys()))
```

（`save_snapshot` / `compute_deltas` 呼叫不變。）

(b) `src/report/ven_status_generator.py:143-146` — 刪除 label 正規化 hack，直接傳 raw kpis 並加遷移：

```python
            _kpi_dict = build_kpi_dict_from_metadata(result.module_results.get("kpis", []))
            _prev = load_previous(output_dir, "ven")
            _prev = canonicalize_legacy_keys(_prev, candidate_keys=list(_kpi_dict.keys()))
```

（import 列表加上 `canonicalize_legacy_keys`；刪除 `_raw_kpis` / `_kpis_labeled` 兩行。）

(c) `src/report/audit_generator.py:744-751` 與 `src/report/policy_usage_generator.py:322-329` — 同樣在 `load_previous` 之後插入：

```python
            prev = canonicalize_legacy_keys(prev, candidate_keys=list(kpi_dict.keys()))
```

（兩處的 import 列表各加 `canonicalize_legacy_keys`。）

(d) `src/report/analysis/mod12_executive_summary.py:193` — enforcement-mode KPI 補 `label_key`：

```python
                kpis.append({"label_key": f"mod12_kpi_enforce_mode_{mode}", "label": t("mod12_kpi_enforcement_prefix", default="Enforcement:", lang=lang) + f" {mode_label}", "value": _fmt(count)})
```

- [ ] **Step 6: 渲染時把 canonical key 翻回當前語言**

`src/report/exporters/html_exporter.py:233`（`_trend_deltas_section` 內 `'Metric': d.get('metric', '')`）改為：

```python
    from src.i18n import t as _t_i18n
    for d in deltas:
        _metric_key = d.get('metric', '')
        rows.append({
            'Metric': _t_i18n(_metric_key, lang=lang, default=_metric_key),
            'Previous': d.get('previous', 0),
            'Current': d.get('current', 0),
            'Delta': d,  # carry the raw entry through; renderer formats as chip
        })
```

（`from src.i18n import t as _t_i18n` 放到檔頭既有 import 區；若檔頭已 import `t` 則直接用。）

- [ ] **Step 7: 跑相關既有測試**

Run: `./venv/bin/python -m pytest tests/test_trend_store_canonical.py tests/test_traffic_trend_decisions.py tests/test_posture.py -v`
Expected: 全 PASS（`test_traffic_trend_decisions.py` 若因 key 名稱斷言失敗，更新其斷言改用 canonical key——那正是本修正的目的）

- [ ] **Step 8: Commit**

```bash
git add src/report/trend_store.py src/report/report_generator.py src/report/ven_status_generator.py src/report/audit_generator.py src/report/policy_usage_generator.py src/report/analysis/mod12_executive_summary.py src/report/exporters/html_exporter.py tests/test_trend_store_canonical.py
git commit -m "fix(report): trend snapshots use canonical i18n keys, not localized labels

Cross-language reports could never match previous snapshots (zh_TW
'流量總數' vs en 'Total Flows'), so Trend vs Previous Report always
showed 'No previous snapshot'. Store label_key/i18n_key, migrate legacy
label-keyed snapshots via reverse i18n lookup, localize at render time."
```

---

### Task 2: Key Findings 資料量格式化（修缺失 #2）

**Files:**
- Modify: `src/report/analysis/mod12_executive_summary.py:230`
- Modify: `src/i18n_en.json:2365`、`src/i18n_zh_TW.json:2365`（`rpt_actmtx_data_volume_msg`）
- Test: `tests/test_mod12_data_volume_format.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_mod12_data_volume_format.py
"""Key Findings data-volume must be human-formatted, not raw MB."""
from src.report.analysis.mod12_executive_summary import executive_summary


def _base_results(total_mb):
    return {
        "mod01": {"total_flows": 10, "total_connections": 10, "unique_src_ips": 1,
                  "unique_dst_ips": 1, "blocked_flows": 0, "src_managed_pct": 100,
                  "total_mb": total_mb, "date_range": "x"},
        "mod03": {"enforced_coverage_pct": 90, "staged_coverage_pct": 5, "true_gap_pct": 5},
        "mod11": {"bytes_data_available": True, "total_mb": total_mb},
        "findings": [],
    }


def test_data_volume_key_finding_is_humanized():
    res = executive_summary(_base_results(438821219), lang="en")
    vol_findings = [k for k in res["key_findings"] if "data volume" in k["finding"].lower()]
    assert vol_findings, "data-volume key finding should fire above 1000 MB"
    text = vol_findings[0]["finding"]
    assert "438821219" not in text          # raw MB 不得出現
    assert "TB" in text or "PB" in text     # fmt_bytes_auto 換算後的單位
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_mod12_data_volume_format.py -v`
Expected: FAIL —— assert "438821219" not in text

- [ ] **Step 3: 實作**

(a) `src/report/analysis/mod12_executive_summary.py:230`：

```python
            f, a = _actmtx("data_volume", lang, vol=fmt_bytes_auto(total_mb, input_unit="MB"))
```

（`fmt_bytes_auto` 已在檔頭 import，第 9 行。）

(b) `src/i18n_en.json` 的 `rpt_actmtx_data_volume_msg`：

```json
  "rpt_actmtx_data_volume_msg": "Total data volume: {vol} across the analysis period.",
```

(c) `src/i18n_zh_TW.json` 的 `rpt_actmtx_data_volume_msg`：

```json
  "rpt_actmtx_data_volume_msg": "分析期間總資料量：{vol}。",
```

- [ ] **Step 4: 跑測試 + i18n 稽核**

Run: `./venv/bin/python -m pytest tests/test_mod12_data_volume_format.py -v && ./venv/bin/python scripts/audit_i18n_usage.py`
Expected: 測試 PASS；i18n 稽核無新增違規

- [ ] **Step 5: Commit**

```bash
git add src/report/analysis/mod12_executive_summary.py src/i18n_en.json src/i18n_zh_TW.json tests/test_mod12_data_volume_format.py
git commit -m "fix(report): humanize data-volume key finding (was raw '438821219 MB')"
```

---

### Task 3: Findings 證據表格 i18n 洩漏（修缺失 #3）

`_format_evidence`（`html_exporter.py:155`）以 process-global `get_language()` 取標籤語言；報表 lang=en 但 GUI 行程語言為 zh_TW 時，英文報表出現「Flow 總數」。

**Files:**
- Modify: `src/report/exporters/html_exporter.py:155-165`（簽名加 `lang`）、`:1162`（call site 傳 `self._lang`）
- Test: `tests/test_format_evidence_lang.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_format_evidence_lang.py
"""Evidence pill labels must follow the report lang, not the process language."""
from src.i18n import set_language
from src.report.exporters.html_exporter import _format_evidence


def test_evidence_labels_use_explicit_lang_not_global(monkeypatch):
    set_language("zh_TW")  # 模擬 GUI 行程全域語言為中文
    try:
        html = _format_evidence({"total_flows": 11}, lang="en")
    finally:
        set_language("en")
    assert "Flow 總數" not in html
    assert "Total Flows" in html
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_format_evidence_lang.py -v`
Expected: FAIL — `TypeError: _format_evidence() got an unexpected keyword argument 'lang'`

- [ ] **Step 3: 實作**

(a) `html_exporter.py:155-161`：

```python
def _format_evidence(evidence: dict, lang: str | None = None) -> str:
    """Convert evidence dict to readable pills, parsing Python literal strings where possible."""
    if not evidence:
        return ''
    import ast
    pills = []
    _sl = lang or get_language()
```

（函式其餘部分不變。）

(b) `html_exporter.py:1162`：

```python
                evidence_html = _format_evidence(f.evidence, lang=self._lang)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_format_evidence_lang.py tests/test_i18n_set_language_callers.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/html_exporter.py tests/test_format_evidence_lang.py
git commit -m "fix(report): evidence pill labels follow report lang (zh labels leaked into en reports)"
```

---

# Phase 2 — Policy Diff 報表內容補強

### Task 4: 變更風險分級（修缺失 #4）

新增純函式模組對 diff 列標注 `risk`（HIGH/MEDIUM/—）：停用 ruleset/rule（enabled True→False）= HIGH；移除 ruleset/rule = MEDIUM。Exporter 加風險欄、HIGH 列加紅色標記並排序置頂。

**Files:**
- Create: `src/report/analysis/policy_diff/risk.py`
- Modify: `src/report/policy_diff_report.py:55-59`（`build()` 接上 grade）
- Modify: `src/report/exporters/policy_diff_html_exporter.py:48-76`
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（3 個新 key）
- Test: `tests/test_policy_diff_risk.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_policy_diff_risk.py
"""Risk grading for policy diff rows."""
import pandas as pd

from src.report.analysis.policy_diff.risk import grade_changes


def _diff(ruleset_rows, rule_rows):
    cols = ["change_type", "ruleset_name", "field", "draft_value", "active_value"]
    return {
        "ruleset_changes": pd.DataFrame(ruleset_rows, columns=cols),
        "rule_changes": pd.DataFrame(rule_rows, columns=cols),
        "summary": {},
    }


def test_disabling_ruleset_is_high_risk():
    d = _diff([["modified", "Quarantine", "enabled", "True", "False"]], [])
    out = grade_changes(d)
    assert out["ruleset_changes"].iloc[0]["risk"] == "HIGH"


def test_removed_rule_is_medium_risk():
    d = _diff([], [["removed", "test", "*", "", "x"]])
    out = grade_changes(d)
    assert out["rule_changes"].iloc[0]["risk"] == "MEDIUM"


def test_plain_modification_has_no_risk_flag():
    d = _diff([], [["modified", "test", "providers", "a", "b"]])
    out = grade_changes(d)
    assert out["rule_changes"].iloc[0]["risk"] == ""


def test_empty_frames_pass_through():
    d = {"ruleset_changes": pd.DataFrame(), "rule_changes": None, "summary": {}}
    out = grade_changes(d)  # 不得 raise
    assert out["rule_changes"] is None
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_policy_diff_risk.py -v`
Expected: FAIL — `ModuleNotFoundError: ... policy_diff.risk`

- [ ] **Step 3: 實作 risk.py**

```python
# src/report/analysis/policy_diff/risk.py
"""Risk grading for policy-diff rows.

PURE post-processing: adds a ``risk`` column (HIGH / MEDIUM / "") to the
ruleset_changes / rule_changes DataFrames. Microsegmentation-governance
heuristics:

  HIGH   — a ruleset or rule is being DISABLED in draft (enabled True→False).
           Disabling e.g. a Quarantine ruleset silently removes containment.
  MEDIUM — a ruleset or rule is being removed entirely.
  ""     — everything else (informational).
"""
from __future__ import annotations

import pandas as pd


def _grade_row(row: pd.Series) -> str:
    change = str(row.get("change_type", ""))
    field = str(row.get("field", ""))
    draft = str(row.get("draft_value", ""))
    active = str(row.get("active_value", ""))
    if change == "modified" and field == "enabled" and draft == "False" and active == "True":
        return "HIGH"
    if change == "modified" and field == "enabled" and draft == "True" and active == "False":
        # ACTIVE 已停用、DRAFT 重新啟用 — 同樣值得注意（例如重新開放被關閉的範圍）
        return "MEDIUM"
    if change == "removed":
        return "MEDIUM"
    return ""


def _apply(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    df = df.copy()
    df["risk"] = df.apply(_grade_row, axis=1)
    return df


def grade_changes(diff: dict) -> dict:
    diff["ruleset_changes"] = _apply(diff.get("ruleset_changes"))
    diff["rule_changes"] = _apply(diff.get("rule_changes"))
    return diff
```

注意：實測案例「Quarantine enabled `True`(draft)→`False`(active)」的欄位語意是 *draft_value=True, active_value=False* —— 即 ACTIVE 端目前是停用、DRAFT 將啟用。請先跑 Step 1 測試對齊 diff_engine 的實際欄位語意（`diff_engine.py` 的 `draft_value`/`active_value` 定義），若與上述相反，對調 `_grade_row` 兩個分支的 HIGH/MEDIUM，並同步修正測試第一筆的期望值。**以「即將生效的狀態是停用 → HIGH」為準。**

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_policy_diff_risk.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 接上 facade 與 exporter**

(a) `src/report/policy_diff_report.py` — import 區加：

```python
from src.report.analysis.policy_diff.risk import grade_changes
```

`build()`（line 55-60）改為：

```python
    def build(self, lang: str = "en") -> dict:
        """Return the attributed diff module_results (no export)."""
        draft = self.api.get_all_rulesets(force_refresh=True) if self.api else []
        active = self.api.get_active_rulesets() if self.api else []
        diff = diff_rulesets(draft, active)
        diff = attribute_changes(diff, self._fetch_policy_events(lang))
        diff = grade_changes(diff)
        return diff
```

(b) `src/report/exporters/policy_diff_html_exporter.py`：

`_COL_I18N`（line 48-58）加一列：

```python
        "risk": "rpt_policy_diff_col_risk",
```

`_CSS`（line 29 之後）加：

```python
.pd-risk-high{color:#b91c1c;font-weight:700;}
.pd-risk-medium{color:#b45309;font-weight:600;}
```

`_table`（line 64-76）改為（HIGH 置頂 + 風險欄渲染）：

```python
    _RISK_RANK = {"HIGH": 0, "MEDIUM": 1}

    def _table(self, df: pd.DataFrame, id_col: str) -> str:
        if df is None or df.empty:
            return f'<p>{_esc(t("rpt_policy_diff_no_changes", lang=self._lang))}</p>'
        if "risk" in df.columns:
            df = df.copy()
            df["_rank"] = df["risk"].map(self._RISK_RANK).fillna(9)
            df = df.sort_values("_rank").drop(columns="_rank")
        cols = ["risk", "change_type", "ruleset_name", id_col, "field",
                "draft_value", "active_value", "last_actor", "last_changed"]
        cols = [c for c in cols if c in df.columns]
        head = "".join(f"<th>{self._header(c)}</th>" for c in cols)
        body = []
        for _, row in df.iterrows():
            cls = _ROW_CLASS.get(str(row.get("change_type", "")), "")
            cells = []
            for c in cols:
                v = row.get(c, "")
                if c == "risk" and v:
                    cells.append(f'<td class="pd-risk-{str(v).lower()}">{_esc(v)}</td>')
                else:
                    cells.append(f"<td>{_esc(v)}</td>")
            body.append(f'<tr class="{cls}">{"".join(cells)}</tr>')
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
```

(c) i18n 兩檔各加（依字母序插入）：

`src/i18n_en.json`：
```json
  "rpt_policy_diff_col_risk": "Risk",
```
`src/i18n_zh_TW.json`：
```json
  "rpt_policy_diff_col_risk": "風險",
```

- [ ] **Step 6: 跑既有 policy diff 測試**

Run: `./venv/bin/python -m pytest tests/test_policy_diff_risk.py tests/test_policy_diff_html_exporter.py tests/test_policy_diff_report.py tests/test_policy_diff_engine.py -v`
Expected: 全 PASS（exporter 測試若斷言固定欄位列表，補上 `risk` 欄）

- [ ] **Step 7: Commit**

```bash
git add src/report/analysis/policy_diff/risk.py src/report/policy_diff_report.py src/report/exporters/policy_diff_html_exporter.py src/i18n_en.json src/i18n_zh_TW.json tests/test_policy_diff_risk.py
git commit -m "feat(policy-diff): grade change risk (disable=HIGH, remove=MEDIUM), surface in HTML"
```

---

### Task 5: Rule 變更顯示友善名稱（修缺失 #5）

`_summarize_actors`（`diff_engine.py:27-50`）輸出原始 href。讓 `diff_rulesets` 接受可選的 `names`（href→顯示名稱）對照表；facade 從 ApiClient 既有的 ACTIVE 物件查詢（`get_ip_lists` / `get_label_groups` / `get_services`，見 `api_client.py:737+`，c24b215 已改為 ACTIVE）建表。引擎保持純函式。

**Files:**
- Modify: `src/report/analysis/policy_diff/diff_engine.py:27-68`（+ `diff_rulesets` 簽名）
- Modify: `src/report/policy_diff_report.py`（建 names map）
- Test: `tests/test_policy_diff_engine.py`（增測試）

- [ ] **Step 1: 寫失敗測試（加到既有 `tests/test_policy_diff_engine.py` 末尾）**

```python
def test_summarize_actors_uses_friendly_names():
    from src.report.analysis.policy_diff.diff_engine import _summarize_actors

    names = {
        "/orgs/1/sec_policy/active/ip_lists/1": "Any (0.0.0.0/0)",
        "/orgs/1/sec_policy/active/services/9": "HTTPS 443",
    }
    items = [
        {"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/1"}},
        {"href": "/orgs/1/sec_policy/active/services/9"},
    ]
    out = _summarize_actors(items, names=names)
    assert "Any (0.0.0.0/0)" in out
    assert "HTTPS 443" in out
    assert "/orgs/1/" not in out  # 不再出現原始 href


def test_summarize_actors_falls_back_to_href_without_names():
    from src.report.analysis.policy_diff.diff_engine import _summarize_actors

    out = _summarize_actors([{"href": "/orgs/1/sec_policy/active/services/9"}])
    assert "/orgs/1/sec_policy/active/services/9" in out
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_policy_diff_engine.py -v -k friendly_names`
Expected: FAIL — `TypeError: _summarize_actors() got an unexpected keyword argument 'names'`

- [ ] **Step 3: 實作 diff_engine 變更**

(a) `_summarize_actors`（line 27-50）改為：

```python
def _summarize_actors(items: list, names: dict[str, str] | None = None) -> str:
    """Order-stable string summary of a providers/consumers/services list.

    ``names`` maps an object href to its display name; unknown hrefs fall
    back to the raw href so the diff stays unambiguous.
    """
    names = names or {}

    def _nm(href: str) -> str:
        return names.get(href, href)

    if not items:
        return "(any)"
    tokens = []
    for it in items:
        if not isinstance(it, dict):
            tokens.append(str(it))
            continue
        if it.get("actors"):
            tokens.append(f"actors:{it['actors']}")
        elif isinstance(it.get("label"), dict) and it["label"].get("href"):
            tokens.append(f"label:{_nm(it['label']['href'])}")
        elif isinstance(it.get("ip_list"), dict) and it["ip_list"].get("href"):
            tokens.append(f"ip_list:{_nm(it['ip_list']['href'])}")
        elif isinstance(it.get("workload"), dict) and it["workload"].get("href"):
            tokens.append(f"workload:{_nm(it['workload']['href'])}")
        elif it.get("proto") is not None or it.get("port") is not None:
            tokens.append(f"svc:{it.get('proto')}/{it.get('port')}")
        elif isinstance(it.get("href"), str):
            tokens.append(f"svc:{_nm(it['href'])}")
        else:
            tokens.append(str(sorted(it.items())))
    return ", ".join(sorted(tokens))
```

(b) `_rule_fields`（line 62-68）與其上游：`_rule_fields(rule)` 改 `_rule_fields(rule, names)` 並把 `names` 傳給三個 `_summarize_actors` 呼叫；`diff_rulesets(draft, active)` 簽名改為 `diff_rulesets(draft, active, names: dict[str, str] | None = None)`，沿呼叫鏈把 `names` 傳到 `_rule_fields`。（檔內所有 `_rule_fields(...)` 呼叫點都要帶上 `names`；grep `_rule_fields(` 確認無遺漏。）

注意：friendly name 可能與 href 多對一（兩個同名 service），fallback 保留 href 即可消歧；名稱衝突不在本任務範圍。

- [ ] **Step 4: facade 建立 names map**

`src/report/policy_diff_report.py` — `build()` 改為：

```python
    def _build_name_map(self) -> dict[str, str]:
        """href -> display name, from ACTIVE object inventories (best-effort)."""
        names: dict[str, str] = {}
        if not self.api:
            return names
        try:
            for obj in (self.api.get_ip_lists() or []):
                if obj.get("href") and obj.get("name"):
                    names[obj["href"]] = obj["name"]
            for obj in (self.api.get_services() or []):
                if obj.get("href") and obj.get("name"):
                    names[obj["href"]] = obj["name"]
            for obj in (self.api.get_label_groups() or []):
                if obj.get("href") and obj.get("name"):
                    names[obj["href"]] = obj["name"]
        except Exception as exc:
            logger.warning(f"PolicyDiffReport: name map unavailable ({exc})")
        return names

    def build(self, lang: str = "en") -> dict:
        """Return the attributed diff module_results (no export)."""
        draft = self.api.get_all_rulesets(force_refresh=True) if self.api else []
        active = self.api.get_active_rulesets() if self.api else []
        diff = diff_rulesets(draft, active, names=self._build_name_map())
        diff = attribute_changes(diff, self._fetch_policy_events(lang))
        diff = grade_changes(diff)
        return diff
```

（label href 的名稱來源是 labels 而非 label_groups；若 `api_client.py` 有 `get_labels()`（grep 確認），在 `_build_name_map` 以 `value`（`key:value` 組合）為顯示名稱加入同樣的迴圈：`names[obj["href"]] = f"{obj.get('key','')}:{obj.get('value','')}"`。若無此方法，labels 維持 href fallback，不要為此新增 API 方法。）

注意：diff 的 draft 端 href 是 `/draft/`、name map 是 ACTIVE 物件的 `/active/` href —— 對 draft href 也要能命中。在 `_build_name_map` 回傳前加：

```python
        names.update({h.replace("/active/", "/draft/"): n for h, n in names.items() if "/active/" in h})
```

- [ ] **Step 5: 跑測試**

Run: `./venv/bin/python -m pytest tests/test_policy_diff_engine.py tests/test_policy_diff_report.py -v`
Expected: 全 PASS

- [ ] **Step 6: 實機驗證（lab PCE）**

Run: `./venv/bin/python illumio-ops.py report policy-diff --format html --output-dir /tmp/review_reports && grep -c "sec_policy/draft/services" /tmp/review_reports/Illumio_Policy_Diff_Report_*.html | tail -1`
Expected: 新產出的 HTML 中 rule 變更列顯示服務／IP list 名稱；原始 href 僅在無名稱可查時出現

- [ ] **Step 7: Commit**

```bash
git add src/report/analysis/policy_diff/diff_engine.py src/report/policy_diff_report.py tests/test_policy_diff_engine.py
git commit -m "feat(policy-diff): resolve service/ip_list/label-group hrefs to friendly names"
```

---

### Task 6: 歸因窗口可調 + 超窗標示（修缺失 #6）

**Files:**
- Modify: `src/report/policy_diff_report.py:18,28-47`（`attribution_days` 參數）
- Modify: `src/cli/report.py`（policy-diff 子命令加 `--attribution-days`；先 `grep -rn "policy-diff" src/cli/` 定位確切檔案與 click 裝飾器位置）
- Modify: `src/report/exporters/policy_diff_html_exporter.py`（空白 actor 顯示 `—`）
- Test: `tests/test_policy_diff_report.py`（增測試）

- [ ] **Step 1: 寫失敗測試（加到 `tests/test_policy_diff_report.py`）**

```python
def test_attribution_window_is_configurable():
    from src.report.policy_diff_report import PolicyDiffReport

    r = PolicyDiffReport(cm=None, api_client=None, attribution_days=90)
    assert r._attribution_days == 90


def test_attribution_window_default_30():
    from src.report.policy_diff_report import PolicyDiffReport

    r = PolicyDiffReport(cm=None, api_client=None)
    assert r._attribution_days == 30
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_policy_diff_report.py -v -k attribution_window`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'attribution_days'`

- [ ] **Step 3: 實作**

(a) `policy_diff_report.py` `__init__`：

```python
    def __init__(self, cm, api_client=None, config_dir: str = "config", cache_reader=None,
                 attribution_days: int = _DEFAULT_WINDOW_DAYS):
        self.cm = cm
        self.api = api_client
        self._config_dir = config_dir
        self._cache = cache_reader
        self._attribution_days = int(attribution_days)
```

`_fetch_policy_events` 內 `start = end - datetime.timedelta(days=_DEFAULT_WINDOW_DAYS)` 改為：

```python
            start = end - datetime.timedelta(days=self._attribution_days)
```

(b) CLI：在 policy-diff 子命令（`grep -rn '"policy-diff"\|policy_diff' src/cli/report.py` 定位）加 click 選項並傳入：

```python
@click.option("--attribution-days", type=int, default=30, show_default=True,
              help="Audit-event lookback window for operator attribution.")
```

並把該值傳給 `PolicyDiffReport(..., attribution_days=attribution_days)`。

(c) Exporter `_table` 的 cell 渲染（Task 4 改過的版本）中，actor/changed 空白改顯示佔位：

```python
                if c in ("last_actor", "last_changed") and not str(v).strip():
                    cells.append(f'<td title="{_esc(t("rpt_policy_diff_attribution_note", lang=self._lang))}">—</td>')
```

（插在 `if c == "risk"` 分支之後、else 之前。）

- [ ] **Step 4: 跑測試**

Run: `./venv/bin/python -m pytest tests/test_policy_diff_report.py tests/test_cli_report_policy_diff.py tests/test_policy_diff_html_exporter.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/policy_diff_report.py src/cli/report.py src/report/exporters/policy_diff_html_exporter.py tests/test_policy_diff_report.py
git commit -m "feat(policy-diff): configurable attribution window (--attribution-days), em-dash for out-of-window"
```

---

# Phase 3 — GUI 修正與 Policy Diff 入口

### Task 7: `?tab=integrations` 深層連結（修缺失 #7）

**Files:**
- Modify: `src/static/js/utils.js:321`

- [ ] **Step 1: 修改 validTabs**

```javascript
  const validTabs = ['dashboard', 'traffic-workload', 'events', 'rules', 'reports', 'settings', 'rule-scheduler', 'integrations'];
```

- [ ] **Step 2: 驗證**

Run: `grep -n "integrations" src/static/js/utils.js`
Expected: validTabs 列表含 `'integrations'`。手動驗證（可選）：啟動 GUI 開 `/?tab=integrations` 應落在整合頁。

- [ ] **Step 3: Commit**

```bash
git add src/static/js/utils.js
git commit -m "fix(gui): ?tab=integrations deep link (missing from validTabs)"
```

---

### Task 8: 產生成功後刷新報表卡片 Last 時間（修缺失 #8）

四個產生流程的成功分支都只呼叫 `loadReports()`；卡片中繼資料由 `loadRcardMeta()`（`dashboard.js:224`）載入。

**Files:**
- Modify: `src/static/js/dashboard.js`（traffic 成功分支 :929-934；audit / ven / policy_usage 的對應成功分支，grep `loadReports()` 定位）

- [ ] **Step 1: 修改所有產生成功分支**

對 `dashboard.js` 中每一處產生成功後的 `loadReports();`（traffic 在 933 行，audit/ven/policy_usage 各有一處，`grep -n "loadReports()" src/static/js/dashboard.js` 全列出）改為：

```javascript
        loadReports();
        if (typeof loadRcardMeta === 'function') loadRcardMeta();
```

（僅改「產生成功」分支；`switchTab` 內 reports 分支已有 loadRcardMeta，不動。）

- [ ] **Step 2: 驗證**

Run: `grep -n -A1 "loadReports()" src/static/js/dashboard.js`
Expected: 每個產生成功分支後面都跟著 `loadRcardMeta` 呼叫

- [ ] **Step 3: Commit**

```bash
git add src/static/js/dashboard.js
git commit -m "fix(gui): refresh report-card Last timestamps after successful generation"
```

---

### Task 9: 報表語言預設跟隨 UI 語言（修缺失 #9）

`syncReportLangToUi()` 依賴 `window._uiLang`（`/api/status` 回應後才設定，`dashboard.js:1076`）；在它就緒前開啟對話框會 fallback 'en'。改為再 fallback 到 `<html lang>`（伺服器端 Jinja 已渲染）。

**Files:**
- Modify: `src/static/js/dashboard.js:626-631`
- Modify: `src/templates/index.html`（確認 `<html>` 標籤帶 lang；若無則補）

- [ ] **Step 1: 確認 index.html 的 html lang**

Run: `grep -n "<html" src/templates/index.html`
若 `<html>` 無 `lang` 屬性，改為（沿用模板既有的語言變數，`grep -n "lang" src/templates/index.html | head` 找到 Jinja 變數名，通常為 `{{ lang }}`）：

```html
<html lang="{{ lang }}">
```

- [ ] **Step 2: 修改 syncReportLangToUi**

```javascript
// Set the m-gen-lang <select> to the current UI language.
function syncReportLangToUi() {
  const el = document.getElementById('m-gen-lang');
  if (!el) return;
  // window._uiLang is set from /api/status; before it resolves, fall back to
  // the server-rendered <html lang> so the default matches the visible UI.
  const docLang = (document.documentElement.lang || '').replace('-', '_');
  const lang = window._uiLang || docLang;
  el.value = lang === 'zh_TW' ? 'zh_TW' : 'en';
}
```

- [ ] **Step 3: 驗證**

啟動 GUI（zh_TW 設定）、開「產生流量分析報表」對話框，報表語言應預設「繁體中文」。
Run（替代驗證）: `grep -n "documentElement.lang" src/static/js/dashboard.js`
Expected: 有命中

- [ ] **Step 4: Commit**

```bash
git add src/static/js/dashboard.js src/templates/index.html
git commit -m "fix(gui): report-language select defaults to UI language before /api/status resolves"
```

---

### Task 10: rate-limiter snapshot 目錄自動建立 + gitignore（修缺失 #10）

**Files:**
- Modify: `src/gui/__init__.py:323-336`（`_write_snapshot`）
- Modify: `.gitignore`

- [ ] **Step 1: _write_snapshot 前置 mkdir**

`src/gui/__init__.py` `_write_snapshot` 的 `try:` 區塊開頭（`now = time.time()` 前）加：

```python
                    self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: .gitignore 加一行**

```
config/limiter/
```

- [ ] **Step 3: 驗證**

Run: `rm -rf config/limiter && ./venv/bin/python -c "
from pathlib import Path
import json, time
# 模擬 JsonFileStorage 寫入路徑（不啟動完整 GUI）
p = Path('config/limiter/rate_limits.json')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({}))
print('ok', p.exists())
" && git check-ignore config/limiter/rate_limits.json && echo IGNORED; rm -rf config/limiter`
Expected: `ok True` 且輸出 `IGNORED`

- [ ] **Step 4: Commit**

```bash
git add src/gui/__init__.py .gitignore
git commit -m "fix(gui): auto-create limiter snapshot dir; ignore config/limiter runtime state"
```

---

### Task 11: favicon（修缺失 #11）

**Files:**
- Modify: `src/templates/index.html`、`src/templates/login.html`（`<head>` 各加一行）

- [ ] **Step 1: 找現成 logo 資產**

Run: `ls src/static/ | grep -i -E "svg|ico|png"`
用現有的盾牌 logo（index.html 頁首 `<img>` 引用的那個檔，`grep -n "img" src/templates/index.html | head -3` 可定位）。

- [ ] **Step 2: 兩個模板 `<head>` 內加（以實際資產路徑為準，下例假設 `logo.svg`）**

```html
<link rel="icon" type="image/svg+xml" href="/static/logo.svg">
```

若 static 下沒有任何可用影像資產，改用內嵌 SVG data URI（Illumio 橘色盾牌）：

```html
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23FF5500' d='M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z'/%3E%3C/svg%3E">
```

- [ ] **Step 3: 驗證**

啟動 GUI、瀏覽器分頁應出現圖示；console 不再有 favicon 404。
Run（替代驗證）: `grep -n "rel=\"icon\"" src/templates/index.html src/templates/login.html`
Expected: 兩檔各一筆

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html src/templates/login.html
git commit -m "fix(gui): add favicon (was 404 on every page load)"
```

---

### Task 12: GUI 報表頁加 Policy Diff 入口（修缺失 #12）

鏡射 audit 報表的既有模式：後端路由（`reports.py:270-322` 為範本）、報表卡（index.html）、產生流程（dashboard.js）、i18n 字串。

**Files:**
- Modify: `src/gui/routes/reports.py`（`api_generate_audit_report` 之後加新路由）
- Modify: `src/templates/index.html`（報表卡區塊，`grep -n "gui_gen_pu_title\|rcard" src/templates/index.html` 定位現有四張卡）
- Modify: `src/static/js/dashboard.js`（`openReportGenModal` 的 `meta` 表 + `_doGeneratePolicyDiff`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_gui_policy_diff_generate.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

參考既有 GUI 路由測試的 fixture 寫法（`grep -rln "audit_report/generate" tests/` 找到範本測試檔，沿用其 app/client fixture 與 login helper）：

```python
# tests/test_gui_policy_diff_generate.py
"""POST /api/policy_diff_report/generate happy path + lang guard."""
from unittest.mock import MagicMock, patch


def test_policy_diff_generate_returns_file(client_logged_in):
    fake_path = "/tmp/x/Illumio_Policy_Diff_Report_x.html"
    with patch("src.report.policy_diff_report.PolicyDiffReport") as MockRep:
        MockRep.return_value.run.return_value = fake_path
        r = client_logged_in.post(
            "/api/policy_diff_report/generate",
            json={"lang": "zh_TW", "format": "html"},
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["files"] == ["Illumio_Policy_Diff_Report_x.html"]


def test_policy_diff_generate_rejects_bad_lang(client_logged_in):
    with patch("src.report.policy_diff_report.PolicyDiffReport") as MockRep:
        MockRep.return_value.run.return_value = "/tmp/x/a.html"
        r = client_logged_in.post(
            "/api/policy_diff_report/generate", json={"lang": "fr"}
        )
    assert r.status_code == 200
    MockRep.return_value.run.assert_called_once()
    assert MockRep.return_value.run.call_args.kwargs["lang"] == "en"  # fallback
```

（`client_logged_in` fixture：若 conftest 無現成者，從範本測試檔複製其 client+login fixture 進本檔。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_gui_policy_diff_generate.py -v`
Expected: FAIL — 404 NOT FOUND（路由不存在）

- [ ] **Step 3: 後端路由（插在 `api_generate_audit_report` 之後，`reports.py:323`）**

```python
    # ── API: Policy Diff Report ──────────────────────────────────────────────
    @bp.route('/api/policy_diff_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_policy_diff_report():
        d = request.json or {}
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.report.policy_diff_report import PolicyDiffReport
            from src.api_client import ApiClient
            cm.load()
            config_dir = _resolve_config_dir()
            from src.main import _make_cache_reader
            rep = PolicyDiffReport(cm, api_client=ApiClient(cm), config_dir=config_dir,
                                   cache_reader=_make_cache_reader(cm))
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in ('html', 'csv') else 'html'
            output_dir = _resolve_reports_dir(cm)
            path = rep.run(output_dir=output_dir, lang=lang, fmt=fmt)
            paths = path if isinstance(path, list) else [path]
            return jsonify({"ok": True, "files": [os.path.basename(p) for p in paths]})
        except Exception as e:
            return _err_with_log("report_policy_diff_generate", e, lang=lang)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_gui_policy_diff_generate.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: i18n 字串（兩檔同步，依字母序插入）**

`src/i18n_en.json`：
```json
  "gui_gen_policy_diff_title": "Generate Policy Diff Report",
  "gui_rcard_policy_diff_desc": "DRAFT vs ACTIVE ruleset drift, with operator attribution and risk grading",
  "gui_rcard_policy_diff_title": "Policy Diff Report",
  "gui_toast_policy_diff_done": "Policy Diff report generated.",
  "gui_toast_policy_diff_fail": "Policy Diff report failed.",
```
`src/i18n_zh_TW.json`：
```json
  "gui_gen_policy_diff_title": "產生 Policy Diff 報表",
  "gui_rcard_policy_diff_desc": "DRAFT vs ACTIVE ruleset 漂移，含操作者歸因與風險分級",
  "gui_rcard_policy_diff_title": "Policy Diff 報表",
  "gui_toast_policy_diff_done": "Policy Diff 報表已產生。",
  "gui_toast_policy_diff_fail": "Policy Diff 報表產生失敗。",
```

- [ ] **Step 6: index.html 報表卡**

複製既有「Policy 使用報表」卡片區塊（`grep -n "policy_usage" src/templates/index.html` 定位），貼於其後並改為：

- 卡標題 `data-i18n="gui_rcard_policy_diff_title"`
- 描述 `data-i18n="gui_rcard_policy_diff_desc"`
- 產生按鈕 `data-action="openReportGenModal" data-args='["policy_diff"]'`
- 卡片 id / Last 欄位 id 比照既有命名（如 `rcard-policy-diff-last`），與 `loadRcardMeta()` 的對應 key 一致（見 Step 7）。

- [ ] **Step 7: dashboard.js 接線**

(a) `openReportGenModal` 的 `meta` 表（:636-640）加：

```javascript
    policy_diff:  { titleKey: 'gui_gen_policy_diff_title', icon: '#icon-shield', dates: false },
```

(b) 仿 `_doGenerateAudit`（:947 起）新增：

```javascript
async function _doGeneratePolicyDiff() {
  _updateGenStep(_t('gui_gen_step_fetching'));
  try {
    const fmtEl = document.getElementById('m-gen-format');
    const langEl = document.getElementById('m-gen-lang');
    const fmt = fmtEl && fmtEl.value === 'csv' ? 'csv' : 'html';
    const r = await post('/api/policy_diff_report/generate', {
      format: fmt, lang: langEl ? langEl.value : 'en',
    });
    if (r.ok) {
      _hideGenProgress(true, '');
      toast(_t('gui_toast_policy_diff_done'));
      loadReports();
      if (typeof loadRcardMeta === 'function') loadRcardMeta();
    } else {
      _hideGenProgress(false, r.error || _t('gui_toast_policy_diff_fail'));
      toast(r.error || _t('gui_toast_policy_diff_fail'), 'err');
    }
  } catch (e) {
    _hideGenProgress(false, e.message);
    toast(e.message, 'err');
  }
}
```

(c) 產生分派處（`grep -n "_doGenerateAudit()" src/static/js/dashboard.js` 找到 type 分派 switch/if）加 `policy_diff` 分支呼叫 `_doGeneratePolicyDiff()`。

(d) `loadRcardMeta()`（:224）若以報表類型清單迭代，把 `policy_diff` 加入清單並對應檔名前綴 `Illumio_Policy_Diff_Report_`。

- [ ] **Step 8: i18n 稽核 + 全測試**

Run: `./venv/bin/python scripts/audit_i18n_usage.py && ./venv/bin/python -m pytest tests/ -x -q`
Expected: 稽核無新增違規；測試全 PASS

- [ ] **Step 9: 實機驗證**

啟動 GUI → 報表頁出現第五張卡「Policy Diff 報表」→ 產生 → 清單出現新檔、可「檢視」開啟，HIGH 風險列置頂顯示。

- [ ] **Step 10: Commit**

```bash
git add src/gui/routes/reports.py src/templates/index.html src/static/js/dashboard.js src/i18n_en.json src/i18n_zh_TW.json tests/test_gui_policy_diff_generate.py
git commit -m "feat(gui): Policy Diff report card + /api/policy_diff_report/generate endpoint"
```

---

## 後續項目（本計劃不含，另開計劃）

實測也觀察到下列項目，因規模較大或需先調查，**刻意不納入本計劃**：

1. **臨時產生報表改 async**：目前同步 HTTP 請求（cheroot 對 idle keep-alive 連線回 408 的 race 實測踩到一次，請求遺失且前端只顯示 "Request Timeout"）。建議複用 report-schedules「立即執行」的背景 thread + 輪詢模式。
2. **稽核報表「7 天無資料」調查**：事件檢視頁同時段有大量事件（50 筆/小時），`report audit` 卻回無資料 —— 先確認 `AuditGenerator._fetch_events` 的事件類型過濾條件再決定是否為 bug。
3. **Findings 補 MITRE ATT&CK technique 對應**（mod13/14/15 已是 attack-stage 導向，加 technique ID 自然）。
4. **儀表板空狀態 CTA**（Posture 區塊「請執行報表」應有按鈕直達產生對話框）、**管線健康 ERROR 顯示原因與修復指引**（實測為 cache 延遲 1004h 但 UI 只顯示 ERROR）。
5. **Policy Resolver 報表 GUI 入口**（建議與本計劃 Task 12 同模式，待 resolver 輸出穩定後做）。
6. **規則排程頁**：24h 時間軸卡 Loading、「下次觸發 —」；**email 摘要版報表**；**VEN 版本分布**；流量頁「POLICY 判」表頭截字。

---

## Self-Review 紀錄

- 缺失 #1–#12 全部對應到 Task 1–12，逐項可追溯（見總表 Phase 欄）。
- 已知不確定點均給了現場確認指令而非留白：T4 Step 3（draft/active 欄位語意以測試對齊）、T5 Step 4（`get_labels()` 是否存在）、T6 Step 3b（CLI 檔案定位）、T12 Step 1（測試 fixture 範本）。
- 型別/名稱一致性：`canonicalize_legacy_keys` 在 T1 各呼叫端拼寫一致；`grade_changes` 在 T4 risk.py 與 facade 一致；`_doGeneratePolicyDiff` 與分派處一致。
