# Report R0+R1 — Semantics, Reader Guide, Profile Split

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `potentially_blocked` semantic incorrectness, add a uniform per-section reader-guide framework across all four reports, and split the Traffic report into `security_risk` and `network_inventory` profiles sharing one analysis pipeline.

**Architecture:** Phase R0 builds infrastructure (section_guidance registry + reader-guide rendering across 4 HTML exporters) and adds guidance content for high-priority modules. Phase R1 corrects PB semantics across mod03/mod12/mod13/html_exporter/docs, redesigns the executive summary into 6+6 profile-specific KPIs (with `staged_coverage` deprecated alias), fixes the Date Range fallback, and adds the `traffic_report_profile` parameter to gate which sections each profile sees. Same DataFrames flow through both profiles; only the exporter selects sections.

**Tech Stack:** Python 3.11, pandas, Flask, vanilla JS, Plotly, existing report exporters, pytest, i18n pipeline (`src/i18n_en.json` + `src/i18n_zh_TW.json`).

**Spec:** `docs/superpowers/specs/2026-04-25-report-content-optimization-design.md`

**Prerequisite:** policy-decision-alignment B1+B2+B3 (v3.15/v3.16/v3.17) merged. This phase does NOT touch draft_policy_decision modules — those are owned by B2.

**Branch:** `feat/report-r01-semantics`
**Target tag:** `v3.18.0-report-semantics`
**Baseline (record at start):** Run `python3 -m pytest tests/ -q` and write the count here. Spec baseline reference: 582 passed + 1 skipped (post-Phase 15). Target after this plan: ~620 passed.

---

## File Structure

### New files

| Path | Responsibility |
|------|----------------|
| `src/report/section_guidance.py` | Registry of `module_id → guidance fields` (i18n keys + visibility rules). |
| `tests/test_section_guidance.py` | Registry validation: keys exist, profile rules consistent. |
| `tests/test_pb_semantics.py` | Asserts PB increases uncovered exposure, never readiness. |
| `tests/test_traffic_profile_split.py` | Generates Traffic report twice (security_risk, network_inventory) and diffs sections. |
| `tests/test_executive_kpis.py` | Asserts the 6+6 KPI fields exist with correct names per profile. |
| `tests/test_date_range_fallback.py` | Asserts query_context dates are used when first/last_detected missing. |

### Modified files

| Path | Change |
|------|--------|
| `src/report/analysis/mod03_uncovered_flows.py` | Rename internal "staged" semantics; PB counted as uncovered exposure. |
| `src/report/analysis/mod12_executive_summary.py` | Replace ad-hoc KPIs with 6+6 named KPIs; add Top-3-Actions block; profile-aware. |
| `src/report/analysis/mod13_readiness.py` | PB does NOT contribute to readiness; rename rendered label, keep field alias. |
| `src/report/analysis/mod01_traffic_overview.py` | Date Range falls back to query_context when first/last_detected missing. |
| `src/report/report_generator.py` | Accept `traffic_report_profile` parameter; default `security_risk`; pass to exporter. |
| `src/report/exporters/html_exporter.py` | (1) Reader-guide rendering. (2) PB wording. (3) B003/L008 rule descriptions. (4) Profile-driven section selection. |
| `src/report/exporters/audit_html_exporter.py` | Reader-guide rendering. |
| `src/report/exporters/policy_usage_html_exporter.py` | Reader-guide rendering. |
| `src/report/exporters/ven_html_exporter.py` | Reader-guide rendering. |
| `src/report/dashboard_summaries.py` | Mirror new KPI fields; preserve `staged_coverage` alias. |
| `src/report/report_metadata.py` | Mirror new KPI fields if metadata summary needs them. |
| `docs/Security_Rules_Reference.md` | Update PB language; B003/L008 descriptions. |
| `docs/Security_Rules_Reference_zh.md` | Same in zh-TW. |
| `docs/report_module_inventory_zh.md` | Verify against current code; mark any deltas. |
| `src/i18n_en.json` | +~40 new keys (guidance for 12 modules + KPI labels + new wording). |
| `src/i18n_zh_TW.json` | Same keys in zh-TW. |
| `src/__init__.py` | Bump `__version__` to `3.18.0-report-semantics` at end of phase. |

---

## Task 1: Capture baseline test count

**Files:** none (read-only)

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/ -q 2>&1 | tail -5
```

- [ ] **Step 2: Record numbers**

Note the `N passed, M skipped` count in this task header (edit the Baseline line at the top of this plan).

- [ ] **Step 3: Run i18n audit baseline**

```bash
python3 scripts/audit_i18n_usage.py
```

Expected: A–I = 0 findings (clean baseline). If any pre-existing findings appear, record them so they can be excluded from later regression checks.

---

## Task 2: Verify module inventory against current code

**Files:**
- Modify (if drift): `docs/report_module_inventory_zh.md`

- [ ] **Step 1: List actual modules in tree**

```bash
ls /mnt/d/RD/illumio_ops/src/report/analysis/
ls /mnt/d/RD/illumio_ops/src/report/analysis/audit/
ls /mnt/d/RD/illumio_ops/src/report/analysis/policy_usage/ 2>/dev/null || true
```

- [ ] **Step 2: Cross-check inventory file**

Open `docs/report_module_inventory_zh.md`. For each module listed, confirm the source file exists with the expected name. Flag any mismatches in a new "## Drift" section at the bottom of the inventory file.

- [ ] **Step 3: Resolve drift**

If a listed module has been renamed, update the inventory entry to match. If a listed module was removed, mark it `removed (YYYY-MM-DD)`.

- [ ] **Step 4: Commit only if changes were made**

```bash
git add docs/report_module_inventory_zh.md
git commit -m "docs(report): reconcile module inventory with current src/report/analysis/"
```

If no changes, skip the commit.

---

## Task 3: Create `section_guidance.py` registry skeleton

**Files:**
- Create: `src/report/section_guidance.py`
- Create: `tests/test_section_guidance.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_section_guidance.py`:

```python
"""Validates the section_guidance registry shape and internal consistency."""
import json
from pathlib import Path

import pytest

from src.report.section_guidance import (
    SectionGuidance, REGISTRY, get_guidance, ProfileVisibility, DetailLevel,
)


def test_registry_is_a_dict_keyed_by_module_id():
    assert isinstance(REGISTRY, dict)
    assert all(isinstance(k, str) for k in REGISTRY)


def test_each_entry_is_section_guidance_instance():
    for module_id, entry in REGISTRY.items():
        assert isinstance(entry, SectionGuidance), f"{module_id} not SectionGuidance"


def test_guidance_fields_are_i18n_keys():
    for module_id, entry in REGISTRY.items():
        for fld in ("purpose_key", "watch_signals_key", "how_to_read_key", "recommended_actions_key"):
            v = getattr(entry, fld)
            assert isinstance(v, str) and len(v) > 0, f"{module_id}.{fld} empty"
            assert v.startswith("rpt_guidance_"), f"{module_id}.{fld} bad prefix: {v}"


def test_profile_visibility_values_are_valid():
    valid = {"security_risk", "network_inventory"}
    for module_id, entry in REGISTRY.items():
        for p in entry.profile_visibility:
            assert p in valid, f"{module_id} bad profile: {p}"


def test_min_detail_level_is_valid():
    valid = {"executive", "standard", "full"}
    for module_id, entry in REGISTRY.items():
        assert entry.min_detail_level in valid


def test_get_guidance_returns_none_for_unknown():
    assert get_guidance("no_such_module") is None


def test_get_guidance_returns_entry_for_known():
    # Pick any registered module from the registry.
    if not REGISTRY:
        pytest.skip("registry empty in this phase task")
    sample_id = next(iter(REGISTRY))
    g = get_guidance(sample_id)
    assert g is not None
    assert g.module_id == sample_id


def test_all_referenced_i18n_keys_exist_in_both_locales():
    en = json.loads(Path("src/i18n_en.json").read_text())
    zh = json.loads(Path("src/i18n_zh_TW.json").read_text())
    missing_en, missing_zh = [], []
    for module_id, entry in REGISTRY.items():
        for fld in ("purpose_key", "watch_signals_key", "how_to_read_key", "recommended_actions_key"):
            key = getattr(entry, fld)
            if key not in en: missing_en.append(f"{module_id}.{fld}={key}")
            if key not in zh: missing_zh.append(f"{module_id}.{fld}={key}")
    assert not missing_en, f"missing in i18n_en.json: {missing_en}"
    assert not missing_zh, f"missing in i18n_zh_TW.json: {missing_zh}"
```

- [ ] **Step 2: Run — expect FAIL (module missing)**

```bash
python3 -m pytest tests/test_section_guidance.py -v
```

Expected: all FAIL with `ModuleNotFoundError: src.report.section_guidance`.

- [ ] **Step 3: Implement `src/report/section_guidance.py`**

```python
"""Section reader-guide registry.

Each entry maps a report module id to i18n keys for the four guidance fields
(purpose / watch_signals / how_to_read / recommended_actions) plus visibility
rules (which profile this section appears in, minimum detail_level).

Renderers query this registry via `get_guidance(module_id)` and render the
guidance card before the section content.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

ProfileVisibility = Literal["security_risk", "network_inventory"]
DetailLevel = Literal["executive", "standard", "full"]
Audience = Literal["security", "network", "platform", "app_owner", "executive", "mixed"]


@dataclass(frozen=True)
class SectionGuidance:
    module_id: str
    purpose_key: str
    watch_signals_key: str
    how_to_read_key: str
    recommended_actions_key: str
    primary_audience: Audience = "mixed"
    profile_visibility: tuple[ProfileVisibility, ...] = ("security_risk", "network_inventory")
    min_detail_level: DetailLevel = "standard"


# Registry — module_id → SectionGuidance.
# Populated by Tasks 8-11; this skeleton starts empty.
REGISTRY: dict[str, SectionGuidance] = {}


def get_guidance(module_id: str) -> Optional[SectionGuidance]:
    """Return guidance for a module, or None if not registered."""
    return REGISTRY.get(module_id)


def visible_in(module_id: str, profile: ProfileVisibility, detail_level: DetailLevel) -> bool:
    """Return True if the section should render in the given profile + detail."""
    g = REGISTRY.get(module_id)
    if g is None:
        return True  # unregistered modules render by default; fix by registering
    if profile not in g.profile_visibility:
        return False
    order = ("executive", "standard", "full")
    return order.index(detail_level) >= order.index(g.min_detail_level)
```

- [ ] **Step 4: Run tests — PASS**

```bash
python3 -m pytest tests/test_section_guidance.py -v
```

Expected: all PASS (registry empty so most tests pass trivially; `test_get_guidance_returns_entry_for_known` will skip per the `pytest.skip`).

- [ ] **Step 5: Commit**

```bash
git add src/report/section_guidance.py tests/test_section_guidance.py
git commit -m "feat(report): add section_guidance registry skeleton"
```

---

## Task 4: Wire reader-guide rendering into Traffic HTML exporter

**Files:**
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json` (add `rpt_guidance_purpose_label` etc.)
- Create: `tests/test_reader_guide_render.py`

- [ ] **Step 1: Add base i18n keys for the guide block**

In `src/i18n_en.json` and `src/i18n_zh_TW.json`, add:

```
rpt_guidance_purpose_label              "Purpose" / "本章目的"
rpt_guidance_watch_signals_label        "Watch signals" / "要注意的訊號"
rpt_guidance_how_to_read_label          "How to read" / "判讀方式"
rpt_guidance_recommended_actions_label  "Recommended actions" / "建議行動"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_reader_guide_render.py`:

```python
"""Reader-guide rendering: when a module has registered guidance, the HTML
section starts with a guidance card that includes the four labels."""
from src.report.exporters.html_exporter import render_section_guidance


def test_returns_empty_when_module_unregistered():
    assert render_section_guidance("nope_unknown_mod", profile="security_risk",
                                    detail_level="standard") == ""


def test_returns_card_when_registered(monkeypatch):
    from src.report import section_guidance as sg
    fake = sg.SectionGuidance(
        module_id="demo",
        purpose_key="rpt_guidance_demo_purpose",
        watch_signals_key="rpt_guidance_demo_signals",
        how_to_read_key="rpt_guidance_demo_how",
        recommended_actions_key="rpt_guidance_demo_actions",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="standard",
    )
    monkeypatch.setitem(sg.REGISTRY, "demo", fake)
    html = render_section_guidance("demo", profile="security_risk",
                                    detail_level="standard")
    assert "Purpose" in html or "本章目的" in html  # label rendered (depends on locale)
    assert "rpt_guidance_demo_purpose" not in html  # i18n keys must be looked up, not raw


def test_executive_mode_renders_only_purpose_and_actions(monkeypatch):
    from src.report import section_guidance as sg
    fake = sg.SectionGuidance(
        module_id="demo2",
        purpose_key="rpt_guidance_demo_purpose",
        watch_signals_key="rpt_guidance_demo_signals",
        how_to_read_key="rpt_guidance_demo_how",
        recommended_actions_key="rpt_guidance_demo_actions",
        profile_visibility=("security_risk",),
        min_detail_level="executive",
    )
    monkeypatch.setitem(sg.REGISTRY, "demo2", fake)
    html = render_section_guidance("demo2", profile="security_risk",
                                    detail_level="executive")
    # how_to_read and watch_signals are suppressed in executive mode
    assert "rpt_guidance_demo_how" not in html
    assert "rpt_guidance_demo_signals" not in html


def test_returns_empty_when_profile_excluded(monkeypatch):
    from src.report import section_guidance as sg
    fake = sg.SectionGuidance(
        module_id="demo3",
        purpose_key="rpt_guidance_demo_purpose",
        watch_signals_key="rpt_guidance_demo_signals",
        how_to_read_key="rpt_guidance_demo_how",
        recommended_actions_key="rpt_guidance_demo_actions",
        profile_visibility=("network_inventory",),  # only network, not security
        min_detail_level="standard",
    )
    monkeypatch.setitem(sg.REGISTRY, "demo3", fake)
    html = render_section_guidance("demo3", profile="security_risk",
                                    detail_level="standard")
    assert html == ""
```

- [ ] **Step 3: Run — expect FAIL**

```bash
python3 -m pytest tests/test_reader_guide_render.py -v
```

Expected: FAIL with `ImportError` for `render_section_guidance`.

- [ ] **Step 4: Add `render_section_guidance` helper to `html_exporter.py`**

Near the top of `src/report/exporters/html_exporter.py`, after existing imports:

```python
from src.report.section_guidance import get_guidance, visible_in
from src.i18n import t


def render_section_guidance(module_id: str, profile: str, detail_level: str) -> str:
    """Return a small HTML card with the section's reader-guide.
    Empty string if module has no guidance, or section not visible at this
    (profile, detail_level)."""
    g = get_guidance(module_id)
    if g is None:
        return ""
    if not visible_in(module_id, profile, detail_level):
        return ""
    purpose = t(g.purpose_key)
    actions = t(g.recommended_actions_key)
    if detail_level == "executive":
        return (
            '<div class="section-guidance executive">'
            f'<div><b>{t("rpt_guidance_purpose_label")}</b>: {purpose}</div>'
            f'<div><b>{t("rpt_guidance_recommended_actions_label")}</b>: {actions}</div>'
            "</div>"
        )
    signals = t(g.watch_signals_key)
    how = t(g.how_to_read_key)
    return (
        '<div class="section-guidance standard">'
        f'<div><b>{t("rpt_guidance_purpose_label")}</b>: {purpose}</div>'
        f'<div><b>{t("rpt_guidance_watch_signals_label")}</b>: {signals}</div>'
        f'<div><b>{t("rpt_guidance_how_to_read_label")}</b>: {how}</div>'
        f'<div><b>{t("rpt_guidance_recommended_actions_label")}</b>: {actions}</div>'
        "</div>"
    )
```

- [ ] **Step 5: Inject `render_section_guidance(...)` calls before each Traffic section**

For each section render in `html_exporter.py`, locate the section header and prepend a call to `render_section_guidance(<module_id>, profile, detail_level)`. For now, use `profile="security_risk"` and `detail_level="standard"` as defaults — Task 22 will pass real values via parameter.

Example for one section (apply the same pattern to all):

```python
# Before:
html_parts.append(f'<h2>{t("gui_traffic_uncovered")}</h2>')
html_parts.append(render_uncovered_table(data))

# After:
html_parts.append(render_section_guidance("mod03_uncovered_flows",
                                          profile="security_risk",
                                          detail_level="standard"))
html_parts.append(f'<h2>{t("gui_traffic_uncovered")}</h2>')
html_parts.append(render_uncovered_table(data))
```

- [ ] **Step 6: Add CSS for `.section-guidance` block in the report template style block**

In whichever HTML template `html_exporter.py` injects styles into (locate via `grep -n "<style>" src/report/exporters/html_exporter.py`), add:

```css
.section-guidance {
  background: #f6f8fa;
  border-left: 4px solid #0969da;
  padding: 8px 12px;
  margin: 8px 0 12px;
  font-size: .9em;
}
.section-guidance.executive { background: #fff8c5; border-left-color: #d4a72c; }
.section-guidance b { color: #24292f; }
@media (prefers-color-scheme: dark) {
  .section-guidance { background: #161b22; border-left-color: #58a6ff; color: #c9d1d9; }
  .section-guidance b { color: #c9d1d9; }
}
```

- [ ] **Step 7: Run tests — PASS**

```bash
python3 -m pytest tests/test_reader_guide_render.py tests/test_section_guidance.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/report/exporters/html_exporter.py \
        src/i18n_en.json src/i18n_zh_TW.json \
        tests/test_reader_guide_render.py
git commit -m "feat(report): reader-guide rendering helper for Traffic exporter"
```

---

## Task 5: Wire reader-guide into Audit HTML exporter

**Files:**
- Modify: `src/report/exporters/audit_html_exporter.py`

- [ ] **Step 1: Reuse `render_section_guidance` from html_exporter**

Add import at top of `src/report/exporters/audit_html_exporter.py`:

```python
from src.report.exporters.html_exporter import render_section_guidance
```

- [ ] **Step 2: Inject calls before each Audit section**

Locate each `<h2>` header for `audit_mod00`, `audit_mod01`, `audit_mod02`, `audit_mod03`, `audit_mod04` in `audit_html_exporter.py` and prepend:

```python
html_parts.append(render_section_guidance("audit_mod0X_<name>",
                                          profile="security_risk",  # ignored — Audit has no profile axis
                                          detail_level="standard"))
```

(Profile parameter is unused for Audit reports but required by signature; pass the default.)

- [ ] **Step 3: Quick smoke test**

```bash
python3 -m pytest tests/ -k "audit" -q
```

Expected: existing audit tests still pass.

- [ ] **Step 4: Commit**

```bash
git add src/report/exporters/audit_html_exporter.py
git commit -m "feat(report): reader-guide rendering in Audit exporter"
```

---

## Task 6: Wire reader-guide into Policy Usage HTML exporter

**Files:**
- Modify: `src/report/exporters/policy_usage_html_exporter.py`

- [ ] **Step 1: Add import**

```python
from src.report.exporters.html_exporter import render_section_guidance
```

- [ ] **Step 2: Inject before each section**

For `pu_mod00_executive`, `pu_mod01_overview`, `pu_mod02_hit_detail`, `pu_mod03_unused_detail`, `pu_mod04_deny_effectiveness`, prepend the same `render_section_guidance("pu_modXX_<name>", ...)` call.

- [ ] **Step 3: Smoke test**

```bash
python3 -m pytest tests/ -k "policy_usage" -q
```

- [ ] **Step 4: Commit**

```bash
git add src/report/exporters/policy_usage_html_exporter.py
git commit -m "feat(report): reader-guide rendering in Policy Usage exporter"
```

---

## Task 7: Wire reader-guide into VEN HTML exporter

**Files:**
- Modify: `src/report/exporters/ven_html_exporter.py`

- [ ] **Step 1: Add import + inject calls**

Same pattern as Tasks 5/6. VEN sections include online inventory, offline VENs, lost-heartbeat (<24h, 24-48h), policy sync state. For each section, register a `ven_<section>` module id (decide concrete ids in Task 11).

- [ ] **Step 2: Smoke test**

```bash
python3 -m pytest tests/ -k "ven" -q
```

- [ ] **Step 3: Commit**

```bash
git add src/report/exporters/ven_html_exporter.py
git commit -m "feat(report): reader-guide rendering in VEN exporter"
```

---

## Task 8: Populate guidance for Traffic policy/coverage modules (mod02, mod03)

**Files:**
- Modify: `src/report/section_guidance.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add 8 i18n keys (4 fields × 2 modules)**

Add to both locale files. Use the EN/zh-TW pairs below; substitute zh-TW with semantically equivalent translations.

```
rpt_guidance_mod02_purpose      "Show how observed flows split among allow / block / potentially blocked policy decisions, segmented per profile."
rpt_guidance_mod02_signals      "A high potentially_blocked share means coverage gaps. A high blocked share signals attempted disallowed traffic."
rpt_guidance_mod02_how          "Compare allowed vs PB share. PB does not mean a rule is staged — it means no matching allow exists and only visibility mode is hiding the block."
rpt_guidance_mod02_actions      "Author allow rules for legitimate PB flows; investigate blocked flows for attacker activity or misconfiguration."

rpt_guidance_mod03_purpose      "Surface flows with no matching allow rule that would be blocked under default-deny enforcement."
rpt_guidance_mod03_signals      "High count of PB uncovered flows; flows targeting crown-jewel labels; flows from unmanaged sources."
rpt_guidance_mod03_how          "Each row is a label-pair / port that lacks coverage. Higher volume + critical destination = higher remediation priority."
rpt_guidance_mod03_actions      "Build candidate allow rules; or accept default-deny impact; or investigate as suspicious."
```

- [ ] **Step 2: Register both modules in `section_guidance.py`**

Append to the registry at the bottom of `src/report/section_guidance.py`:

```python
REGISTRY["mod02_policy_decisions"] = SectionGuidance(
    module_id="mod02_policy_decisions",
    purpose_key="rpt_guidance_mod02_purpose",
    watch_signals_key="rpt_guidance_mod02_signals",
    how_to_read_key="rpt_guidance_mod02_how",
    recommended_actions_key="rpt_guidance_mod02_actions",
    primary_audience="mixed",
    profile_visibility=("security_risk", "network_inventory"),
    min_detail_level="standard",
)
REGISTRY["mod03_uncovered_flows"] = SectionGuidance(
    module_id="mod03_uncovered_flows",
    purpose_key="rpt_guidance_mod03_purpose",
    watch_signals_key="rpt_guidance_mod03_signals",
    how_to_read_key="rpt_guidance_mod03_how",
    recommended_actions_key="rpt_guidance_mod03_actions",
    primary_audience="security",
    profile_visibility=("security_risk", "network_inventory"),
    min_detail_level="standard",
)
```

- [ ] **Step 3: Run tests — PASS**

```bash
python3 -m pytest tests/test_section_guidance.py -v
python3 scripts/audit_i18n_usage.py
python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -q
```

- [ ] **Step 4: Commit**

```bash
git add src/report/section_guidance.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): guidance for mod02 policy decisions and mod03 uncovered flows"
```

---

## Task 9: Guidance for Traffic risk modules (mod04, mod07, mod08)

**Files:**
- Modify: `src/report/section_guidance.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add 12 i18n keys (4 × 3)**

```
rpt_guidance_mod04_purpose      "Identify exposure to ransomware-relevant ports and protocols (SMB/RDP/SSH/etc)."
rpt_guidance_mod04_signals      "Internet-facing or unmanaged sources reaching critical-port destinations."
rpt_guidance_mod04_how          "Each row is a workload pair using a high-risk port. Flag if not in your allowed admin-tooling baseline."
rpt_guidance_mod04_actions      "Quarantine or restrict; convert legitimate admin flows into named allow rules; investigate the rest."

rpt_guidance_mod07_purpose      "Map source-label → destination-label → service crossings to expose dependency structure."
rpt_guidance_mod07_signals      "Unexpected env crossings (prod ↔ dev), unknown labels, app pairs lacking justification."
rpt_guidance_mod07_how          "Read along rows = source group, columns = destination group. Cell intensity reflects flow volume."
rpt_guidance_mod07_actions      "Convert legitimate cells into label-based allow rules; investigate unexpected high-volume crossings."

rpt_guidance_mod08_purpose      "List unmanaged hosts (no VEN) participating in observed flows."
rpt_guidance_mod08_signals      "Unmanaged sources accessing crown-jewel apps; high-volume unmanaged egress; unmanaged peers in critical environments."
rpt_guidance_mod08_how          "Each row is an unmanaged IP and its observed peers, ports, and label hits."
rpt_guidance_mod08_actions      "Install VEN where feasible; document and accept exceptions; tighten boundary rules around unmanaged peers."
```

- [ ] **Step 2: Register modules**

Append:

```python
REGISTRY["mod04_ransomware_exposure"] = SectionGuidance(
    module_id="mod04_ransomware_exposure",
    purpose_key="rpt_guidance_mod04_purpose",
    watch_signals_key="rpt_guidance_mod04_signals",
    how_to_read_key="rpt_guidance_mod04_how",
    recommended_actions_key="rpt_guidance_mod04_actions",
    primary_audience="security",
    profile_visibility=("security_risk",),  # appendix-only in network_inventory (not registered there)
    min_detail_level="standard",
)
REGISTRY["mod07_cross_label_matrix"] = SectionGuidance(
    module_id="mod07_cross_label_matrix",
    purpose_key="rpt_guidance_mod07_purpose",
    watch_signals_key="rpt_guidance_mod07_signals",
    how_to_read_key="rpt_guidance_mod07_how",
    recommended_actions_key="rpt_guidance_mod07_actions",
    primary_audience="network",
    profile_visibility=("network_inventory",),  # security_risk uses filtered version
    min_detail_level="standard",
)
REGISTRY["mod08_unmanaged_hosts"] = SectionGuidance(
    module_id="mod08_unmanaged_hosts",
    purpose_key="rpt_guidance_mod08_purpose",
    watch_signals_key="rpt_guidance_mod08_signals",
    how_to_read_key="rpt_guidance_mod08_how",
    recommended_actions_key="rpt_guidance_mod08_actions",
    primary_audience="mixed",
    profile_visibility=("security_risk", "network_inventory"),
    min_detail_level="standard",
)
```

- [ ] **Step 3: Run i18n + section tests**

```bash
python3 -m pytest tests/test_section_guidance.py -v
python3 scripts/audit_i18n_usage.py
```

- [ ] **Step 4: Commit**

```bash
git add src/report/section_guidance.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): guidance for mod04 ransomware, mod07 label matrix, mod08 unmanaged"
```

---

## Task 10: Guidance for Traffic enforcement modules (mod13, mod15)

**Files:**
- Modify: `src/report/section_guidance.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add 8 i18n keys**

```
rpt_guidance_mod13_purpose      "Estimate enforcement readiness per app/env: how much would shifting to default-deny break vs protect."
rpt_guidance_mod13_signals      "Low ready-to-enforce share; high PB exposure; unmanaged dependencies blocking enforcement."
rpt_guidance_mod13_how          "Higher PB count = more flows that would be blocked. Higher allowed share with named rules = more ready."
rpt_guidance_mod13_actions      "Convert PB into named allows; resolve unmanaged dependencies; then move app to selective enforcement."

rpt_guidance_mod15_purpose      "Show east-west paths an attacker could traverse after initial foothold."
rpt_guidance_mod15_signals      "Long chains spanning environments; PB-heavy hops; risky-port chains (SMB/RDP)."
rpt_guidance_mod15_how          "Path length, port mix, and crossings between sensitive labels indicate blast-radius risk."
rpt_guidance_mod15_actions      "Cut the highest-impact hops via allow rules or boundary deny; isolate crown jewels."
```

- [ ] **Step 2: Register**

```python
REGISTRY["mod13_readiness"] = SectionGuidance(
    module_id="mod13_readiness",
    purpose_key="rpt_guidance_mod13_purpose",
    watch_signals_key="rpt_guidance_mod13_signals",
    how_to_read_key="rpt_guidance_mod13_how",
    recommended_actions_key="rpt_guidance_mod13_actions",
    primary_audience="mixed",
    profile_visibility=("security_risk", "network_inventory"),
    min_detail_level="standard",
)
REGISTRY["mod15_lateral_movement"] = SectionGuidance(
    module_id="mod15_lateral_movement",
    purpose_key="rpt_guidance_mod15_purpose",
    watch_signals_key="rpt_guidance_mod15_signals",
    how_to_read_key="rpt_guidance_mod15_how",
    recommended_actions_key="rpt_guidance_mod15_actions",
    primary_audience="security",
    profile_visibility=("security_risk", "network_inventory"),  # both, but exporter may render shorter version in network_inventory
    min_detail_level="standard",
)
```

- [ ] **Step 3: Test + audit + commit**

```bash
python3 -m pytest tests/test_section_guidance.py -v
python3 scripts/audit_i18n_usage.py
git add src/report/section_guidance.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): guidance for mod13 readiness and mod15 lateral movement"
```

---

## Task 11: Guidance for Audit, Policy Usage, VEN sections

**Files:**
- Modify: `src/report/section_guidance.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add 24 i18n keys (4 fields × 6 sections)**

Sections: `audit_mod03_policy`, `audit_mod04_correlation`, `pu_mod03_unused_detail`, `pu_mod04_deny_effectiveness`, `ven_offline`, `ven_policy_sync`.

```
rpt_guidance_audit_mod03_purpose     "Track policy changes and lifecycle events across rulesets."
rpt_guidance_audit_mod03_signals     "Off-hours changes, mass deletes, unauthorized actor, policy churn spikes."
rpt_guidance_audit_mod03_how         "Each row is a change event with actor, time, and target. Cluster by actor or ruleset to spot patterns."
rpt_guidance_audit_mod03_actions     "Verify changes are tied to approved tickets; investigate anomalous actors or timing."

rpt_guidance_audit_mod04_purpose     "Correlate suspicious events with policy changes and VEN activity to surface investigation stories."
rpt_guidance_audit_mod04_signals     "Auth-failure → policy-change chains; agent tamper → traffic blip; mass-delete → blocked-flow surge."
rpt_guidance_audit_mod04_how         "Correlation chains are time-windowed multi-event sequences with shared actor or workload."
rpt_guidance_audit_mod04_actions     "Open IR ticket; pull full PCE audit log for chain; verify with VEN telemetry."

rpt_guidance_pu_mod03_purpose        "Identify unused (zero-hit) policy rules that are candidates for cleanup."
rpt_guidance_pu_mod03_signals        "Rules unused for >30 days; broad-scope rules with zero hits (over-permissive but ineffective)."
rpt_guidance_pu_mod03_how            "Each row is a rule with last-hit timestamp and hit count over the query window."
rpt_guidance_pu_mod03_actions        "Disable then remove after a verification period; or replace with tighter rules if needed."

rpt_guidance_pu_mod04_purpose        "Quantify how effective deny rules are: what they actually blocked vs intended scope."
rpt_guidance_pu_mod04_signals        "Deny rules with zero hits (possibly redundant); deny rules being bypassed (low effective ratio)."
rpt_guidance_pu_mod04_how            "Effective ratio = blocked flows matching deny scope / total flows in scope."
rpt_guidance_pu_mod04_actions        "Tighten rule scope; remove redundant denies; investigate bypasses."

rpt_guidance_ven_offline_purpose     "List VENs that are offline or have lost recent heartbeat — these are segmentation blind spots."
rpt_guidance_ven_offline_signals     "Offline VENs on critical workloads; long lost-heartbeat duration; clustered offline failures."
rpt_guidance_ven_offline_how         "Offline = no contact > heartbeat threshold. Lost <24h is recoverable; >48h needs intervention."
rpt_guidance_ven_offline_actions     "Restart VEN or re-enroll; if persistent, flag the workload as unmanaged in policy planning."

rpt_guidance_ven_policy_sync_purpose "Show VENs whose policy version does not match the current PCE state."
rpt_guidance_ven_policy_sync_signals "Stale policy versions; high count of out-of-sync VENs after a recent provision."
rpt_guidance_ven_policy_sync_how     "Each row shows VEN ID, current policy version, expected version, and last sync attempt."
rpt_guidance_ven_policy_sync_actions "Trigger re-sync; investigate VEN connectivity to PCE."
```

- [ ] **Step 2: Register all six entries**

Append the corresponding `REGISTRY[...] = SectionGuidance(...)` blocks (same pattern as Tasks 8–10).

- [ ] **Step 3: Test + audit + commit**

```bash
python3 -m pytest tests/test_section_guidance.py -v
python3 scripts/audit_i18n_usage.py
git add src/report/section_guidance.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): guidance for audit/policy-usage/VEN priority sections"
```

---

## Task 12: PB semantics — write tests asserting PB ≠ readiness

**Files:**
- Create: `tests/test_pb_semantics.py`

- [ ] **Step 1: Write the failing test**

```python
"""potentially_blocked is uncovered exposure, not staged/ready coverage.
This test guards against regressing the wording or metric calculation."""
import pandas as pd
import pytest

from src.report.analysis import mod03_uncovered_flows
from src.report.analysis import mod12_executive_summary
from src.report.analysis import mod13_readiness


def _flows_pb_only():
    return pd.DataFrame([
        {"src": "a", "dst": "b", "port": 443, "policy_decision": "potentially_blocked"},
        {"src": "a", "dst": "c", "port": 80,  "policy_decision": "potentially_blocked"},
    ])


def _flows_allowed_only():
    return pd.DataFrame([
        {"src": "a", "dst": "b", "port": 443, "policy_decision": "allowed"},
    ])


def test_mod03_counts_pb_as_uncovered():
    out = mod03_uncovered_flows.analyze(_flows_pb_only())
    # PB flows are uncovered exposure
    pb = out.get("pb_uncovered_count", out.get("pb_count"))
    assert pb == 2, f"expected 2 PB uncovered, got {pb}; full output: {out}"


def test_mod13_pb_does_not_increase_readiness():
    out_pb = mod13_readiness.analyze(_flows_pb_only())
    out_allow = mod13_readiness.analyze(_flows_allowed_only())
    # Readiness should NOT credit PB as ready coverage; allowed-only should be >= PB-only
    ready_pb = out_pb.get("ready_to_enforce_share", out_pb.get("ready_share", 0))
    ready_allow = out_allow.get("ready_to_enforce_share", out_allow.get("ready_share", 0))
    assert ready_allow >= ready_pb, (
        "PB credited toward readiness — must not. "
        f"PB-only={ready_pb}, allowed-only={ready_allow}"
    )


def test_mod12_exposes_pb_uncovered_exposure_kpi():
    out = mod12_executive_summary.analyze(_flows_pb_only(), profile="security_risk")
    # KPI must exist with new name (alias staged_coverage may also exist for one release)
    assert "pb_uncovered_exposure" in out.get("kpis", {})
    assert out["kpis"]["pb_uncovered_exposure"] >= 1


def test_mod12_legacy_alias_present_for_one_release():
    """staged_coverage is preserved as a deprecated alias; remove in v3.21."""
    out = mod12_executive_summary.analyze(_flows_pb_only(), profile="security_risk")
    # The alias must still exist to not break dashboards on this release.
    aliases = out.get("kpi_aliases", {})
    assert "staged_coverage" in aliases or "staged_coverage" in out.get("kpis", {})
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_pb_semantics.py -v
```

Expected: FAIL because mod12 doesn't yet take a `profile` parameter and may not expose `pb_uncovered_exposure`. mod13 may currently credit PB toward readiness.

- [ ] **Step 3: Commit the failing tests (then later tasks make them pass)**

```bash
git add tests/test_pb_semantics.py
git commit -m "test(report): guard PB semantics — uncovered exposure, not readiness"
```

These tests intentionally fail until Tasks 13–15 land. Each subsequent task should make one assertion pass at a time.

---

## Task 13: Fix mod03 — PB counted as uncovered exposure (not staged)

**Files:**
- Modify: `src/report/analysis/mod03_uncovered_flows.py`

- [ ] **Step 1: Read current implementation**

```bash
grep -n "staged\|pb\|potentially_blocked" /mnt/d/RD/illumio_ops/src/report/analysis/mod03_uncovered_flows.py
```

Identify how PB is currently labeled. If the module emits `staged_count` / `staged_share`, those need rename.

- [ ] **Step 2: Make the assertion in test_pb_semantics.py::test_mod03_counts_pb_as_uncovered pass**

In `mod03_uncovered_flows.analyze()`, ensure the output dict contains:
- `pb_uncovered_count`: count of PB flows
- `pb_uncovered_share`: PB / total
- (Backward compat) preserve `staged_count` / `staged_share` as aliases for one release; mark in a comment `# DEPRECATED ALIAS: remove in v3.21`.

Example diff structure:

```python
def analyze(flows_df: pd.DataFrame) -> dict:
    total = len(flows_df)
    pb_mask = flows_df["policy_decision"] == "potentially_blocked"
    pb_count = int(pb_mask.sum())
    out = {
        "total": total,
        "pb_uncovered_count": pb_count,
        "pb_uncovered_share": (pb_count / total) if total else 0.0,
        # DEPRECATED ALIAS — remove in v3.21
        "staged_count": pb_count,
        "staged_share": (pb_count / total) if total else 0.0,
        # ... existing detail rows / top pairs / etc. unchanged ...
    }
    return out
```

- [ ] **Step 3: Run targeted tests**

```bash
python3 -m pytest tests/test_pb_semantics.py::test_mod03_counts_pb_as_uncovered -v
python3 -m pytest tests/ -k "mod03 or uncovered" -v
```

Expected: targeted test PASS; existing mod03 tests still PASS.

- [ ] **Step 4: Commit**

```bash
git add src/report/analysis/mod03_uncovered_flows.py
git commit -m "fix(report): mod03 names PB as uncovered exposure; preserve staged alias"
```

---

## Task 14: Fix mod13 — PB does NOT credit readiness

**Files:**
- Modify: `src/report/analysis/mod13_readiness.py`

- [ ] **Step 1: Read current implementation**

```bash
grep -n "staged\|pb\|potentially_blocked\|ready" /mnt/d/RD/illumio_ops/src/report/analysis/mod13_readiness.py
```

If readiness adds `pb_count` to a "ready" or "staged" bucket, that is the bug.

- [ ] **Step 2: Make the assertion in test_pb_semantics.py::test_mod13_pb_does_not_increase_readiness pass**

Ensure readiness calculation only credits flows with `policy_decision="allowed"` and a matching named rule. PB flows go into a separate `pb_uncovered_count` field, NOT readiness.

```python
def analyze(flows_df: pd.DataFrame) -> dict:
    total = len(flows_df)
    allowed = int((flows_df["policy_decision"] == "allowed").sum())
    pb = int((flows_df["policy_decision"] == "potentially_blocked").sum())
    return {
        "total": total,
        "ready_to_enforce_share": (allowed / total) if total else 0.0,
        "pb_uncovered_count": pb,
        # ... existing detail unchanged ...
    }
```

- [ ] **Step 3: Run target test**

```bash
python3 -m pytest tests/test_pb_semantics.py::test_mod13_pb_does_not_increase_readiness -v
python3 -m pytest tests/ -k "mod13 or readiness" -v
```

- [ ] **Step 4: Commit**

```bash
git add src/report/analysis/mod13_readiness.py
git commit -m "fix(report): mod13 readiness no longer credits PB as ready coverage"
```

---

## Task 15: Update HTML wording + B003/L008 rule descriptions

**Files:**
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `docs/Security_Rules_Reference.md`
- Modify: `docs/Security_Rules_Reference_zh.md`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add new wording i18n keys**

```
rpt_pb_label              "PB Uncovered Exposure" / "PB 未覆蓋暴露"
rpt_pb_explainer          "Traffic observed in visibility mode without a matching allow rule. Would be blocked once selective/full enforcement is enabled." / "視覺化模式下觀察到、但無對應 allow 規則的流量；切換到 selective/full enforcement 後將被預設拒絕。"
rpt_rule_b003_desc        "Detect attempted broadly-scoped allow rules that conflict with least-privilege baselines."
rpt_rule_l008_desc        "Detect lateral movement candidates: chains crossing trust boundaries via risky ports."
```

(Adjust B003/L008 descriptions to actual rule semantics if they differ; check `src/report/rules_engine.py` for current text.)

- [ ] **Step 2: Replace hardcoded "Staged Coverage" / "rules ready" in html_exporter**

```bash
grep -n "Staged Coverage\|rules ready\|staged_coverage" /mnt/d/RD/illumio_ops/src/report/exporters/html_exporter.py
```

For each match, replace:
- Display label `Staged Coverage` → `t("rpt_pb_label")`
- Inline phrase `rules ready, pending enforcement` → `t("rpt_pb_explainer")`

- [ ] **Step 3: Update docs**

In both `docs/Security_Rules_Reference.md` and `docs/Security_Rules_Reference_zh.md`, locate the PB / B003 / L008 sections and update to match the new wording.

- [ ] **Step 4: i18n audit + smoke test**

```bash
python3 scripts/audit_i18n_usage.py
python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/html_exporter.py \
        docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md \
        src/i18n_en.json src/i18n_zh_TW.json
git commit -m "fix(report): correct PB wording in HTML output and rule docs"
```

---

## Task 16: Audit dashboard / API consumers of `staged_coverage`

**Files:**
- Read-only investigation (no edits unless drift found)

- [ ] **Step 1: Enumerate consumers**

```bash
grep -rn "staged_coverage\|Staged Coverage" /mnt/d/RD/illumio_ops/src/ /mnt/d/RD/illumio_ops/tests/ 2>/dev/null
```

- [ ] **Step 2: For each consumer, decide**
  - **Internal code (analyzer, exporters)**: should switch to new field name `pb_uncovered_count`. File a follow-up task.
  - **External-facing JSON (metadata.json, dashboard summary, API response)**: must keep `staged_coverage` alias for one release. Confirm Task 13 preserves it.
  - **Test fixtures**: update to use both field names so tests guard the alias.

- [ ] **Step 3: Document findings**

Append a `## Consumer Audit (Task 16)` section to this plan file with the list of consumers and disposition. This is a paper trail for the v3.21 alias removal.

- [ ] **Step 4: Commit only if doc was updated**

```bash
git add docs/superpowers/plans/2026-04-25-report-r01-semantics-and-profiles.md
git commit -m "docs(plan): r01 consumer audit of staged_coverage"
```

---

## Task 17: Date Range fallback in mod01 / report_generator

**Files:**
- Create: `tests/test_date_range_fallback.py`
- Modify: `src/report/analysis/mod01_traffic_overview.py`
- Modify: `src/report/report_generator.py` if needed

- [ ] **Step 1: Write failing test**

```python
"""When first/last_detected are missing or unparseable, the report metadata
should fall back to query_context.start_date / end_date instead of N/A."""
import pandas as pd

from src.report.analysis import mod01_traffic_overview


def test_date_range_falls_back_to_query_context_when_missing():
    flows = pd.DataFrame([{"src": "a", "dst": "b", "port": 80,
                           "policy_decision": "allowed"}])
    query_context = {"start_date": "2026-04-18", "end_date": "2026-04-25"}
    out = mod01_traffic_overview.analyze(flows, query_context=query_context)
    assert out["date_range"]["start"] == "2026-04-18"
    assert out["date_range"]["end"] == "2026-04-25"


def test_date_range_uses_first_last_detected_when_present():
    flows = pd.DataFrame([
        {"src": "a", "dst": "b", "port": 80, "policy_decision": "allowed",
         "first_detected": "2026-04-19T01:00:00Z", "last_detected": "2026-04-24T22:00:00Z"},
    ])
    query_context = {"start_date": "2026-04-18", "end_date": "2026-04-25"}
    out = mod01_traffic_overview.analyze(flows, query_context=query_context)
    # Detected times override query_context when they are real
    assert out["date_range"]["start"].startswith("2026-04-19")
    assert out["date_range"]["end"].startswith("2026-04-24")


def test_date_range_returns_query_context_when_detected_unparseable():
    flows = pd.DataFrame([
        {"src": "a", "dst": "b", "port": 80, "policy_decision": "allowed",
         "first_detected": "garbage", "last_detected": None},
    ])
    query_context = {"start_date": "2026-04-18", "end_date": "2026-04-25"}
    out = mod01_traffic_overview.analyze(flows, query_context=query_context)
    assert out["date_range"]["start"] == "2026-04-18"
    assert out["date_range"]["end"] == "2026-04-25"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_date_range_fallback.py -v
```

- [ ] **Step 3: Implement fallback in mod01**

Edit `src/report/analysis/mod01_traffic_overview.py`. Add `query_context` parameter (kwarg, default `None`). After computing first/last_detected:

```python
def analyze(flows_df, query_context: dict | None = None):
    qc = query_context or {}
    # ... existing logic ...
    start_detected = _safe_parse(flows_df.get("first_detected"))
    end_detected = _safe_parse(flows_df.get("last_detected"))
    out["date_range"] = {
        "start": start_detected or qc.get("start_date") or "N/A",
        "end":   end_detected   or qc.get("end_date")   or "N/A",
    }
    return out


def _safe_parse(series_or_none):
    """Return earliest valid timestamp string, or None."""
    if series_or_none is None or len(series_or_none) == 0:
        return None
    valid = pd.to_datetime(series_or_none, errors="coerce").dropna()
    if valid.empty:
        return None
    return valid.min().isoformat()
```

(Adjust `_safe_parse` to use `.max()` for the end_detected variant; or define `_safe_parse_min` and `_safe_parse_max` for clarity.)

Pass `query_context` from `report_generator.py` when calling mod01.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_date_range_fallback.py -v
python3 -m pytest tests/ -k "mod01 or traffic_overview" -v
```

- [ ] **Step 5: Commit**

```bash
git add src/report/analysis/mod01_traffic_overview.py src/report/report_generator.py tests/test_date_range_fallback.py
git commit -m "fix(report): mod01 date range falls back to query_context when detected missing"
```

---

## Task 18: Executive Summary — write KPI test

**Files:**
- Create: `tests/test_executive_kpis.py`

- [ ] **Step 1: Write failing test**

```python
"""mod12 executive summary must expose the 6+6 KPIs per profile, with names
matching spec §6.4."""
import pandas as pd

from src.report.analysis import mod12_executive_summary


SECURITY_RISK_KPI_NAMES = {
    "microsegmentation_maturity",
    "active_allow_coverage",
    "pb_uncovered_exposure",
    "blocked_flows",
    "high_risk_lateral_paths",
    "top_remediation_action",
}

NETWORK_INVENTORY_KPI_NAMES = {
    "observed_apps_envs",
    "known_dependency_coverage",
    "label_completeness",
    "rule_candidate_count",
    "unmanaged_unknown_dependencies",
    "top_rule_building_gap",
}


def _sample_flows():
    return pd.DataFrame([
        {"src": "a", "dst": "b", "port": 443, "policy_decision": "allowed"},
        {"src": "a", "dst": "c", "port": 80,  "policy_decision": "potentially_blocked"},
        {"src": "x", "dst": "y", "port": 22,  "policy_decision": "blocked"},
    ])


def test_security_risk_profile_returns_6_kpis():
    out = mod12_executive_summary.analyze(_sample_flows(), profile="security_risk")
    kpis = out.get("kpis", {})
    assert SECURITY_RISK_KPI_NAMES.issubset(set(kpis.keys())), (
        f"missing: {SECURITY_RISK_KPI_NAMES - set(kpis.keys())}")


def test_network_inventory_profile_returns_6_kpis():
    out = mod12_executive_summary.analyze(_sample_flows(), profile="network_inventory")
    kpis = out.get("kpis", {})
    assert NETWORK_INVENTORY_KPI_NAMES.issubset(set(kpis.keys())), (
        f"missing: {NETWORK_INVENTORY_KPI_NAMES - set(kpis.keys())}")


def test_top_3_actions_block_present_in_security_risk():
    out = mod12_executive_summary.analyze(_sample_flows(), profile="security_risk")
    actions = out.get("top_actions", [])
    assert isinstance(actions, list)
    assert len(actions) <= 3
    # Each action should have count + code + text + optional top app/env
    for a in actions:
        assert "code" in a and "count" in a


def test_default_profile_is_security_risk():
    out_default = mod12_executive_summary.analyze(_sample_flows())
    out_explicit = mod12_executive_summary.analyze(_sample_flows(), profile="security_risk")
    assert set(out_default.get("kpis", {}).keys()) == set(out_explicit.get("kpis", {}).keys())
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_executive_kpis.py -v
```

Expected: FAIL — mod12 doesn't yet take `profile` and may not produce these KPIs.

- [ ] **Step 3: Commit failing test**

```bash
git add tests/test_executive_kpis.py
git commit -m "test(report): KPI contract for security_risk + network_inventory profiles"
```

---

## Task 19: mod12 — implement Security Risk profile KPIs

**Files:**
- Modify: `src/report/analysis/mod12_executive_summary.py`

- [ ] **Step 1: Refactor `analyze()` to accept `profile`**

```python
def analyze(flows_df: pd.DataFrame, profile: str = "security_risk", **kwargs) -> dict:
    if profile == "security_risk":
        return _security_risk_kpis(flows_df, **kwargs)
    if profile == "network_inventory":
        return _network_inventory_kpis(flows_df, **kwargs)
    raise ValueError(f"unknown profile: {profile!r}")
```

- [ ] **Step 2: Implement `_security_risk_kpis`**

```python
def _security_risk_kpis(flows_df, *, attack_summary=None, lateral_summary=None,
                        readiness_summary=None, **_) -> dict:
    total = len(flows_df)
    allowed = int((flows_df["policy_decision"] == "allowed").sum())
    pb = int((flows_df["policy_decision"] == "potentially_blocked").sum())
    blocked = int((flows_df["policy_decision"] == "blocked").sum())
    # Maturity = allowed_share weighted by readiness if available
    allowed_share = (allowed / total) if total else 0.0
    maturity = allowed_share if readiness_summary is None else (
        allowed_share * readiness_summary.get("ready_to_enforce_share", 1.0))
    high_risk_lateral = (lateral_summary or {}).get("high_risk_path_count", 0)
    top_action = (attack_summary or {}).get("action_matrix", {}).get("top1", {
        "code": "NONE", "count": 0, "text": ""})
    kpis = {
        "microsegmentation_maturity": round(maturity, 4),
        "active_allow_coverage": round(allowed_share, 4),
        "pb_uncovered_exposure": pb,
        "blocked_flows": blocked,
        "high_risk_lateral_paths": high_risk_lateral,
        "top_remediation_action": top_action,
    }
    return {
        "profile": "security_risk",
        "kpis": kpis,
        "kpi_aliases": {"staged_coverage": pb},  # DEPRECATED alias for v3.21 removal
        "top_actions": _build_top_actions(attack_summary, limit=3),
    }


def _build_top_actions(attack_summary, *, limit=3):
    if not attack_summary:
        return []
    rows = attack_summary.get("action_matrix", {}).get("ranked", [])
    return rows[:limit]
```

- [ ] **Step 3: Run targeted tests**

```bash
python3 -m pytest tests/test_executive_kpis.py::test_security_risk_profile_returns_6_kpis tests/test_executive_kpis.py::test_top_3_actions_block_present_in_security_risk tests/test_executive_kpis.py::test_default_profile_is_security_risk -v
python3 -m pytest tests/test_pb_semantics.py::test_mod12_exposes_pb_uncovered_exposure_kpi tests/test_pb_semantics.py::test_mod12_legacy_alias_present_for_one_release -v
```

Expected: PASS for security_risk-only tests.

- [ ] **Step 4: Commit**

```bash
git add src/report/analysis/mod12_executive_summary.py
git commit -m "feat(report): mod12 Security Risk profile with 6 named KPIs + top actions"
```

---

## Task 20: mod12 — implement Network Inventory profile KPIs

**Files:**
- Modify: `src/report/analysis/mod12_executive_summary.py`

- [ ] **Step 1: Implement `_network_inventory_kpis`**

```python
def _network_inventory_kpis(flows_df, *, label_summary=None, ringfence_summary=None,
                             unmanaged_summary=None, **_) -> dict:
    apps = flows_df.get("app", flows_df.get("dst_app", pd.Series(dtype=object))).dropna().nunique()
    envs = flows_df.get("env", flows_df.get("dst_env", pd.Series(dtype=object))).dropna().nunique()
    # Known dependency coverage: flows where src+dst labels are fully resolved
    if "src_label" in flows_df.columns and "dst_label" in flows_df.columns:
        known = int((flows_df["src_label"].notna() & flows_df["dst_label"].notna()).sum())
    else:
        known = 0
    total = len(flows_df)
    label_complete = (label_summary or {}).get("fill_rate",
        (known / total) if total else 0.0)
    rule_candidates = (ringfence_summary or {}).get("candidate_rules_count", 0)
    unmanaged = (unmanaged_summary or {}).get("count", 0)
    top_gap = (ringfence_summary or {}).get("top_rule_gap", {
        "src_label": None, "dst_label": None, "flows": 0})
    kpis = {
        "observed_apps_envs": {"apps": apps, "envs": envs},
        "known_dependency_coverage": round((known / total) if total else 0.0, 4),
        "label_completeness": round(label_complete, 4),
        "rule_candidate_count": rule_candidates,
        "unmanaged_unknown_dependencies": unmanaged,
        "top_rule_building_gap": top_gap,
    }
    return {"profile": "network_inventory", "kpis": kpis}
```

- [ ] **Step 2: Run targeted test**

```bash
python3 -m pytest tests/test_executive_kpis.py::test_network_inventory_profile_returns_6_kpis -v
```

- [ ] **Step 3: Run all KPI + PB tests + full executive_summary tests**

```bash
python3 -m pytest tests/test_executive_kpis.py tests/test_pb_semantics.py -v
python3 -m pytest tests/ -k "executive_summary or mod12" -v
```

- [ ] **Step 4: Commit**

```bash
git add src/report/analysis/mod12_executive_summary.py
git commit -m "feat(report): mod12 Network Inventory profile with 6 named KPIs"
```

---

## Task 21: Mirror new KPI fields in dashboard_summaries / metadata

**Files:**
- Modify: `src/report/dashboard_summaries.py`
- Modify: `src/report/report_metadata.py` (if it summarizes KPIs)

- [ ] **Step 1: Locate the dashboard summary builder**

```bash
grep -n "staged_coverage\|kpi" /mnt/d/RD/illumio_ops/src/report/dashboard_summaries.py /mnt/d/RD/illumio_ops/src/report/report_metadata.py
```

- [ ] **Step 2: Mirror the new KPI fields**

Wherever the dashboard summary references KPIs, ensure both the new name (`pb_uncovered_exposure`) AND the deprecated alias (`staged_coverage`) are present. Add a comment marking the alias for v3.21 removal.

- [ ] **Step 3: Run dashboard tests**

```bash
python3 -m pytest tests/ -k "dashboard or metadata" -v
```

- [ ] **Step 4: Commit**

```bash
git add src/report/dashboard_summaries.py src/report/report_metadata.py
git commit -m "feat(report): dashboard_summaries mirror new KPIs; preserve staged_coverage alias"
```

---

## Task 22: Plumb `traffic_report_profile` through report_generator

**Files:**
- Modify: `src/report/report_generator.py`
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: Accept the parameter**

In `src/report/report_generator.py`, add `traffic_report_profile` parameter to the report-generation entry point(s). Default `"security_risk"`.

```python
def generate_traffic_report(..., traffic_report_profile: str = "security_risk", **kwargs):
    if traffic_report_profile not in ("security_risk", "network_inventory"):
        raise ValueError(f"invalid traffic_report_profile: {traffic_report_profile!r}")
    # ... existing logic ...
    # Pass to mod12 + exporter
```

- [ ] **Step 2: Pass into mod12 and exporter**

When calling `mod12_executive_summary.analyze`, pass `profile=traffic_report_profile`. When calling the HTML exporter, pass `profile=traffic_report_profile`.

- [ ] **Step 3: Update exporter signature**

In `src/report/exporters/html_exporter.py`, add `profile` and `detail_level` parameters to the entry function. Replace the placeholder defaults from Task 4 (Step 5) with the real values.

- [ ] **Step 4: Run existing report tests**

```bash
python3 -m pytest tests/ -k "report_generator or html_exporter" -v
```

Expected: existing tests still pass (callers without the parameter get the security_risk default).

- [ ] **Step 5: Commit**

```bash
git add src/report/report_generator.py src/report/exporters/html_exporter.py
git commit -m "feat(report): plumb traffic_report_profile through generator and exporter"
```

---

## Task 23: Profile-driven section selection in HTML exporter

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: Wrap each section render with `visible_in()` check**

```python
from src.report.section_guidance import visible_in

# Before each section append:
if visible_in("mod04_ransomware_exposure", profile, detail_level):
    html_parts.append(render_section_guidance("mod04_ransomware_exposure", profile, detail_level))
    html_parts.append(f'<h2>{t("rpt_mod04_title")}</h2>')
    html_parts.append(render_ransomware_section(data))
```

- [ ] **Step 2: For modules NOT in `profile_visibility`, hide entirely (or render as appendix)**

For now, hide entirely. R2 introduces appendix mechanics.

- [ ] **Step 3: Smoke test — generate one report each profile**

Add a dev script or manual run:

```bash
python3 -c "
from src.report.report_generator import generate_traffic_report
from tests.fixtures.report_fixtures import sample_flows  # or any test fixture loader
# Or use an existing CLI command if one exists.
"
```

(If no scriptable entry exists yet, defer the smoke to Task 24.)

- [ ] **Step 4: Commit**

```bash
git add src/report/exporters/html_exporter.py
git commit -m "feat(report): exporter selects sections per profile via visible_in()"
```

---

## Task 24: End-to-end profile split test

**Files:**
- Create: `tests/test_traffic_profile_split.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end: generate Traffic report twice from same fixture, once per profile.
Verify the two outputs differ in expected sections."""
import pandas as pd
import pytest

from src.report.exporters.html_exporter import render_traffic_report  # adjust to actual entry point


@pytest.fixture
def sample_flows():
    return pd.DataFrame([
        {"src": "a", "dst": "b", "port": 443, "policy_decision": "allowed",
         "src_label": "app=web|env=prod", "dst_label": "app=db|env=prod"},
        {"src": "a", "dst": "c", "port": 445, "policy_decision": "potentially_blocked",
         "src_label": "app=web|env=prod", "dst_label": "app=fileserver|env=prod"},
        {"src": "x", "dst": "y", "port": 22,  "policy_decision": "blocked",
         "src_label": None, "dst_label": "app=db|env=prod"},
    ])


def test_security_risk_includes_ransomware_section(sample_flows):
    html = render_traffic_report(sample_flows, profile="security_risk", detail_level="standard")
    # Module visibility: mod04 ransomware is security_risk only
    assert "rpt_mod04_title" in html or "Ransomware" in html or "勒索" in html


def test_network_inventory_omits_ransomware_main_section(sample_flows):
    html = render_traffic_report(sample_flows, profile="network_inventory", detail_level="standard")
    # mod04 should be appendix-only or hidden entirely in network_inventory main report
    # For this phase, we hide entirely; R2 introduces appendix.
    assert "Ransomware" not in html and "勒索" not in html


def test_network_inventory_includes_label_matrix(sample_flows):
    html = render_traffic_report(sample_flows, profile="network_inventory", detail_level="standard")
    assert "Cross-Label" in html or "Label Matrix" in html or "標籤矩陣" in html


def test_security_risk_omits_full_label_matrix(sample_flows):
    """mod07 cross_label_matrix is network_inventory primary; security_risk gets a filtered version (or skips)."""
    html = render_traffic_report(sample_flows, profile="security_risk", detail_level="standard")
    # Expect either omitted or filtered marker
    assert ("Cross-Label" not in html) or ("filtered" in html or "filtered" in html.lower())


def test_default_profile_is_security_risk_in_e2e(sample_flows):
    html_default = render_traffic_report(sample_flows, detail_level="standard")
    html_explicit = render_traffic_report(sample_flows, profile="security_risk", detail_level="standard")
    # Same length within rounding (timestamps may differ)
    assert abs(len(html_default) - len(html_explicit)) < 200
```

- [ ] **Step 2: Run — fix any wiring gaps**

```bash
python3 -m pytest tests/test_traffic_profile_split.py -v
```

If the test entry point name (`render_traffic_report`) does not match the real function, adjust the import.

- [ ] **Step 3: Commit**

```bash
git add tests/test_traffic_profile_split.py
git commit -m "test(report): end-to-end Traffic profile split — security_risk vs network_inventory"
```

---

## Task 25: Surface `traffic_report_profile` in CLI / GUI report builder

**Files:**
- Modify: CLI report subcommand (locate via `grep -rn 'def report\|@report' src/cli/`)
- Modify: GUI report-builder template/JS (locate via `grep -rn 'report_format\|traffic_report' src/templates/ src/static/js/`)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add CLI option**

If CLI has `illumio-ops report traffic`, add `--profile [security_risk|network_inventory]` (default `security_risk`).

- [ ] **Step 2: Add GUI dropdown**

In the report-builder UI (Settings → Report or similar), add a dropdown "Traffic Report Profile" with the two values. i18n keys: `gui_report_profile_label`, `gui_report_profile_security_risk`, `gui_report_profile_network_inventory`.

- [ ] **Step 3: Pass through to backend**

Whichever HTTP endpoint generates reports must accept and pass `traffic_report_profile`.

- [ ] **Step 4: Smoke test**

Manual: generate one report each profile via CLI and via GUI; verify HTML differs as expected.

- [ ] **Step 5: i18n audit**

```bash
python3 scripts/audit_i18n_usage.py
```

- [ ] **Step 6: Commit**

```bash
git add <files modified>
git commit -m "feat(report): surface traffic_report_profile in CLI and GUI"
```

---

## Task 26: Phase R0+R1 verification gate + version bump

**Files:**
- Modify: `src/__init__.py`

- [ ] **Step 1: Full pytest**

```bash
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: ALL pass. Compare to baseline from Task 1; net should be +25 (approximate, depending on exact test counts in tasks).

- [ ] **Step 2: Full i18n audit**

```bash
python3 scripts/audit_i18n_usage.py
python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v
```

Expected: A–I = 0 findings; i18n suite passes.

- [ ] **Step 3: Generate sample reports for visual review**

Run the existing report-generation command (`illumio-ops report ...` or equivalent) twice:
1. `--profile security_risk --detail standard`
2. `--profile network_inventory --detail standard`

Open in browser. Verify:
- [ ] Each section starts with a guidance card (Purpose / Watch Signals / How to Read / Recommended Actions).
- [ ] PB wording uses "PB Uncovered Exposure" (not "Staged Coverage" or "rules ready").
- [ ] Executive Summary shows the 6 KPIs for the chosen profile.
- [ ] Top-3-Actions block appears in security_risk reports.
- [ ] Date Range shows actual dates (not N/A).
- [ ] security_risk report includes Ransomware section; network_inventory does not.
- [ ] network_inventory report includes full Cross-Label Matrix; security_risk has filtered or omitted version.

- [ ] **Step 4: Bump version**

Edit `src/__init__.py`:

```python
__version__ = "3.18.0-report-semantics"
```

(Adjust if the project uses a different next-tag pattern.)

- [ ] **Step 5: Commit**

```bash
git add src/__init__.py
git commit -m "chore: bump version to 3.18.0-report-semantics"
```

- [ ] **Step 6: Tag (optional, usually done on merge)**

```bash
git tag v3.18.0-report-semantics
```

---

## Self-Review Checklist

- [ ] Spec coverage:
  - G1 PB semantic correction → Tasks 12, 13, 14, 15
  - G2 Traffic profile split → Tasks 22, 23, 24, 25
  - G3 detail_level — section_guidance supports it (Task 3); full enforcement is R2's job
  - G4 reader-guide framework → Tasks 3-11
  - G6 (XLSX) — out of scope here, deferred to R2 (Task R2.4)
  - G7 (R3 modules) — out of scope here, deferred to R3
- [ ] All new i18n keys added to BOTH `src/i18n_en.json` and `src/i18n_zh_TW.json` (Tasks 4, 8, 9, 10, 11, 15, 25).
- [ ] `staged_coverage` alias preserved (Tasks 13, 19, 21); removal scheduled for v3.21 documented in Task 16.
- [ ] Type/name consistency:
  - Profile values: `security_risk`, `network_inventory` (no `combined`) — consistent across tasks.
  - KPI names match spec §6.4 — Tasks 18, 19, 20.
  - `SectionGuidance` dataclass fields — consistent in Tasks 3, 4, 8-11.
  - `render_section_guidance(module_id, profile, detail_level)` signature — Tasks 4, 5, 6, 7, 23.
- [ ] No TBD/TODO/placeholders — every step has actual code or commands.
- [ ] Tests run after every task that produces them; final pytest gate in Task 26.
- [ ] i18n audit gate present after every task that adds keys; final gate in Task 26.
