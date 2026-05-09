# Render-Layer i18n Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate the ~62 hardcoded English strings still appearing in zh_TW HTML reports — `Tier-1 Critical`, `Identity` / `Provider` / `Bridge` role labels, severity tokens, and DataFrame column headers — without breaking the source modules whose dict keys / groupby keys / column references depend on those exact stable strings.

**Architecture:** Extend the existing report-layer i18n machinery (`src/report/exporters/report_i18n.py:STRINGS` + auto-derived `COL_I18N` + `src/report/exporters/table_renderer.py:render_df_table`) instead of mutating analysis-module DataFrames. Two extensions: (1) `render_df_table` gains a `value_i18n_maps` parameter that translates specific cell values via stable→key lookup; (2) `report_i18n.py` exposes reusable value maps (`TIER_VALUE_I18N`, `ROLE_VALUE_I18N`, etc.) and adds the missing column-name STRINGS entries. Analysis modules under `src/report/analysis/mod*.py` remain untouched — translation happens at the exporter boundary in `src/report/exporters/html_exporter.py`.

**Tech Stack:** Python 3.10+, pandas DataFrames, the project's existing i18n loader (`src/i18n` returns lang-aware values; `src/report/exporters/report_i18n.py:_StringMap` mirrors the same shape for HTML rendering).

---

## Scope Note

This plan covers exactly the items deferred from Batch 6 commit `7db8f9d`:

- mod14 `_classify_tier` returns 4 Tier labels used as DataFrame column values
- mod14 `role` / `asset_type` labels (Identity, Database, Provider, Consumer, Bridge, Peer; Identity Infrastructure, Database)
- mod14 `edge_df` column headers (`Source App (Env)`, `Source App Env Key`, `Destination App (Env)`, `Destination App Env Key`, `Connections`)
- mod13 `_severity` returns (CRITICAL / HIGH / MEDIUM / LOW / INFO) used as DataFrame value AND priority lookup key
- mod13 default DataFrame columns (`Priority`, `App (Env)`, `App Env Key`, `Issue`, `Action`, `Action Code`, `Severity`)
- mod12 `dim_labels` (Enforcement Coverage / Policy Coverage / Lateral Control / Managed Asset Ratio / Risk Port Control) used as chart bar labels
- mod12 inserted KPI label "Maturity Score" — STRINGS already has `rpt_tr_maturity_score`
- html_exporter mod01 summary metric/value rows (Policy Coverage / Allowed/Blocked/Potentially Blocked / Total Data / Date Range)
- html_exporter readiness factor table rename (Factor / Weight / Score / Ratio %)
- html_exporter app_env_scores rename (10 column headers)
- html_exporter recommendations rename (5 column headers)

Out of scope (separate plans / declined by user):
- chart titles already keyed via `*_key` (Batch 7 already activated for `render_plotly_html`)
- mod14 `_classify_tier` source change (stays English by design)
- glossary-protected tokens (Allowed / Blocked / Potentially Blocked / Manage / Unmanage / VEN / PCE / App / Label / Ringfence / Policy)

---

## Glossary Policy (Harry's reminder 2026-05-09)

These tokens **must remain English** in zh_TW values:

- `Allowed`, `Blocked`, `Potentially Blocked` (audit `[E]` enforces)
- `Manage`, `Unmanage`, `Managed`, `Unmanaged`
- `VEN`, `PCE`, `App`, `Label`, `Illumio`, `PCE Ops`
- `Policy`, `Ringfence` (Ringfence already established as "應用程式 Ringfence")
- `Port`, `Service`, `Hostname` (audit `[E]` enforces)
- `HTTPS`, `TLS`, `SSL`, `HTTP`, `TCP`, `UDP`
- `HTML`, `PDF`, `Excel`, `JSON`, `CSV`, `API`, `URL`, `IP`
- Placeholder tokens (`{exc}`, `{count}`, etc.)

These are **translatable** in this plan:

- `Identity` → 身分, `Database` → 資料庫, `Provider` → 提供者, `Consumer` → 消費者, `Bridge` → 橋接器, `Peer` → 對等
- `Critical` → 重大, `Important` → 重要, `Shared` → 共用, `Peripheral` → 邊緣
- `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` / `INFO` — translated to 嚴重 / 高 / 中 / 低 / 資訊 (severity badges; if user objects after seeing visual, single revert via STRINGS edit)
- column words: `Issue` → 問題, `Action` → 建議動作, `Connections` → 連線數, `Source` → 來源, `Destination` → 目的, `Factor` → 因素, `Weight` → 權重, `Score` → 分數, `Ratio` → 比例, `Grade` → 等級, `Flows` → 流量數, `Readiness` → 就緒度, `Coverage` → 覆蓋率, `Maturity` → 成熟度

Tier label hybrid: keep English part + add zh suffix:
- `Tier-1 Critical` → `Tier-1 重大`
- `Tier-2 Important` → `Tier-2 重要`
- `Tier-3 Shared` → `Tier-3 共用`
- `Tier-4 Peripheral` → `Tier-4 邊緣`

---

## File Structure

**Modified:**
- `src/report/exporters/table_renderer.py` — extend `render_df_table` with `value_i18n_maps` parameter (~30 lines added)
- `src/report/exporters/report_i18n.py` — add ~30 new `rpt_col_*`, `rpt_tier_*`, `rpt_role_*`, `rpt_severity_*`, `rpt_asset_type_*` STRINGS entries; expose `TIER_VALUE_I18N`, `ROLE_VALUE_I18N`, `SEVERITY_VALUE_I18N`, `ASSET_TYPE_VALUE_I18N`, `MOD01_METRIC_VALUE_I18N` constants
- `src/report/exporters/html_exporter.py` — `_mod14_html`, `_mod13_html`, `_mod12_html`, mod01 summary table site each gain 1-3 lines: `value_i18n_maps={...}` argument when calling `render_df_table`, plus chart title/label_key swaps where applicable

**Created:**
- `tests/test_render_layer_i18n.py` — unit tests for `value_i18n_maps` plumbing + integration tests asserting zh_TW HTML reports show translated Tier/role/severity/columns

No source under `src/report/analysis/mod*.py` is modified. That is the architectural commitment.

---

## Pre-flight Checklist (run once before starting)

- [ ] Verify clean working tree: `git status` → "clean"
- [ ] Verify on `main` and up-to-date: `git pull --ff-only`
- [ ] Verify baseline green: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -3` → `974 passed, 1 skipped`
- [ ] Verify audit baseline: `PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3` → `Total: 0 finding(s)`
- [ ] Verify mypy gate: `PYTHONPATH=... venv/bin/python3 -m mypy src/api_client.py src/analyzer.py src/reporter.py 2>&1 | tail -2` → `Success`
- [ ] Create branch (optional — `main` direct commits is also acceptable per project convention): `git checkout -b render-layer-i18n` or stay on `main`

---

## Task 1: Extend `render_df_table` with `value_i18n_maps`

**Why:** The existing `render_df_table` translates column headers via `col_i18n: dict[str, str]` and renders raw cell values verbatim. We need cell-level translation for stable English values like `Tier-1 Critical`, `CRITICAL`, `Identity` without making every caller write a `render_cell` callback.

**Files:**
- Modify: `src/report/exporters/table_renderer.py`
- Test: `tests/test_render_layer_i18n.py` (new)

- [ ] **Step 1: Read the current signature**

```bash
sed -n '33,50p' src/report/exporters/table_renderer.py
```

Confirm signature is:
```python
def render_df_table(
    df,
    *,
    col_i18n: dict[str, str],
    no_data_key: str = "rpt_no_data",
    render_cell: Callable | None = None,
    row_attrs: Callable | None = None,
    lang: str = "en",
) -> str:
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_render_layer_i18n.py`:

```python
"""Render-layer i18n: cell value translation in render_df_table."""
from __future__ import annotations

import pandas as pd

from src.report.exporters.report_i18n import STRINGS
from src.report.exporters.table_renderer import render_df_table


def test_value_i18n_maps_translates_zh_cell():
    """Stable English cell values resolve via i18n key in zh_TW."""
    STRINGS["rpt_test_tier_1"] = {"en": "Tier-1 Critical", "zh_TW": "Tier-1 重大"}
    df = pd.DataFrame({"Tier": ["Tier-1 Critical"]})
    html = render_df_table(
        df,
        col_i18n={},
        value_i18n_maps={"Tier": {"Tier-1 Critical": "rpt_test_tier_1"}},
        lang="zh_TW",
    )
    assert "Tier-1 重大" in html
    assert "Tier-1 Critical" not in html


def test_value_i18n_maps_passthrough_on_unknown_value():
    """Cell values not in the map render as-is (stable behavior for new enums)."""
    df = pd.DataFrame({"Tier": ["Tier-99 Unknown"]})
    html = render_df_table(
        df,
        col_i18n={},
        value_i18n_maps={"Tier": {"Tier-1 Critical": "rpt_test_tier_1"}},
        lang="zh_TW",
    )
    assert "Tier-99 Unknown" in html


def test_value_i18n_maps_falls_back_to_en_when_zh_missing():
    """If STRINGS entry has no zh_TW value, en value renders (matches existing col_i18n behavior)."""
    STRINGS["rpt_test_only_en"] = {"en": "Identity", "zh_TW": ""}
    df = pd.DataFrame({"Role": ["Identity"]})
    html = render_df_table(
        df,
        col_i18n={},
        value_i18n_maps={"Role": {"Identity": "rpt_test_only_en"}},
        lang="zh_TW",
    )
    assert "Identity" in html


def test_value_i18n_maps_does_not_affect_other_columns():
    """Translation only applies to columns listed in value_i18n_maps."""
    STRINGS["rpt_test_role_id"] = {"en": "Identity", "zh_TW": "身分"}
    df = pd.DataFrame({
        "Role": ["Identity"],
        "Other": ["Identity"],
    })
    html = render_df_table(
        df,
        col_i18n={},
        value_i18n_maps={"Role": {"Identity": "rpt_test_role_id"}},
        lang="zh_TW",
    )
    # Role column localized; Other column passthrough
    assert html.count("身分") == 1
    assert html.count("Identity") == 1


def test_value_i18n_maps_optional_argument():
    """Existing callers (no value_i18n_maps) keep working — backwards compat."""
    df = pd.DataFrame({"x": [1]})
    html = render_df_table(df, col_i18n={}, lang="en")
    assert "<table" in html
```

- [ ] **Step 3: Run test to verify it fails**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_render_layer_i18n.py -v --timeout=60
```

Expected: FAIL — `render_df_table() got an unexpected keyword argument 'value_i18n_maps'`

- [ ] **Step 4: Implement the parameter**

Read `src/report/exporters/table_renderer.py` around the function definition and the row-rendering loop (the `for _, row in df.iterrows():` block).

In the signature, add `value_i18n_maps: dict[str, dict[str, str]] | None = None,` after `render_cell`. In the cell-rendering loop, before `render_cell` is called, intercept:

```python
    # ... in the for col in columns: loop, replace the existing cell rendering line:
    for col in columns:
        raw_value = row[col]
        # Render-layer i18n: translate stable English value via map (if provided)
        # before custom render_cell or default rendering. Pass-through on miss.
        if value_i18n_maps and col in value_i18n_maps:
            key = value_i18n_maps[col].get(str(raw_value))
            if key:
                entry = _STRINGS.get(key)
                if entry:
                    translated = entry.get(lang) or entry.get("en") or str(raw_value)
                    if translated:
                        raw_value = translated
        cell_html = render_cell(col, raw_value, row) if render_cell else _default_cell(raw_value)
        html_parts.append(f"<td>{cell_html}</td>")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_render_layer_i18n.py -v --timeout=60
```

Expected: 5 passed

- [ ] **Step 6: Run full pytest to confirm no regression**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -3
```

Expected: `979 passed, 1 skipped` (974 baseline + 5 new tests)

- [ ] **Step 7: Commit**

```bash
git add src/report/exporters/table_renderer.py tests/test_render_layer_i18n.py
git commit -m "feat(report): render_df_table accepts value_i18n_maps for cell translation

Adds optional value_i18n_maps={col: {stable_value: i18n_key}} kwarg that
translates DataFrame cell values at render time via STRINGS lookup —
matching the existing col_i18n pattern for column headers. Pass-through
on unknown values; backwards compatible (default None).

Used by upcoming Tasks 4-7 to translate Tier/role/severity labels in
mod13/14 HTML output without mutating mod*.py source modules.

Tests: 5 new in tests/test_render_layer_i18n.py covering zh translation,
unknown-value pass-through, en fallback when zh missing, scope isolation
to listed columns, and backwards-compat default.
"
```

---

## Task 2: Add column STRINGS entries for new HTML report columns

**Why:** mod13 / mod14 / readiness / app_env_scores tables surface column names that don't yet exist as `rpt_col_*` STRINGS entries. Adding them populates the auto-derived `COL_I18N` so existing `render_df_table` calls (which pass `col_i18n=_COL_I18N`) translate the headers automatically.

**Files:**
- Modify: `src/report/exporters/report_i18n.py`

- [ ] **Step 1: Locate the existing `rpt_col_*` cluster**

```bash
grep -n '"rpt_col_' src/report/exporters/report_i18n.py | head -10
```

Use one of the existing entries as the insertion point (e.g. above `rpt_col_uncovered_flows` at line ~67).

- [ ] **Step 2: Add the new STRINGS entries**

Append into the `STRINGS = _StringMap({...})` dict (alphabetical insertion preferred but not required — `_StringMap` is plain dict, audit doesn't enforce order):

```python
    "rpt_col_action": _entry("Action", "建議動作"),
    "rpt_col_action_code": _entry("Action Code", "動作代碼"),
    "rpt_col_app_env": _entry("App (Env)", "App (Env)"),
    "rpt_col_app_env_key": _entry("App Env Key", "App Env Key"),
    "rpt_col_connections": _entry("Connections", "連線數"),
    "rpt_col_destination_app_env": _entry("Destination App (Env)", "目的 App (Env)"),
    "rpt_col_destination_app_env_key": _entry("Destination App Env Key", "目的 App Env Key"),
    "rpt_col_enforcement_pct": _entry("Enforcement Mode %", "Enforcement Mode %"),
    "rpt_col_factor": _entry("Factor", "因素"),
    "rpt_col_flows": _entry("Flows", "Flows"),
    "rpt_col_grade": _entry("Grade", "等級"),
    "rpt_col_issue": _entry("Issue", "問題"),
    "rpt_col_metric": _entry("Metric", "指標"),
    "rpt_col_policy_coverage_pct": _entry("Policy Coverage %", "Policy 覆蓋率 %"),
    "rpt_col_priority": _entry("Priority", "優先順序"),
    "rpt_col_ratio_pct": _entry("Ratio %", "比例 %"),
    "rpt_col_readiness_score": _entry("Readiness Score", "就緒分數"),
    "rpt_col_remote_pct": _entry("Remote-App Coverage %", "遠端 App 覆蓋率 %"),
    "rpt_col_ringfence_pct": _entry("Ringfence Maturity %", "Ringfence 成熟度 %"),
    "rpt_col_score": _entry("Score", "分數"),
    "rpt_col_severity": _entry("Severity", "嚴重度"),
    "rpt_col_source_app_env": _entry("Source App (Env)", "來源 App (Env)"),
    "rpt_col_source_app_env_key": _entry("Source App Env Key", "來源 App Env Key"),
    "rpt_col_staged_pct": _entry("Staged Readiness %", "Staged 就緒度 %"),
    "rpt_col_value": _entry("Value", "數值"),
    "rpt_col_weight": _entry("Weight", "權重"),
```

Note: `App (Env)` / `App Env Key` / `Flows` / `Enforcement Mode %` keep the brand/glossary tokens English in both en and zh per the policy.

- [ ] **Step 3: Verify COL_I18N picks them up**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -c "
from src.report.exporters.report_i18n import COL_I18N
expected = ['App (Env)', 'Source App (Env)', 'Connections', 'Issue', 'Action',
            'Severity', 'Priority', 'Factor', 'Weight', 'Score', 'Ratio %',
            'Readiness Score', 'Policy Coverage %', 'Ringfence Maturity %',
            'Enforcement Mode %', 'Staged Readiness %', 'Remote-App Coverage %',
            'Flows', 'Grade', 'Action Code', 'App Env Key',
            'Source App Env Key', 'Destination App (Env)',
            'Destination App Env Key', 'Metric', 'Value']
missing = [c for c in expected if c not in COL_I18N]
print('missing:', missing)
assert not missing, missing
print(f'OK — COL_I18N gained {len(expected)} entries')
"
```

Expected: `OK — COL_I18N gained 26 entries`

- [ ] **Step 4: Run audit (no glossary [E] should fire)**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3
```

Expected: `Total: 0 finding(s)`. If `[E]` fires for `rpt_col_severity` (Severity → 嚴重度), check the glossary policy in this plan and either accept the translation or revert that single entry to keep "Severity" English (audit will then pass).

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/report_i18n.py
git commit -m "i18n(report): add 26 rpt_col_* entries for mod13/14/readiness HTML

The auto-derived COL_I18N picks these up, so any existing render_df_table
call already passing col_i18n=_COL_I18N will start translating these
columns without further changes — mod13 / mod14 / readiness / app_env
tables included.

Glossary policy honoured (Harry's reminder 2026-05-09): App (Env), App
Env Key, Flows, Enforcement Mode %, Source/Destination App (Env), Ringfence
kept English in zh_TW values; Issue/Action/Connections/Factor/Weight/etc.
translated.
"
```

---

## Task 3: Add value-level i18n constants + STRINGS entries

**Why:** Cell values like `Tier-1 Critical`, `Identity`, `CRITICAL` need stable→key maps that callers can pass to `render_df_table(value_i18n_maps=...)`. Defining them once in `report_i18n.py` lets every exporter reuse the same mapping.

**Files:**
- Modify: `src/report/exporters/report_i18n.py`

- [ ] **Step 1: Add tier/role/severity/asset-type STRINGS entries**

In the same `STRINGS = _StringMap({...})` dict:

```python
    # Tier classification (mod14 _classify_tier returns these as DataFrame column values)
    "rpt_tier_1_critical": _entry("Tier-1 Critical", "Tier-1 重大"),
    "rpt_tier_2_important": _entry("Tier-2 Important", "Tier-2 重要"),
    "rpt_tier_3_shared": _entry("Tier-3 Shared", "Tier-3 共用"),
    "rpt_tier_4_peripheral": _entry("Tier-4 Peripheral", "Tier-4 邊緣"),
    # Role labels (mod14 role column)
    "rpt_role_identity": _entry("Identity", "身分"),
    "rpt_role_database": _entry("Database", "資料庫"),
    "rpt_role_provider": _entry("Provider", "提供者"),
    "rpt_role_consumer": _entry("Consumer", "消費者"),
    "rpt_role_bridge": _entry("Bridge", "橋接器"),
    "rpt_role_peer": _entry("Peer", "對等"),
    # Asset type labels (mod14 asset_type column — NOTE: empty-string is also a valid value)
    "rpt_asset_type_identity_infra": _entry("Identity Infrastructure", "身分基礎架構"),
    "rpt_asset_type_database": _entry("Database", "資料庫"),
    # Severity labels (mod13 _severity returns; also priority lookup key)
    "rpt_severity_critical": _entry("CRITICAL", "嚴重"),
    "rpt_severity_high": _entry("HIGH", "高"),
    "rpt_severity_medium": _entry("MEDIUM", "中"),
    "rpt_severity_low": _entry("LOW", "低"),
    "rpt_severity_info": _entry("INFO", "資訊"),
    # mod01 metric/value rows (visible in HTML traffic report mod01 section)
    "rpt_metric_policy_coverage": _entry("Policy Coverage", "Policy 覆蓋率"),
    "rpt_metric_allowed_blocked_potential": _entry("Allowed / Blocked / Potentially Blocked", "Allowed / Blocked / Potentially Blocked"),
    "rpt_metric_total_data": _entry("Total Data", "總資料量"),
    "rpt_metric_date_range": _entry("Date Range", "日期範圍"),
```

Note: `rpt_metric_allowed_blocked_potential` zh value preserves the glossary tokens verbatim — the metric label IS the three terms.

- [ ] **Step 2: Add reusable value maps (constants for callers)**

Append at the bottom of `report_i18n.py`, after the `COL_I18N` derivation:

```python
# Render-layer value i18n maps. Pass these to render_df_table via
# value_i18n_maps={col_name: <map>}. Stable English keys; values are
# STRINGS lookup keys.

TIER_VALUE_I18N: dict[str, str] = {
    "Tier-1 Critical":   "rpt_tier_1_critical",
    "Tier-2 Important":  "rpt_tier_2_important",
    "Tier-3 Shared":     "rpt_tier_3_shared",
    "Tier-4 Peripheral": "rpt_tier_4_peripheral",
}

ROLE_VALUE_I18N: dict[str, str] = {
    "Identity": "rpt_role_identity",
    "Database": "rpt_role_database",
    "Provider": "rpt_role_provider",
    "Consumer": "rpt_role_consumer",
    "Bridge":   "rpt_role_bridge",
    "Peer":     "rpt_role_peer",
}

ASSET_TYPE_VALUE_I18N: dict[str, str] = {
    "Identity Infrastructure": "rpt_asset_type_identity_infra",
    "Database":                "rpt_asset_type_database",
}

SEVERITY_VALUE_I18N: dict[str, str] = {
    "CRITICAL": "rpt_severity_critical",
    "HIGH":     "rpt_severity_high",
    "MEDIUM":   "rpt_severity_medium",
    "LOW":      "rpt_severity_low",
    "INFO":     "rpt_severity_info",
}

MOD01_METRIC_VALUE_I18N: dict[str, str] = {
    "Policy Coverage":                       "rpt_metric_policy_coverage",
    "Allowed / Blocked / Potentially Blocked": "rpt_metric_allowed_blocked_potential",
    "Total Data":                            "rpt_metric_total_data",
    "Date Range":                            "rpt_metric_date_range",
}
```

- [ ] **Step 3: Write the consistency test**

In `tests/test_render_layer_i18n.py`, append:

```python
def test_value_i18n_constants_resolve_to_real_strings():
    """Every map value must point to an existing STRINGS entry with non-empty en."""
    from src.report.exporters.report_i18n import (
        STRINGS,
        TIER_VALUE_I18N,
        ROLE_VALUE_I18N,
        ASSET_TYPE_VALUE_I18N,
        SEVERITY_VALUE_I18N,
        MOD01_METRIC_VALUE_I18N,
    )
    for label, name in [
        ("TIER", TIER_VALUE_I18N),
        ("ROLE", ROLE_VALUE_I18N),
        ("ASSET_TYPE", ASSET_TYPE_VALUE_I18N),
        ("SEVERITY", SEVERITY_VALUE_I18N),
        ("MOD01_METRIC", MOD01_METRIC_VALUE_I18N),
    ]:
        for stable_en, key in name.items():
            entry = STRINGS.get(key)
            assert entry is not None, f"{label} maps {stable_en!r} → missing key {key!r}"
            assert entry.get("en"), f"{label}.{key} has empty en value"
            assert entry.get("zh_TW"), f"{label}.{key} has empty zh_TW value"
```

- [ ] **Step 4: Run the new test**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_render_layer_i18n.py -v --timeout=60
```

Expected: 6 passed (5 from Task 1 + 1 new).

- [ ] **Step 5: Run audit**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3
```

Expected: `0 finding(s)`. If `[E]` flags any zh value translating a glossary token (e.g. "嚴重度" for "Severity" might trigger; "資料庫" for "Database" might trigger if "Database" is on the audit's whitelist), revert THAT specific entry to keep the English token in zh_TW — then re-run audit until 0.

- [ ] **Step 6: Commit**

```bash
git add src/report/exporters/report_i18n.py tests/test_render_layer_i18n.py
git commit -m "i18n(report): add Tier/role/severity/asset_type/mod01-metric value maps

19 new STRINGS entries + 5 reusable value maps (TIER_VALUE_I18N,
ROLE_VALUE_I18N, ASSET_TYPE_VALUE_I18N, SEVERITY_VALUE_I18N,
MOD01_METRIC_VALUE_I18N) for mod14 / mod13 / mod01 HTML rendering.

Glossary policy: App (Env)/App Env Key/Flows/Enforcement %/Allowed/Blocked/
Potentially Blocked/Ringfence/Policy/Database keep English in zh_TW.
Tier-1..4 hybrid (English Tier-N + zh suffix). Severity translated
(嚴重/高/中/低/資訊) — revertible single edit if visual review prefers
English.

Tests: TIER/ROLE/ASSET_TYPE/SEVERITY/MOD01_METRIC maps each verified
to point at populated STRINGS entries (en + zh_TW non-empty).
"
```

---

## Task 4: Apply value maps to mod14 HTML rendering

**Why:** mod14's role / tier / asset_type DataFrame columns now have STRINGS entries and value maps (Task 3). The HTML exporter's `_mod14_html` method must pass `value_i18n_maps=...` to `render_df_table` so zh users see translated values.

**Files:**
- Modify: `src/report/exporters/html_exporter.py`
- Test: `tests/test_render_layer_i18n.py`

- [ ] **Step 1: Read `_mod14_html` and find the render_df_table call sites**

```bash
sed -n '1216,1290p' src/report/exporters/html_exporter.py
```

Identify each `render_df_table(...)` call within `_mod14_html`. There are typically 2-3: a tier/role summary table, an edge_df table, and possibly a hub_apps table.

- [ ] **Step 2: Read the value-map import line at top of html_exporter.py**

```bash
grep -n 'from .report_i18n import' src/report/exporters/html_exporter.py
```

It currently looks like `from .report_i18n import STRINGS, lang_btn_html, COL_I18N as _COL_I18N`.

- [ ] **Step 3: Extend the import**

Replace that line with:

```python
from .report_i18n import (
    STRINGS,
    lang_btn_html,
    COL_I18N as _COL_I18N,
    TIER_VALUE_I18N,
    ROLE_VALUE_I18N,
    ASSET_TYPE_VALUE_I18N,
    SEVERITY_VALUE_I18N,
    MOD01_METRIC_VALUE_I18N,
)
```

- [ ] **Step 4: Apply value maps in `_mod14_html`**

For each `render_df_table` call inside `_mod14_html` whose DataFrame has a `Tier` / `role` / `asset_type` column, add the matching value map. Example for a tier summary table:

```python
# Before
return render_df_table(
    role_summary,
    col_i18n=_COL_I18N,
    lang=self._lang,
)

# After
return render_df_table(
    role_summary,
    col_i18n=_COL_I18N,
    value_i18n_maps={
        "Tier": TIER_VALUE_I18N,
    },
    lang=self._lang,
)
```

For a table that has `role` and `asset_type` columns (the scored_df):

```python
return render_df_table(
    scored_df,
    col_i18n=_COL_I18N,
    value_i18n_maps={
        "role": ROLE_VALUE_I18N,
        "asset_type": ASSET_TYPE_VALUE_I18N,
        "Tier": TIER_VALUE_I18N,
    },
    lang=self._lang,
)
```

For the edge_df table (no value-level translation needed; columns auto-translate via COL_I18N):

```python
return render_df_table(
    edge_df,
    col_i18n=_COL_I18N,
    lang=self._lang,
)
```

The exact lines vary per build; the rule is: any `render_df_table` call inside `_mod14_html` whose DataFrame contains a column listed in TIER/ROLE/ASSET_TYPE_VALUE_I18N gets that map.

- [ ] **Step 5: Add the integration test**

In `tests/test_render_layer_i18n.py`, append:

```python
def test_mod14_html_translates_tier_and_role_in_zh():
    """End-to-end: mod14 HTML output contains zh tier/role labels in zh_TW."""
    import pandas as pd
    from src.report.exporters.html_exporter import HTMLExporter

    fake_report = {
        "mod14": {
            "scored_apps": [
                {"app_env": "alpha|prod", "Tier": "Tier-1 Critical",
                 "role": "Identity", "asset_type": "Identity Infrastructure"},
                {"app_env": "beta|dev", "Tier": "Tier-3 Shared",
                 "role": "Provider", "asset_type": ""},
            ],
        },
    }
    # Construct a minimal exporter — the constructor signature in this codebase
    # accepts (report_dict, lang). If your local signature differs, adapt:
    exporter = HTMLExporter(fake_report, lang="zh_TW")
    html = exporter._mod14_html()

    assert "Tier-1 重大" in html
    assert "身分" in html  # role: Identity → 身分
    assert "身分基礎架構" in html  # asset_type: Identity Infrastructure
    # English value should NOT leak in zh_TW
    assert "Identity Infrastructure" not in html
```

NOTE: If `HTMLExporter` requires more constructor arguments or the fake report shape differs, inspect `src/report/exporters/html_exporter.py` for the actual signature and adapt. The test must:
- construct an exporter in zh_TW mode
- call `_mod14_html()` (or whichever method renders mod14)
- assert at least one zh translated value is present
- assert the corresponding English value is absent

- [ ] **Step 6: Run the test (it should fail until step 4 changes are saved)**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_render_layer_i18n.py::test_mod14_html_translates_tier_and_role_in_zh -v --timeout=60
```

Expected: PASS (Step 4 already saved the source change).

- [ ] **Step 7: Run full pytest**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -3
```

Expected: `980 passed, 1 skipped` (979 from Task 3 + 1 new).

- [ ] **Step 8: Commit**

```bash
git add src/report/exporters/html_exporter.py tests/test_render_layer_i18n.py
git commit -m "i18n(report): translate mod14 Tier/role/asset_type in HTML output

_mod14_html now passes value_i18n_maps={Tier: TIER_VALUE_I18N,
role: ROLE_VALUE_I18N, asset_type: ASSET_TYPE_VALUE_I18N} to
render_df_table. mod14_infrastructure.py source unchanged — translation
is view-layer only.

Test: end-to-end zh_TW HTML output contains '身分' / 'Tier-1 重大' /
'身分基礎架構' and excludes the English originals.
"
```

---

## Task 5: Apply value maps to mod13 HTML rendering

**Why:** mod13_readiness's recommendations DataFrame uses `Severity` (CRITICAL/HIGH/MEDIUM/...) as a cell value — render-layer translation needed.

**Files:**
- Modify: `src/report/exporters/html_exporter.py`
- Test: `tests/test_render_layer_i18n.py`

- [ ] **Step 1: Read `_mod13_html`**

```bash
grep -n '_mod13_html' src/report/exporters/html_exporter.py
sed -n '1098,1150p' src/report/exporters/html_exporter.py
```

Identify the `render_df_table(recommendations, ...)` call. The recommendations DataFrame has columns `Priority`, `App (Env)`, `App Env Key`, `Issue`, `Action`, `Action Code`, `Severity`.

- [ ] **Step 2: Add `value_i18n_maps={"Severity": SEVERITY_VALUE_I18N}` to that call**

```python
# Before
return render_df_table(
    recommendations,
    col_i18n=_COL_I18N,
    lang=self._lang,
)

# After
return render_df_table(
    recommendations,
    col_i18n=_COL_I18N,
    value_i18n_maps={"Severity": SEVERITY_VALUE_I18N},
    lang=self._lang,
)
```

- [ ] **Step 3: Add the test**

In `tests/test_render_layer_i18n.py`:

```python
def test_mod13_html_translates_severity_in_zh():
    """mod13 recommendations table shows zh severity labels in zh_TW."""
    import pandas as pd
    from src.report.exporters.html_exporter import HTMLExporter

    fake_report = {
        "mod13": {
            "recommendations": pd.DataFrame([
                {"Priority": "P1", "App (Env)": "alpha|prod", "App Env Key": "alpha|prod",
                 "Issue": "Low Coverage", "Action": "Tighten enforcement",
                 "Action Code": "ACT_001", "Severity": "CRITICAL"},
            ]),
        },
    }
    exporter = HTMLExporter(fake_report, lang="zh_TW")
    html = exporter._mod13_html()

    # Severity zh label present, English absent
    assert "嚴重" in html
    assert ">CRITICAL<" not in html  # don't leak as visible cell value (header may still say Severity → 嚴重度)
```

(If `HTMLExporter._mod13_html` requires more keys in `_r["mod13"]`, populate them as empty / sensible defaults so the method runs to the recommendations rendering branch.)

- [ ] **Step 4: Run the test**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest tests/test_render_layer_i18n.py::test_mod13_html_translates_severity_in_zh -v --timeout=60
```

Expected: PASS.

- [ ] **Step 5: Run full pytest**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -3
```

Expected: `981 passed, 1 skipped`.

- [ ] **Step 6: Commit**

```bash
git add src/report/exporters/html_exporter.py tests/test_render_layer_i18n.py
git commit -m "i18n(report): translate mod13 Severity in HTML output"
```

---

## Task 6: Apply mod01 metric/value translation in mod01 summary table

**Why:** The mod01 summary table in `_mod01_summary_table` (around html_exporter.py:712-722) builds rows with hardcoded English metric/value strings. These rows feed `render_df_table` — pass `value_i18n_maps={"Metric": MOD01_METRIC_VALUE_I18N}` so zh users see translated metric names.

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: Read `_mod01_summary_table`**

```bash
grep -n '_mod01_summary_table\|_mod01_html' src/report/exporters/html_exporter.py
sed -n '710,730p' src/report/exporters/html_exporter.py
```

- [ ] **Step 2: Pass the value map**

In the `render_df_table` call inside `_mod01_summary_table` (or wherever the summary DataFrame is rendered):

```python
return render_df_table(
    summary_df,
    col_i18n=_COL_I18N,
    value_i18n_maps={"Metric": MOD01_METRIC_VALUE_I18N},
    lang=self._lang,
)
```

- [ ] **Step 3: Quick smoke**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -c "
import pandas as pd
from src.report.exporters.html_exporter import HTMLExporter
fake = {'mod01': {'pds': {'allowed': 1, 'blocked': 0, 'potential': 0},
                  'date_range': '2026-05-01 ~ 2026-05-09',
                  'total_bytes': 1024}}
exporter = HTMLExporter(fake, lang='zh_TW')
print('Policy 覆蓋率' in exporter._mod01_summary_table())
"
```

Expected: `True`. If `False`, the summary table doesn't surface those exact strings — re-inspect `_mod01_summary_table` for the actual row labels and adjust `MOD01_METRIC_VALUE_I18N` keys to match.

- [ ] **Step 4: Run full pytest**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -3
```

Expected: `981 passed, 1 skipped` (no new test added in this Task — Task 8 covers visual smoke).

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/html_exporter.py
git commit -m "i18n(report): translate mod01 summary metric column in HTML"
```

---

## Task 7: Activate column rename for app_env_scores / recommendations / readiness factor tables

**Why:** `html_exporter.py:1187, 1192, 1206` currently call `rename(columns={"X": "X", ...})` (no-op renames preserved as i18n hooks). With Task 2's STRINGS entries in place, the simpler approach is to drop the rename calls entirely and rely on `col_i18n=_COL_I18N` to translate column headers automatically.

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: Read the three rename sites**

```bash
sed -n '1185,1215p' src/report/exporters/html_exporter.py
```

- [ ] **Step 2: Remove the rename calls (or replace with identity if downstream code depends on them)**

For each of the three `df.rename(columns={...})` calls:

```python
# Before — no-op rename keeping English
factor_table = factor_table.rename(columns={"Factor": "Factor", "Weight": "Weight",
                                            "Score": "Score", "Ratio %": "Ratio %"})

# After — let render_df_table translate via COL_I18N
# (factor_table column names already match COL_I18N keys after Task 2)
```

Just delete the no-op rename lines. The column headers will be translated by `render_df_table(col_i18n=_COL_I18N)` based on Task 2's STRINGS entries.

For the `app_env_scores` rename (line ~1192), same pattern: delete it. For `recommendations` rename (line ~1206), same.

- [ ] **Step 3: Verify no caller depends on the renamed columns**

```bash
grep -nE 'app_env_scores\[|recommendations\[' src/report/ | grep -v '"App ' | head
```

Expected: empty or only DataFrame construction sites — meaning no later code accesses those DataFrames by the renamed column names.

- [ ] **Step 4: Run full pytest**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -3
```

Expected: `981 passed, 1 skipped`.

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/html_exporter.py
git commit -m "refactor(report): drop no-op column renames; rely on COL_I18N for headers

After Task 2 added rpt_col_* entries for App (Env) / Source App (Env) /
Connections / Issue / Action / Severity / Priority / Factor / Weight /
Score / Ratio % / Readiness Score / Policy Coverage % / Ringfence Maturity %
/ Enforcement Mode % / Staged Readiness % / Remote-App Coverage % / Flows /
Grade / Action Code / App Env Key, the no-op rename(columns={...}) calls
that previously held those English headers in place are redundant.
render_df_table(col_i18n=_COL_I18N) now translates them automatically.
"
```

---

## Task 8: Visual smoke test + audit + final verification

**Why:** Wrap up — confirm zh_TW HTML reports render the way an end-user would experience them.

**Files:** none modified.

- [ ] **Step 1: Run audit**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3
```

Expected: `Total: 0 finding(s)`.

- [ ] **Step 2: Run mypy gate**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m mypy src/api_client.py src/analyzer.py src/reporter.py 2>&1 | tail -3
```

Expected: `Success: no issues found in 3 source files`.

- [ ] **Step 3: Run full pytest**

```bash
PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -3
```

Expected: `981 passed, 1 skipped, 0 failed`.

- [ ] **Step 4: Generate sample zh_TW HTML report**

```bash
ILLUMIO_LANG=zh_TW PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m src.report.cli generate traffic --since 2026-05-01 --until 2026-05-09 --format html --output-dir /tmp/render-i18n-smoke 2>&1 | tail -5
```

(If your `report.cli` invocation differs, adapt; the goal is to produce a real HTML report under zh_TW.)

- [ ] **Step 5: Manually inspect the produced HTML**

```bash
grep -E '(Tier-[1-4]|Identity|CRITICAL|App \(Env\)|Source App|Severity)' /tmp/render-i18n-smoke/*.html | head -20
```

For zh_TW, you should see the translated labels (`Tier-1 重大`, `身分`, `嚴重`, `App (Env)` kept English by design, `來源 App (Env)`, `嚴重度`). English-only matches indicate the translation was skipped — re-inspect that specific render path.

- [ ] **Step 6: Generate sample en HTML report — confirm translations DON'T leak in en mode**

```bash
ILLUMIO_LANG=en PYTHONPATH=$(pwd):$(pwd)/venv/lib/python3.12/site-packages venv/bin/python3 -m src.report.cli generate traffic --since 2026-05-01 --until 2026-05-09 --format html --output-dir /tmp/render-i18n-smoke-en 2>&1 | tail -5
grep -cE '重大|身分|嚴重|連線數' /tmp/render-i18n-smoke-en/*.html
```

Expected: `0` matches (no zh leak in en report).

- [ ] **Step 7: Push (if working on `main`) or open PR (if working on `render-layer-i18n` branch)**

```bash
# main path:
git push origin main

# branch path:
git push -u origin render-layer-i18n
gh pr create --title "Render-layer i18n refactor (Tier/role/severity/columns)" \
             --body "Implements docs/superpowers/plans/2026-05-09-render-layer-i18n.md"
```

- [ ] **Step 8: Mark plan as DONE in source**

Append to the bottom of this plan file:

```markdown
## Implementation Status

DONE 2026-MM-DD. All 8 tasks completed; ~62 strings now translated;
audit / pytest / mypy all green.
```

Stop and request review.

---

## Self-Review

**Spec coverage:** Each scope item has a task —
- mod14 Tier/role/asset_type → Task 4
- mod14 edge_df columns → Task 2 (auto via COL_I18N)
- mod13 severity → Task 5
- mod13 column headers → Task 2 (auto via COL_I18N)
- mod12 dim_labels → out-of-scope this plan (chart_renderer Batch 7 already covers via title_key)
- mod12 Maturity Score KPI → already in STRINGS (`rpt_tr_maturity_score`); KPI rendering must look up and translate (verify via Task 8 visual smoke; if missing, add a 30-line follow-up Task 9)
- mod01 summary metric/value → Task 6
- readiness factor / app_env_scores / recommendations columns → Task 7

**Placeholder scan:** No "TBD", "implement later", or "fill in details" in any step. Each step contains either an exact command, exact code, or exact assertion. The two `If your X differs, adapt` notes (Task 4 Step 5, Task 8 Step 4) are unavoidable because the test/CLI signatures are codebase-specific; they direct the engineer to the exact file to inspect.

**Type consistency:** `value_i18n_maps: dict[str, dict[str, str]] | None` in Task 1's signature, the same shape in Tasks 4-7. STRINGS entry shape `{"en": str, "zh_TW": str}` consistent. Constants `TIER_VALUE_I18N` etc. defined as `dict[str, str]` in Task 3, consumed unchanged in Tasks 4-7.

**Backwards compatibility:** `value_i18n_maps` defaults to `None` (Task 1), so all 30+ existing `render_df_table` callers in the codebase keep working unchanged. Only the 4-5 callers in mod14/mod13/mod01 sections of html_exporter.py opt in.

**Risk acknowledged:** Severity translation (`CRITICAL` → `嚴重`) is the most likely single revert point. The Task 3 commit message explicitly notes it as a single-edit revert if visual review prefers English. If the user prefers all-English severity badges, comment out / delete the `rpt_severity_*` STRINGS entries in Task 3 Step 1 — caller Task 5 stays unchanged because it uses the constant `SEVERITY_VALUE_I18N` which becomes a no-op when STRINGS entries are absent (zh value falls back to en, both being "CRITICAL").
