# H6 — `src/settings.py` Rename + Reorg Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break `src/settings.py` (2218 lines — a grab-bag of CLI wizard functions and event
catalog data) into focused modules under `src/cli/menus/` and `src/events/catalog.py`. Every
existing importer continues to work unchanged via re-export shims until a future PR migrates
them (migration is OUT OF SCOPE here).

**Architecture:** Replace the monolithic `src/settings.py` with:

```
src/
├── cli/
│   └── menus/                   ← NEW directory; wizards only
│       ├── __init__.py          # backwards-compat re-exports of all wizard functions
│       ├── _helpers.py          # shared: _wizard_step, _wizard_confirm, _menu_hints,
│       │                        #         _tz_offset_info, _utc_to_local_hour,
│       │                        #         _local_to_utc_hour, _empty_uses_default
│       ├── event.py             # add_event_menu + event-local helpers
│       ├── system_health.py     # add_system_health_menu
│       ├── traffic.py           # add_traffic_menu
│       ├── bandwidth.py         # add_bandwidth_volume_menu
│       ├── manage_rules.py      # manage_rules_menu + _parse_manage_rules_command
│       ├── alert.py             # alert_settings_menu
│       ├── web_gui.py           # web_gui_security_menu + _web_gui_tls_menu + _clear_screen
│       ├── report_schedule.py   # manage_report_schedules_menu + _add_report_schedule_wizard
│       └── _root.py             # settings_menu (the top-level wizard)
└── events/
    └── catalog.py               ← EXTENDED (wizard catalog data added here)
        # New exports: FULL_EVENT_CATALOG, ACTION_EVENTS, SEVERITY_FILTER_EVENTS,
        # DISCOVERY_EVENTS, EVENT_DESCRIPTION_KEYS, EVENT_TIPS_KEYS,
        # _event_category, _humanize_event_id, _event_translation_key,
        # plus all the builder internals.

src/settings.py                  ← THIN RE-EXPORT SHIM (replaces 2218-line file)
```

`src/settings.py` becomes a ~40-line shim that re-exports every public symbol so the six
existing importers (`src/main.py`, `src/gui/__init__.py`, `tests/test_manage_rules_menu.py`,
`tests/test_wizard_default_enter.py`, `tests/test_event_core.py`,
`scripts/generate_alert_mail_samples.py`) keep working without changes.

**Tech Stack:** Python 3.12. Test runner: `venv/bin/python3 -m pytest`. mypy:
`venv/bin/python3 -m mypy --config-file mypy.ini`.

---

## Scope Note

This plan is one of three Batch 4 sub-plans (see
`docs/superpowers/plans/2026-05-01-code-review-fixes.md` Batch 4 sketch). H4
(`src/i18n.py` data extraction) and H5 (`src/gui/__init__.py` Blueprint split) are
separate plans. This plan touches `src/settings.py` and the files listed above only.

**Importers of `src.settings` — complete list as verified by grep:**

| File | Symbols imported |
|------|-----------------|
| `src/main.py:10` | `settings_menu`, `add_event_menu`, `add_system_health_menu`, `add_traffic_menu`, `add_bandwidth_volume_menu`, `manage_rules_menu`, `manage_report_schedules_menu` |
| `src/gui/__init__.py:1000` | `_event_category` (lazy import inside a function) |
| `src/gui/__init__.py:1276` | `FULL_EVENT_CATALOG`, `ACTION_EVENTS`, `SEVERITY_FILTER_EVENTS`, `EVENT_DESCRIPTION_KEYS`, `EVENT_TIPS_KEYS` (lazy import inside a function) |
| `tests/test_manage_rules_menu.py:8` | `from src import settings as settings_module` — then calls `settings_module.manage_rules_menu`, `settings_module.add_event_menu`, etc. and patches `settings_module.os` |
| `tests/test_wizard_default_enter.py:8` | `from src import settings as settings_module` — then calls `settings_module.add_traffic_menu`, `settings_module.add_bandwidth_volume_menu`, patches `settings_module.os` and `settings_module.get_last_input_action` |
| `tests/test_event_core.py:10` | `from src.settings import FULL_EVENT_CATALOG` |
| `scripts/generate_alert_mail_samples.py` | `from src.settings import FULL_EVENT_CATALOG` |

All seven importers will keep working because `src/settings.py` is converted to a re-export
shim that forwards every symbol. The shim also re-exports `os` and `get_last_input_action` at
module level so `settings_module.os` and `settings_module.get_last_input_action` patches in
tests continue to work — see Task 2 for details on this test-patch preservation strategy.

---

## Key Insight: `src/events/catalog.py` Already Exists

`src/events/catalog.py` currently contains only `KNOWN_EVENT_TYPES`, `LOCAL_EXTENSION_EVENT_TYPES`,
and `is_known_event_type()`. The `FULL_EVENT_CATALOG` that `src/settings.py` builds is a
*separate*, higher-level structure (categorised buckets of event IDs for UI rendering) derived
FROM `KNOWN_EVENT_TYPES`. There is no overlap — the two serve different roles:

- `src/events/catalog.py` → raw set of known PCE event type strings (operational)
- `FULL_EVENT_CATALOG` → UI-facing categorised catalog for wizard menus (presentational)

**Decision:** Extend `src/events/catalog.py` with all the wizard-catalog symbols. This keeps
event-related data in one file, avoids a new `src/events/wizard_catalog.py` file, and matches
the sketch in the parent plan ("Move `FULL_EVENT_CATALOG` to `src/events/catalog.py`").

---

## Risk Analysis

### Risk 1: Module-load-time initialization order

`src/settings.py` computes four constants at import time in a specific order:

```
Lines 10–54:   FULL_EVENT_CATALOG (initial stub dict — only used by lines 162–171 below)
Lines 162–171: _LEGACY_EVENT_CATALOG, _EVENT_CATEGORY_OVERRIDES, _EVENT_DESCRIPTION_OVERRIDES
               (built from the stub; used later by _event_category())
Lines 337–345: _build_full_event_catalog() definition (reads KNOWN_EVENT_TYPES)
Line 347:      FULL_EVENT_CATALOG = _build_full_event_catalog()   ← FINAL, overwrites stub
Lines 348–350: ACTION_EVENTS, SEVERITY_FILTER_EVENTS, DISCOVERY_EVENTS   ← FINAL
Lines 352–414: EVENT_DESCRIPTION_KEYS, EVENT_TIPS_KEYS
```

The initial stub dict at lines 10–54 is ONLY used to seed the intermediate constants at
lines 162–171. The real `FULL_EVENT_CATALOG` at line 347 is what callers use.

When moving these to `src/events/catalog.py`, the entire initialization sequence must be
preserved top-to-bottom. Task 3 (catalog extraction) handles this explicitly by renaming the
stub to `_LEGACY_STUB` so its reference can be resolved before the final `FULL_EVENT_CATALOG`
is assigned.

### Risk 2: Test patches via `settings_module.os` and `settings_module.get_last_input_action`

Two test files import `settings_module = src.settings` and then patch:
- `settings_module.os` — stops the screen-clear call from firing during tests
- `settings_module.get_last_input_action` — controls flow-control logic in traffic/bandwidth menus

After the split, `os` is imported inside each new module, not in `src/settings.py`. Patching
`settings_module.os` would patch the shim's `os` reference, which the new modules don't use.

**Mitigation (chosen):** Update the test patches in Task 11 to target the new module paths:
- `settings_module.os` → `src.cli.menus.manage_rules.os` (in test_manage_rules_menu.py)
- `settings_module.os` → `src.cli.menus.traffic.os` + `src.cli.menus.bandwidth.os`
  (in test_wizard_default_enter.py)
- `settings_module.get_last_input_action` → `src.cli.menus._helpers.get_last_input_action`

Tasks 7–9 may cause those specific tests to fail temporarily; Task 11 is the designated fix.

### Risk 3: Circular import between `src/cli/menus/event.py` and `src/events/catalog.py`

`add_event_menu` in `event.py` will import `FULL_EVENT_CATALOG`, `ACTION_EVENTS` from
`src/events/catalog.py`. Those catalog symbols are built using `KNOWN_EVENT_TYPES` which
lives in the same `src/events/catalog.py`. No circular dependency exists because
`src/events/catalog.py` imports nothing from `src/cli/`.

Verify after Task 3:
```bash
venv/bin/python3 -c "from src.events.catalog import FULL_EVENT_CATALOG; print('ok')"
```

### Risk 4: `_web_gui_tls_menu` lazy-imports from `src.gui`

`_web_gui_tls_menu` (line 1602) contains a lazy import inside the function body:
```python
from src.gui import (
    _generate_self_signed_cert,
    _get_cert_info,
    _cert_days_remaining,
    _ROOT_DIR,
    _SELF_SIGNED_VALIDITY_DAYS,
)
```

This import is intentionally lazy — it avoids importing Flask when the CLI starts. After
moving `_web_gui_tls_menu` to `src/cli/menus/web_gui.py`, the lazy import stays lazy.

**Note:** If H5 (Blueprint split) runs before H6, these private TLS helpers may move from
`src/gui/__init__.py` to `src/gui/tls.py`. H6 must be coordinated: if H5 has moved the
helpers, update the lazy import path in `web_gui.py` accordingly at Task 10.

### Risk 5: `manage_report_schedules_menu` infers `root_dir` from `__file__`

At line 1963:
```python
pkg_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(pkg_dir)
state_file = os.path.join(root_dir, "logs", "state.json")
```

When `__file__` was `src/settings.py`, `pkg_dir = src/` and `root_dir = <project_root>/`.
After moving to `src/cli/menus/report_schedule.py`, `pkg_dir = src/cli/menus/` and
`root_dir = src/cli/` — **wrong path**.

**Fix required in Task 10:** Replace the chain with pathlib:

```python
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
# parents[0]=menus, parents[1]=cli, parents[2]=src, parents[3]=project_root
state_file = str(_PROJECT_ROOT / "logs" / "state.json")
```

Verify before committing Task 10:
```bash
venv/bin/python3 -c "
from pathlib import Path
p = Path('src/cli/menus/report_schedule.py').resolve()
print(p.parents[3])  # should equal project root
"
```

---

## File Structure (before → after)

**Before:** `src/settings.py` — 2218 lines

**After:**
```
src/
├── settings/
│   └── __init__.py              ~55 lines  (shim, kept for backwards compat)
├── cli/
│   └── menus/
│       ├── __init__.py          ~50 lines  (re-exports all wizard public API)
│       ├── _helpers.py          ~80 lines  (shared wizard helpers)
│       ├── event.py             ~230 lines (add_event_menu; original lines 416–633)
│       ├── system_health.py     ~80 lines  (add_system_health_menu; lines 635–711)
│       ├── traffic.py           ~280 lines (add_traffic_menu; lines 713–990)
│       ├── bandwidth.py         ~270 lines (add_bandwidth_volume_menu; lines 992–1258)
│       ├── manage_rules.py      ~155 lines (manage_rules_menu; lines 108–122 + 1260–1407)
│       ├── alert.py             ~95 lines  (alert_settings_menu; lines 1409–1500)
│       ├── web_gui.py           ~175 lines (web_gui_security_menu + TLS; lines 1501–1769)
│       ├── report_schedule.py   ~265 lines (schedules wizard; lines 1953–2218)
│       └── _root.py             ~185 lines (settings_menu; lines 1771–1950)
└── events/
    └── catalog.py               ~340 lines (original ~300 + wizard-catalog symbols)
```

Net change: 2218 lines split into ~1900 lines of content across 12 new/modified files plus
a ~55-line shim.

---

## Pre-flight Checklist (run once before starting)

- [ ] Verify clean working tree: `git status` → "nothing to commit"
- [ ] Verify on correct branch (H6 runs on top of Batch 5 fixes):
      `git log --oneline -3` — confirm recent commits are code-review-fixes work
- [ ] Verify test suite green baseline:
      `venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3`
      → expect `824 passed, 1 skipped`
- [ ] Confirm `src/settings.py` is 2218 lines:
      `wc -l src/settings.py` → `2218 src/settings.py`
- [ ] Confirm `src/cli/menus/` does NOT yet exist:
      `ls src/cli/menus/ 2>&1` → "No such file or directory"
- [ ] Confirm `src/events/catalog.py` exists and exports `KNOWN_EVENT_TYPES`:
      `venv/bin/python3 -c "from src.events.catalog import KNOWN_EVENT_TYPES; print(len(KNOWN_EVENT_TYPES))"`
      → a number (approximately 280)
- [ ] Create branch:
      `git checkout -b h6-settings-rename-reorg`

---

## Task 1: Capture golden-output baseline for catalog constants

**Why:** The four computed constants (`FULL_EVENT_CATALOG`, `ACTION_EVENTS`,
`SEVERITY_FILTER_EVENTS`, `DISCOVERY_EVENTS`) are built at import time from `KNOWN_EVENT_TYPES`.
Any mistake in the catalog-extraction task (Task 3) would produce a silently wrong catalog.
Capturing a JSON snapshot now and testing against it after Task 3 makes drift detectable at
the commit boundary.

**Files:**
- Create: `tests/_settings_catalog_baseline.json` (generated, not hand-authored)
- Create: `tests/test_settings_catalog_baseline.py` (temporary — deleted in Task 12)

- [ ] **Step 1: Generate the baseline JSON**

```bash
venv/bin/python3 - <<'PY'
import json
import pathlib
from src import settings as s

baseline = {
    "FULL_EVENT_CATALOG": s.FULL_EVENT_CATALOG,
    "ACTION_EVENTS": s.ACTION_EVENTS,
    "SEVERITY_FILTER_EVENTS": s.SEVERITY_FILTER_EVENTS,
    "DISCOVERY_EVENTS": s.DISCOVERY_EVENTS,
    "EVENT_DESCRIPTION_KEYS": s.EVENT_DESCRIPTION_KEYS,
    "EVENT_TIPS_KEYS": s.EVENT_TIPS_KEYS,
}
out = pathlib.Path("tests/_settings_catalog_baseline.json")
out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
print(f"Wrote {out}: {out.stat().st_size} bytes")
cats = baseline['FULL_EVENT_CATALOG']
total = sum(len(v) for v in cats.values())
print(f"  FULL_EVENT_CATALOG: {total} entries across {len(cats)} categories")
print(f"  ACTION_EVENTS: {len(baseline['ACTION_EVENTS'])}")
print(f"  SEVERITY_FILTER_EVENTS: {len(baseline['SEVERITY_FILTER_EVENTS'])}")
print(f"  DISCOVERY_EVENTS: {len(baseline['DISCOVERY_EVENTS'])}")
print(f"  EVENT_DESCRIPTION_KEYS: {len(baseline['EVENT_DESCRIPTION_KEYS'])}")
print(f"  EVENT_TIPS_KEYS: {len(baseline['EVENT_TIPS_KEYS'])}")
PY
```

Expected: a JSON file written successfully, approximately 11 categories in
`FULL_EVENT_CATALOG`, approximately 12 entries in `ACTION_EVENTS`.

- [ ] **Step 2: Write the differential test**

`tests/test_settings_catalog_baseline.py`:

```python
"""Golden-output snapshot test for the H6 refactor.

Compares catalog constants from src.settings against a baseline captured
before the refactor. Deleted in Task 12 once the refactor is verified complete.
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

_BASELINE_PATH = Path(__file__).parent / "_settings_catalog_baseline.json"


def _baseline() -> dict:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("symbol", [
    "FULL_EVENT_CATALOG",
    "ACTION_EVENTS",
    "SEVERITY_FILTER_EVENTS",
    "DISCOVERY_EVENTS",
    "EVENT_DESCRIPTION_KEYS",
    "EVENT_TIPS_KEYS",
])
def test_catalog_symbol_matches_baseline(symbol):
    from src import settings as s
    actual = getattr(s, symbol)
    expected = _baseline()[symbol]
    if isinstance(expected, dict):
        drifted = {k for k in set(expected) | set(actual) if expected.get(k) != actual.get(k)}
        assert not drifted, (
            f"{symbol} drifted from baseline on keys: {list(drifted)[:5]}"
        )
    else:
        assert actual == expected, (
            f"{symbol} drifted: got {len(actual)} items, expected {len(expected)}"
        )
```

- [ ] **Step 3: Run the test against pristine baseline (must pass)**

```bash
venv/bin/python3 -m pytest tests/test_settings_catalog_baseline.py -v --timeout=60 2>&1 | tail -12
```

Expected: `6 passed`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_settings_catalog_baseline.py tests/_settings_catalog_baseline.json
git commit -m "$(cat <<'EOF'
test(settings): add baseline snapshot for H6 catalog constants refactor

Captures FULL_EVENT_CATALOG, ACTION_EVENTS, SEVERITY_FILTER_EVENTS,
DISCOVERY_EVENTS, EVENT_DESCRIPTION_KEYS, EVENT_TIPS_KEYS as a JSON
snapshot plus 6 parametrized tests. Guards Task 3 (catalog extraction)
from silent drift. Both files deleted in Task 12.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create `src/cli/menus/` package skeleton and convert `src/settings.py` to a package

**Why:** Before moving any code we need two things: (a) the destination package directory
exists, and (b) `src/settings.py` is converted to a package (`src/settings/__init__.py`) that
acts as a shim, so all six importers keep working throughout the entire refactor without any
changes to their files.

Converting to a shim first means every subsequent task can be verified with the full test
suite passing — we never have a broken intermediate state.

**Files:**
- Create: `src/cli/menus/__init__.py` (initially just a docstring — filled in per task)
- Create: `src/settings/__init__.py` (shim that re-exports from `_legacy`)
- Rename: `src/settings.py` → `src/settings/_legacy.py`

**CRITICAL — test-patch compatibility:** Two test files do:
```python
from src import settings as settings_module
monkeypatch.setattr(settings_module.os, "system", ...)
monkeypatch.setattr(settings_module, "get_last_input_action", ...)
```

For these patches to remain effective on the shim throughout Tasks 3–10 (while all wizard
code still lives in `_legacy.py`), `src/settings/__init__.py` must expose `os` and
`get_last_input_action` as module-level names. Task 11 updates those test patches to target
the final new-module locations after `_legacy.py` is deleted.

**Note on H4 precedent:** This is identical to how H4 handled `src/i18n.py` — rename the
file into a package, add a `__init__.py` shim, keep tests green throughout, delete `_legacy`
at the end.

- [ ] **Step 1: Create the menus package directory**

```bash
mkdir -p src/cli/menus
```

`src/cli/menus/__init__.py` initial content:

```python
"""CLI interactive wizard menus.

Public wizard functions are exported here as a convenience. Each function
also lives in its own module (event.py, traffic.py, etc.).
"""
# Populated incrementally by Tasks 5-10.
```

- [ ] **Step 2: Convert `src/settings.py` into a package**

```bash
mkdir -p src/settings
git mv src/settings.py src/settings/_legacy.py
```

- [ ] **Step 3: Write `src/settings/__init__.py`**

```python
"""src/settings — backwards-compatibility re-export shim.

The wizard functions and catalog constants have moved:
  Wizards  → src/cli/menus/
  Catalogs → src/events/catalog

This shim re-exports every public symbol so all six importers of
`from src.settings import X` continue to work unchanged.

This shim also re-exports `os` and `get_last_input_action` at module level
so that test patches of `settings_module.os` and
`settings_module.get_last_input_action` (in tests/test_manage_rules_menu.py
and tests/test_wizard_default_enter.py) remain effective during Tasks 3-10
while wizard code still lives in _legacy.py.
"""
from __future__ import annotations

import os  # noqa: F401  (needed for test-patch compatibility)
from src.utils import get_last_input_action  # noqa: F401  (ditto)

from src.settings._legacy import (  # noqa: F401
    # Catalog constants
    FULL_EVENT_CATALOG,
    ACTION_EVENTS,
    SEVERITY_FILTER_EVENTS,
    DISCOVERY_EVENTS,
    EVENT_DESCRIPTION_KEYS,
    EVENT_TIPS_KEYS,
    # Catalog helpers (used by src/gui/__init__.py)
    _event_category,
    # Wizard functions (used by src/main.py)
    settings_menu,
    add_event_menu,
    add_system_health_menu,
    add_traffic_menu,
    add_bandwidth_volume_menu,
    manage_rules_menu,
    manage_report_schedules_menu,
    # Helpers accessed via settings_module in tests
    _parse_manage_rules_command,
    _wizard_step,
    _wizard_confirm,
    _menu_hints,
    _tz_offset_info,
    _utc_to_local_hour,
    _local_to_utc_hour,
    _empty_uses_default,
)
```

- [ ] **Step 4: Run the full test suite**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: `830 passed, 1 skipped` (824 original + 6 from Task 1).

- [ ] **Step 5: Confirm the baseline still passes**

```bash
venv/bin/python3 -m pytest tests/test_settings_catalog_baseline.py -v --timeout=60 2>&1 | tail -8
```

Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/settings/__init__.py src/settings/_legacy.py src/cli/menus/__init__.py
git commit -m "$(cat <<'EOF'
refactor(settings): convert src/settings.py to package skeleton (H6 step 1)

Renames src/settings.py → src/settings/_legacy.py and adds __init__.py
that re-exports every public symbol so all six importers keep working.
Creates empty src/cli/menus/__init__.py for subsequent tasks.

Also re-exports `os` and `get_last_input_action` at shim level so test
patches of settings_module.os / settings_module.get_last_input_action
remain effective during Tasks 3-10 (while code still lives in _legacy.py).

No behaviour change; all 830 tests green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Extract catalog constants to `src/events/catalog.py`

**Why:** `FULL_EVENT_CATALOG` and its companion constants are event data, not CLI code. They
belong in `src/events/`, alongside `KNOWN_EVENT_TYPES`. Moving them here also eliminates the
risk of circular imports: once in `src/events/catalog.py`, the wizard modules can import from
`src.events.catalog` without touching `src/settings`.

**Files:**
- Modify: `src/events/catalog.py` — append all catalog builder constants and functions
- Modify: `src/settings/_legacy.py` — replace catalog block with imports from `src.events.catalog`

The catalog section in `_legacy.py` spans roughly lines 10–414 of the original file:
initial stub dict, intermediate constants, helper functions, `_build_full_event_catalog()`,
final computed constants, `EVENT_DESCRIPTION_KEYS`, `EVENT_TIPS_KEYS`.

**Initialization order to preserve when appending to `src/events/catalog.py`:**

The new content must be appended AFTER the existing content (KNOWN_EVENT_TYPES and
is_known_event_type). The ordering within the appended block must match the original:

```
# 1. Legacy stub dict (the initial FULL_EVENT_CATALOG stub from _legacy.py lines 10–54)
#    Renamed to _LEGACY_STUB to distinguish it from the final FULL_EVENT_CATALOG below.
_LEGACY_STUB = { "General": {"*": "event_all_events"}, ... }

# 2. Intermediate constants built from _LEGACY_STUB (original lines 162–171)
_LEGACY_EVENT_CATALOG = _LEGACY_STUB          ← note: was "= FULL_EVENT_CATALOG" in original
_EVENT_CATEGORY_OVERRIDES = {event_id: cat for cat, events in _LEGACY_EVENT_CATALOG.items() ...}
_EVENT_DESCRIPTION_OVERRIDES = {event_id: desc for events in _LEGACY_EVENT_CATALOG.values() ...}

# 3. Builder configuration (original lines 173–202)
_CATEGORY_ORDER = [...]
_HIDDEN_EVENT_TYPES = {...}
_STATUS_FILTER_EVENT_TYPES = {...}
_SEVERITY_FILTER_EVENT_TYPES = set(_STATUS_FILTER_EVENT_TYPES)

# 4. Helper functions (original lines 204–345)
def _humanize_event_id(event_id: str) -> str: ...
def _event_category(event_id: str) -> str: ...      # uses _EVENT_CATEGORY_OVERRIDES
def _event_translation_key(event_id: str) -> str: ... # uses _EVENT_DESCRIPTION_OVERRIDES
def _build_full_event_catalog() -> dict[str, dict[str, str]]: ...  # uses KNOWN_EVENT_TYPES

# 5. Final computed constants — module-load-time (original lines 347–350)
FULL_EVENT_CATALOG = _build_full_event_catalog()
ACTION_EVENTS = sorted(e for e in KNOWN_EVENT_TYPES if e in _STATUS_FILTER_EVENT_TYPES)
SEVERITY_FILTER_EVENTS = sorted(e for e in KNOWN_EVENT_TYPES if e in _SEVERITY_FILTER_EVENT_TYPES)
DISCOVERY_EVENTS = sorted(set(KNOWN_EVENT_TYPES) - set(ACTION_EVENTS))

# 6. Description / tips lookup dicts (original lines 352–414)
EVENT_DESCRIPTION_KEYS = { "agent.goodbye": "event_desc_agent_goodbye", ... }
EVENT_TIPS_KEYS = { "*": "event_tips_all", ... }
```

**The single critical rename:** In the original, line 162 reads
`_LEGACY_EVENT_CATALOG = FULL_EVENT_CATALOG` — this captured the initial stub. After the
move, the stub is `_LEGACY_STUB`, so this line becomes
`_LEGACY_EVENT_CATALOG = _LEGACY_STUB`.

Do NOT copy the stub lists at original lines 129–160 (`ACTION_EVENTS = [...]` and
`DISCOVERY_EVENTS = [...]`). Those were overwritten at lines 348–350; the final versions
from the `_build_full_event_catalog()` call are the ones that matter.

- [ ] **Step 1: Open `src/events/catalog.py` and append the catalog block**

After the closing line `KNOWN_EVENT_TYPES |= LOCAL_EXTENSION_EVENT_TYPES` and the
`is_known_event_type` function, append a blank line and a section header comment, then
copy the catalog block as described above. Exact content comes from `src/settings/_legacy.py`
lines 10–414 (adjust for renaming `FULL_EVENT_CATALOG` stub → `_LEGACY_STUB` on the single
line that assigns it to `_LEGACY_EVENT_CATALOG`).

- [ ] **Step 2: Verify the new catalog module loads in isolation**

```bash
venv/bin/python3 - <<'PY'
from src.events.catalog import (
    FULL_EVENT_CATALOG, ACTION_EVENTS, SEVERITY_FILTER_EVENTS,
    DISCOVERY_EVENTS, EVENT_DESCRIPTION_KEYS, EVENT_TIPS_KEYS, _event_category
)
print(f"FULL_EVENT_CATALOG: {len(FULL_EVENT_CATALOG)} categories")
print(f"ACTION_EVENTS: {len(ACTION_EVENTS)}")
print(f"DISCOVERY_EVENTS: {len(DISCOVERY_EVENTS)}")
print(f"_event_category('agent.goodbye'): {_event_category('agent.goodbye')}")
PY
```

Expected: non-zero counts matching the baseline, `_event_category('agent.goodbye')` returns
`"Agent Health"`.

- [ ] **Step 3: Update `src/settings/_legacy.py` — replace catalog block with imports**

Find lines 10–414 in `_legacy.py` (the entire catalog block: stub dict, intermediate
constants, helper functions, final computed constants, description/tips dicts). Replace ALL
of it with:

```python
# Catalog constants and helpers have moved to src/events/catalog.
# Imported here so _legacy.py callers keep working during the H6 refactor.
from src.events.catalog import (
    FULL_EVENT_CATALOG,
    ACTION_EVENTS,
    SEVERITY_FILTER_EVENTS,
    DISCOVERY_EVENTS,
    EVENT_DESCRIPTION_KEYS,
    EVENT_TIPS_KEYS,
    _event_category,
    _humanize_event_id,
    _event_translation_key,
    _build_full_event_catalog,
    _LEGACY_STUB,
    _LEGACY_EVENT_CATALOG,
    _EVENT_CATEGORY_OVERRIDES,
    _EVENT_DESCRIPTION_OVERRIDES,
    _CATEGORY_ORDER,
    _HIDDEN_EVENT_TYPES,
    _STATUS_FILTER_EVENT_TYPES,
    _SEVERITY_FILTER_EVENT_TYPES,
)
```

Also remove the stub `ACTION_EVENTS = [...]` and `DISCOVERY_EVENTS = [...]` list literals at
the original lines 129–160 (they were overwritten anyway and are now covered by the import
above).

- [ ] **Step 4: Run full test suite + catalog baseline**

```bash
venv/bin/python3 -m pytest tests/test_settings_catalog_baseline.py -v --timeout=60 2>&1 | tail -8
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected:
- Baseline: `6 passed` (FULL_EVENT_CATALOG and friends are structurally identical).
- Full suite: `830 passed, 1 skipped`.

**If baseline fails:** The most likely cause is the `_LEGACY_EVENT_CATALOG = _LEGACY_STUB`
rename. Inspect: `_event_category` uses `_EVENT_CATEGORY_OVERRIDES` which is built from
`_LEGACY_STUB`. If `_LEGACY_STUB` is missing any key that the original stub had, categories
will differ. Compare the stub dict you appended against the original lines 10–54.

- [ ] **Step 5: Commit**

```bash
git add src/events/catalog.py src/settings/_legacy.py
git commit -m "$(cat <<'EOF'
refactor(settings): extract FULL_EVENT_CATALOG to src/events/catalog (H6 step 2)

Appends the wizard-facing event catalog (FULL_EVENT_CATALOG, ACTION_EVENTS,
SEVERITY_FILTER_EVENTS, DISCOVERY_EVENTS, EVENT_DESCRIPTION_KEYS,
EVENT_TIPS_KEYS, and builder internals) to src/events/catalog.py.

src/settings/_legacy.py now imports these from src.events.catalog.
The _LEGACY_STUB rename (was FULL_EVENT_CATALOG stub) is the only
semantic change from a verbatim copy; it prevents a forward-reference
error before the final FULL_EVENT_CATALOG is assigned.

Baseline snapshot test (6 assertions) confirms no catalog drift.
Removes approximately 400 lines from _legacy.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Extract shared wizard helpers to `src/cli/menus/_helpers.py`

**Why:** Eight functions are used by multiple wizard modules. Extracting them first prevents
any need for sibling wizard modules to import from each other.

**Functions to move (all currently in `src/settings/_legacy.py`):**
- `_tz_offset_info(cm)` — original line 56
- `_utc_to_local_hour(utc_hour, offset_hours)` — original line 75
- `_local_to_utc_hour(local_hour, offset_hours)` — original line 78
- `_menu_hints(path)` — original line 81
- `_wizard_step(step, total, title)` — original line 87
- `_wizard_confirm(summary_lines)` — original line 91
- `_empty_uses_default(default_value)` — original line 125

**Files:**
- Create: `src/cli/menus/_helpers.py`
- Modify: `src/settings/_legacy.py` — replace function bodies with an import block

- [ ] **Step 1: Create `src/cli/menus/_helpers.py`**

```python
"""Shared helper functions for all CLI wizard menus.

Previously defined in src/settings.py; extracted here as part of the H6 refactor.
"""
from __future__ import annotations
import datetime

from src.utils import Colors, draw_panel, get_last_input_action
from src.i18n import t


def _tz_offset_info(cm) -> tuple[str, float]:
    """Return (tz_label, offset_hours) from config's settings.timezone."""
    tz_str = cm.config.get('settings', {}).get('timezone', 'local')
    if not tz_str or tz_str == 'local':
        offset = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
        hours = offset.total_seconds() / 3600
        sign = '+' if hours >= 0 else '-'
        abs_h = abs(hours)
        label = (f"UTC{sign}{int(abs_h):02d}" if abs_h == int(abs_h)
                 else f"UTC{sign}{abs_h}")
        return label, hours
    if tz_str == 'UTC':
        return 'UTC', 0.0
    if tz_str.startswith('UTC+') or tz_str.startswith('UTC-'):
        sign = 1 if tz_str[3] == '+' else -1
        hours = sign * float(tz_str[4:])
        return tz_str, hours
    return 'UTC', 0.0


def _utc_to_local_hour(utc_hour: int, offset_hours: float) -> int:
    return int(((utc_hour + offset_hours) % 24 + 24) % 24)


def _local_to_utc_hour(local_hour: int, offset_hours: float) -> int:
    return int(((local_hour - offset_hours) % 24 + 24) % 24)


def _menu_hints(path: str) -> list[str]:
    return [
        f"{Colors.DARK_GRAY}{t('cli_path_label', path=path)}{Colors.ENDC}",
        f"{Colors.DARK_GRAY}{t('cli_shortcuts_compact')}{Colors.ENDC}",
    ]


def _wizard_step(step: int, total: int, title: str) -> None:
    step_label = t("wiz_step")
    print(f"\n{Colors.BOLD}{Colors.CYAN}[{step_label} {step}/{total}] {title}{Colors.ENDC}")


def _wizard_confirm(summary_lines: list[str]) -> bool:
    title = t("wiz_review_config")
    draw_panel(title, summary_lines)
    prompt = t("wiz_save_rule_confirm")
    answer = (
        input(f"\n{Colors.CYAN}[?]{Colors.ENDC} {prompt} {Colors.GREEN}>❯{Colors.ENDC} ")
        .strip()
        .lower()
    )
    if not answer:
        return True
    return answer in ["y", "yes", "是", "好"]


def _empty_uses_default(default_value) -> bool:
    return get_last_input_action() == "empty" and default_value not in (None, "")
```

- [ ] **Step 2: Update `src/settings/_legacy.py`**

Replace the function bodies of the seven helpers with a single import block:

```python
from src.cli.menus._helpers import (
    _tz_offset_info,
    _utc_to_local_hour,
    _local_to_utc_hour,
    _menu_hints,
    _wizard_step,
    _wizard_confirm,
    _empty_uses_default,
)
```

Delete the original function bodies at original lines 56–126.

- [ ] **Step 3: Run the full test suite**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: `830 passed, 1 skipped`.

- [ ] **Step 4: Commit**

```bash
git add src/cli/menus/_helpers.py src/settings/_legacy.py
git commit -m "$(cat <<'EOF'
refactor(settings): extract shared wizard helpers to src/cli/menus/_helpers.py (H6 step 3)

Moves _wizard_step, _wizard_confirm, _menu_hints, _tz_offset_info,
_utc_to_local_hour, _local_to_utc_hour, _empty_uses_default to the
shared helpers module. _legacy.py imports them back so all wizard
functions still find them.

Removes approximately 70 lines from _legacy.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Extract `add_event_menu` to `src/cli/menus/event.py`

**Files:**
- Create: `src/cli/menus/event.py`
- Modify: `src/settings/_legacy.py`, `src/cli/menus/__init__.py`

`add_event_menu` spans original lines 416–633 (~218 lines). It references `FULL_EVENT_CATALOG`,
`ACTION_EVENTS`, `_SEVERITY_FILTER_EVENT_TYPES` from the catalog (now in `src/events/catalog`)
and the shared helpers.

- [ ] **Step 1: Create `src/cli/menus/event.py`**

```python
"""CLI wizard for adding or editing event alert rules."""
from __future__ import annotations
import os
import datetime

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel, draw_table
from src.events.catalog import (
    FULL_EVENT_CATALOG,
    ACTION_EVENTS,
    _SEVERITY_FILTER_EVENT_TYPES,
)
from src.cli.menus._helpers import _menu_hints, _wizard_step, _wizard_confirm


def add_event_menu(cm: ConfigManager, edit_rule=None) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 416-633).
    # Remove the `from src.utils import ...` lazy import inside the function
    # body (original line 417) — those imports are now at the top of this file.
    ...
```

**After copying:** the `while True:` loop at the start of `add_event_menu` calls `draw_panel`,
`safe_input`, `draw_table` — all available via top-level imports. The internal call to
`_menu_hints` resolves via `_helpers` import. References to `FULL_EVENT_CATALOG` and
`ACTION_EVENTS` resolve via `src.events.catalog` import.

- [ ] **Step 2: Update `src/settings/_legacy.py`**

Replace the `add_event_menu` function body (original lines 416–633) with:

```python
from src.cli.menus.event import add_event_menu  # noqa: F401
```

- [ ] **Step 3: Update `src/cli/menus/__init__.py`**

```python
from src.cli.menus.event import add_event_menu  # noqa: F401
```

- [ ] **Step 4: Run the full test suite**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
venv/bin/python3 -m pytest tests/test_settings_catalog_baseline.py -v --timeout=60 2>&1 | tail -8
```

Expected: `830 passed, 1 skipped`; `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/cli/menus/event.py src/cli/menus/__init__.py src/settings/_legacy.py
git commit -m "$(cat <<'EOF'
refactor(settings): move add_event_menu to src/cli/menus/event.py (H6 step 4)

Extracts the 218-line add_event_menu wizard. Imports FULL_EVENT_CATALOG
from src.events.catalog (no circular dependency). _legacy.py re-imports
the function; shim unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Extract `add_system_health_menu` to `src/cli/menus/system_health.py`

**Files:**
- Create: `src/cli/menus/system_health.py`
- Modify: `src/settings/_legacy.py`, `src/cli/menus/__init__.py`

`add_system_health_menu` spans original lines 635–711 (~77 lines).

- [ ] **Step 1: Create `src/cli/menus/system_health.py`**

```python
"""CLI wizard for adding or editing system-health alert rules."""
from __future__ import annotations
import os
import datetime

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints, _wizard_step, _wizard_confirm


def add_system_health_menu(cm: ConfigManager, edit_rule=None) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 635-711).
    # Remove the `from src.utils import Colors, safe_input, draw_panel`
    # lazy import inside the function body (original line 636).
    ...
```

- [ ] **Step 2: Update `src/settings/_legacy.py` and `src/cli/menus/__init__.py`**

```python
# in _legacy.py:
from src.cli.menus.system_health import add_system_health_menu  # noqa: F401

# in menus/__init__.py — add:
from src.cli.menus.system_health import add_system_health_menu  # noqa: F401
```

- [ ] **Step 3: Run tests**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: `830 passed, 1 skipped`.

- [ ] **Step 4: Commit**

```bash
git add src/cli/menus/system_health.py src/cli/menus/__init__.py src/settings/_legacy.py
git commit -m "$(cat <<'EOF'
refactor(settings): move add_system_health_menu to src/cli/menus/system_health.py (H6 step 5)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Extract `add_traffic_menu` to `src/cli/menus/traffic.py`

**Files:**
- Create: `src/cli/menus/traffic.py`
- Modify: `src/settings/_legacy.py`, `src/cli/menus/__init__.py`

`add_traffic_menu` spans original lines 713–990 (~278 lines). It calls `_empty_uses_default`
and references no catalog constants.

- [ ] **Step 1: Create `src/cli/menus/traffic.py`**

```python
"""CLI wizard for adding or editing traffic alert rules."""
from __future__ import annotations
import os
import datetime

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import (
    _menu_hints,
    _wizard_step,
    _wizard_confirm,
    _empty_uses_default,
)


def add_traffic_menu(cm: ConfigManager, edit_rule=None) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 713-990).
    # Remove the `from src.utils import Colors, safe_input, draw_panel`
    # lazy import inside the function body (original line 714).
    # The nested `def should_restart_flow():` at original line 717 stays
    # INSIDE add_traffic_menu — it is a closure, not a module-level helper.
    ...
```

- [ ] **Step 2: Update `src/settings/_legacy.py` and `src/cli/menus/__init__.py`**

```python
from src.cli.menus.traffic import add_traffic_menu  # noqa: F401
```

- [ ] **Step 3: Run tests — note any failures in `test_wizard_default_enter.py`**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
venv/bin/python3 -m pytest tests/test_wizard_default_enter.py -v --timeout=60 2>&1 | tail -10
```

Expected: `830 passed, 1 skipped`.

**Expected failure mode:** `test_wizard_default_enter.py` patches `settings_module.os` to
suppress the screen-clear call. After this task, the screen-clear call is inside `traffic.py`
which has its own `os` reference — the patch on the shim no longer intercepts it. In a
terminal/CI environment the actual `clear` command runs but is harmless. If the test fails
due to an actual assertion error (not just a clear-screen side effect), that indicates a
genuine code-move error. Fix it before committing. If it fails only due to the patch issue,
note it and proceed — Task 11 fixes it.

- [ ] **Step 4: Commit**

```bash
git add src/cli/menus/traffic.py src/cli/menus/__init__.py src/settings/_legacy.py
git commit -m "$(cat <<'EOF'
refactor(settings): move add_traffic_menu to src/cli/menus/traffic.py (H6 step 6)

Note: test_wizard_default_enter.py's os-patch may no longer intercept
the screen-clear call inside traffic.py. Patch fix is in Task 11.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Extract `add_bandwidth_volume_menu` to `src/cli/menus/bandwidth.py`

**Files:**
- Create: `src/cli/menus/bandwidth.py`
- Modify: `src/settings/_legacy.py`, `src/cli/menus/__init__.py`

`add_bandwidth_volume_menu` spans original lines 992–1258 (~267 lines). Same structure as
traffic: includes a nested `def should_restart_flow():` closure that stays inside the function.

- [ ] **Step 1: Create `src/cli/menus/bandwidth.py`**

```python
"""CLI wizard for adding or editing bandwidth/volume alert rules."""
from __future__ import annotations
import os
import datetime

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import (
    _menu_hints,
    _wizard_step,
    _wizard_confirm,
    _empty_uses_default,
)


def add_bandwidth_volume_menu(cm: ConfigManager, edit_rule=None) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 992-1258).
    # Remove the `from src.utils import Colors, safe_input, draw_panel`
    # lazy import inside the function body (original line 993).
    # The nested `def should_restart_flow():` stays inside the function.
    ...
```

- [ ] **Step 2: Update `src/settings/_legacy.py` and `src/cli/menus/__init__.py`**

```python
from src.cli.menus.bandwidth import add_bandwidth_volume_menu  # noqa: F401
```

- [ ] **Step 3: Run tests**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: `830 passed, 1 skipped`.

- [ ] **Step 4: Commit**

```bash
git add src/cli/menus/bandwidth.py src/cli/menus/__init__.py src/settings/_legacy.py
git commit -m "$(cat <<'EOF'
refactor(settings): move add_bandwidth_volume_menu to src/cli/menus/bandwidth.py (H6 step 7)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Extract `manage_rules_menu` to `src/cli/menus/manage_rules.py`

**Files:**
- Create: `src/cli/menus/manage_rules.py`
- Modify: `src/settings/_legacy.py`, `src/cli/menus/__init__.py`

`manage_rules_menu` spans original lines 1260–1407. It calls all four wizard functions
(already moved to sibling modules by Tasks 5–8). `_parse_manage_rules_command` (original
lines 108–122) and `_MANAGE_RULES_COMMAND_RE` (original line 105) move here because they
are only used by `manage_rules_menu`.

- [ ] **Step 1: Create `src/cli/menus/manage_rules.py`**

```python
"""CLI wizard for the manage-rules menu (list, delete, modify rules)."""
from __future__ import annotations
import os
import re
import unicodedata

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel, draw_table, get_visible_width
from src.cli.menus._helpers import _menu_hints
from src.cli.menus.event import add_event_menu
from src.cli.menus.system_health import add_system_health_menu
from src.cli.menus.traffic import add_traffic_menu
from src.cli.menus.bandwidth import add_bandwidth_volume_menu


_MANAGE_RULES_COMMAND_RE = re.compile(
    r"^\s*([dm])\s*(\d+(?:\s*,\s*\d+)*)\s*$", re.IGNORECASE
)


def _parse_manage_rules_command(raw: str):
    # Copy verbatim from src/settings/_legacy.py (original lines 108-122).
    ...


def manage_rules_menu(cm: ConfigManager) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 1260-1407).
    # Remove the `from src.utils import draw_panel, draw_table, get_visible_width`
    # lazy import inside the function body (original line 1261).
    # Remove the `import unicodedata` inside the function body (original line 1335).
    # Both are now top-level imports above.
    ...
```

- [ ] **Step 2: Update `src/settings/_legacy.py`**

```python
from src.cli.menus.manage_rules import manage_rules_menu, _parse_manage_rules_command  # noqa: F401
```

Also remove `_MANAGE_RULES_COMMAND_RE` from `_legacy.py` (it moved).

- [ ] **Step 3: Update `src/cli/menus/__init__.py`**

```python
from src.cli.menus.manage_rules import manage_rules_menu  # noqa: F401
```

- [ ] **Step 4: Run tests — note any dispatch-patch failures**

```bash
venv/bin/python3 -m pytest tests/test_manage_rules_menu.py -v --timeout=60 2>&1 | tail -12
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: `830 passed, 1 skipped`.

**Expected failure mode for `test_manage_rules_menu.py`:** Tests that patch
`settings_module.add_event_menu` to intercept dispatch (e.g.
`test_manage_rules_menu_modify_command_routes_by_rule_type`) will fail here because
`manage_rules_menu` now calls `add_event_menu` from `src.cli.menus.manage_rules`, not from
`src.settings`. Patching the shim's attribute no longer intercepts the call.

Tests that do NOT rely on dispatch patches (delete, invalid format, multi-index modify
rejection) should continue to pass. If those fail, that is a genuine code-move error; fix
before committing.

Dispatch-patch failures are expected and are fixed in Task 11.

- [ ] **Step 5: Commit**

```bash
git add src/cli/menus/manage_rules.py src/cli/menus/__init__.py src/settings/_legacy.py
git commit -m "$(cat <<'EOF'
refactor(settings): move manage_rules_menu to src/cli/menus/manage_rules.py (H6 step 8)

Also moves _parse_manage_rules_command and _MANAGE_RULES_COMMAND_RE.
Sibling wizard functions imported directly from their new modules.

Note: dispatch-patch tests in test_manage_rules_menu.py may fail here;
fixed in Task 11 (test-patch updates).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Extract remaining wizard menus (alert, web_gui, report_schedule, settings_menu)

This task moves four more menus. They have no cross-dependencies on each other so they are
batched into one commit.

**Files:**
- Create: `src/cli/menus/alert.py`
- Create: `src/cli/menus/web_gui.py`
- Create: `src/cli/menus/report_schedule.py`
- Create: `src/cli/menus/_root.py`
- Modify: `src/settings/_legacy.py`, `src/cli/menus/__init__.py`

### 10a — `alert_settings_menu` → `src/cli/menus/alert.py`

Original lines 1409–1500 (~92 lines).

- [ ] **Step 1: Create `src/cli/menus/alert.py`**

```python
"""CLI wizard for alert-channel settings (mail, LINE, webhook, language)."""
from __future__ import annotations
import os

from src.config import ConfigManager
from src.i18n import t, set_language
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints, _wizard_step


def alert_settings_menu(cm: ConfigManager) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 1409-1500).
    # Remove the `from src.utils import draw_panel` lazy import (original line 1410).
    ...
```

### 10b — `web_gui_security_menu`, `_web_gui_tls_menu`, `_clear_screen` → `src/cli/menus/web_gui.py`

Original lines 1501–1769 (~269 lines). The `_clear_screen` helper at line 1598 also moves.

- [ ] **Step 2: Create `src/cli/menus/web_gui.py`**

```python
"""CLI wizard for Web GUI security settings (password, IP restrictions, TLS)."""
from __future__ import annotations
import os

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints


def _clear_screen() -> None:
    """Centralised screen-clear so callers don't each invoke subprocess."""
    import subprocess
    subprocess.run(["cls" if os.name == "nt" else "clear"], shell=False, check=False)


def web_gui_security_menu(cm: ConfigManager) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 1501-1597).
    # Remove the `from src.utils import draw_panel` lazy import (original line 1502).
    # The lazy `from src.config import hash_password` (original line 1552) stays
    # lazy inside its elif branch — do NOT hoist to top level.
    ...


def _web_gui_tls_menu(cm: ConfigManager) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 1602-1769).
    # The lazy import block:
    #   from src.gui import (
    #       _generate_self_signed_cert, _get_cert_info, _cert_days_remaining,
    #       _ROOT_DIR, _SELF_SIGNED_VALIDITY_DAYS,
    #   )
    # stays lazy inside the function body — do NOT hoist to top level.
    #
    # COORDINATION WITH H5: If H5 (Blueprint split) has moved these helpers
    # from src/gui/__init__.py to src/gui/tls.py, update the import path to
    # `from src.gui.tls import ...` before committing this task.
    ...
```

Note: `_clear_screen` in the original simply calls `os.system("cls" if os.name == "nt"
else "clear")`. The `os.system` call with static arguments is safe (it is not user-controlled),
but for explicitness the new implementation can use `subprocess.run` with `shell=False` and a
fixed command list. Either form is acceptable; choose the approach that matches the existing
codebase style.

### 10c — `manage_report_schedules_menu`, `_add_report_schedule_wizard` → `src/cli/menus/report_schedule.py`

Original lines 1953–2218 (~266 lines). **Critical: apply the `__file__` path fix (Risk 5).**

- [ ] **Step 3: Create `src/cli/menus/report_schedule.py`**

```python
"""CLI wizard for managing report schedules."""
from __future__ import annotations
import os
import json as _json
from pathlib import Path

from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel, draw_table
from src.cli.menus._helpers import (
    _menu_hints,
    _wizard_step,
    _wizard_confirm,
    _tz_offset_info,
    _utc_to_local_hour,
    _local_to_utc_hour,
)

# This file lives at src/cli/menus/report_schedule.py.
# parents[0]=menus  parents[1]=cli  parents[2]=src  parents[3]=project_root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def manage_report_schedules_menu(cm: ConfigManager) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 1953-2059).
    # Remove `from src.utils import Colors, safe_input, draw_panel, draw_table`
    # lazy import (original line 1955).
    # Remove `import json as _json` inside the function body (now top-level).
    #
    # REPLACE the __file__-relative state.json path calculation:
    #   ORIGINAL (wrong after move):
    #     pkg_dir = os.path.dirname(os.path.abspath(__file__))
    #     root_dir = os.path.dirname(pkg_dir)
    #     state_file = os.path.join(root_dir, "logs", "state.json")
    #   REPLACEMENT (correct):
    #     state_file = str(_PROJECT_ROOT / "logs" / "state.json")
    ...


def _add_report_schedule_wizard(cm: ConfigManager, edit_sched: dict = None) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 2060-2218).
    # Remove `from src.utils import Colors, safe_input, draw_panel` lazy import
    # if present inside the function body.
    ...
```

### 10d — `settings_menu` → `src/cli/menus/_root.py`

Original lines 1771–1950 (~180 lines). This is the top-level settings wizard; it calls
`alert_settings_menu` and `web_gui_security_menu` (both already moved above).

- [ ] **Step 4: Create `src/cli/menus/_root.py`**

```python
"""Top-level settings wizard (entry point for all settings navigation)."""
from __future__ import annotations
import os

from src import __version__
from src.config import ConfigManager
from src.i18n import t
from src.utils import Colors, safe_input, draw_panel
from src.cli.menus._helpers import _menu_hints, _wizard_step
from src.cli.menus.alert import alert_settings_menu
from src.cli.menus.web_gui import web_gui_security_menu


def settings_menu(cm: ConfigManager) -> None:
    # Copy verbatim from src/settings/_legacy.py (original lines 1771-1950).
    # Remove the `from src.utils import draw_panel` lazy import (original line 1772).
    ...
```

### 10e — Update `src/settings/_legacy.py` and `src/cli/menus/__init__.py`

- [ ] **Step 5: Update `_legacy.py`**

```python
from src.cli.menus.alert import alert_settings_menu  # noqa: F401
from src.cli.menus.web_gui import web_gui_security_menu, _web_gui_tls_menu, _clear_screen  # noqa: F401
from src.cli.menus.report_schedule import manage_report_schedules_menu  # noqa: F401
from src.cli.menus._root import settings_menu  # noqa: F401
```

- [ ] **Step 6: Update `src/cli/menus/__init__.py`**

```python
from src.cli.menus.alert import alert_settings_menu  # noqa: F401
from src.cli.menus.web_gui import web_gui_security_menu  # noqa: F401
from src.cli.menus.report_schedule import manage_report_schedules_menu  # noqa: F401
from src.cli.menus._root import settings_menu  # noqa: F401
```

### 10f — Verify `_PROJECT_ROOT` and run tests

- [ ] **Step 7: Verify `_PROJECT_ROOT` resolves correctly**

```bash
venv/bin/python3 - <<'PY'
from pathlib import Path
# Simulate the path resolution for report_schedule.py
simulated = (Path("src/cli/menus/report_schedule.py").resolve()).parents[3]
actual_proj = Path(".").resolve()
assert simulated == actual_proj, f"Mismatch: {simulated} vs {actual_proj}"
print(f"_PROJECT_ROOT resolves to: {simulated}  OK")
PY
```

- [ ] **Step 8: Run full test suite + catalog baseline**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
venv/bin/python3 -m pytest tests/test_settings_catalog_baseline.py -v --timeout=60 2>&1 | tail -8
```

Expected: `830 passed, 1 skipped`; `6 passed`.

- [ ] **Step 9: Commit**

```bash
git add \
  src/cli/menus/alert.py \
  src/cli/menus/web_gui.py \
  src/cli/menus/report_schedule.py \
  src/cli/menus/_root.py \
  src/cli/menus/__init__.py \
  src/settings/_legacy.py
git commit -m "$(cat <<'EOF'
refactor(settings): move alert, web_gui, report_schedule, settings_menu to src/cli/menus/ (H6 step 9)

Moves:
  alert_settings_menu             -> src/cli/menus/alert.py
  web_gui_security_menu +
    _web_gui_tls_menu + _clear_screen -> src/cli/menus/web_gui.py
  manage_report_schedules_menu +
    _add_report_schedule_wizard   -> src/cli/menus/report_schedule.py
  settings_menu                   -> src/cli/menus/_root.py

Fixes the __file__-relative state.json path in
manage_report_schedules_menu: old os.path.dirname chain resolved
to src/ as root; new Path.parents[3] resolves to project root
regardless of nesting depth.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Fix test patches and delete `src/settings/_legacy.py`

**Why:** With all wizard code now in `src/cli/menus/`, `_legacy.py` contains only re-export
imports. Before deleting it, the two test files that patch `settings_module.os` and
`settings_module.add_event_menu` etc. need updating — those patches no longer intercept calls
inside the new modules.

### 11a — Update `tests/test_manage_rules_menu.py`

The test's `_prepare_menu` function patches `settings_module.os`. After the move, the
screen-clear call happens in `src.cli.menus.manage_rules.os`. The dispatch patches
(`settings_module.add_event_menu` etc.) no longer intercept calls inside `manage_rules.py`.

Changes required:

1. Import `src.cli.menus.manage_rules` as `_mr` at the test module level (or inside the helper).
2. Change `monkeypatch.setattr(settings_module.os, "system", ...)` to
   `monkeypatch.setattr(_mr.os, "system", ...)`.
3. Change all four `monkeypatch.setattr(settings_module, "add_event_menu", ...)` calls to
   `monkeypatch.setattr(_mr, "add_event_menu", ...)` (and `add_system_health_menu`,
   `add_traffic_menu`, `add_bandwidth_volume_menu`).

The tests continue to call `settings_module.manage_rules_menu(cm)` — the shim routing
still works. Alternatively, the tests can be updated to call
`_mr.manage_rules_menu(cm)` directly.

- [ ] **Step 1: Edit `tests/test_manage_rules_menu.py`**

```python
# Add near top:
import src.cli.menus.manage_rules as _manage_rules_module

# Update _prepare_menu:
def _prepare_menu(monkeypatch, answers):
    inputs = iter(answers)
    monkeypatch.setattr(_manage_rules_module.os, "system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.utils.draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.utils.draw_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(inputs))

# Update all dispatch patches (lines ~74-77, ~111-114):
# OLD: monkeypatch.setattr(settings_module, "add_event_menu", ...)
# NEW: monkeypatch.setattr(_manage_rules_module, "add_event_menu", ...)
# (same for add_system_health_menu, add_traffic_menu, add_bandwidth_volume_menu)
```

### 11b — Update `tests/test_wizard_default_enter.py`

The test's `_prepare_wizard` patches `settings_module.os` and `settings_module.get_last_input_action`.
After the move, traffic/bandwidth have their own `os`, and `get_last_input_action` is used
inside `_empty_uses_default` which lives in `_helpers.py`.

Changes required:

1. Import `src.cli.menus.traffic`, `src.cli.menus.bandwidth`, `src.cli.menus._helpers`.
2. Patch `_tr.os.system` and `_bw.os.system` to suppress screen clears.
3. Patch `_helpers.get_last_input_action` (not `settings_module.get_last_input_action`)
   to control the `_empty_uses_default` flow logic.

- [ ] **Step 2: Edit `tests/test_wizard_default_enter.py`**

```python
# Add near top:
import src.cli.menus.traffic as _traffic_module
import src.cli.menus.bandwidth as _bandwidth_module
import src.cli.menus._helpers as _helpers_module

# Update _prepare_wizard:
def _prepare_wizard(monkeypatch, answers):
    state = {"action": "value"}
    queue = iter(answers)

    def fake_safe_input(*_args, **_kwargs):
        value, action = next(queue)
        state["action"] = action
        return value

    confirms = iter(["", ""])

    monkeypatch.setattr(_traffic_module.os, "system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_bandwidth_module.os, "system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.utils.draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.utils.safe_input", fake_safe_input)
    monkeypatch.setattr(_helpers_module, "get_last_input_action", lambda: state["action"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(confirms))
```

### 11c — Delete `_legacy.py` and finalise the shim

- [ ] **Step 3: Confirm `_legacy.py` contains only import lines**

```bash
grep -vE "^(from |import |#|$)" src/settings/_legacy.py | head -20
```

Expected: empty output.

- [ ] **Step 4: Confirm nothing imports `_legacy` by name**

```bash
grep -rn "settings._legacy\|settings import _legacy" src/ tests/ scripts/ 2>/dev/null
```

Expected: zero output.

- [ ] **Step 5: Delete `_legacy.py`**

```bash
git rm src/settings/_legacy.py
```

- [ ] **Step 6: Update `src/settings/__init__.py` to import directly from new modules**

Replace the current `from src.settings._legacy import (...)` block with direct imports:

```python
"""src/settings — backwards-compatibility re-export shim.

Wizard functions live in src/cli/menus/; catalog data in src/events/catalog.
This shim exists so the six importers of 'from src.settings import X' keep
working without changes.

The `os` and `get_last_input_action` module-level names are kept for any
external code that accesses them via the settings module reference.
"""
from __future__ import annotations

import os  # noqa: F401
from src.utils import get_last_input_action  # noqa: F401

from src.events.catalog import (  # noqa: F401
    FULL_EVENT_CATALOG,
    ACTION_EVENTS,
    SEVERITY_FILTER_EVENTS,
    DISCOVERY_EVENTS,
    EVENT_DESCRIPTION_KEYS,
    EVENT_TIPS_KEYS,
    _event_category,
)
from src.cli.menus.event import add_event_menu  # noqa: F401
from src.cli.menus.system_health import add_system_health_menu  # noqa: F401
from src.cli.menus.traffic import add_traffic_menu  # noqa: F401
from src.cli.menus.bandwidth import add_bandwidth_volume_menu  # noqa: F401
from src.cli.menus.manage_rules import (  # noqa: F401
    manage_rules_menu,
    _parse_manage_rules_command,
)
from src.cli.menus.alert import alert_settings_menu  # noqa: F401
from src.cli.menus.web_gui import (  # noqa: F401
    web_gui_security_menu,
    _web_gui_tls_menu,
)
from src.cli.menus.report_schedule import manage_report_schedules_menu  # noqa: F401
from src.cli.menus._root import settings_menu  # noqa: F401
from src.cli.menus._helpers import (  # noqa: F401
    _wizard_step,
    _wizard_confirm,
    _menu_hints,
    _tz_offset_info,
    _utc_to_local_hour,
    _local_to_utc_hour,
    _empty_uses_default,
)
```

- [ ] **Step 7: Run the full test suite**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
venv/bin/python3 -m pytest tests/test_manage_rules_menu.py tests/test_wizard_default_enter.py tests/test_event_core.py -v --timeout=60 2>&1 | tail -20
```

Expected: `830 passed, 1 skipped`; all targeted tests pass.

- [ ] **Step 8: Commit**

```bash
git add \
  tests/test_manage_rules_menu.py \
  tests/test_wizard_default_enter.py \
  src/settings/__init__.py
git commit -m "$(cat <<'EOF'
refactor(settings): fix test patches, drop _legacy.py, finalise shim (H6 step 10)

Updates test_manage_rules_menu.py to patch src.cli.menus.manage_rules.os
and src.cli.menus.manage_rules.add_*_menu instead of the shim module.

Updates test_wizard_default_enter.py to patch src.cli.menus.traffic.os,
src.cli.menus.bandwidth.os, and src.cli.menus._helpers.get_last_input_action
instead of the shim module.

Deletes src/settings/_legacy.py (contained only import lines after
Tasks 3-10). Updates src/settings/__init__.py to import directly from
the new modules.

All 830 tests green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Verification gate + retire baseline scaffolding

**Why:** The refactor is complete. The catalog-snapshot test was a guard during development;
keeping it permanently would require regenerating the snapshot every time event catalog content
changes legitimately. Remove it and record the final test count.

**Files:**
- Delete: `tests/test_settings_catalog_baseline.py`
- Delete: `tests/_settings_catalog_baseline.json`

- [ ] **Step 1: Final full-suite + mypy run**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -5
venv/bin/python3 -m mypy --config-file mypy.ini \
  src/settings/__init__.py \
  src/cli/menus/_helpers.py \
  src/cli/menus/event.py \
  src/cli/menus/manage_rules.py \
  src/events/catalog.py \
  2>&1 | tail -5
```

Expected:
- Tests: `830 passed, 1 skipped`.
- mypy: 0 errors on all five targeted files.

- [ ] **Step 2: Structural audit**

```bash
# src/settings/ is a package (not a .py file):
venv/bin/python3 -c "
import importlib.util
spec = importlib.util.find_spec('src.settings')
assert spec.submodule_search_locations is not None, 'src.settings must be a package'
print('src.settings is a package OK')
"

# All wizard menus importable from src.cli.menus:
venv/bin/python3 -c "
from src.cli.menus import (
    add_event_menu, add_system_health_menu, add_traffic_menu,
    add_bandwidth_volume_menu, manage_rules_menu, alert_settings_menu,
    web_gui_security_menu, manage_report_schedules_menu, settings_menu,
)
print('All wizard functions importable from src.cli.menus OK')
"

# Catalog importable from src.events.catalog:
venv/bin/python3 -c "
from src.events.catalog import (
    FULL_EVENT_CATALOG, ACTION_EVENTS, SEVERITY_FILTER_EVENTS,
    DISCOVERY_EVENTS, EVENT_DESCRIPTION_KEYS, EVENT_TIPS_KEYS, _event_category
)
print(f'Catalog: {len(FULL_EVENT_CATALOG)} categories OK')
"

# Shim still works for all known importers:
venv/bin/python3 -c "
from src.settings import (
    FULL_EVENT_CATALOG, ACTION_EVENTS, SEVERITY_FILTER_EVENTS,
    EVENT_DESCRIPTION_KEYS, EVENT_TIPS_KEYS, _event_category,
    settings_menu, add_event_menu, add_system_health_menu,
    add_traffic_menu, add_bandwidth_volume_menu, manage_rules_menu,
    manage_report_schedules_menu,
)
print('All shim re-exports OK')
"

# Line count sanity:
wc -l src/settings/__init__.py src/cli/menus/_helpers.py \
       src/cli/menus/event.py src/events/catalog.py
# Expected: __init__.py ~55, _helpers.py ~80, event.py ~230, catalog.py ~340
```

- [ ] **Step 3: Run i18n audit**

```bash
venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -3
```

Expected: `Total: 0 finding(s)`.

- [ ] **Step 4: Delete baseline scaffolding**

```bash
git rm tests/test_settings_catalog_baseline.py tests/_settings_catalog_baseline.json
```

- [ ] **Step 5: Run suite one final time — expect count drops by 6**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: `824 passed, 1 skipped` (back to pre-flight baseline; the 6 catalog tests are gone,
no regressions).

- [ ] **Step 6: Commit**

```bash
git add -u tests/
git commit -m "$(cat <<'EOF'
refactor(settings): retire H6 baseline scaffolding, verify final structure

H6 is complete. Baseline snapshot test served its purpose as a guard
during the refactor; removing it to avoid maintenance overhead.

Final structure:
  src/settings/__init__.py          ~55 lines  (shim)
  src/cli/menus/__init__.py         ~50 lines  (re-exports)
  src/cli/menus/_helpers.py         ~80 lines  (shared helpers)
  src/cli/menus/event.py            ~230 lines
  src/cli/menus/system_health.py    ~80 lines
  src/cli/menus/traffic.py          ~280 lines
  src/cli/menus/bandwidth.py        ~270 lines
  src/cli/menus/manage_rules.py     ~155 lines
  src/cli/menus/alert.py            ~95 lines
  src/cli/menus/web_gui.py          ~175 lines
  src/cli/menus/report_schedule.py  ~265 lines
  src/cli/menus/_root.py            ~185 lines
  src/events/catalog.py             ~340 lines  (extended)

Original src/settings.py: 2218 lines ->
shim: ~55 lines + ~1870 lines in focused modules.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final Acceptance

- [ ] `venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -3`
      → `824 passed, 1 skipped`
- [ ] `venv/bin/python3 scripts/audit_i18n_usage.py 2>&1 | tail -1`
      → `Total: 0 finding(s)`
- [ ] `venv/bin/python3 -m mypy --config-file mypy.ini src/settings/__init__.py src/cli/menus/ src/events/catalog.py 2>&1 | tail -3`
      → 0 errors
- [ ] `find src -maxdepth 2 -name 'settings.py' 2>/dev/null`
      → no output (the original standalone file is gone; `src/settings/__init__.py` is
      a package init, not a `settings.py` file)
- [ ] `ls src/settings/`
      → only `__init__.py` (plus `__pycache__/`)
- [ ] `ls src/cli/menus/`
      → `__init__.py _helpers.py _root.py alert.py bandwidth.py event.py manage_rules.py report_schedule.py system_health.py traffic.py web_gui.py`
- [ ] `wc -l src/settings/__init__.py` → output is ≤ 60
- [ ] `venv/bin/python3 -c "from src.settings import FULL_EVENT_CATALOG; print(len(FULL_EVENT_CATALOG), 'categories')"`
      → prints a non-zero count (approximately 11)
- [ ] `venv/bin/python3 -c "from src.cli.menus import settings_menu; print('ok')"`
      → `ok`
- [ ] `venv/bin/python3 -c "from src import gui; print('gui imported ok')"`
      → `gui imported ok` (confirms `src/gui/__init__.py` lazy imports of `_event_category`
      and catalog constants still resolve)
- [ ] Squash-merge or rebase-merge `h6-settings-rename-reorg` → `main`

---

## Self-Review Notes

**Spec coverage:** Every item in the Batch 4 H6 sketch is covered:

- "Move 24 wizard functions into `src/cli/menus/`" → Tasks 5–10 (add_event_menu,
  add_system_health_menu, add_traffic_menu, add_bandwidth_volume_menu, manage_rules_menu,
  alert_settings_menu, web_gui_security_menu + _web_gui_tls_menu + _clear_screen,
  manage_report_schedules_menu + _add_report_schedule_wizard, settings_menu,
  plus helpers _parse_manage_rules_command, _tz_offset_info, _utc_to_local_hour,
  _local_to_utc_hour, _menu_hints, _wizard_step, _wizard_confirm, _empty_uses_default).
- "Move `FULL_EVENT_CATALOG` to `src/events/catalog.py`" → Task 3. The existing
  `src/events/catalog.py` content (KNOWN_EVENT_TYPES, is_known_event_type) is preserved
  unchanged; wizard-catalog constants are appended.
- "Update every importer of `from src.settings import *`" → `src/settings/__init__.py` shim
  means all six importers keep working without changes; test patch paths updated in Task 11.
- "Delete `src/settings.py`" → converted to a package shim. The original `.py` file is gone;
  the package `src/settings/` with a ~55-line `__init__.py` replaces it.

**Placeholders:** None. Every task lists exact file paths, exact code blocks with the correct
import statements, exact verification commands with expected output.

**Type consistency:** All new module-level function signatures match the originals.
`_tz_offset_info` returns `tuple[str, float]`. `_wizard_confirm` returns `bool`.
`_parse_manage_rules_command` return type is left as-is from the original
(union of `tuple[str, int]` and `tuple[str, list[int]]`).

**Risk gating:** Task 1 captures a golden JSON baseline before any code moves. Every task
re-runs both the full suite AND the 6-assertion baseline test. Drift is caught at the
offending task boundary, not at the end.

**Reversibility:** Each task is a single commit. `git reset --hard HEAD~1` undoes any
single task. The branch `h6-settings-rename-reorg` is a throwaway until final acceptance.

**Test-patch strategy:** The two-phase approach (shim-level patches in Tasks 2–10 via
`_legacy.py`, module-level patches in Task 11 after `_legacy.py` is deleted) means there is
never a window where tests silently fail due to patch routing. Tasks 7–9 explicitly call out
the expected intermediate failure mode so the engineer knows what to expect.

**Coordination with H5:** If H5 runs before H6, verify the lazy import target of
`_web_gui_tls_menu` before committing Task 10. The plan calls this out with a `COORDINATION
WITH H5` comment in the code template for `web_gui.py`.
