# Report R3 — New High-Value Analyses

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five new analysis modules layered on the draft_policy_decision foundation already shipped in policy-decision-alignment B2: actionable Override Deny / Allowed Across Boundary remediation (`mod_draft_actions`), Enforcement Rollout Plan (`mod_enforcement_rollout`), Application Ringfence view (`mod_ringfence`), Change Impact via JSON snapshots (`mod_change_impact`), and Exfiltration / threat-intel hooks (`mod_exfiltration_intel`).

**Architecture:** Each new module is a standalone analyzer in `src/report/analysis/` returning a result dict consumed by `html_exporter`. R3.4 introduces a small JSON snapshot store under `reports/snapshots/traffic/` with retention managed at the end of each report generation. No new top-level dependencies; everything builds on existing pandas / Plotly / openpyxl stack.

**Tech Stack:** Python 3.11, pandas, existing report exporters, pytest.

**Spec:** `docs/superpowers/specs/2026-04-25-report-content-optimization-design.md` (§6.5 snapshot schema; §7.3 module list)

**Prerequisite:**
- R0+R1 plan merged (v3.18.0-report-semantics) — provides `traffic_report_profile`, `section_guidance`, KPI redesign.
- R2 plan merged (v3.19.0-report-compact) — provides `detail_level`, appendix, single-bundle Plotly.
- policy-decision-alignment B2 merged (v3.16.0-draft-pd-reports) — provides `src/report/analysis/mod_draft_summary.py` with 7-subtype counts and top workload pairs. R3 modules consume its output, do not duplicate it.

**Branch:** `feat/report-r03-intelligence`
**Target tag:** `v3.20.0-report-intelligence`
**Baseline (record at start):** Run `python3 -m pytest tests/ -q` and write the count here. R2 target was ~640 passed; R3 target ~680 passed.

---

## File Structure

### New files

| Path | Responsibility |
|------|----------------|
| `src/report/analysis/mod_draft_actions.py` | Override Deny remediation, Allowed Across Boundary review, what-if assumptions. |
| `src/report/analysis/mod_enforcement_rollout.py` | Score apps for enforcement readiness; ranked rollout table. |
| `src/report/analysis/mod_ringfence.py` | Per-app dependency profile + candidate allowlist + boundary deny suggestions. |
| `src/report/analysis/mod_change_impact.py` | Compare current vs previous snapshot; detect improvement / regression. |
| `src/report/analysis/mod_exfiltration_intel.py` | Managed→unmanaged exfiltration + threat-intel join. |
| `src/report/snapshot_store.py` | JSON snapshot write / read / list / cleanup. |
| `tests/test_mod_draft_actions.py` | Unit tests for Override Deny + Allowed Across Boundary analysis. |
| `tests/test_mod_enforcement_rollout.py` | Scoring + ranking tests. |
| `tests/test_mod_ringfence.py` | Per-app profile + candidate rules. |
| `tests/test_mod_change_impact.py` | Comparison + improvement/regression labeling. |
| `tests/test_snapshot_store.py` | Write/read/list/cleanup roundtrip + retention. |
| `tests/test_mod_exfiltration_intel.py` | Managed→unmanaged + threat-intel join. |

### Modified files

| Path | Change |
|------|--------|
| `src/report/analysis/__init__.py` | Register 5 new modules. |
| `src/report/exporters/html_exporter.py` | Render new sections (gated by `visible_in()`); pass snapshot path to `mod_change_impact`. |
| `src/report/report_generator.py` | Trigger snapshot write at end of each Traffic report; trigger retention cleanup. |
| `src/report/section_guidance.py` | Register guidance for 5 new modules. |
| `src/config_models.py` | Add `report.snapshot_retention_days` (default 90), `report.threat_intel_csv_path` (optional), `report.draft_actions_enabled` (default True). |
| `src/i18n_en.json`, `src/i18n_zh_TW.json` | +~40 keys (5 modules × 4 guidance + section titles + KPI labels). |
| `src/__init__.py` | Bump to `3.20.0-report-intelligence`. |

---

## Task 1: Capture baseline

**Files:** none

- [ ] **Step 1: Test count baseline**

```bash
python3 -m pytest tests/ -q 2>&1 | tail -3
```

Record in plan header.

- [ ] **Step 2: Confirm prerequisite modules exist**

```bash
ls /mnt/d/RD/illumio_ops/src/report/analysis/mod_draft_summary.py
```

Expected: file exists (B2 deliverable). If missing, R3 must wait for B2 to ship.

- [ ] **Step 3: Confirm directories**

```bash
mkdir -p /mnt/d/RD/illumio_ops/reports/snapshots/traffic
```

(Will be auto-created by `snapshot_store.py` later, but confirm permissions.)

---

## Task 2: `snapshot_store.py` — write/read/list/cleanup

**Files:**
- Create: `src/report/snapshot_store.py`
- Create: `tests/test_snapshot_store.py`

- [ ] **Step 1: Write failing test**

```python
"""Snapshot store: KPI-only JSON files in reports/snapshots/<type>/<YYYY-MM-DD>.json."""
import json
from datetime import datetime, timezone

import pytest

from src.report.snapshot_store import (
    write_snapshot, read_latest, list_snapshots, cleanup_old, SCHEMA_VERSION,
)


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.snapshot_store._BASE_DIR", str(tmp_path))
    return tmp_path


def _make_snapshot(date_str: str, profile: str = "security_risk", **kpi_overrides):
    base_kpis = {
        "microsegmentation_maturity": 0.62,
        "active_allow_coverage": 0.71,
        "pb_uncovered_exposure": 1234,
        "blocked_flows": 87,
        "high_risk_lateral_paths": 14,
        "top_remediation_action": {"code": "QUARANTINE", "count": 3},
    }
    base_kpis.update(kpi_overrides)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "traffic",
        "profile": profile,
        "generated_at": f"{date_str}T08:00:00Z",
        "query_window": {"start": "2026-04-18", "end": date_str},
        "kpis": base_kpis,
        "policy_changes_since_previous": [],
    }


def test_write_then_read_latest(store_dir):
    snap = _make_snapshot("2026-04-25")
    write_snapshot("traffic", snap)
    latest = read_latest("traffic", profile="security_risk")
    assert latest is not None
    assert latest["kpis"]["pb_uncovered_exposure"] == 1234


def test_read_latest_returns_none_when_empty(store_dir):
    assert read_latest("traffic", profile="security_risk") is None


def test_list_snapshots_sorted_desc(store_dir):
    write_snapshot("traffic", _make_snapshot("2026-04-23"))
    write_snapshot("traffic", _make_snapshot("2026-04-25"))
    write_snapshot("traffic", _make_snapshot("2026-04-24"))
    items = list_snapshots("traffic", profile="security_risk")
    dates = [it["generated_at"][:10] for it in items]
    assert dates == ["2026-04-25", "2026-04-24", "2026-04-23"]


def test_same_date_overwrites(store_dir):
    write_snapshot("traffic", _make_snapshot("2026-04-25", pb_uncovered_exposure=100))
    write_snapshot("traffic", _make_snapshot("2026-04-25", pb_uncovered_exposure=200))
    latest = read_latest("traffic", profile="security_risk")
    assert latest["kpis"]["pb_uncovered_exposure"] == 200


def test_cleanup_old_respects_retention(store_dir):
    write_snapshot("traffic", _make_snapshot("2026-01-01"))
    write_snapshot("traffic", _make_snapshot("2026-04-25"))
    removed = cleanup_old("traffic", retention_days=30, today=datetime(2026, 4, 25, tzinfo=timezone.utc))
    items = list_snapshots("traffic", profile="security_risk")
    assert len(items) == 1
    assert items[0]["generated_at"].startswith("2026-04-25")
    assert removed == 1


def test_read_latest_filters_by_profile(store_dir):
    write_snapshot("traffic", _make_snapshot("2026-04-25", profile="security_risk", pb_uncovered_exposure=111))
    write_snapshot("traffic", _make_snapshot("2026-04-25", profile="network_inventory", pb_uncovered_exposure=999))
    sec = read_latest("traffic", profile="security_risk")
    net = read_latest("traffic", profile="network_inventory")
    assert sec["kpis"]["pb_uncovered_exposure"] == 111
    assert net["kpis"]["pb_uncovered_exposure"] == 999
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_snapshot_store.py -v
```

- [ ] **Step 3: Implement `src/report/snapshot_store.py`**

```python
"""KPI-only JSON snapshot store for report Change Impact analysis.

Path: reports/snapshots/<report_type>/<YYYY-MM-DD>_<profile>.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1
_BASE_DIR = "reports/snapshots"


def _dir_for(report_type: str) -> Path:
    p = Path(_BASE_DIR) / report_type
    p.mkdir(parents=True, exist_ok=True)
    return p


def _filename(snap: dict) -> str:
    date = snap["generated_at"][:10]  # YYYY-MM-DD
    profile = snap.get("profile", "default")
    return f"{date}_{profile}.json"


def write_snapshot(report_type: str, snap: dict) -> Path:
    """Atomic write. Same date+profile overwrites."""
    if snap.get("schema_version") != SCHEMA_VERSION:
        snap["schema_version"] = SCHEMA_VERSION
    target = _dir_for(report_type) / _filename(snap)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, indent=2, sort_keys=True))
    tmp.replace(target)
    return target


def list_snapshots(report_type: str, *, profile: Optional[str] = None) -> list[dict]:
    """Return snapshots sorted by generated_at descending. Filtered by profile if given."""
    items = []
    for f in _dir_for(report_type).glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if profile is not None and data.get("profile") != profile:
            continue
        items.append(data)
    items.sort(key=lambda d: d.get("generated_at", ""), reverse=True)
    return items


def read_latest(report_type: str, *, profile: Optional[str] = None) -> Optional[dict]:
    items = list_snapshots(report_type, profile=profile)
    return items[0] if items else None


def cleanup_old(report_type: str, *, retention_days: int, today: Optional[datetime] = None) -> int:
    """Delete snapshots older than retention_days. Returns number removed."""
    cutoff = (today or datetime.now(timezone.utc)).date()
    removed = 0
    for f in _dir_for(report_type).glob("*.json"):
        try:
            data = json.loads(f.read_text())
            snap_date = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00")).date()
        except (KeyError, ValueError, json.JSONDecodeError, OSError):
            continue
        age_days = (cutoff - snap_date).days
        if age_days > retention_days:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
```

- [ ] **Step 4: Run tests — PASS**

```bash
python3 -m pytest tests/test_snapshot_store.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/report/snapshot_store.py tests/test_snapshot_store.py
git commit -m "feat(report): JSON snapshot store with retention for Change Impact"
```

---

## Task 3: Add `report.snapshot_retention_days` to config

**Files:**
- Modify: `src/config_models.py`
- Modify: `src/report/snapshot_store.py` (read default from config)

- [ ] **Step 1: Extend `ReportSettings` with new fields**

In `src/config_models.py`, locate `class ReportSettings` and add:

```python
class ReportSettings(_Base):
    # ... existing fields ...
    snapshot_retention_days: int = Field(default=90, ge=1, le=3650)
    threat_intel_csv_path: Optional[str] = None
    draft_actions_enabled: bool = True
```

- [ ] **Step 2: Write a small test**

Append to `tests/test_config_models.py` (or `tests/test_config_validators.py`):

```python
def test_report_snapshot_retention_default():
    from src.config_models import ReportSettings
    r = ReportSettings()
    assert r.snapshot_retention_days == 90
    assert r.draft_actions_enabled is True
    assert r.threat_intel_csv_path is None


def test_report_snapshot_retention_validates_range():
    import pytest
    from pydantic import ValidationError
    from src.config_models import ReportSettings
    with pytest.raises(ValidationError):
        ReportSettings(snapshot_retention_days=0)
```

- [ ] **Step 3: Run + commit**

```bash
python3 -m pytest tests/test_config_models.py tests/test_config_validators.py -v
git add src/config_models.py tests/test_config_models.py
git commit -m "feat(config): report.snapshot_retention_days/threat_intel_csv_path/draft_actions_enabled"
```

---

## Task 4: `mod_draft_actions` — Override Deny remediation analysis

**Files:**
- Create: `src/report/analysis/mod_draft_actions.py`
- Create: `tests/test_mod_draft_actions.py`

- [ ] **Step 1: Write failing test for Override Deny**

```python
"""mod_draft_actions: Override Deny remediation suggestions."""
import pandas as pd

from src.report.analysis import mod_draft_actions


def _flows_with_override_deny():
    return pd.DataFrame([
        {"src": "web-1", "dst": "db-1", "port": 3306, "policy_decision": "allowed",
         "draft_policy_decision": "blocked_by_override_deny"},
        {"src": "web-1", "dst": "db-2", "port": 3306, "policy_decision": "allowed",
         "draft_policy_decision": "blocked_by_override_deny"},
        {"src": "app-1", "dst": "log-1", "port": 514, "policy_decision": "allowed",
         "draft_policy_decision": "potentially_blocked_by_override_deny"},
    ])


def test_skipped_when_no_draft_column():
    out = mod_draft_actions.analyze(pd.DataFrame([{"src": "a", "dst": "b", "port": 80,
                                                    "policy_decision": "allowed"}]))
    assert out.get("skipped") is True


def test_override_deny_remediation_top_pairs():
    out = mod_draft_actions.analyze(_flows_with_override_deny())
    od = out["override_deny"]
    # Top pair web-1 -> (db-1, db-2) with port 3306 contributes 2 flows
    assert od["count"] == 2  # only blocked_by_override_deny — not the potentially_ variant
    assert any(p["src"] == "web-1" and p["port"] == 3306 for p in od["top_pairs"])


def test_potentially_blocked_by_override_deny_separate():
    out = mod_draft_actions.analyze(_flows_with_override_deny())
    pod = out["potentially_blocked_by_override_deny"]
    assert pod["count"] == 1


def test_remediation_suggestion_present():
    out = mod_draft_actions.analyze(_flows_with_override_deny())
    od = out["override_deny"]
    assert "remediation" in od
    # Each remediation has action_code + description_key
    for r in od["remediation"]:
        assert "action_code" in r and "description_key" in r
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_mod_draft_actions.py -v
```

- [ ] **Step 3: Implement Override Deny logic**

```python
"""Actionable analysis for draft_policy_decision sub-categories that need
human review or remediation: Override Deny, Allowed Across Boundary, what-if.

Distinct from mod_draft_summary (B2.2) which only counts and lists top pairs.
"""
from __future__ import annotations

import pandas as pd


def analyze(flows_df: pd.DataFrame) -> dict:
    if "draft_policy_decision" not in flows_df.columns:
        return {"skipped": True, "reason": "no draft_policy_decision column"}
    return {
        "override_deny": _override_deny_block(flows_df),
        "potentially_blocked_by_override_deny": _potentially_override_deny_block(flows_df),
        "allowed_across_boundary": _allowed_across_boundary_block(flows_df),
        "what_if_summary": _what_if_summary(flows_df),
    }


def _override_deny_block(flows_df):
    mask = flows_df["draft_policy_decision"] == "blocked_by_override_deny"
    sub = flows_df[mask]
    top = (sub.groupby(["src", "dst", "port"]).size()
           .sort_values(ascending=False).head(20)
           .reset_index(name="flows").to_dict("records"))
    return {
        "count": int(mask.sum()),
        "top_pairs": top,
        "remediation": _remediation_for_override_deny(top),
    }


def _potentially_override_deny_block(flows_df):
    mask = flows_df["draft_policy_decision"] == "potentially_blocked_by_override_deny"
    sub = flows_df[mask]
    top = (sub.groupby(["src", "dst", "port"]).size()
           .sort_values(ascending=False).head(20)
           .reset_index(name="flows").to_dict("records"))
    return {"count": int(mask.sum()), "top_pairs": top}


def _allowed_across_boundary_block(flows_df):
    mask = flows_df["draft_policy_decision"] == "allowed_across_boundary"
    sub = flows_df[mask]
    top = (sub.groupby(["src", "dst", "port"]).size()
           .sort_values(ascending=False).head(20)
           .reset_index(name="flows").to_dict("records"))
    return {
        "count": int(mask.sum()),
        "top_pairs": top,
        "review_workflow": _build_review_workflow(top),
    }


def _what_if_summary(flows_df):
    """If draft were promoted to active right now, count flows that would change."""
    if "policy_decision" not in flows_df.columns:
        return {"skipped": True}
    same = (flows_df["policy_decision"] == flows_df["draft_policy_decision"])
    differ = ~same
    return {
        "total": len(flows_df),
        "would_change": int(differ.sum()),
        "would_change_share": (float(differ.sum()) / len(flows_df)) if len(flows_df) else 0.0,
    }


def _remediation_for_override_deny(top_pairs):
    """For each top Override Deny pair, suggest a remediation action."""
    out = []
    for p in top_pairs:
        out.append({
            "action_code": "REVIEW_OVERRIDE_DENY",
            "description_key": "rpt_draft_actions_remediate_override_deny",
            "src": p["src"], "dst": p["dst"], "port": p["port"], "flows": p["flows"],
        })
    return out


def _build_review_workflow(top_pairs):
    """For each Allowed Across Boundary pair, suggest review steps."""
    return [{
        "step": "verify_intent",
        "description_key": "rpt_draft_actions_aab_verify_intent",
        "pair": p,
    } for p in top_pairs]
```

- [ ] **Step 4: Add 4 i18n keys**

```
rpt_draft_actions_remediate_override_deny    "Review the active allow rule and the override-deny boundary; tighten or remove conflict."
rpt_draft_actions_aab_verify_intent          "Confirm boundary crossing was intentional; otherwise add boundary deny or scope rule."
```

(Add to both EN and zh-TW JSON files; use semantically equivalent translations for zh-TW.)

- [ ] **Step 5: Run tests — PASS**

```bash
python3 -m pytest tests/test_mod_draft_actions.py -v
python3 scripts/audit_i18n_usage.py
```

- [ ] **Step 6: Commit**

```bash
git add src/report/analysis/mod_draft_actions.py tests/test_mod_draft_actions.py \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): mod_draft_actions for Override Deny + Allowed Across Boundary remediation"
```

---

## Task 5: Register `mod_draft_actions` + render guidance + HTML integration

**Files:**
- Modify: `src/report/analysis/__init__.py`
- Modify: `src/report/section_guidance.py`
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Register in analysis __init__**

Add to the analysis registry pattern used by existing modules:

```python
"mod_draft_actions": ("mod_draft_actions", "draft_policy_actions"),
```

- [ ] **Step 2: Add 4 guidance i18n keys**

```
rpt_guidance_mod_draft_actions_purpose       "Convert raw draft_policy_decision counts into specific remediation actions for Override Deny and Allowed Across Boundary."
rpt_guidance_mod_draft_actions_signals       "High Override Deny count — active allow conflicts with intended boundary deny. High Allowed Across Boundary count — boundaries leaking."
rpt_guidance_mod_draft_actions_how           "Each remediation row points to a specific src→dst→port pair and the action to take."
rpt_guidance_mod_draft_actions_actions       "Tighten or remove conflicting allow rules; add boundary deny if leaks confirmed; verify legitimate cross-boundary flows."
```

- [ ] **Step 3: Register in section_guidance**

```python
REGISTRY["mod_draft_actions"] = SectionGuidance(
    module_id="mod_draft_actions",
    purpose_key="rpt_guidance_mod_draft_actions_purpose",
    watch_signals_key="rpt_guidance_mod_draft_actions_signals",
    how_to_read_key="rpt_guidance_mod_draft_actions_how",
    recommended_actions_key="rpt_guidance_mod_draft_actions_actions",
    primary_audience="security",
    profile_visibility=("security_risk",),
    min_detail_level="standard",
)
```

- [ ] **Step 4: Render in HTML exporter**

In `src/report/exporters/html_exporter.py`, after the existing draft_summary section (from B2):

```python
if visible_in("mod_draft_actions", profile, detail_level):
    from src.report.analysis import mod_draft_actions
    if cm.models.report.draft_actions_enabled:
        actions_data = mod_draft_actions.analyze(flows)
        if not actions_data.get("skipped"):
            html_parts.append(render_section_guidance("mod_draft_actions", profile, detail_level))
            html_parts.append(f'<h2>{t("rpt_mod_draft_actions_title")}</h2>')
            html_parts.append(_render_draft_actions_section(actions_data))
```

Add helper `_render_draft_actions_section` that renders three sub-sections (Override Deny / potentially Override Deny / Allowed Across Boundary), each with the top pairs table and remediation suggestions.

Add i18n key `rpt_mod_draft_actions_title` = "Draft Policy: Actionable Remediation" / "Draft 政策：可採取行動的修復".

- [ ] **Step 5: Test + audit**

```bash
python3 -m pytest tests/test_mod_draft_actions.py tests/test_section_guidance.py -v
python3 scripts/audit_i18n_usage.py
```

- [ ] **Step 6: Commit**

```bash
git add src/report/analysis/__init__.py src/report/section_guidance.py \
        src/report/exporters/html_exporter.py \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): integrate mod_draft_actions section in Traffic exporter"
```

---

## Task 6: `mod_enforcement_rollout` — scoring & ranked table

**Files:**
- Create: `src/report/analysis/mod_enforcement_rollout.py`
- Create: `tests/test_mod_enforcement_rollout.py`

- [ ] **Step 1: Write failing test**

```python
"""mod_enforcement_rollout: rank apps by enforcement readiness vs risk."""
import pandas as pd

from src.report.analysis import mod_enforcement_rollout


def _flows():
    return pd.DataFrame([
        # app A: high allowed, low PB → high readiness
        {"src": "a-web", "dst": "a-db", "port": 443, "policy_decision": "allowed",
         "src_app": "A", "dst_app": "A"},
        {"src": "a-web", "dst": "a-db", "port": 80,  "policy_decision": "allowed",
         "src_app": "A", "dst_app": "A"},
        # app B: lots of PB → low readiness, high risk
        {"src": "b-web", "dst": "b-db", "port": 3306, "policy_decision": "potentially_blocked",
         "src_app": "B", "dst_app": "B"},
        {"src": "b-web", "dst": "b-cache", "port": 6379, "policy_decision": "potentially_blocked",
         "src_app": "B", "dst_app": "B"},
        {"src": "b-web", "dst": "b-svc", "port": 22,   "policy_decision": "potentially_blocked",
         "src_app": "B", "dst_app": "B"},
    ])


def test_rollout_returns_ranked_apps():
    out = mod_enforcement_rollout.analyze(_flows())
    ranked = out["ranked"]
    assert len(ranked) >= 2
    # App A should rank higher (more ready) than B
    apps_in_order = [r["app"] for r in ranked]
    assert apps_in_order.index("A") < apps_in_order.index("B")


def test_rollout_row_fields():
    out = mod_enforcement_rollout.analyze(_flows())
    row = out["ranked"][0]
    for fld in ("priority", "app", "why_now", "expected_default_deny_impact",
                "required_allow_rules", "risk_reduction"):
        assert fld in row, f"missing {fld}"


def test_rollout_top3_callout():
    out = mod_enforcement_rollout.analyze(_flows())
    top3 = out["top3_callout"]
    assert isinstance(top3, list) and len(top3) <= 3
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_mod_enforcement_rollout.py -v
```

- [ ] **Step 3: Implement**

```python
"""Enforcement Rollout Plan: rank apps for moving to enforcement.

Inputs: flows DataFrame with src_app/dst_app columns (or label parsing).
Optional: draft_summary output (from B2.2 mod_draft_summary) for richer scoring.
"""
from __future__ import annotations

import pandas as pd


def analyze(flows_df: pd.DataFrame, *, draft_summary: dict | None = None,
            readiness_summary: dict | None = None) -> dict:
    if "dst_app" not in flows_df.columns and "src_app" not in flows_df.columns:
        # Try label parsing — out of scope for this initial impl.
        return {"skipped": True, "reason": "no app labels"}

    apps = sorted(set(flows_df.get("dst_app", pd.Series(dtype=object)).dropna().unique())
                  | set(flows_df.get("src_app", pd.Series(dtype=object)).dropna().unique()))

    rows = []
    for app in apps:
        app_flows = flows_df[(flows_df.get("src_app") == app) | (flows_df.get("dst_app") == app)]
        total = len(app_flows)
        if total == 0:
            continue
        allowed = int((app_flows["policy_decision"] == "allowed").sum())
        pb = int((app_flows["policy_decision"] == "potentially_blocked").sum())
        blocked = int((app_flows["policy_decision"] == "blocked").sum())
        readiness = (allowed / total) if total else 0.0
        # Score = readiness - risk_penalty; higher = more ready to enforce
        risk_penalty = (pb / total) if total else 0.0
        score = readiness - risk_penalty
        rows.append({
            "app": app,
            "_score": round(score, 4),
            "priority": 0,  # filled after sort
            "why_now": _why_now(allowed, pb, blocked, total),
            "expected_default_deny_impact": pb,  # PB flows would be blocked
            "required_allow_rules": _required_allows(app_flows),
            "risk_reduction": _risk_reduction(app_flows),
        })
    rows.sort(key=lambda r: r["_score"], reverse=True)
    for i, r in enumerate(rows, start=1):
        r["priority"] = i
    return {
        "ranked": rows,
        "top3_callout": rows[:3],
    }


def _why_now(allowed, pb, blocked, total):
    if pb == 0:
        return "all_flows_have_policy"
    if pb / max(total, 1) > 0.3:
        return "high_pb_share"
    if blocked > 0:
        return "active_block_signal"
    return "ready_with_minor_gaps"


def _required_allows(app_flows):
    pb_mask = app_flows["policy_decision"] == "potentially_blocked"
    if not pb_mask.any():
        return 0
    pb_pairs = app_flows[pb_mask].groupby(["src", "dst", "port"]).size()
    return int(len(pb_pairs))


def _risk_reduction(app_flows):
    """Estimate flows that would no longer be uncovered after enforcement."""
    return int((app_flows["policy_decision"] == "potentially_blocked").sum())
```

- [ ] **Step 4: Run tests + commit**

```bash
python3 -m pytest tests/test_mod_enforcement_rollout.py -v
git add src/report/analysis/mod_enforcement_rollout.py tests/test_mod_enforcement_rollout.py
git commit -m "feat(report): mod_enforcement_rollout — rank apps for enforcement"
```

---

## Task 7: Register + render `mod_enforcement_rollout`

**Files:**
- Modify: `src/report/analysis/__init__.py`
- Modify: `src/report/section_guidance.py`
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add 4 guidance keys + section title**

```
rpt_guidance_mod_enf_rollout_purpose      "Rank apps by readiness to move to enforcement; show what each app needs first."
rpt_guidance_mod_enf_rollout_signals      "Apps with high readiness + low PB are top candidates. Apps with high PB need allow rules first."
rpt_guidance_mod_enf_rollout_how          "Higher priority = more ready. Required Allow Rules = unique label-pair/port combinations to author."
rpt_guidance_mod_enf_rollout_actions      "Schedule top 3 apps for selective enforcement; address PB gaps for the rest."
rpt_mod_enf_rollout_title                 "Enforcement Rollout Plan"
```

- [ ] **Step 2: Register in section_guidance**

```python
REGISTRY["mod_enforcement_rollout"] = SectionGuidance(
    module_id="mod_enforcement_rollout",
    purpose_key="rpt_guidance_mod_enf_rollout_purpose",
    watch_signals_key="rpt_guidance_mod_enf_rollout_signals",
    how_to_read_key="rpt_guidance_mod_enf_rollout_how",
    recommended_actions_key="rpt_guidance_mod_enf_rollout_actions",
    primary_audience="mixed",
    profile_visibility=("security_risk", "network_inventory"),
    min_detail_level="standard",
)
```

- [ ] **Step 3: Render in exporter**

```python
if visible_in("mod_enforcement_rollout", profile, detail_level):
    from src.report.analysis import mod_enforcement_rollout, mod_draft_summary
    draft = mod_draft_summary.analyze(flows) if "draft_policy_decision" in flows.columns else None
    rollout = mod_enforcement_rollout.analyze(flows, draft_summary=draft)
    if not rollout.get("skipped"):
        html_parts.append(render_section_guidance("mod_enforcement_rollout", profile, detail_level))
        html_parts.append(f'<h2>{t("rpt_mod_enf_rollout_title")}</h2>')
        html_parts.append(_render_rollout_table(rollout["ranked"]))
```

- [ ] **Step 4: Add Top-3 callout to executive summary block (mod12)**

In the mod12 render path, after KPI rendering, if rollout is available:

```python
if rollout and rollout.get("top3_callout"):
    html_parts.append(_render_top3_rollout_callout(rollout["top3_callout"]))
```

- [ ] **Step 5: Test + audit + commit**

```bash
python3 -m pytest tests/ -k "rollout or guidance" -v
python3 scripts/audit_i18n_usage.py
git add src/report/analysis/__init__.py src/report/section_guidance.py \
        src/report/exporters/html_exporter.py \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): integrate mod_enforcement_rollout + Top-3 callout"
```

---

## Task 8: `mod_ringfence` — per-app dependency profile + candidate allowlist

**Files:**
- Create: `src/report/analysis/mod_ringfence.py`
- Create: `tests/test_mod_ringfence.py`

- [ ] **Step 1: Write failing test**

```python
"""mod_ringfence: per-app dependency profile and candidate allow rules."""
import pandas as pd

from src.report.analysis import mod_ringfence


def _flows():
    return pd.DataFrame([
        # App X: intra-app + cross-app to shared infra
        {"src": "x-web", "dst": "x-db", "port": 5432, "policy_decision": "allowed",
         "src_app": "X", "dst_app": "X"},
        {"src": "x-web", "dst": "shared-dns", "port": 53, "policy_decision": "allowed",
         "src_app": "X", "dst_app": "shared"},
        # App X: cross-env exception
        {"src": "x-web", "dst": "y-db", "port": 5432, "policy_decision": "potentially_blocked",
         "src_app": "X", "dst_app": "Y", "src_env": "prod", "dst_env": "dev"},
    ])


def test_per_app_profile():
    out = mod_ringfence.analyze(_flows(), app="X")
    assert "intra_app_flows" in out
    assert "cross_app_dependencies" in out
    assert "cross_env_exceptions" in out


def test_candidate_allow_rules():
    out = mod_ringfence.analyze(_flows(), app="X")
    candidates = out["candidate_allow_rules"]
    assert len(candidates) >= 1
    for c in candidates:
        assert "src_label" in c and "dst_label" in c and "port" in c


def test_returns_top_apps_when_no_app_specified():
    out = mod_ringfence.analyze(_flows())
    assert "top_apps" in out
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_mod_ringfence.py -v
```

- [ ] **Step 3: Implement**

```python
"""Application Ringfence: per-app dependency profile + candidate allow rules.

When `app` is provided, returns a deep profile for that app.
When `app` is omitted, returns top apps by flow volume for selection.
"""
from __future__ import annotations

import pandas as pd


def analyze(flows_df: pd.DataFrame, *, app: str | None = None) -> dict:
    if "src_app" not in flows_df.columns and "dst_app" not in flows_df.columns:
        return {"skipped": True, "reason": "no app labels"}

    if app is None:
        return {"top_apps": _top_apps(flows_df, limit=20)}

    return _profile_for_app(flows_df, app)


def _top_apps(flows_df, limit):
    series_dst = flows_df.get("dst_app", pd.Series(dtype=object)).dropna()
    series_src = flows_df.get("src_app", pd.Series(dtype=object)).dropna()
    counts = (pd.concat([series_dst, series_src]).value_counts()
              .head(limit).reset_index().rename(columns={"index": "app", 0: "flows"}))
    return counts.to_dict("records")


def _profile_for_app(flows_df, app):
    is_app = (flows_df.get("src_app") == app) | (flows_df.get("dst_app") == app)
    sub = flows_df[is_app]
    intra = sub[(sub.get("src_app") == app) & (sub.get("dst_app") == app)]
    cross = sub[(sub.get("src_app") == app) ^ (sub.get("dst_app") == app)]

    cross_env = pd.DataFrame()
    if "src_env" in sub.columns and "dst_env" in sub.columns:
        cross_env = sub[(sub["src_env"].notna()) & (sub["dst_env"].notna())
                        & (sub["src_env"] != sub["dst_env"])]

    candidates = _candidate_allows(sub)
    return {
        "app": app,
        "intra_app_flows": int(len(intra)),
        "cross_app_dependencies": _summarize_cross_app(cross, app),
        "cross_env_exceptions": _summarize_cross_env(cross_env),
        "candidate_allow_rules": candidates,
        "candidate_rules_count": len(candidates),
        "boundary_deny_candidates": _boundary_deny_candidates(sub),
    }


def _summarize_cross_app(cross_df, app):
    if cross_df.empty:
        return []
    by_pair = cross_df.groupby(["src_app", "dst_app"]).size()
    return [{"src_app": s, "dst_app": d, "flows": int(c)} for (s, d), c in by_pair.items() if s != d or s != app]


def _summarize_cross_env(cross_env_df):
    if cross_env_df.empty:
        return []
    return [{"src_env": s, "dst_env": d, "flows": int(c)}
            for (s, d), c in cross_env_df.groupby(["src_env", "dst_env"]).size().items()]


def _candidate_allows(sub):
    """Build candidate allow rules from observed flows lacking explicit allow."""
    pb = sub[sub["policy_decision"] == "potentially_blocked"]
    if pb.empty:
        return []
    grouped = pb.groupby(["src", "dst", "port"]).size().reset_index(name="flows")
    return [{
        "src_label": _label_of(sub, row["src"]),
        "dst_label": _label_of(sub, row["dst"]),
        "port": int(row["port"]),
        "flows": int(row["flows"]),
    } for _, row in grouped.iterrows()]


def _label_of(sub, addr):
    """Best-effort label lookup; returns the address itself if no label is present."""
    if "src_label" in sub.columns:
        match = sub[sub["src"] == addr]["src_label"].dropna()
        if not match.empty:
            return match.iloc[0]
    if "dst_label" in sub.columns:
        match = sub[sub["dst"] == addr]["dst_label"].dropna()
        if not match.empty:
            return match.iloc[0]
    return addr


def _boundary_deny_candidates(sub):
    """Cross-env or unknown-dst flows that should be denied at the boundary."""
    if "src_env" not in sub.columns or "dst_env" not in sub.columns:
        return []
    crosses = sub[(sub["src_env"].notna()) & (sub["dst_env"].notna())
                  & (sub["src_env"] != sub["dst_env"])]
    return [{"src_env": s, "dst_env": d, "flows": int(c)}
            for (s, d), c in crosses.groupby(["src_env", "dst_env"]).size().items()]
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_mod_ringfence.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/report/analysis/mod_ringfence.py tests/test_mod_ringfence.py
git commit -m "feat(report): mod_ringfence — per-app dependency profile + candidate allows"
```

---

## Task 9: Register + render `mod_ringfence`

**Files:**
- Modify: `src/report/analysis/__init__.py`
- Modify: `src/report/section_guidance.py`
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: i18n keys + register guidance**

```
rpt_guidance_mod_ringfence_purpose    "Map per-app dependencies and propose label-based ringfence rules."
rpt_guidance_mod_ringfence_signals    "High cross-app or cross-env flows lacking allow rules; unknown labels in dependencies."
rpt_guidance_mod_ringfence_how        "Each candidate rule is a src_label → dst_label → port triple ready for review."
rpt_guidance_mod_ringfence_actions    "Author candidate allows; add boundary deny for cross-env exceptions; resolve unmanaged dependencies."
rpt_mod_ringfence_title               "Application Ringfence"
```

Register `mod_ringfence` with `primary_audience="network"`, `profile_visibility=("network_inventory",)` (security_risk shows it only via the rollout dependency, not as a standalone section).

- [ ] **Step 2: Render in exporter (network_inventory profile only by default)**

```python
if visible_in("mod_ringfence", profile, detail_level):
    from src.report.analysis import mod_ringfence
    rf = mod_ringfence.analyze(flows)
    if not rf.get("skipped"):
        html_parts.append(render_section_guidance("mod_ringfence", profile, detail_level))
        html_parts.append(f'<h2>{t("rpt_mod_ringfence_title")}</h2>')
        html_parts.append(_render_ringfence_top_apps(rf["top_apps"]))
        # Per-app deep dive — for each top app render a sub-section
        for app_summary in rf["top_apps"][:5]:
            deep = mod_ringfence.analyze(flows, app=app_summary["app"])
            html_parts.append(_render_ringfence_app(deep))
```

- [ ] **Step 3: Test + audit + commit**

```bash
python3 -m pytest tests/test_mod_ringfence.py -v
python3 scripts/audit_i18n_usage.py
git add src/report/analysis/__init__.py src/report/section_guidance.py \
        src/report/exporters/html_exporter.py \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): integrate mod_ringfence in network_inventory profile"
```

---

## Task 10: `mod_change_impact` — compare current vs previous snapshot

**Files:**
- Create: `src/report/analysis/mod_change_impact.py`
- Create: `tests/test_mod_change_impact.py`

- [ ] **Step 1: Write failing test**

```python
"""mod_change_impact: compare current KPIs to a previous snapshot."""
import pandas as pd
import pytest

from src.report.analysis import mod_change_impact


def _kpis(**overrides):
    base = {"pb_uncovered_exposure": 1000, "blocked_flows": 50,
            "high_risk_lateral_paths": 10, "active_allow_coverage": 0.6,
            "microsegmentation_maturity": 0.5}
    base.update(overrides)
    return base


def test_returns_skipped_when_no_previous():
    out = mod_change_impact.compare(current_kpis=_kpis(), previous=None)
    assert out["skipped"] is True
    assert "no_previous_snapshot" in out["reason"]


def test_detects_improvement():
    previous = {"kpis": _kpis(pb_uncovered_exposure=2000, high_risk_lateral_paths=20)}
    out = mod_change_impact.compare(current_kpis=_kpis(pb_uncovered_exposure=1000,
                                                       high_risk_lateral_paths=10),
                                    previous=previous)
    assert out["overall_verdict"] == "improved"
    deltas = out["deltas"]
    assert deltas["pb_uncovered_exposure"]["delta"] == -1000
    assert deltas["pb_uncovered_exposure"]["direction"] == "improved"


def test_detects_regression():
    previous = {"kpis": _kpis(pb_uncovered_exposure=500, blocked_flows=10)}
    out = mod_change_impact.compare(current_kpis=_kpis(pb_uncovered_exposure=2000, blocked_flows=100),
                                    previous=previous)
    assert out["overall_verdict"] == "regressed"


def test_mixed_returns_mixed():
    previous = {"kpis": _kpis(pb_uncovered_exposure=2000, blocked_flows=10)}
    out = mod_change_impact.compare(current_kpis=_kpis(pb_uncovered_exposure=1000, blocked_flows=100),
                                    previous=previous)
    assert out["overall_verdict"] == "mixed"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_mod_change_impact.py -v
```

- [ ] **Step 3: Implement**

```python
"""Change Impact: compare current report's KPIs to the previous snapshot.

Direction interpretation per KPI:
  pb_uncovered_exposure:    lower is better
  high_risk_lateral_paths:  lower is better
  blocked_flows:            higher = better signal that controls are working,
                            BUT a sudden spike may also indicate an attack.
                            Treat increase as 'improved' for this verdict; the
                            executive narrative discusses the spike separately.
  active_allow_coverage:    higher is better
  microsegmentation_maturity: higher is better
"""
from __future__ import annotations

from typing import Optional

LOWER_BETTER = ("pb_uncovered_exposure", "high_risk_lateral_paths")
HIGHER_BETTER = ("blocked_flows", "active_allow_coverage", "microsegmentation_maturity")


def compare(*, current_kpis: dict, previous: Optional[dict]) -> dict:
    if previous is None:
        return {"skipped": True, "reason": "no_previous_snapshot"}
    prev_kpis = previous.get("kpis", {})
    deltas = {}
    improved_count = 0
    regressed_count = 0
    for k, current in current_kpis.items():
        if not isinstance(current, (int, float)):
            continue
        prev = prev_kpis.get(k)
        if not isinstance(prev, (int, float)):
            continue
        delta = current - prev
        direction = _direction(k, delta)
        if direction == "improved":
            improved_count += 1
        elif direction == "regressed":
            regressed_count += 1
        deltas[k] = {"current": current, "previous": prev, "delta": delta, "direction": direction}
    verdict = _verdict(improved_count, regressed_count)
    return {
        "deltas": deltas,
        "improved_count": improved_count,
        "regressed_count": regressed_count,
        "overall_verdict": verdict,
        "previous_snapshot_at": previous.get("generated_at"),
    }


def _direction(kpi: str, delta: float) -> str:
    if delta == 0:
        return "unchanged"
    if kpi in LOWER_BETTER:
        return "improved" if delta < 0 else "regressed"
    if kpi in HIGHER_BETTER:
        return "improved" if delta > 0 else "regressed"
    return "neutral"


def _verdict(improved, regressed):
    if improved > 0 and regressed == 0:
        return "improved"
    if regressed > 0 and improved == 0:
        return "regressed"
    if improved > 0 and regressed > 0:
        return "mixed"
    return "unchanged"
```

- [ ] **Step 4: Run + commit**

```bash
python3 -m pytest tests/test_mod_change_impact.py -v
git add src/report/analysis/mod_change_impact.py tests/test_mod_change_impact.py
git commit -m "feat(report): mod_change_impact compares current KPIs vs previous snapshot"
```

---

## Task 11: Wire snapshot write + Change Impact rendering

**Files:**
- Modify: `src/report/report_generator.py`
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `src/report/section_guidance.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: At end of Traffic report generation, write snapshot + cleanup**

In `src/report/report_generator.py`, after the report HTML is generated:

```python
from src.report.snapshot_store import write_snapshot, cleanup_old
from src.config import ConfigManager

def generate_traffic_report(..., traffic_report_profile="security_risk", detail_level="standard", ...):
    # ... existing logic ...
    cm = ConfigManager()
    retention = cm.models.report.snapshot_retention_days
    snap = {
        "report_type": "traffic",
        "profile": traffic_report_profile,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_window": {"start": query_context.get("start_date"),
                         "end": query_context.get("end_date")},
        "kpis": exec_summary.get("kpis", {}),
        "policy_changes_since_previous": [],
    }
    write_snapshot("traffic", snap)
    cleanup_old("traffic", retention_days=retention)
```

- [ ] **Step 2: Render Change Impact in exporter**

```python
if visible_in("mod_change_impact", profile, detail_level):
    from src.report.snapshot_store import read_latest
    from src.report.analysis import mod_change_impact
    previous = read_latest("traffic", profile=profile)
    # Note: previous returned BEFORE we write the new snapshot — so it really is "previous"
    impact = mod_change_impact.compare(current_kpis=exec_summary["kpis"], previous=previous)
    if not impact.get("skipped"):
        html_parts.append(render_section_guidance("mod_change_impact", profile, detail_level))
        html_parts.append(f'<h2>{t("rpt_mod_change_impact_title")}</h2>')
        html_parts.append(_render_change_impact_table(impact))
```

(Note ordering: read previous → render section → THEN write new snapshot at end of report_generator. Don't write before reading.)

- [ ] **Step 3: Add 4 guidance keys + section title**

```
rpt_guidance_mod_change_impact_purpose    "Show how key risk metrics changed since the previous report run."
rpt_guidance_mod_change_impact_signals    "Big regressions in PB exposure, lateral paths; or improvements after recent policy changes."
rpt_guidance_mod_change_impact_how        "Each KPI shows previous vs current and direction (improved / regressed / unchanged)."
rpt_guidance_mod_change_impact_actions    "Investigate regressions; document improvements; correlate with audit policy changes."
rpt_mod_change_impact_title               "Change Impact"
```

Register guidance with `profile_visibility=("security_risk", "network_inventory")`, `min_detail_level="standard"`.

- [ ] **Step 4: Test + audit**

```bash
python3 -m pytest tests/test_mod_change_impact.py tests/test_snapshot_store.py -v
python3 scripts/audit_i18n_usage.py
```

- [ ] **Step 5: Commit**

```bash
git add src/report/report_generator.py src/report/exporters/html_exporter.py \
        src/report/section_guidance.py \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): wire snapshot write + Change Impact section"
```

---

## Task 12: `mod_exfiltration_intel` — managed→unmanaged + threat-intel hook

**Files:**
- Create: `src/report/analysis/mod_exfiltration_intel.py`
- Create: `tests/test_mod_exfiltration_intel.py`

- [ ] **Step 1: Write failing test**

```python
"""mod_exfiltration_intel: managed→unmanaged exfiltration + threat intel join."""
import pandas as pd

from src.report.analysis import mod_exfiltration_intel


def _flows_with_exfil():
    return pd.DataFrame([
        {"src": "internal-1", "dst": "203.0.113.50", "port": 443, "bytes": 5_000_000_000,
         "policy_decision": "allowed",
         "src_managed": True, "dst_managed": False},
        {"src": "internal-2", "dst": "203.0.113.51", "port": 443, "bytes": 100_000,
         "policy_decision": "allowed",
         "src_managed": True, "dst_managed": False},
    ])


def test_skipped_when_no_managed_columns():
    out = mod_exfiltration_intel.analyze(pd.DataFrame([{"src": "a", "dst": "b", "port": 80}]))
    assert out.get("skipped") is True


def test_high_volume_exfil_flagged():
    out = mod_exfiltration_intel.analyze(_flows_with_exfil())
    high = out["high_volume_exfil"]
    assert any(r["dst"] == "203.0.113.50" and r["bytes"] >= 1_000_000_000 for r in high)


def test_threat_intel_match(tmp_path):
    intel = tmp_path / "bad_ips.csv"
    intel.write_text("ip,reason\n203.0.113.50,known_c2\n")
    out = mod_exfiltration_intel.analyze(_flows_with_exfil(), threat_intel_csv=str(intel))
    matches = out["threat_intel_matches"]
    assert any(m["dst"] == "203.0.113.50" and m["reason"] == "known_c2" for m in matches)


def test_threat_intel_returns_empty_when_no_csv():
    out = mod_exfiltration_intel.analyze(_flows_with_exfil(), threat_intel_csv=None)
    assert out["threat_intel_matches"] == []
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_mod_exfiltration_intel.py -v
```

- [ ] **Step 3: Implement**

```python
"""Exfiltration & threat-intel analysis.

- Flag managed→unmanaged flows with high byte volume.
- Optional: join against a CSV of known-bad IPs.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

HIGH_VOLUME_THRESHOLD_BYTES = 1_000_000_000  # 1 GB


def analyze(flows_df: pd.DataFrame, *, threat_intel_csv: str | None = None) -> dict:
    if "src_managed" not in flows_df.columns or "dst_managed" not in flows_df.columns:
        return {"skipped": True, "reason": "no managed/unmanaged labels"}
    exfil = flows_df[(flows_df["src_managed"] == True) & (flows_df["dst_managed"] == False)]
    high_vol = []
    if "bytes" in exfil.columns:
        big = exfil[exfil["bytes"] >= HIGH_VOLUME_THRESHOLD_BYTES]
        high_vol = (big.groupby(["src", "dst", "port"])
                    .agg(bytes=("bytes", "sum"), flows=("dst", "count"))
                    .reset_index().sort_values("bytes", ascending=False).head(50)
                    .to_dict("records"))
    return {
        "high_volume_exfil": high_vol,
        "managed_to_unmanaged_count": int(len(exfil)),
        "threat_intel_matches": _threat_intel_join(exfil, threat_intel_csv),
    }


def _threat_intel_join(exfil_df, threat_intel_csv):
    if not threat_intel_csv:
        return []
    p = Path(threat_intel_csv)
    if not p.exists():
        return []
    bad = {}
    with p.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            bad[row["ip"].strip()] = row.get("reason", "unknown").strip()
    if not bad:
        return []
    matches = exfil_df[exfil_df["dst"].isin(bad.keys())]
    out = []
    for _, row in matches.iterrows():
        out.append({"src": row["src"], "dst": row["dst"], "port": int(row.get("port", 0)),
                    "reason": bad.get(row["dst"], "unknown")})
    return out
```

- [ ] **Step 4: Run + commit**

```bash
python3 -m pytest tests/test_mod_exfiltration_intel.py -v
git add src/report/analysis/mod_exfiltration_intel.py tests/test_mod_exfiltration_intel.py
git commit -m "feat(report): mod_exfiltration_intel — high-volume exfil + threat intel hook"
```

---

## Task 13: Register + render `mod_exfiltration_intel`

**Files:**
- Modify: `src/report/analysis/__init__.py`
- Modify: `src/report/section_guidance.py`
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add guidance keys + section title**

```
rpt_guidance_mod_exfil_purpose      "Highlight managed→unmanaged flows with high byte volume; optionally cross-reference threat intel."
rpt_guidance_mod_exfil_signals      "Single destination receiving GBs of data; matches against known-bad IP list."
rpt_guidance_mod_exfil_how          "Rows are dst-IP / port aggregates; flagged rows match the threat intel CSV when configured."
rpt_guidance_mod_exfil_actions      "Investigate as exfil/IR incident; quarantine source; verify destination is sanctioned."
rpt_mod_exfil_title                 "Exfiltration & Threat Intel"
```

Register with `profile_visibility=("security_risk",)`, `min_detail_level="standard"`.

- [ ] **Step 2: Render in exporter**

```python
if visible_in("mod_exfiltration_intel", profile, detail_level):
    from src.report.analysis import mod_exfiltration_intel
    intel_csv = cm.models.report.threat_intel_csv_path  # may be None
    exfil = mod_exfiltration_intel.analyze(flows, threat_intel_csv=intel_csv)
    if not exfil.get("skipped"):
        html_parts.append(render_section_guidance("mod_exfiltration_intel", profile, detail_level))
        html_parts.append(f'<h2>{t("rpt_mod_exfil_title")}</h2>')
        html_parts.append(_render_exfil_section(exfil))
```

- [ ] **Step 3: Test + audit + commit**

```bash
python3 -m pytest tests/test_mod_exfiltration_intel.py -v
python3 scripts/audit_i18n_usage.py
git add src/report/analysis/__init__.py src/report/section_guidance.py \
        src/report/exporters/html_exporter.py \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): integrate mod_exfiltration_intel section"
```

---

## Task 14: End-to-end smoke — generate Traffic report twice, verify Change Impact populates on second run

**Files:**
- Create: `tests/test_r3_e2e.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end: run Traffic report twice, second run should have Change Impact."""
import json
from pathlib import Path

import pandas as pd
import pytest

from src.report.snapshot_store import _BASE_DIR  # type: ignore


@pytest.fixture
def biggish_flows():
    rows = []
    for i in range(50):
        rows.append({
            "src": f"10.0.0.{i}", "dst": f"10.1.0.{i}", "port": 443,
            "policy_decision": ["allowed", "potentially_blocked"][i % 2],
            "src_app": f"app{i % 5}", "dst_app": f"app{(i + 1) % 5}",
        })
    return pd.DataFrame(rows)


def test_change_impact_appears_on_second_run(biggish_flows, tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.snapshot_store._BASE_DIR", str(tmp_path))
    from src.report.exporters.html_exporter import render_traffic_report
    # First run — no previous snapshot exists, Change Impact is skipped/empty.
    html1 = render_traffic_report(biggish_flows, profile="security_risk", detail_level="standard")
    # snapshot should now be written by report_generator path; if render_traffic_report doesn't
    # call write_snapshot, the test must invoke whatever entry point does.
    # ... see report_generator wiring in Task 11.
    # Second run — should compare against first.
    html2 = render_traffic_report(biggish_flows, profile="security_risk", detail_level="standard")
    # Heuristic: second-run HTML should contain the Change Impact section title.
    assert "Change Impact" in html2 or "變化影響" in html2
```

(If `render_traffic_report` does not itself write snapshots — only the higher-level `generate_traffic_report` does — adjust the test to call the higher-level entry point.)

- [ ] **Step 2: Run — adjust until passes**

```bash
python3 -m pytest tests/test_r3_e2e.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_r3_e2e.py
git commit -m "test(report): R3 end-to-end — Change Impact populates on second run"
```

---

## Task 15: Phase R3 verification + version bump

**Files:**
- Modify: `src/__init__.py`

- [ ] **Step 1: Full pytest**

```bash
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: previous baseline + ~25 new tests.

- [ ] **Step 2: i18n audit**

```bash
python3 scripts/audit_i18n_usage.py
python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v
```

- [ ] **Step 3: Generate sample reports**

Run report generation twice (one day apart, or simulate by manually creating an old snapshot). Verify in HTML:
- Draft Actions section appears (Override Deny + Allowed Across Boundary).
- Enforcement Rollout Plan with ranked apps + Top-3 callout.
- Application Ringfence (network_inventory profile).
- Change Impact section with deltas (on second run).
- Exfiltration section if managed/unmanaged labels exist.
- Snapshot file present at `reports/snapshots/traffic/<YYYY-MM-DD>_<profile>.json`.

- [ ] **Step 4: Bump version**

```python
# src/__init__.py
__version__ = "3.20.0-report-intelligence"
```

- [ ] **Step 5: Commit**

```bash
git add src/__init__.py
git commit -m "chore: bump version to 3.20.0-report-intelligence"
```

---

## Self-Review Checklist

- [ ] Spec coverage:
  - G7.a `mod_draft_actions` (Override Deny + Allowed Across Boundary): Tasks 4, 5
  - G7.b `mod_enforcement_rollout`: Tasks 6, 7
  - G7.c `mod_ringfence`: Tasks 8, 9
  - G7.d `mod_change_impact` + snapshot store: Tasks 2, 3, 10, 11, 14
  - G7.e `mod_exfiltration_intel`: Tasks 12, 13
- [ ] All new i18n keys added to BOTH `src/i18n_en.json` and `src/i18n_zh_TW.json` (Tasks 4, 5, 7, 9, 11, 13).
- [ ] Snapshot path `reports/snapshots/traffic/<YYYY-MM-DD>_<profile>.json` matches spec §6.5.
- [ ] Snapshot KPI-only (no raw flows) — Task 11.
- [ ] Snapshot retention default 90 days (configurable via `report.snapshot_retention_days`) — Task 3.
- [ ] mod_draft_actions does NOT duplicate B2.2 mod_draft_summary — distinct scope (actionable vs counts) confirmed in Task 4.
- [ ] Type/name consistency:
  - Module names: `mod_draft_actions`, `mod_enforcement_rollout`, `mod_ringfence`, `mod_change_impact`, `mod_exfiltration_intel` — consistent across tasks.
  - `analyze(flows_df, ...)` signature for each module — consistent.
  - `compare(*, current_kpis, previous)` for change_impact — Task 10, 11.
  - Snapshot fields: `schema_version`, `report_type`, `profile`, `generated_at`, `query_window`, `kpis` — consistent with spec §6.5.
  - `read_latest("traffic", profile=...)` ordering — read BEFORE write_snapshot in Task 11.
- [ ] No TBD/TODO/placeholders — every step has actual code or commands.
- [ ] Tests run after every task that produces them; final pytest gate in Task 15.
- [ ] i18n audit gate present after every task that adds keys; final gate in Task 15.
- [ ] Backward compatibility: prerequisite check at Task 1 prevents accidental run before B2 ships; `draft_actions_enabled` config flag (Task 3) lets users disable if performance becomes an issue (per Spec §9 rollback).
