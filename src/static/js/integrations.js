// Integrations tab: switcher + shared helpers + per-pane renderers.
(function () {
  'use strict';

  // Escape user-provided text before inserting into markup.
  // Used throughout this module — NEVER inline user data without this.
  function escapeAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  window.escapeAttr = escapeAttr;

  function integrationsSwitch(name) {
    ['overview', 'cache', 'siem', 'dlq'].forEach(function (n) {
      var pane = document.getElementById('it-pane-' + n);
      if (pane) pane.style.display = (n === name) ? '' : 'none';
    });
    document.querySelectorAll('#p-integrations .sub-tab').forEach(function (btn) {
      // After M1 (CSP) the buttons use data-action/data-args instead of onclick.
      var args = [];
      try { args = JSON.parse(btn.getAttribute('data-args') || '[]'); } catch (_) { args = []; }
      btn.classList.toggle('active', args[0] === name);
    });
    if (name === 'overview') renderOverview();
    else if (name === 'cache') renderCache();
    else if (name === 'siem') renderSiem();
    else if (name === 'dlq') renderDlq();
  }
  window.integrationsSwitch = integrationsSwitch;

  // Hook into the project's existing switchTab to auto-render Overview on
  // first visit. integrations.js loads BEFORE tabs.js (which defines
  // switchTab), so an immediate wrap would no-op. Try once now, otherwise
  // wrap on DOMContentLoaded — by then tabs.js has parsed.
  function wrapSwitchTab() {
    var originalSwitchTab = window.switchTab;
    if (typeof originalSwitchTab !== 'function') return false;
    if (originalSwitchTab.__integrationsWrapped) return true;
    var wrapped = function (name) {
      var r = originalSwitchTab.apply(this, arguments);
      if (name === 'integrations') integrationsSwitch('overview');
      return r;
    };
    wrapped.__integrationsWrapped = true;
    window.switchTab = wrapped;
    return true;
  }
  if (!wrapSwitchTab()) {
    document.addEventListener('DOMContentLoaded', wrapSwitchTab);
  }

  // Placeholder renderers — later tasks replace each body.
  async function renderOverview() {}
  async function renderCache() {}
  async function renderSiem() {}
  async function renderDlq() {}

  // Expose for later tasks.
  window._integrations = {
    renderOverview: function () { return renderOverview(); },
    renderCache: function () { return renderCache(); },
    renderSiem: function () { return renderSiem(); },
    renderDlq: function () { return renderDlq(); },
    setRender: function (name, fn) {
      if (name === 'overview') renderOverview = fn;
      else if (name === 'cache') renderCache = fn;
      else if (name === 'siem') renderSiem = fn;
      else if (name === 'dlq') renderDlq = fn;
    },
  };
})();

// ── Cache sub-tab ────────────────────────────────────────────────────────────
window._integrations.setRender('cache', async function renderCache() {
  var el = document.getElementById('it-pane-cache');
  if (!el) return;
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';

  var stRes, cfgRes, status, s;
  try {
    var results = await Promise.all([
      fetch('/api/cache/status'), fetch('/api/cache/settings')
    ]);
    stRes = results[0]; cfgRes = results[1];
    status = await stRes.json();
    s = await cfgRes.json();
  } catch (err) {
    el.innerHTML = '<p style="color:red">Failed to load cache data: ' + escapeAttr(String(err)) + '</p>';
    return;
  }

  // Ingestor lag is best-effort: a 503 (cache not configured) or fetch error must
  // not blank out the status cards, so swallow failures and just skip the row.
  var lag = null;
  try { var lr = await fetch('/api/cache/lag'); if (lr.ok) lag = await lr.json(); } catch (_) {}

  var throughput = null;
  try { var tr = await fetch('/api/cache/throughput'); if (tr.ok) throughput = await tr.json(); } catch (_) {}

  var header = buildCacheStatusCards(status, s, throughput);
  var form = buildCacheForm(s);
  el.innerHTML = header + buildCacheLagRow(lag) + form;
  el.dataset.settings = JSON.stringify(s);
  renderTrafficFilter(s);
  renderTrafficSampling(s);
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function buildCacheStatusCards(status, s, throughput) {
  var events     = Number(status.events      || 0);
  var trafficRaw = Number(status.traffic_raw || 0);
  var trafficAgg = Number(status.traffic_agg || 0);
  var stateClass = s.enabled ? 'ok' : 'err';
  var stateText  = s.enabled
    ? '<span style="color:var(--color-success)"><svg class="icon" aria-hidden="true" style="width:13px;height:13px;vertical-align:middle;margin-right:2px;"><use href="#icon-check"></use></svg>' + escapeAttr(_t('gui_cache_enabled')) + '</span>'
    : '<span style="color:var(--color-danger)"><svg class="icon" aria-hidden="true" style="width:13px;height:13px;vertical-align:middle;margin-right:2px;"><use href="#icon-cross"></use></svg>' + escapeAttr(_t('gui_cache_disabled')) + '</span>';

  // 1h ingest counts from throughput endpoint
  var events1h     = throughput && throughput.events_1h     != null ? Number(throughput.events_1h)     : null;
  var trafficRaw1h = throughput && throughput.traffic_raw_1h != null ? Number(throughput.traffic_raw_1h) : null;
  var trafficAgg1h = throughput && throughput.traffic_agg_1h != null ? Number(throughput.traffic_agg_1h) : null;
  function fmt1h(n) {
    if (n == null) return '';
    return ' <span style="font-size:.7rem;color:var(--accent2);" data-i18n="gui_ov_cache_ingest_1h">+' + n.toLocaleString() + ' (1h)</span>';
  }

  return '<div class="cards" style="margin-bottom:16px;">'
    + '<div class="card card-' + stateClass + '">'
    + '<div class="label" data-i18n="gui_cache_status">Cache Status</div>'
    + '<div class="value" style="font-size:1.05rem;">' + stateText + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_ov_events">events</div>'
    + '<div class="value">' + events.toLocaleString() + fmt1h(events1h) + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_cache_card_traffic_raw">Traffic Raw</div>'
    + '<div class="value">' + trafficRaw.toLocaleString() + fmt1h(trafficRaw1h) + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_cache_card_traffic_agg">Traffic Agg</div>'
    + '<div class="value">' + trafficAgg.toLocaleString() + fmt1h(trafficAgg1h) + '</div>'
    + '</div>'
    + '</div>'
    + '<div class="toolbar" style="margin-bottom:16px;">'
    + '<button class="btn btn-sm" data-action="cacheBackfill" data-i18n="gui_backfill">Backfill</button>'
    + '<button class="btn btn-sm" data-action="cacheRetentionNow" data-i18n="gui_retention_now">Retention now</button>'
    + '</div>';
}

// Ingestor lag row: one entry per watermark source, coloured by level (ok/warning/error).
// Returns '' when no watermark data exists yet (cache never synced) so nothing is shown.
function buildCacheLagRow(lag) {
  var sources = (lag && lag.sources) || [];
  if (!sources.length) return '';
  var colors = { ok: 'var(--color-success)', warning: 'var(--color-warning,#f59e0b)', error: 'var(--color-danger)' };
  function fmtLag(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    if (sec < 60)   return sec + 's';
    if (sec < 3600) return Math.floor(sec / 60) + 'm';
    return Math.floor(sec / 3600) + 'h';
  }
  var parts = sources.map(function (r) {
    // A failed ingest still bumps last_sync_at, so a small lag can mask an error —
    // treat last_status 'error' as unhealthy and expose the reason via a tooltip.
    var errored = r.last_status === 'error';
    var c = colors[errored ? 'error' : r.level] || 'var(--dim)';
    var title = (errored && r.last_error) ? ' title="' + escapeAttr(String(r.last_error)) + '"' : '';
    return '<span' + title + '>' + escapeAttr(String(r.source))
      + ' <strong style="color:' + c + '">' + fmtLag(r.lag_seconds)
      + (errored ? ' &#9888;' : '') + '</strong></span>';
  }).join(' &middot; ');
  return '<div class="cache-lag" style="margin:-8px 0 16px;font-size:.85rem;color:var(--dim);">'
    + '<span data-i18n="gui_cache_ingest_lag">Ingestion lag</span>: ' + parts
    + '</div>';
}

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
    + '<small class="form-text text-muted" data-i18n="gui_cache_db_path_help"></small>'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_retention">Retention (days)</legend>'
    + '<div class="form-row-3">'
    + '<div class="form-group"><label data-i18n="gui_ov_events">events</label>'
    + '<input type="number" name="events_retention_days" min="1" value="' + Number(s.events_retention_days || 90) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_events_retention_days_help"></small></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_card_traffic_raw">Traffic Raw</label>'
    + '<input type="number" name="traffic_raw_retention_days" min="1" value="' + Number(s.traffic_raw_retention_days || 30) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_traffic_raw_retention_days_help"></small></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_card_traffic_agg">Traffic Agg</label>'
    + '<input type="number" name="traffic_agg_retention_days" min="1" value="' + Number(s.traffic_agg_retention_days || 30) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_traffic_agg_retention_days_help"></small></div>'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_polling">Polling (seconds)</legend>'
    + '<div class="form-row">'
    + '<div class="form-group"><label>events_poll_interval_seconds</label>'
    + '<input type="number" name="events_poll_interval_seconds" min="30" value="' + Number(s.events_poll_interval_seconds || 30) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_events_poll_interval_seconds_help"></small></div>'
    + '<div class="form-group"><label>traffic_poll_interval_seconds</label>'
    + '<input type="number" name="traffic_poll_interval_seconds" min="60" value="' + Number(s.traffic_poll_interval_seconds || 60) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_traffic_poll_interval_seconds_help"></small></div>'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_throughput">Throughput</legend>'
    + '<div class="form-row">'
    + '<div class="form-group"><label>rate_limit_per_minute</label>'
    + '<input type="number" name="rate_limit_per_minute" min="10" max="500" value="' + Number(s.rate_limit_per_minute || 100) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_rate_limit_per_minute_help"></small></div>'
    + '<div class="form-group"><label>async_threshold_events</label>'
    + '<input type="number" name="async_threshold_events" min="1" max="10000" value="' + Number(s.async_threshold_events || 1000) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_async_threshold_events_help"></small></div>'
    + '</div>'
    + '</fieldset>'
    + '<div id="cache-form-extra"></div>'
    + '<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:8px;">'
    + '<div id="cache-banner" style="flex:1;display:none;"></div>'
    + '<button type="button" class="btn btn-primary" onclick="cacheSave()" data-i18n="gui_save">Save</button>'
    + '</div>'
    + '</form>';
}

async function cacheSave() {
  var form = document.getElementById('cache-form');
  var data = Object.fromEntries(new FormData(form));
  var pane = document.getElementById('it-pane-cache');
  var existing = JSON.parse(pane.dataset.settings);
  var payload = Object.assign({}, existing, {
    enabled: form.elements['enabled'].checked,
    db_path: data.db_path,
    events_retention_days: Number(data.events_retention_days),
    traffic_raw_retention_days: Number(data.traffic_raw_retention_days),
    traffic_agg_retention_days: Number(data.traffic_agg_retention_days),
    events_poll_interval_seconds: Number(data.events_poll_interval_seconds),
    traffic_poll_interval_seconds: Number(data.traffic_poll_interval_seconds),
    rate_limit_per_minute: Number(data.rate_limit_per_minute),
    async_threshold_events: Number(data.async_threshold_events),
    traffic_filter: (typeof window.collectTrafficFilter === 'function')
      ? window.collectTrafficFilter() : existing.traffic_filter,
    traffic_sampling: (typeof window.collectTrafficSampling === 'function')
      ? window.collectTrafficSampling() : existing.traffic_sampling,
  });
  var resp = await fetch('/api/cache/settings', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
    body: JSON.stringify(payload),
  });
  var body = await resp.json();
  var banner = document.getElementById('cache-banner');
  if (body.ok) {
    showRestartBanner(banner);
  } else {
    banner.style.display = 'block';
    banner.textContent = 'Validation error:';
    var ul = document.createElement('ul');
    Object.entries(body.errors || {}).forEach(function(entry) {
      var li = document.createElement('li');
      li.textContent = entry[0] + ': ' + entry[1];
      ul.appendChild(li);
    });
    banner.appendChild(ul);
  }
}

function showRestartBanner(target) {
  target.style.display = 'block';
  target.innerHTML = '';
  var wrap = document.createElement('div');
  wrap.className = 'banner';
  var span = document.createElement('span');
  span.setAttribute('data-i18n', 'gui_restart_required_banner');
  span.textContent = 'Settings saved. Restart monitor to apply scheduling changes.';
  var restartBtn = document.createElement('button');
  restartBtn.className = 'btn btn-primary';
  restartBtn.setAttribute('data-i18n', 'gui_restart_monitor_btn');
  restartBtn.textContent = 'Restart Monitor';
  restartBtn.addEventListener('click', function() { doDaemonRestart(restartBtn, span); });
  var dismissBtn = document.createElement('button');
  dismissBtn.className = 'btn';
  dismissBtn.setAttribute('data-i18n', 'gui_dismiss');
  dismissBtn.textContent = 'Dismiss';
  dismissBtn.addEventListener('click', function() { target.style.display = 'none'; });
  wrap.appendChild(span);
  wrap.appendChild(restartBtn);
  wrap.appendChild(dismissBtn);
  target.appendChild(wrap);
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

async function doDaemonRestart(btn, msgSpan) {
  btn.disabled = true;
  var original = btn.textContent;
  btn.textContent = '…';
  try {
    var resp = await fetch('/api/daemon/restart', {method: 'POST', headers: {'X-CSRF-Token': _csrfToken()}});
    var body = await resp.json();
    if (resp.status === 409) {
      msgSpan.textContent = _t('gui_daemon_external_restart_hint');
      msgSpan.removeAttribute('data-i18n');
      btn.style.display = 'none';
      return;
    }
    if (body.ok) {
      btn.textContent = 'OK';
      msgSpan.textContent = _t('gui_restart_success');
      msgSpan.removeAttribute('data-i18n');
      setTimeout(function() {
        if (btn.parentElement && btn.parentElement.parentElement) {
          btn.parentElement.parentElement.style.display = 'none';
        }
      }, 1500);
    } else {
      btn.textContent = original;
      btn.disabled = false;
      alert(_t('gui_restart_failed') + ': ' + (body.error || ''));
    }
  } catch (exc) {
    btn.textContent = original;
    btn.disabled = false;
    alert(_t('gui_restart_failed') + ': ' + exc);
  }
}

// Open the Cache Backfill modal with a sensible default (last 7 days).
function cacheBackfill() {
  if (typeof setDateRange === 'function') setDateRange('cb', 7);
  var src = document.getElementById('cb-source');
  if (src) src.value = 'events';
  var result = document.getElementById('cb-result');
  if (result) { result.style.display = 'none'; result.textContent = ''; }
  if (typeof openModal === 'function') openModal('m-cache-backfill');
}

async function submitCacheBackfill() {
  var sourceEl = document.getElementById('cb-source');
  var startEl = document.getElementById('cb-start');
  var endEl = document.getElementById('cb-end');
  var btn = document.getElementById('cb-submit');
  var result = document.getElementById('cb-result');
  var source = (sourceEl && sourceEl.value) || 'events';
  var start = startEl && startEl.value;
  var end = endEl && endEl.value;
  if (!start || !end) {
    if (result) {
      result.style.display = 'block';
      result.style.color = 'var(--color-danger)';
      result.textContent = (typeof _t === 'function' ? _t('gui_cb_dates_required') : 'Start and end dates are required.');
    }
    return;
  }
  if (btn) btn.disabled = true;
  if (result) {
    result.style.display = 'block';
    result.style.color = 'var(--dim)';
    result.textContent = (typeof _t === 'function' ? _t('gui_cb_running') : 'Running…');
  }
  try {
    var r = await fetch('/api/cache/backfill', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({source: source, since: start, until: end}),
    });
    var body = await r.json().catch(function() { return {}; });
    if (!r.ok) {
      if (result) {
        result.style.color = 'var(--color-danger)';
        result.textContent = 'Backfill failed: ' + (body.error || r.status);
      }
      return;
    }
    if (result) {
      result.style.color = 'var(--accent2,var(--fg))';
      result.textContent = 'Done — source: ' + source
        + ' · inserted: ' + (body.inserted || 0)
        + ' · duplicates: ' + (body.duplicates || 0)
        + ' · total: ' + (body.total_rows || 0)
        + ' · ' + (body.elapsed_seconds || 0) + 's';
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function cacheRetentionNow() {
  if (!confirm('Run retention purge now? This will delete cache rows older than the configured retention days.')) return;
  var r = await fetch('/api/cache/retention/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
  });
  var body = await r.json().catch(function() { return {}; });
  if (!r.ok) {
    alert('Retention failed: ' + (body.error || r.status));
    return;
  }
  alert('Retention done — events: ' + (body.events || 0)
    + ', traffic_raw: ' + (body.traffic_raw || 0)
    + ', traffic_agg: ' + (body.traffic_agg || 0)
    + ', dead_letter: ' + (body.dead_letter || 0));
}
window.cacheBackfill = cacheBackfill;
window.submitCacheBackfill = submitCacheBackfill;
window.cacheRetentionNow = cacheRetentionNow;

// ── Cache traffic_filter section ────────────────────────────────────────────
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
    + '<input id="tf-env" value="' + envVals + '" placeholder="prod,staging">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_workload_label_env_help"></small></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_ports">Ports</label>'
    + '<input id="tf-ports" value="' + portVals + '" placeholder="22,443,...">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_ports_help"></small></div>'
    + '</div>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_exclude_ips">Exclude src IPs</label>'
    + '<input id="tf-ips" value="' + ipVals + '" placeholder="10.0.0.1,...">'
    + '<small class="form-text text-muted" data-i18n="gui_cache_exclude_src_ips_help"></small></div>'
    + '<div id="tf-validation-hints" style="color:var(--color-danger);font-size:.8rem;"></div>'
    + '</fieldset>';

  var extra = document.getElementById('cache-form-extra');
  if (extra) extra.innerHTML = html;
}

window.collectTrafficFilter = function () {
  function pick(sel) {
    return Array.from(document.querySelectorAll(sel)).map(function(el) { return el.value; });
  }
  function parse(id) {
    var el = document.getElementById(id);
    return (el ? el.value : '').split(',').map(function(x) { return x.trim(); }).filter(Boolean);
  }
  return {
    actions: pick('input[name="tf-action"]:checked'),
    workload_label_env: parse('tf-env'),
    ports: parse('tf-ports').map(Number).filter(function(n) { return Number.isFinite(n); }),
    protocols: pick('input[name="tf-protocol"]:checked'),
    exclude_src_ips: parse('tf-ips'),
  };
};

function validateIp(s) {
  if (/^(\d{1,3}\.){3}\d{1,3}$/.test(s)) {
    return s.split('.').every(function(o) { return Number(o) <= 255; });
  }
  return /^[\da-fA-F:]+$/.test(s) && s.indexOf(':') >= 0;
}

function validateTrafficFilterHints() {
  var hints = [];
  var ipsEl = document.getElementById('tf-ips');
  var ips = (ipsEl ? ipsEl.value : '').split(',').map(function(s) { return s.trim(); }).filter(Boolean);
  ips.forEach(function(ip) { if (!validateIp(ip)) hints.push(_t('gui_err_invalid_ip') + ': ' + ip); });
  var portsEl = document.getElementById('tf-ports');
  var ports = (portsEl ? portsEl.value : '').split(',').map(function(s) { return s.trim(); }).filter(Boolean);
  ports.forEach(function(p) {
    var n = Number(p);
    if (!Number.isInteger(n) || n < 1 || n > 65535) hints.push(_t('gui_err_port_range') + ': ' + p);
  });
  var el = document.getElementById('tf-validation-hints');
  if (el) el.textContent = hints.join(' · ');
}

const _debouncedTrafficFilterHints = window.debounce(function(target) {
  validateTrafficFilterHints();
  setTimeout(() => target.classList.remove('input-loading'), 50);
}, 300);
document.addEventListener('input', function(e) {
  if (e.target && (e.target.id === 'tf-ips' || e.target.id === 'tf-ports')) {
    e.target.classList.add('input-loading');
    _debouncedTrafficFilterHints(e.target);
  }
});

// ── Cache traffic_sampling section ───────────────────────────────────────────
function renderTrafficSampling(s) {
  var ts      = s.traffic_sampling || {};
  var ratio   = Number(ts.sample_ratio_allowed || 1);
  var maxRows = Number(ts.max_rows_per_batch || 200000);
  var html = '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_traffic_sampling">Traffic Sampling</legend>'
    + '<div class="form-row">'
    + '<div class="form-group">'
    +   '<label data-i18n="gui_cache_ts_ratio">Sampling ratio (Allowed traffic)</label>'
    +   '<input type="number" id="ts-ratio" min="1" value="' + ratio + '">'
    +   '<small class="form-text text-muted" data-i18n="gui_cache_ts_ratio_help"></small>'
    + '</div>'
    + '<div class="form-group">'
    +   '<label data-i18n="gui_cache_ts_max_rows">Max rows per batch</label>'
    +   '<input type="number" id="ts-max" min="1" max="200000" value="' + maxRows + '">'
    +   '<small class="form-text text-muted" data-i18n="gui_cache_ts_max_rows_help"></small>'
    + '</div>'
    + '</div>'
    + '</fieldset>';
  var extra = document.getElementById('cache-form-extra');
  if (extra) extra.insertAdjacentHTML('beforeend', html);
}

window.collectTrafficSampling = function () {
  var ratioEl = document.getElementById('ts-ratio');
  var maxEl = document.getElementById('ts-max');
  return {
    sample_ratio_allowed: Number(ratioEl ? ratioEl.value : 1),
    max_rows_per_batch: Number(maxEl ? maxEl.value : 200000),
  };
};

// ── SIEM sub-tab ─────────────────────────────────────────────────────────────
window._integrations.setRender('siem', async function renderSiem() {
  var el = document.getElementById('it-pane-siem');
  if (!el) return;
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';

  var fw, destsBody, status;
  try {
    var results = await Promise.all([
      fetch('/api/siem/forwarder').then(function(r) { return r.json(); }),
      fetch('/api/siem/destinations').then(function(r) { return r.json(); }),
      fetch('/api/siem/status').then(function(r) { return r.json(); }),
    ]);
    fw = results[0]; destsBody = results[1]; status = results[2];
  } catch (err) {
    el.innerHTML = '<p style="color:red">Failed to load SIEM data: ' + escapeAttr(String(err)) + '</p>';
    return;
  }
  var dests = destsBody.destinations || destsBody || [];

  // ── KPI strip ──────────────────────────────────────────────────────────────────────────────────
  var siemRows = (status && status.status) || [];
  var kpiSent = 0, kpiFailed = 0, kpiDlq = 0;
  var kpiSent1h = 0, kpiFailed1h = 0;
  var kpiLatencyWsum = 0, kpiLatencyWtotal = 0;
  siemRows.forEach(function(d) {
    kpiSent   += Number(d.sent    || 0);
    kpiFailed += Number(d.failed  || 0);
    kpiDlq    += Number(d.dlq     || 0);
    var s1h = Number(d.sent_1h   || 0);
    var f1h = Number(d.failed_1h || 0);
    kpiSent1h   += s1h;
    kpiFailed1h += f1h;
    var w = s1h + f1h;
    if (w > 0 && d.avg_latency_ms != null) {
      kpiLatencyWsum   += Number(d.avg_latency_ms) * w;
      kpiLatencyWtotal += w;
    }
  });
  var kpiRateColor = kpiFailed > 0 ? 'var(--color-danger,#f43f5e)' : 'var(--color-success,#22c55e)';
  var kpiDlqColor  = kpiDlq   > 0 ? 'var(--warn,#f59e0b)' : 'inherit';

  // 1h success rate (weighted across destinations)
  var kpiAttempts1h = kpiSent1h + kpiFailed1h;
  var kpiRate1h = kpiAttempts1h > 0
    ? (kpiSent1h / kpiAttempts1h * 100).toFixed(1) + '%'
    : '\u2014';
  var kpiRate1hColor = kpiFailed1h > 0 ? 'var(--color-danger,#f43f5e)' : 'var(--color-success,#22c55e)';

  // Weighted average latency across destinations
  var kpiLatencyStr = '\u2014';
  if (kpiLatencyWtotal > 0) {
    var avgMs = kpiLatencyWsum / kpiLatencyWtotal;
    kpiLatencyStr = avgMs < 1000 ? Math.round(avgMs) + 'ms' : (avgMs / 1000).toFixed(1) + 's';
  }

  var kpiHtml = '<div class="it-kpi-strip">'
    + '<div class="it-kpi-cell"><div class="it-kpi-label" data-i18n="gui_ov_sent">\u7e3d\u9001\u51fa</div>'
    + '<div class="it-kpi-value">' + kpiSent.toLocaleString() + '</div></div>'
    + '<div class="it-kpi-cell"><div class="it-kpi-label" data-i18n="gui_ov_siem_success_1h">\u6210\u529f\u7387 (1h)</div>'
    + '<div class="it-kpi-value" style="color:' + kpiRate1hColor + ';">' + kpiRate1h + '</div></div>'
    + '<div class="it-kpi-cell"><div class="it-kpi-label">DLQ \u7d2f\u7a4d</div>'
    + '<div class="it-kpi-value" style="color:' + kpiDlqColor + ';">' + kpiDlq + '</div></div>'
    + '<div class="it-kpi-cell"><div class="it-kpi-label" data-i18n="gui_ov_siem_latency">\u5e73\u5747\u5ef6\u9072</div>'
    + '<div class="it-kpi-value it-kpi-muted">' + kpiLatencyStr + '</div></div>'
    + '</div>';

  el.innerHTML = kpiHtml + buildSiemForwarderForm(fw) + buildSiemDestinationsSection();

  var tbody = document.getElementById('siem-dest-tbody');
  // Build a name→stats lookup from status.status rows (status.per_destination is not populated)
  var perDestMap = {};
  siemRows.forEach(function(d) { if (d.destination) perDestMap[d.destination] = d; });
  var rows = dests.map(function(d) { return buildSiemRow(d, perDestMap[d.name] || {}); }).join('');
  tbody.innerHTML = rows || '<tr><td colspan="6" style="color:var(--dim);">(none)</td></tr>';
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

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

function buildSiemForwarderForm(fw) {
  return '<section class="rs-glass" style="margin-bottom:16px;">'
    + '<h3 style="color:var(--accent2);margin:0 0 14px;" data-i18n="gui_siem_forwarder">Forwarder</h3>'
    + '<div class="form-row">'
    + '<div class="form-group">'
    + '<label data-i18n="gui_siem_dispatch_tick">dispatch_tick_seconds</label>'
    + '<input type="number" id="siem-tick" min="1" value="' + Number(fw.dispatch_tick_seconds || 10) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_siem_dispatch_tick_help"></small>'
    + '</div>'
    + '<div class="form-group">'
    + '<label data-i18n="gui_siem_dlq_max">dlq_max_per_dest</label>'
    + '<input type="number" id="siem-dlq-max" min="100" value="' + Number(fw.dlq_max_per_dest || 500) + '">'
    + '<small class="form-text text-muted" data-i18n="gui_siem_dlq_max_help"></small>'
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

function buildSiemDestinationsSection() {
  return '<section class="rs-glass">'
    + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
    + '<h3 style="color:var(--accent2);margin:0;" data-i18n="gui_siem_destinations">Destinations</h3>'
    + '<button class="btn btn-sm" onclick="siemOpenDestModal()" data-i18n="gui_siem_add">+ Add</button>'
    + '</div>'
    + '<div class="table-container">'
    + '<table class="rule-table">'
    + '<colgroup>'
    + '<col style="width:18%"><col style="width:10%"><col style="width:12%"><col style="width:20%"><col style="width:7%"><col style="width:14%"><col>'
    + '</colgroup>'
    + '<thead><tr>'
    + '<th data-i18n="gui_siem_th_name">Name</th>'
    + '<th data-i18n="gui_siem_th_transport">Transport</th>'
    + '<th data-i18n="gui_siem_th_format">Format</th>'
    + '<th data-i18n="gui_siem_th_host">Host</th>'
    + '<th data-i18n="gui_siem_th_port">Port</th>'
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

function buildSiemRow(d, st) {
  var nameEnc = encodeURIComponent(d.name).replace(/'/g, '%27');
  var dim = d.enabled ? '' : ' <span style="color:var(--dim);font-size:.8rem;">(disabled)</span>';
  return '<tr>'
    + '<td><b>' + escapeAttr(d.name) + '</b>' + dim + '</td>'
    + '<td><code>' + escapeAttr(d.transport) + '</code>'
    + ((/udp/i.test(d.transport)) ? ' <span class="it-chip-noack" title="UDP — no ACK, DLQ confirmation not supported">No ACK · Monitor</span>' : '')
    + '</td>'
    + '<td><code>' + escapeAttr(d.format) + '</code></td>'
    + '<td>' + escapeAttr(d.host || '') + '</td>'
    + '<td>' + Number(d.port || 514) + '</td>'
    + '<td>' + _siemStatusBadge(d, st) + '</td>'
    + '<td style="white-space:nowrap;">'
    + '<button class="btn btn-sm" onclick="siemTestDest(\'' + nameEnc + '\')" data-i18n="gui_siem_test">Test</button> '
    + '<button class="btn btn-sm" onclick="siemOpenDestModal(\'' + nameEnc + '\')" data-i18n="gui_siem_edit">Edit</button> '
    + '<button class="btn btn-sm btn-danger" onclick="siemDeleteDest(\'' + nameEnc + '\')" data-i18n="gui_siem_delete">Delete</button>'
    + '</td>'
    + '</tr>';
}

async function siemSaveForwarder() {
  var payload = {
    enabled: document.getElementById('siem-enabled').checked,
    dispatch_tick_seconds: Number(document.getElementById('siem-tick').value),
    dlq_max_per_dest: Number(document.getElementById('siem-dlq-max').value),
  };
  var resp = await fetch('/api/siem/forwarder', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
    body: JSON.stringify(payload),
  });
  var body = await resp.json();
  var banner = document.getElementById('siem-banner');
  if (body.ok) {
    showRestartBanner(banner);
  } else {
    banner.textContent = 'Validation error: ' + JSON.stringify(body.errors || body.error || '');
  }
}

async function siemDeleteDest(nameEnc) {
  var name = decodeURIComponent(nameEnc);
  var confirmMsg = (typeof _t === 'function') ? _t('gui_confirm_delete') : 'Delete this destination?';
  if (!confirm(confirmMsg)) return;
  var r = await fetch('/api/siem/destinations/' + encodeURIComponent(name), {method: 'DELETE', headers: {'X-CSRF-Token': _csrfToken()}});
  if (!r.ok) { alert('Delete failed: HTTP ' + r.status); return; }
  window._integrations.renderSiem();
}

async function siemOpenDestModal(nameEnc) {
  var name = nameEnc ? decodeURIComponent(nameEnc) : null;
  var dest = {
    name: '', enabled: true, transport: 'udp', format: 'cef',
    host: '', port: 514, tls_verify: true, tls_ca_bundle: '', hec_token: '',
    batch_size: 100, source_types: ['audit', 'traffic'], max_retries: 10
  };
  if (name) {
    try {
      var body = await fetch('/api/siem/destinations').then(function(r) { return r.json(); });
      var all = body.destinations || body || [];
      var found = all.filter(function(d) { return d.name === name; })[0];
      if (!found) {
        console.warn('Destination not found:', name);
        return;
      }
      dest = Object.assign(dest, found);
    } catch (err) {
      // If fetch fails, proceed with default values
      console.warn('Could not load destination data:', err);
    }
  }
  document.getElementById('siem-modal-host').innerHTML = buildDestModal(dest, name);
  siemToggleCondFields();
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

var _SIEM_DEFAULT_PORTS = { udp: 514, tcp: 514, tls: 6514, hec: 8088 };

function buildDestModal(dest, editName) {
  var nameVal = escapeAttr(dest.name);
  var host = escapeAttr(dest.host || '');
  var port = Number(dest.port) || 514;
  var caBundle = escapeAttr(dest.tls_ca_bundle || '');
  var hecToken = escapeAttr(dest.hec_token || '');
  var readonly = editName ? ' readonly' : '';
  var editAttr = editName ? encodeURIComponent(editName).replace(/'/g, '%27') : '';
  var titleKey = editName ? 'gui_siem_modal_title_edit' : 'gui_siem_modal_title_add';
  var titleText = editName ? 'Edit' : 'Add';
  var sourceTypes = dest.source_types || [];

  function mkOpts(list, cur) {
    return list.map(function(v) {
      return '<option' + (v === cur ? ' selected' : '') + '>' + escapeAttr(v) + '</option>';
    }).join('');
  }

  return '<div class="modal-backdrop" onclick="siemCloseModal(event)">'
    + '<div class="modal" onclick="event.stopPropagation()">'
    + '<h2 data-i18n="' + titleKey + '">' + titleText + ' destination</h2>'

    + '<h3 data-i18n="gui_siem_sec_basic">Basic</h3>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_siem_name">Name</label>'
    + '<input id="md-name" value="' + nameVal + '"' + readonly + '></div>'
    + '<div class="form-group" style="flex:0 0 auto;align-self:flex-end;padding-bottom:4px">'
    + '<label><input type="checkbox" id="md-enabled"' + (dest.enabled ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_siem_enabled">Enabled</span></label></div>'
    + '</div>'
    + '<div class="form-group"><label data-i18n="gui_siem_source_types">Forwarding Content</label>'
    + '<div style="display:flex;gap:16px;margin-top:4px">'
    + '<label><input type="checkbox" name="md-st" value="audit"' + (sourceTypes.indexOf('audit') >= 0 ? ' checked' : '') + '> Audit Events</label>'
    + '<label><input type="checkbox" name="md-st" value="traffic"' + (sourceTypes.indexOf('traffic') >= 0 ? ' checked' : '') + '> Traffic Flows</label>'
    + '</div></div>'

    + '<h3 data-i18n="gui_siem_sec_transport">Transport</h3>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_siem_transport">Transport</label>'
    + '<select id="md-transport" onchange="siemToggleCondFields()">' + mkOpts(['udp', 'tcp', 'tls', 'hec'], dest.transport) + '</select>'
    + '<small class="form-text text-muted" data-i18n="gui_siem_transport_help"></small></div>'
    + '<div class="form-group"><label data-i18n="gui_siem_format">Format</label>'
    + '<select id="md-format">' + mkOpts(['cef', 'json', 'syslog_cef', 'syslog_json'], dest.format) + '</select>'
    + '<small class="form-text text-muted" data-i18n="gui_siem_format_help"></small></div>'
    + '</div>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_siem_host">Server Address</label>'
    + '<input id="md-host" value="' + host + '" placeholder="192.168.1.10"></div>'
    + '<div class="form-group" style="flex:0 0 100px"><label data-i18n="gui_siem_port">Port</label>'
    + '<input type="number" id="md-port" min="1" max="65535" value="' + port + '"></div>'
    + '</div>'

    + '<div id="md-tls-section">'
    + '<h3 data-i18n="gui_siem_sec_tls">TLS</h3>'
    + '<label><input type="checkbox" id="md-tls-verify"' + (dest.tls_verify ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_siem_tls_verify">Verify TLS Certificate</span></label>'
    + '<div class="form-group" style="margin-top:8px"><label data-i18n="gui_siem_ca_bundle">CA Bundle Path</label>'
    + '<input id="md-tls-ca" value="' + caBundle + '" placeholder="/etc/ssl/certs/ca-bundle.crt"></div>'
    + '</div>'

    + '<div id="md-hec-section">'
    + '<h3 data-i18n="gui_siem_sec_hec">HEC</h3>'
    + '<div class="form-group"><label data-i18n="gui_siem_hec_token">HEC Token</label>'
    + '<input type="password" id="md-hec-token" value="' + hecToken + '"></div>'
    + '</div>'

    + '<details style="margin-top:14px">'
    + '<summary style="cursor:pointer;font-weight:600;padding:4px 0" data-i18n="gui_siem_sec_advanced">Advanced</summary>'
    + '<div style="margin-top:10px">'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_siem_batch_size">Batch Size</label>'
    + '<input type="number" id="md-batch" min="1" max="10000" value="' + Number(dest.batch_size) + '"></div>'
    + '<div class="form-group"><label data-i18n="gui_siem_max_retries">Max Retries</label>'
    + '<input type="number" id="md-retries" min="0" value="' + Number(dest.max_retries) + '"></div>'
    + '</div></div>'
    + '</details>'

    + '<div id="md-banner" style="margin-top:10px;color:var(--color-danger);"></div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">'
    + '<button class="btn" onclick="siemCloseModal(event)" data-i18n="gui_cancel">Cancel</button>'
    + '<button class="btn" onclick="siemTestDestInline()" data-i18n="gui_siem_test_inline">Test Connection</button>'
    + '<button class="btn btn-primary" onclick="siemSaveDest(\'' + editAttr + '\')" data-i18n="gui_save">Save</button>'
    + '</div>'
    + '</div>'
    + '</div>';
}

function siemToggleCondFields() {
  var transport = document.getElementById('md-transport');
  if (!transport) return;
  var t = transport.value;
  var tlsEl = document.getElementById('md-tls-section');
  var hecEl = document.getElementById('md-hec-section');
  if (tlsEl) tlsEl.style.display = (t === 'tls' || t === 'hec') ? '' : 'none';
  if (hecEl) hecEl.style.display = (t === 'hec') ? '' : 'none';
  // Auto-fill default port only if port field is still at a known default value
  var portEl = document.getElementById('md-port');
  if (portEl) {
    var cur = Number(portEl.value);
    var defaults = Object.values(_SIEM_DEFAULT_PORTS);
    if (defaults.indexOf(cur) >= 0 || cur === 514) {
      portEl.value = _SIEM_DEFAULT_PORTS[t] || 514;
    }
  }
}

function siemCloseModal() {
  var host = document.getElementById('siem-modal-host');
  if (host) host.innerHTML = '';
}

async function siemSaveDest(editNameEnc) {
  var editName = editNameEnc ? decodeURIComponent(editNameEnc) : '';
  var sourceTypes = Array.from(document.querySelectorAll('input[name="md-st"]:checked'))
    .map(function(el) { return el.value; });
  var payload = {
    name: editName || document.getElementById('md-name').value.trim(),
    enabled: document.getElementById('md-enabled').checked,
    transport: document.getElementById('md-transport').value,
    format: document.getElementById('md-format').value,
    host: document.getElementById('md-host').value.trim(),
    port: Number(document.getElementById('md-port').value),
    tls_verify: document.getElementById('md-tls-verify').checked,
    tls_ca_bundle: document.getElementById('md-tls-ca').value.trim() || null,
    hec_token: document.getElementById('md-hec-token').value || null,
    batch_size: Number(document.getElementById('md-batch').value),
    max_retries: Number(document.getElementById('md-retries').value),
    source_types: sourceTypes.length ? sourceTypes : ['audit', 'traffic'],
  };
  var resp, body;
  try {
    if (editName) {
      resp = await fetch('/api/siem/destinations/' + encodeURIComponent(editName), {
        method: 'PUT', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
        body: JSON.stringify(payload),
      });
    } else {
      resp = await fetch('/api/siem/destinations', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
        body: JSON.stringify(payload),
      });
    }
    body = await resp.json();
  } catch (err) {
    document.getElementById('md-banner').textContent = 'Save failed: ' + String(err);
    return;
  }
  if (resp.ok && body.ok !== false) {
    siemCloseModal();
    await window._integrations.renderSiem();
    showRestartBanner(document.getElementById('siem-banner'));
  } else {
    var banner = document.getElementById('md-banner');
    if (banner) banner.textContent = 'Save failed: ' + (body.error || JSON.stringify(body.errors || body));
  }
}

async function siemTestDest(nameEnc) {
  var name = decodeURIComponent(nameEnc);
  var resp, body;
  try {
    resp = await fetch('/api/siem/destinations/' + encodeURIComponent(name) + '/test', {method: 'POST', headers: {'X-CSRF-Token': _csrfToken()}});
    body = await resp.json();
  } catch (err) {
    alert('Test error: ' + String(err));
    return;
  }
  var msg = body.ok
    ? 'OK: ' + _t('gui_siem_test_ok') + ' (' + _t('gui_siem_test_latency') + ': ' + Number(body.latency_ms) + ' ms)'
    : 'FAIL: ' + _t('gui_siem_test_fail') + ': ' + String(body.error || '');
  alert(msg);
}

async function siemTestDestInline() {
  var banner = document.getElementById('md-banner');
  if (!banner) return;
  banner.style.color = '';
  banner.textContent = 'Testing…';
  var name = (document.getElementById('md-name') || {}).value || '';
  name = name.trim();
  if (!name) {
    banner.textContent = 'Enter name, then Save, then Test.';
    return;
  }
  var resp, body;
  try {
    resp = await fetch('/api/siem/destinations/' + encodeURIComponent(name) + '/test', {method: 'POST', headers: {'X-CSRF-Token': _csrfToken()}});
    body = await resp.json();
  } catch (err) {
    banner.textContent = 'Test error: ' + String(err);
    return;
  }
  if (resp.status === 404) {
    banner.textContent = 'Destination not yet saved. Save first, then Test.';
  } else if (body.ok) {
    banner.style.color = 'var(--ok, green)';
    banner.textContent = 'OK: ' + _t('gui_siem_test_ok') + ' (' + _t('gui_siem_test_latency') + ': ' + Number(body.latency_ms) + ' ms)';
  } else {
    banner.style.color = 'var(--color-danger)';
    banner.textContent = 'FAIL: ' + _t('gui_siem_test_fail') + ': ' + String(body.error || '');
  }
}
window.siemTestDest = siemTestDest;
window.siemTestDestInline = siemTestDestInline;

window.siemSaveForwarder = siemSaveForwarder;
window.siemDeleteDest = siemDeleteDest;
window.siemOpenDestModal = siemOpenDestModal;
window.siemToggleCondFields = siemToggleCondFields;
window.siemCloseModal = siemCloseModal;
window.siemSaveDest = siemSaveDest;

// ── DLQ sub-tab ──────────────────────────────────────────────────────────────
var _dlqPage = 1;
var DLQ_PAGE_SIZE = 50;
var DLQ_MAX_PAGE = Math.floor(500 / DLQ_PAGE_SIZE); // API cap is 500 entries

window._integrations.setRender('dlq', async function renderDlq() {
  var el = document.getElementById('it-pane-dlq');
  if (!el) return;
  el.innerHTML = buildDlqSkeleton();
  await populateDlqDestinations();
  await dlqSearch();
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function _fmtShortDt(iso) {
  if (!iso) return '—';
  var d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  var M = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return M[d.getMonth()] + ' ' + String(d.getDate()).padStart(2, '0')
    + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

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
    + '<th data-i18n="gui_dlq_th_retries">Retries</th>'
    + '<th></th>'
    + '</tr></thead>'
    + '<tbody id="dlq-tbody"></tbody>'
    + '</table>'
    + '</div>'
    + '<div id="dlq-empty-state" class="it-dlq-empty" style="display:none;">'
    + '<div class="it-dlq-empty-icon">∅</div>'
    + '<h3>DLQ is empty</h3>'
    + '<p>All destinations are currently delivering normally. To test backfill, temporarily point the host to a blackhole IP (e.g. 192.0.2.1) and send an event.</p>'
    + '</div>'
    + '<div id="dlq-pager" style="margin-top:8px;"></div>'
    + '<div id="dlq-modal-host"></div>';
}

async function populateDlqDestinations() {
  try {
    var body = await fetch('/api/siem/destinations').then(function(r) { return r.json(); });
    var dests = body.destinations || body || [];
    var sel = document.getElementById('dlq-dest');
    if (!sel) return;
    dests.forEach(function(d) {
      var opt = document.createElement('option');
      opt.value = d.name;
      opt.textContent = d.name;
      sel.appendChild(opt);
    });
  } catch (err) {
    console.warn('Could not load destinations for DLQ filter:', err);
  }
}

async function dlqSearch() {
  _dlqPage = 1;
  await _dlqLoadPage();
}

async function _dlqLoadPage() {
  var destEl = document.getElementById('dlq-dest');
  var reasonEl = document.getElementById('dlq-reason');
  var dest = destEl ? destEl.value : '';
  var reason = reasonEl ? reasonEl.value.trim() : '';

  var q = new URLSearchParams();
  if (dest) q.set('dest', dest);
  // Fetch enough for current page (API has no offset)
  q.set('limit', String(DLQ_PAGE_SIZE * _dlqPage));

  var allEntries = [];
  try {
    var body = await fetch('/api/siem/dlq?' + q.toString()).then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
    allEntries = body.entries || body || [];
  } catch (err) {
    var tbody = document.getElementById('dlq-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="color:red">Failed to load: ' + escapeAttr(String(err)) + '</td></tr>';
    return;
  }

  // Client-side reason filter
  if (reason) {
    var reasonLower = reason.toLowerCase();
    allEntries = allEntries.filter(function(e) {
      return (e.last_error || '').toLowerCase().indexOf(reasonLower) >= 0;
    });
  }

  var pageEntries = allEntries.slice((_dlqPage - 1) * DLQ_PAGE_SIZE, _dlqPage * DLQ_PAGE_SIZE);
  window._dlqCurrentEntries = pageEntries;
  var tbody = document.getElementById('dlq-tbody');
  if (!tbody) return;
  var dlqEmptyEl = document.getElementById('dlq-empty-state');
  if (pageEntries.length === 0) {
    tbody.innerHTML = '';
    if (dlqEmptyEl) dlqEmptyEl.style.display = '';
  } else {
    if (dlqEmptyEl) dlqEmptyEl.style.display = 'none';
    tbody.innerHTML = pageEntries.map(buildDlqRow).join('');
  }

  var pager = document.getElementById('dlq-pager');
  if (pager) {
    var hasMore = allEntries.length >= DLQ_PAGE_SIZE * _dlqPage;
    var atMax = _dlqPage >= DLQ_MAX_PAGE;
    pager.innerHTML = _t('gui_dlq_page') + ' ' + _dlqPage + ' · '
      + '<button class="btn" onclick="dlqPrevPage()"' + (_dlqPage <= 1 ? ' disabled' : '') + '>‹</button>'
      + ' <button class="btn" onclick="dlqNextPage()"' + (!hasMore || atMax ? ' disabled' : '') + '>›</button>';
  }
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

function buildDlqRow(e) {
  var id     = Number(e.id);
  var reason = String(e.last_error || '');
  return '<tr>'
    + '<td><input type="checkbox" class="dlq-chk" value="' + id + '"></td>'
    + '<td><code>' + escapeAttr(e.destination || e.source_table || '') + '</code></td>'
    + '<td style="font-size:.78rem;color:var(--dim);">' + escapeAttr(String(e.source_id || '')) + '</td>'
    + '<td title="' + escapeAttr(reason) + '">' + escapeAttr(reason) + '</td>'
    + '<td style="font-size:.78rem;color:var(--dim);">' + escapeAttr(_fmtShortDt(e.quarantined_at)) + '</td>'
    + '<td style="text-align:center;">' + Number(e.retries || 0) + '</td>'
    + '<td style="white-space:nowrap;">'
    + '<button class="btn btn-sm" onclick="dlqView(' + id + ')" data-i18n="gui_dlq_view">View</button> '
    + '<button class="btn btn-sm" onclick="dlqReplay([' + id + '])" data-i18n="gui_dlq_replay">Replay</button>'
    + '</td>'
    + '</tr>';
}

function dlqPrevPage() { if (_dlqPage > 1) { _dlqPage--; _dlqLoadPage(); } }
function dlqNextPage() { if (_dlqPage < DLQ_MAX_PAGE) { _dlqPage++; _dlqLoadPage(); } }

// ── DLQ bulk actions ─────────────────────────────────────────────────────────

function dlqSelectAll() {
  document.querySelectorAll('.dlq-chk').forEach(function(c) { c.checked = true; });
}

function _dlqSelectedIds() {
  return Array.from(document.querySelectorAll('.dlq-chk:checked')).map(function(c) { return Number(c.value); });
}

async function dlqReplaySelected() {
  var ids = _dlqSelectedIds();
  if (!ids.length) return;
  try {
    var r = await fetch('/api/siem/dlq/replay', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({ids: ids}),
    });
    if (!r.ok) { alert('Request failed: HTTP ' + r.status); return; }
    var body = await r.json();
    // Show per-item requeued results if available
    if (body && body.requeued) {
      var summary = body.requeued.map(function(item) {
        return 'id=' + item.id + ': ' + (item.ok ? 'requeued' : 'skipped');
      }).join('\n');
      console.info('[DLQ replay]', summary);
    }
  } catch (err) { alert('Replay error: ' + String(err)); return; }
  dlqSearch();
}

async function dlqReplay(ids) {
  if (!ids || !ids.length) return;
  try {
    var r = await fetch('/api/siem/dlq/replay', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({ids: ids}),
    });
    if (!r.ok) { alert('Request failed: HTTP ' + r.status); return; }
    var body = await r.json();
    if (body && body.requeued) {
      var summary = body.requeued.map(function(item) {
        return 'id=' + item.id + ': ' + (item.ok ? 'requeued' : 'skipped');
      }).join('\n');
      console.info('[DLQ replay]', summary);
    }
  } catch (err) { alert('Replay error: ' + String(err)); return; }
  dlqSearch();
}

async function dlqPurgeSelected() {
  var ids = _dlqSelectedIds();
  if (!ids.length) return;
  var dest = (document.getElementById('dlq-dest') || {}).value || '';
  if (!dest) { alert('Select a destination filter first.'); return; }
  if (!confirm('Purge ' + ids.length + ' entries from ' + dest + '?')) return;
  try {
    var r = await fetch('/api/siem/dlq/purge', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({dest: dest, older_than_days: 0}),
    });
    if (!r.ok) { alert('Request failed: HTTP ' + r.status); return; }
  } catch (err) { alert('Purge error: ' + String(err)); return; }
  dlqSearch();
}

async function dlqPurgeAll() {
  var dest = (document.getElementById('dlq-dest') || {}).value || '';
  if (!dest) { alert('Pick a destination first.'); return; }
  var confirmMsg = (typeof _t === 'function') ? _t('gui_dlq_confirm_purge_all') : 'Type the destination name to confirm Purge ALL';
  var typed = prompt(confirmMsg, '');
  if (typed !== dest) return;
  try {
    var r = await fetch('/api/siem/dlq/purge', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({dest: dest, older_than_days: 0}),
    });
    if (!r.ok) { alert('Request failed: HTTP ' + r.status); return; }
  } catch (err) { alert('Purge error: ' + String(err)); return; }
  dlqSearch();
}

function dlqExport() {
  var destEl = document.getElementById('dlq-dest');
  var dest = destEl ? destEl.value : '';
  var q = new URLSearchParams();
  if (dest) q.set('dest', dest);
  var a = document.createElement('a');
  a.href = '/api/siem/dlq/export?' + q.toString();
  a.download = 'dlq.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function dlqView(id) {
  var host = document.getElementById('dlq-modal-host');
  if (!host) return;

  // Fetch full entry from API (includes full payload + last_error)
  var entry = null;
  try {
    var r = await fetch('/api/siem/dlq/' + id);
    if (!r.ok) { alert('Failed to load entry: HTTP ' + r.status); return; }
    entry = await r.json();
  } catch (err) {
    alert('Inspect error: ' + String(err));
    return;
  }

  host.innerHTML = '';
  var backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.addEventListener('click', function() { host.innerHTML = ''; });
  var modal = document.createElement('div');
  modal.className = 'modal';
  modal.addEventListener('click', function(e) { e.stopPropagation(); });

  var title = document.createElement('h3');
  title.setAttribute('data-i18n', 'gui_dlq_modal_title');
  title.textContent = 'DLQ entry detail';
  modal.appendChild(title);

  [
    ['Destination', entry.destination || entry.source_table],
    ['Event ID', entry.source_id],
    ['Failed at', entry.quarantined_at],
    ['Retries', entry.retries],
  ].forEach(function(pair) {
    var d = document.createElement('div');
    var b = document.createElement('b');
    b.textContent = pair[0];
    d.appendChild(b);
    d.appendChild(document.createTextNode(': ' + (pair[1] == null ? '' : pair[1])));
    modal.appendChild(d);
  });

  // Full last_error
  if (entry.last_error) {
    var errLabel = document.createElement('div');
    errLabel.style.marginTop = '10px';
    var errB = document.createElement('b');
    errB.textContent = 'Reason';
    errLabel.appendChild(errB);
    modal.appendChild(errLabel);
    var errPre = document.createElement('pre');
    errPre.style.cssText = 'background:var(--bg3);padding:10px;overflow:auto;max-height:160px;white-space:pre-wrap;';
    errPre.innerHTML = escapeHtml(String(entry.last_error));
    modal.appendChild(errPre);
  }

  // Full payload
  if (entry.payload) {
    var payLabel = document.createElement('div');
    payLabel.style.marginTop = '10px';
    var payB = document.createElement('b');
    payB.textContent = 'Payload';
    payLabel.appendChild(payB);
    modal.appendChild(payLabel);
    var payPre = document.createElement('pre');
    payPre.style.cssText = 'background:var(--bg3);padding:10px;overflow:auto;max-height:400px;white-space:pre-wrap;';
    var payStr = typeof entry.payload === 'string' ? entry.payload : JSON.stringify(entry.payload, null, 2);
    payPre.innerHTML = escapeHtml(payStr);
    modal.appendChild(payPre);
  }

  var row = document.createElement('div');
  row.style.textAlign = 'right';
  var btn = document.createElement('button');
  btn.className = 'btn';
  btn.setAttribute('data-i18n', 'gui_close');
  btn.textContent = 'Close';
  btn.addEventListener('click', function() { host.innerHTML = ''; });
  row.appendChild(btn);
  modal.appendChild(row);
  backdrop.appendChild(modal);
  host.appendChild(backdrop);
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

window.dlqSearch = dlqSearch;
window._dlqLoadPage = _dlqLoadPage;
window.dlqPrevPage = dlqPrevPage;
window.dlqNextPage = dlqNextPage;
window.dlqSelectAll = dlqSelectAll;
window.dlqReplaySelected = dlqReplaySelected;
window.dlqReplay = dlqReplay;
window.dlqPurgeSelected = dlqPurgeSelected;
window.dlqPurgeAll = dlqPurgeAll;
window.dlqExport = dlqExport;
window.dlqView = dlqView;

// ── Overview sub-tab ─────────────────────────────────────────────────────────
function _buildOvPipelineHealth(health) {
  var verdict = (health && health.verdict) || 'ok';
  var colorMap = {ok: 'var(--color-success,#22c55e)', warn: 'var(--color-warning,#f59e0b)', error: 'var(--color-danger,#f43f5e)'};
  var cardClass = verdict === 'error' ? 'card-err' : verdict === 'warn' ? 'card-warn' : 'card-ok';
  var color = colorMap[verdict] || colorMap.ok;
  return '<div class="cards" style="margin-bottom:8px;">'
    + '<div class="card ' + cardClass + '" style="flex:0 0 auto;min-width:160px;">'
    + '<div class="label" data-i18n="gui_ov_pipeline_health">Pipeline Health</div>'
    + '<div class="value" style="color:' + color + ';font-size:1.1rem;font-weight:700;">' + verdict.toUpperCase() + '</div>'
    + '</div>'
    + '</div>';
}

function _buildOvCards(cache, siemStatus, totalPending, totalSent, totalFailed, totalDlq, throughput) {
  var siemClass = totalFailed > 0 ? 'card-err' : 'card-ok';
  var dlqClass  = totalDlq  > 0 ? 'card-warn' : 'card-ok';
  var cacheEvents  = Number(cache.events      || 0);
  var cacheTraffic = Number(cache.traffic_raw || 0) + Number(cache.traffic_agg || 0);
  var traffic24h   = throughput && throughput.traffic_raw_24h != null ? Number(throughput.traffic_raw_24h) : null;
  var traffic24hBadge = traffic24h == null ? ''
    : ' <span style="font-size:.7rem;color:var(--accent2);">' + _t('gui_ov_traffic_24h').replace('{n}', traffic24h.toLocaleString()) + '</span>';
  var failedColor  = totalFailed > 0 ? 'var(--color-danger)' : 'var(--dim)';
  var queueInner = '<div style="display:flex;gap:16px;margin-top:6px;">'
    + '<div><div style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_pending">pending</div>'
    + '<div style="font-size:1.3rem;color:var(--accent2);font-weight:700;">' + totalPending + '</div></div>'
    + '<div><div style="font-size:.7rem;color:var(--color-success);" data-i18n="gui_ov_sent">sent</div>'
    + '<div style="font-size:1.3rem;color:var(--color-success);font-weight:700;">' + totalSent + '</div></div>'
    + '<div><div style="font-size:.7rem;color:' + failedColor + ';" data-i18n="gui_ov_failed">failed</div>'
    + '<div style="font-size:1.3rem;color:' + failedColor + ';font-weight:700;">' + totalFailed + '</div></div>'
    + '</div>';
  return '<div class="cards" style="margin-bottom:16px;">'
    + '<div class="card card-neutral">'
    + '<div class="label" data-i18n="gui_ov_cache_rows">Cache Rows</div>'
    + '<div class="value" style="font-size:.95rem;line-height:1.5;">'
    + cacheEvents.toLocaleString() + ' <span style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_events">events</span><br>'
    + cacheTraffic.toLocaleString() + ' <span style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_traffic">traffic</span>'
    + traffic24hBadge
    + '</div>'
    + '</div>'
    + '<div class="card card-neutral">'
    + '<div class="label" data-i18n="gui_ov_siem_destinations">SIEM Destinations</div>'
    + '<div class="value">' + siemStatus.length + '</div>'
    + '<div style="font-size:.75rem;color:var(--dim);">' + _t('gui_ov_destinations_fmt').replace('{n}', siemStatus.length) + '</div>'
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
      var failStyle = Number(d.failed || 0) > 0 ? ' style="color:var(--color-danger)"' : '';
      rows += '<tr>'
        + '<td><code>' + escapeAttr(d.destination || '') + '</code></td>'
        + '<td>' + Number(d.pending || 0) + '</td>'
        + '<td style="color:var(--color-success)">' + Number(d.sent || 0) + '</td>'
        + '<td' + failStyle + '>' + Number(d.failed || 0) + '</td>'
        + '<td>' + Number(d.dlq || 0) + '</td>'
        + '</tr>';
    });
  }
  return '<h3 style="color:var(--accent2);font-size:.9rem;font-weight:700;margin:16px 0 8px;" data-i18n="gui_ov_recent_events">Recent dispatch events</h3>'
    + '<div class="table-container">'
    + '<table class="rule-table">'
    + '<colgroup>'
    + '<col style="width:30%"><col style="width:14%"><col style="width:18%"><col style="width:14%"><col style="width:24%">'
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
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';

  var cache, siem, settings, health, throughput;
  try {
    var results = await Promise.all([
      fetch('/api/cache/status').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
      fetch('/api/siem/status').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
      fetch('/api/settings').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
      fetch('/api/cache/health').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
      fetch('/api/cache/throughput').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
    ]);
    cache      = results[0] || {};
    siem       = results[1] || {status: []};
    settings   = results[2] || {};
    health     = results[3] || {};
    throughput = results[4] || {};
  } catch (err) {
    el.textContent = '';
    var p = document.createElement('p');
    p.style.color = 'var(--danger,red)';
    p.textContent = _t('gui_ov_load_error').replace('{err}', String(err));
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

  el.innerHTML = _buildOvPipelineHealth(health)
               + _buildOvCards(cache, siemStatus, totalPending, totalSent, totalFailed, totalDlq, throughput)
               + _buildOvRecentTable(siemStatus)
               + _buildAlertChannelCards(settings);
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function _buildAlertChannelCards(settings) {
  var alerts = settings.alerts || {};
  var smtp   = settings.smtp   || {};
  var email  = settings.email  || {};

  // Mail card
  var mailConfigured = !!(smtp.host || email.smtp_host);
  var mailHost = smtp.host || email.smtp_host || '';
  var mailPort = smtp.port || email.smtp_port || '';
  var mailSender = (alerts.mail && alerts.mail.sender) || email.sender || '';
  var mailStatus = mailConfigured ? 'ok' : 'muted';
  var mailStatusLabel = mailConfigured ? 'Verified' : 'Not configured';
  var mailSub = mailHost ? (mailHost + (mailPort ? ':' + mailPort : '')) : 'SMTP not configured';

  // Alert channel config is stored FLAT under `alerts` (e.g. alerts.line_channel_access_token),
  // not as nested sub-objects. Secret fields are redacted to asterisks by /api/settings, which
  // also emits an authoritative `<key>__set` boolean — trust that for "configured", not the value.

  // LINE card
  var lineConfigured = !!alerts.line_channel_access_token__set;
  var lineStatus = lineConfigured ? 'ok' : 'muted';
  var lineStatusLabel = lineConfigured ? 'Verified' : 'Not configured';
  var lineTarget = alerts.line_target_id || '';

  // Telegram card
  var tgConfigured = !!alerts.telegram_bot_token__set;
  var tgChatId = alerts.telegram_chat_id || '';
  var tgStatus = tgConfigured ? 'ok' : 'muted';
  var tgStatusLabel = tgConfigured ? 'Configured' : 'Not configured';

  // Webhook card (url is redacted, so the real value can't be displayed)
  var whConfigured = !!alerts.webhook_url__set;
  var whStatus = whConfigured ? 'ok' : 'muted';
  var whStatusLabel = whConfigured ? 'Verified' : 'Not configured';

  function chip(cls, label) {
    return '<span class="it-status-chip it-status-' + cls + '">' + label + '</span>';
  }

  var cards = '<div class="it-channel-section">'
    + '<div class="it-channel-header">'
    + '<div><strong>Alert channels</strong><span class="it-channel-sub">Mail · LINE · Telegram · Webhook</span></div>'
    + '</div>'
    + '<div class="integ-grid">';

  // Mail
  cards += '<div class="integ-card">'
    + '<div class="integ-card-h">'
    + '<div class="integ-card-logo">@</div>'
    + '<div><div class="integ-card-name">Mail (SMTP)</div>'
    + '<div class="integ-card-sub">' + escapeAttr(mailSub) + '</div></div>'
    + chip(mailStatus, mailStatusLabel)
    + '</div>';
  if (mailConfigured) {
    cards += '<div class="integ-card-meta">'
      + (mailSender ? '<span>Sender <strong>' + escapeAttr(mailSender) + '</strong></span>' : '')
      + '</div>';
  }
  cards += '</div>';

  // LINE
  cards += '<div class="integ-card">'
    + '<div class="integ-card-h">'
    + '<div class="integ-card-logo">L</div>'
    + '<div><div class="integ-card-name">LINE Push</div>'
    + '<div class="integ-card-sub">Channel access token</div></div>'
    + chip(lineStatus, lineStatusLabel)
    + '</div>';
  if (lineConfigured && lineTarget) {
    var lineShort = lineTarget.length > 14 ? lineTarget.slice(0, 7) + '…' + lineTarget.slice(-6) : lineTarget;
    cards += '<div class="integ-card-meta"><span>Target ID <strong>' + escapeAttr(lineShort) + '</strong></span></div>';
  }
  cards += '</div>';

  // Telegram
  cards += '<div class="integ-card">'
    + '<div class="integ-card-h">'
    + '<div class="integ-card-logo">T</div>'
    + '<div><div class="integ-card-name">Telegram</div>'
    + '<div class="integ-card-sub">Bot token · HTML parse_mode</div></div>'
    + chip(tgStatus, tgStatusLabel)
    + '</div>';
  if (tgChatId) {
    cards += '<div class="integ-card-meta"><span>Chat ID <strong>' + escapeAttr(String(tgChatId)) + '</strong></span></div>';
  }
  cards += '</div>';

  // Webhook
  cards += '<div class="integ-card">'
    + '<div class="integ-card-h">'
    + '<div class="integ-card-logo">W</div>'
    + '<div><div class="integ-card-name">Webhook</div>'
    + '<div class="integ-card-sub">POST JSON · https only</div></div>'
    + chip(whStatus, whStatusLabel)
    + '</div>';
  cards += '</div>';

  cards += '</div></div>'; // close integ-grid + it-channel-section
  return cards;
}
