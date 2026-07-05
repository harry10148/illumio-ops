# GUI Report 3-Way Split + Rules→Alert Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the already-3-way report backend in the GUI (ad-hoc cards + scheduler dropdown) and rename the alert-rules tab from "Rules" to "Alerts / 告警", leaving CLI, backend, and the Illumio Rule Scheduler untouched.

**Architecture:** Pure front-end + i18n. The CLI (`report traffic|security|inventory`), scheduler backend (`report_scheduler.py:314-338` dispatches `traffic`/`security_risk`/`network_inventory`), and ad-hoc backend (`/api/reports/generate` accepts all three profiles) already support three reports. This plan (1) replaces the single ad-hoc "Traffic" card with three fixed-profile cards and removes the profile dropdown, (2) adds two scheduler `<option>`s, and (3) renames the `p-rules` tab. Modal type === profile name (`traffic`/`security_risk`/`network_inventory`), so no mapping layer is needed.

**Test runner:** the repo venv lives at `venv/` — invoke tests as `venv/bin/python -m pytest ...` and scripts as `venv/bin/python ...`.

**Tech Stack:** Jinja2 template (`src/templates/index.html`), vanilla JS (`src/static/js/dashboard.js`), JSON i18n (`src/i18n_en.json`, `src/i18n_zh_TW.json`, `src/i18n/data/zh_explicit.json`), pytest, `node --check`.

## Global Constraints

- **i18n three-file rule:** every new/changed `gui_` key must appear in `src/i18n_en.json` AND `src/i18n_zh_TW.json` AND `src/i18n/data/zh_explicit.json`. `gui_` is a strict prefix (`src/i18n/data/strict_prefixes.json`) — a missing key renders `[MISSING:key]` and fails `tests/test_i18n_quality.py`.
- **Glossary rule:** if an EN value contains any of {Block, Blocked, Allow, Allowed, Enforcement, Label, Labels, Managed, Offline, Online, Unmanaged, Service, Workload, Port, Policy}, the zh_TW value MUST keep that term in English (enforced by `tests/test_i18n_quality.py::test_glossary_terms_stay_english_in_zh_tw`). All copy in this plan already complies.
- **Modal type === profile name:** the three report types are the literal strings `traffic`, `security_risk`, `network_inventory` everywhere (card `data-args`, modal `_genReportType`, scheduler `<option value>`), matching backend `report_type` / `traffic_report_profile`.
- **Do NOT touch:** CLI (`src/cli/report.py`), scheduler backend dispatch/generators (`src/report_scheduler.py`), report pipeline, and the Illumio Rule Scheduler tab (`p-rule-scheduler`, all `gui_rs_*` keys).
- **No emoji** anywhere (code, comments, commits). Commit messages: English conventional-commits, ending with the repo's `Co-Authored-By` trailer.
- **`gui_tab_rules` stays** (still used by the in-page sub-tab at `index.html:1235`). The main tab gets a NEW key `gui_tab_alerts`.

---

### Task 1: i18n keys (new keys + changed values)

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`
- Modify: `src/i18n/data/zh_explicit.json`
- Modify: `tests/test_gui_header_chip.py:43-46` (aria expected values change)
- Test: `tests/test_gui_report_split_and_alert_rename.py` (new)

**Interfaces:**
- Produces these i18n keys for later tasks:
  - `gui_tab_alerts` — main-tab label (Task 5)
  - `gui_rcard_security_title`, `gui_rcard_security_desc`, `gui_rcard_inventory_title`, `gui_rcard_inventory_desc` — cards (Task 2)
  - `gui_gen_security_title`, `gui_gen_inventory_title` — modal titles (Task 3)
  - `gui_sched_rt_security`, `gui_sched_rt_inventory` — scheduler options (Task 4)
  - changed: `gui_rules_count` (→ Alerts/告警數), `gui_rcard_traffic_desc` (pure-flow copy), `gui_hdr_chip_aria` (rules→alerts wording)

- [ ] **Step 1: Write the failing test**

Create `tests/test_gui_report_split_and_alert_rename.py`:

```python
"""GUI report 3-way split + Rules→Alert rename: i18n + template contracts."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
ZH = json.loads((ROOT / "src" / "i18n_zh_TW.json").read_text(encoding="utf-8"))
ZH_EXPLICIT = json.loads(
    (ROOT / "src" / "i18n" / "data" / "zh_explicit.json").read_text(encoding="utf-8")
)

NEW_KEYS = [
    "gui_tab_alerts",
    "gui_rcard_security_title", "gui_rcard_security_desc",
    "gui_rcard_inventory_title", "gui_rcard_inventory_desc",
    "gui_gen_security_title", "gui_gen_inventory_title",
    "gui_sched_rt_security", "gui_sched_rt_inventory",
]


def test_new_keys_present_in_all_three_i18n_files():
    for k in NEW_KEYS:
        assert k in EN and EN[k].strip(), f"{k} missing/empty in i18n_en.json"
        assert k in ZH and ZH[k].strip(), f"{k} missing/empty in i18n_zh_TW.json"
        assert k in ZH_EXPLICIT and ZH_EXPLICIT[k].strip(), f"{k} missing in zh_explicit.json"


def test_changed_values_updated():
    assert EN["gui_rules_count"] == "Alerts"
    assert ZH["gui_rules_count"] == "告警數"
    assert ZH_EXPLICIT["gui_rules_count"] == "告警數"
    assert "alerts" in EN["gui_hdr_chip_aria"]
    assert "告警" in ZH["gui_hdr_chip_aria"]
    # traffic card description no longer references the old profile views
    assert "Security Risk" not in EN["gui_rcard_traffic_desc"]
    assert "Network Inventory" not in EN["gui_rcard_traffic_desc"]


def test_tab_alerts_label():
    assert EN["gui_tab_alerts"] == "Alerts"
    assert ZH["gui_tab_alerts"] == "告警"
    # gui_tab_rules unchanged — still used by the in-page sub-tab
    assert EN["gui_tab_rules"] == "Rules"
    assert ZH["gui_tab_rules"] == "規則"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py -q`
Expected: FAIL — KeyError / assert on missing `gui_tab_alerts` etc.
(If the venv path differs, use the repo's usual `pytest` invocation.)

- [ ] **Step 3: Add the new keys and change values in `src/i18n_en.json`**

Add these entries (anywhere in the JSON object) and change the three existing values:

```json
"gui_tab_alerts": "Alerts",
"gui_rcard_security_title": "Security & Risk Report",
"gui_rcard_security_desc": "Security posture, attack surface, and risk findings",
"gui_rcard_inventory_title": "Network Inventory Report",
"gui_rcard_inventory_desc": "Asset and Label governance across your environment",
"gui_gen_security_title": "Generate Security & Risk Report",
"gui_gen_inventory_title": "Generate Network Inventory Report",
"gui_sched_rt_security": "Security & Risk Report",
"gui_sched_rt_inventory": "Network Inventory Report"
```

Change existing:
- `gui_rules_count`: `"Rules"` → `"Alerts"`
- `gui_rcard_traffic_desc`: → `"Pure traffic facts — connections, Ports & Protocols, bandwidth and volume"`
- `gui_hdr_chip_aria`: → `"PCE connection status, {rules} alerts, {schedules} schedules, loaded {loaded}"`

- [ ] **Step 4: Add the same keys with zh values in `src/i18n_zh_TW.json` AND `src/i18n/data/zh_explicit.json`**

Add to BOTH files:

```json
"gui_tab_alerts": "告警",
"gui_rcard_security_title": "資安與風險報表",
"gui_rcard_security_desc": "安全態勢、攻擊面與風險發現",
"gui_rcard_inventory_title": "網路盤點報表",
"gui_rcard_inventory_desc": "環境資產與 Label 治理盤點",
"gui_gen_security_title": "產生資安與風險報表",
"gui_gen_inventory_title": "產生網路盤點報表",
"gui_sched_rt_security": "資安與風險報表",
"gui_sched_rt_inventory": "網路盤點報表"
```

Change existing in BOTH files (`gui_rcard_traffic_desc` is currently absent from zh_explicit — add it there too so the explicit source of truth matches):
- `gui_rules_count`: `"規則數"` → `"告警數"`
- `gui_rcard_traffic_desc`: → `"純流量事實：連線、Ports 與 Protocols、頻寬與傳輸量"`
- `gui_hdr_chip_aria`: → `"PCE 連線狀態，{rules} 條告警，{schedules} 個排程，載入於 {loaded}"`

- [ ] **Step 5: Update the coupled header-chip aria test**

In `tests/test_gui_header_chip.py`, change the `test_chip_aria_label_i18n_key_present` expected values (lines 43-46):

```python
    assert en.get("gui_hdr_chip_aria") == \
        "PCE connection status, {rules} alerts, {schedules} schedules, loaded {loaded}"
    assert zh.get("gui_hdr_chip_aria") == \
        "PCE 連線狀態，{rules} 條告警，{schedules} 個排程，載入於 {loaded}"
```

- [ ] **Step 6: Run the new test + i18n quality gates + precompute dry-run**

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py tests/test_gui_header_chip.py tests/test_i18n_quality.py tests/test_i18n_strings_parity.py -q`
Expected: PASS (parity, glossary, missing-marker gates all green).

Run: `venv/bin/python scripts/precompute_zh_translations.py --dry-run`
Expected: no pending updates for the touched keys and no glossary violations (existing non-empty zh values are skipped; explicit overrides match).

- [ ] **Step 7: Commit**

```bash
git add src/i18n_en.json src/i18n_zh_TW.json src/i18n/data/zh_explicit.json \
        tests/test_gui_header_chip.py tests/test_gui_report_split_and_alert_rename.py
git commit -m "feat(i18n): add report-split card/scheduler keys, rename Rules chip/tab strings to Alerts"
```

---

### Task 2: Ad-hoc report cards — split one Traffic card into three

**Files:**
- Modify: `src/templates/index.html:1334-1346` (the traffic `rcard`)
- Test: `tests/test_gui_report_split_and_alert_rename.py` (extend)

**Interfaces:**
- Consumes: i18n keys `gui_rcard_security_title/desc`, `gui_rcard_inventory_title/desc`, `gui_btn_traffic_report`, `gui_rcard_traffic_desc` (Task 1).
- Produces: three cards whose Generate buttons call `openReportGenModal` with `["traffic"]`, `["security_risk"]`, `["network_inventory"]` — consumed by Task 3's modal.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_report_split_and_alert_rename.py`:

```python
INDEX_HTML = (ROOT / "src" / "templates" / "index.html").read_text(encoding="utf-8")


def test_three_adhoc_report_cards_present():
    for args in ('["traffic"]', '["security_risk"]', '["network_inventory"]'):
        assert f"data-action=\"openReportGenModal\" data-args='{args}'" in INDEX_HTML, \
            f"missing ad-hoc report card button for {args}"


def test_security_and_inventory_cards_use_new_i18n_keys():
    assert "gui_rcard_security_title" in INDEX_HTML
    assert "gui_rcard_inventory_title" in INDEX_HTML
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py -q -k adhoc_report_cards`
Expected: FAIL — only `["traffic"]` card exists.

- [ ] **Step 3: Replace the single traffic card with three cards**

In `src/templates/index.html`, replace the traffic `rcard` block (currently `index.html:1334-1346`, the `<div class="rcard" ...>` … `</div>` that contains `id="btn-gen-report"`) with three sibling cards. Keep the existing `rcard`/`rcard-icon`/`rcard-body` structure:

```html
        <div class="rcard" data-rtype="traffic">
          <div class="rcard-icon"><svg class="icon" aria-hidden="true"><use href="#icon-play"></use></svg></div>
          <div class="rcard-body">
            <h3 data-i18n="gui_btn_traffic_report">Traffic Report</h3>
            <p data-i18n="gui_rcard_traffic_desc">Pure traffic facts — connections, Ports &amp; Protocols, bandwidth and volume</p>
            <div class="rcard-meta"><span class="rcard-meta-last"></span><span class="rcard-meta-sched" style="display:none;"></span></div>
            <div style="display:flex;gap:6px;margin-top:10px;">
              <button class="btn btn-primary btn-sm" id="btn-gen-report" data-action="openReportGenModal" data-args='["traffic"]'>
                <svg class="icon"><use href="#icon-play"></use></svg> <span data-i18n="gui_gen_generate">Generate</span>
              </button>
            </div>
          </div>
        </div>
        <div class="rcard" data-rtype="security_risk">
          <div class="rcard-icon"><svg class="icon" aria-hidden="true"><use href="#icon-shield"></use></svg></div>
          <div class="rcard-body">
            <h3 data-i18n="gui_rcard_security_title">Security &amp; Risk Report</h3>
            <p data-i18n="gui_rcard_security_desc">Security posture, attack surface, and risk findings</p>
            <div class="rcard-meta"><span class="rcard-meta-last"></span><span class="rcard-meta-sched" style="display:none;"></span></div>
            <div style="display:flex;gap:6px;margin-top:10px;">
              <button class="btn btn-primary btn-sm" id="btn-gen-security" data-action="openReportGenModal" data-args='["security_risk"]'>
                <svg class="icon"><use href="#icon-shield"></use></svg> <span data-i18n="gui_gen_generate">Generate</span>
              </button>
            </div>
          </div>
        </div>
        <div class="rcard" data-rtype="network_inventory">
          <div class="rcard-icon"><svg class="icon" aria-hidden="true"><use href="#icon-search"></use></svg></div>
          <div class="rcard-body">
            <h3 data-i18n="gui_rcard_inventory_title">Network Inventory Report</h3>
            <p data-i18n="gui_rcard_inventory_desc">Asset and Label governance across your environment</p>
            <div class="rcard-meta"><span class="rcard-meta-last"></span><span class="rcard-meta-sched" style="display:none;"></span></div>
            <div style="display:flex;gap:6px;margin-top:10px;">
              <button class="btn btn-primary btn-sm" id="btn-gen-inventory" data-action="openReportGenModal" data-args='["network_inventory"]'>
                <svg class="icon"><use href="#icon-search"></use></svg> <span data-i18n="gui_gen_generate">Generate</span>
              </button>
            </div>
          </div>
        </div>
```

- [ ] **Step 4: Run test to verify it passes + spacing lint stays green**

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py tests/test_css_spacing_lint.py -q`
Expected: PASS. (Spacing count goes 191 → 193, well under the 222 threshold — no threshold change needed.)

- [ ] **Step 5: Commit**

```bash
git add src/templates/index.html tests/test_gui_report_split_and_alert_rename.py
git commit -m "feat(gui): split ad-hoc Traffic report card into Traffic/Security/Inventory"
```

---

### Task 3: Report modal — three fixed-profile types, remove profile dropdown

**Files:**
- Modify: `src/static/js/dashboard.js` (meta map ~631; branch logic 644-685; dispatch 742; `_doGenerateTraffic` 920-961; gen typeLabels ~731)
- Modify: `src/templates/index.html:2842-2848` (remove `m-gen-profile-row`)
- Test: `tests/test_gui_report_split_and_alert_rename.py` (extend)

**Interfaces:**
- Consumes: card `data-args` values from Task 2; i18n `gui_gen_security_title`, `gui_gen_inventory_title` from Task 1.
- Produces: module-scope const `TRAFFIC_PROFILE_TYPES = ['traffic','security_risk','network_inventory']` used again by Task 4's scheduler gating.
- The modal posts `traffic_report_profile: _genReportType` to `/api/reports/generate` (backend `_run_adhoc` already validates these three via `_VALID_PROFILES`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_report_split_and_alert_rename.py`:

```python
DASHBOARD_JS = (ROOT / "src" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")


def test_modal_meta_has_three_profile_types():
    assert "security_risk:" in DASHBOARD_JS
    assert "network_inventory:" in DASHBOARD_JS
    assert "gui_gen_security_title" in DASHBOARD_JS
    assert "gui_gen_inventory_title" in DASHBOARD_JS


def test_profile_dropdown_removed():
    assert "m-gen-profile-row" not in INDEX_HTML, "profile dropdown row must be removed"
    assert "m-gen-profile" not in DASHBOARD_JS, "no code should read the removed profile select"


def test_shared_traffic_profile_types_constant():
    assert "TRAFFIC_PROFILE_TYPES" in DASHBOARD_JS
```

Note: `INDEX_HTML`/`DASHBOARD_JS` are read at import time; run this task's test in a fresh process (pytest already does).

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py -q -k "modal_meta or profile_dropdown or traffic_profile_types"`
Expected: FAIL — `m-gen-profile-row` still present, meta lacks the two types.

- [ ] **Step 3: Add the shared constant near the top of `dashboard.js`**

Add once, at module scope (e.g. just before `function openReportGenModal`):

```javascript
// The three traffic-based report profiles share one generation pipeline and
// modal layout; each maps 1:1 to a backend traffic_report_profile / report_type.
const TRAFFIC_PROFILE_TYPES = ['traffic', 'security_risk', 'network_inventory'];
```

- [ ] **Step 4: Add the two meta entries and generalize the branch logic**

In `openReportGenModal`'s `meta` map (currently `dashboard.js:632-639`), add after the `traffic:` line:

```javascript
    security_risk:     { titleKey: 'gui_gen_security_title',   icon: '#icon-shield', dates: true },
    network_inventory: { titleKey: 'gui_gen_inventory_title',  icon: '#icon-search', dates: true },
```

Change the branch condition (currently `if (type === 'traffic') {` at line 644) to:

```javascript
  if (TRAFFIC_PROFILE_TYPES.includes(type)) {
```

Inside that branch, DELETE the two lines that show/reset the profile row:

```javascript
    $('m-gen-profile-row').style.display = '';
```
(line 647) and remove the `$('m-gen-profile-row').style.display = 'none';` lines in the `else if` (line 661) and `else` (line 668) branches.

Change the cache-support check (line 681) from `type === 'traffic'` to:

```javascript
    const supportsCache = (TRAFFIC_PROFILE_TYPES.includes(type) || type === 'app_summary');
```

- [ ] **Step 5: Route dispatch and gen typeLabels for the three types**

Dispatch (currently `dashboard.js:742`): change

```javascript
    if      (_genReportType === 'traffic')      await _doGenerateTraffic();
```
to
```javascript
    if      (TRAFFIC_PROFILE_TYPES.includes(_genReportType)) await _doGenerateTraffic();
```

Gen-progress `typeLabels` (currently `dashboard.js:731-739`, keyed by `_genReportType`): add

```javascript
    security_risk: _t('gui_gen_security_title'),
    network_inventory: _t('gui_gen_inventory_title'),
```

- [ ] **Step 6: Send the fixed profile instead of reading the dropdown**

In `_doGenerateTraffic`, replace the CSV-path read (line ~920-921):

```javascript
      const profileElCsv = document.getElementById('m-gen-profile');
      formData.append('traffic_report_profile', profileElCsv ? profileElCsv.value : 'security_risk');
```
with
```javascript
      formData.append('traffic_report_profile', _genReportType);
```

And the API-path read (line ~954-961): delete `const profileEl = document.getElementById('m-gen-profile');` and change

```javascript
        traffic_report_profile: profileEl ? profileEl.value : 'security_risk',
```
to
```javascript
        traffic_report_profile: _genReportType,
```

- [ ] **Step 7: Remove the profile row from the template**

Delete the `m-gen-profile-row` block in `src/templates/index.html` (currently lines 2842-2848):

```html
      <div id="m-gen-profile-row" style="margin-top:10px; display:none;">
        ... </select>
      </div>
```

- [ ] **Step 8: Syntax-check JS and run tests**

Run: `node --check src/static/js/dashboard.js`
Expected: no output (valid).

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/static/js/dashboard.js src/templates/index.html tests/test_gui_report_split_and_alert_rename.py
git commit -m "feat(gui): fixed-profile report modal for the three report types, drop profile dropdown"
```

---

### Task 4: Scheduler dropdown — add Security & Inventory options

**Files:**
- Modify: `src/templates/index.html:1521-1522` (`sched-report-type` options)
- Modify: `src/static/js/dashboard.js` (schedule-list `typeLabels` ~308; filter gating 372, 409-410, 438)
- Test: `tests/test_gui_report_split_and_alert_rename.py` (extend)

**Interfaces:**
- Consumes: i18n `gui_sched_rt_security`, `gui_sched_rt_inventory` (Task 1); `TRAFFIC_PROFILE_TYPES` (Task 3).
- Produces: scheduler can persist `report_type` of `security_risk` / `network_inventory` — backend `report_scheduler.py:328` already dispatches these.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_report_split_and_alert_rename.py`:

```python
def test_scheduler_has_security_and_inventory_options():
    assert 'value="security_risk"' in INDEX_HTML
    assert 'value="network_inventory"' in INDEX_HTML
    assert "gui_sched_rt_security" in INDEX_HTML
    assert "gui_sched_rt_inventory" in INDEX_HTML


def test_schedule_list_typelabels_cover_new_types():
    # both scheduler typeLabels maps must resolve the new report types
    assert DASHBOARD_JS.count("gui_sched_rt_security") >= 1
    assert DASHBOARD_JS.count("gui_sched_rt_inventory") >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py -q -k "scheduler_has or typelabels_cover"`
Expected: FAIL — options/labels absent.

- [ ] **Step 3: Add the two scheduler `<option>`s**

In `src/templates/index.html`, after the `traffic` option (line 1522), add:

```html
            <option value="security_risk" data-i18n="gui_sched_rt_security">Security &amp; Risk Report</option>
            <option value="network_inventory" data-i18n="gui_sched_rt_inventory">Network Inventory Report</option>
```

- [ ] **Step 4: Add labels to the schedule-list typeLabels map**

In `dashboard.js` (the map at ~308-316, keyed by `s.report_type`), add:

```javascript
    security_risk: _t('gui_sched_rt_security'),
    network_inventory: _t('gui_sched_rt_inventory'),
```

- [ ] **Step 5: Generalize scheduler filter gating to the three types**

Replace the three `=== 'traffic'` scheduler checks with `TRAFFIC_PROFILE_TYPES.includes(...)`:

- Line ~372: `$('sched-filter-section').style.display = TRAFFIC_PROFILE_TYPES.includes(rt) ? '' : 'none';`
- Line ~409-410: `const isTraffic = TRAFFIC_PROFILE_TYPES.includes(rt);`
- Line ~438: `const schedFilters = TRAFFIC_PROFILE_TYPES.includes(reportType) ? _collectSchedFilters() : null;`

(Do not change the `app_summary` branch or any other report type.)

- [ ] **Step 6: Syntax-check and run tests**

Run: `node --check src/static/js/dashboard.js`
Expected: valid.

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/templates/index.html src/static/js/dashboard.js tests/test_gui_report_split_and_alert_rename.py
git commit -m "feat(gui): schedule Security & Risk and Network Inventory reports"
```

---

### Task 5: Rename the alert-rules tab (Rules → Alerts)

**Files:**
- Modify: `src/templates/index.html:187` (main tab `data-i18n`)
- Test: `tests/test_gui_report_split_and_alert_rename.py` (extend)

**Interfaces:**
- Consumes: `gui_tab_alerts` (Task 1).
- The main tab keeps `data-tab="rules"` / `aria-controls="p-rules"` (only the visible LABEL key changes; wiring/ids stay so no JS route breaks). The in-page sub-tab at `index.html:1235` keeps `gui_tab_rules`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui_report_split_and_alert_rename.py`:

```python
import re


def test_main_tab_uses_alerts_key_subtab_keeps_rules():
    # main nav tab button (controls p-rules) now labelled via gui_tab_alerts
    main_tab = re.search(
        r'<button[^>]*aria-controls="p-rules"[^>]*data-i18n="([^"]+)"', INDEX_HTML
    )
    assert main_tab and main_tab.group(1) == "gui_tab_alerts", \
        "main Rules tab should use gui_tab_alerts"
    # in-page sub-tab button still uses gui_tab_rules
    assert 'id="rules-tab-rules" data-i18n="gui_tab_rules"' in INDEX_HTML
    # tab wiring unchanged
    assert 'data-tab="rules"' in INDEX_HTML
    assert 'aria-controls="p-rules"' in INDEX_HTML
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py -q -k main_tab_uses_alerts`
Expected: FAIL — main tab still `data-i18n="gui_tab_rules"`.

- [ ] **Step 3: Change the main tab label key**

In `src/templates/index.html:187`, change only the `data-i18n` attribute on the main nav tab button (the one with `aria-controls="p-rules"` / `data-tab="rules"`) from `data-i18n="gui_tab_rules"` to `data-i18n="gui_tab_alerts"`, and update the visible fallback text `Rules` → `Alerts` on line 190. Leave `data-tab`, `aria-controls`, `data-args`, and the icon unchanged.

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_gui_report_split_and_alert_rename.py tests/test_gui_header_chip.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templates/index.html tests/test_gui_report_split_and_alert_rename.py
git commit -m "feat(gui): rename alert-rules tab from Rules to Alerts"
```

---

### Task 6: End-to-end verification (full suite + real report output)

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `venv/bin/python -m pytest -q`
Expected: all green (baseline was ~2533 passing; no regressions).

- [ ] **Step 2: JS syntax final check**

Run: `node --check src/static/js/dashboard.js`
Expected: valid.

- [ ] **Step 3: Generate all three reports from the CLI on real/sample data**

Run each and confirm distinct output files are produced:
```bash
venv/bin/python -m src.cli report traffic   --source api --format html --output-dir /tmp/rpt_verify
venv/bin/python -m src.cli report security  --source api --format html --output-dir /tmp/rpt_verify
venv/bin/python -m src.cli report inventory --source api --format html --output-dir /tmp/rpt_verify
```
(If no live PCE, use `--source csv --file <sample>` with a sample export. Adjust the module invocation to the repo's actual CLI entrypoint if different.)

- [ ] **Step 4: Per-project report inspection (CLAUDE.md rule)**

Open the three generated HTML reports and page through them. Confirm the Traffic report is pure-flow (no maturity/attack content), Security and Inventory render their sections, and — per `CLAUDE.md` — no field is silently truncated or overflowing. Record the check result (files inspected, pass/fail per report) in the completion report.

- [ ] **Step 5: GUI smoke (optional if a GUI is running)**

Launch the GUI, open the Reports tab: confirm three report cards, each opens a modal with no profile dropdown and the correct title; confirm the scheduler dropdown lists Security & Risk and Network Inventory; confirm the main nav tab reads "Alerts / 告警" while its sub-tab still reads "Rules / 規則". Confirm the Rule Scheduler tab is unchanged.

- [ ] **Step 6: Final commit (if any verification tweak was needed)**

Only if Steps 1-5 surfaced a fix. Otherwise nothing to commit.

---

## Self-Review

**Spec coverage:**
- Spec A1 (three cards) → Task 2. A2 (modal +2 types, drop dropdown, fixed profile, dispatch, gen typeLabels) → Task 3. A3 (scheduler options, list typeLabels, filter gating) → Task 4. A4 (i18n new/changed keys) → Task 1. B (main tab new key, chip value, aria) → Task 1 (values) + Task 5 (tab); sub-tab & Rule Scheduler explicitly untouched. Verification/CLAUDE.md report inspection → Task 6. No spec section is unmapped.
- Spec "不做" items (CLI, backend dispatch, Rule Scheduler, overview alert tile) are covered by the Global Constraints "Do NOT touch" list and are not modified by any task.

**Placeholder scan:** No TBD/TODO; every code/edit step shows exact content, file, and command. Line numbers are given as "currently N" because prior tasks shift them.

**Type/name consistency:** `TRAFFIC_PROFILE_TYPES` defined in Task 3 Step 3, consumed in Task 3 (dispatch/branch) and Task 4 (gating). The three literals `traffic`/`security_risk`/`network_inventory` are used identically in card `data-args`, modal meta, `_genReportType`, scheduler `<option value>`, and typeLabels. i18n key names match between Task 1 (definition) and Tasks 2-5 (use). `gui_tab_rules` preserved for the sub-tab; `gui_tab_alerts` is the only main-tab change.

**Note on line numbers:** Tasks 2-5 edit `index.html`/`dashboard.js` sequentially; absolute line numbers drift as edits land. Anchor by the quoted surrounding code / element ids, not by line number alone.
