# Accelerate Workload Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add row + bulk-bar "Accelerate" buttons to the Workload Search page that call the PCE `set_flow_reporting_frequency` endpoint, with a frontend-driven persistent mode.

**Architecture:** Backend stays stateless: a new `ApiClient` method auto-batches at 50, and a Flask route validates hrefs and forwards. Frontend handles persistent mode via `setInterval` (re-issues every 10 min), with a countdown bar. Unmanaged workloads are filtered/disabled in the UI.

**Tech Stack:** Python 3.12 / Flask / pytest, vanilla JS, Jinja2 templates. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-09-accelerate-workload-button-design.md`

---

## File Structure

| File | Type | Responsibility |
|---|---|---|
| `src/api_client.py` | modify | New `set_flow_reporting_frequency()` method (~line 617 after `search_workloads`) |
| `src/gui/routes/actions.py` | modify | New `/api/workloads/accelerate` route (after `api_quarantine_bulk_apply`, ~line 254) |
| `src/templates/index.html` | modify | Bulk-bar button (~line 547), modal `m-accelerate`, countdown bar |
| `src/static/js/quarantine.js` | modify | Row button cell update, `accelerateOne`, `openAccelerateModal`, `confirmAccelerate`, `cancelAccelerate`, countdown tick |
| `src/i18n_en.json` | modify | 11 new keys |
| `src/i18n_zh_TW.json` | modify | 11 new keys |
| `tests/test_api_client_accelerate.py` | create | Unit tests for `set_flow_reporting_frequency` |
| `tests/test_gui_accelerate.py` | create | Route tests for `/api/workloads/accelerate` |

---

## Task 1: ApiClient.set_flow_reporting_frequency

**Files:**
- Test: `tests/test_api_client_accelerate.py`
- Modify: `src/api_client.py` (add method after `search_workloads`, around line 617)

- [ ] **Step 1: Write failing tests**

Create `tests/test_api_client_accelerate.py`:

```python
"""Tests for ApiClient.set_flow_reporting_frequency."""
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


def _make_client() -> ApiClient:
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "k",
            "secret": "s",
            "verify_ssl": True,
        }
    }
    return ApiClient(cm)


class TestSetFlowReportingFrequency(unittest.TestCase):
    def test_empty_hrefs_returns_zero(self):
        client = _make_client()
        client._api_post = MagicMock()
        success, fail = client.set_flow_reporting_frequency([])
        self.assertEqual((success, fail), (0, 0))
        client._api_post.assert_not_called()

    def test_single_batch_under_50(self):
        client = _make_client()
        client._api_post = MagicMock(return_value=(204, None))
        hrefs = [f"/orgs/1/workloads/{i}" for i in range(10)]

        success, fail = client.set_flow_reporting_frequency(hrefs)

        self.assertEqual((success, fail), (10, 0))
        self.assertEqual(client._api_post.call_count, 1)
        endpoint, payload = client._api_post.call_args[0][0], client._api_post.call_args[0][1]
        self.assertEqual(endpoint, "/orgs/1/workloads/set_flow_reporting_frequency")
        self.assertEqual(payload, {"workloads": [{"href": h} for h in hrefs]})

    def test_batches_at_50_boundary(self):
        client = _make_client()
        client._api_post = MagicMock(return_value=(200, None))
        hrefs = [f"/orgs/1/workloads/{i}" for i in range(125)]

        success, fail = client.set_flow_reporting_frequency(hrefs)

        self.assertEqual((success, fail), (125, 0))
        self.assertEqual(client._api_post.call_count, 3)
        sizes = [len(call.args[1]["workloads"]) for call in client._api_post.call_args_list]
        self.assertEqual(sizes, [50, 50, 25])

    def test_failure_status_counts_as_fail(self):
        client = _make_client()
        client._api_post = MagicMock(return_value=(403, None))
        hrefs = [f"/orgs/1/workloads/{i}" for i in range(5)]

        success, fail = client.set_flow_reporting_frequency(hrefs)

        self.assertEqual((success, fail), (0, 5))

    def test_partial_failure_across_batches(self):
        client = _make_client()
        client._api_post = MagicMock(side_effect=[(204, None), (500, None)])
        hrefs = [f"/orgs/1/workloads/{i}" for i in range(60)]

        success, fail = client.set_flow_reporting_frequency(hrefs)

        self.assertEqual((success, fail), (50, 10))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_client_accelerate.py -v`
Expected: 5 tests FAIL with `AttributeError: 'ApiClient' object has no attribute 'set_flow_reporting_frequency'`

- [ ] **Step 3: Add the method**

In `src/api_client.py`, immediately after the `search_workloads` method (currently ends around line 617), add:

```python
    def set_flow_reporting_frequency(self, hrefs: list[str]) -> tuple[int, int]:
        """Increase traffic update rate (a.k.a. flow reporting frequency) for
        the given workload hrefs.

        PCE caps each request at 50 workloads, so we auto-batch.
        Returns (success_count, fail_count) by batch size.
        Effect on PCE is temporary (~10 min); caller must re-issue to sustain.
        """
        if not hrefs:
            return 0, 0
        org = self.api_cfg["org_id"]
        endpoint = f"/orgs/{org}/workloads/set_flow_reporting_frequency"
        success = 0
        fail = 0
        for i in range(0, len(hrefs), 50):
            batch = hrefs[i:i + 50]
            payload = {"workloads": [{"href": h} for h in batch]}
            try:
                status, _ = self._api_post(endpoint, payload, timeout=15)
                if status in (200, 201, 204):
                    success += len(batch)
                else:
                    fail += len(batch)
                    logger.error(
                        f"set_flow_reporting_frequency batch failed: status={status}"
                    )
            except Exception as e:
                fail += len(batch)
                logger.error(f"set_flow_reporting_frequency batch error: {e}")
        return success, fail
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api_client_accelerate.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_client_accelerate.py src/api_client.py
git commit -m "feat(api): add set_flow_reporting_frequency with 50-href batching"
```

---

## Task 2: i18n keys

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`

- [ ] **Step 1: Add 11 new keys to `src/i18n_en.json`**

Append the following key/value pairs into `src/i18n_en.json` (preserve existing JSON structure; insert near other `gui_*` keys, e.g., next to `gui_btn_isolate`):

```json
"gui_btn_accelerate": "⚡ Accelerate",
"gui_accel_unmanaged_tip": "VEN not installed",
"gui_accel_bulk_btn": "⚡ Accelerate Selected",
"gui_accel_modal_title": "Accelerate Workloads",
"gui_accel_modal_summary": "{total} selected, {managed} managed, {skipped} will be skipped.",
"gui_accel_duration": "Duration",
"gui_accel_single": "Single shot",
"gui_accel_running_label": "Accelerating",
"gui_accel_started": "Accelerating {n} workloads",
"gui_accel_done": "Accelerated",
"gui_accel_no_targets": "No valid workloads to accelerate."
```

- [ ] **Step 2: Add the same keys to `src/i18n_zh_TW.json`** (preserve JSON structure):

```json
"gui_btn_accelerate": "⚡ 加速",
"gui_accel_unmanaged_tip": "VEN 未安裝",
"gui_accel_bulk_btn": "⚡ 加速所選",
"gui_accel_modal_title": "加速工作負載",
"gui_accel_modal_summary": "已選 {total}，可加速 {managed}，將略過 {skipped}。",
"gui_accel_duration": "持續時長",
"gui_accel_single": "單次",
"gui_accel_running_label": "加速中",
"gui_accel_started": "已開始加速 {n} 個工作負載",
"gui_accel_done": "加速已套用",
"gui_accel_no_targets": "沒有可加速的工作負載。"
```

- [ ] **Step 3: Run i18n parity test to confirm both files contain the same keys**

Run: `pytest tests/test_i18n_strings_parity.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/i18n_en.json src/i18n_zh_TW.json
git commit -m "i18n(accel): add accelerate-workload UI strings (en + zh_TW)"
```

---

## Task 3: Flask route /api/workloads/accelerate

**Files:**
- Test: `tests/test_gui_accelerate.py`
- Modify: `src/gui/routes/actions.py` (add route after `api_quarantine_bulk_apply`, ~line 254)

- [ ] **Step 1: Write failing tests**

Create `tests/test_gui_accelerate.py`:

```python
"""Tests for /api/workloads/accelerate route."""
from tests._helpers import _csrf


def _login(client):
    login = client.post(
        '/api/login',
        json={"username": "admin", "password": "testpass"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
    )
    assert login.status_code == 200
    return _csrf(login)


def test_accelerate_rejects_empty_hrefs(client):
    csrf = _login(client)
    r = client.post(
        '/api/workloads/accelerate',
        json={"hrefs": [], "duration_minutes": 0},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf},
    )
    assert r.status_code == 200
    assert r.json["ok"] is False
    assert "no" in r.json["error"].lower() or "valid" in r.json["error"].lower()


def test_accelerate_filters_invalid_hrefs(client, monkeypatch):
    csrf = _login(client)
    captured = {}

    def fake(self, hrefs):
        captured["hrefs"] = list(hrefs)
        return len(hrefs), 0

    monkeypatch.setattr(
        "src.api_client.ApiClient.set_flow_reporting_frequency", fake
    )

    r = client.post(
        '/api/workloads/accelerate',
        json={
            "hrefs": [
                "/orgs/1/workloads/aaa",
                "/orgs/1/labels/99",        # invalid: not a workload href
                "",                          # invalid: empty
                "/orgs/1/workloads/bbb",
            ],
            "duration_minutes": 30,
        },
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf},
    )
    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["success"] == 2
    assert r.json["failed"] == 0
    assert r.json["skipped_invalid"] == 2
    assert captured["hrefs"] == ["/orgs/1/workloads/aaa", "/orgs/1/workloads/bbb"]


def test_accelerate_bubbles_partial_failure(client, monkeypatch):
    csrf = _login(client)
    monkeypatch.setattr(
        "src.api_client.ApiClient.set_flow_reporting_frequency",
        lambda self, hrefs: (3, 1),
    )

    r = client.post(
        '/api/workloads/accelerate',
        json={
            "hrefs": [f"/orgs/1/workloads/{i}" for i in range(4)],
            "duration_minutes": 0,
        },
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf},
    )
    assert r.status_code == 200
    assert r.json["ok"] is True
    assert r.json["success"] == 3
    assert r.json["failed"] == 1
    assert r.json["skipped_invalid"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gui_accelerate.py -v`
Expected: 3 tests FAIL with 404 / route not found.

- [ ] **Step 3: Add the route**

In `src/gui/routes/actions.py`, locate the `api_quarantine_bulk_apply` function (currently ends with `return _err_with_log("quarantine_bulk_apply", e)` around line 254). Immediately after its closing block (and before `@bp.route('/api/actions/run', methods=['POST'])`), insert:

```python
    @bp.route('/api/workloads/accelerate', methods=['POST'])
    def api_workloads_accelerate():
        """Increase traffic update rate for the given workload hrefs.

        Backend is stateless: it issues exactly one PCE call per request.
        Persistent mode (re-issue every 10 min) is handled by the frontend
        via setInterval. Invalid hrefs are dropped and counted in
        skipped_invalid.
        """
        d = request.json or {}
        raw_hrefs = d.get('hrefs', []) or []
        duration = int(d.get('duration_minutes', 0) or 0)  # logged only
        hrefs = [h for h in raw_hrefs if _is_workload_href(h)]
        skipped_invalid = len(raw_hrefs) - len(hrefs)

        if not hrefs:
            return jsonify({"ok": False, "error": t("gui_accel_no_targets")})

        try:
            from src.api_client import ApiClient
            api = ApiClient(cm)
            success, fail = api.set_flow_reporting_frequency(hrefs)
            try:
                from src.module_log import ModuleLog as _ML
                _ML.get("actions").info(
                    f"Accelerate: success={success}, fail={fail}, "
                    f"skipped_invalid={skipped_invalid}, duration_minutes={duration}"
                )
            except Exception:
                pass  # audit-log best-effort, must not block primary action
            return jsonify({
                "ok": True,
                "success": success,
                "failed": fail,
                "skipped_invalid": skipped_invalid,
            })
        except Exception as e:
            return _err_with_log("workloads_accelerate", e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gui_accelerate.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_accelerate.py src/gui/routes/actions.py
git commit -m "feat(gui): add /api/workloads/accelerate route (stateless, validates hrefs)"
```

---

## Task 4: Frontend — row button + accelerateOne handler

**Files:**
- Modify: `src/static/js/quarantine.js` (renderQwPage row template, ~line 522-537; add `accelerateOne` near other handlers)

- [ ] **Step 1: Update the Actions cell in `renderQwPage()`**

Find this block in `src/static/js/quarantine.js` (around line 522):

```js
    html += `<tr>
          <td style="text-align:center;"><input type="checkbox" class="qw-chk" value="${href}"></td>
          <td>
            <div style="display:flex;align-items:center;">
              ${statusDot} <strong style="font-size:0.95rem;">${escapeHtml(w.name || w.hostname)}</strong>
            </div>
            <div style="font-size:10px;color:var(--dim);margin-top:2px;margin-left:14px;">${escapeHtml(w.hostname)}</div>
          </td>
          <td><span style="font-size:11px; color:${w.managed ? 'var(--success)' : 'var(--dim)'}; font-weight:600;">${mgmtText}</span></td>
          <td>${ipStr}</td>
          <td style="font-size:11px;">${labelsHtml || `<span style="color:var(--dim);font-size:10px;">${_t('gui_no_labels')}</span>`}</td>
          <td>
            <button class="btn btn-danger btn-sm" onclick="openQuarantineModal('${href}')"><span data-i18n="gui_btn_isolate">${_t('gui_btn_isolate')}</span></button>
            ${hasQuarantine ? `<span style="font-size:10px;color:var(--danger);font-weight:bold;margin-left:8px;">${_t('gui_isolated')}</span>` : ''}
          </td>
        </tr>`;
```

Replace it with:

```js
    const isManaged = w.managed === true;
    const accelLabel = escapeHtml((w.hostname || w.name || href).replace(/'/g, "\\'"));
    const accelBtn = isManaged
      ? `<button class="btn btn-secondary btn-sm" style="margin-left:6px;" onclick="accelerateOne('${href}','${accelLabel}')">${_t('gui_btn_accelerate')}</button>`
      : `<button class="btn btn-secondary btn-sm" style="margin-left:6px;" disabled title="${_t('gui_accel_unmanaged_tip')}">${_t('gui_btn_accelerate')}</button>`;

    html += `<tr>
          <td style="text-align:center;"><input type="checkbox" class="qw-chk" value="${href}" data-managed="${isManaged ? '1' : '0'}"></td>
          <td>
            <div style="display:flex;align-items:center;">
              ${statusDot} <strong style="font-size:0.95rem;">${escapeHtml(w.name || w.hostname)}</strong>
            </div>
            <div style="font-size:10px;color:var(--dim);margin-top:2px;margin-left:14px;">${escapeHtml(w.hostname)}</div>
          </td>
          <td><span style="font-size:11px; color:${w.managed ? 'var(--success)' : 'var(--dim)'}; font-weight:600;">${mgmtText}</span></td>
          <td>${ipStr}</td>
          <td style="font-size:11px;">${labelsHtml || `<span style="color:var(--dim);font-size:10px;">${_t('gui_no_labels')}</span>`}</td>
          <td>
            <button class="btn btn-danger btn-sm" onclick="openQuarantineModal('${href}')"><span data-i18n="gui_btn_isolate">${_t('gui_btn_isolate')}</span></button>
            ${accelBtn}
            ${hasQuarantine ? `<span style="font-size:10px;color:var(--danger);font-weight:bold;margin-left:8px;">${_t('gui_isolated')}</span>` : ''}
          </td>
        </tr>`;
```

(Two changes: added `data-managed` to the checkbox so the bulk modal can compute skip count without re-fetching; appended `accelBtn` next to the Isolate button.)

- [ ] **Step 2: Add `accelerateOne` handler near other workload handlers**

Append to `src/static/js/quarantine.js` (end of file is fine):

```js
// --- Accelerate (Increase Traffic Update Rate) ---

async function accelerateOne(href, label) {
  try {
    const r = await fetch('/api/workloads/accelerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hrefs: [href], duration_minutes: 0 }),
    }).then(res => res.json());
    if (!r.ok) throw new Error(r.error || 'failed');
    if (typeof toast === 'function') {
      toast(_t('gui_accel_done') + ': ' + label);
    } else {
      console.info('[accelerate] done:', label);
    }
  } catch (e) {
    if (typeof toast === 'function') {
      toast(_t('gui_rs_error_prefix') + ': ' + e.message, 'error');
    } else {
      console.error('[accelerate] failed:', e.message);
    }
  }
}
```

(Defensive `typeof toast` check — `toast()` may or may not exist depending on which JS modules are loaded; falls back to console.)

- [ ] **Step 3: Smoke test**

Start the GUI: `python illumio-ops.py gui` (or however the local dev server is started in this repo) and:

1. Navigate to Traffic & Workloads → Workloads tab.
2. Search a workload that you know is managed; verify the new "⚡ Accelerate" button is enabled.
3. Search a known unmanaged workload; verify the button is disabled and hovering shows "VEN not installed".
4. Click the button on the managed workload. Verify:
   - Network tab shows `POST /api/workloads/accelerate` with `{"hrefs":["..."], "duration_minutes":0}` returning `{"ok": true, "success": 1, ...}`.
   - PCE event log shows a `workloads.flow_reporting_frequency_updated` entry within seconds.

- [ ] **Step 4: Commit**

```bash
git add src/static/js/quarantine.js
git commit -m "feat(gui): row-level Accelerate button on Workload Search"
```

---

## Task 5: Frontend — bulk-bar button, modal, countdown bar (HTML)

**Files:**
- Modify: `src/templates/index.html` (add to bulk-bar around line 543; add modal + countdown bar near other modals)

- [ ] **Step 1: Add Accelerate button to bulk-bar**

Find this block in `src/templates/index.html` (around line 538-548):

```html
  <!-- Floating Bulk Quarantine Action Bar -->
  <div class="floating-action-bar" id="bulk-bar">
    <div style="color:var(--fg); font-size:1rem;">
      <span data-i18n="gui_selected">Selected</span> <span class="sel-count" id="bulk-sel-count">0</span> <span data-i18n="gui_workloads">workloads</span>
    </div>
    <button class="btn btn-danger" data-action="openQuarantineModal" data-args='[null, true]' data-i18n="gui_q_apply">
      <svg class="icon">
        <use href="#icon-alert"></use>
      </svg> Apply Quarantine
    </button>
  </div>
```

Replace with:

```html
  <!-- Floating Bulk Quarantine Action Bar -->
  <div class="floating-action-bar" id="bulk-bar">
    <div style="color:var(--fg); font-size:1rem;">
      <span data-i18n="gui_selected">Selected</span> <span class="sel-count" id="bulk-sel-count">0</span> <span data-i18n="gui_workloads">workloads</span>
    </div>
    <button class="btn btn-danger" data-action="openQuarantineModal" data-args='[null, true]' data-i18n="gui_q_apply">
      <svg class="icon">
        <use href="#icon-alert"></use>
      </svg> Apply Quarantine
    </button>
    <button class="btn btn-secondary" data-action="openAccelerateModal" data-i18n="gui_accel_bulk_btn">
      <svg class="icon">
        <use href="#icon-activity"></use>
      </svg> ⚡ Accelerate Selected
    </button>
  </div>
```

- [ ] **Step 2: Add `m-accelerate` modal**

Search for an existing modal in `index.html` (e.g., search for `id="m-quarantine"` or any `class="modal"` element). Add the following modal block immediately after the closing tag of one such existing modal (placement is non-functional as long as it's at the same DOM depth):

```html
  <div class="modal" id="m-accelerate" role="dialog" aria-modal="true">
    <div class="modal-card">
      <h3 data-i18n="gui_accel_modal_title">Accelerate Workloads</h3>
      <p id="accel-summary" style="font-size:0.9rem;color:var(--dim);margin-bottom:12px;"></p>
      <fieldset style="margin-bottom:12px;">
        <legend data-i18n="gui_accel_duration">Duration</legend>
        <label style="display:block;margin:4px 0;"><input type="radio" name="accel-dur" value="0" checked> <span data-i18n="gui_accel_single">Single shot</span></label>
        <label style="display:block;margin:4px 0;"><input type="radio" name="accel-dur" value="30"> 30 min</label>
        <label style="display:block;margin:4px 0;"><input type="radio" name="accel-dur" value="60"> 60 min</label>
        <label style="display:block;margin:4px 0;"><input type="radio" name="accel-dur" value="120"> 120 min</label>
      </fieldset>
      <div class="modal-actions" style="display:flex;gap:8px;justify-content:flex-end;">
        <button class="btn btn-secondary" data-action="closeModal" data-args='["m-accelerate"]' data-i18n="gui_cancel">Cancel</button>
        <button class="btn btn-primary" data-action="confirmAccelerate" data-i18n="gui_confirm">Confirm</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 3: Add countdown floating bar**

Append immediately after the `m-accelerate` modal (or near the existing `bulk-bar`):

```html
  <div class="floating-action-bar" id="accel-countdown" style="display:none;">
    <span style="color:var(--fg); font-size:0.95rem;">
      🟢 <span data-i18n="gui_accel_running_label">Accelerating</span>
      <strong id="accel-count">0</strong> —
      <span id="accel-remaining" style="font-variant-numeric:tabular-nums;">--:--</span>
    </span>
    <button class="btn btn-sm btn-secondary" data-action="cancelAccelerate" data-i18n="gui_cancel">Cancel</button>
  </div>
```

- [ ] **Step 4: Smoke test (visual only — JS handlers come in Task 6)**

Reload the page; verify no template parse errors and the new modal/countdown bar are NOT visible by default (modal needs `.show` class; countdown has `display:none`).

- [ ] **Step 5: Commit**

```bash
git add src/templates/index.html
git commit -m "feat(gui): bulk-bar Accelerate button, m-accelerate modal, countdown bar"
```

---

## Task 6: Frontend — bulk handler, setInterval, countdown tick

**Files:**
- Modify: `src/static/js/quarantine.js` (append handlers)

- [ ] **Step 1: Append bulk handlers**

Append to `src/static/js/quarantine.js` (after `accelerateOne` from Task 4):

```js
// --- Bulk Accelerate state (browser-tab-bound) ---
let _accel_timer = null;       // 10-minute re-issue interval
let _accel_tick = null;        // 1-second display tick
let _accel_endTs = 0;          // epoch ms when persistent mode should stop
let _accel_hrefs = [];         // managed hrefs to send each tick

function openAccelerateModal() {
  const checked = Array.from(document.querySelectorAll('.qw-chk:checked'));
  const all = checked.map(c => ({
    href: c.value,
    managed: c.dataset.managed === '1',
  }));
  const managed = all.filter(x => x.managed);
  const skipped = all.length - managed.length;

  const summary = (_t('gui_accel_modal_summary') || '')
    .replace('{total}', all.length)
    .replace('{managed}', managed.length)
    .replace('{skipped}', skipped);
  const sumEl = document.getElementById('accel-summary');
  if (sumEl) sumEl.textContent = summary;

  _accel_hrefs = managed.map(x => x.href);
  document.getElementById('m-accelerate').classList.add('show');
}

async function _fireAccelerate(durationMinutes) {
  try {
    const r = await fetch('/api/workloads/accelerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hrefs: _accel_hrefs, duration_minutes: durationMinutes }),
    }).then(res => res.json());
    if (!r.ok) throw new Error(r.error || 'failed');
    return r;
  } catch (e) {
    if (typeof toast === 'function') {
      toast(_t('gui_rs_error_prefix') + ': ' + e.message, 'error');
    } else {
      console.error('[accelerate] failed:', e.message);
    }
    return { ok: false };
  }
}

async function confirmAccelerate() {
  const dur = parseInt(
    document.querySelector('input[name="accel-dur"]:checked').value, 10
  );
  closeModal('m-accelerate');
  if (_accel_hrefs.length === 0) return;

  await _fireAccelerate(dur);
  if (typeof toast === 'function') {
    toast(_t('gui_accel_started').replace('{n}', _accel_hrefs.length));
  }

  if (dur > 0) {
    cancelAccelerate();   // clear any prior run before starting a new one
    _accel_endTs = Date.now() + dur * 60_000;
    _accel_timer = setInterval(() => {
      if (Date.now() >= _accel_endTs) { cancelAccelerate(); return; }
      _fireAccelerate(dur);
    }, 600_000);  // every 10 minutes
    _showAccelCountdown();
  }
}

function cancelAccelerate() {
  if (_accel_timer) { clearInterval(_accel_timer); _accel_timer = null; }
  if (_accel_tick) { clearInterval(_accel_tick); _accel_tick = null; }
  _accel_endTs = 0;
  const bar = document.getElementById('accel-countdown');
  if (bar) bar.style.display = 'none';
}

function _showAccelCountdown() {
  const bar = document.getElementById('accel-countdown');
  const countEl = document.getElementById('accel-count');
  const remEl = document.getElementById('accel-remaining');
  if (!bar || !countEl || !remEl) return;

  countEl.textContent = String(_accel_hrefs.length);
  bar.style.display = 'flex';

  const fmt = (ms) => {
    const total = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };
  remEl.textContent = fmt(_accel_endTs - Date.now());
  _accel_tick = setInterval(() => {
    const left = _accel_endTs - Date.now();
    if (left <= 0) { cancelAccelerate(); return; }
    remEl.textContent = fmt(left);
  }, 1000);
}
```

- [ ] **Step 2: No dispatcher registration needed**

The repo's `src/static/js/_event_dispatcher.js` resolves `data-action="<name>"` via `window[name]`, so any global function in `quarantine.js` is automatically callable. The three new functions (`openAccelerateModal`, `confirmAccelerate`, `cancelAccelerate`) are top-level in `quarantine.js`, so no allow-list edit is required. Skip this step.

- [ ] **Step 3: Smoke test — single-shot bulk**

1. GUI: Workload Search → search managed workloads → tick 2-3 boxes.
2. Click "⚡ Accelerate Selected" in the bulk-bar.
3. Modal opens. Summary line shows correct counts. Leave "Single shot" selected. Click Confirm.
4. Network tab: one POST to `/api/workloads/accelerate` with `duration_minutes: 0`.
5. No countdown bar appears.
6. PCE event log: one `workloads.flow_reporting_frequency_updated` event per affected workload.

- [ ] **Step 4: Smoke test — persistent (use 30 min, verify first re-issue)**

1. Repeat Step 3 but pick "30 min" radio. Click Confirm.
2. Countdown bar appears bottom-right showing `30:00` ticking down.
3. Wait ~10 minutes; verify a second POST is sent (Network tab) and PCE event log shows a second event.
4. Click Cancel on the countdown bar. Bar disappears. No more requests fire (verify by waiting another minute).

- [ ] **Step 5: Smoke test — mixed managed/unmanaged**

1. Search a query that returns both managed and unmanaged workloads.
2. Tick all of them. Click Accelerate Selected.
3. Modal summary shows e.g. "5 selected, 3 managed, 2 will be skipped."
4. Confirm; backend receives only the 3 managed hrefs.

- [ ] **Step 6: Commit**

```bash
git add src/static/js/quarantine.js
git commit -m "feat(gui): bulk Accelerate with persistent mode and countdown"
```

---

## Task 7: End-to-end verification

**Files:** none (verification-only)

- [ ] **Step 1: Run full backend test suite**

Run: `pytest tests/test_api_client_accelerate.py tests/test_gui_accelerate.py tests/test_i18n_strings_parity.py -v`
Expected: all PASS.

- [ ] **Step 2: Verify no regressions in adjacent tests**

Run: `pytest tests/test_gui_quarantine.py tests/test_api_client.py -v`
Expected: PASS (these touch the same files we modified).

- [ ] **Step 3: Lint check (only if the repo runs one in CI)**

Run: `python -m mypy src/api_client.py src/gui/routes/actions.py` if mypy is part of CI. Otherwise skip.

- [ ] **Step 4: Final manual smoke**

Re-run the three smoke scenarios from Task 6 (single-shot bulk, persistent, mixed) plus the row-level button from Task 4 to confirm no integration regressions.

- [ ] **Step 5: Commit nothing (verification only)**

If everything is green, the feature is complete. If a regression appears, file a follow-up task — do not amend the published commits.

---

## Out of Scope (per spec §9)

- Server-side persistent mode with `accelerate_jobs` table.
- Custom minute input beyond `0/30/60/120`.
- Per-workload countdown chip in each row.

These are deferred to a v2 if the v1 proves valuable.
