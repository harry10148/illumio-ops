# Integrations UI/UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 visual design gaps between the Integrations tab (Overview/Cache/SIEM/DLQ) and the rest of the app — sub-tab active styling, form-group labels, rule-table, accent2 h3 colours, undefined CSS classes, and status badges.

**Architecture:** CSS-only and JS HTML-string changes; no backend Python changes. New CSS classes added to `app.css`. Four JS render functions rewritten in place; two helper functions added. Six i18n keys added, four dead keys removed — both JSON files updated in the same commit as the JS that uses them.

**Tech Stack:** Vanilla ES5-style JS (var/function, no arrow fns, string concatenation), Flask Jinja2 template, app.css custom properties

---

## File Map

| File | Change |
|------|--------|
| `src/static/css/app.css` | Add ~25 lines: sub-tab active, card variants, status badge, dot |
| `src/static/js/integrations.js` | Rewrite 8 functions, add 2 helper functions |
| `src/i18n_en.json` | Update 1 value, add 5 keys, remove 4 dead keys |
| `src/i18n_zh_TW.json` | Mirror all JSON changes |

---

## Task 1: CSS — Add missing visual classes

**Files:**
- Modify: `src/static/css/app.css` (insert before `/* Empty state */` comment, around line 1299)

- [ ] **Step 1: Insert the CSS block**

Find `/* Empty state */` in `app.css` and insert this block immediately before it:

```css
    /* ── Integrations UI ──────────────────────────────────────────────────── */

    /* Sub-tab active underline (matches .rs-tab-bar pattern) */
    #p-integrations .sub-tab.active {
      border-bottom: 3px solid var(--accent);
      font-weight: 700;
    }

    /* Card left-border colour variants */
    .card.card-ok      { border-left: 4px solid var(--success); }
    .card.card-warn    { border-left: 4px solid var(--warn); }
    .card.card-err     { border-left: 4px solid var(--danger); }
    .card.card-neutral { border-left: 4px solid var(--dim); opacity: .85; }

    /* Status badge pill */
    .status-badge {
      display: inline-flex; align-items: center; gap: 4px;
      font-size: .73rem; padding: 2px 8px; border-radius: 99px; font-weight: 600;
    }
    .status-badge.ok   { background: rgba(41,155,101,.15); color: var(--success); border: 1px solid rgba(41,155,101,.3); }
    .status-badge.warn { background: rgba(230,167,0,.12);  color: var(--warn);    border: 1px solid rgba(230,167,0,.3); }
    .status-badge.err  { background: rgba(244,63,81,.15);  color: var(--danger);  border: 1px solid rgba(244,63,81,.3); }

    /* Dot indicator (used inside .status-badge) */
    .dot      { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .dot.ok   { background: var(--success); }
    .dot.warn { background: var(--warn); }
    .dot.err  { background: var(--danger); }
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/ -q --tb=no -x 2>&1 | tail -3
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
cd /mnt/d/RD/illumio_ops
git add src/static/css/app.css
git commit -m "style(integrations): add sub-tab active, card variants, status-badge CSS"
```

---

## Task 2: Overview Tab — Better cards + mini-table

**Files:**
- Modify: `src/static/js/integrations.js` (block at line ~966–1049)
- Modify: `src/i18n_en.json` and `src/i18n_zh_TW.json`

**Context:** The first overview card label is "Cache Lag" but the API returns row counts, not lag. Rename the JSON value. The SIEM Queue card is redesigned to show 3 mini-columns (pending/sent/failed). The per-destination list changes from a plain `<ul>` to a `rule-table`.

- [ ] **Step 1: Update i18n value for cache card label**

In `src/i18n_en.json` line 559, change:
```json
  "gui_ov_cache_lag": "Cache Lag",
```
to:
```json
  "gui_ov_cache_lag": "Cache Rows",
```

In `src/i18n_zh_TW.json` line 559, change:
```json
  "gui_ov_cache_lag": "快取延遲",
```
to:
```json
  "gui_ov_cache_lag": "快取列數",
```

- [ ] **Step 2: Replace the entire Overview block in integrations.js**

The block to replace starts at:
```
// ── Overview sub-tab ─────────────────────────────────────────────────────────
window._integrations.setRender('overview', async function renderOverview() {
```
and ends at the closing `});` on line 1049.

Replace it with the following (note: uses `el.innerHTML = html` — pre-escaped via `escapeAttr` throughout):

```javascript
// ── Overview sub-tab ─────────────────────────────────────────────────────────
function _buildOvCards(cache, siemStatus, totalPending, totalSent, totalFailed, totalDlq) {
  var siemClass = totalFailed > 0 ? 'card-err' : 'card-ok';
  var dlqClass  = totalDlq  > 0 ? 'card-warn' : 'card-ok';
  var cacheEvents  = Number(cache.events      || 0);
  var cacheTraffic = Number(cache.traffic_raw || 0) + Number(cache.traffic_agg || 0);
  var failedColor  = totalFailed > 0 ? 'var(--danger)' : 'var(--dim)';
  var queueInner = '<div style="display:flex;gap:16px;margin-top:6px;">'
    + '<div><div style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_pending">pending</div>'
    + '<div style="font-size:1.3rem;color:var(--accent2);font-weight:700;">' + totalPending + '</div></div>'
    + '<div><div style="font-size:.7rem;color:var(--success);" data-i18n="gui_ov_sent">sent</div>'
    + '<div style="font-size:1.3rem;color:var(--success);font-weight:700;">' + totalSent + '</div></div>'
    + '<div><div style="font-size:.7rem;color:' + failedColor + ';" data-i18n="gui_ov_failed">failed</div>'
    + '<div style="font-size:1.3rem;color:' + failedColor + ';font-weight:700;">' + totalFailed + '</div></div>'
    + '</div>';
  return '<div class="cards" style="margin-bottom:16px;">'
    + '<div class="card card-neutral">'
    + '<div class="label" data-i18n="gui_ov_cache_lag">Cache Rows</div>'
    + '<div class="value" style="font-size:.95rem;line-height:1.5;">'
    + cacheEvents.toLocaleString() + ' <span style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_events">events</span><br>'
    + cacheTraffic.toLocaleString() + ' <span style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_traffic">traffic</span>'
    + '</div>'
    + '</div>'
    + '<div class="card card-neutral">'
    + '<div class="label" data-i18n="gui_ov_siem_destinations">SIEM Destinations</div>'
    + '<div class="value">' + siemStatus.length + '</div>'
    + '<div style="font-size:.75rem;color:var(--dim);">' + escapeAttr(_t('gui_ov_destinations_fmt').replace('{n}', siemStatus.length)) + '</div>'
    + '</div>'
    + '<div class="card ' + siemClass + '">'
    + '<div class="label" data-i18n="gui_ov_siem_queue">SIEM Queue</div>'
    + queueInner
    + '</div>'
    + '<div class="card ' + dlqClass + '">'
    + '<div class="label" data-i18n="gui_ov_dlq_total">DLQ Total</div>'
    + '<div class="value">' + totalDlq + '</div>'
    + '</div>'
    + '</div>';
}

function _buildOvRecentTable(siemStatus) {
  var rows = '';
  if (siemStatus.length === 0) {
    rows = '<tr><td colspan="5" style="color:var(--dim);padding:16px 10px;" data-i18n="gui_ov_no_events">(no recent events)</td></tr>';
  } else {
    siemStatus.forEach(function(d) {
      var failStyle = Number(d.failed || 0) > 0 ? ' style="color:var(--danger)"' : '';
      rows += '<tr>'
        + '<td><code>' + escapeAttr(d.destination || '') + '</code></td>'
        + '<td>' + Number(d.pending || 0) + '</td>'
        + '<td style="color:var(--success)">' + Number(d.sent || 0) + '</td>'
        + '<td' + failStyle + '>' + Number(d.failed || 0) + '</td>'
        + '<td>' + Number(d.dlq || 0) + '</td>'
        + '</tr>';
    });
  }
  return '<h3 style="color:var(--accent2);font-size:.9rem;font-weight:700;margin:16px 0 8px;" data-i18n="gui_ov_recent_events">Recent dispatch events</h3>'
    + '<div class="table-container">'
    + '<table class="rule-table">'
    + '<colgroup>'
    + '<col style="width:30%"><col style="width:14%"><col style="width:18%"><col style="width:14%"><col style="width:14%">'
    + '</colgroup>'
    + '<thead><tr>'
    + '<th data-i18n="gui_dlq_th_dest">Dest</th>'
    + '<th data-i18n="gui_ov_pending">pending</th>'
    + '<th data-i18n="gui_ov_sent">sent</th>'
    + '<th data-i18n="gui_ov_failed">failed</th>'
    + '<th data-i18n="gui_ov_dlq">DLQ</th>'
    + '</tr></thead>'
    + '<tbody>' + rows + '</tbody>'
    + '</table>'
    + '</div>';
}

window._integrations.setRender('overview', async function renderOverview() {
  var el = document.getElementById('it-pane-overview');
  if (!el) return;
  el.innerHTML = '<p data-i18n="gui_it_loading" style="color:var(--dim)">Loading...</p>';

  var cache, siem;
  try {
    var results = await Promise.all([
      fetch('/api/cache/status').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
      fetch('/api/siem/status').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
    ]);
    cache = results[0] || {};
    siem  = results[1] || {status: []};
  } catch (err) {
    el.textContent = '';
    var p = document.createElement('p');
    p.style.color = 'var(--danger,red)';
    p.textContent = 'Failed to load overview: ' + String(err);
    el.appendChild(p);
    return;
  }

  var siemStatus = siem.status || [];
  var totalPending = 0, totalSent = 0, totalFailed = 0, totalDlq = 0;
  siemStatus.forEach(function(d) {
    totalPending += Number(d.pending || 0);
    totalSent    += Number(d.sent    || 0);
    totalFailed  += Number(d.failed  || 0);
    totalDlq     += Number(d.dlq     || 0);
  });

  el.innerHTML = _buildOvCards(cache, siemStatus, totalPending, totalSent, totalFailed, totalDlq)
               + _buildOvRecentTable(siemStatus);
  if (typeof window.i18nApply === 'function') window.i18nApply();
});
```

- [ ] **Step 3: Run i18n audit**

```bash
cd /mnt/d/RD/illumio_ops && python3 scripts/audit_i18n_usage.py 2>&1 | tail -4
```

Expected: `Total: 0 finding(s)`

- [ ] **Step 4: Commit**

```bash
cd /mnt/d/RD/illumio_ops
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(integrations/overview): better 4-card layout + rule-table dispatch events"
```

---

## Task 3: Cache Tab — fieldset sections + form-group labels + fixed status cards

**Files:**
- Modify: `src/static/js/integrations.js` (functions `buildCacheStatusCards`, `buildCacheForm`, `renderTrafficFilter`, `renderTrafficSampling`)
- Modify: `src/i18n_en.json` and `src/i18n_zh_TW.json`

**Context:** `buildCacheStatusCards` reads `events_lag_sec`/`traffic_lag_sec` which don't exist in the API response (endpoint returns `events`, `traffic_raw`, `traffic_agg` row counts — see `src/pce_cache/web.py:82–94`). The form uses `<h3>` without `color:var(--accent2)` and plain `<label>` without `.form-group`. Replacing `<h3>` with `<fieldset><legend>` picks up existing CSS styling automatically. Four dead i18n keys removed; two new keys added.

**i18n changes:**
- Add `"gui_cache_card_traffic_raw": "Traffic Raw"` / `"原始流量"`
- Add `"gui_cache_card_traffic_agg": "Traffic Agg"` / `"彙總流量"`
- Remove `gui_cache_events_lag`, `gui_cache_traffic_lag`, `gui_cache_last_events`, `gui_cache_last_traffic` (grep confirms they are only used in `buildCacheStatusCards`)

- [ ] **Step 1: Update src/i18n_en.json**

Add after the `"gui_cache_db_path": "DB path",` line:
```json
  "gui_cache_card_traffic_raw": "Traffic Raw",
  "gui_cache_card_traffic_agg": "Traffic Agg",
```

Remove these four lines:
```json
  "gui_cache_events_lag": "Events lag (s)",
  "gui_cache_last_events": "Last events ingest",
  "gui_cache_last_traffic": "Last traffic ingest",
  "gui_cache_traffic_lag": "Traffic lag (s)",
```

- [ ] **Step 2: Update src/i18n_zh_TW.json**

Run first to see exact values:
```bash
grep "gui_cache_events_lag\|gui_cache_last_events\|gui_cache_last_traffic\|gui_cache_traffic_lag" /mnt/d/RD/illumio_ops/src/i18n_zh_TW.json
```

Add after `gui_cache_db_path`:
```json
  "gui_cache_card_traffic_raw": "原始流量",
  "gui_cache_card_traffic_agg": "彙總流量",
```

Remove the four lines found by the grep above.

- [ ] **Step 3: Replace buildCacheStatusCards (lines ~92–110)**

```javascript
function buildCacheStatusCards(status, s) {
  var events     = Number(status.events      || 0);
  var trafficRaw = Number(status.traffic_raw || 0);
  var trafficAgg = Number(status.traffic_agg || 0);
  var stateClass = s.enabled ? 'ok' : 'err';
  var stateText  = s.enabled
    ? '<span style="color:var(--success)">✓ ' + escapeAttr(_t('gui_cache_enabled')) + '</span>'
    : '<span style="color:var(--danger)">✗ ' + escapeAttr(_t('gui_cache_enabled')) + '</span>';
  return '<div class="cards" style="margin-bottom:16px;">'
    + '<div class="card card-' + stateClass + '">'
    + '<div class="label" data-i18n="gui_cache_status">Cache Status</div>'
    + '<div class="value" style="font-size:1.05rem;">' + stateText + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_ov_events">events</div>'
    + '<div class="value">' + events.toLocaleString() + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_cache_card_traffic_raw">Traffic Raw</div>'
    + '<div class="value">' + trafficRaw.toLocaleString() + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_cache_card_traffic_agg">Traffic Agg</div>'
    + '<div class="value">' + trafficAgg.toLocaleString() + '</div>'
    + '</div>'
    + '</div>'
    + '<div class="toolbar" style="margin-bottom:16px;">'
    + '<button class="btn btn-sm" onclick="cacheBackfill()" data-i18n="gui_backfill">Backfill</button>'
    + '<button class="btn btn-sm" onclick="cacheRetentionNow()" data-i18n="gui_retention_now">Retention now</button>'
    + '</div>';
}
```

- [ ] **Step 4: Replace buildCacheForm (lines ~112–142)**

Preserve all input `name` attributes exactly (they are read by `cacheSave()` via `new FormData(form)`).

```javascript
function buildCacheForm(s) {
  var dbPath = escapeAttr(s.db_path);
  return '<form id="cache-form">'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_basic">Basic</legend>'
    + '<div class="chk" style="margin-bottom:14px;">'
    + '<label><input type="checkbox" name="enabled"' + (s.enabled ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_cache_enabled">Enabled</span></label>'
    + '</div>'
    + '<div class="form-group">'
    + '<label data-i18n="gui_cache_db_path">DB path</label>'
    + '<input name="db_path" value="' + dbPath + '">'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_retention">Retention (days)</legend>'
    + '<div class="form-row-3">'
    + '<div class="form-group"><label data-i18n="gui_ov_events">events</label>'
    + '<input type="number" name="events_retention_days" min="1" value="' + Number(s.events_retention_days) + '"></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_card_traffic_raw">Traffic Raw</label>'
    + '<input type="number" name="traffic_raw_retention_days" min="1" value="' + Number(s.traffic_raw_retention_days) + '"></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_card_traffic_agg">Traffic Agg</label>'
    + '<input type="number" name="traffic_agg_retention_days" min="1" value="' + Number(s.traffic_agg_retention_days) + '"></div>'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_polling">Polling (seconds)</legend>'
    + '<div class="form-row">'
    + '<div class="form-group"><label>events_poll_interval_seconds</label>'
    + '<input type="number" name="events_poll_interval_seconds" min="30" value="' + Number(s.events_poll_interval_seconds) + '"></div>'
    + '<div class="form-group"><label>traffic_poll_interval_seconds</label>'
    + '<input type="number" name="traffic_poll_interval_seconds" min="60" value="' + Number(s.traffic_poll_interval_seconds) + '"></div>'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_throughput">Throughput</legend>'
    + '<div class="form-row">'
    + '<div class="form-group"><label>rate_limit_per_minute</label>'
    + '<input type="number" name="rate_limit_per_minute" min="10" max="500" value="' + Number(s.rate_limit_per_minute) + '"></div>'
    + '<div class="form-group"><label>async_threshold_events</label>'
    + '<input type="number" name="async_threshold_events" min="1" max="10000" value="' + Number(s.async_threshold_events) + '"></div>'
    + '</div>'
    + '</fieldset>'
    + '<div id="cache-form-extra"></div>'
    + '<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:8px;">'
    + '<div id="cache-banner" style="flex:1;display:none;"></div>'
    + '<button type="button" class="btn btn-primary" onclick="cacheSave()" data-i18n="gui_save">Save</button>'
    + '</div>'
    + '</form>';
}
```

Also update the `renderCache` function: find the line that sets `el.innerHTML` (around line 85):

```javascript
el.innerHTML = header + form + '<div id="cache-banner" style="display:none;margin-top:12px;"></div>';
```

Replace with:

```javascript
el.innerHTML = header + form;
```

(The `#cache-banner` div is now inside `buildCacheForm`.)

- [ ] **Step 5: Replace renderTrafficFilter (lines ~267–298)**

```javascript
function renderTrafficFilter(s) {
  var tf = s.traffic_filter || {};
  var actions   = ['blocked', 'potentially_blocked', 'allowed'];
  var protocols = ['TCP', 'UDP', 'ICMP'];
  var envVals  = (tf.workload_label_env || []).map(escapeAttr).join(',');
  var portVals = escapeAttr((tf.ports || []).map(Number).join(','));
  var ipVals   = (tf.exclude_src_ips || []).map(escapeAttr).join(',');

  var html = '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_traffic_filter">Traffic Filter</legend>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_actions">Actions</label>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap;padding:4px 0;">'
    + actions.map(function(a) {
        return '<label style="display:inline-flex;align-items:center;gap:6px;">'
          + '<input type="checkbox" name="tf-action" value="' + escapeAttr(a) + '"'
          + ((tf.actions || []).indexOf(a) >= 0 ? ' checked' : '') + '> '
          + escapeAttr(a) + '</label>';
      }).join('')
    + '</div></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_protocols">Protocols</label>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap;padding:4px 0;">'
    + protocols.map(function(p) {
        return '<label style="display:inline-flex;align-items:center;gap:6px;">'
          + '<input type="checkbox" name="tf-protocol" value="' + escapeAttr(p) + '"'
          + ((tf.protocols || []).indexOf(p) >= 0 ? ' checked' : '') + '> '
          + escapeAttr(p) + '</label>';
      }).join('')
    + '</div></div>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_workload_env">Workload label env</label>'
    + '<input id="tf-env" value="' + envVals + '" placeholder="prod,staging"></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_ports">Ports</label>'
    + '<input id="tf-ports" value="' + portVals + '" placeholder="22,443,..."></div>'
    + '</div>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_exclude_ips">Exclude src IPs</label>'
    + '<input id="tf-ips" value="' + ipVals + '" placeholder="10.0.0.1,..."></div>'
    + '<div id="tf-validation-hints" style="color:var(--danger);font-size:.8rem;"></div>'
    + '</fieldset>';

  var extra = document.getElementById('cache-form-extra');
  if (extra) extra.innerHTML = html;
}
```

- [ ] **Step 6: Replace renderTrafficSampling (lines ~346–357)**

```javascript
function renderTrafficSampling(s) {
  var ts      = s.traffic_sampling || {};
  var ratio   = Number(ts.sample_ratio_allowed || 1);
  var maxRows = Number(ts.max_rows_per_batch || 200000);
  var html = '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_traffic_sampling">Traffic Sampling</legend>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_cache_ts_ratio">sample_ratio_allowed</label>'
    + '<input type="number" id="ts-ratio" min="1" value="' + ratio + '"></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_ts_max_rows">max_rows_per_batch</label>'
    + '<input type="number" id="ts-max" min="1" max="200000" value="' + maxRows + '"></div>'
    + '</div>'
    + '</fieldset>';
  var extra = document.getElementById('cache-form-extra');
  if (extra) extra.insertAdjacentHTML('beforeend', html);
}
```

- [ ] **Step 7: Run i18n audit**

```bash
cd /mnt/d/RD/illumio_ops && python3 scripts/audit_i18n_usage.py 2>&1 | tail -4
```

Expected: `Total: 0 finding(s)`

- [ ] **Step 8: Run tests**

```bash
cd /mnt/d/RD/illumio_ops && python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
cd /mnt/d/RD/illumio_ops
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(integrations/cache): fieldset sections, form-group labels, accurate status cards"
```

---

## Task 4: SIEM Tab — rule-table + status badges + form-group

**Files:**
- Modify: `src/static/js/integrations.js` (add `_siemStatusBadge`; replace `buildSiemForwarderForm`, `buildSiemDestinationsSection`, `buildSiemRow`)
- Modify: `src/i18n_en.json` and `src/i18n_zh_TW.json`

**Context:** Forwarder form lacks `.form-group` wrappers. Destinations table uses `style="width:100%;font-size:.85rem;"` instead of `class="rule-table"`. Status column shows emoji dots (🔴🟡🟢) — replace with CSS badge pills. Three new i18n keys needed for the badge text.

- [ ] **Step 1: Add new i18n keys to src/i18n_en.json**

Add after the existing `gui_siem_th_*` block (around line 946):
```json
  "gui_siem_status_healthy": "Healthy",
  "gui_siem_status_disabled": "Disabled",
  "gui_siem_status_error": "Error",
```

- [ ] **Step 2: Add same keys to src/i18n_zh_TW.json**

Add in the same position:
```json
  "gui_siem_status_healthy": "正常",
  "gui_siem_status_disabled": "停用",
  "gui_siem_status_error": "錯誤",
```

- [ ] **Step 3: Add _siemStatusBadge helper**

Insert just before `function buildSiemForwarderForm(fw) {` (line ~397):

```javascript
function _siemStatusBadge(d, st) {
  if (!d.enabled) {
    return '<span class="status-badge warn"><span class="dot warn"></span>'
      + escapeAttr(_t('gui_siem_status_disabled')) + '</span>';
  }
  if (Number(st.failed || 0) > 0) {
    return '<span class="status-badge err"><span class="dot err"></span>'
      + escapeAttr(_t('gui_siem_status_error')) + '</span>';
  }
  return '<span class="status-badge ok"><span class="dot ok"></span>'
    + escapeAttr(_t('gui_siem_status_healthy')) + '</span>';
}
```

- [ ] **Step 4: Replace buildSiemForwarderForm (lines ~397–408)**

```javascript
function buildSiemForwarderForm(fw) {
  return '<section class="rs-glass" style="margin-bottom:16px;">'
    + '<h3 style="color:var(--accent2);margin:0 0 14px;" data-i18n="gui_siem_forwarder">Forwarder</h3>'
    + '<div class="form-row">'
    + '<div class="form-group">'
    + '<label data-i18n="gui_siem_dispatch_tick">dispatch_tick_seconds</label>'
    + '<input type="number" id="siem-tick" min="1" value="' + Number(fw.dispatch_tick_seconds) + '">'
    + '</div>'
    + '<div class="form-group">'
    + '<label data-i18n="gui_siem_dlq_max">dlq_max_per_dest</label>'
    + '<input type="number" id="siem-dlq-max" min="100" value="' + Number(fw.dlq_max_per_dest) + '">'
    + '</div>'
    + '</div>'
    + '<div class="chk" style="margin-bottom:14px;">'
    + '<label><input type="checkbox" id="siem-enabled"' + (fw.enabled ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_siem_enabled">Enabled</span></label>'
    + '</div>'
    + '<div style="display:flex;justify-content:flex-end;">'
    + '<button class="btn btn-primary btn-sm" onclick="siemSaveForwarder()" data-i18n="gui_save">Save</button>'
    + '</div>'
    + '</section>';
}
```

- [ ] **Step 5: Replace buildSiemDestinationsSection (lines ~410–430)**

```javascript
function buildSiemDestinationsSection() {
  return '<section class="rs-glass">'
    + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
    + '<h3 style="color:var(--accent2);margin:0;" data-i18n="gui_siem_destinations">Destinations</h3>'
    + '<button class="btn btn-sm" onclick="siemOpenDestModal()" data-i18n="gui_siem_add">+ Add</button>'
    + '</div>'
    + '<div class="table-container">'
    + '<table class="rule-table">'
    + '<colgroup>'
    + '<col style="width:18%"><col style="width:10%"><col style="width:13%"><col style="width:25%"><col style="width:16%"><col>'
    + '</colgroup>'
    + '<thead><tr>'
    + '<th data-i18n="gui_siem_th_name">Name</th>'
    + '<th data-i18n="gui_siem_th_transport">Transport</th>'
    + '<th data-i18n="gui_siem_th_format">Format</th>'
    + '<th data-i18n="gui_siem_th_endpoint">Endpoint</th>'
    + '<th data-i18n="gui_siem_th_status">Status</th>'
    + '<th data-i18n="gui_siem_th_actions">Actions</th>'
    + '</tr></thead>'
    + '<tbody id="siem-dest-tbody"></tbody>'
    + '</table>'
    + '</div>'
    + '</section>'
    + '<div id="siem-banner" style="margin-top:12px;"></div>'
    + '<div id="siem-modal-host"></div>';
}
```

- [ ] **Step 6: Replace buildSiemRow (lines ~432–448)**

```javascript
function buildSiemRow(d, st) {
  var nameEnc = encodeURIComponent(d.name).replace(/'/g, '%27');
  var dim = d.enabled ? '' : ' <span style="color:var(--dim);font-size:.8rem;">(disabled)</span>';
  return '<tr>'
    + '<td><b>' + escapeAttr(d.name) + '</b>' + dim + '</td>'
    + '<td><code>' + escapeAttr(d.transport) + '</code></td>'
    + '<td><code>' + escapeAttr(d.format) + '</code></td>'
    + '<td title="' + escapeAttr(d.endpoint) + '">' + escapeAttr(d.endpoint) + '</td>'
    + '<td>' + _siemStatusBadge(d, st) + '</td>'
    + '<td style="white-space:nowrap;">'
    + '<button class="btn btn-sm" onclick="siemTestDest(\'' + nameEnc + '\')" data-i18n="gui_siem_test">Test</button> '
    + '<button class="btn btn-sm" onclick="siemOpenDestModal(\'' + nameEnc + '\')" data-i18n="gui_siem_edit">Edit</button> '
    + '<button class="btn btn-sm btn-danger" onclick="siemDeleteDest(\'' + nameEnc + '\')" data-i18n="gui_siem_delete">Delete</button>'
    + '</td>'
    + '</tr>';
}
```

- [ ] **Step 7: Run i18n audit**

```bash
cd /mnt/d/RD/illumio_ops && python3 scripts/audit_i18n_usage.py 2>&1 | tail -4
```

Expected: `Total: 0 finding(s)`

- [ ] **Step 8: Run tests**

```bash
cd /mnt/d/RD/illumio_ops && python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
cd /mnt/d/RD/illumio_ops
git add src/static/js/integrations.js src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(integrations/siem): rule-table, form-group, status badge (replaces emoji dots)"
```

---

## Task 5: DLQ Tab — combined toolbar + rule-table + truncation + short date

**Files:**
- Modify: `src/static/js/integrations.js` (add `_fmtShortDt`; replace `buildDlqSkeleton`, update `renderDlq`, replace `buildDlqRow`)

**Context:** Filter and bulk action bars are separate divs; merging them into one `.toolbar` saves vertical space. DLQ table has no `.rule-table` class. Reason cells show raw text with no truncation (ellipsis is applied via `rule-table td` once the class is added). Dates show full ISO strings. A Retries column is added — the data is in the API response (`e.retries`) but was never rendered. The empty-state `colspan` must increase from 6 to 7 to match the new column count.

- [ ] **Step 1: Add _fmtShortDt helper**

Insert just before `function buildDlqSkeleton() {` (line ~699):

```javascript
function _fmtShortDt(iso) {
  if (!iso) return '—';
  var d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  var M = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return M[d.getMonth()] + ' ' + d.getDate()
    + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
```

- [ ] **Step 2: Replace buildDlqSkeleton (lines ~699–721)**

The new version folds the bulk action buttons into the same `.toolbar` div as the filter controls:

```javascript
function buildDlqSkeleton() {
  return '<div class="toolbar" style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;margin-bottom:10px;">'
    + '<div class="form-group" style="margin:0;min-width:130px;">'
    + '<label data-i18n="gui_dlq_filter_dest">Destination</label>'
    + '<select id="dlq-dest" style="width:100%;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:6px 8px;color:var(--fg);font-size:.83rem;">'
    + '<option value="" data-i18n="gui_dlq_filter_all">All</option></select>'
    + '</div>'
    + '<div class="form-group" style="margin:0;flex:1;min-width:140px;">'
    + '<label data-i18n="gui_dlq_filter_reason">Reason contains</label>'
    + '<input id="dlq-reason" style="width:100%;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:6px 8px;color:var(--fg);font-size:.83rem;">'
    + '</div>'
    + '<button class="btn btn-sm" onclick="dlqSearch()" style="align-self:flex-end;" data-i18n="gui_dlq_search">Search</button>'
    + '<span class="spacer"></span>'
    + '<button class="btn btn-sm" onclick="dlqSelectAll()" style="align-self:flex-end;" data-i18n="gui_dlq_select_all">Select All</button>'
    + '<button class="btn btn-sm" onclick="dlqReplaySelected()" style="align-self:flex-end;" data-i18n="gui_dlq_replay_selected">Replay</button>'
    + '<button class="btn btn-sm btn-warn" onclick="dlqPurgeSelected()" style="align-self:flex-end;" data-i18n="gui_dlq_purge_selected">Purge</button>'
    + '<button class="btn btn-sm btn-danger" onclick="dlqPurgeAll()" style="align-self:flex-end;" data-i18n="gui_dlq_purge_all">Purge ALL</button>'
    + '<button class="btn btn-sm" onclick="dlqExport()" style="align-self:flex-end;" data-i18n="gui_dlq_export">Export CSV</button>'
    + '</div>'
    + '<div class="table-container">'
    + '<table class="rule-table">'
    + '<colgroup><col style="width:32px"><col style="width:15%"><col style="width:12%"><col><col style="width:110px"><col style="width:55px"><col style="width:130px"></colgroup>'
    + '<thead><tr>'
    + '<th></th>'
    + '<th data-i18n="gui_dlq_th_dest">Dest</th>'
    + '<th data-i18n="gui_dlq_th_event_id">Event ID</th>'
    + '<th data-i18n="gui_dlq_th_reason">Reason</th>'
    + '<th data-i18n="gui_dlq_th_failed_at">Failed At</th>'
    + '<th>Retries</th>'
    + '<th></th>'
    + '</tr></thead>'
    + '<tbody id="dlq-tbody"></tbody>'
    + '</table>'
    + '</div>'
    + '<div id="dlq-pager" style="margin-top:8px;"></div>'
    + '<div id="dlq-modal-host"></div>';
}
```

- [ ] **Step 3: Simplify renderDlq — remove the bulkBar block**

Find `renderDlq` (line ~680). Remove this block (7 lines):

```javascript
  var bulkBar = document.getElementById('dlq-bulk-bar');
  if (bulkBar) {
    bulkBar.innerHTML = '<div style="display:flex;gap:8px;margin-bottom:8px;">'
      + '<button class="btn" onclick="dlqSelectAll()" data-i18n="gui_dlq_select_all">Select All</button>'
      + '<button class="btn" onclick="dlqReplaySelected()" data-i18n="gui_dlq_replay_selected">Replay Selected</button>'
      + '<button class="btn btn-warn" onclick="dlqPurgeSelected()" data-i18n="gui_dlq_purge_selected">Purge Selected</button>'
      + '<button class="btn btn-danger" onclick="dlqPurgeAll()" data-i18n="gui_dlq_purge_all">Purge ALL</button>'
      + '<button class="btn" onclick="dlqExport()" data-i18n="gui_dlq_export">Export CSV</button>'
      + '</div>';
  }
```

After removal the full `renderDlq` block is:

```javascript
window._integrations.setRender('dlq', async function renderDlq() {
  var el = document.getElementById('it-pane-dlq');
  if (!el) return;
  el.innerHTML = buildDlqSkeleton();
  await populateDlqDestinations();
  await dlqSearch();
  if (typeof window.i18nApply === 'function') window.i18nApply();
});
```

- [ ] **Step 4: Replace buildDlqRow (lines ~795–808)**

The `title` attribute on the Reason `<td>` lets the browser show the full text on hover. The `.rule-table td` CSS already applies `overflow:hidden; text-overflow:ellipsis; white-space:nowrap` so no extra class is needed.

```javascript
function buildDlqRow(e) {
  var id     = Number(e.id);
  var reason = String(e.last_error || '');
  return '<tr>'
    + '<td><input type="checkbox" class="dlq-chk" value="' + id + '"></td>'
    + '<td><code>' + escapeAttr(e.destination || e.source_table || '') + '</code></td>'
    + '<td style="font-size:.78rem;color:var(--dim);">' + escapeAttr(e.source_id || '') + '</td>'
    + '<td title="' + escapeAttr(reason) + '">' + escapeAttr(reason) + '</td>'
    + '<td style="font-size:.78rem;color:var(--dim);">' + escapeAttr(_fmtShortDt(e.quarantined_at)) + '</td>'
    + '<td style="text-align:center;">' + Number(e.retries || 0) + '</td>'
    + '<td style="white-space:nowrap;">'
    + '<button class="btn btn-sm" onclick="dlqView(' + id + ')" data-i18n="gui_dlq_view">View</button> '
    + '<button class="btn btn-sm" onclick="dlqReplay([' + id + '])" data-i18n="gui_dlq_replay">Replay</button>'
    + '</td>'
    + '</tr>';
}
```

- [ ] **Step 5: Fix empty-state colspan**

Find in `_dlqLoadPage` (line ~782):
```javascript
|| '<tr><td colspan="6" style="color:var(--dim);" data-i18n="gui_dlq_empty">(no DLQ entries)</td></tr>';
```
Change `colspan="6"` to `colspan="7"`.

- [ ] **Step 6: Run i18n audit**

```bash
cd /mnt/d/RD/illumio_ops && python3 scripts/audit_i18n_usage.py 2>&1 | tail -4
```

Expected: `Total: 0 finding(s)`

- [ ] **Step 7: Run full test suite**

```bash
cd /mnt/d/RD/illumio_ops && python3 -m pytest tests/ -q --tb=short 2>&1 | tail -8
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
cd /mnt/d/RD/illumio_ops
git add src/static/js/integrations.js
git commit -m "feat(integrations/dlq): combined toolbar, rule-table, reason tooltip, short date, retries column"
```

---

## Task 6: Final Verification

- [ ] **Step 1: Full i18n audit**

```bash
cd /mnt/d/RD/illumio_ops && python3 scripts/audit_i18n_usage.py
```

Expected: `Total: 0 finding(s)`

- [ ] **Step 2: Full pytest suite**

```bash
cd /mnt/d/RD/illumio_ops && python3 -m pytest tests/ -v --tb=short 2>&1 | tail -15
```

Expected: all tests pass, same count as baseline (≥ 523).

- [ ] **Step 3: Browser manual checklist**

Start the app: `cd /mnt/d/RD/illumio_ops && python3 illumio_ops.py --gui`

Navigate to `https://127.0.0.1:5001/?tab=integrations` and verify:

| Tab | Check | Expected |
|-----|-------|----------|
| All | Click each sub-tab | Active tab shows orange underline; inactive tabs dim |
| Overview | Cards | 4 cards; SIEM Queue shows 3 sub-columns (pending/sent/failed) |
| Overview | Dispatch table | `rule-table` header row (uppercase, grey bg); destination in `<code>` |
| Cache | Status cards | 4 cards showing row counts (not "—") |
| Cache | Toolbar | Backfill + Retention Now buttons |
| Cache | Form sections | Orange `<legend>` headers; labels in uppercase dim colour |
| Cache | Retention section | 3-column grid |
| Cache | Polling section | 2-column grid |
| SIEM | Forwarder | Tick + DLQ-max inputs side by side; Save at bottom right |
| SIEM | Destinations | `rule-table` headers; Status column shows green/orange badge pill |
| SIEM | Disabled dest | Status shows orange "Disabled" badge |
| DLQ | Toolbar | Single row with filter fields + bulk actions |
| DLQ | Table | Has Retries column; header row uppercase |
| DLQ | Reason | Hover shows full error text as browser tooltip |
| DLQ | Date | Shows `Apr 26 14:30` format (not full ISO) |
