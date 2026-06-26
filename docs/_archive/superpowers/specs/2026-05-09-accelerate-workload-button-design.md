# Accelerate Workload Button — Design Spec

- Date: 2026-05-09
- Owner: harry
- Status: Approved (brainstorming phase)

## 1. Goal

Add an "Accelerate" action to the Workload Search page so the user can raise the
traffic-update frequency on selected VEN-managed workloads (the same effect as
the PCE Web UI's *Increase Traffic Update Rate* command, and `workloader
increase-ven-update-rate`). Two trigger surfaces:

1. Per-row button next to *Isolate*.
2. Bulk button in the floating action bar for multi-selection.

Persistent mode (re-issue every 10 min for N min) is supported via a browser
`setInterval`. The backend stays stateless.

## 2. Non-Goals

- Server-side scheduled job, persisted state, or restart-survival.
- Stop/unset API (PCE does not expose one; rate decays on its own ~10 min after
  the last call).
- Acceleration history UI (the PCE event log already records
  `workloads.flow_reporting_frequency_updated`).
- Custom minute values — first version offers `Single shot / 30 / 60 / 120 min`.

## 3. End-to-End Flow

```
[user click row "⚡ Accelerate"]                  (single shot)
[user click bulk-bar "⚡ Accelerate Selected"]    (modal → choose duration)
        │
        ▼
quarantine.js
  - collect hrefs from row click OR `.qw-chk:checked`
  - skip workloads with `managed === false` (button is also disabled in DOM)
  - if duration > 0 → start `setInterval(fn, 600_000)` and show countdown bar
        │
        ▼  POST /api/workloads/accelerate
        │  body: { hrefs: ["/orgs/1/workloads/..."], duration_minutes: 0|30|60|120 }
        │  (backend ignores `duration_minutes` — it's metadata for logs only)
        │
Flask actions blueprint (src/gui/routes/actions.py)
  - validate hrefs via `_is_workload_href`
  - call `api.set_flow_reporting_frequency(valid_hrefs)`
        │
        ▼
ApiClient.set_flow_reporting_frequency  (src/api_client.py)
  - chunk into batches of 50
  - POST /api/v2/orgs/{org}/workloads/set_flow_reporting_frequency
    body: { "workloads": [ {"href": ...}, ... ] }
  - returns (success_count, fail_count)
        │
        ▼
PCE — emits `workloads.flow_reporting_frequency_updated` event per call.
```

## 4. Backend

### 4.1 `src/api_client.py` — new method

Place it next to `update_workload_labels` / `search_workloads` (~line 605).

```python
def set_flow_reporting_frequency(self, hrefs: list[str]) -> tuple[int, int]:
    """Increase traffic update rate (a.k.a. flow reporting frequency) for
    the given workload hrefs.

    PCE caps each request at 50 workloads, so we auto-batch.
    Returns (success_count, fail_count) by batch size.
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
                logger.error(f"set_flow_reporting_frequency batch failed: status={status}")
        except Exception as e:
            fail += len(batch)
            logger.error(f"set_flow_reporting_frequency batch error: {e}")
    return success, fail
```

### 4.2 `src/gui/routes/actions.py` — new route

Place it after `api_quarantine_bulk_apply` (current line 254).

```python
@bp.route('/api/workloads/accelerate', methods=['POST'])
def api_workloads_accelerate():
    d = request.json or {}
    raw_hrefs = d.get('hrefs', []) or []
    duration = int(d.get('duration_minutes', 0) or 0)  # for log only
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
            pass  # audit-log best-effort
        return jsonify({
            "ok": True,
            "success": success,
            "failed": fail,
            "skipped_invalid": skipped_invalid,
        })
    except Exception as e:
        return _err_with_log("workloads_accelerate", e)
```

The backend never holds duration state. `duration_minutes` is logged only so
operators can grep history.

## 5. Frontend

### 5.1 Row button — `src/static/js/quarantine.js`

In `renderQwPage()` (current line ~533) extend the Actions cell:

```js
const isManaged = w.managed === true;
const accelBtn = isManaged
  ? `<button class="btn btn-sm btn-secondary" onclick="accelerateOne('${href}','${escapeHtml(w.hostname || w.name || href)}')">
       <span data-i18n="gui_btn_accelerate">${_t('gui_btn_accelerate')}</span>
     </button>`
  : `<button class="btn btn-sm btn-secondary" disabled
            title="${_t('gui_accel_unmanaged_tip')}">
       <span>${_t('gui_btn_accelerate')}</span>
     </button>`;
```

Append `${accelBtn}` after the existing Isolate button in the `<td>` for
column 6.

`accelerateOne` is a thin handler:

```js
async function accelerateOne(href, label) {
  try {
    const r = await fetch('/api/workloads/accelerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hrefs: [href], duration_minutes: 0 }),
    }).then(r => r.json());
    if (!r.ok) throw new Error(r.error || 'failed');
    toast(`${_t('gui_accel_done')}: ${label}`);
  } catch (e) {
    toast(`${_t('gui_rs_error_prefix')}: ${e.message}`, 'error');
  }
}
```

(Reuse the existing `toast()` helper if present; otherwise fall back to a
simple `alert`/`console.warn` until a toast util is added.)

### 5.2 Bulk button — `src/templates/index.html`

In the `floating-action-bar#bulk-bar` (line 539) append after the Quarantine
button:

```html
<button class="btn btn-secondary" data-action="openAccelerateModal"
        data-i18n="gui_accel_bulk_btn">
  <svg class="icon"><use href="#icon-activity"></use></svg>
  ⚡ Accelerate Selected
</button>
```

### 5.3 Bulk modal — `src/templates/index.html`

Add a new modal `m-accelerate` (mirror the structure of existing modals):

```html
<div class="modal" id="m-accelerate" role="dialog" aria-modal="true">
  <div class="modal-card">
    <h3 data-i18n="gui_accel_modal_title">Accelerate Workloads</h3>
    <p id="accel-summary" style="font-size:0.9rem;color:var(--dim);"></p>
    <fieldset>
      <legend data-i18n="gui_accel_duration">Duration</legend>
      <label><input type="radio" name="accel-dur" value="0" checked> <span data-i18n="gui_accel_single">Single shot</span></label><br>
      <label><input type="radio" name="accel-dur" value="30"> 30 min</label><br>
      <label><input type="radio" name="accel-dur" value="60"> 60 min</label><br>
      <label><input type="radio" name="accel-dur" value="120"> 120 min</label>
    </fieldset>
    <div class="modal-actions">
      <button class="btn btn-secondary" data-action="closeModal" data-args='["m-accelerate"]' data-i18n="gui_cancel">Cancel</button>
      <button class="btn btn-primary" data-action="confirmAccelerate" data-i18n="gui_confirm">Confirm</button>
    </div>
  </div>
</div>
```

### 5.4 Bulk handlers — `src/static/js/quarantine.js`

```js
let _accel_timer = null;       // setInterval handle
let _accel_endTs = 0;
let _accel_hrefs = [];

function openAccelerateModal() {
  const checked = Array.from(document.querySelectorAll('.qw-chk:checked'));
  const all = checked.map(c => ({ href: c.value, managed: c.dataset.managed === '1' }));
  const managed = all.filter(x => x.managed);
  const skipped = all.length - managed.length;
  document.getElementById('accel-summary').textContent =
    _t('gui_accel_modal_summary')
      .replace('{total}', all.length)
      .replace('{managed}', managed.length)
      .replace('{skipped}', skipped);
  _accel_hrefs = managed.map(x => x.href);
  document.getElementById('m-accelerate').classList.add('show');
}

async function confirmAccelerate() {
  const dur = parseInt(document.querySelector('input[name="accel-dur"]:checked').value, 10);
  closeModal('m-accelerate');
  if (_accel_hrefs.length === 0) return;

  const fire = async () => {
    const r = await fetch('/api/workloads/accelerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hrefs: _accel_hrefs, duration_minutes: dur }),
    }).then(r => r.json()).catch(e => ({ ok: false, error: e.message }));
    if (!r.ok) toast(_t('gui_rs_error_prefix') + ': ' + (r.error || ''), 'error');
    return r;
  };

  await fire();
  toast(_t('gui_accel_started').replace('{n}', _accel_hrefs.length));

  if (dur > 0) {
    cancelAccelerate();   // clear any prior timer
    _accel_endTs = Date.now() + dur * 60_000;
    _accel_timer = setInterval(() => {
      if (Date.now() >= _accel_endTs) { cancelAccelerate(); return; }
      fire();
    }, 600_000);  // 10 minutes
    showAccelerateCountdown();
  }
}

function cancelAccelerate() {
  if (_accel_timer) { clearInterval(_accel_timer); _accel_timer = null; }
  hideAccelerateCountdown();
}
```

`renderQwPage` must also stamp `data-managed="1|0"` onto each `.qw-chk` so the
modal can compute `skipped` without re-fetching the workload list.

### 5.5 Countdown bar — `src/templates/index.html`

Add a small floating element shown only while `_accel_timer` is non-null:

```html
<div id="accel-countdown" class="floating-action-bar" style="display:none;">
  <span>🟢 <span data-i18n="gui_accel_running_label">Accelerating</span>
        <span id="accel-count">0</span> —
        <span id="accel-remaining">--:--</span></span>
  <button class="btn btn-sm btn-secondary" data-action="cancelAccelerate"
          data-i18n="gui_cancel">Cancel</button>
</div>
```

`showAccelerateCountdown()` updates `accel-remaining` every second via a
separate 1-second tick. (Display only — does not call the API.)

## 6. i18n keys

`src/i18n_en.json` and `src/i18n_zh_TW.json` add:

| key | en | zh_TW |
|---|---|---|
| `gui_btn_accelerate` | `⚡ Accelerate` | `⚡ 加速` |
| `gui_accel_unmanaged_tip` | `VEN not installed` | `VEN 未安裝` |
| `gui_accel_bulk_btn` | `⚡ Accelerate Selected` | `⚡ 加速所選` |
| `gui_accel_modal_title` | `Accelerate Workloads` | `加速工作負載` |
| `gui_accel_modal_summary` | `{total} selected, {managed} managed, {skipped} will be skipped.` | `已選 {total}，可加速 {managed}，將略過 {skipped}。` |
| `gui_accel_duration` | `Duration` | `持續時長` |
| `gui_accel_single` | `Single shot` | `單次` |
| `gui_accel_running_label` | `Accelerating` | `加速中` |
| `gui_accel_started` | `Accelerating {n} workloads` | `已開始加速 {n} 個工作負載` |
| `gui_accel_done` | `Accelerated` | `加速已套用` |
| `gui_accel_no_targets` | `No valid workloads to accelerate.` | `沒有可加速的工作負載。` |

## 7. Constraints

- `set_flow_reporting_frequency` API is undocumented but used by both
  `brian1917/workloader` and the PCE Web UI. The endpoint
  `POST /api/v2/orgs/{org}/workloads/set_flow_reporting_frequency` is
  considered stable based on observation; if PCE versions diverge, isolate
  the call site to one method (`set_flow_reporting_frequency`) for easy
  swapping.
- 50-workload batch cap is hard-coded; PCE-side limit.
- Persistent mode is browser-tab-bound. Closing the tab stops the loop. PCE
  decays back to normal frequency ~10 min after the last call.
- Only managed workloads accept the API. Unmanaged workloads are skipped on
  the frontend (button disabled / filtered before send) — the backend also
  validates href format only, not managed state.

## 8. Test Plan

Unit:
- `test_set_flow_reporting_frequency_batches_at_50` — ApiClient method
  produces correct number of POST calls for 1, 50, 51, 200 hrefs.
- `test_set_flow_reporting_frequency_returns_counts` — mock 2xx vs 4xx
  responses and verify `(success, fail)` math.
- `test_api_workloads_accelerate_validates_hrefs` — bad hrefs are dropped
  and counted as `skipped_invalid`.
- `test_api_workloads_accelerate_empty` — empty list returns `ok: False`.

Integration / smoke (manual against a real PCE):
- Single-shot row click on one managed workload → PCE event log shows
  `workloads.flow_reporting_frequency_updated`.
- Bulk 30-min on 12 selected (1 unmanaged) → toast says "11 accelerated";
  countdown bar appears; PCE event fires now and ~10 min later.
- Cancel button stops the timer (verified by no further events).

## 9. Out of Scope (revisit later)

- v2: Server-side persistent mode with `accelerate_jobs` table, restart
  recovery, multi-user visibility.
- v2: Custom minute input.
- v2: Per-workload countdown chip in the row (today only the global bar
  shows status).
