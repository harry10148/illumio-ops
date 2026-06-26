# Report R2 — Compression, Density Modes, Appendix, XLSX

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut HTML report size dramatically (target: standard Traffic report under 5 MB vs current 18.7 MB), add a `detail_level` axis (`executive`/`standard`/`full`) that gates section depth, demote low-signal sections to collapsible appendix, and replace empty XLSX shells with real per-sheet content for all four report types.

**Architecture:** R2.1 wires `detail_level` end-to-end alongside the existing `traffic_report_profile` from R1. R2.2 introduces a small `<details>` appendix wrapper and demotes mod06/mod07-detail/mod09. R2.3 changes the Plotly JS renderer so only the first chart inlines the JS bundle (subsequent charts use `include_plotlyjs=False`). R2.4 fills the four XLSX exporters with real DataFrames per sheet, scoped by `top_n` defaults.

**Tech Stack:** Python 3.11, pandas, openpyxl, Plotly, existing report exporters, pytest.

**Spec:** `docs/superpowers/specs/2026-04-25-report-content-optimization-design.md`

**Prerequisite:** R0+R1 plan merged (v3.18.0-report-semantics). `traffic_report_profile` parameter and `section_guidance.visible_in()` must exist.

**Branch:** `feat/report-r02-compact`
**Target tag:** `v3.19.0-report-compact`
**Baseline (record at start):** Run `python3 -m pytest tests/ -q` and write the count here. R1 target was ~620 passed; R2 target ~640 passed.

---

## File Structure

### New files

| Path | Responsibility |
|------|----------------|
| `tests/test_detail_level.py` | Asserts `executive` shows fewer sections than `standard`; `full` shows everything. |
| `tests/test_appendix_render.py` | Asserts demoted sections render inside `<details>` blocks. |
| `tests/test_html_size.py` | Asserts standard Traffic report size < threshold (target 5 MB). |
| `tests/test_xlsx_content_traffic.py` | Asserts Traffic XLSX has real sheets with real rows. |
| `tests/test_xlsx_content_audit.py` | Same for Audit. |
| `tests/test_xlsx_content_policy_usage.py` | Same for Policy Usage. |
| `tests/test_xlsx_content_ven.py` | Same for VEN. |

### Modified files

| Path | Change |
|------|--------|
| `src/report/report_generator.py` | Accept `detail_level` parameter (default `standard`); validate; pass to exporters and aggregators. |
| `src/report/audit_generator.py` | Accept `detail_level`. |
| `src/report/policy_usage_generator.py` | Accept `detail_level`. |
| `src/report/ven_status_generator.py` | Accept `detail_level`. |
| `src/report/exporters/html_exporter.py` | Per-section gating via `visible_in()` + new `render_appendix(title, body)` helper; demote mod06/mod07-detail/mod09 to appendix. |
| `src/report/exporters/audit_html_exporter.py` | `render_appendix` for raw events tables; `detail_level` gating. |
| `src/report/exporters/policy_usage_html_exporter.py` | Demote full hit/unused detail tables to appendix. |
| `src/report/exporters/ven_html_exporter.py` | Demote online VEN inventory to appendix. |
| `src/report/exporters/chart_renderer.py` | New `render_plotly_html(fig, *, include_js=False)` mode; track first-chart-per-document. |
| `src/report/exporters/xlsx_exporter.py` | Replace empty sheet logic with real DataFrames; scope by `top_n`. |
| CLI / GUI report option surfaces | Expose `detail_level` parameter. |
| `src/i18n_en.json`, `src/i18n_zh_TW.json` | +~15 keys (appendix labels, detail_level labels). |
| `src/__init__.py` | Bump version to `3.19.0-report-compact`. |

---

## Task 1: Capture baseline (test count + sample HTML size)

**Files:** none (read-only)

- [ ] **Step 1: Test count baseline**

```bash
python3 -m pytest tests/ -q 2>&1 | tail -3
```

Record the `N passed, M skipped` count in this plan's Baseline header.

- [ ] **Step 2: Sample report size baseline**

Locate the most recent generated traffic report (the existing samples should be in `reports/`):

```bash
ls -lh /mnt/d/RD/illumio_ops/reports/Illumio_Traffic_Report_*.html | tail -3
ls -lh /mnt/d/RD/illumio_ops/reports/illumio_audit_report_*.html | tail -3
```

Record current sizes (e.g., 18.7 MB for Traffic) so the size-reduction test in Task 11 can assert improvement.

- [ ] **Step 3: i18n audit baseline**

```bash
python3 scripts/audit_i18n_usage.py
```

Expected: 0 findings (clean from R1).

---

## Task 2: `detail_level` parameter plumbing in report generators

**Files:**
- Modify: `src/report/report_generator.py`
- Modify: `src/report/audit_generator.py`
- Modify: `src/report/policy_usage_generator.py`
- Modify: `src/report/ven_status_generator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_detail_level.py`:

```python
"""detail_level parameter must be accepted by all four generators and validated."""
import pytest


def test_traffic_generator_rejects_invalid_detail():
    from src.report.report_generator import generate_traffic_report
    with pytest.raises(ValueError, match="detail_level"):
        generate_traffic_report(flows=None, detail_level="bogus")


def test_audit_generator_rejects_invalid_detail():
    from src.report.audit_generator import generate_audit_report
    with pytest.raises(ValueError, match="detail_level"):
        generate_audit_report(events=None, detail_level="bogus")


def test_policy_usage_generator_rejects_invalid_detail():
    from src.report.policy_usage_generator import generate_policy_usage_report
    with pytest.raises(ValueError, match="detail_level"):
        generate_policy_usage_report(rules=None, detail_level="bogus")


def test_ven_generator_rejects_invalid_detail():
    from src.report.ven_status_generator import generate_ven_status_report
    with pytest.raises(ValueError, match="detail_level"):
        generate_ven_status_report(workloads=None, detail_level="bogus")


def test_default_detail_level_is_standard():
    """The default must be standard so legacy callers see no behavior change."""
    # Smoke test via signature inspection.
    import inspect
    from src.report.report_generator import generate_traffic_report
    sig = inspect.signature(generate_traffic_report)
    assert sig.parameters["detail_level"].default == "standard"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_detail_level.py -v
```

- [ ] **Step 3: Add `detail_level` parameter to each generator**

For each of the four generator functions, add to the signature (default `"standard"`) and validate at the top:

```python
_VALID_DETAIL_LEVELS = ("executive", "standard", "full")

def generate_traffic_report(..., detail_level: str = "standard", ...):
    if detail_level not in _VALID_DETAIL_LEVELS:
        raise ValueError(f"invalid detail_level: {detail_level!r}; must be one of {_VALID_DETAIL_LEVELS}")
    # ... existing logic, passing detail_level into exporters ...
```

(Apply to `audit_generator`, `policy_usage_generator`, `ven_status_generator` similarly.)

- [ ] **Step 4: Run tests — PASS**

```bash
python3 -m pytest tests/test_detail_level.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/report/report_generator.py src/report/audit_generator.py \
        src/report/policy_usage_generator.py src/report/ven_status_generator.py \
        tests/test_detail_level.py
git commit -m "feat(report): add detail_level parameter to all four generators"
```

---

## Task 3: `detail_level` enforcement in HTML exporters via `visible_in()`

**Files:**
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `src/report/exporters/audit_html_exporter.py`
- Modify: `src/report/exporters/policy_usage_html_exporter.py`
- Modify: `src/report/exporters/ven_html_exporter.py`

- [ ] **Step 1: Extend test_detail_level.py with rendering assertions**

Append:

```python
def test_executive_renders_fewer_sections_than_standard(sample_flows_fixture):
    """Same data, executive vs standard — executive HTML must be smaller and have
    fewer <h2> headers (sections demoted away)."""
    from src.report.exporters.html_exporter import render_traffic_report
    html_exec = render_traffic_report(sample_flows_fixture, profile="security_risk", detail_level="executive")
    html_std = render_traffic_report(sample_flows_fixture, profile="security_risk", detail_level="standard")
    h2_exec = html_exec.count("<h2")
    h2_std = html_std.count("<h2")
    assert h2_exec <= h2_std, (
        f"executive should have <= sections than standard; exec={h2_exec}, std={h2_std}")


def test_full_renders_at_least_as_many_sections_as_standard(sample_flows_fixture):
    from src.report.exporters.html_exporter import render_traffic_report
    html_std = render_traffic_report(sample_flows_fixture, profile="security_risk", detail_level="standard")
    html_full = render_traffic_report(sample_flows_fixture, profile="security_risk", detail_level="full")
    assert html_full.count("<h2") >= html_std.count("<h2")


@pytest.fixture
def sample_flows_fixture():
    import pandas as pd
    return pd.DataFrame([
        {"src": "a", "dst": "b", "port": 443, "policy_decision": "allowed"},
        {"src": "a", "dst": "c", "port": 445, "policy_decision": "potentially_blocked"},
        {"src": "x", "dst": "y", "port": 22,  "policy_decision": "blocked"},
    ])
```

- [ ] **Step 2: Run — expect FAIL (until exporter actually gates)**

```bash
python3 -m pytest tests/test_detail_level.py -v
```

- [ ] **Step 3: Use `visible_in()` to gate every section**

In `html_exporter.py` and the other three exporters, every section render block becomes:

```python
from src.report.section_guidance import visible_in

if visible_in("mod_id_here", profile, detail_level):
    html_parts.append(render_section_guidance("mod_id_here", profile, detail_level))
    html_parts.append(f'<h2>{t("rpt_modX_title")}</h2>')
    html_parts.append(render_modX_section(data))
```

For unregistered sections (no entry in `section_guidance.REGISTRY`), `visible_in` returns `True` by default — they always render. R0+R1 registered the high-priority modules; later modules can be added incrementally.

- [ ] **Step 4: Run tests — PASS**

```bash
python3 -m pytest tests/test_detail_level.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/html_exporter.py src/report/exporters/audit_html_exporter.py \
        src/report/exporters/policy_usage_html_exporter.py src/report/exporters/ven_html_exporter.py \
        tests/test_detail_level.py
git commit -m "feat(report): exporters gate sections via section_guidance.visible_in()"
```

---

## Task 4: Appendix infrastructure (`render_appendix` helper)

**Files:**
- Modify: `src/report/exporters/html_exporter.py`
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`
- Create: `tests/test_appendix_render.py`

- [ ] **Step 1: Add i18n keys**

```
rpt_appendix_label              "Appendix" / "附錄"
rpt_appendix_show               "Show details" / "顯示詳細"
rpt_appendix_hide               "Hide" / "隱藏"
rpt_appendix_open_in_full       "Always open in 'full' mode" / "於 full 模式自動展開"
```

- [ ] **Step 2: Write failing test**

Create `tests/test_appendix_render.py`:

```python
"""Appendix wrapper renders content inside collapsible <details> by default,
and expanded in 'full' mode."""
from src.report.exporters.html_exporter import render_appendix


def test_appendix_uses_details_in_standard():
    out = render_appendix("Test", "<p>body</p>", detail_level="standard")
    assert "<details" in out
    assert "<summary" in out
    assert "<p>body</p>" in out
    assert "open" not in out  # collapsed by default


def test_appendix_open_in_full():
    out = render_appendix("Test", "<p>body</p>", detail_level="full")
    assert "<details open" in out


def test_appendix_omitted_in_executive():
    """Executive mode hides appendix entirely."""
    out = render_appendix("Test", "<p>body</p>", detail_level="executive")
    assert out == ""
```

- [ ] **Step 3: Run — expect FAIL**

```bash
python3 -m pytest tests/test_appendix_render.py -v
```

- [ ] **Step 4: Implement `render_appendix`**

In `src/report/exporters/html_exporter.py`:

```python
from src.i18n import t


def render_appendix(title: str, body_html: str, *, detail_level: str) -> str:
    """Wrap body_html in a collapsible <details> block.
    - executive: returns "" (appendix entirely hidden).
    - standard:  collapsed by default.
    - full:      <details open>.
    title may be a translated string or an i18n key (caller decides).
    """
    if detail_level == "executive":
        return ""
    open_attr = " open" if detail_level == "full" else ""
    return (
        f'<details class="report-appendix"{open_attr}>'
        f'<summary><b>{t("rpt_appendix_label")}: {title}</b></summary>'
        f'{body_html}'
        f'</details>'
    )
```

- [ ] **Step 5: Run tests — PASS**

```bash
python3 -m pytest tests/test_appendix_render.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/report/exporters/html_exporter.py \
        src/i18n_en.json src/i18n_zh_TW.json \
        tests/test_appendix_render.py
git commit -m "feat(report): collapsible appendix wrapper render_appendix()"
```

---

## Task 5: Demote mod09 (Traffic Distribution) to Appendix

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: Locate current mod09 render**

```bash
grep -n "mod09\|traffic_distribution" /mnt/d/RD/illumio_ops/src/report/exporters/html_exporter.py
```

- [ ] **Step 2: Wrap in `render_appendix`**

Replace the direct render with:

```python
mod09_body = render_traffic_distribution_section(data)  # existing render
html_parts.append(render_appendix(
    title=t("rpt_mod09_title"),
    body_html=mod09_body,
    detail_level=detail_level,
))
```

- [ ] **Step 3: Verify visibility tests still pass**

```bash
python3 -m pytest tests/test_appendix_render.py tests/test_detail_level.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/report/exporters/html_exporter.py
git commit -m "feat(report): demote mod09 traffic distribution to collapsible appendix"
```

---

## Task 6: Demote mod06 (User/Process) to conditional appendix

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: Add condition**

mod06 only renders if user/process data is present. When present, demote to appendix in `standard`. In `executive`, hide entirely (handled by `render_appendix` returning ""):

```python
if has_user_process_data(data):
    mod06_body = render_user_process_section(data)
    html_parts.append(render_appendix(
        title=t("rpt_mod06_title"),
        body_html=mod06_body,
        detail_level=detail_level,
    ))
```

- [ ] **Step 2: Smoke test**

```bash
python3 -m pytest tests/ -k "mod06 or user_process" -v
```

- [ ] **Step 3: Commit**

```bash
git add src/report/exporters/html_exporter.py
git commit -m "feat(report): demote mod06 user/process to conditional appendix"
```

---

## Task 7: Demote mod07 detail rows in security_risk profile

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: In security_risk profile, render mod07 as filtered top-N + appendix for full matrix**

```python
if profile == "security_risk":
    # Top-N risky crossings only in main; full matrix in appendix.
    top_risky = render_mod07_top_risky(data, n=20)
    html_parts.append(render_section_guidance("mod07_cross_label_matrix", profile, detail_level))
    html_parts.append(f'<h2>{t("rpt_mod07_title")} ({t("rpt_mod07_filtered")})</h2>')
    html_parts.append(top_risky)
    html_parts.append(render_appendix(
        title=t("rpt_mod07_full_matrix"),
        body_html=render_mod07_full_matrix(data),
        detail_level=detail_level,
    ))
elif profile == "network_inventory":
    # Full matrix in main (it's the primary section for this profile).
    html_parts.append(render_section_guidance("mod07_cross_label_matrix", profile, detail_level))
    html_parts.append(f'<h2>{t("rpt_mod07_title")}</h2>')
    html_parts.append(render_mod07_full_matrix(data))
```

Add i18n keys: `rpt_mod07_filtered`, `rpt_mod07_full_matrix`.

- [ ] **Step 2: i18n audit + smoke**

```bash
python3 scripts/audit_i18n_usage.py
python3 -m pytest tests/ -k "mod07 or label_matrix or profile_split" -v
```

- [ ] **Step 3: Commit**

```bash
git add src/report/exporters/html_exporter.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(report): mod07 split — filtered top-N in security_risk, full matrix to appendix"
```

---

## Task 8: Plotly single-bundle renderer mode

**Files:**
- Modify: `src/report/exporters/chart_renderer.py`

- [ ] **Step 1: Read current renderer**

```bash
grep -n "include_plotlyjs\|render_plotly" /mnt/d/RD/illumio_ops/src/report/exporters/chart_renderer.py
```

- [ ] **Step 2: Add an explicit `include_js` parameter and a per-document tracker**

```python
def render_plotly_html(fig, *, include_js: bool = False, **kwargs) -> str:
    """Render a Plotly figure to HTML.
    include_js=True  -> bundle full plotly JS (use for first chart in a document).
    include_js=False -> reference already-loaded plotly (for subsequent charts).
    """
    return fig.to_html(
        include_plotlyjs="inline" if include_js else False,
        full_html=False,
        **kwargs,
    )


class FirstChartTracker:
    """Use one instance per document. First call returns True; subsequent False."""
    def __init__(self):
        self._first = True
    def consume(self) -> bool:
        v = self._first
        self._first = False
        return v
```

- [ ] **Step 3: Quick test**

Add a small unit test in `tests/test_html_size.py` (created in Task 11) — for now skip until that task.

- [ ] **Step 4: Commit**

```bash
git add src/report/exporters/chart_renderer.py
git commit -m "feat(report): chart_renderer supports single-bundle plotly load"
```

---

## Task 9: Use `FirstChartTracker` in Traffic HTML exporter

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: Instantiate tracker once per report render**

At the top of the entry function (e.g., `render_traffic_report`):

```python
from src.report.exporters.chart_renderer import render_plotly_html, FirstChartTracker

def render_traffic_report(flows, profile="security_risk", detail_level="standard"):
    chart_tracker = FirstChartTracker()
    # ... existing setup ...
```

- [ ] **Step 2: Replace every `render_plotly_html(fig)` call**

```python
html_parts.append(render_plotly_html(fig, include_js=chart_tracker.consume()))
```

- [ ] **Step 3: Smoke test — generate a report locally**

Generate a report and inspect the output. Search for `<script>` tags containing `Plotly` — should be only one full bundle inlined; subsequent chart `<div>`s reference the loaded global.

- [ ] **Step 4: Commit**

```bash
git add src/report/exporters/html_exporter.py
git commit -m "feat(report): Traffic exporter loads Plotly JS once per document"
```

---

## Task 10: Use `FirstChartTracker` in Audit / Policy Usage / VEN exporters

**Files:**
- Modify: `src/report/exporters/audit_html_exporter.py`
- Modify: `src/report/exporters/policy_usage_html_exporter.py`
- Modify: `src/report/exporters/ven_html_exporter.py`

- [ ] **Step 1: Apply same pattern as Task 9**

For each of the three exporters: instantiate `FirstChartTracker` at entry, replace every `render_plotly_html(fig)` with `render_plotly_html(fig, include_js=tracker.consume())`.

- [ ] **Step 2: Smoke test each**

```bash
python3 -m pytest tests/ -k "audit or policy_usage or ven" -q
```

- [ ] **Step 3: Commit**

```bash
git add src/report/exporters/audit_html_exporter.py \
        src/report/exporters/policy_usage_html_exporter.py \
        src/report/exporters/ven_html_exporter.py
git commit -m "feat(report): Audit/PolicyUsage/VEN exporters load Plotly JS once"
```

---

## Task 11: HTML size assertion test

**Files:**
- Create: `tests/test_html_size.py`

- [ ] **Step 1: Write the test**

```python
"""Standard Traffic report HTML must be smaller than the historical 18.7 MB
inline-Plotly-per-chart size. Target threshold is 5 MB."""
import pandas as pd
import pytest


@pytest.fixture
def biggish_flows():
    """Create a synthetic dataset large enough to exercise multiple charts."""
    rows = []
    for i in range(500):
        rows.append({
            "src": f"10.0.{i // 256}.{i % 256}",
            "dst": f"10.1.{i // 256}.{i % 256}",
            "port": 443 if i % 2 == 0 else 80,
            "policy_decision": ["allowed", "potentially_blocked", "blocked"][i % 3],
            "src_label": f"app=app{i % 10}|env=prod",
            "dst_label": f"app=app{(i + 1) % 10}|env=prod",
        })
    return pd.DataFrame(rows)


def test_traffic_standard_under_5mb(biggish_flows):
    from src.report.exporters.html_exporter import render_traffic_report
    html = render_traffic_report(biggish_flows, profile="security_risk", detail_level="standard")
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)
    assert size_mb < 5.0, f"Traffic standard report is {size_mb:.1f} MB (target <5 MB)"


def test_plotly_bundle_inlined_only_once(biggish_flows):
    """Count plotly script bundle occurrences — should be exactly 1."""
    from src.report.exporters.html_exporter import render_traffic_report
    html = render_traffic_report(biggish_flows, profile="security_risk", detail_level="standard")
    # Plotly bundle marker: 'Plotly.newPlot' appears in chart divs (cheap),
    # but the FULL JS bundle includes 'Plotly = require'.
    full_bundle_marker = "plotly-graph-div"  # adjust if a more reliable marker exists
    chart_count = html.count(full_bundle_marker)
    # Hard to count "bundle" exactly without inspecting plotly internals;
    # alternative: assert that the largest <script> appears once.
    script_blocks = html.split("<script")
    big_scripts = [s for s in script_blocks if len(s) > 100_000]
    assert len(big_scripts) <= 1, (
        f"expected single big Plotly bundle, found {len(big_scripts)} (>100KB script blocks)")
```

- [ ] **Step 2: Run the test**

```bash
python3 -m pytest tests/test_html_size.py -v
```

If it fails, investigate: are charts using the tracker? Is the renderer mode flag respected? Adjust Tasks 8/9/10 as needed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_html_size.py
git commit -m "test(report): assert Traffic standard report < 5MB and Plotly inlined once"
```

---

## Task 12: Traffic XLSX real content

**Files:**
- Modify: `src/report/report_generator.py` (or `src/report/exporters/xlsx_exporter.py`)
- Create: `tests/test_xlsx_content_traffic.py`

- [ ] **Step 1: Write failing test**

```python
"""Traffic XLSX must contain real DataFrames per sheet, not empty shells."""
import io
import pandas as pd
import pytest
from openpyxl import load_workbook


@pytest.fixture
def sample_flows():
    return pd.DataFrame([
        {"src": "10.0.0.1", "dst": "10.0.0.2", "port": 443, "policy_decision": "allowed"},
        {"src": "10.0.0.1", "dst": "10.0.0.3", "port": 445, "policy_decision": "potentially_blocked"},
        {"src": "10.0.0.4", "dst": "10.0.0.2", "port": 22,  "policy_decision": "blocked"},
    ])


def test_traffic_xlsx_has_expected_sheets(sample_flows, tmp_path):
    from src.report.report_generator import generate_traffic_xlsx
    out_path = tmp_path / "traffic.xlsx"
    generate_traffic_xlsx(sample_flows, str(out_path), profile="security_risk")
    wb = load_workbook(str(out_path))
    expected = {
        "Executive Summary",
        "Policy Decisions",
        "Uncovered Flows",
        "Lateral Movement",
        "Top Talkers",
    }
    assert expected.issubset(set(wb.sheetnames)), f"missing: {expected - set(wb.sheetnames)}"


def test_traffic_xlsx_executive_sheet_has_kpis(sample_flows, tmp_path):
    from src.report.report_generator import generate_traffic_xlsx
    out_path = tmp_path / "traffic.xlsx"
    generate_traffic_xlsx(sample_flows, str(out_path), profile="security_risk")
    wb = load_workbook(str(out_path))
    sheet = wb["Executive Summary"]
    rows = list(sheet.iter_rows(values_only=True))
    flat = [str(c) for r in rows for c in r if c is not None]
    # The 6 KPI names must appear somewhere in the sheet.
    for kpi in ("microsegmentation_maturity", "active_allow_coverage",
                "pb_uncovered_exposure", "blocked_flows",
                "high_risk_lateral_paths", "top_remediation_action"):
        assert any(kpi in s for s in flat), f"KPI {kpi} missing from Executive sheet"


def test_traffic_xlsx_uncovered_sheet_has_rows(sample_flows, tmp_path):
    from src.report.report_generator import generate_traffic_xlsx
    out_path = tmp_path / "traffic.xlsx"
    generate_traffic_xlsx(sample_flows, str(out_path), profile="security_risk")
    wb = load_workbook(str(out_path))
    sheet = wb["Uncovered Flows"]
    rows = list(sheet.iter_rows(values_only=True))
    # Header + at least one PB row from sample_flows
    assert len(rows) >= 2, f"expected header + ≥1 PB row, got {len(rows)} rows"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_xlsx_content_traffic.py -v
```

- [ ] **Step 3: Implement / extend `generate_traffic_xlsx`**

In `src/report/report_generator.py` (or wherever the Traffic XLSX entry lives), replace any empty-sheet logic with concrete DataFrame writes per sheet. Use existing analysis modules' output as the source.

```python
def generate_traffic_xlsx(flows, out_path: str, profile: str = "security_risk", top_n: int = 100):
    import pandas as pd
    from openpyxl import Workbook
    from src.report.analysis import (mod02_policy_decisions, mod03_uncovered_flows,
                                      mod12_executive_summary, mod15_lateral_movement)

    wb = Workbook()
    # Drop default sheet
    wb.remove(wb.active)

    # Executive Summary
    exec_data = mod12_executive_summary.analyze(flows, profile=profile)
    ws = wb.create_sheet("Executive Summary")
    ws.append(["KPI", "Value"])
    for k, v in exec_data.get("kpis", {}).items():
        ws.append([k, str(v)])

    # Policy Decisions
    pol = mod02_policy_decisions.analyze(flows)
    ws = wb.create_sheet("Policy Decisions")
    pol_df = pd.DataFrame(pol.get("breakdown", []))
    if not pol_df.empty:
        ws.append(list(pol_df.columns))
        for row in pol_df.itertuples(index=False):
            ws.append(list(row))

    # Uncovered Flows
    unc = mod03_uncovered_flows.analyze(flows)
    ws = wb.create_sheet("Uncovered Flows")
    unc_df = pd.DataFrame(unc.get("rows", []))[:top_n]
    if not unc_df.empty:
        ws.append(list(unc_df.columns))
        for row in unc_df.itertuples(index=False):
            ws.append(list(row))
    else:
        ws.append(["src", "dst", "port", "policy_decision"])

    # Lateral Movement (security_risk only; for network_inventory it can be omitted)
    lat = mod15_lateral_movement.analyze(flows)
    ws = wb.create_sheet("Lateral Movement")
    lat_df = pd.DataFrame(lat.get("paths", []))[:top_n]
    if not lat_df.empty:
        ws.append(list(lat_df.columns))
        for row in lat_df.itertuples(index=False):
            ws.append(list(row))

    # Top Talkers
    ws = wb.create_sheet("Top Talkers")
    talkers = (flows.groupby(["src", "dst"]).size()
               .sort_values(ascending=False).head(top_n)
               .reset_index(name="flows"))
    ws.append(list(talkers.columns))
    for row in talkers.itertuples(index=False):
        ws.append(list(row))

    wb.save(out_path)
    return out_path
```

(Adjust analysis-module API calls to actual signatures; the structure of "analyze → DataFrame → write sheet" is the pattern.)

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_xlsx_content_traffic.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/report/report_generator.py tests/test_xlsx_content_traffic.py
git commit -m "feat(report): Traffic XLSX exports real per-sheet DataFrames"
```

---

## Task 13: Audit XLSX real content

**Files:**
- Modify: `src/report/audit_generator.py`
- Create: `tests/test_xlsx_content_audit.py`

- [ ] **Step 1: Write failing test**

```python
"""Audit XLSX must contain attention/health/users/policy/correlation sheets with real rows."""
import pandas as pd
import pytest
from openpyxl import load_workbook


@pytest.fixture
def sample_events():
    return pd.DataFrame([
        {"timestamp": "2026-04-25T01:00:00Z", "actor": "admin", "event": "policy.create"},
        {"timestamp": "2026-04-25T02:00:00Z", "actor": "admin", "event": "policy.delete"},
        {"timestamp": "2026-04-25T03:00:00Z", "actor": "svc-deploy", "event": "auth.fail"},
    ])


def test_audit_xlsx_has_expected_sheets(sample_events, tmp_path):
    from src.report.audit_generator import generate_audit_xlsx
    out_path = tmp_path / "audit.xlsx"
    generate_audit_xlsx(sample_events, str(out_path))
    wb = load_workbook(str(out_path))
    expected = {"Attention Required", "Health", "Users", "Policy Changes", "Correlations"}
    assert expected.issubset(set(wb.sheetnames))


def test_audit_xlsx_has_real_rows(sample_events, tmp_path):
    from src.report.audit_generator import generate_audit_xlsx
    out_path = tmp_path / "audit.xlsx"
    generate_audit_xlsx(sample_events, str(out_path))
    wb = load_workbook(str(out_path))
    sheet = wb["Policy Changes"]
    rows = list(sheet.iter_rows(values_only=True))
    assert len(rows) >= 2  # header + at least one row
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_xlsx_content_audit.py -v
```

- [ ] **Step 3: Implement `generate_audit_xlsx`**

Same pattern as Traffic: instantiate audit analysis modules (`audit_mod00_executive`, `audit_mod01_health`, `audit_mod02_users`, `audit_mod03_policy`, `audit_mod04_correlation`), get their DataFrames, write each to a sheet.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_xlsx_content_audit.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/report/audit_generator.py tests/test_xlsx_content_audit.py
git commit -m "feat(report): Audit XLSX exports real per-sheet DataFrames"
```

---

## Task 14: Policy Usage XLSX real content

**Files:**
- Modify: `src/report/policy_usage_generator.py`
- Create: `tests/test_xlsx_content_policy_usage.py`

- [ ] **Step 1: Write failing test**

```python
"""Policy Usage XLSX: hit/unused/deny/execution sheets with real rows."""
import pandas as pd
import pytest
from openpyxl import load_workbook


@pytest.fixture
def sample_rules():
    return pd.DataFrame([
        {"rule_id": "r-1", "name": "allow web→db", "hit_count": 1234, "is_deny": False},
        {"rule_id": "r-2", "name": "deny untrusted", "hit_count": 0,    "is_deny": True},
        {"rule_id": "r-3", "name": "old broad allow", "hit_count": 0,   "is_deny": False},
    ])


def test_policy_usage_xlsx_has_expected_sheets(sample_rules, tmp_path):
    from src.report.policy_usage_generator import generate_policy_usage_xlsx
    out_path = tmp_path / "pu.xlsx"
    generate_policy_usage_xlsx(sample_rules, str(out_path))
    wb = load_workbook(str(out_path))
    expected = {"Hit Rules", "Unused Rules", "Deny Effectiveness", "Execution Stats"}
    assert expected.issubset(set(wb.sheetnames))


def test_policy_usage_xlsx_unused_sheet_has_rows(sample_rules, tmp_path):
    from src.report.policy_usage_generator import generate_policy_usage_xlsx
    out_path = tmp_path / "pu.xlsx"
    generate_policy_usage_xlsx(sample_rules, str(out_path))
    wb = load_workbook(str(out_path))
    sheet = wb["Unused Rules"]
    rows = list(sheet.iter_rows(values_only=True))
    assert len(rows) >= 2  # r-2 (deny zero-hit) and r-3 (allow zero-hit)
```

- [ ] **Step 2: Run — expect FAIL; implement; rerun**

Implement `generate_policy_usage_xlsx` using `pu_mod02_hit_detail`, `pu_mod03_unused_detail`, `pu_mod04_deny_effectiveness`, plus an Execution Stats sheet (query timings, etc.).

- [ ] **Step 3: Commit**

```bash
git add src/report/policy_usage_generator.py tests/test_xlsx_content_policy_usage.py
git commit -m "feat(report): Policy Usage XLSX exports real per-sheet DataFrames"
```

---

## Task 15: VEN XLSX real content

**Files:**
- Modify: `src/report/ven_status_generator.py`
- Create: `tests/test_xlsx_content_ven.py`

- [ ] **Step 1: Write failing test**

```python
"""VEN XLSX: online / offline / lost <24h / lost 24-48h sheets with real rows."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from openpyxl import load_workbook


@pytest.fixture
def sample_workloads():
    now = datetime.now(timezone.utc)
    return pd.DataFrame([
        {"hostname": "web-1", "ven_status": "active", "last_heartbeat": now.isoformat()},
        {"hostname": "web-2", "ven_status": "offline", "last_heartbeat": (now - timedelta(hours=72)).isoformat()},
        {"hostname": "db-1",  "ven_status": "active",  "last_heartbeat": (now - timedelta(hours=12)).isoformat()},
        {"hostname": "db-2",  "ven_status": "active",  "last_heartbeat": (now - timedelta(hours=36)).isoformat()},
    ])


def test_ven_xlsx_has_expected_sheets(sample_workloads, tmp_path):
    from src.report.ven_status_generator import generate_ven_xlsx
    out_path = tmp_path / "ven.xlsx"
    generate_ven_xlsx(sample_workloads, str(out_path))
    wb = load_workbook(str(out_path))
    expected = {"Online", "Offline", "Lost <24h", "Lost 24-48h"}
    assert expected.issubset(set(wb.sheetnames))


def test_ven_xlsx_offline_sheet_has_offline_workloads(sample_workloads, tmp_path):
    from src.report.ven_status_generator import generate_ven_xlsx
    out_path = tmp_path / "ven.xlsx"
    generate_ven_xlsx(sample_workloads, str(out_path))
    wb = load_workbook(str(out_path))
    sheet = wb["Offline"]
    rows = list(sheet.iter_rows(values_only=True))
    flat = [str(c) for r in rows for c in r if c is not None]
    assert any("web-2" in s for s in flat)
```

- [ ] **Step 2: Implement `generate_ven_xlsx`**

Use the existing VEN status logic to bucket workloads by heartbeat freshness. Write each bucket to its own sheet.

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/test_xlsx_content_ven.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/report/ven_status_generator.py tests/test_xlsx_content_ven.py
git commit -m "feat(report): VEN XLSX exports real per-sheet DataFrames"
```

---

## Task 16: Surface `detail_level` in CLI / GUI

**Files:**
- Modify: CLI report subcommand
- Modify: GUI report-builder template/JS
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: CLI `--detail-level [executive|standard|full]` for all four report subcommands**

Default `standard`. Validate against the enum.

- [ ] **Step 2: GUI dropdown**

Add a "Detail Level" dropdown next to the Profile dropdown (added in R1 Task 25). i18n keys: `gui_report_detail_label`, `gui_report_detail_executive`, `gui_report_detail_standard`, `gui_report_detail_full`.

- [ ] **Step 3: Backend pass-through**

Whichever HTTP endpoint generates reports must accept and pass `detail_level`.

- [ ] **Step 4: Manual smoke**

Generate three Traffic reports (executive, standard, full) via CLI and via GUI; verify HTML differs as expected.

- [ ] **Step 5: i18n audit + commit**

```bash
python3 scripts/audit_i18n_usage.py
git add <files modified>
git commit -m "feat(report): surface detail_level in CLI and GUI"
```

---

## Task 17: Phase R2 verification + version bump

**Files:**
- Modify: `src/__init__.py`

- [ ] **Step 1: Full pytest**

```bash
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: previous baseline + ~20 new tests.

- [ ] **Step 2: i18n audit**

```bash
python3 scripts/audit_i18n_usage.py
python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v
```

- [ ] **Step 3: Generate sample report and confirm size reduction**

Generate one Traffic standard report. Confirm:
- File size < 5 MB (compare to baseline ~18.7 MB).
- Plotly bundle inlined once.
- mod09 / mod06 / mod07-detail in collapsible appendix.
- XLSX has real content per sheet (open and inspect).

- [ ] **Step 4: Bump version**

Edit `src/__init__.py`:

```python
__version__ = "3.19.0-report-compact"
```

- [ ] **Step 5: Commit**

```bash
git add src/__init__.py
git commit -m "chore: bump version to 3.19.0-report-compact"
```

---

## Self-Review Checklist

- [ ] Spec coverage:
  - G3 (`detail_level` axis): Tasks 2, 3, 16
  - G5 (HTML compression): Tasks 4-11 (appendix + Plotly single-bundle + size assertion)
  - G6 (XLSX real content): Tasks 12, 13, 14, 15
- [ ] All new i18n keys added to BOTH `src/i18n_en.json` and `src/i18n_zh_TW.json` (Tasks 4, 7, 16).
- [ ] Type/name consistency:
  - `detail_level` enum: `("executive", "standard", "full")` — Tasks 2, 3, 4, 16.
  - `render_appendix(title, body_html, *, detail_level)` signature — Tasks 4-7.
  - `render_plotly_html(fig, *, include_js)` signature + `FirstChartTracker` — Tasks 8, 9, 10.
  - XLSX sheet names — Tasks 12-15 each define their own; tests assert exact names.
- [ ] No TBD/TODO/placeholders — every step has actual code or commands.
- [ ] Tests run after every task that produces them; final pytest gate in Task 17.
- [ ] i18n audit gate present after every task that adds keys; final gate in Task 17.
- [ ] Backward compatibility: `staged_coverage` alias from R1 untouched here (R2 doesn't change KPIs).
