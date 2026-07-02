# Phase 1: Traffic 報表獨立（profile 感知模組執行）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增純流量事實的 `traffic` profile 報表（6 個輕量模組、無安全評分），`report traffic` CLI 改產此報表，趨勢/drift 快照按 profile 分離。

**Architecture:** 模組登錄表（`TRAFFIC_MODULES`）每項加 `profiles` 標記；`traffic` profile 只執行 mod01/02/08/09/11 + mod12 摘要，並跳過 rules engine、drift、labels、vuln。security_risk 與 network_inventory 兩個既有 profile 的模組集合維持現狀（全跑），其收斂屬 Phase 2/3。新增 `TrafficFlowsHtmlExporter` 產出無成熟度、無攻擊摘要的精簡 HTML。

**Tech Stack:** Python 3.12、pandas、click、pytest。專案 venv：`venv/bin/python`。

**Spec:** `docs/superpowers/specs/2026-07-02-traffic-security-report-split-design.md`（A、D、E 節）

## Global Constraints

- Commit message：英文 conventional commits（repo 慣例），結尾附 Co-Authored-By 行。
- 所有使用者可見字串走 i18n：`src/i18n_en.json` 與 `src/i18n_zh_TW.json` 兩檔都要加同一 key。
- 任何輸出（程式、註解、報表）不使用 emoji。
- 例外記錄用 loguru `logger.exception(...)`，不用 `exc_info=True`。
- 測試命令一律 `venv/bin/python -m pytest`（系統無裸 `python`）。
- 新報表 HTML 必須含「列印 / PDF」按鈕（由 `_TrafficReportBase` 的 TOC 提供，勿覆寫掉）；表格不得需要水平拖拉（spec N 節）。
- security_risk / network_inventory 兩個 profile 的既有輸出在本 Phase 不得改變（僅 trend/drift 快照鍵改為 per-profile，屬預期變更）。

---

### Task 1: 模組登錄表加 profiles 標記

**Files:**
- Modify: `src/report/analysis/__init__.py`
- Test: `tests/test_traffic_profile_registry.py`（新檔）

**Interfaces:**
- Produces: `get_traffic_modules(profile: str | None = None) -> list[tuple[str, Callable, Callable]]` — 傳入 `"traffic"` 只回傳 mod01/mod02/mod08/mod09/mod11；傳 `"security_risk"`/`"network_inventory"`/`None` 回傳全部（現狀）。
- Produces: `PROFILES = ("traffic", "security_risk", "network_inventory")` 常數。

- [ ] **Step 1: Write the failing test**

建立 `tests/test_traffic_profile_registry.py`：

```python
"""Phase 1: profile-aware module registry."""
from src.report.analysis import get_traffic_modules, PROFILES


def _ids(profile=None):
    return {mod_id for mod_id, _fn, _adapter in get_traffic_modules(profile)}


def test_profiles_constant():
    assert PROFILES == ("traffic", "security_risk", "network_inventory")


def test_traffic_profile_runs_only_lightweight_modules():
    assert _ids("traffic") == {"mod01", "mod02", "mod08", "mod09", "mod11"}


def test_security_risk_profile_unchanged_full_set():
    # Phase 1 keeps the existing behavior: security/inventory run everything.
    full = {"mod01", "mod02", "mod03", "mod04", "mod06", "mod07", "mod08",
            "mod09", "mod10", "mod11", "mod13", "mod14", "mod15",
            "mod_draft_summary", "mod_ringfence"}
    assert _ids("security_risk") == full
    assert _ids("network_inventory") == full


def test_none_profile_returns_all_modules():
    assert _ids(None) == _ids("security_risk")


def test_unknown_profile_raises():
    import pytest
    with pytest.raises(ValueError):
        get_traffic_modules("bogus")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_traffic_profile_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'PROFILES'`

- [ ] **Step 3: Implement registry profiles**

修改 `src/report/analysis/__init__.py`。在 `TRAFFIC_MODULES` 定義前加：

```python
PROFILES = ("traffic", "security_risk", "network_inventory")
_ALL = frozenset(PROFILES)
_SEC_INV = frozenset({"security_risk", "network_inventory"})
_TRAFFIC_TOO = frozenset({"traffic", "security_risk", "network_inventory"})
```

`TRAFFIC_MODULES` 每個 tuple 追加第 5 欄 `profiles`（`traffic` 只標 mod01/02/08/09/11；其餘標 `_SEC_INV`）：

```python
TRAFFIC_MODULES: list[tuple[str, str, str, Callable, frozenset]] = [
    ('mod01', 'src.report.analysis.mod01_traffic_overview',     'traffic_overview',         _call_df,       _TRAFFIC_TOO),
    ('mod02', 'src.report.analysis.mod02_policy_decisions',     'policy_decision_analysis', _call_df_n,     _TRAFFIC_TOO),
    ('mod03', 'src.report.analysis.mod03_uncovered_flows',      'uncovered_flows',          _call_df_n,     _SEC_INV),
    ('mod04', 'src.report.analysis.mod04_ransomware_exposure',  'ransomware_exposure',      _call_df_cfg_n, _SEC_INV),
    # mod05 (Remote Access) consolidated into mod15 (Lateral Movement Risk)
    ('mod06', 'src.report.analysis.mod06_user_process',         'user_process_analysis',    _call_df_n,     _SEC_INV),
    ('mod07', 'src.report.analysis.mod07_cross_label_matrix',   'cross_label_flow_matrix',  _call_df_n,     _SEC_INV),
    ('mod08', 'src.report.analysis.mod08_unmanaged_hosts',      'unmanaged_traffic',        _call_df_n,     _TRAFFIC_TOO),
    ('mod09', 'src.report.analysis.mod09_traffic_distribution', 'traffic_distribution',     _call_df_n,     _TRAFFIC_TOO),
    ('mod10', 'src.report.analysis.mod10_allowed_traffic',      'allowed_traffic',          _call_df_n,     _SEC_INV),
    ('mod11', 'src.report.analysis.mod11_bandwidth',            'bandwidth_analysis',       _call_df_n,     _TRAFFIC_TOO),
    ('mod13', 'src.report.analysis.mod13_readiness',            'enforcement_readiness',    _call_readiness, _SEC_INV),
    ('mod14', 'src.report.analysis.mod14_infrastructure',       'infrastructure_scoring',   _call_df_n,     _SEC_INV),
    ('mod15', 'src.report.analysis.mod15_lateral_movement',     'lateral_movement_risk',    _call_df_n,     _SEC_INV),
    ('mod_draft_summary', 'src.report.analysis.mod_draft_summary', 'analyze',               _call_df,       _SEC_INV),
    ('mod_ringfence',     'src.report.analysis.mod_ringfence',     'analyze',               _call_df,       _SEC_INV),
]
```

`get_traffic_modules` 加 profile 參數：

```python
def get_traffic_modules(profile: str | None = None) -> list[tuple[str, Callable, Callable]]:
    """Return (mod_id, function, call_adapter) for modules in the given profile.

    profile=None returns every registered module (legacy behavior).
    """
    if profile is not None and profile not in PROFILES:
        raise ValueError(f"unknown traffic report profile: {profile!r}")
    result = []
    for mod_id, mod_path, func_name, adapter, profiles in TRAFFIC_MODULES:
        if profile is not None and profile not in profiles:
            continue
        try:
            fn = load_module_fn(mod_path, func_name)
            result.append((mod_id, fn, adapter))
        except Exception as e:
            logger.error(f"Failed to load module {mod_id} ({mod_path}): {e}")
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_traffic_profile_registry.py -v`
Expected: 5 PASS

- [ ] **Step 5: 檢查既有測試未破壞**

Run: `venv/bin/python -m pytest tests/ -k "registry or module" -q`
Expected: PASS（無人直接解構 4-tuple 的既有用法；若有 fail，該處同步改 5-tuple 解構）

- [ ] **Step 6: Commit**

```bash
git add src/report/analysis/__init__.py tests/test_traffic_profile_registry.py
git commit -m "feat(report): profile-aware traffic module registry"
```

---

### Task 2: mod12 traffic 摘要分支

**Files:**
- Modify: `src/report/analysis/mod12_executive_summary.py:142`（`executive_summary` 開頭）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（新 KPI keys）
- Test: `tests/test_mod12_traffic_summary.py`（新檔）

**Interfaces:**
- Consumes: `results` dict 內的 `mod01`（`total_flows`、`total_connections`、`unique_src_ips`、`unique_dst_ips`、`allowed_flows`、`blocked_flows`、`potentially_blocked_flows`、`total_mb`、`date_range`）。
- Produces: `executive_summary(results, profile="traffic", lang=...)` 回傳 dict，`kpis` 為純流量 KPI，`key_findings`/`findings` 為空 list、`findings_summary` 空 dict、五個 attack posture keys（`boundary_breaches`、`suspicious_pivot_behavior`、`blast_radius`、`blind_spots`、`action_matrix`）皆空 list，**無** `maturity_score`/`maturity_grade`/`maturity_dimensions`/`chart_spec` keys。下游（exporter hero、`_build_report_metadata`）依賴這些空值安全略過。

- [ ] **Step 1: Write the failing test**

建立 `tests/test_mod12_traffic_summary.py`：

```python
"""Phase 1: mod12 traffic-profile summary branch."""
from src.report.analysis.mod12_executive_summary import executive_summary


def _results():
    return {
        "mod01": {
            "total_flows": 100, "total_connections": 5000,
            "unique_src_ips": 10, "unique_dst_ips": 20,
            "allowed_flows": 30, "blocked_flows": 5,
            "potentially_blocked_flows": 65,
            "total_mb": 2048.0, "date_range": "2026-04-27 ~ 2026-05-04",
        },
        "findings": [],
    }


def test_traffic_profile_kpis_only():
    out = executive_summary(_results(), profile="traffic", lang="en")
    keys = {k["label_key"] for k in out["kpis"]}
    assert "mod12_kpi_total_flows" in keys
    assert "mod12_kpi_allowed_flows" in keys
    assert "mod12_kpi_pb_flows" in keys
    assert "mod12_kpi_maturity_score" not in keys


def test_traffic_profile_no_security_analysis():
    out = executive_summary(_results(), profile="traffic", lang="en")
    assert out["key_findings"] == []
    assert out["findings_summary"] == {}
    assert out["action_matrix"] == []
    assert out["boundary_breaches"] == []
    assert "maturity_score" not in out
    assert "chart_spec" not in out


def test_security_profile_still_has_maturity():
    out = executive_summary(_results(), profile="security_risk", lang="en")
    assert "maturity_score" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_mod12_traffic_summary.py -v`
Expected: 前兩個 FAIL（traffic profile 仍走完整路徑，帶 maturity KPI）

- [ ] **Step 3: Implement the traffic branch**

在 `executive_summary()` 函式開頭（`mod01 = results.get(...)` 之前）加：

```python
    if profile == "traffic":
        return _traffic_flows_summary(results, lang=lang)
```

在 `executive_summary` 上方新增：

```python
def _traffic_flows_summary(results: dict[str, Any], lang: str = "en") -> dict:
    """Plain traffic-facts summary: scale KPIs only, no scoring or posture."""
    mod01 = results.get("mod01", {})
    kpis = [
        {"label_key": "mod12_kpi_total_flows",       "label": t("mod12_kpi_total_flows", default="Total Flows", lang=lang), "value": _fmt(mod01.get("total_flows", 0))},
        {"label_key": "mod12_kpi_total_connections", "label": t("mod12_kpi_total_connections", default="Total Connections", lang=lang), "value": _fmt(mod01.get("total_connections", 0))},
        {"label_key": "mod12_kpi_unique_src_ips",    "label": t("mod12_kpi_unique_src_ips", default="Unique Source IPs", lang=lang), "value": _fmt(mod01.get("unique_src_ips", 0))},
        {"label_key": "mod12_kpi_unique_dst_ips",    "label": t("mod12_kpi_unique_dst_ips", default="Unique Dest IPs", lang=lang), "value": _fmt(mod01.get("unique_dst_ips", 0))},
        {"label_key": "mod12_kpi_allowed_flows",     "label": t("mod12_kpi_allowed_flows", default="Allowed Flows", lang=lang), "value": _fmt(mod01.get("allowed_flows", 0))},
        {"label_key": "mod12_kpi_blocked_flows",     "label": t("mod12_kpi_blocked_flows", default="Blocked Flows", lang=lang), "value": _fmt(mod01.get("blocked_flows", 0))},
        {"label_key": "mod12_kpi_pb_flows",          "label": t("mod12_kpi_pb_flows", default="Potentially Blocked Flows", lang=lang), "value": _fmt(mod01.get("potentially_blocked_flows", 0))},
        {"label_key": "mod12_kpi_total_data_volume", "label": t("mod12_kpi_total_data_volume", default="Total Data Volume", lang=lang), "value": fmt_bytes_auto(mod01.get("total_mb", 0), input_unit="MB")},
        {"label_key": "mod12_kpi_date_range",        "label": t("mod12_kpi_date_range", default="Date Range", lang=lang), "value": mod01.get("date_range", "N/A")},
    ]
    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kpis": kpis,
        "findings_summary": {},
        "total_findings": 0,
        "key_findings": [],
        "findings": [],
        "boundary_breaches": [],
        "suspicious_pivot_behavior": [],
        "blast_radius": [],
        "blind_spots": [],
        "action_matrix": [],
    }
```

- [ ] **Step 4: 加 i18n keys**

`src/i18n_en.json` 加（放在既有 `mod12_kpi_blocked_flows` key 附近）：

```json
"mod12_kpi_allowed_flows": "Allowed Flows",
"mod12_kpi_pb_flows": "Potentially Blocked Flows",
```

`src/i18n_zh_TW.json` 同位置加：

```json
"mod12_kpi_allowed_flows": "Allowed 流量",
"mod12_kpi_pb_flows": "Potentially Blocked 流量",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_mod12_traffic_summary.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/report/analysis/mod12_executive_summary.py src/i18n_en.json src/i18n_zh_TW.json tests/test_mod12_traffic_summary.py
git commit -m "feat(report): mod12 traffic-profile plain summary branch"
```

---

### Task 3: ReportGenerator profile 感知管線

**Files:**
- Modify: `src/report/report_generator.py`（`generate_from_api:328`、`generate_from_csv:418`、`_run_pipeline:646`、`_run_modules:749`）
- Test: `tests/test_traffic_flows_pipeline.py`（新檔）

**Interfaces:**
- Consumes: Task 1 的 `get_traffic_modules(profile)`、Task 2 的 mod12 分支。
- Produces: `_run_pipeline(df, source, query_context, traffic_report_profile="traffic")` 產出的 `module_results` 只含 `findings`（空 list）、mod01/02/08/09/11、mod12、`mod_labels`（skip 標記）。`generate_from_api`/`generate_from_csv` 接受 `traffic_report_profile="traffic"`。

- [ ] **Step 1: Write the failing test**

建立 `tests/test_traffic_flows_pipeline.py`：

```python
"""Phase 1: traffic-profile pipeline runs only lightweight modules."""
import pandas as pd
import pytest
from unittest.mock import MagicMock

from src.report.report_generator import ReportGenerator


def _flows_df(n=6):
    rows = []
    for i in range(n):
        rows.append({
            "src_ip": f"10.0.0.{i}", "src_hostname": f"h{i}", "src_managed": True,
            "src_app": "AppA", "src_env": "prod", "src_loc": "dc1", "src_role": "web",
            "dst_ip": f"10.0.1.{i}", "dst_hostname": f"d{i}", "dst_managed": (i % 2 == 0),
            "dst_app": "AppB", "dst_env": "prod", "dst_loc": "dc1", "dst_role": "db",
            "port": 443 + i, "proto": "TCP",
            "process_name": "", "user_name": "",
            "num_connections": 10 + i,
            "policy_decision": ["allowed", "blocked", "potentially_blocked"][i % 3],
            "bytes_total": 1000 * (i + 1), "bandwidth_mbps": 0.5,
            "data_source": "test",
            "first_detected": pd.Timestamp("2026-04-28", tz="UTC"),
            "last_detected": pd.Timestamp("2026-05-03", tz="UTC"),
        })
    return pd.DataFrame(rows)


def _gen():
    cm = MagicMock()
    cm.config = {"settings": {}}
    gen = ReportGenerator(cm, api_client=None)
    return gen


def test_traffic_profile_runs_only_lightweight_modules():
    result = _gen()._run_pipeline(_flows_df(), source="api",
                                  traffic_report_profile="traffic")
    mods = set(result.module_results.keys())
    assert {"mod01", "mod02", "mod08", "mod09", "mod11", "mod12"} <= mods
    for heavy in ("mod03", "mod04", "mod13", "mod14", "mod15",
                  "mod07", "mod10", "mod_ringfence", "mod_draft_summary"):
        assert heavy not in mods, heavy


def test_traffic_profile_skips_rules_engine():
    result = _gen()._run_pipeline(_flows_df(), source="api",
                                  traffic_report_profile="traffic")
    assert result.findings == []


def test_traffic_profile_accepted_by_generate_from_csv_validation():
    gen = _gen()
    with pytest.raises(ValueError):
        gen.generate_from_csv("/nonexistent.csv", traffic_report_profile="bogus")


def test_security_profile_still_runs_full_set():
    result = _gen()._run_pipeline(_flows_df(), source="api",
                                  traffic_report_profile="security_risk")
    assert "mod15" in result.module_results
    assert "mod13" in result.module_results
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_traffic_flows_pipeline.py -v`
Expected: FAIL — traffic profile 被 `generate_from_api` 前的驗證擋下不了（_run_pipeline 直呼），但 heavy modules 仍在 module_results

- [ ] **Step 3: Implement**

(a) `generate_from_api` 與 `generate_from_csv` 的 profile 驗證（兩處相同修改）：

```python
        from src.report.analysis import PROFILES
        if traffic_report_profile not in PROFILES:
            raise ValueError(f"invalid traffic_report_profile: {traffic_report_profile!r}")
```

(b) `_run_pipeline`：rules engine 條件化（`traffic` 不跑）——把

```python
        engine = RulesEngine(self._report_cfg, config_dir=self._config_dir, lang=lang)
        findings = engine.evaluate(df)
        print(t("rpt_rules_findings", count=len(findings), lang=lang))
```

改為：

```python
        if traffic_report_profile == "traffic":
            findings = []
        else:
            engine = RulesEngine(self._report_cfg, config_dir=self._config_dir, lang=lang)
            findings = engine.evaluate(df)
            print(t("rpt_rules_findings", count=len(findings), lang=lang))
```

(c) `_run_pipeline` 的 mod_labels 區塊（line 676-687）與 mod_vuln 區塊（line 689-697）條件化：整段 label hygiene try/except 外包 `if traffic_report_profile != "traffic":`，並在 else 補 skip 標記（exporter 章節不渲染，但 CSV 匯出結構保持可預期）：

```python
        if traffic_report_profile != "traffic":
            try:
                from src.report.analysis.mod_labels import label_hygiene
                ...（原內容不動）...
        else:
            results["mod_labels"] = {"workload_data_available": False,
                                     "managed_unlabeled_flow_count": 0}
```

mod_vuln 區塊改為 `if getattr(self, "_vuln_csv_path", None) and traffic_report_profile != "traffic":`。

(d) `_run_modules`：把 `get_traffic_modules()` 呼叫改為 `get_traffic_modules(traffic_report_profile)`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_traffic_flows_pipeline.py -v`
Expected: 4 PASS

- [ ] **Step 5: 既有管線測試不破壞**

Run: `venv/bin/python -m pytest tests/ -k "report or pipeline or draft" -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/report/report_generator.py tests/test_traffic_flows_pipeline.py
git commit -m "feat(report): profile-aware pipeline, traffic profile skips security analysis"
```

---

### Task 4: export() — exporter 選擇與 per-profile 趨勢/drift 快照

**Files:**
- Modify: `src/report/report_generator.py:449-505`（`export()`）
- Test: `tests/test_traffic_report_trend_keying.py`（新檔）

**Interfaces:**
- Consumes: Task 5 的 `TrafficFlowsHtmlExporter`（本 task 先引用，Task 5 實作；依順序執行時本 task 的 HTML 測試在 Task 5 完成後才會全綠 — 因此本 task 的測試只驗 trend keying 與 drift 條件，exporter import 於 Task 5 加入）。
- Produces: trend/drift 快照鍵 `f"traffic_{profile}"`；drift 只在 `security_risk` 計算與注入。

**注意：** 舊快照鍵為 `"traffic"`（所有 profile 共用、互相污染）。改鍵後每個 profile 第一次跑沒有前期基準（`與前次報表比較` 顯示首次產出訊息）— 這是預期行為，記入 CHANGELOG（Task 7）。

- [ ] **Step 1: Write the failing test**

建立 `tests/test_traffic_report_trend_keying.py`：

```python
"""Phase 1: per-profile trend/drift snapshot keying in export()."""
import pandas as pd
from unittest.mock import MagicMock, patch

from src.report.report_generator import ReportGenerator, ReportResult


def _result():
    df = pd.DataFrame([{
        "src_ip": "10.0.0.1", "dst_ip": "10.0.1.1", "src_app": "A", "dst_app": "B",
        "port": 443, "proto": "TCP", "num_connections": 3,
        "policy_decision": "allowed",
    }])
    return ReportResult(data_source="api", record_count=1,
                        module_results={"mod12": {"kpis": []}}, dataframe=df)


def _gen():
    cm = MagicMock()
    cm.config = {"settings": {}}
    return ReportGenerator(cm, api_client=None)


def _export(profile, tmp_path):
    gen = _gen()
    with patch("src.report.trend_store.load_previous", return_value=None) as lp, \
         patch("src.report.trend_store.save_snapshot") as ss, \
         patch("src.report.flow_history.load_previous_signatures",
               return_value=(None, None)) as ls, \
         patch("src.report.flow_history.save_signatures") as sv, \
         patch.object(gen, "_build_report_metadata", return_value={"kpis": [], "generated_at": ""}):
        gen.export(_result(), fmt="csv", output_dir=str(tmp_path),
                   traffic_report_profile=profile)
    return lp, ss, ls, sv


def test_security_risk_uses_profile_keyed_snapshots(tmp_path):
    lp, ss, ls, sv = _export("security_risk", tmp_path)
    assert lp.call_args.args[1] == "traffic_security_risk"
    assert ss.call_args.args[1] == "traffic_security_risk"
    assert ls.called and sv.called  # drift runs for security_risk


def test_traffic_profile_skips_drift(tmp_path):
    lp, ss, ls, sv = _export("traffic", tmp_path)
    assert lp.call_args.args[1] == "traffic_traffic"
    assert not ls.called and not sv.called  # no drift for traffic profile
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_traffic_report_trend_keying.py -v`
Expected: FAIL — 現行鍵是 `"traffic"` 且 drift 無條件執行

- [ ] **Step 3: Implement**

`export()` 內 trend/drift 區塊（line 470-489）改為：

```python
        try:
            from src.report.trend_store import save_snapshot, load_previous, compute_deltas, build_kpi_dict_from_metadata, canonicalize_legacy_keys
            _trend_key = f"traffic_{traffic_report_profile}"
            meta = self._build_report_metadata(result, file_format="snapshot")
            kpi_dict = build_kpi_dict_from_metadata(meta.get("kpis", []))
            ts = meta.get("generated_at", "")
            prev = load_previous(output_dir, _trend_key)
            prev = canonicalize_legacy_keys(prev, candidate_keys=list(kpi_dict.keys()))
            save_snapshot(output_dir, _trend_key, kpi_dict, generated_at=ts)
            if prev:
                result.module_results["_trend_deltas"] = compute_deltas(kpi_dict, prev)
            # Baseline drift is a security_risk-only section; other profiles
            # neither render nor archive flow signatures.
            if traffic_report_profile == "security_risk":
                from src.report.flow_history import build_signatures, load_previous_signatures, save_signatures
                from src.report.analysis.mod_drift import baseline_drift
                if result.dataframe is not None and not result.dataframe.empty:
                    _prev_sigs, _prev_ts = load_previous_signatures(output_dir, _trend_key)
                    result.module_results["mod_drift"] = baseline_drift(
                        result.dataframe, prev_signatures=_prev_sigs, prev_generated_at=_prev_ts)
                    save_signatures(output_dir, _trend_key, build_signatures(result.dataframe), generated_at=ts)
        except Exception as e:
            logger.warning(f"[ReportGenerator] Trend snapshot failed: {e}")
```

exporter 選擇（line 491-494）改為（`TrafficFlowsHtmlExporter` 於 Task 5 建立；先寫好選擇邏輯）：

```python
        if fmt in ('html', 'all', 'all_raw'):
            from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter
            _exporter_cls = {
                "network_inventory": NetworkInventoryHtmlExporter,
                "traffic": TrafficFlowsHtmlExporter,
            }.get(traffic_report_profile, SecurityRiskHtmlExporter)
```

（Task 5 完成前 `TrafficFlowsHtmlExporter` import 會失敗——本 task 測試只用 `fmt="csv"` 路徑，不觸發。為了讓中間狀態可 commit，Task 5 前先在 `html_exporter.py` 檔尾放最小 stub：

```python
class TrafficFlowsHtmlExporter(SecurityRiskHtmlExporter):
    """Placeholder until the dedicated traffic-flows exporter lands (Task 5)."""
```
）

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_traffic_report_trend_keying.py tests/ -k "trend or drift" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/report_generator.py src/report/exporters/html_exporter.py tests/test_traffic_report_trend_keying.py
git commit -m "feat(report): per-profile trend/drift snapshot keys, drift only for security_risk"
```

---

### Task 5: TrafficFlowsHtmlExporter

**Files:**
- Modify: `src/report/exporters/html_exporter.py`（base `export()` 檔名 hook、hero 第三分支、cover 分支、檔尾新 class 取代 Task 4 stub）
- Modify: `src/report/exporters/report_css.py:91`（badge CSS）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_traffic_flows_html_exporter.py`（新檔）

**Interfaces:**
- Consumes: Task 2 mod12 traffic 摘要（`kpis`、空 findings/posture）、Task 3 的 module_results。
- Produces: `TrafficFlowsHtmlExporter(results, profile="traffic", ...)`，`.export(output_dir)` 產 `Illumio_Traffic_Report_<YYYY-MM-DD_HHMM>.html`（無 profile 後綴）。章節順序 `['summary', 'overview', 'policy', 'distribution', 'bandwidth', 'unmanaged']`。

- [ ] **Step 1: Write the failing test**

建立 `tests/test_traffic_flows_html_exporter.py`：

```python
"""Phase 1: TrafficFlowsHtmlExporter output shape."""
import os
import re
import pandas as pd

from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter


def _results():
    df = pd.DataFrame([{"Port": 443, "Protocol": "TCP", "Flow Count": 10}])
    return {
        "findings": [],
        "mod01": {"total_flows": 10, "total_connections": 100,
                  "unique_src_ips": 2, "unique_dst_ips": 3,
                  "allowed_flows": 4, "blocked_flows": 1,
                  "potentially_blocked_flows": 5, "unknown_flows": 0,
                  "total_bytes": 0, "total_mb": 1.0,
                  "policy_coverage_pct": 40.0,
                  "src_managed_pct": 100.0, "dst_managed_pct": 50.0,
                  "date_range": "2026-04-27 ~ 2026-05-04",
                  "top_ports": df, "top_protocols": df},
        "mod02": {"summary": df, "chart_spec": None},
        "mod08": {"unmanaged_flow_count": 3, "unmanaged_pct": 30.0,
                  "unique_unmanaged_src": 1, "unique_unmanaged_dst": 1,
                  "top_unmanaged_src": df},
        "mod09": {"label_distribution": {"src_app": df, "dst_app": df,
                                         "src_env": df, "dst_env": df,
                                         "src_role": df, "dst_role": df},
                  "port_distribution": df, "proto_distribution": df},
        "mod11": {"bytes_data_available": True, "total_mb": 1.0,
                  "top_by_bytes": df, "top_bandwidth": df,
                  "byte_ratio_anomalies": df, "anomaly_threshold": 1.0},
        "mod12": {"generated_at": "2026-07-02 12:00:00", "kpis": [],
                  "findings_summary": {}, "total_findings": 0,
                  "key_findings": [], "findings": [],
                  "boundary_breaches": [], "suspicious_pivot_behavior": [],
                  "blast_radius": [], "blind_spots": [], "action_matrix": []},
    }


def _export(tmp_path, lang="en"):
    exp = TrafficFlowsHtmlExporter(_results(), data_source="api", lang=lang)
    return exp.export(str(tmp_path))


def test_filename_has_no_profile_suffix(tmp_path):
    path = _export(tmp_path)
    name = os.path.basename(path)
    assert re.fullmatch(r"Illumio_Traffic_Report_\d{4}-\d{2}-\d{2}_\d{4}\.html", name), name


def test_no_security_content(tmp_path):
    html = open(_export(tmp_path), encoding="utf-8").read()
    for banned in ("Maturity", "Lateral", "Ransomware", "Readiness",
                   "Infrastructure Scoring", "Attack"):
        assert banned not in html, banned


def test_sections_and_pdf_button_present(tmp_path):
    html = open(_export(tmp_path), encoding="utf-8").read()
    for anchor in ('id="summary"', 'id="overview"', 'id="policy"',
                   'id="distribution"', 'id="bandwidth"', 'id="unmanaged"'):
        assert anchor in html, anchor
    assert "window.print()" in html  # PDF export button (spec N)


def test_role_loc_dimensions_not_rendered(tmp_path):
    html = open(_export(tmp_path), encoding="utf-8").read()
    assert "Src Role" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_traffic_flows_html_exporter.py -v`
Expected: FAIL — stub 繼承 SecurityRisk（檔名帶 SecurityRisk、含 Maturity 等字串）

- [ ] **Step 3: base class 檔名與 hero hooks**

`_TrafficReportBase.export()`（line 429-434）的檔名組裝抽成 hook。將

```python
        filename = f'Illumio_Traffic_Report_{self.REPORT_KIND or "SecurityRisk"}_{ts}.html'
```

改為 `filename = self._filename(ts)`，並在 base class 加：

```python
    def _filename(self, ts: str) -> str:
        return f'Illumio_Traffic_Report_{self.REPORT_KIND or "SecurityRisk"}_{ts}.html'

    def _hero_includes_findings(self) -> bool:
        """Whether the hero card renders key-findings + attack summary."""
        return True
```

hero 組裝（line 620-631）：badge 與標題改三分支、findings 區塊依 hook。將原本的 badge 三元運算與 `+ f'<h2>{_s("rpt_key_findings")}</h2>' + key_findings_html + attack_summary_html` 改為：

```python
        _badge_html = {
            "SecurityRisk": f'<div class="report-profile-badge report-profile-badge--security">{_s("rpt_kicker_security_risk")}</div>',
            "NetworkInventory": f'<div class="report-profile-badge report-profile-badge--inventory">{_s("rpt_kicker_network_inventory")}</div>',
            "Traffic": f'<div class="report-profile-badge report-profile-badge--traffic">{_s("rpt_kicker_traffic_flows")}</div>',
        }[self.REPORT_KIND or "SecurityRisk"]
        _title_key = {
            "SecurityRisk": "rpt_security_report_title",
            "NetworkInventory": "rpt_inventory_report_title",
            "Traffic": "rpt_traffic_flows_report_title",
        }[self.REPORT_KIND or "SecurityRisk"]
        _findings_block = ((f'<h2>{_s("rpt_key_findings")}</h2>' + key_findings_html
                            + attack_summary_html)
                           if self._hero_includes_findings() else '')
        _hero = (
            '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            f'<div class="report-kicker">{_s("rpt_kicker_traffic")}</div>'
            + _badge_html
            + f'<h1>{_s(_title_key)}</h1>'
            f'<p class="report-subtitle">{_s("rpt_generated")} ' + generated_at + '</p></div>'
            + summary_pills + _maturity_block + trend_html
            + _findings_block + '</section>\n'
        )
```

cover 分支（line 689 起）加 elif：

```python
        if self._profile == "network_inventory":
            _report_title = t("rpt_cover_type_inventory", lang=self._lang)
            ...
        elif self._profile == "traffic":
            _report_title = t("rpt_cover_type_traffic", lang=self._lang)
            cover_html = _build_cover_page(
                title=_report_title,
                report_type=_report_title,
                date_range=self._date_range,
                pce_url=self._pce_url,
                org_name=self._org_name,
                lang=self._lang,
            )
        else:
            ...（原內容不動）...
```

- [ ] **Step 4: 實作 TrafficFlowsHtmlExporter（取代 Task 4 stub）**

`html_exporter.py` 檔尾（`HtmlExporter` shim 之後）：

```python
class TrafficFlowsHtmlExporter(_TrafficReportBase):
    """Plain traffic-facts report: no scoring, no security analysis (spec A)."""

    REPORT_KIND = "Traffic"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("profile", "traffic")
        super().__init__(*args, **kwargs)

    def _include_maturity(self) -> bool:
        return False

    def _hero_includes_findings(self) -> bool:
        return False

    def _filename(self, ts: str) -> str:
        return f'Illumio_Traffic_Report_{ts}.html'

    def _ordered_section_keys(self) -> list[str]:
        return ['summary', 'overview', 'policy', 'distribution', 'bandwidth', 'unmanaged']

    def _mod02_html(self):
        # Summary table + decision chart only — no per-decision app-flow detail.
        _lang = self._lang
        m = self._r.get('mod02', {}) or {}
        chart_html = _render_chart_for_html(m.get('chart_spec'), lang=_lang)
        table_html = self._subnote('rpt_tr_mod02_intro') + _df_to_html(m.get('summary'), lang=_lang)
        return ('<div class="section-top">' + chart_html + '</div>'
                + '<div class="section-bottom">' + table_html + '</div>')

    def _mod09_html(self):
        # App / Env distribution only (role/loc are inventory concerns).
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod09', {}) or {}
        dist = m.get('label_distribution', {}) or {}
        out = ''
        for key in ('app', 'env'):
            for side in ('src', 'dst'):
                d = dist.get(f'{side}_{key}')
                if d is not None and hasattr(d, 'empty') and not d.empty:
                    out += _df_to_html(d, lang=_lang)
        pd_ = m.get('port_distribution')
        if pd_ is not None and hasattr(pd_, 'empty') and not pd_.empty:
            out += f'<h3>{_s("rpt_tr_port_distribution")}</h3>' + _df_to_html(pd_, lang=_lang)
        proto = m.get('proto_distribution')
        if proto is not None and hasattr(proto, 'empty') and not proto.empty:
            out += f'<h3>{_s("rpt_tr_proto_distribution")}</h3>' + _df_to_html(proto, lang=_lang)
        return out

    def _mod08_html(self):
        # Unmanaged overview: KPI strip + top sources table only.
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod08', {}) or {}
        return (
            '<div class="coverage-grid">'
            + _cov_stat(_s('rpt_tr_unmanaged_flow_stat'), str(m.get('unmanaged_flow_count', 0)) + ' (' + str(m.get('unmanaged_pct', 0)) + '%)')
            + _cov_stat(_s('rpt_tr_unique_unmanaged_src'), str(m.get('unique_unmanaged_src', 0)))
            + _cov_stat(_s('rpt_tr_unique_unmanaged_dst'), str(m.get('unique_unmanaged_dst', 0)))
            + '</div>'
            + self._subnote('rpt_tr_unmanaged_subnote')
            + f'<h3>{_s("rpt_tr_top_unmanaged")}</h3>'
            + _df_to_html(m.get('top_unmanaged_src'), lang=_lang)
        )
```

（`rpt_tr_port_distribution` / `rpt_tr_proto_distribution` 若 i18n 檔已存在則沿用；不存在則在 Step 5 一併加。以 `grep '"rpt_tr_port_distribution"' src/i18n_en.json` 確認。）

- [ ] **Step 5: i18n keys 與 badge CSS**

`src/i18n_en.json`：

```json
"rpt_kicker_traffic_flows": "Traffic Report",
"rpt_traffic_flows_report_title": "Illumio Traffic Flow Report",
"rpt_cover_type_traffic": "Traffic Report",
```

`src/i18n_zh_TW.json`：

```json
"rpt_kicker_traffic_flows": "流量報表",
"rpt_traffic_flows_report_title": "Illumio 網路流量報表",
"rpt_cover_type_traffic": "流量報表",
```

`src/report/exporters/report_css.py` 在 `--inventory` badge（line 91）後加：

```css
.report-profile-badge--traffic { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_traffic_flows_html_exporter.py tests/test_traffic_report_trend_keying.py -v`
Expected: PASS

- [ ] **Step 7: 既有 exporter 測試不破壞**

Run: `venv/bin/python -m pytest tests/ -k "exporter or html" -q`
Expected: PASS（hero 重構後 SecurityRisk / NetworkInventory 輸出不變）

- [ ] **Step 8: Commit**

```bash
git add src/report/exporters/html_exporter.py src/report/exporters/report_css.py src/i18n_en.json src/i18n_zh_TW.json tests/test_traffic_flows_html_exporter.py
git commit -m "feat(report): TrafficFlowsHtmlExporter for the plain traffic profile"
```

---

### Task 6: CLI / 排程 / GUI 接線

**Files:**
- Modify: `src/cli/report.py`（`generate_traffic_report:88`、`report_traffic:268` 與 `--profile` option）
- Modify: `src/report_scheduler.py:310-335`（bare `traffic` 分支）
- Modify: `src/gui/routes/reports.py:302`（`_VALID_PROFILES`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（deprecation 訊息）
- Test: `tests/test_cli_report_traffic_profile.py`（新檔）；Modify: `tests/test_cli_report_commands.py`（若其斷言 traffic 預設 security_risk）

**Interfaces:**
- Consumes: Task 3/4/5 的 traffic profile 路徑。
- Produces: `report traffic`（無 `--profile`）→ `traffic_report_profile="traffic"`；`--profile security_risk|network_inventory` → 印 `cli_report_profile_deprecated` 到 stderr 後沿用原行為。scheduler `report_type == "traffic"` 明確傳 `traffic_report_profile="traffic"`。

- [ ] **Step 1: Write the failing test**

建立 `tests/test_cli_report_traffic_profile.py`：

```python
"""Phase 1: report traffic CLI produces the new traffic profile."""
from unittest.mock import patch
from click.testing import CliRunner

from src.cli.root import cli


def _invoke(args):
    runner = CliRunner()
    with patch("src.cli.report.generate_traffic_report", return_value=["/tmp/x.html"]) as gen:
        result = runner.invoke(cli, args)
    return result, gen


def test_bare_traffic_uses_traffic_profile():
    result, gen = _invoke(["report", "traffic"])
    assert result.exit_code == 0
    assert gen.call_args.kwargs["traffic_report_profile"] == "traffic"


def test_profile_flag_is_deprecated_but_honored():
    result, gen = _invoke(["report", "traffic", "--profile", "security_risk"])
    assert result.exit_code == 0
    assert gen.call_args.kwargs["traffic_report_profile"] == "security_risk"
    assert "deprecat" in (result.stderr or result.output).lower()


def test_security_command_unchanged():
    runner = CliRunner()
    with patch("src.cli.report.generate_traffic_report", return_value=["/tmp/x.html"]) as gen:
        result = runner.invoke(cli, ["report", "security"])
    assert result.exit_code == 0
    assert gen.call_args.kwargs["traffic_report_profile"] == "security_risk"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_cli_report_traffic_profile.py -v`
Expected: FAIL — bare traffic 目前預設 security_risk 且無 deprecation 訊息

- [ ] **Step 3: Implement CLI**

(a) `report_traffic` command 的 `--profile` option：default 改 `None`（原 `default="security_risk"`），help 註明 deprecated：

```python
@click.option(
    "--profile", "traffic_report_profile",
    type=click.Choice(_TRAFFIC_PROFILES), default=None,
    help="(deprecated) use `report security` / `report inventory` instead.",
)
```

(b) `report_traffic` 函式體開頭：

```python
    if traffic_report_profile is None:
        traffic_report_profile = "traffic"
    else:
        click.echo(t("cli_report_profile_deprecated", lang=_ctx_lang()), err=True)
```

之後照原樣把 `traffic_report_profile` 傳給 `generate_traffic_report`。

(c) `generate_traffic_report` 函式簽名的 default 保持 `"security_risk"`（`security`/`inventory` wrapper 顯式傳入，不受影響）。

(d) i18n：

`src/i18n_en.json`：
```json
"cli_report_profile_deprecated": "--profile is deprecated: use `report security` or `report inventory`. This run keeps the requested profile.",
```
`src/i18n_zh_TW.json`：
```json
"cli_report_profile_deprecated": "--profile 已棄用：請改用 `report security` 或 `report inventory`。本次仍以指定的 profile 產生。",
```

- [ ] **Step 4: Implement scheduler + GUI**

(a) `src/report_scheduler.py` `_generate_report` 的 `report_type == "traffic"` 分支，`generate_from_api` 與 `export` 都明確帶 profile：

```python
            result = gen.generate_from_api(start_date=start_date, end_date=end_date,
                                           filters=filters, lang=lang,
                                           traffic_report_profile="traffic")
            ...
            paths = gen.export(result, fmt=fmt, output_dir=output_dir,
                               send_email=False, reporter=None,
                               traffic_report_profile="traffic")
```

(b) `src/gui/routes/reports.py:302`：

```python
        _VALID_PROFILES = ("traffic", "security_risk", "network_inventory")
```

（GUI 前端 UI 選項不在本 Phase；伺服端先接受該值。GUI 預設值 `security_risk` 不變。）

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_cli_report_traffic_profile.py tests/test_cli_report_commands.py tests/test_cli_report_verb_aliases.py tests/test_cli_report_data_source.py -v`
Expected: PASS（若 `test_cli_report_commands.py` 斷言 bare traffic 為 security_risk，改斷言為 traffic）

- [ ] **Step 6: Commit**

```bash
git add src/cli/report.py src/report_scheduler.py src/gui/routes/reports.py src/i18n_en.json src/i18n_zh_TW.json tests/test_cli_report_traffic_profile.py tests/test_cli_report_commands.py
git commit -m "feat(cli): report traffic produces the plain traffic profile, --profile deprecated"
```

---

### Task 7: 端對端驗證、CHANGELOG、文件

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`、`README_zh.md`（報表清單段落）
- Modify: `docs/`（operations manual 英/中對應報表章節；以 `grep -rl "security_risk" docs/` 定位）

- [ ] **Step 1: 全套測試**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: 全綠

- [ ] **Step 2: 實際產生三份報表煙霧測試**

```bash
venv/bin/python illumio-ops.py report traffic --data-source cache-only --output-dir /tmp/phase1-smoke
venv/bin/python illumio-ops.py report security --data-source cache-only --output-dir /tmp/phase1-smoke
venv/bin/python illumio-ops.py report inventory --data-source cache-only --output-dir /tmp/phase1-smoke
ls /tmp/phase1-smoke
```

Expected：三個 HTML，traffic 檔名無 profile 後綴；用瀏覽器或 grep 檢查 traffic 報表無「成熟度/橫向移動/勒索」章節、有列印按鈕。
（注意：本機快取資料在 2026-04-27 ~ 2026-05-04；如 cache-only 無資料，煙霧測試需先確認快取視窗，或以 `--data-source hybrid` 對 lab PCE 執行。）

- [ ] **Step 3: CHANGELOG 與文件**

`CHANGELOG.md` Unreleased 段加：

```markdown
### Changed
- `report traffic` now generates the new plain Traffic Flow Report (traffic facts only,
  no security scoring). Use `report security` / `report inventory` for the previous
  outputs; `--profile` on `report traffic` is deprecated.
- Trend and baseline-drift snapshots are now keyed per report profile
  (`traffic_security_risk`, `traffic_network_inventory`, `traffic_traffic`).
  The first run after upgrading has no previous baseline to compare against.

### Added
- Plain Traffic Flow Report profile (`traffic`): overview, policy decision summary,
  app/env distribution, bandwidth, unmanaged overview. Runs only lightweight modules.
```

README / operations manual：報表清單加「Traffic Flow Report（純流量事實）」一列並註明三種 profile 對應的命令。英文與中文檔都要改。

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md README.md README_zh.md docs/
git commit -m "docs: document traffic report split and per-profile snapshots"
```

---

## Self-Review 檢核

1. **Spec 覆蓋**：A（新 profile 六章 → Task 1/2/3/5）、D（profile 感知執行 → Task 1/3）、E（CLI/排程/檔名/快照分離 → Task 4/6）。B/C/F/I/J/K/L 屬 Phase 2-6，不在本計畫。
2. **既有行為保護**：security/inventory 模組集合 Phase 1 不變（Task 1 測試鎖定全集）；hero 重構有既有 exporter 測試回歸（Task 5 Step 7）。
3. **型別一致**：`get_traffic_modules(profile)`（Task 1）↔ `_run_modules` 呼叫（Task 3）；`TrafficFlowsHtmlExporter`（Task 5）↔ export 選擇（Task 4）；`traffic_report_profile="traffic"` 貫穿 CLI/scheduler（Task 6）。
