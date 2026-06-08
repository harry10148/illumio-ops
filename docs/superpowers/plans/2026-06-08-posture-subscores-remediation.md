# Posture Sub-scores + Score-Impact Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing posture score actionable by exposing risk_health's per-axis penalties as 0-100 named sub-scores (D) and deriving a weight-renormalized "fix this → +N points" remediation list (B), surfaced in the existing dashboard modal.

**Architecture:** Two pure derivations over `compute_posture()` output — no new PCE collection, no external deps (air-gap safe). `compute_posture` gains an additive `risk_subscores` field; a new `posture_advisor.build_remediation()` ranks recoverable points; both are wired into the existing dashboard route + scheduler consumers (which the report path already reuses via `run_posture_summary`), then rendered in the existing posture modal.

**Tech Stack:** Python 3.10+, pytest, Flask (existing GUI), vanilla JS (dashboard.js), JSON i18n (EN + ZH_TW).

**Spec:** `docs/superpowers/specs/2026-06-08-posture-subscores-remediation-design.md`

**Deliberate refinements to the spec (disclosed):**
1. `build_remediation(posture)` drops the `lang` param — it returns i18n **keys**, not rendered text (rendering happens at the presentation layer), so `lang` would be unused.
2. Dedicated `evidence_key`/`evidence_args` fields are omitted; each item's `current`/`target` values convey magnitude and `recommendation_key` carries guidance. (YAGNI; can be added later.)
3. Per-axis sub-score omission when a signal is absent (spec §3.3) is implemented via per-axis availability checks.
4. No separate report-engine task: `report_generator.py` refreshes posture by calling `run_posture_summary` (line 503-504), so wiring remediation into that scheduler function (Task 3) covers the report path too.

---

### Task 1: D — add `risk_subscores` to `compute_posture`

**Files:**
- Modify: `src/report/posture.py` (risk signal block ~136-148; risk_health component ~213-230)
- Test: `tests/test_posture.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_posture.py`:

```python
def _risk_kpis():
    """Synthetic snapshot with all three risk signals present (deterministic)."""
    return {
        "enforced_coverage_pct": 80.0,
        "maturity_score": 70.0,
        "risk_flows_total": 4,          # ransomware_apps=4 → pts=min(40,20)=20 → value=50
        "true_gap_pct": 20.0,           # uncovered_pts=min(30,10)=10 → value=round(100*(1-10/30))=67
        "maturity_dimensions": {
            "lateral_movement_control": {"ratio": 0.5},  # lateral_pts=round(0.5*30)=15 → value=50
        },
    }


class TestRiskSubscores:
    def _risk_component(self, kpis):
        result = compute_posture(kpis)
        return next(c for c in result["components"] if c["key"] == "risk_health")

    def test_all_three_subscores_present_with_expected_values(self):
        rh = self._risk_component(_risk_kpis())
        subs = {s["key"]: s for s in rh["risk_subscores"]}
        assert subs["ransomware_containment"]["value"] == 50
        assert subs["ransomware_containment"]["penalty_points"] == 20
        assert subs["ransomware_containment"]["max_penalty"] == 40
        assert subs["lateral_containment"]["value"] == 50
        assert subs["lateral_containment"]["penalty_points"] == 15
        assert subs["flow_coverage"]["value"] == 67
        assert subs["flow_coverage"]["penalty_points"] == 10

    def test_absent_signal_omits_its_subscore(self):
        # Only ransomware signal present; lateral ratio + gap absent.
        kpis = {"enforced_coverage_pct": 80.0, "maturity_score": 70.0,
                "risk_flows_total": 4}
        rh = self._risk_component(kpis)
        keys = {s["key"] for s in rh["risk_subscores"]}
        assert keys == {"ransomware_containment"}

    def test_existing_keys_unchanged(self):
        rh = self._risk_component(_risk_kpis())
        for k in ("key", "label_key", "value", "unit", "weight",
                  "effective_weight", "points", "note_key", "detail"):
            assert k in rh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_posture.py::TestRiskSubscores -v`
Expected: FAIL with `KeyError: 'risk_subscores'`.

- [ ] **Step 3: Track per-axis availability for the uncovered signal**

In `src/report/posture.py`, replace the uncovered block (currently lines ~136-148):

```python
    # uncovered_pct: true_gap_pct (% of flows with no policy) or pb_uncovered
    uncovered_pct: float = 0.0
    tgp = _get_float(kpis, "true_gap_pct")
    if tgp is not None:
        uncovered_pct = float(tgp)
    else:
        flat_kpis = kpis.get("kpis") or {}
        if isinstance(flat_kpis, dict):
            pb = _get_float(flat_kpis, "pb_uncovered_exposure")
            if pb is not None:
                # Convert raw flow count to an approximate percentage (capped at 100)
                total = _get_float(kpis, "total_flows") or 1.0
                uncovered_pct = min(100.0, float(pb) / float(total) * 100.0)
```

with (adds `uncovered_avail`):

```python
    # uncovered_pct: true_gap_pct (% of flows with no policy) or pb_uncovered
    uncovered_pct: float = 0.0
    uncovered_avail = False
    tgp = _get_float(kpis, "true_gap_pct")
    if tgp is not None:
        uncovered_pct = float(tgp)
        uncovered_avail = True
    else:
        flat_kpis = kpis.get("kpis") or {}
        if isinstance(flat_kpis, dict):
            pb = _get_float(flat_kpis, "pb_uncovered_exposure")
            if pb is not None:
                # Convert raw flow count to an approximate percentage (capped at 100)
                total = _get_float(kpis, "total_flows") or 1.0
                uncovered_pct = min(100.0, float(pb) / float(total) * 100.0)
                uncovered_avail = True
```

- [ ] **Step 4: Build and attach `risk_subscores` inside the risk_health component**

In `src/report/posture.py`, replace the risk_health append block (currently lines ~213-230):

```python
    if has_risk:
        rh_points = round(eff_rsk * risk_health, 2)
        components.append({
            "key": "risk_health",
            "label_key": "gui_posture_risk_health",
            "value": round(risk_health, 1),
            "unit": "%",
            "weight": 0.4,
            "effective_weight": round(eff_rsk, 3),
            "points": rh_points,
            "note_key": "gui_posture_risk_health_note",
            "detail": {
                "ransomware_apps": ransomware_apps,
                "lateral_control_ratio": round(lateral_control_ratio, 4),
                "uncovered_pct": round(uncovered_pct, 2),
                "penalty": round(penalty, 1),
            },
        })
```

with (adds `risk_subscores`, one entry per available axis):

```python
    if has_risk:
        rh_points = round(eff_rsk * risk_health, 2)
        risk_subscores = []
        if rft is not None:
            risk_subscores.append({
                "key": "ransomware_containment",
                "label_key": "gui_posture_sub_ransomware",
                "value": round(100.0 * (1.0 - ransomware_pts / 40.0)),
                "unit": "%",
                "penalty_points": round(ransomware_pts, 2),
                "max_penalty": 40,
            })
        if lm.get("ratio") is not None:
            risk_subscores.append({
                "key": "lateral_containment",
                "label_key": "gui_posture_sub_lateral",
                "value": round(100.0 * (1.0 - lateral_pts / 30.0)),
                "unit": "%",
                "penalty_points": round(lateral_pts, 2),
                "max_penalty": 30,
            })
        if uncovered_avail:
            risk_subscores.append({
                "key": "flow_coverage",
                "label_key": "gui_posture_sub_coverage",
                "value": round(100.0 * (1.0 - uncovered_pts / 30.0)),
                "unit": "%",
                "penalty_points": round(uncovered_pts, 2),
                "max_penalty": 30,
            })
        components.append({
            "key": "risk_health",
            "label_key": "gui_posture_risk_health",
            "value": round(risk_health, 1),
            "unit": "%",
            "weight": 0.4,
            "effective_weight": round(eff_rsk, 3),
            "points": rh_points,
            "note_key": "gui_posture_risk_health_note",
            "risk_subscores": risk_subscores,
            "detail": {
                "ransomware_apps": ransomware_apps,
                "lateral_control_ratio": round(lateral_control_ratio, 4),
                "uncovered_pct": round(uncovered_pct, 2),
                "penalty": round(penalty, 1),
            },
        })
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_posture.py -v`
Expected: PASS (new `TestRiskSubscores` + all pre-existing posture tests).

- [ ] **Step 6: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/posture.py tests/test_posture.py
git commit -m "feat(posture): expose risk_health per-axis containment sub-scores"
```

---

### Task 2: B — `posture_advisor.build_remediation`

**Files:**
- Create: `src/report/posture_advisor.py`
- Test: `tests/test_posture_advisor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_posture_advisor.py`:

```python
"""Tests for score-impact remediation advisor (pure derivation)."""
from __future__ import annotations

from src.report.posture import compute_posture
from src.report.posture_advisor import build_remediation


def _risk_kpis():
    return {
        "enforced_coverage_pct": 80.0,   # coverage value 80 → recoverable 0.3*20=6.0
        "maturity_score": 70.0,          # readiness value 70 → recoverable 0.3*30=9.0
        "risk_flows_total": 4,           # ransomware pts 20 → recoverable 0.4*20=8.0
        "true_gap_pct": 20.0,            # flow_coverage pts 10 → recoverable 0.4*10=4.0
        "maturity_dimensions": {
            "lateral_movement_control": {"ratio": 0.5},  # lateral pts 15 → 0.4*15=6.0
        },
    }


def test_ranked_by_recoverable_points_desc():
    posture = compute_posture(_risk_kpis())
    items = build_remediation(posture)
    assert [i["key"] for i in items] == [
        "readiness", "ransomware_containment", "coverage",
        "lateral_containment", "flow_coverage",
    ]
    assert items[0]["recoverable_points"] == 9.0
    assert items[1]["recoverable_points"] == 8.0


def test_item_shape():
    posture = compute_posture(_risk_kpis())
    top = build_remediation(posture)[0]
    assert top["label_key"]
    assert top["target"] == 100
    assert "recommendation_key" in top
    assert isinstance(top["current"], (int, float))


def test_perfect_axis_excluded():
    # coverage already 100 → no coverage remediation item.
    kpis = dict(_risk_kpis(), enforced_coverage_pct=100.0)
    items = build_remediation(compute_posture(kpis))
    assert all(i["key"] != "coverage" for i in items)


def test_unavailable_posture_returns_empty():
    assert build_remediation({"available": False}) == []
    assert build_remediation({}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_posture_advisor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.posture_advisor'`.

- [ ] **Step 3: Write the implementation**

Create `src/report/posture_advisor.py`:

```python
"""Score-impact remediation advisor.

PURE derivation over compute_posture() output (no I/O). Turns the posture
breakdown into a ranked "fix this → +N points" list. Each item's
``recoverable_points`` is how much the overall (weight-renormalized) posture
score would rise if that axis were brought to 100, reusing the
``effective_weight`` already computed by compute_posture().

Returns i18n KEYS, not rendered text — the presentation layer renders them.
"""
from __future__ import annotations

# Risk sub-score key → recommendation i18n key
_RISK_REC = {
    "ransomware_containment": "gui_posture_rmd_ransomware",
    "lateral_containment": "gui_posture_rmd_lateral",
    "flow_coverage": "gui_posture_rmd_coverage",
}
# Top-level component key → recommendation i18n key
_COMPONENT_REC = {
    "coverage": "gui_posture_rmd_policy_coverage",
    "readiness": "gui_posture_rmd_readiness",
}


def build_remediation(posture: dict) -> list[dict]:
    """Return remediation items sorted by recoverable_points (desc)."""
    if not posture or not posture.get("available"):
        return []

    items: list[dict] = []
    for comp in posture.get("components") or []:
        key = comp.get("key")
        eff = comp.get("effective_weight") or 0.0

        if key in ("coverage", "readiness"):
            value = comp.get("value")
            if value is None:
                continue
            recoverable = eff * (100.0 - value)
            if recoverable <= 0:
                continue
            items.append({
                "key": key,
                "label_key": comp.get("label_key"),
                "recoverable_points": round(recoverable, 1),
                "current": round(value, 1),
                "target": 100,
                "recommendation_key": _COMPONENT_REC.get(key, ""),
            })

        elif key == "risk_health":
            for sub in comp.get("risk_subscores") or []:
                pts = sub.get("penalty_points") or 0.0
                recoverable = eff * pts
                if recoverable <= 0:
                    continue
                items.append({
                    "key": sub.get("key"),
                    "label_key": sub.get("label_key"),
                    "recoverable_points": round(recoverable, 1),
                    "current": sub.get("value"),
                    "target": 100,
                    "recommendation_key": _RISK_REC.get(sub.get("key"), ""),
                })

    items.sort(key=lambda x: x["recoverable_points"], reverse=True)
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_posture_advisor.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/posture_advisor.py tests/test_posture_advisor.py
git commit -m "feat(posture): add score-impact remediation advisor"
```

---

### Task 3: Wire remediation into dashboard route + scheduler

**Files:**
- Modify: `src/gui/routes/dashboard.py` (`_overview_posture`, ~184-206)
- Modify: `src/scheduler/jobs.py` (`run_posture_summary`, ~258-271)
- Test: `tests/test_posture_advisor.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_posture_advisor.py`:

```python
from unittest.mock import patch


def test_overview_posture_attaches_remediation():
    from src.gui.routes.dashboard import _overview_posture
    snap = {"kpis": _risk_kpis(), "generated_at": "2026-06-08T00:00:00Z"}
    with patch("src.report.snapshot_store.read_latest", return_value=snap):
        result = _overview_posture({})
    assert result.get("available") is True
    assert "remediation" in result
    assert result["remediation"][0]["key"] == "readiness"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_posture_advisor.py::test_overview_posture_attaches_remediation -v`
Expected: FAIL with `KeyError: 'remediation'` (or assertion error — key missing).

- [ ] **Step 3: Attach remediation in `_overview_posture`**

In `src/gui/routes/dashboard.py`, replace the body of `_overview_posture` (the `try`/fallback block, ~194-206):

```python
    try:
        from src.report.snapshot_store import read_latest
        from src.report.posture import compute_posture
        snap = read_latest("traffic")
        if snap:
            p = compute_posture(snap.get("kpis") or snap)
            if p.get("available"):
                p["source_date"] = snap.get("generated_at", "")
                return p
    except Exception:
        pass
    ps = state.get("posture_summary")
    if isinstance(ps, dict) and ("score" in ps or ps.get("available") is False):
        return ps
    return {"available": False}
```

with:

```python
    try:
        from src.report.snapshot_store import read_latest
        from src.report.posture import compute_posture
        from src.report.posture_advisor import build_remediation
        snap = read_latest("traffic")
        if snap:
            p = compute_posture(snap.get("kpis") or snap)
            if p.get("available"):
                p["source_date"] = snap.get("generated_at", "")
                p["remediation"] = build_remediation(p)
                return p
    except Exception:
        pass
    ps = state.get("posture_summary")
    if isinstance(ps, dict) and ("score" in ps or ps.get("available") is False):
        if ps.get("available") and "remediation" not in ps:
            try:
                from src.report.posture_advisor import build_remediation
                ps["remediation"] = build_remediation(ps)
            except Exception:
                pass
        return ps
    return {"available": False}
```

- [ ] **Step 4: Attach remediation in `run_posture_summary`**

In `src/scheduler/jobs.py`, find (in `run_posture_summary`, ~267-269):

```python
        posture = compute_posture(snap.get("kpis") or snap)
        posture["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        posture["source_date"] = snap.get("generated_at", "")
```

and replace with:

```python
        from src.report.posture_advisor import build_remediation
        posture = compute_posture(snap.get("kpis") or snap)
        posture["remediation"] = build_remediation(posture)
        posture["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        posture["source_date"] = snap.get("generated_at", "")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_posture_advisor.py tests/test_dashboard_overview.py -v`
Expected: PASS (new wiring test + pre-existing overview tests still green).

- [ ] **Step 6: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/gui/routes/dashboard.py src/scheduler/jobs.py tests/test_posture_advisor.py
git commit -m "feat(posture): surface remediation list in dashboard route + scheduler"
```

---

### Task 4: i18n keys (EN + ZH_TW)

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`

- [ ] **Step 1: Add the new keys to `src/i18n_en.json`**

Insert these keys in alphabetical position within the existing `gui_posture_*` block (after `gui_posture_risk_health_note`, line ~1576). All start with the `gui_` strict prefix:

```json
  "gui_posture_rmd_coverage": "Close uncovered flows: write policy for unmatched traffic to remove visibility gaps.",
  "gui_posture_rmd_lateral": "Contain lateral movement: enforce east-west segmentation between application tiers.",
  "gui_posture_rmd_points": "Potential gain",
  "gui_posture_rmd_policy_coverage": "Increase Policy coverage: move more Workloads into enforced Policy.",
  "gui_posture_rmd_ransomware": "Reduce Ransomware exposure: Ringfence high-risk Apps and restrict RDP/SMB to explicit allowlists.",
  "gui_posture_rmd_readiness": "Improve Enforcement readiness: advance Workloads from visibility-only to full Enforcement.",
  "gui_posture_rmd_title": "Priority Remediation",
  "gui_posture_sub_coverage": "Flow Coverage",
  "gui_posture_sub_lateral": "Lateral Containment",
  "gui_posture_sub_ransomware": "Ransomware Containment",
  "gui_posture_sub_title": "Risk Sub-scores",
```

- [ ] **Step 2: Add the SAME keys to `src/i18n_zh_TW.json`**

Insert in the same alphabetical position. Glossary terms (Ransomware, Ringfence, App, Workload, Policy, Enforcement, RDP/SMB) are kept in English per `src/i18n/data/glossary.json`:

```json
  "gui_posture_rmd_coverage": "補上未覆蓋流量：為未匹配流量撰寫 Policy 以消除可視性缺口。",
  "gui_posture_rmd_lateral": "遏制橫向移動：在各 App 層級間強制東西向分段。",
  "gui_posture_rmd_points": "可回收分數",
  "gui_posture_rmd_policy_coverage": "提高 Policy 覆蓋：將更多 Workload 納入 Enforcement Policy。",
  "gui_posture_rmd_ransomware": "降低 Ransomware 暴露：對高風險 App 做 Ringfence，並將 RDP/SMB 收斂為明確 allowlist。",
  "gui_posture_rmd_readiness": "提升 Enforcement 就緒度：將 Workload 從僅可視推進到完整 Enforcement。",
  "gui_posture_rmd_title": "優先修補",
  "gui_posture_sub_coverage": "流量覆蓋度",
  "gui_posture_sub_lateral": "橫向移動遏制度",
  "gui_posture_sub_ransomware": "Ransomware 遏制度",
  "gui_posture_sub_title": "風險子分數",
```

- [ ] **Step 3: Verify i18n parity + glossary**

Run: `cd /home/harry/rd/illumio-ops && python scripts/audit_i18n_usage.py`
Expected: no NEW parity (Cat I) or glossary (Cat E) failures for the `gui_posture_rmd_*` / `gui_posture_sub_*` keys. If the audit flags a glossary violation, edit the ZH_TW value to preserve the flagged English term, then re-run.

- [ ] **Step 4: Run the i18n test suite**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_i18n_audit.py tests/test_i18n_glossary.py -v`
Expected: PASS (no new failures introduced by the added keys).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/i18n_en.json src/i18n_zh_TW.json
git commit -m "i18n(posture): add sub-score + remediation strings (EN/ZH_TW)"
```

---

### Task 5: Render sub-scores + remediation in the posture modal

**Files:**
- Modify: `src/templates/index.html` (the `m-posture-score` modal body — after the `ov-posture-risk-detail` element)
- Modify: `src/static/js/dashboard.js` (`_renderPostureHero`, ~1293-1323)

> Note: front-end rendering is verified manually (the JS layer is not covered by pytest). The data it renders is already verified by Tasks 1-3.

- [ ] **Step 1: Add modal containers in `index.html`**

Locate the posture modal element that holds the risk detail. Run:
`cd /home/harry/rd/illumio-ops && grep -n 'ov-posture-risk-detail' src/templates/index.html`

Immediately AFTER the element with `id="ov-posture-risk-detail"`, insert:

```html
        <div id="ov-posture-subscores" style="margin-top:14px"></div>
        <div id="ov-posture-remediation" style="margin-top:14px"></div>
```

(Match the surrounding indentation of the modal body.)

- [ ] **Step 2: Render the sub-scores table + remediation list in `dashboard.js`**

In `src/static/js/dashboard.js`, find the end of the risk-detail population block inside `_renderPostureHero` — the lines that populate `ov-posture-risk-detail` (~1310-1323), ending before the function's closing `}`. After that block (and before the function returns/closes), insert:

```javascript
  // Risk sub-scores table (D)
  var subEl = document.getElementById('ov-posture-subscores');
  if (subEl) {
    var rhSub = (Array.isArray(posture.components) ? posture.components : [])
      .find(function (c) { return c.key === 'risk_health'; });
    var subs = (rhSub && Array.isArray(rhSub.risk_subscores)) ? rhSub.risk_subscores : [];
    if (subs.length) {
      var sh = '<div class="posture-sub-title">'
             + T('gui_posture_sub_title', 'Risk Sub-scores') + '</div>';
      subs.forEach(function (s) {
        sh += '<div class="posture-sub-row">'
            + '<span class="posture-sub-k">' + T(s.label_key, s.key) + '</span>'
            + '<span class="posture-sub-v">' + s.value + '%</span>'
            + '</div>';
      });
      subEl.innerHTML = sh;
    } else {
      subEl.innerHTML = '';
    }
  }

  // Priority remediation list (B)
  var remEl = document.getElementById('ov-posture-remediation');
  if (remEl) {
    var rem = Array.isArray(posture.remediation) ? posture.remediation : [];
    if (rem.length) {
      var rhtml = '<div class="posture-sub-title">'
                + T('gui_posture_rmd_title', 'Priority Remediation') + '</div>';
      rem.forEach(function (r) {
        rhtml += '<div class="posture-rmd-row">'
              + '<span class="posture-rmd-gain">+' + r.recoverable_points + '</span> '
              + '<span class="posture-rmd-text">' + T(r.recommendation_key, T(r.label_key, r.key)) + '</span>'
              + '</div>';
      });
      remEl.innerHTML = rhtml;
    } else {
      remEl.innerHTML = '';
    }
  }
```

- [ ] **Step 3: Add minimal styling in `index.html`**

In the `<style>` block near the other `.posture-*` rules (~620-627), add:

```css
      #p-dashboard .posture-sub-title { font-size:12px; color:var(--dim); margin-bottom:6px; font-weight:600; }
      #p-dashboard .posture-sub-row, #p-dashboard .posture-rmd-row { display:flex; gap:10px; padding:3px 0; font-size:13px; }
      #p-dashboard .posture-sub-row .posture-sub-v { margin-left:auto; font-variant-numeric:tabular-nums; }
      #p-dashboard .posture-rmd-row .posture-rmd-gain { color:var(--color-success,#16a34a); font-variant-numeric:tabular-nums; min-width:40px; }
```

- [ ] **Step 4: Manual verification**

Run the GUI and open the posture modal:

```bash
cd /home/harry/rd/illumio-ops && python illumio-ops.py --gui --port 5001
```

In a browser at `https://127.0.0.1:5001`: log in, go to the dashboard, click the posture-score info button (opens `m-posture-score`). Verify:
- A "Risk Sub-scores" section lists ransomware/lateral/flow containment with 0-100 values.
- A "Priority Remediation" section lists items ordered by `+N` gain, highest first.
- (If posture shows "unavailable", run a traffic/security report first to populate the snapshot.)

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/templates/index.html src/static/js/dashboard.js
git commit -m "feat(posture): render sub-scores + remediation in posture modal"
```

---

## Final Verification

- [ ] **Run the full posture + i18n + dashboard test scope**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_posture.py tests/test_posture_advisor.py tests/test_dashboard_overview.py tests/test_i18n_audit.py tests/test_i18n_glossary.py -v`
Expected: all PASS.

- [ ] **Confirm backward compatibility**

`compute_posture` still returns `score`, `available`, `formula`, `components`; the risk_health component still carries `detail`. The two existing consumers (`dashboard.py:_overview_posture`, `scheduler/jobs.py:run_posture_summary`) only gained an additive `remediation` key.

---

## Self-Review Notes (author)

- **Spec coverage:** D → Task 1; B → Task 2; placement (dashboard modal) → Tasks 3+5; report path → covered by Task 3 (report_generator reuses run_posture_summary); i18n → Task 4; tests → each task + Final Verification. All spec sections mapped.
- **Type consistency:** `risk_subscores` entry shape (key/label_key/value/unit/penalty_points/max_penalty) is produced in Task 1 and consumed in Task 2 (`penalty_points`) and Task 5 (`value`, `label_key`). Remediation item shape (key/label_key/recoverable_points/current/target/recommendation_key) produced in Task 2, consumed in Task 5 (`recoverable_points`, `recommendation_key`, `label_key`). Consistent.
- **Placeholders:** none — every code/step has concrete content.
