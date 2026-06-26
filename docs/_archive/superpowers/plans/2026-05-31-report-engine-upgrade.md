# Report Engine Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the 5 HTML reports decision-useful and presentable: add "vs previous run" KPI deltas (incl. VEN), replace zero-insight donuts with bars, give NetworkInventory its own cover, extract Audit's concern card into a shared component, and protect cards/tables from mid-page print splits.

**Architecture:** Reuse the existing `trend_store.py` per-run delta engine (already wired for Traffic/Audit/Policy; add VEN). Convert skewed `type:"pie"` chart specs to `type:"bar"` (same data shape). Branch the Traffic cover on `self._profile`. Lift `AuditHtmlExporter._attention_section` into a shared `concern_card.py` + move its CSS into `BASE_CSS`. Add `page-break-inside:avoid` print rules.

**Tech Stack:** Python 3.12, the `src/report/exporters/*` HTML exporters, `chart_renderer.py` (Plotly), `report_css.py`, pytest, playwright (print-emulation visual check).

**Spec:** `docs/superpowers/specs/2026-05-31-report-engine-upgrade-design.md`

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/report/ven_status_generator.py` | Modify | Wire trend_store → `_trend_deltas` |
| `src/report/exporters/ven_html_exporter.py` | Modify | Render VEN delta row; pie→bar |
| `src/report/exporters/concern_card.py` | Create | Shared concern-card renderer |
| `src/report/exporters/audit_html_exporter.py` | Modify | Use shared concern_card |
| `src/report/exporters/report_css.py` | Modify | Move concern CSS to BASE_CSS; print rules |
| `src/report/exporters/html_exporter.py` | Modify | NetworkInventory cover branch |
| `src/report/analysis/mod01_traffic_overview.py`, `analysis/policy_usage/pu_mod04_deny_effectiveness.py` | Modify | pie→bar |
| `src/report/report_i18n.py` or `src/i18n_*.json` | Modify | `rpt_cover_type_inventory` |
| `tests/test_report_engine_upgrade.py` | Create | Unit tests for all above |

---

## Task 1: VEN report — wire trend_store delta

**Files:** Modify `src/report/ven_status_generator.py`, `src/report/exporters/ven_html_exporter.py`; Test `tests/test_report_engine_upgrade.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_engine_upgrade.py
import types
import pandas as pd


def test_ven_generate_produces_trend_deltas(tmp_path):
    from src.report.ven_status_generator import VenStatusGenerator
    cm = types.SimpleNamespace(config={"settings": {"timezone": "UTC"}})

    class _Api:
        def fetch_managed_workloads(self):
            return [{"hostname": "h1", "interfaces": [{"address": "10.0.0.1"}], "labels": [],
                     "agent": {"status": {"status": "active", "hours_since_last_heartbeat": 0.1,
                                          "security_policy_sync_state": "active",
                                          "last_heartbeat_on": "2026-05-31T00:00:00Z",
                                          "agent_version": "21.5"}}}]
    g = VenStatusGenerator(cm, api_client=_Api())
    # First run: establishes baseline (no prior → deltas may be empty)
    r1 = g.generate(lang="en", output_dir=str(tmp_path))
    # Second run: a prior snapshot now exists → deltas computed
    r2 = g.generate(lang="en", output_dir=str(tmp_path))
    assert "_trend_deltas" in r2.module_results
    assert isinstance(r2.module_results["_trend_deltas"], list)
```

> If `VenStatusGenerator.generate` does not currently accept `output_dir`, add the kwarg (default `"reports/"`); the report CLI/route already passes an output dir to other generators — thread it through identically.

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_report_engine_upgrade.py::test_ven_generate_produces_trend_deltas -q`
Expected: FAIL — `KeyError: '_trend_deltas'` (or TypeError on `output_dir`).

- [ ] **Step 3: Implement — wire trend_store in `generate()`**

In `ven_status_generator.py`, inside `generate()`, after `kpis` are assembled and before returning the result, add (mirrors `report_generator.py:447-456`):

```python
        from src.report.trend_store import (
            load_previous, save_snapshot, compute_deltas, build_kpi_dict_from_metadata,
        )
        try:
            _kpi_dict = build_kpi_dict_from_metadata(kpis)
            _prev = load_previous(output_dir, "ven")
            save_snapshot(output_dir, "ven", _kpi_dict)
            result.module_results["_trend_deltas"] = compute_deltas(_kpi_dict, _prev) if _prev else []
        except Exception as e:
            logger.warning("VEN trend delta skipped: {}", e)
            result.module_results["_trend_deltas"] = []
```

(Ensure `generate(self, detail_level=..., lang="en", output_dir="reports/")` and that `result.module_results` exists — VenStatusResult already carries a dict; if not, add it.)

- [ ] **Step 4: Render the delta row in the exporter**

In `ven_html_exporter.py`, where the exec-summary is emitted (after `render_exec_summary_html`, ~line 146), insert the delta chips reusing the Traffic pattern:

```python
        _deltas = (self._result.module_results or {}).get("_trend_deltas") or []
        if _deltas:
            from src.report.exporters.html_exporter import _trend_deltas_section
            body += _trend_deltas_section(_deltas, self._lang)
```

(If `_trend_deltas_section` is not importable cleanly, copy its small chip-table body — it's ~20 lines at `html_exporter.py:217`.)

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_report_engine_upgrade.py::test_ven_generate_produces_trend_deltas -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/report/ven_status_generator.py src/report/exporters/ven_html_exporter.py tests/test_report_engine_upgrade.py
git commit -m "feat(report): VEN status report period-over-period KPI deltas"
```

---

## Task 2: Shared concern-card component

**Files:** Create `src/report/exporters/concern_card.py`; Modify `audit_html_exporter.py`, `report_css.py`; Test (extend).

- [ ] **Step 1: Write the failing test**

```python
def test_concern_card_renders_severity_and_recommendation():
    from src.report.exporters.concern_card import render_concern_cards
    items = [{"risk": "CRITICAL", "event_type": "agent.tampering", "count": 3,
              "summary": "Firewall tampered", "actors": ["admin@lab"], "targets": [],
              "resources": [], "src_ips": ["10.0.0.1"],
              "recommendation": "Investigate workload compromise"}]
    html = render_concern_cards(items, lang="en")
    assert "risk-CRITICAL" in html
    assert "agent.tampering" in html
    assert "Investigate workload compromise" in html
    assert render_concern_cards([], lang="en") == ""   # empty → no markup
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_report_engine_upgrade.py::test_concern_card_renders_severity_and_recommendation -q`
Expected: FAIL — `ModuleNotFoundError: concern_card`.

- [ ] **Step 3: Create `concern_card.py`** by lifting `AuditHtmlExporter._attention_section` + `_risk_badge` verbatim (audit_html_exporter.py:144-186, :136). Generalize class names `audit-attn-*` → `concern-*` (keep `audit-attn-*` as duplicate classes for back-compat) and accept `lang`:

```python
"""Shared 'needs attention' concern card — severity + actor/IP/target + recommendation."""
from src.report.analysis.audit.audit_risk import RISK_ORDER, RISK_COLOR
from src.report.exporters.report_i18n import s as _s   # adjust to the project's report string getter


def _risk_badge(risk):
    color = RISK_COLOR.get(risk, "#64748b")
    return f'<span class="risk-badge" style="background:{color}">{risk}</span>'


def render_concern_cards(items, lang="en"):
    if not items:
        return ""
    rows = []
    for it in sorted(items, key=lambda x: RISK_ORDER.index(x.get("risk", "INFO"))
                     if x.get("risk") in RISK_ORDER else 99):
        risk = it.get("risk", "INFO")
        actors = ", ".join(it.get("actors") or [])
        ips = ", ".join(it.get("src_ips") or [])
        rows.append(
            f'<div class="concern-card audit-attn-item risk-{risk}">'
            f'<div class="concern-header audit-attn-header">{_risk_badge(risk)}'
            f'<code class="concern-event audit-attn-event-code">{it.get("event_type","")}</code>'
            f'<span class="concern-count audit-attn-count">x{it.get("count",0)}</span></div>'
            f'<div class="concern-summary audit-attn-summary">{it.get("summary","")}</div>'
            f'<div class="concern-meta audit-attn-meta"><strong>{_s("rpt_au_actor", lang)}</strong> {actors}'
            + (f' | <strong>IP:</strong> {ips}' if ips else "") + '</div>'
            f'<div class="concern-rec audit-attn-rec"><strong>{_s("rpt_au_rec", lang)}</strong> '
            f'{it.get("recommendation","")}</div></div>')
    return "".join(rows)
```

> Adjust the `_s` import to the report's actual string getter (audit uses a local `_s` — match its source). Verify `RISK_ORDER`/`RISK_COLOR` import path (`src/report/analysis/audit/audit_risk.py:47-48`).

- [ ] **Step 4: Audit exporter uses the shared renderer**

In `audit_html_exporter.py:144`, replace the body of `_attention_section` with `return render_concern_cards(attention_items, self._lang)` wrapped in the existing section heading (keep the `rpt_au_attention_title` `--red` wrapper at :182-186). Import `from src.report.exporters.concern_card import render_concern_cards`.

- [ ] **Step 5: Move concern CSS to BASE_CSS**

In `report_css.py`, move the `.audit-attn-*` / `.risk-*` block (lines 354-382 in `AUDIT_CSS`) into `BASE_CSS`, duplicating selectors as `.concern-card`, `.concern-header`, etc. (so both old and new classes are styled). Leave `.risk-badge` in BASE_CSS (already shared-ish).

- [ ] **Step 6: Run tests + audit report regression**

Run: `venv/bin/python -m pytest tests/test_report_engine_upgrade.py -k concern -q && venv/bin/python -m pytest tests/ -k "audit" -q`
Expected: PASS (concern test + existing audit report tests).

- [ ] **Step 7: Commit**

```bash
git add src/report/exporters/concern_card.py src/report/exporters/audit_html_exporter.py src/report/exporters/report_css.py tests/test_report_engine_upgrade.py
git commit -m "refactor(report): extract shared concern_card from audit attention section"
```

---

## Task 3: Donut → bar for skewed distributions

**Files:** Modify `analysis/mod01_traffic_overview.py:97`, `ven_html_exporter.py:114`, the audit severity chart spec, `analysis/policy_usage/pu_mod04_deny_effectiveness.py:98`; Test.

- [ ] **Step 1: Write the failing test**

```python
def test_ven_status_chart_is_bar_not_pie():
    import types
    from src.report.ven_status_generator import VenStatusGenerator
    cm = types.SimpleNamespace(config={"settings": {"timezone": "UTC"}})
    class _Api:
        def fetch_managed_workloads(self):
            return [{"hostname": f"h{i}", "interfaces": [{"address": "10.0.0.1"}], "labels": [],
                     "agent": {"status": {"status": "active", "hours_since_last_heartbeat": 0.1,
                                          "security_policy_sync_state": "active",
                                          "last_heartbeat_on": "2026-05-31T00:00:00Z"}}} for i in range(20)]
    g = VenStatusGenerator(cm, api_client=_Api())
    html = g.generate(lang="en", output_dir="reports/").html  # or _build()
    # the VEN status chart must now be a bar chart
    assert "VEN Status Distribution" in html
    # Plotly bar traces carry type:"bar"; pie would carry type:"pie"
    assert '"type": "bar"' in html or '"type":"bar"' in html
    assert '"type": "pie"' not in html.split("VEN Status Distribution")[1][:2000]
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m pytest tests/test_report_engine_upgrade.py::test_ven_status_chart_is_bar_not_pie -q`
Expected: FAIL — pie type present.

- [ ] **Step 3: Change the spec `type`** at each skewed call site from `"pie"` to `"bar"` (data `{"labels","values"}` is identical, no other change needed):
- `ven_html_exporter.py:114` — VEN Status Distribution
- `analysis/mod01_traffic_overview.py:97` — Policy Decision Breakdown
- `analysis/policy_usage/pu_mod04_deny_effectiveness.py:98` — Deny effectiveness
- The audit severity-distribution chart spec (find via `grep -rn '"type": "pie"' src/report/analysis/audit/` — change that one too).

Leave balanced-distribution pies unchanged.

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_report_engine_upgrade.py -k chart -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(report): bar charts for skewed distributions (VEN/policy/audit/deny)"
```

---

## Task 4: NetworkInventory distinct cover

**Files:** Modify `html_exporter.py:690`, add i18n key `rpt_cover_type_inventory`; Test.

- [ ] **Step 1: Write the failing test**

```python
def test_network_inventory_cover_distinct_and_no_grade(monkeypatch):
    # Build the traffic report with profile=network_inventory and assert the cover
    # title differs from security and no maturity grade block is emitted.
    from src.report.exporters import html_exporter
    # Minimal: render cover via the same path the exporter uses.
    from src.report.exporters.cover_page import build_cover_page
    inv = build_cover_page(title="Network Inventory", report_type="Network Inventory",
                           lang="en")   # no maturity_grade kwarg
    assert "Network Inventory" in inv
    assert "report-cover-grade" not in inv   # grade block suppressed when no grade passed
```

> The pure-cover assertion above locks the suppression behavior; an end-to-end profile test can be added once the exporter wiring is in place.

- [ ] **Step 2: Run to verify it fails / passes baseline**

Run: `venv/bin/python -m pytest tests/test_report_engine_upgrade.py -k inventory_cover -q`
Expected: PASS for the grade-suppression part (build_cover_page already omits grade when not passed); the title branch is enforced by Step 3.

- [ ] **Step 3: Branch the cover in the exporter**

In `html_exporter.py:690`, replace the hardcoded security title with a profile branch:

```python
        if self._profile == "network_inventory":
            _report_title = t("rpt_cover_type_inventory", lang=self._lang)
            cover_html = _build_cover_page(title=_report_title, report_type=_report_title,
                                           lang=self._lang, pce_url=..., org_name=...)
            # NOTE: no maturity_grade/maturity_score for inventory
        else:
            _report_title = t("rpt_cover_type_security", lang=self._lang)
            cover_html = _build_cover_page(title=_report_title, report_type=_report_title,
                                           lang=self._lang, pce_url=..., org_name=...,
                                           maturity_grade=mod12.get("maturity_grade"),
                                           maturity_score=mod12.get("maturity_score"))
```

(Preserve the existing `pce_url`/`org_name` args from the current call.) Also branch the `<title>` (`html_exporter.py:705`) if it currently hardcodes the traffic title.

- [ ] **Step 4: Add i18n key**

Add `rpt_cover_type_inventory` next to `rpt_cover_type_security` (same file/source — `report_i18n.STRINGS` or `i18n_*.json`): en "Network Inventory", zh_TW "網路盤點".

- [ ] **Step 5: Run + i18n parity**

Run: `venv/bin/python -m pytest tests/test_report_engine_upgrade.py -k inventory -q && venv/bin/python -m pytest tests/test_i18n_audit.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(report): distinct NetworkInventory cover (no security maturity grade)"
```

---

## Task 5: Print page-break protection

**Files:** Modify `src/report/exporters/report_css.py`.

- [ ] **Step 1: Add the rules** inside the `@media print` block (after report_css.py:296):

```css
  .card, .kpi-card, .audit-attn-item, .concern-card, .pu-card,
  .score-hero, .mat-row, .report-table-panel {
    page-break-inside: avoid; break-inside: avoid;
  }
  h2, h3 { break-after: avoid; }
```

- [ ] **Step 2: Verify present**

Run: `grep -c "break-inside: avoid" src/report/exporters/report_css.py`  Expected: ≥ 2 (existing + new).

- [ ] **Step 3: Visual print-emulation check** (optional but recommended)

Render a report with `playwright` `page.emulate_media(media="print")` + `page.pdf(...)`, open the PDF and confirm a concern card / KPI card is not split across a page boundary. (Mirror the prior VEN/trend repro scripts.)

- [ ] **Step 4: Commit**

```bash
git add src/report/exporters/report_css.py
git commit -m "fix(report): protect cards/tables/KPIs from mid-page print splits"
```

---

## Task 6: Full regression + (optional deploy)

- [ ] **Step 1:** `venv/bin/python -m pytest -q -p no:cacheprovider` — all pass.
- [ ] **Step 2:** `venv/bin/python -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -q` — pass.
- [ ] **Step 3:** Regenerate the 5 reports locally (or on the test box) and eyeball: VEN delta row, bar charts, NetworkInventory cover, concern cards, print layout.
- [ ] **Step 4:** Commit/push; deploy per session flow if desired.

## Notes for the executor
- Charts: `pie`↔`bar` share `{"labels","values"}` — only the `type` string changes. Don't touch `chart_renderer.py`.
- Keep glossary terms (Blocked/Potentially Blocked/VEN/PCE) English in zh_TW.
- The concern-card extraction must not change Audit's rendered output — verify the existing audit report test still passes byte-compatibly enough (class names additive).
