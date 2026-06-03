# Traffic Report Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the single profile-switched Traffic report into two independent report types — **Security & Risk** and **Network Inventory** — each with its own exporter subclass, facade, CLI verb, scheduler type, and filename, while sharing one analysis engine (`ReportGenerator`).

**Architecture:** `ReportGenerator` stays the shared traffic-flow analysis engine (runs mod01–16 once → `ReportResult`). The exporter is refactored so `_TrafficReportBase._build()` computes EVERY possible section into a `sections` dict + nav specs, and each subclass declares only its **ordered section keys**. Two thin facades wrap generator + the right exporter. `report traffic --profile` and scheduler `report_type:"traffic"` stay as long-term compat aliases.

**Tech Stack:** Python 3.12, click CLI, APScheduler, pytest. Spec: `docs/superpowers/specs/2026-06-03-traffic-report-split-design.md`.

---

## File Structure

**Modify:**
- `src/report/exporters/html_exporter.py` — refactor `HtmlExporter` → `_TrafficReportBase` (sections-dict + ordered-keys hook); add `SecurityRiskHtmlExporter` + `NetworkInventoryHtmlExporter` subclasses. Keep `HtmlExporter = SecurityRiskHtmlExporter` alias for back-compat.
- `src/report/report_generator.py` — `export()` selects exporter class by report type (not profile string).
- `src/cli/report.py` — add `report security` + `report inventory` commands + `generate_security_report`/`generate_inventory_report` helpers; keep `report traffic --profile` as deprecated alias.
- `src/report_scheduler.py` — `_generate_report` handles `report_type` `security_risk`/`network_inventory`; keep `traffic`(+profile) compat.
- `src/i18n_en.json`, `src/i18n_zh_TW.json` — new title/CLI-help keys.

**Create:**
- `src/report/security_risk_report.py` — `SecurityRiskReport` facade.
- `src/report/network_inventory_report.py` — `NetworkInventoryReport` facade.
- `tests/test_traffic_report_split.py` — exporter section-set + facade + CLI + scheduler tests.

**Key invariant (the only content delta vs today):** Network Inventory must NOT render the **maturity hero** or the **Enforcement Readiness (mod13)** section. Everything else already diverges correctly by section set.

---

## Task 1: Refactor exporter into base + section-dict assembly

**Files:**
- Modify: `src/report/exporters/html_exporter.py`
- Test: `tests/test_traffic_report_split.py`

**Goal:** Replace the profile `if/else` in `_build()` (current lines ~540–694) with: (a) a `sections: dict[str, str]` holding every section's HTML, (b) `nav_specs: dict[str, tuple]` for nav links, (c) two overridable hooks `_ordered_section_keys()` and `_report_kind()`/filename. The base raises `NotImplementedError` for the hooks (it's abstract); subclasses (Task 2) provide them. Keep `HtmlExporter` as an alias so nothing else breaks mid-refactor.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_traffic_report_split.py`:

```python
"""Traffic report split: two independent exporter types from a shared base."""
from src.report.exporters.html_exporter import (
    _TrafficReportBase, SecurityRiskHtmlExporter, NetworkInventoryHtmlExporter,
)


def _results():
    # Minimal module results so _build() runs without a live PCE.
    return {
        "mod00": {}, "mod01": {"total_flows": 10}, "mod02": {}, "mod03": {},
        "mod04": {}, "mod06": {}, "mod07": {}, "mod08": {}, "mod09": {},
        "mod10": {}, "mod11": {}, "mod13": {}, "mod14": {}, "mod15": {},
        "mod12": {"kpis": [], "key_findings": [], "maturity_score": 60,
                  "maturity_grade": "B", "maturity_dimensions": {}},
        "findings": [],
    }


def test_base_is_abstract():
    import pytest
    b = _TrafficReportBase(_results())
    with pytest.raises(NotImplementedError):
        b._ordered_section_keys()


def test_security_renders_maturity_and_readiness():
    html = SecurityRiskHtmlExporter(_results()).build()
    assert 'id="summary"' in html       # maturity hero section present
    assert 'id="readiness"' in html
    assert 'id="ransomware"' in html
    assert 'id="findings"' in html


def test_inventory_omits_maturity_and_readiness():
    html = NetworkInventoryHtmlExporter(_results()).build()
    assert 'id="readiness"' not in html     # deduped: security-only
    assert 'score-hero' not in html         # maturity hero deduped
    assert 'id="unmanaged"' in html
    assert 'id="distribution"' in html
    # shared sections kept in both:
    assert 'id="overview"' in html and 'id="policy"' in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_traffic_report_split.py -p no:cacheprovider -q`
Expected: ImportError (`_TrafficReportBase`/subclasses don't exist yet).

- [ ] **Step 3: Rename `HtmlExporter` → `_TrafficReportBase` and refactor `_build()`**

In `src/report/exporters/html_exporter.py`:

(a) Rename the class `class HtmlExporter:` → `class _TrafficReportBase:`. Keep `__init__`, `build()`, all `_modNN_html`, `_section`, `_attack_summary_html`, `_trend_deltas_html`, and every other method UNCHANGED (they stay in the base).

(b) Add abstract hooks to the base (after `__init__`):

```python
    # ── Subclass contract ────────────────────────────────────────────────
    REPORT_KIND = ""          # "SecurityRisk" | "NetworkInventory" (filename)

    def _ordered_section_keys(self) -> list[str]:
        """Ordered section keys this report renders (subclass provides)."""
        raise NotImplementedError

    def _include_maturity(self) -> bool:
        """Whether the summary hero shows the micro-segmentation maturity block."""
        raise NotImplementedError
```

(c) Replace `export()`'s `profile_label` line (current :417) so the filename comes from the subclass:

```python
        filename = f'Illumio_Traffic_Report_{self.REPORT_KIND or "SecurityRisk"}_{ts}.html'
```

(d) In `_build()`, keep all preamble computation up to and including `_mod07_block` (current ~426–553) UNCHANGED, EXCEPT: gate the maturity hero on the hook. Find where `maturity_html` is used in the hero section (current body ~623) — see step (f).

(e) Replace the profile `if/else` for nav (current ~561–592) with a **section→nav-spec map** and build nav from the subclass's ordered keys. After the `_nav_link(...)` closure definition (current :556), add:

```python
        # All possible nav links keyed by section id; subclasses pick the order.
        _findings_badge = n_findings
        _nav_spec = {
            'summary':        _nav_link('summary', 'rpt_tr_nav_summary', 'Executive Summary'),
            'overview':       _nav_link('overview', 'rpt_tr_nav_overview', '1 Traffic Overview'),
            'policy':         _nav_link('policy', 'rpt_tr_nav_policy', '2 Policy Decisions'),
            'uncovered':      _nav_link('uncovered', 'rpt_tr_nav_uncovered', '3 Uncovered Flows'),
            'ransomware':     _nav_link('ransomware', 'rpt_tr_nav_ransomware', '4 Ransomware Exposure'),
            'user':           (_nav_link('user', 'rpt_tr_nav_user', '6 User & Process') if _mod06_has_data else ''),
            'matrix':         (_nav_link('matrix', 'rpt_tr_nav_matrix', '7 Cross-Label Matrix') if _mod07_block else ''),
            'unmanaged':      _nav_link('unmanaged', 'rpt_tr_nav_unmanaged', '8 Unmanaged Hosts'),
            'distribution':   _nav_link('distribution', 'rpt_tr_nav_distribution', '9 Traffic Distribution'),
            'allowed':        _nav_link('allowed', 'rpt_tr_nav_allowed', '10 Allowed Traffic'),
            'bandwidth':      _nav_link('bandwidth', 'rpt_tr_nav_bandwidth', '11 Bandwidth & Volume'),
            'readiness':      _nav_link('readiness', 'rpt_tr_nav_readiness', '13 Enforcement Readiness'),
            'infrastructure': _nav_link('infrastructure', 'rpt_tr_nav_infrastructure', '14 Infrastructure Scoring'),
            'lateral':        _nav_link('lateral', 'rpt_tr_nav_lateral', '15 Lateral Movement'),
            'ringfence':      (_nav_link('ringfence', 'rpt_tr_nav_ringfence', 'Application Ringfence') if visible_in('mod_ringfence', profile, detail_level) else ''),
            'change_impact':  (_nav_link('change_impact', 'rpt_tr_nav_change_impact', 'Change Impact') if visible_in('mod_change_impact', profile, detail_level) else ''),
            'findings':       _nav_link('findings', 'rpt_tr_nav_findings', 'Findings', badge=_findings_badge),
        }
        _nav_links = [_nav_spec.get(k, '') for k in self._ordered_section_keys()]
```

(f) Replace the body assembly (current ~607–694) with a **section→html map** then assemble from the ordered keys. Build each section's HTML into `_sec`:

```python
        exec_html = render_exec_summary_html(_traffic_mod00, report_name=t('gui_btn_traffic_report', lang=self._lang), lang=self._lang)

        # The summary hero: maturity block included only when the subclass opts in.
        _maturity_block = (f'<h2>{_s("rpt_tr_maturity_heading")}</h2>' + maturity_html) if self._include_maturity() else ''
        _hero = (
            '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            f'<div class="report-kicker">{_s("rpt_kicker_traffic")}</div>'
            + (f'<div class="report-profile-badge report-profile-badge--security">{_s("rpt_kicker_security_risk")}</div>'
               if self.REPORT_KIND == "SecurityRisk" else
               f'<div class="report-profile-badge report-profile-badge--inventory">{_s("rpt_kicker_network_inventory")}</div>')
            + f'<h1>{_s("rpt_tr_title")}</h1>'
            f'<p class="report-subtitle">{_s("rpt_generated")} ' + generated_at + '</p></div>'
            + summary_pills + _maturity_block + trend_html
            + f'<h2>{_s("rpt_key_findings")}</h2>' + key_findings_html
            + attack_summary_html + '</section>\n'
        )

        _sec = {
            'summary': _hero,
            'overview': self._section('overview', 'rpt_tr_sec_overview', 'Traffic Overview',
                          render_section_guidance('mod01', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod01_html(),
                          'rpt_tr_sec_overview_intro', 'Start from overall traffic scale, Policy coverage, and top Ports to set a baseline for reading the rest of the report.') + '\n',
            'policy': self._section('policy', 'rpt_tr_sec_policy', 'Policy Decisions',
                          render_section_guidance('mod02', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod02_html(),
                          layout='layout-b') + '\n',
            'uncovered': self._section('uncovered', 'rpt_tr_sec_uncovered', 'Uncovered Flows',
                          render_section_guidance('mod03', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod03_html(),
                          'rpt_tr_sec_uncovered_intro', 'Focus on traffic not yet covered by effective Policy, helping prioritise which Services and directions to tighten first.') + '\n',
            'ransomware': self._section('ransomware', 'rpt_tr_sec_ransomware', 'Ransomware Exposure',
                          render_section_guidance('mod04', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod04_html(),
                          'rpt_tr_sec_ransomware_intro', 'Check high-risk Ports, Allowed flows, and host exposure commonly tied to ransomware attack chains.') + '\n',
            'user': _mod06_block,
            'matrix': _mod07_block,
            'unmanaged': self._section('unmanaged', 'rpt_tr_sec_unmanaged', 'Unmanaged Hosts',
                          render_section_guidance('mod08', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod08_html(),
                          'rpt_tr_sec_unmanaged_intro', 'Inventory traffic involving hosts not managed by VEN; these typically sit outside the visibility and control boundary.') + '\n',
            'distribution': self._section('distribution', 'rpt_tr_sec_distribution', 'Traffic Distribution',
                          render_section_guidance('mod09', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod09_html()) + '\n',
            'allowed': self._section('allowed', 'rpt_tr_sec_allowed', 'Allowed Traffic',
                          render_section_guidance('mod10', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod10_html(),
                          'rpt_tr_sec_allowed_intro', 'Focus on explicitly Allowed traffic to confirm which are required business paths and which still deserve an audit.') + '\n',
            'bandwidth': self._section('bandwidth', 'rpt_tr_sec_bandwidth', 'Bandwidth &amp; Volume',
                          render_section_guidance('mod11', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod11_html(),
                          'rpt_tr_sec_bandwidth_intro', 'Review high-volume flows by bandwidth and data volume to identify large backups, batch jobs, or suspected exfiltration.') + '\n',
            'readiness': self._section('readiness', 'rpt_tr_sec_readiness', 'Enforcement Readiness',
                          render_section_guidance('mod13', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod13_html(),
                          'rpt_tr_sec_readiness_intro', 'Aggregate multiple signals into a readiness score to help assess whether it is safe to tighten Enforcement.') + '\n',
            'infrastructure': self._section('infrastructure', 'rpt_tr_sec_infrastructure', 'Infrastructure Scoring',
                          render_section_guidance('mod14', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod14_html(),
                          'rpt_tr_sec_infrastructure_intro', 'Identify critical nodes and infrastructure roles with large blast radius from application communication patterns.') + '\n',
            'lateral': self._section('lateral', 'rpt_tr_sec_lateral', 'Lateral Movement',
                          render_section_guidance('mod15', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod15_html(),
                          'rpt_tr_sec_lateral_intro', 'Focus on paths, Services, and sources tied to lateral movement to surface spread risk.') + '\n',
            'ringfence': (self._section('ringfence', 'rpt_mod_ringfence_title', 'Application Ringfence',
                          render_section_guidance('mod_ringfence', profile, detail_level, lang=self._lang) + self._mod_ringfence_html(), '', '') + '\n'),
            'change_impact': (self._section('change_impact', 'rpt_mod_change_impact_title', 'Change Impact',
                          render_section_guidance('mod_change_impact', profile, detail_level, lang=self._lang) + self._mod_change_impact_html(), '', '') + '\n'),
            'findings': (
                '<section id="findings" class="card">'
                f'<h2>{_s("rpt_tr_sec_findings")} ({n_findings})</h2>'
                + self._findings_html() + '</section>\n'),
        }

        body = exec_html + "".join(_sec.get(k, '') for k in self._ordered_section_keys())
        body += f'<footer>{_s("rpt_tr_footer")} &middot; {today_str}</footer>'
```

Keep the surrounding `nav_html` construction (the `_toc_items`/`<aside>` block, current ~593–607) and the final HTML-shell wrapping (the `return` after body) UNCHANGED — they consume `_nav_links` and `body` exactly as before.

NOTE: `profile` local in `_build` still feeds `render_section_guidance`/`visible_in`. Keep `profile = profile or self._profile`. Subclasses set `self._profile` (Task 2) so guidance text stays profile-appropriate.

(g) At the very end of the file, add a back-compat alias:

```python
HtmlExporter = SecurityRiskHtmlExporter   # legacy import name (defaults to security-risk profile)
```

(define after the subclasses from Task 2 exist; if Task 2 is a separate commit, temporarily set `HtmlExporter = _TrafficReportBase` is NOT valid since base is abstract — so implement Task 1 + Task 2 before running the suite.)

- [ ] **Step 4: (defer running until Task 2 adds subclasses)** — proceed to Task 2, then run.

---

## Task 2: Add the two exporter subclasses

**Files:**
- Modify: `src/report/exporters/html_exporter.py`

- [ ] **Step 1: Add subclasses (after `_TrafficReportBase`, before the `HtmlExporter` alias)**

```python
class SecurityRiskHtmlExporter(_TrafficReportBase):
    REPORT_KIND = "SecurityRisk"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("profile", "security_risk")
        super().__init__(*args, **kwargs)

    def _include_maturity(self) -> bool:
        return True

    def _ordered_section_keys(self) -> list[str]:
        return ['summary', 'overview', 'policy', 'uncovered', 'ransomware',
                'user', 'allowed', 'infrastructure', 'lateral', 'readiness', 'findings']


class NetworkInventoryHtmlExporter(_TrafficReportBase):
    REPORT_KIND = "NetworkInventory"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("profile", "network_inventory")
        super().__init__(*args, **kwargs)

    def _include_maturity(self) -> bool:
        return False

    def _ordered_section_keys(self) -> list[str]:
        return ['summary', 'overview', 'policy', 'matrix', 'unmanaged',
                'distribution', 'bandwidth', 'ringfence', 'change_impact']
```

Then set the alias `HtmlExporter = SecurityRiskHtmlExporter`.

NOTE on filename: both subclasses still write `Illumio_Traffic_Report_<KIND>_…` (existing prefix kept so `reports/` history + scheduler prune globs keep matching). The user-facing distinction is `KIND` (SecurityRisk/NetworkInventory). Renaming the prefix to `Illumio_Security_Risk_Report_` is OPTIONAL and deferred (would need scheduler prune-glob updates) — out of scope.

- [ ] **Step 2: Run Task 1 + Task 2 tests**

Run: `python3 -m pytest tests/test_traffic_report_split.py -p no:cacheprovider -q`
Expected: PASS (4 tests: abstract base, security has maturity+readiness+ransomware+findings, inventory omits maturity+readiness but has unmanaged/distribution/overview/policy).

- [ ] **Step 3: Commit**

```bash
git add src/report/exporters/html_exporter.py tests/test_traffic_report_split.py
git commit -m "refactor(report): split traffic exporter into base + security/inventory subclasses"
```

---

## Task 3: Route `ReportGenerator.export()` by exporter class

**Files:**
- Modify: `src/report/report_generator.py` (the `export()` method, ~line 318–360)

- [ ] **Step 1: Inspect current export()**

Run: `sed -n '318,365p' src/report/report_generator.py` — note where it instantiates `HtmlExporter(...)` and passes `profile=traffic_report_profile`.

- [ ] **Step 2: Select exporter class by profile**

Replace the `HtmlExporter(...)` instantiation in `export()` with:

```python
        from src.report.exporters.html_exporter import (
            SecurityRiskHtmlExporter, NetworkInventoryHtmlExporter,
        )
        _ExporterCls = (NetworkInventoryHtmlExporter
                        if traffic_report_profile == "network_inventory"
                        else SecurityRiskHtmlExporter)
        exporter = _ExporterCls(results, data_source=..., detail_level=..., lang=..., ...)
```
(Preserve the existing keyword arguments passed to `HtmlExporter` verbatim; only the class and the now-redundant `profile=` kwarg change — drop `profile=` since the subclass sets it.)

- [ ] **Step 3: Run report-generator tests**

Run: `python3 -m pytest tests/ -k "report_generator or traffic" -p no:cacheprovider -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/report/report_generator.py
git commit -m "refactor(report): ReportGenerator.export selects exporter subclass by profile"
```

---

## Task 4: Facades (SecurityRiskReport / NetworkInventoryReport)

**Files:**
- Create: `src/report/security_risk_report.py`, `src/report/network_inventory_report.py`
- Test: `tests/test_traffic_report_split.py` (append)

- [ ] **Step 1: Write the failing test**

Append:
```python
def test_facades_produce_files(tmp_path, monkeypatch):
    from src.report.security_risk_report import SecurityRiskReport
    from src.report.network_inventory_report import NetworkInventoryReport
    # Both facades wrap a generator that yields canned results (no live PCE).
    import types
    fake_result = types.SimpleNamespace(record_count=1, module_results=_results())
    class _Gen:
        def __init__(self, *a, **k): pass
        def generate_from_api(self, **k): return fake_result
    monkeypatch.setattr("src.report.security_risk_report.ReportGenerator", _Gen)
    monkeypatch.setattr("src.report.network_inventory_report.ReportGenerator", _Gen)
    p1 = SecurityRiskReport(cm=None, api_client=None).run(output_dir=str(tmp_path))
    p2 = NetworkInventoryReport(cm=None, api_client=None).run(output_dir=str(tmp_path))
    assert "SecurityRisk" in p1 and p1.endswith(".html")
    assert "NetworkInventory" in p2 and p2.endswith(".html")
```

- [ ] **Step 2: Run → fail** (`ModuleNotFoundError`).

Run: `python3 -m pytest tests/test_traffic_report_split.py::test_facades_produce_files -p no:cacheprovider -q`

- [ ] **Step 3: Implement facades**

`src/report/security_risk_report.py`:
```python
"""Security & Risk report facade — shared analysis engine + security exporter."""
from __future__ import annotations

from src.report.report_generator import ReportGenerator
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter


class SecurityRiskReport:
    def __init__(self, cm, api_client=None, config_dir: str = "", cache_reader=None):
        self.cm = cm
        self._gen = ReportGenerator(cm, api_client=api_client, config_dir=config_dir,
                                    cache_reader=cache_reader)

    def run(self, output_dir: str = "reports", lang: str = "en") -> str:
        result = self._gen.generate_from_api(traffic_report_profile="security_risk", lang=lang)
        if result.record_count == 0:
            return ""
        return SecurityRiskHtmlExporter(result.module_results, lang=lang).export(output_dir)
```

`src/report/network_inventory_report.py`: identical but `from ... import NetworkInventoryHtmlExporter`, class `NetworkInventoryReport`, `traffic_report_profile="network_inventory"`, exporter `NetworkInventoryHtmlExporter`.

- [ ] **Step 4: Run → PASS.** **Step 5: Commit**

```bash
git add src/report/security_risk_report.py src/report/network_inventory_report.py tests/test_traffic_report_split.py
git commit -m "feat(report): add SecurityRiskReport + NetworkInventoryReport facades"
```

---

## Task 5: CLI verbs (`report security` / `report inventory`) + traffic alias

**Files:**
- Modify: `src/cli/report.py`

- [ ] **Step 1: Add helpers + commands**

After `generate_traffic_report` (line ~99), add `generate_security_report` and `generate_inventory_report` modeled on it but calling the facades (or `generate_traffic_report(traffic_report_profile=...)` directly to reuse the export plumbing). Simplest reuse:
```python
def generate_security_report(**kw):
    return generate_traffic_report(traffic_report_profile="security_risk", **kw)

def generate_inventory_report(**kw):
    return generate_traffic_report(traffic_report_profile="network_inventory", **kw)
```
Add two click commands modeled on `report_traffic` (line ~209) — `report security` and `report inventory` — WITHOUT the `--profile` option (profile is fixed), calling the respective helper. Register `generate-security`/`generate-inventory` aliases like the existing `generate-traffic` (line ~387).

- [ ] **Step 2: Keep `report traffic --profile` as deprecated alias** — leave the existing command, but add a one-line `click.echo("note: 'report traffic --profile' is deprecated; use 'report security' / 'report inventory'", err=True)` at its top.

- [ ] **Step 3: Test**

Append to `tests/test_traffic_report_split.py` a CLI test using the `cli_runner` fixture (from conftest):
```python
def test_cli_has_security_and_inventory_commands(cli_runner):
    from src.cli.root import cli
    out = cli_runner.invoke(cli, ['report', '--help']).output
    assert 'security' in out and 'inventory' in out
```
Run: `python3 -m pytest tests/test_traffic_report_split.py::test_cli_has_security_and_inventory_commands -p no:cacheprovider -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add src/cli/report.py tests/test_traffic_report_split.py
git commit -m "feat(cli): add report security + report inventory verbs (traffic kept as deprecated alias)"
```

---

## Task 6: Scheduler report types + traffic compat

**Files:**
- Modify: `src/report_scheduler.py` (`_generate_report`, ~line 247–262)

- [ ] **Step 1: Add new report_type branches**

In `_generate_report`, before the `report_type == "traffic"` branch, add:
```python
        if report_type in ("security_risk", "network_inventory"):
            profile = report_type
            result = self._gen_traffic(api, start_date, end_date, filters, profile, lang)
            ...export via the matching exporter (reuse the traffic export path with profile=report_type)...
```
Reuse the existing traffic generate+export code path, passing `traffic_report_profile=report_type`. Keep the `report_type == "traffic"` branch (reads the schedule's existing `profile` field) as the long-term compat path.

- [ ] **Step 2: Test** (scheduler dispatch)

Append a test that a schedule with `report_type:"network_inventory"` routes to the inventory exporter (mock the generator to return canned results; assert the produced filename contains `NetworkInventory`). Mirror existing scheduler tests' mocking style.

- [ ] **Step 3: Commit**

```bash
git add src/report_scheduler.py tests/test_traffic_report_split.py
git commit -m "feat(scheduler): support security_risk/network_inventory report types (traffic kept as compat)"
```

---

## Task 7: i18n keys

**Files:**
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

- [ ] **Step 1: Add report-title + CLI-help keys (both files, identical key set)**

en:
```json
  "rpt_security_report_title": "Illumio Security & Risk Report",
  "rpt_inventory_report_title": "Illumio Network & Traffic Inventory Report",
  "cli_report_security_help": "Generate the Security & Risk traffic report.",
  "cli_report_inventory_help": "Generate the Network & Traffic Inventory report.",
```
zh_TW:
```json
  "rpt_security_report_title": "Illumio 資安與風險報表",
  "rpt_inventory_report_title": "Illumio 網路流量盤點報表",
  "cli_report_security_help": "產生資安與風險流量報表。",
  "cli_report_inventory_help": "產生網路流量盤點報表。",
```
Wire these into the CLI command help (Task 5 commands) and any report-title rendering if the kicker text needs to differ per type (otherwise the shared `rpt_tr_title` stays).

- [ ] **Step 2: Verify parity + leakage**

Run: `python3 -m pytest tests/test_report_i18n_leakage.py tests/test_i18n_quality.py::test_zh_tw_json_has_tracked_key_parity_with_en_json -p no:cacheprovider -q`
Expected: PASS (keys present in both; glossary terms — keep "Illumio"/"Network" English per glossary if flagged; adjust values if `test_i18n_glossary` complains).

- [ ] **Step 3: Commit**

```bash
git add src/i18n_en.json src/i18n_zh_TW.json src/cli/report.py
git commit -m "i18n(report): add security/inventory report titles + CLI help"
```

---

## Task 8: Final verification

- [ ] **Step 1: Generate both reports against lab PCE** (manual smoke)

```bash
python3 -c "from src.cli.report import generate_security_report, generate_inventory_report; print(generate_security_report(output_dir='reports/')); print(generate_inventory_report(output_dir='reports/'))"
```
Expected: two HTML paths; open and confirm Security has maturity+readiness+findings, Inventory omits them but has unmanaged/distribution/bandwidth; both have overview+policy.

- [ ] **Step 2: Full suite**

Run: `python3 -m pytest tests/ -p no:cacheprovider -q`  (via `rtk proxy` if needed for clean output)
Expected: green at the established baseline (1579 passed + the new split tests; 5 skipped).

- [ ] **Step 3: Back-compat smoke**

Run: `python3 -c "from src.cli.report import generate_traffic_report; print(generate_traffic_report(traffic_report_profile='network_inventory', output_dir='reports/'))"`
Expected: still works (deprecated alias path), produces a NetworkInventory file.

---

## Notes for the implementer

- **Branch first** (modifies main-tracked files).
- **TDD per task**; commit after each task with **scoped `git add`** (never `git add -A` — it has previously swept untracked spec/plan docs into commits).
- The ONLY content change vs today is dedup: Network Inventory loses the maturity hero (`_include_maturity()=False`) and the readiness section (not in its ordered keys). Verify both are absent in the inventory output and present in security.
- Keep `profile` flowing to `render_section_guidance`/`visible_in` so per-profile guidance text is unchanged.
- `HtmlExporter` alias (= `SecurityRiskHtmlExporter`) preserves any external imports during transition.
