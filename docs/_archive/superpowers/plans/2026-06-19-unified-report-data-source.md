# Unified Report Data-Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inconsistent per-surface cache controls (CLI `--cache/--no-cache`, GUI cache dropdown + clip-to-cache checkbox, shell nothing) with one 3-mode `data_source` selector (hybrid / live / cache-only) used identically across CLI, interactive shell, and Web GUI for cache-capable report types, with a safeguard when the cache is unavailable.

**Architecture:** Two pure, unit-testable helpers in a new `src/report/cache_support.py` become the single source of truth: `resolve_data_source()` maps a `data_source` string → the existing `(use_cache, clip_to_cache)` backend flags plus an optional warning; `cache_available()` decides whether cache modes are offerable. Each surface (CLI/GUI/shell) calls these instead of rolling its own logic. The backend fetch algorithm (`ReportGenerator.generate_from_api`) is unchanged.

**Tech Stack:** Python 3.12, Click (CLI), Flask (GUI routes), vanilla JS (GUI frontend), pytest.

## Global Constraints

- Cache-capable report types = **traffic** (security_risk/network_inventory) and **app-summary** only. All other types show no data-source control and are always live.
- The three modes map to the EXISTING backend flags exactly: `hybrid`→`(use_cache=True, clip_to_cache=False)`; `live`→`(use_cache=False, clip_to_cache=False)`; `cache-only`→`(use_cache=True, clip_to_cache=True)`. Do NOT change `ReportGenerator`'s fetch logic.
- Back-compat: CLI `--no-cache` still works as an alias for `--data-source live`; `--cache` aliases `hybrid`. Emit a one-line deprecation note when the old flags are used.
- 防呆: when cache is unavailable, GUI/shell hide cache modes (offer only Live); CLI accepts the flag but prints a clear warning and falls back to live. Never silently degrade.
- i18n: any new user-visible string in GUI/shell must use i18n keys (en + zh_TW), per project AGENTS.md.
- Default mode = `hybrid`.

---

### Task 1: `resolve_data_source` pure function

**Files:**
- Create: `src/report/cache_support.py`
- Test: `tests/test_cache_support.py`

**Interfaces:**
- Produces: `resolve_data_source(value: str | None, cache_ok: bool) -> tuple[bool, bool, str | None]` returning `(use_cache, clip_to_cache, warning)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cache_support.py
from src.report.cache_support import resolve_data_source

def test_modes_when_cache_available():
    assert resolve_data_source("hybrid", True) == (True, False, None)
    assert resolve_data_source("live", True) == (False, False, None)
    assert resolve_data_source("cache-only", True) == (True, True, None)

def test_default_and_aliases():
    assert resolve_data_source(None, True) == (True, False, None)      # default hybrid
    assert resolve_data_source("", True) == (True, False, None)
    assert resolve_data_source("cache", True) == (True, False, None)   # alias -> hybrid
    assert resolve_data_source("no-cache", True) == (False, False, None)  # alias -> live
    assert resolve_data_source("api", True) == (False, False, None)    # alias -> live

def test_cache_unavailable_falls_back_with_warning():
    uc, clip, warn = resolve_data_source("hybrid", False)
    assert (uc, clip) == (False, False) and warn and "live" in warn.lower()
    uc, clip, warn = resolve_data_source("cache-only", False)
    assert (uc, clip) == (False, False) and warn and "cache-only" in warn.lower()
    # live never warns
    assert resolve_data_source("live", False) == (False, False, None)

def test_unknown_value_defaults_hybrid():
    assert resolve_data_source("bogus", True) == (True, False, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/test_cache_support.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.cache_support'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/report/cache_support.py
"""Single source of truth for the report data-source choice.

The traffic/app-summary backend is driven by two booleans (use_cache,
clip_to_cache). The UI exposes ONE 3-mode choice; this module maps between them
and enforces the cache-unavailable safeguard, so CLI/GUI/shell stay consistent.
"""
from __future__ import annotations

_ALIASES = {"cache": "hybrid", "no-cache": "live", "api": "live"}
_VALID = ("hybrid", "live", "cache-only")


def resolve_data_source(value: str | None, cache_ok: bool) -> tuple[bool, bool, str | None]:
    """Map a data_source choice to (use_cache, clip_to_cache, warning).

    value: 'hybrid' | 'live' | 'cache-only' (None/'' -> 'hybrid'); aliases
    'cache'->hybrid, 'no-cache'/'api'->live are accepted for back-compat.
    cache_ok: whether the PCE cache is available (see cache_available()).
    When a cache mode is requested while cache_ok is False, returns the live
    mapping plus a human-readable warning so the caller can warn + fall back.
    """
    mode = (value or "hybrid").strip().lower()
    mode = _ALIASES.get(mode, mode)
    if mode not in _VALID:
        mode = "hybrid"
    if mode == "live":
        return (False, False, None)
    if not cache_ok:
        if mode == "cache-only":
            return (False, False,
                    "'cache-only' requested but the PCE cache is unavailable; "
                    "falling back to a FULL live PCE query (slower).")
        return (False, False,
                f"'{mode}' requested but the PCE cache is unavailable; "
                "generating from live PCE instead.")
    if mode == "hybrid":
        return (True, False, None)
    return (True, True, None)  # cache-only
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/test_cache_support.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/report/cache_support.py tests/test_cache_support.py
git commit -m "feat(report): resolve_data_source — 3-mode data-source → backend flags"
```

---

### Task 2: `cache_available(cm)` helper

**Files:**
- Modify: `src/report/cache_support.py`
- Test: `tests/test_cache_support.py`

**Interfaces:**
- Consumes: `cm.models.pce_cache.enabled` (bool); `src.main._make_cache_reader(cm)` (returns a CacheReader or None); `reader.earliest_data_timestamp("traffic")`.
- Produces: `cache_available(cm) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_cache_support.py
from types import SimpleNamespace
from unittest.mock import patch
from src.report.cache_support import cache_available

def _cm(enabled):
    return SimpleNamespace(models=SimpleNamespace(pce_cache=SimpleNamespace(enabled=enabled)))

def test_cache_unavailable_when_disabled():
    assert cache_available(_cm(False)) is False

def test_cache_unavailable_when_reader_none():
    with patch("src.main._make_cache_reader", return_value=None):
        assert cache_available(_cm(True)) is False

def test_cache_unavailable_when_empty():
    reader = SimpleNamespace(earliest_data_timestamp=lambda src: None)
    with patch("src.main._make_cache_reader", return_value=reader):
        assert cache_available(_cm(True)) is False

def test_cache_available_when_has_data():
    reader = SimpleNamespace(earliest_data_timestamp=lambda src: "2026-06-01T00:00:00Z")
    with patch("src.main._make_cache_reader", return_value=reader):
        assert cache_available(_cm(True)) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/test_cache_support.py -q -k cache_`
Expected: FAIL with `ImportError: cannot import name 'cache_available'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/report/cache_support.py
def cache_available(cm) -> bool:
    """True iff pce_cache is enabled, reachable, and holds traffic data.

    Lazy-imports _make_cache_reader to avoid a circular import with src.main.
    Any failure (disabled, unreachable db, empty cache) returns False.
    """
    try:
        if not cm.models.pce_cache.enabled:
            return False
        from src.main import _make_cache_reader
        reader = _make_cache_reader(cm)
        if reader is None:
            return False
        return reader.earliest_data_timestamp("traffic") is not None
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/test_cache_support.py -q`
Expected: PASS (8 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/report/cache_support.py tests/test_cache_support.py
git commit -m "feat(report): cache_available — gate cache modes on enabled+populated cache"
```

---

### Task 3: CLI — `--data-source` on traffic + app-summary

**Files:**
- Modify: `src/cli/report.py` (traffic ~223-367, app-summary ~567-603)
- Test: `tests/test_cli_report_data_source.py`

**Interfaces:**
- Consumes: `resolve_data_source`, `cache_available` from `src.report.cache_support`.
- Behavior: add `--data-source [hybrid|live|cache-only]` (default `hybrid`). Keep `--cache/--no-cache` flags but map them (`--no-cache`→live, `--cache`→hybrid) and print a deprecation note when used. Pass resolved `(use_cache, clip_to_cache)` to the generator. When `resolve_data_source` returns a warning, print it to stderr.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_report_data_source.py
from click.testing import CliRunner
from unittest.mock import patch
from src.cli.root import cli

def _run(args):
    # capture the (use_cache, clip_to_cache) the command would pass to the generator
    captured = {}
    def fake_generate_from_api(self, *a, **k):
        captured["use_cache"] = k.get("use_cache")
        captured["clip_to_cache"] = k.get("clip_to_cache")
        raise SystemExit(0)  # stop before real work
    with patch("src.report.report_generator.ReportGenerator.generate_from_api",
               fake_generate_from_api), \
         patch("src.report.cache_support.cache_available", return_value=True):
        CliRunner().invoke(cli, args, catch_exceptions=True)
    return captured

def test_cli_data_source_live():
    assert _run(["report", "traffic", "--data-source", "live"])["use_cache"] is False

def test_cli_data_source_cache_only():
    c = _run(["report", "traffic", "--data-source", "cache-only"])
    assert (c["use_cache"], c["clip_to_cache"]) == (True, True)

def test_cli_no_cache_alias_still_works():
    assert _run(["report", "traffic", "--no-cache"])["use_cache"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/test_cli_report_data_source.py -q`
Expected: FAIL (`--data-source` is not a known option / KeyError)

- [ ] **Step 3: Write minimal implementation**

In `src/cli/report.py`, for the `traffic` command (and its `security`/`inventory` aliases) and `app-summary`:
- Add the option above the handler: `@click.option("--data-source", type=click.Choice(["hybrid", "live", "cache-only"]), default=None, help="Where report data comes from: hybrid (cache + live gap-fill, default), live (PCE only), cache-only (fastest, cached range).")`
- Keep existing `--cache/--no-cache` as `@click.option("--cache/--no-cache", "legacy_cache", default=None, help="(deprecated) use --data-source")`.
- In the handler, before calling the generator:

```python
from src.report.cache_support import resolve_data_source, cache_available
# legacy_cache: True -> 'cache'(hybrid alias), False -> 'no-cache'(live alias)
ds = data_source
if ds is None and legacy_cache is not None:
    ds = "cache" if legacy_cache else "no-cache"
    click.echo("note: --cache/--no-cache is deprecated; use --data-source", err=True)
use_cache, clip_to_cache, warn = resolve_data_source(ds, cache_available(cm))
if warn:
    click.echo(f"warning: {warn}", err=True)
```
- Pass `use_cache=use_cache, clip_to_cache=clip_to_cache` to `generate_from_api(...)` (replace the previous `use_cache=...` argument).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/test_cli_report_data_source.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Regression — existing report CLI tests still pass**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/ -q -k "report" --ignore=tests/test_e2e_report_html_redesign.py --ignore=tests/test_report_cover_page.py --ignore=tests/test_report_no_kpi_duplication.py`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add src/cli/report.py tests/test_cli_report_data_source.py
git commit -m "feat(cli): --data-source (hybrid/live/cache-only) for traffic + app-summary"
```

---

### Task 4: GUI route — accept `data_source`, map + safeguard

**Files:**
- Modify: `src/gui/routes/reports.py` (`/api/reports/generate` ~271-365; `/api/app_report/generate` ~518-574)
- Test: `tests/test_gui_report_data_source.py`

**Interfaces:**
- Consumes: `resolve_data_source`, `cache_available`. Request JSON now carries `data_source` (string). Back-compat: if absent, derive from legacy `use_cache` (bool) / `clip_to_cache` (bool) fields.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gui_report_data_source.py
from src.report.cache_support import resolve_data_source

# Route-level mapping is delegated to resolve_data_source; assert the route
# helper picks the right (use_cache, clip_to_cache). The route exposes a small
# pure helper _data_source_from_payload(payload, cache_ok) for testability.
from src.gui.routes.reports import _data_source_from_payload

def test_payload_explicit_data_source():
    assert _data_source_from_payload({"data_source": "cache-only"}, True)[:2] == (True, True)

def test_payload_legacy_use_cache_false():
    # old GUI clients sent use_cache=false meaning live
    assert _data_source_from_payload({"use_cache": False}, True)[:2] == (False, False)

def test_payload_default_hybrid():
    assert _data_source_from_payload({}, True)[:2] == (True, False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/test_gui_report_data_source.py -q`
Expected: FAIL (`cannot import name '_data_source_from_payload'`)

- [ ] **Step 3: Write minimal implementation**

In `src/gui/routes/reports.py` add a module-level helper and use it in both routes:

```python
from src.report.cache_support import resolve_data_source

def _data_source_from_payload(payload: dict, cache_ok: bool) -> tuple[bool, bool, str | None]:
    """Resolve (use_cache, clip_to_cache, warning) from a report request payload.
    Prefers explicit 'data_source'; falls back to legacy use_cache/clip_to_cache."""
    ds = payload.get("data_source")
    if ds is None:
        if payload.get("use_cache") is False:
            ds = "live"
        elif payload.get("clip_to_cache") is True:
            ds = "cache-only"
        else:
            ds = "hybrid"
    return resolve_data_source(ds, cache_ok)
```

In each generate route, replace the previous `use_cache`/`clip_to_cache` parsing with:

```python
from src.report.cache_support import cache_available
use_cache, clip_to_cache, warn = _data_source_from_payload(payload, cache_available(cm))
if warn:
    logger.warning("Report data-source fallback: {}", warn)
```
Pass `use_cache`/`clip_to_cache` into the generator call as before.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. venv/bin/python -m pytest tests/test_gui_report_data_source.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gui/routes/reports.py tests/test_gui_report_data_source.py
git commit -m "feat(gui): report routes accept data_source with cache-unavailable fallback"
```

---

### Task 5: GUI frontend — single Data source dropdown

**Files:**
- Modify: `src/templates/index.html` (report modal ~2864-3019: remove `m-gen-cache-mode` + `m-gen-clip-to-cache`, add `m-gen-data-source`)
- Modify: `src/static/js/dashboard.js` (visibility ~701-707; traffic extraction ~1023-1024; app_summary ~1170-1171)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json` (option labels)

**Interfaces:**
- Consumes: a `cacheAvailable` boolean exposed to the page (Task 8). Sends `data_source` in the generate POST.

- [ ] **Step 1: Replace the modal control**

In `index.html`, replace the cache dropdown row and the clip-to-cache checkbox with one select:

```html
<div class="form-row" id="m-gen-data-source-row" style="display:none;">
  <label data-i18n="gui_rpt_data_source">Data source</label>
  <select id="m-gen-data-source">
    <option value="hybrid"     data-i18n="gui_rpt_ds_hybrid">Cache + live gap-fill (recommended)</option>
    <option value="live"       data-i18n="gui_rpt_ds_live">Live PCE only (freshest, slower)</option>
    <option value="cache-only" data-i18n="gui_rpt_ds_cache_only">Cache only (fastest, cached range)</option>
  </select>
</div>
```

- [ ] **Step 2: Update visibility + extraction in dashboard.js**

Replace the cache-row visibility block (~701-707) so the data-source row shows only for cache-capable types AND when cache is available:

```javascript
const dsRow = document.getElementById('m-gen-data-source-row');
if (dsRow) {
  const supportsCache = (type === 'traffic' || type === 'app_summary');
  dsRow.style.display = (supportsCache && window._CACHE_AVAILABLE) ? '' : 'none';
  const sel = document.getElementById('m-gen-data-source');
  if (sel) sel.value = 'hybrid';
}
```

Replace the traffic use_cache extraction (~1023-1024) and the app_summary one (~1170-1171) with:

```javascript
const dsEl = document.getElementById('m-gen-data-source');
const dataSource = (window._CACHE_AVAILABLE && dsEl) ? dsEl.value : 'live';
// include in the POST body:  data_source: dataSource
// (remove the old use_cache / clip_to_cache fields from the body)
```

- [ ] **Step 3: Add i18n keys (en + zh_TW)**

Add to both files: `gui_rpt_data_source`, `gui_rpt_ds_hybrid`, `gui_rpt_ds_live`, `gui_rpt_ds_cache_only` (English values above; zh_TW: "資料來源", "快取＋即時補抓（建議）", "純 Live PCE（最新、較慢）", "僅快取（最快、限快取範圍）").

- [ ] **Step 4: Verify JSON + JS syntax**

Run: `node --check src/static/js/dashboard.js && PYTHONPATH=. venv/bin/python -c "import json; json.load(open('src/i18n_en.json')); json.load(open('src/i18n_zh_TW.json')); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Manual GUI check (documented, not automated)**

Launch GUI, open report modal for traffic with cache available → the single "Data source" dropdown shows 3 options; for audit/ven/policy-usage the row is hidden; with cache disabled the row is hidden for all. (E2E is gated behind ILLUMIO_OPS_E2E_BASE_URL; note this as the manual gate.)

- [ ] **Step 6: Commit**

```bash
git add src/templates/index.html src/static/js/dashboard.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(gui): single Data source dropdown replacing cache dropdown + clip checkbox"
```

---

### Task 6: Expose `cacheAvailable` to the GUI page

**Files:**
- Modify: `src/gui/routes/auth.py` (`index()` ~34-57, the render_template call)
- Modify: `src/templates/index.html` (the bootstrap `<script>` ~14-22 that sets `window._INIT_*`)

**Interfaces:**
- Produces: `window._CACHE_AVAILABLE` (bool) consumed by Task 5.

- [ ] **Step 1: Compute and inject the flag**

In `index()` add `from src.report.cache_support import cache_available` and pass `cache_available=cache_available(cm)` to `render_template("index.html", ...)`.

- [ ] **Step 2: Set the JS global in the template**

In the bootstrap script block, add:
```html
<script nonce="{{ csp_nonce() }}">window._CACHE_AVAILABLE = {{ 'true' if cache_available else 'false' }};</script>
```

- [ ] **Step 3: Verify it renders**

Run (smoke): `PYTHONPATH=. venv/bin/python -c "from src.gui.routes.auth import make_auth_blueprint" 2>/dev/null; echo import-ok` and confirm template has the global. (Live render verified manually in Task 5 Step 5.)

- [ ] **Step 4: Commit**

```bash
git add src/gui/routes/auth.py src/templates/index.html
git commit -m "feat(gui): expose cacheAvailable to report modal for data-source gating"
```

---

### Task 7: Interactive shell — data-source prompt + option alignment

**Files:**
- Modify: the shell traffic generate flow + `src/cli/menus/report_schedule.py` (traffic branch)
- Modify: `src/i18n_en.json`, `src/i18n_zh_TW.json`

**Interfaces:**
- Consumes: `resolve_data_source`, `cache_available`. Adds a Data source prompt (only when `cache_available(cm)`), plus `profile` and `source` prompts for traffic to match CLI/GUI.

- [ ] **Step 1: Add the data-source prompt helper call**

In the shell traffic generate path, when `cache_available(cm)` is True, prompt:
```python
from src.report.cache_support import resolve_data_source, cache_available
ds = "hybrid"
if cache_available(cm):
    # safe_input int 1..3 -> hybrid/live/cache-only
    sel = safe_input(t("rpt_ds_prompt"), int, range(1, 4), allow_cancel=True) or 1
    ds = {1: "hybrid", 2: "live", 3: "cache-only"}[sel]
use_cache, clip_to_cache, warn = resolve_data_source(ds, cache_available(cm))
if warn:
    print(warn)
```
Pass `use_cache`/`clip_to_cache` into the generator call.

- [ ] **Step 2: Add traffic profile + source prompts (option alignment)**

In the same flow add a `profile` prompt (1=security_risk, 2=network_inventory) and a `source` prompt (1=api, 2=csv) mirroring the CLI choices, defaulting to security_risk / api.

- [ ] **Step 3: Add i18n keys**

Add `rpt_ds_prompt`, `rpt_profile_prompt`, `rpt_source_prompt` (en + zh_TW).

- [ ] **Step 4: Drive-test the prompt renders**

Run: `printf '2\n1\n-1\n0\n0\n' | PYTHONPATH=. timeout 25 venv/bin/python illumio-ops.py shell 2>&1 | sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g' | grep -iE "data source|資料來源|profile|source"`
Expected: the new prompts appear when launching traffic report generation (cache available).

- [ ] **Step 5: Commit**

```bash
git add src/cli/menus/ src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(shell): data-source + profile + source prompts for traffic report"
```

---

### Task 8: GUI policy-usage — add `source` toggle (option alignment)

> **DONE (2026-06-20).** Initially deferred because the GUI policy-usage route
> (`api_generate_policy_usage_report`) was API-only, so a source toggle needed new
> CSV-upload capability rather than just exposing a hidden option. On user request
> this was implemented: the route now accepts multipart `source=csv` + file upload
> (→ `PolicyUsageGenerator.generate_from_csv`), and the modal shows the api/csv
> source toggle for policy_usage (`toggleTrafficSource` made type-aware so the
> cache-mode row only shows for cache-capable types). Verified by py_compile +
> JS syntax + GUI route tests; deployed to 10.10.48.147.


**Files:**
- Modify: `src/templates/index.html` (policy-usage form fields)
- Modify: `src/static/js/dashboard.js` (`_doGeneratePolicyUsageClean` ~1223-1260)
- (Route `/api/policy_usage_report/generate` already accepts `source`.)

**Interfaces:**
- Sends `source` (api|csv) in the policy-usage POST, matching the CLI `--source`.

- [ ] **Step 1: Add the source control to the policy-usage form**

Add a source radio/select (api/csv) to the policy-usage section, mirroring traffic's source control markup, with i18n labels (reuse existing `gui_*source*` keys if present).

- [ ] **Step 2: Send it in the POST**

In `_doGeneratePolicyUsageClean`, read the selected source and include `source: <value>` in the request body.

- [ ] **Step 3: Verify JS syntax**

Run: `node --check src/static/js/dashboard.js`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/templates/index.html src/static/js/dashboard.js
git commit -m "feat(gui): expose source (api/csv) for policy-usage report (align with CLI)"
```

---

## Self-Review

- **Spec coverage:** 3-mode model → Tasks 1,3,4,5,7. 防呆 (`cache_available` + hide/warn) → Tasks 2,3,4,5,6,7. CLI back-compat `--no-cache` → Task 3. GUI single control → Tasks 5,6. shell data-source + profile/source alignment → Task 7. GUI policy-usage source alignment → Task 8. All spec sections mapped.
- **Out-of-scope honored:** no new cache backends; no new report types added to any surface; fetch algorithm untouched.
- **Type consistency:** `resolve_data_source(value, cache_ok) -> (use_cache, clip_to_cache, warning)` and `cache_available(cm) -> bool` used identically in Tasks 3/4/7; route helper `_data_source_from_payload(payload, cache_ok) -> (use_cache, clip_to_cache, warning)`.
- **Note:** Tasks 5/6/8 (frontend) have a documented manual GUI gate because automated E2E requires `ILLUMIO_OPS_E2E_BASE_URL`; logic-bearing pieces (Tasks 1–4,7) are unit-tested.
