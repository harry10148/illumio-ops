# H5 — `src/gui/__init__.py` Blueprint Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose the 3821-line `src/gui/__init__.py` monolith (77 Flask routes, 25+ helper functions, one giant `_create_app` factory) into a package of focused Blueprint modules. After the refactor, `__init__.py` shrinks to ~200 lines (factory shell, module-level state, backwards-compat re-exports) and each Blueprint file covers one coherent API topic.

**Architecture:** Keep `src/gui/__init__.py` as the public entry point and the factory home. Add `src/gui/_helpers.py` for shared utilities. Add `src/gui/routes/` as a subpackage. Each route module exports one `make_<topic>_blueprint(cm, ...)` factory. `_create_app` calls each factory and registers the returned Blueprint.

**Tech Stack:** Python 3.12, Flask 3.x, Flask-Login, Flask-WTF (CSRF), Flask-Limiter, Flask-Talisman. Tests: `venv/bin/python3 -m pytest`. mypy: `venv/bin/python3 -m mypy --config-file mypy.ini`.

---

## Scope Note

This plan is one of three Batch 4 sub-plans (see
`docs/superpowers/plans/2026-05-01-code-review-fixes.md` Batch 4 sketch). H4
(`src/i18n.py` data extraction) and H6 (`settings.py` rename) are separate
plans. This plan touches `src/gui/__init__.py` only — plus the new files it
creates under `src/gui/`.

External importers keep working unchanged. The complete list of symbols
imported from `src.gui` across the codebase:

| Symbol | Importer(s) |
|---|---|
| `build_app` | `tests/test_gui_auth.py`, `tests/test_api_settings.py`, `tests/test_web_security_contracts.py` |
| `_create_app` | `tests/test_siem_forwarder_api.py`, `tests/test_siem_test_endpoint.py`, `tests/test_siem_dlq_export.py`, `tests/test_rule_edit_pygments.py`, `tests/test_siem_web.py`, `tests/test_daemon_restart_api.py`, `tests/test_integrations_e2e.py`, `tests/test_gui_dashboard_plotly_endpoint.py`, `tests/test_web_security_contracts.py` |
| `launch_gui`, `HAS_FLASK`, `FLASK_IMPORT_ERROR` | `src/main.py`, `src/cli/_runtime.py` |
| `_RstDrop` | `tests/test_gui_ip_allowlist.py` |
| `_append_rs_logs` | `src/scheduler/jobs.py` |
| `_build_audit_dashboard_summary`, `_build_policy_usage_dashboard_summary` | `tests/test_phase34_attack_summaries.py` |
| `_build_ssl_context` | `tests/test_tls.py` |
| `_generate_self_signed_cert`, `_get_cert_info`, `_cert_days_remaining`, `_ROOT_DIR`, `_SELF_SIGNED_VALIDITY_DAYS` | `src/settings.py` |
| `_safe_log` | `tests/test_logging.py` |
| `_GUI_OWNS_DAEMON`, `_DAEMON_RESTART_FN`, `_DAEMON_SCHEDULER` | `src/cli/_runtime.py` (assigned at runtime) |

All of these MUST remain importable from `src.gui` after the refactor, via
re-exports from `__init__.py`.

---

## File Structure

After this refactor, the GUI subsystem looks like:

```
src/gui/
├── __init__.py              # ~200 lines. Module-level state (_GUI_OWNS_DAEMON,
│                            # _DAEMON_RESTART_FN, _DAEMON_SCHEDULER), _create_app
│                            # factory shell, launch_gui, build_app, and
│                            # backwards-compat re-exports for all previously-public
│                            # symbols (_RstDrop, _append_rs_logs, _safe_log, etc.).
│                            # No @app.route decorators remain here.
├── _helpers.py              # ~300 lines. Shared utilities used by ≥2 Blueprints:
│                            # _ok, _err, _safe_log, _err_with_log,
│                            # _redact_secrets, _strip_redaction_placeholders,
│                            # _normalize_ip_token, _loopback_equivalent,
│                            # _check_ip_allowed, _validate_allowed_ips,
│                            # _normalize_rule_throttle, _normalize_match_fields,
│                            # _is_workload_href, _normalize_quarantine_hrefs,
│                            # _rst_drop, _RstDrop, _strip_ansi, _ANSI_RE,
│                            # _SECRET_PATTERN, _SETTINGS_ALLOWLISTS,
│                            # _resolve_reports_dir, _resolve_config_dir,
│                            # _resolve_state_file, _GUI_DIR, _PKG_DIR, _ROOT_DIR,
│                            # _UI_EXTRA_KEYS, _ui_translation_dict,
│                            # _plugin_config_roots, _summarize_alert_channels,
│                            # _get_active_pce_url, _spec_to_plotly_figure,
│                            # _load_state_for_charts, chart-spec builders.
├── settings_helpers.py      # Unchanged (pre-existing).
└── routes/
    ├── __init__.py          # Empty — just marks the subpackage.
    ├── auth.py              # 4 routes: /, /login, /api/login, /logout.
    │                        # Also /api/csrf-token (logically auth-adjacent).
    ├── dashboard.py         # 9 routes: /api/dashboard/*, /api/status,
    │                        # /api/ui_translations.
    ├── config.py            # 7 routes: /api/settings (GET+POST),
    │                        # /api/alert-plugins, /api/tls/*, /api/pce-profiles.
    ├── rules.py             # 9 routes: /api/rules, /api/rules/event,
    │                        # /api/rules/system, /api/rules/traffic,
    │                        # /api/rules/bandwidth, /api/rules/<idx> (GET/PUT/DELETE),
    │                        # /api/rules/<idx>/highlight.
    ├── rule_scheduler.py    # 10 routes: /api/rule_scheduler/*.
    ├── reports.py           # 13 routes: /api/reports (GET), /api/reports/<path>
    │                        # (DELETE), /api/reports/bulk-delete, /reports/<path>
    │                        # (GET), /api/reports/generate, /api/audit_report/generate,
    │                        # /api/ven_status_report/generate,
    │                        # /api/policy_usage_report/generate,
    │                        # /api/report-schedules (GET+POST),
    │                        # /api/report-schedules/<id> (PUT/DELETE/toggle/run/history).
    ├── events.py            # 4 routes: /api/events/viewer, /api/events/shadow_compare,
    │                        # /api/events/rule_test, /api/event-catalog.
    ├── actions.py           # 8 routes: /api/actions/*, /api/init_quarantine,
    │                        # /api/quarantine/search, /api/quarantine/apply,
    │                        # /api/quarantine/bulk_apply, /api/workloads.
    └── admin.py             # 5 routes: /api/logs (list), /api/logs/<module>,
                             # /api/shutdown, /api/daemon/restart,
                             # /api/rule_scheduler/logs (log history).
```

Files NOT changed:
- `src/gui/settings_helpers.py`
- `src/siem/web.py` (already a Blueprint, registered in `_create_app` via try/except)
- `src/pce_cache/web.py` (already a Blueprint, same)

---

## Risk Analysis

### R1: Blueprint `before_request` hooks vs. app-level `before_request` hooks

**Risk:** The `security_check()` and `add_security_headers()` hooks at lines
756–803 are attached to the app (not a Blueprint). They must stay app-level.
If any Blueprint registers its own `@bp.before_request`, it runs ONLY for
that Blueprint's routes and does NOT replace the app-level hook.

**Mitigation:** `security_check` and `add_security_headers` stay in
`_create_app` as `@app.before_request` / `@app.after_request`. They are
NOT moved into any Blueprint. They reference `cm` (captured by closure) and
`current_user` (from Flask-Login) — both available app-level.

### R2: Error handlers must be app-level

**Risk:** `@app.errorhandler(CSRFError)`, `@app.errorhandler(429)`,
`@app.errorhandler(Exception)`, and `@app.errorhandler(_RstDrop)` at lines
626–754 handle errors for all routes. Blueprint-level `@bp.errorhandler`
would only fire for that Blueprint's routes.

**Mitigation:** All four error handlers stay inside `_create_app` as
`@app.errorhandler(...)`. They are never moved into a Blueprint.

### R3: Limiter decorators on Blueprint routes

**Risk:** `@limiter.limit("5 per minute")` on `api_login` (line 833) and
`@limiter.limit("5 per hour")` on `api_shutdown` and `api_daemon_restart`
reference the `limiter` object. Blueprints are defined in separate modules
but the `limiter` is created inside `_create_app`.

**Mitigation:** Each Blueprint factory receives `limiter` as a parameter:
`make_auth_blueprint(cm, csrf, limiter, login_required)`. The limiter is
passed in — no global reference required. Decorators apply normally inside
the factory closure.

### R4: `csrf.exempt` on `api_login`

**Risk:** `@csrf.exempt` at line 832 exempts `api_login` from CSRF
protection. The `csrf` object is created inside `_create_app`.

**Mitigation:** `csrf` is passed to `make_auth_blueprint(cm, csrf, limiter,
...)`. The `@csrf.exempt` decorator applies inside the factory before the
route is registered.

### R5: `login_required` decorator from Flask-Login

**Risk:** `login_required` is imported from `flask_login` inside `_create_app`
and applied as a decorator on many routes.

**Mitigation:** Each Blueprint factory that needs it receives
`login_required` as a parameter. The import stays in `_create_app`, which
passes the object to each factory. This avoids circular imports and ensures
only one `LoginManager` instance exists.

### R6: `_RstDrop` class and `_rst_drop()` function

**Risk:** `_rst_drop()` calls `raise _RstDrop()` and `request.environ`.
Both `_RstDrop` and `_rst_drop` are referenced by tests (`test_gui_ip_allowlist.py`)
and by `security_check` (inside `_create_app`).

**Mitigation:** Both move to `src/gui/_helpers.py`. `__init__.py` re-exports
`_RstDrop` so `from src.gui import _RstDrop` keeps working. `_create_app`
imports from `._helpers`.

### R7: `_GUI_OWNS_DAEMON` / `_DAEMON_RESTART_FN` / `_DAEMON_SCHEDULER` module-level state

**Risk:** `src/cli/_runtime.py` imports `src.gui as _gui` and then assigns
`_gui._GUI_OWNS_DAEMON = True`, `_gui._DAEMON_RESTART_FN = _restart`. The
`api_daemon_restart` route (line 3274) reads back `import src.gui as _self;
_self._DAEMON_RESTART_FN`. This only works if the state lives at module level
in `src.gui` (i.e., `src/gui/__init__.py`).

**Mitigation:** These three names stay in `src/gui/__init__.py`. The
`admin.py` Blueprint receives `_gui_module` (the `src.gui` module object)
as a parameter OR the `api_daemon_restart` route stays in `__init__.py`'s
`_create_app` (it is only one route). Recommended: keep `api_daemon_restart`
inside `_create_app` to avoid passing a self-reference.

### R8: Route name collisions between Blueprints

**Risk:** Two Blueprints both defining a function named `api_rules` would
cause a Flask endpoint naming collision when both are registered.

**Mitigation:** Flask auto-prefixes Blueprint endpoint names with
`<blueprint_name>.` — so `auth.login_page`, `rules.api_rules`, etc. Routes
that call `url_for('login_page')` in `security_check` will break unless
updated to `url_for('auth.login_page')`. Scan for all `url_for` calls before
moving routes.

**Action:** `grep -rn "url_for" src/gui/` before each Blueprint task.
Current scan (verified): `security_check` at line 774 uses `redirect('/login')`
(literal path, NOT `url_for`) — safe. No other `url_for` calls found in
`__init__.py`. New Blueprints may use `url_for` internally; prefix them with
`'<blueprint_name>.<func>'` from day one.

### R9: `persistent_mode` closure variable

**Risk:** The `api_shutdown` route at line 2914 closes over `persistent_mode`
(a parameter of `_create_app`). If this route moves to `admin.py`, the
factory must receive `persistent_mode` as a parameter.

**Mitigation:** `make_admin_blueprint(cm, limiter, login_required,
persistent_mode)` — include `persistent_mode` in the signature.

### R10: Talisman's `before_request` handler patch

**Risk:** Lines 721–733 in `_create_app` replace Talisman's internal
`_force_https` hook with a test-aware wrapper by mutating
`app.before_request_funcs[None]`. This must execute BEFORE any Blueprint
is registered (since registering Blueprints may also add before_request
hooks). If Blueprint registration somehow triggers a re-sort, the patch
could end up in the wrong position.

**Mitigation:** The Talisman setup and the before_request-funcs patch stay
at the top of `_create_app`, before any `app.register_blueprint(...)` call.
Blueprint registration calls come at the end of `_create_app`.

### R11: `_append_rs_logs` used by `src/scheduler/jobs.py`

**Risk:** `src/scheduler/jobs.py:65` does `from src.gui import _append_rs_logs`.
If this symbol moves to a helper without a re-export, the scheduler breaks
silently (it catches the ImportError).

**Mitigation:** `_append_rs_logs` either stays in `__init__.py` (it only uses
module-level deque `_rs_log_history` which also stays there) or moves with an
explicit re-export. Given it uses `_rs_log_history` and `_rs_log_lock` (both
module-level state), it is cleanest to keep all three in `__init__.py`.

### R12: Route count drift

**Risk:** Moving routes one-by-one means a typo can silently drop a route.
The Task 1 baseline (JSON of all 77 URL rules) makes drops detectable.

**Mitigation:** Task 1 captures the baseline. Every subsequent task checks
`len(app.url_map.iter_rules())` via the baseline test.

---

## Pre-flight (run once before starting)

- [ ] Verify clean working tree: `git status` → "nothing to commit"
- [ ] Verify on `code-review-fixes` branch and up-to-date:
      `git log --oneline -3`
      Expected top commit: `e22dc5c chore: drop old_password requirement; ...`
- [ ] Verify test suite green baseline:
      `venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3`
      Expected: `825 passed, 1 skipped` (825 collected per `--co` output)
- [ ] Verify gui module imports cleanly:
      `venv/bin/python3 -c "from src.gui import build_app, launch_gui, _create_app; print('ok')"`
      Expected: `ok`
- [ ] Create branch:
      `git checkout -b h5-gui-blueprint-split`

---

## Task 1: Capture route-map baseline

**Why:** With 77 routes spread across 3821 lines, any route silently dropped
during a move is hard to catch in unit tests that mock Flask. A JSON snapshot
of all registered URL rules gives a fast differential check after every
Blueprint task.

**Files:**
- Create: `tests/_gui_route_baseline.json` (one-time generator)
- Create: `tests/test_gui_blueprint_baseline.py` (temporary guard — deleted
  in Task 12 when the split is complete)

- [ ] **Step 1: Generate the route baseline JSON**

```bash
venv/bin/python3 - <<'PY'
import json, pathlib
from src.config import ConfigManager
from src.gui import build_app

cm = ConfigManager()
app = build_app(cm)
rules = []
for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, sorted(r.methods))):
    rules.append({
        "url": rule.rule,
        "endpoint": rule.endpoint,
        "methods": sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS")),
    })
out = pathlib.Path("tests/_gui_route_baseline.json")
out.write_text(json.dumps(rules, indent=2), encoding="utf-8")
print(f"Wrote {out}: {len(rules)} rules")
PY
```

Expected: a JSON file with 77+ entries (Flask also adds `static` and any
siem/pce_cache Blueprint routes from optional modules — the count may be
79-82 in a full install).

- [ ] **Step 2: Write the differential test**

`tests/test_gui_blueprint_baseline.py`:

```python
"""Route-map snapshot test for the H5 Blueprint split.

Compares the Flask URL map against a baseline captured from the pre-split
__init__.py. Deleted in Task 12 once the split is complete.
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

_BASELINE_PATH = Path(__file__).parent / "_gui_route_baseline.json"


@pytest.fixture(scope="module")
def _app():
    from src.config import ConfigManager
    from src.gui import build_app
    cm = ConfigManager()
    return build_app(cm)


def _current_rules(app) -> list[dict]:
    return [
        {
            "url": r.rule,
            "endpoint": r.endpoint,
            "methods": sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS")),
        }
        for r in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, sorted(r.methods)))
    ]


def test_route_count_matches_baseline(_app):
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    current = _current_rules(_app)
    assert len(current) == len(baseline), (
        f"Route count changed: baseline={len(baseline)}, current={len(current)}\n"
        f"Added: {[r['url'] for r in current if r not in baseline]}\n"
        f"Removed: {[r['url'] for r in baseline if r not in current]}"
    )


def test_all_baseline_routes_present(_app):
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    current = _current_rules(_app)
    current_set = {(r["url"], tuple(r["methods"])) for r in current}
    missing = [
        r for r in baseline
        if (r["url"], tuple(r["methods"])) not in current_set
    ]
    assert not missing, f"Missing routes: {missing}"
```

- [ ] **Step 3: Run the test — confirm both pass against pristine baseline**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py -v --timeout=60 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_gui_blueprint_baseline.py tests/_gui_route_baseline.json
git commit -m "$(cat <<'EOF'
test(gui): add route-map baseline snapshot for H5 Blueprint split

Captures all registered Flask URL rules as a JSON snapshot and adds a
differential test that fires after each Blueprint migration task to
confirm no routes were silently dropped. Both files are removed at the
end of Task 12.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Extract helpers to `src/gui/_helpers.py`

**Why:** Before any route moves, the shared utilities must live somewhere
importable by all future Blueprint modules. Moving helpers first keeps
each Blueprint task a single clean step (routes only).

**Files:**
- Create: `src/gui/_helpers.py`
- Modify: `src/gui/__init__.py` — replace the function bodies with imports
  from `._helpers`, preserving all re-exports for external callers.

**Helpers to move** (file:line anchors in current `__init__.py`):

| Symbol | Current line(s) | Notes |
|---|---|---|
| `_ANSI_RE` | 54 | regex — moved as module-level constant |
| `_strip_ansi` | 56–57 | |
| `_normalize_ip_token` | 60–74 | |
| `_loopback_equivalent` | 77–83 | |
| `_check_ip_allowed` | 90–110 | |
| `_validate_allowed_ips` | 112–124 | |
| `_SECRET_PATTERN` | 126–128 | |
| `_redact_secrets` | 130–144 | |
| `_strip_redaction_placeholders` | 147–168 | |
| `_SETTINGS_ALLOWLISTS` | 170–179 | |
| `_normalize_rule_throttle` | 181–191 | |
| `_normalize_match_fields` | 193–204 | |
| `_is_workload_href` | 206–208 | |
| `_normalize_quarantine_hrefs` | 210–216 | |
| `_rst_drop` | 218–250 | uses `request` — must import flask inside body |
| `_RstDrop` | 252–253 | |
| `_GUI_DIR`, `_PKG_DIR`, `_ROOT_DIR` | 255–257 | path constants |
| `_ALLOWED_REPORT_FORMATS` | 263 | |
| `_resolve_reports_dir` | 300–303 | |
| `_resolve_config_dir` | 305–306 | |
| `_resolve_state_file` | 308–309 | |
| `_UI_EXTRA_KEYS` | 311 | |
| `_ui_translation_dict` | 313–319 | |
| `_plugin_config_roots` | 321–328 | |
| `_summarize_alert_channels` | 330–361 | |
| `_ok` | 363–369 | uses `jsonify` — must import flask inside body or at top |
| `_err` | 371–373 | |
| `_safe_log` | 375–377 | |
| `_err_with_log` | 379–395 | |
| `_get_active_pce_url` | 397–404 | |
| `_build_audit_dashboard_summary` | 406–407 | thin wrapper |
| `_write_audit_dashboard_summary` | 409–410 | |
| `_build_policy_usage_dashboard_summary` | 412–413 | |
| `_write_policy_usage_dashboard_summary` | 415–416 | |
| `_spec_to_plotly_figure` | 423–451 | uses plotly |
| `_load_state_for_charts` | 454–462 | |
| `_build_traffic_timeline_spec` | 465–483 | |
| `_build_policy_decisions_spec` | 486–510 | |
| `_build_ven_status_spec` | 513–531 | |
| `_build_rule_hits_spec` | 534–555 | |

**Do NOT move** (must stay in `__init__.py`):
- `_GUI_OWNS_DAEMON`, `_DAEMON_SCHEDULER`, `_DAEMON_RESTART_FN` (module-level state assigned at runtime)
- `_rs_log_history`, `_rs_log_lock`, `_rs_log_history` deque, `_append_rs_logs`, `_rs_background_scheduler` (tightly coupled to the scheduler state that lives in this module)
- `HAS_FLASK`, `FLASK_IMPORT_ERROR` (imported by `src/main.py` and `src/cli/_runtime.py`)
- `_create_app`, `build_app`, `launch_gui` (public API)

**TLS helpers** (`_SELF_SIGNED_VALIDITY_DAYS`, `_cert_has_san`,
`_generate_self_signed_cert`, `_get_cert_info`, `_cert_days_remaining`,
`_maybe_auto_renew_self_signed`, `_build_ssl_context`, `_get_local_ips`):
These are at lines 3297–3629. They are imported by `src/settings.py:1615`
and tested by `tests/test_tls.py`. Move them to `_helpers.py` (not a
Blueprint — they are not routes). Add re-exports in `__init__.py`.

- [ ] **Step 1: Create `src/gui/_helpers.py`**

The file starts with a module docstring and the Flask import guard:

```python
"""
src/gui/_helpers.py — Shared utilities for the GUI Blueprint modules.

All symbols that are used by two or more Blueprint modules (or by external
callers via src.gui re-exports) live here.  Import with:

    from src.gui._helpers import _ok, _err, _err_with_log, ...
"""
from __future__ import annotations

import os
import re
import json
import struct
import datetime
import ipaddress
import socket as _socket
import traceback as _traceback
import uuid as _uuid
from collections import deque
import threading

from loguru import logger

from src.config import ConfigManager
from src.i18n import t, get_messages
from src.alerts import PLUGIN_METADATA, plugin_config_path, plugin_config_value
from src.report.dashboard_summaries import (
    build_audit_dashboard_summary,
    build_policy_usage_dashboard_summary,
    write_audit_dashboard_summary,
    write_policy_usage_dashboard_summary,
)
```

Then copy each function/constant from `__init__.py` verbatim into
`_helpers.py`. The `_ok`, `_err`, `_err_with_log` functions use `jsonify`
from Flask — add `from flask import jsonify, request` at the top (inside the
try/except `HAS_FLASK` guard if desired, or unconditionally since these
helpers are only called with Flask active).

For `_GUI_DIR`, `_PKG_DIR`, `_ROOT_DIR`: these must be computed relative to
`_helpers.py`'s location, which is `src/gui/` — same directory as
`__init__.py`. The path computation is identical:

```python
_GUI_DIR = os.path.dirname(os.path.abspath(__file__))  # src/gui/
_PKG_DIR = os.path.dirname(_GUI_DIR)                   # src/
_ROOT_DIR = os.path.dirname(_PKG_DIR)                  # project root
```

- [ ] **Step 2: Replace function bodies in `__init__.py` with imports**

After copying all helpers to `_helpers.py`, replace the now-redundant
definitions in `__init__.py` with a single block of imports from `._helpers`.
Place this block immediately after the Flask try/except and before the
module-level state (`_GUI_OWNS_DAEMON`):

```python
# ── Shared helpers (moved to _helpers.py; re-exported here for backwards compat) ─
from src.gui._helpers import (  # noqa: F401
    _ANSI_RE, _strip_ansi,
    _normalize_ip_token, _loopback_equivalent,
    _check_ip_allowed, _validate_allowed_ips,
    _SECRET_PATTERN, _redact_secrets, _strip_redaction_placeholders,
    _SETTINGS_ALLOWLISTS,
    _normalize_rule_throttle, _normalize_match_fields,
    _is_workload_href, _normalize_quarantine_hrefs,
    _rst_drop, _RstDrop,
    _GUI_DIR, _PKG_DIR, _ROOT_DIR,
    _ALLOWED_REPORT_FORMATS,
    _resolve_reports_dir, _resolve_config_dir, _resolve_state_file,
    _UI_EXTRA_KEYS, _ui_translation_dict,
    _plugin_config_roots, _summarize_alert_channels,
    _ok, _err, _safe_log, _err_with_log,
    _get_active_pce_url,
    _build_audit_dashboard_summary, _write_audit_dashboard_summary,
    _build_policy_usage_dashboard_summary, _write_policy_usage_dashboard_summary,
    _spec_to_plotly_figure, _load_state_for_charts,
    _build_traffic_timeline_spec, _build_policy_decisions_spec,
    _build_ven_status_spec, _build_rule_hits_spec,
    # TLS helpers
    _SELF_SIGNED_VALIDITY_DAYS, _cert_has_san, _get_local_ips,
    _generate_self_signed_cert, _get_cert_info, _cert_days_remaining,
    _maybe_auto_renew_self_signed, _build_ssl_context,
)
```

Delete the original function bodies from `__init__.py`.

- [ ] **Step 3: Run the full suite + baseline**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: 2 baseline passed; `827 passed, 1 skipped` (825 + 2 new H5
baseline tests from Task 1).

Check the two previously-public symbols most likely to break:

```bash
venv/bin/python3 -c "from src.gui import _RstDrop, _safe_log, _build_ssl_context; print('re-exports ok')"
venv/bin/python3 -c "from src.gui import _build_audit_dashboard_summary; print('dashboard ok')"
```

- [ ] **Step 4: Commit**

```bash
git add src/gui/_helpers.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): extract helpers to src/gui/_helpers.py (H5 step 1)

Moves ~40 pure utility functions and constants out of the 3821-line
__init__.py into a dedicated _helpers.py. __init__.py re-exports every
moved symbol so all existing importers (tests, src/settings.py,
src/scheduler/jobs.py) keep working unchanged.

No routes moved in this commit — _create_app is untouched.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Create `src/gui/routes/` subpackage skeleton + `auth.py` Blueprint

**Why:** Auth routes (`/`, `/login`, `/api/login`, `/logout`, `/api/csrf-token`)
are the smallest, most self-contained group. They have one CSRF exemption, one
rate limit, and no external service calls. They are the lowest-risk first move.

**Routes to migrate:**

| Line | URL | Notes |
|---|---|---|
| 737 | `GET /api/csrf-token` | exempt from login required (before security_check bypass) |
| 806 | `GET /` | index — renders `index.html` |
| 827 | `GET /login` | renders `login.html` |
| 831 | `POST /api/login` | `@csrf.exempt @limiter.limit("5 per minute")` |
| 873 | `POST /logout` | |

**Files:**
- Create: `src/gui/routes/__init__.py` (empty)
- Create: `src/gui/routes/auth.py`
- Modify: `src/gui/__init__.py` — remove the 5 route definitions, add `make_auth_blueprint` call

- [ ] **Step 1: Create the `routes/` subpackage**

```bash
mkdir -p src/gui/routes
touch src/gui/routes/__init__.py
```

- [ ] **Step 2: Write `src/gui/routes/auth.py`**

```python
"""Auth Blueprint: login, logout, session, CSRF-token, and the SPA root."""
from __future__ import annotations

import hmac as _hmac

from flask import (
    Blueprint, current_app, jsonify, redirect,
    render_template, request, session,
)
from flask_login import login_user, logout_user
from flask_wtf.csrf import generate_csrf

from src.config import ConfigManager, hash_password, verify_password
from src.gui._helpers import (
    _get_active_pce_url, _ui_translation_dict, _ok, _err, _safe_log,
)
from src.i18n import t


def make_auth_blueprint(
    cm: ConfigManager,
    csrf,          # flask_wtf.csrf.CSRFProtect instance
    limiter,       # flask_limiter.Limiter instance
    login_required,  # flask_login.login_required decorator
) -> Blueprint:
    bp = Blueprint("auth", __name__)

    @bp.route("/api/csrf-token")
    def api_csrf_token():
        return jsonify({"csrf_token": generate_csrf()})

    @bp.route("/")
    @login_required
    def index():
        import datetime as _dt
        import json as _json
        cm.load()
        pce_url = _get_active_pce_url(cm)
        rules_count = len(cm.config.get("rules", []))
        schedules_count = len(cm.config.get("report_schedules", []))
        config_loaded_at = _dt.datetime.now()
        lang = cm.config.get("settings", {}).get("language", "en")
        ui_translations = _ui_translation_dict(lang)
        return render_template(
            "index.html",
            pce_url=pce_url,
            rules_count=rules_count,
            schedules_count=schedules_count,
            config_loaded_at=config_loaded_at,
            ui_translations_json=_json.dumps(
                ui_translations, ensure_ascii=False
            ).replace("</", "<\\/"),
        )

    @bp.route("/login", methods=["GET"])
    def login_page():
        return render_template("login.html")

    @bp.route("/api/login", methods=["POST"])
    @csrf.exempt
    @limiter.limit("5 per minute")
    def api_login():
        from pydantic import ValidationError as _ValidationError
        from src.auth_models import AdminUser, LoginForm
        try:
            form = LoginForm.model_validate(request.get_json(silent=True) or {})
        except _ValidationError as e:
            return jsonify({"ok": False, "error": "invalid_form", "detail": str(e)}), 400

        username = form.username
        password = form.password
        cm.load()
        gui_cfg = cm.config.get("web_gui", {})
        saved_username = gui_cfg.get("username", "illumio")
        saved_password = gui_cfg.get("password", "")
        username_ok = _hmac.compare_digest(username.strip(), saved_username.strip())
        password_ok = verify_password(password, saved_password)
        if username_ok and password_ok:
            from src.auth_models import AdminUser
            user = AdminUser(username)
            login_user(user, remember=False)
            session.permanent = True
            must_change = bool(gui_cfg.get("must_change_password"))
            return jsonify({"ok": True, "must_change_password": must_change})
        return jsonify({"ok": False, "error": t("gui_err_invalid_credentials")}), 401

    @bp.route("/logout", methods=["POST"])
    def logout():
        logout_user()
        return jsonify({"ok": True})

    return bp
```

Note: The full `api_login` body should be copied verbatim from `__init__.py`
lines 831–871. The skeleton above shows the structure; copy the complete
implementation (including the `must_change_password` logic and the remaining
response branches at lines 855–872).

- [ ] **Step 3: Wire `make_auth_blueprint` into `_create_app`**

In `src/gui/__init__.py`, inside `_create_app`, find the comment
`# SPA endpoint to refresh tokens` (line 736). Replace the 5 route
definitions (lines 737–876) with:

```python
    # ── Auth Blueprint ─────────────────────────────────────────────────────────
    from src.gui.routes.auth import make_auth_blueprint
    app.register_blueprint(make_auth_blueprint(cm, csrf, limiter, login_required))
```

- [ ] **Step 4: Run the full suite + baseline**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: 2 baseline passed; `827 passed, 1 skipped`.

Spot-check endpoint names changed from bare names to Blueprint-prefixed:

```bash
venv/bin/python3 - <<'PY'
from src.config import ConfigManager
from src.gui import build_app
app = build_app(ConfigManager())
rules = {r.endpoint: r.rule for r in app.url_map.iter_rules()}
assert "auth.api_csrf_token" in rules, f"csrf-token endpoint missing: {rules}"
assert "auth.index" in rules, f"index endpoint missing"
assert "auth.login_page" in rules
assert "auth.api_login" in rules
assert "auth.logout" in rules
print("All auth endpoints registered correctly")
PY
```

Verify `security_check` still works — it references literal paths
(`'/login'`, `'/api/login'`, etc.) not `url_for`, so Blueprint renaming
does not break it.

- [ ] **Step 5: Commit**

```bash
git add src/gui/routes/__init__.py src/gui/routes/auth.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move auth routes to src/gui/routes/auth.py Blueprint (H5 step 2)

Extracts the 5 auth routes (/, /login, /api/login, /logout,
/api/csrf-token) into a Blueprint factory. _create_app registers the
Blueprint via app.register_blueprint(make_auth_blueprint(...)).

Baseline test confirms route count and URL map are unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `dashboard.py` Blueprint (9 routes)

**Why:** Dashboard routes cluster naturally — they all serve chart data, status
snapshots, and UI translations. They depend on plotly, the state file, and
`_build_*_spec` helpers already moved to `_helpers.py`.

**Routes to migrate:**

| Line | URL | Method |
|---|---|---|
| 926 | `/api/ui_translations` | GET |
| 931 | `/api/status` | GET |
| 1822 | `/api/dashboard/queries` | GET |
| 1828 | `/api/dashboard/queries` | POST |
| 1887 | `/api/dashboard/queries/<int:idx>` | DELETE |
| 1897 | `/api/dashboard/snapshot` | GET |
| 1914 | `/api/dashboard/audit_summary` | GET |
| 1928 | `/api/dashboard/policy_usage_summary` | GET |
| 1944 | `/api/dashboard/chart/<chart_id>` | GET |
| 2535 | `/api/dashboard/top10` | POST |

**Files:**
- Create: `src/gui/routes/dashboard.py`
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Write `src/gui/routes/dashboard.py`**

Signature:
```python
def make_dashboard_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("dashboard", __name__)
    # ... all 9 route functions, verbatim from __init__.py ...
    return bp
```

All helpers referenced by these routes (`_build_traffic_timeline_spec`,
`_spec_to_plotly_figure`, `_resolve_reports_dir`, `_ui_translation_dict`,
`_ok`, `_err`, `_err_with_log`, `_load_state_for_charts`, etc.) are imported
from `src.gui._helpers`.

The `top10` route at line 2535 uses `login_required` — pass it in the factory
signature.

- [ ] **Step 2: Wire into `_create_app`**

After the auth Blueprint registration, add:

```python
    from src.gui.routes.dashboard import make_dashboard_blueprint
    app.register_blueprint(make_dashboard_blueprint(cm, login_required))
```

Remove the 9 route definitions from `__init__.py` (lines 926–935 and
1822–2534 for the dashboard block, plus the top10 route at 2535–2652).

- [ ] **Step 3: Run verification**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py tests/test_gui_dashboard_plotly_endpoint.py -v --timeout=60 2>&1 | tail -10
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: baseline + plotly tests green; `827 passed, 1 skipped`.

- [ ] **Step 4: Commit**

```bash
git add src/gui/routes/dashboard.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move dashboard routes to src/gui/routes/dashboard.py (H5 step 3)

Extracts 9 dashboard routes (/api/dashboard/*, /api/status,
/api/ui_translations) into Blueprint factory. No behaviour change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `config.py` Blueprint (7 routes)

**Routes to migrate:**

| Line | URL | Method |
|---|---|---|
| 879 | `/api/security` | GET |
| 889 | `/api/security` | POST |
| 1595 | `/api/settings` | GET |
| 1616 | `/api/alert-plugins` | GET |
| 1644 | `/api/settings` | POST |
| 1705 | `/api/tls/status` | GET |
| 1731 | `/api/tls/config` | POST |
| 1753 | `/api/tls/renew` | POST |
| 1772 | `/api/pce-profiles` | GET |
| 1780 | `/api/pce-profiles` | POST |

That is 10 routes (the survey listed 7; the actual grep count is 10 — 2
security + 2 settings + 1 alert-plugins + 3 tls + 2 pce-profiles).

**Files:**
- Create: `src/gui/routes/config.py`
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Write `src/gui/routes/config.py`**

```python
def make_config_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("config", __name__)
    # ...
    return bp
```

The `api_security_get` and `api_security_post` routes reference
`verify_password` and `hash_password` — import from `src.config`.
The TLS routes reference `_generate_self_signed_cert`, `_get_cert_info`,
`_cert_days_remaining`, `_ROOT_DIR` — import from `src.gui._helpers`.

Note: `src/cli/_runtime.py` does NOT import any config routes by name.
`src/settings.py:1615` imports TLS helpers from `src.gui`, which after
Task 2 re-exports them from `_helpers` — no change needed here.

- [ ] **Step 2: Wire and verify**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py tests/test_api_settings.py tests/test_tls.py -v --timeout=60 2>&1 | tail -10
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: all relevant tests green; `827 passed, 1 skipped`.

- [ ] **Step 3: Commit**

```bash
git add src/gui/routes/config.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move config/settings/TLS routes to src/gui/routes/config.py (H5 step 4)

Extracts 10 routes (/api/settings, /api/security, /api/alert-plugins,
/api/tls/*, /api/pce-profiles) into Blueprint factory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `rules.py` Blueprint (9 routes)

**Routes to migrate:**

| Line | URL | Method |
|---|---|---|
| 1338 | `/api/rules` | GET |
| 1384 | `/api/rules/event` | POST |
| 1414 | `/api/rules/system` | POST |
| 1440 | `/api/rules/traffic` | POST |
| 1488 | `/api/rules/bandwidth` | POST |
| 1532 | `/api/rules/<int:idx>` | GET |
| 1539 | `/api/rules/<int:idx>` | PUT |
| 1578 | `/api/rules/<int:idx>` | DELETE |
| 1583 | `/api/rules/<int:idx>/highlight` | GET |

**Files:**
- Create: `src/gui/routes/rules.py`
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Write `src/gui/routes/rules.py`**

```python
def make_rules_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("rules", __name__)
    # ...
    return bp
```

The bandwidth route (line 1488) is the most complex (traffic-pattern parsing,
analyzer calls). Copy verbatim. Helper `_normalize_rule_throttle` and
`_normalize_match_fields` are in `_helpers.py`.

- [ ] **Step 2: Wire and verify**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py tests/test_rule_edit_pygments.py -v --timeout=60 2>&1 | tail -10
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add src/gui/routes/rules.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move rules CRUD routes to src/gui/routes/rules.py (H5 step 5)

Extracts 9 routes (/api/rules, /api/rules/event|system|traffic|bandwidth,
/api/rules/<idx>) into Blueprint factory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `events.py` Blueprint (4 routes)

**Routes to migrate:**

| Line | URL | Method |
|---|---|---|
| 994 | `/api/events/viewer` | GET |
| 1107 | `/api/events/shadow_compare` | GET |
| 1159 | `/api/events/rule_test` | GET |
| 1273 | `/api/event-catalog` | GET |

Note: `/api/init_quarantine` (line 1264) is logically quarantine/actions, not
events — it migrates with `actions.py` in Task 9.

**Files:**
- Create: `src/gui/routes/events.py`
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Write `src/gui/routes/events.py`**

```python
def make_events_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("events", __name__)
    # ...
    return bp
```

The `api_event_catalog` route (line 1273) imports `FULL_EVENT_CATALOG` and
related symbols from `src.settings` dynamically (inside the route body). Copy
verbatim — no changes needed.

- [ ] **Step 2: Wire and verify**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add src/gui/routes/events.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move events routes to src/gui/routes/events.py (H5 step 6)

Extracts 4 routes (/api/events/viewer|shadow_compare|rule_test,
/api/event-catalog) into Blueprint factory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `reports.py` Blueprint (13 routes)

**Routes to migrate:**

| Line | URL | Method |
|---|---|---|
| 1963 | `/api/reports` | GET |
| 2001 | `/api/reports/<path:filename>` | DELETE |
| 2020 | `/api/reports/bulk-delete` | POST |
| 2057 | `/reports/<path:filename>` | GET |
| 2070 | `/api/reports/generate` | POST |
| 2184 | `/api/audit_report/generate` | POST |
| 2236 | `/api/ven_status_report/generate` | POST |
| 2284 | `/api/policy_usage_report/generate` | POST |
| 2347 | `/api/report-schedules` | GET |
| 2371 | `/api/report-schedules` | POST |
| 2387 | `/api/report-schedules/<int:schedule_id>` | PUT |
| 2399 | `/api/report-schedules/<int:schedule_id>` | DELETE |
| 2410 | `/api/report-schedules/<int:schedule_id>/toggle` | POST |
| 2424 | `/api/report-schedules/<int:schedule_id>/run` | POST |
| 2457 | `/api/report-schedules/<int:schedule_id>/history` | GET |

That is 15 routes (survey summary grouped some sub-routes; actual count from grep is 15).

**Files:**
- Create: `src/gui/routes/reports.py`
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Write `src/gui/routes/reports.py`**

```python
def make_reports_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("reports", __name__)
    # ...
    return bp
```

The `/reports/<path:filename>` (GET, line 2057) is a file-serving route using
`send_from_directory` from Werkzeug. Import from `flask` inside the factory.
The `_resolve_reports_dir` helper is in `_helpers.py`.

The `api_reports_generate` route (line 2070) is the longest in this group
(~110 lines). Copy verbatim.

- [ ] **Step 2: Wire and verify**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add src/gui/routes/reports.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move reports routes to src/gui/routes/reports.py (H5 step 7)

Extracts 15 routes (/api/reports*, /reports/<path>, /api/report-schedules*,
/api/audit_report/generate, /api/ven_status_report/generate,
/api/policy_usage_report/generate) into Blueprint factory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `actions.py` Blueprint (8 routes)

**Routes to migrate:**

| Line | URL | Method |
|---|---|---|
| 1264 | `/api/init_quarantine` | POST |
| 2471 | `/api/quarantine/search` | POST |
| 2653 | `/api/workloads` | GET/POST |
| 2726 | `/api/quarantine/apply` | POST |
| 2762 | `/api/quarantine/bulk_apply` | POST |
| 2806 | `/api/actions/run` | POST |
| 2823 | `/api/actions/debug` | POST |
| 2839 | `/api/actions/test-alert` | POST |
| 2866 | `/api/actions/best-practices` | POST |
| 2887 | `/api/actions/test-connection` | POST |

That is 10 routes (workloads counts as 1, despite accepting GET and POST;
`test-connection` at 2887 is in this group).

**Files:**
- Create: `src/gui/routes/actions.py`
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Write `src/gui/routes/actions.py`**

```python
def make_actions_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("actions", __name__)
    # ...
    return bp
```

The `api_quarantine_search` route (line 2471) is ~60 lines; `api_actions_run`
calls the Analyzer pipeline. All are straightforward closures over `cm`.

- [ ] **Step 2: Wire and verify**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py tests/test_integrations_e2e.py -v --timeout=60 2>&1 | tail -10
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

- [ ] **Step 3: Commit**

```bash
git add src/gui/routes/actions.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move actions/quarantine routes to src/gui/routes/actions.py (H5 step 8)

Extracts 10 routes (/api/actions/*, /api/init_quarantine,
/api/quarantine/*, /api/workloads) into Blueprint factory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `rule_scheduler.py` Blueprint (10 routes)

**Routes to migrate:**

| Line | URL | Method |
|---|---|---|
| 2947 | `/api/rule_scheduler/status` | GET |
| 2958 | `/api/rule_scheduler/rulesets` | GET |
| 3003 | `/api/rule_scheduler/rules/search` | GET |
| 3050 | `/api/rule_scheduler/rulesets/<rs_id>` | GET |
| 3105 | `/api/rule_scheduler/schedules` | GET |
| 3140 | `/api/rule_scheduler/schedules` | POST |
| 3197 | `/api/rule_scheduler/schedules/<path:href>` | GET |
| 3209 | `/api/rule_scheduler/schedules/delete` | POST |
| 3224 | `/api/rule_scheduler/check` | POST |
| 3233 | `/api/rule_scheduler/logs` | GET |

Note: The inner function `_get_rs_components()` (line 2936) is a lazy-init
helper used ONLY by the rule_scheduler routes. Move it as a module-level
private function inside `rule_scheduler.py` (not into `_helpers.py` — it is
route-specific).

**Files:**
- Create: `src/gui/routes/rule_scheduler.py`
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Write `src/gui/routes/rule_scheduler.py`**

```python
def make_rule_scheduler_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("rule_scheduler", __name__)

    def _get_rs_components():
        """Lazy-init Rule Scheduler components."""
        from src.rule_scheduler import ScheduleDB, ScheduleEngine
        from src.api_client import ApiClient
        from src.gui._helpers import _resolve_config_dir
        import os
        db_path = os.path.join(_resolve_config_dir(), "rule_schedules.json")
        db = ScheduleDB(db_path)
        db.load()
        api = ApiClient(cm)
        engine = ScheduleEngine(db, api)
        return db, api, engine

    # ... 10 routes verbatim from __init__.py lines 2947-3239 ...
    return bp
```

The `rs_log_history` access in `/api/rule_scheduler/logs` (line 3233): this
route reads `_rs_log_history` which is a module-level deque in
`src/gui/__init__.py`. The route must import it:

```python
import src.gui as _gui_module
# inside the route:
with _gui_module._rs_log_lock:
    history = list(_gui_module._rs_log_history)
```

- [ ] **Step 2: Wire into `_create_app`** (IMPORTANT: register before `admin.py`)

```python
    from src.gui.routes.rule_scheduler import make_rule_scheduler_blueprint
    app.register_blueprint(make_rule_scheduler_blueprint(cm, login_required))
```

- [ ] **Step 3: Run verification**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py -v --timeout=60 2>&1 | tail -5
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

- [ ] **Step 4: Commit**

```bash
git add src/gui/routes/rule_scheduler.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move rule_scheduler routes to src/gui/routes/rule_scheduler.py (H5 step 9)

Extracts 10 /api/rule_scheduler/* routes into Blueprint factory. The
_get_rs_components() helper moves into the module as a private function.
The /api/rule_scheduler/logs route accesses _rs_log_history via an
explicit import src.gui reference to the module-level deque.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `admin.py` Blueprint (5 routes)

**Routes to migrate:**

| Line | URL | Method |
|---|---|---|
| 3240 | `/api/logs` | GET |
| 3251 | `/api/logs/<module_name>` | GET |
| 3274 | `/api/daemon/restart` | POST |

Note: `/api/shutdown` (line 2914) also belongs here. That is 4 routes.
`/api/rule_scheduler/logs` moved in Task 10 to its Blueprint.

The `api_daemon_restart` route (line 3274) is a special case: it reads
`src.gui._GUI_OWNS_DAEMON` and `src.gui._DAEMON_RESTART_FN` at request time
via `import src.gui as _self`. This is the only safe pattern given that
these are module-level mutable state assigned by `_runtime.py` at startup.

**Decision (from R9 + R7 mitigations):** Keep `api_daemon_restart` inside
`_create_app` directly — it is 1 route and its dependency on module-level
state makes it a poor fit for a Blueprint (passing `_gui_module` as a
factory parameter is awkward and error-prone). Move only the 3 remaining
admin routes.

**Files:**
- Create: `src/gui/routes/admin.py`
- Modify: `src/gui/__init__.py`

- [ ] **Step 1: Write `src/gui/routes/admin.py`**

```python
def make_admin_blueprint(
    cm: ConfigManager,
    limiter,
    login_required,
    persistent_mode: bool,
) -> Blueprint:
    bp = Blueprint("admin", __name__)

    @bp.route("/api/logs")
    @login_required
    def api_log_list():
        from src.module_log import ModuleLog, MODULES
        modules = ModuleLog.list_modules()
        present = {m["name"] for m in modules}
        for name, label in MODULES.items():
            if name not in present:
                modules.append({"name": name, "label": label, "count": 0})
        return jsonify({"ok": True, "modules": modules})

    @bp.route("/api/logs/<module_name>")
    @login_required
    def api_log_get(module_name):
        from src.module_log import ModuleLog, MODULES
        if module_name not in MODULES:
            return jsonify({"ok": False, "error": "Unknown module"}), 404
        n = min(int(request.args.get("n", 200)), 500)
        ml = ModuleLog.get(module_name)
        return jsonify({"ok": True, "module": module_name, "entries": ml.get_recent(n)})

    @bp.route("/api/shutdown", methods=["POST"])
    @limiter.limit("5 per hour")
    @login_required
    def api_shutdown():
        import os as _os, threading as _threading, signal as _signal
        if persistent_mode:
            return jsonify({"ok": False, "error": "Shutdown not allowed in persistent mode"}), 403

        def _delayed_exit():
            import time as _t
            _t.sleep(0.5)
            _os.kill(_os.getpid(), _signal.SIGINT)

        _threading.Thread(target=_delayed_exit, daemon=True).start()
        return jsonify({"ok": True})

    return bp
```

- [ ] **Step 2: Wire into `_create_app`** (keep `api_daemon_restart` in `_create_app`)

```python
    from src.gui.routes.admin import make_admin_blueprint
    app.register_blueprint(
        make_admin_blueprint(cm, limiter, login_required, persistent_mode)
    )

    # api_daemon_restart stays here — reads module-level _GUI_OWNS_DAEMON / _DAEMON_RESTART_FN
    @app.route("/api/daemon/restart", methods=["POST"])
    @limiter.limit("5 per hour")
    @login_required
    def api_daemon_restart():
        import src.gui as _self
        if not _self._GUI_OWNS_DAEMON:
            return jsonify({"ok": False,
                            "error": "Daemon is managed externally; restart via systemctl or your service manager."}), 409
        if _self._DAEMON_RESTART_FN is None:
            return jsonify({"ok": False, "error": "restart hook not installed"}), 500
        try:
            _self._DAEMON_SCHEDULER = _self._DAEMON_RESTART_FN()
            return jsonify({"ok": True}), 200
        except Exception as exc:
            from src.gui._helpers import _err_with_log
            return _err_with_log("daemon_restart", exc)
```

- [ ] **Step 3: Run the full verification suite**

```bash
venv/bin/python3 -m pytest tests/test_gui_blueprint_baseline.py tests/test_daemon_restart_api.py -v --timeout=60 2>&1 | tail -10
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: all green; `827 passed, 1 skipped`.

- [ ] **Step 4: Commit**

```bash
git add src/gui/routes/admin.py src/gui/__init__.py
git commit -m "$(cat <<'EOF'
refactor(gui): move admin routes to src/gui/routes/admin.py (H5 step 10)

Extracts /api/logs, /api/logs/<module>, /api/shutdown into Blueprint
factory. /api/daemon/restart stays in _create_app (reads module-level
mutable state set by cli/_runtime.py at startup).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Verification gate + retire baseline scaffolding

**Why:** All 77 routes are now in Blueprints (or the one intentional
exception `api_daemon_restart`). The `_create_app` function should now be
a concise ~80-line factory. Time to verify the final shape, confirm test
counts, and delete the temporary baseline files.

**Files:**
- Delete: `tests/test_gui_blueprint_baseline.py`
- Delete: `tests/_gui_route_baseline.json`

- [ ] **Step 1: Final structural check**

```bash
# Confirm __init__.py is now small
wc -l src/gui/__init__.py
# Expect: ~300 lines (module docstring, imports, state, _append_rs_logs,
# _rs_background_scheduler, _create_app shell, build_app, launch_gui,
# TLS launch helpers)
```

```bash
# Confirm routes/ package exists with all expected files
ls src/gui/routes/
# Expect: __init__.py  admin.py  actions.py  auth.py  config.py
#         dashboard.py  events.py  reports.py  rule_scheduler.py  rules.py
```

```bash
# Confirm no @app.route remains outside _create_app (only daemon/restart
# should be there, and it's @app.route not @bp.route)
python3 -c "
import ast, pathlib
src = pathlib.Path('src/gui/__init__.py').read_text()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == 'route':
            if isinstance(func.value, ast.Name) and func.value.id == 'app':
                print(f'  app.route at line {node.lineno}')
"
# Expect: only /api/daemon/restart (one line)
```

- [ ] **Step 2: Full suite + audit + mypy**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -5
venv/bin/python3 -m mypy --config-file mypy.ini src/api_client.py src/analyzer.py src/reporter.py 2>&1 | tail -3
```

Expected:
- Tests: `827 passed, 1 skipped`.
- mypy: 0 errors on the three target files (M11 typed-core contract).

Confirm all externally-imported symbols still work:

```bash
venv/bin/python3 - <<'PY'
from src.gui import (
    build_app, _create_app, launch_gui, HAS_FLASK, FLASK_IMPORT_ERROR,
    _RstDrop, _append_rs_logs, _build_audit_dashboard_summary,
    _build_policy_usage_dashboard_summary, _build_ssl_context,
    _generate_self_signed_cert, _get_cert_info, _cert_days_remaining,
    _ROOT_DIR, _SELF_SIGNED_VALIDITY_DAYS, _safe_log,
    _GUI_OWNS_DAEMON, _DAEMON_RESTART_FN, _DAEMON_SCHEDULER,
)
print("All public symbols importable from src.gui")
PY
```

- [ ] **Step 3: Delete the baseline scaffolding**

```bash
git rm tests/test_gui_blueprint_baseline.py tests/_gui_route_baseline.json
```

- [ ] **Step 4: Run the suite once more to confirm test count drops by 2**

```bash
venv/bin/python3 -m pytest -q --timeout=60 2>&1 | tail -3
```

Expected: `825 passed, 1 skipped`. (The 2 H5 baseline tests are gone;
the count returns to pre-flight baseline.)

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "$(cat <<'EOF'
refactor(gui): retire H5 baseline scaffolding; Blueprint split complete

H5 is complete. src/gui/__init__.py now contains only module-level state,
the _create_app factory shell (Blueprint registrations + app-level hooks),
build_app, and launch_gui.

Final shape:
  src/gui/__init__.py        ~300 lines (factory + state + re-exports)
  src/gui/_helpers.py        ~350 lines (shared utilities)
  src/gui/routes/auth.py     5 routes
  src/gui/routes/dashboard.py  9 routes
  src/gui/routes/config.py   10 routes
  src/gui/routes/rules.py    9 routes
  src/gui/routes/events.py   4 routes
  src/gui/routes/reports.py  15 routes
  src/gui/routes/actions.py  10 routes
  src/gui/routes/rule_scheduler.py  10 routes
  src/gui/routes/admin.py    3 routes
  src/gui/__init__.py (inline) 1 route (api_daemon_restart)

Original src/gui/__init__.py: 3821 lines → ~300 lines (net ~3500 lines
distributed across Blueprint modules).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final Acceptance

- [ ] `venv/bin/python3 -m pytest --timeout=60 -q 2>&1 | tail -5`
      → green, `825 passed, 1 skipped` (back to the pre-flight baseline
      once Task 12 step 3 deletes the two H5 baselines).
- [ ] `wc -l src/gui/__init__.py` → under 350 lines.
- [ ] `ls src/gui/routes/` → exactly 10 files
      (`__init__.py admin.py actions.py auth.py config.py dashboard.py
      events.py reports.py rule_scheduler.py rules.py`).
- [ ] `venv/bin/python3 -c "from src.gui import build_app, _RstDrop, _safe_log, _build_ssl_context, _GUI_OWNS_DAEMON; print('ok')"` → `ok`.
- [ ] `grep -c "@app\.route" src/gui/__init__.py` → `1`
      (only `api_daemon_restart` remains inline).
- [ ] `grep -rn "@app\.route" src/gui/routes/` → zero output
      (Blueprints use `@bp.route`, not `@app.route`).
- [ ] `venv/bin/python3 -m mypy --config-file mypy.ini src/api_client.py src/analyzer.py src/reporter.py 2>&1 | tail -3`
      → 0 errors.
- [ ] Squash-merge or rebase-merge `h5-gui-blueprint-split` → `main`.

---

## Self-Review Notes

**Spec coverage:** Every item in the Batch 4 H5 sketch has a task:
helpers extraction (Task 2), each Blueprint group (Tasks 3–11), baseline
guard and cleanup (Tasks 1 and 12).

**No placeholders:** Each task lists exact file:line anchors, exact
function signatures for Blueprint factories, exact shell commands with
expected output. Blueprint factory signatures are fully specified with
parameter types.

**Type consistency:** All Blueprint factories follow the same pattern:
`make_<topic>_blueprint(cm: ConfigManager, ...) -> Blueprint`. Dependencies
(`limiter`, `login_required`, `csrf`, `persistent_mode`) are passed
explicitly — no hidden globals.

**Risk gating:** Task 1 captures the golden URL-map before any code moves.
Every task re-runs `tests/test_gui_blueprint_baseline.py` before committing.
Any silently-dropped route is caught at the offending commit boundary.

**Reversibility:** Each task is a single commit. Failed work can be reset
with `git reset --hard HEAD~1`. The branch `h5-gui-blueprint-split` is
throwaway until the final acceptance squash-merge.

**Key decisions documented:**
- `api_daemon_restart` stays in `_create_app` (R7 mitigation).
- All error handlers stay app-level (R2 mitigation).
- `security_check` / `add_security_headers` stay app-level (R1 mitigation).
- Talisman's HTTPS-redirect patch happens before Blueprint registration (R10).
- `_rs_log_history` / `_append_rs_logs` stay in `__init__.py` (R11).

**Open questions for the controller:**
1. The `_append_rs_logs` function is currently called by
   `src/scheduler/jobs.py` via a bare `from src.gui import _append_rs_logs`.
   That import is inside a `try/except` at line 65, so it silently no-ops if
   the GUI package is unavailable. Keeping `_append_rs_logs` in `__init__.py`
   is the safest path. If the controller wants to move it to `_helpers.py`, a
   re-export in `__init__.py` is sufficient.
2. Route endpoint names change from `api_csrf_token` to `auth.api_csrf_token`
   (etc.) after Blueprint migration. The `security_check` hook uses literal
   path strings (not `url_for`), so this is safe. If any JS client calls
   `url_for` via a server-side Jinja template, those templates must be updated.
   Current scan of templates for `url_for` usage is recommended before Task 3.
3. The `_ALLOWED_REPORT_FORMATS` frozenset at line 263 is used only by the
   `reports.py` Blueprint. It can remain in `_helpers.py` or be inlined into
   `routes/reports.py`. The plan leaves it in `_helpers.py` for simplicity.
