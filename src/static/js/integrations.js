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
      btn.classList.toggle('active',
        btn.getAttribute('onclick') && btn.getAttribute('onclick').indexOf("'" + name + "'") >= 0);
    });
    if (name === 'overview') renderOverview();
    else if (name === 'cache') renderCache();
    else if (name === 'siem') renderSiem();
    else if (name === 'dlq') renderDlq();
  }
  window.integrationsSwitch = integrationsSwitch;

  // Hook into the project's existing switchTab to auto-render Overview on first visit.
  var originalSwitchTab = window.switchTab;
  if (typeof originalSwitchTab === 'function') {
    window.switchTab = function (name) {
      var r = originalSwitchTab.apply(this, arguments);
      if (name === 'integrations') integrationsSwitch('overview');
      return r;
    };
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

  var header = buildCacheStatusCards(status, s);
  var form = buildCacheForm(s);
  el.innerHTML = header + form + '<div id="cache-banner" style="display:none;margin-top:12px;"></div>';
  el.dataset.settings = JSON.stringify(s);
  renderTrafficFilter(s);
  renderTrafficSampling(s);
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function buildCacheStatusCards(status, s) {
  var evLag = (status.events_lag_sec == null) ? '—' : Number(status.events_lag_sec);
  var trLag = (status.traffic_lag_sec == null) ? '—' : Number(status.traffic_lag_sec);
  var lastEv = escapeAttr(status.last_event_ingested_at || '—');
  return '<div class="cards" style="margin-bottom:16px;">'
    + '<div class="card"><div class="label" data-i18n="gui_cache_enabled">Enabled</div>'
    + '<div class="value">' + (s.enabled ? '✓' : '—') + '</div></div>'
    + '<div class="card"><div class="label" data-i18n="gui_cache_events_lag">Events lag (s)</div>'
    + '<div class="value">' + evLag + '</div></div>'
    + '<div class="card"><div class="label" data-i18n="gui_cache_traffic_lag">Traffic lag (s)</div>'
    + '<div class="value">' + trLag + '</div></div>'
    + '<div class="card"><div class="label" data-i18n="gui_cache_last_events">Last events ingest</div>'
    + '<div class="value" style="font-size:.8rem;">' + lastEv + '</div></div>'
    + '</div>'
    + '<div style="display:flex;gap:8px;margin-bottom:16px;">'
    + '<button class="btn" onclick="cacheBackfill()" data-i18n="gui_backfill">Backfill</button>'
    + '<button class="btn" onclick="cacheRetentionNow()" data-i18n="gui_retention_now">Retention now</button>'
    + '</div>';
}

function buildCacheForm(s) {
  var dbPath = escapeAttr(s.db_path);
  return '<form id="cache-form" class="rs-glass">'
    + '<h3 data-i18n="gui_cache_sec_basic">Basic</h3>'
    + '<label><input type="checkbox" name="enabled"' + (s.enabled ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_cache_enabled">Enabled</span></label>'
    + '<div><label><span data-i18n="gui_cache_db_path">DB path</span>:'
    + ' <input name="db_path" value="' + dbPath + '"></label></div>'
    + '<h3 data-i18n="gui_cache_sec_retention">Retention (days)</h3>'
    + '<div><label>events_retention_days:'
    + ' <input type="number" name="events_retention_days" min="1" value="' + Number(s.events_retention_days) + '"></label></div>'
    + '<div><label>traffic_raw_retention_days:'
    + ' <input type="number" name="traffic_raw_retention_days" min="1" value="' + Number(s.traffic_raw_retention_days) + '"></label></div>'
    + '<div><label>traffic_agg_retention_days:'
    + ' <input type="number" name="traffic_agg_retention_days" min="1" value="' + Number(s.traffic_agg_retention_days) + '"></label></div>'
    + '<h3 data-i18n="gui_cache_sec_polling">Polling (seconds)</h3>'
    + '<div><label>events_poll_interval_seconds:'
    + ' <input type="number" name="events_poll_interval_seconds" min="30" value="' + Number(s.events_poll_interval_seconds) + '"></label></div>'
    + '<div><label>traffic_poll_interval_seconds:'
    + ' <input type="number" name="traffic_poll_interval_seconds" min="60" value="' + Number(s.traffic_poll_interval_seconds) + '"></label></div>'
    + '<h3 data-i18n="gui_cache_sec_throughput">Throughput</h3>'
    + '<div><label>rate_limit_per_minute:'
    + ' <input type="number" name="rate_limit_per_minute" min="10" max="500" value="' + Number(s.rate_limit_per_minute) + '"></label></div>'
    + '<div><label>async_threshold_events:'
    + ' <input type="number" name="async_threshold_events" min="1" max="10000" value="' + Number(s.async_threshold_events) + '"></label></div>'
    + '<div id="cache-form-extra"></div>'
    + '<div style="text-align:right;margin-top:12px;">'
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
    headers: {'Content-Type': 'application/json'},
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
  target.textContent = 'Settings saved. Restart monitor to apply scheduling changes.';
}

async function cacheBackfill() {
  var start = prompt('Start date (YYYY-MM-DD)');
  var end = prompt('End date (YYYY-MM-DD)');
  if (!start || !end) return;
  await fetch('/api/cache/backfill', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({start: start, end: end}),
  });
  alert('Backfill submitted');
}

async function cacheRetentionNow() {
  alert('Run "Retention now" via CLI; HTTP trigger not yet implemented.');
}

// ── Cache traffic_filter section ────────────────────────────────────────────
function renderTrafficFilter(s) {
  var tf = s.traffic_filter || {};
  var actions = ['blocked', 'potentially_blocked', 'allowed'];
  var protocols = ['TCP', 'UDP', 'ICMP'];
  var envVals = (tf.workload_label_env || []).map(escapeAttr).join(',');
  var portVals = escapeAttr((tf.ports || []).map(Number).join(','));
  var ipVals = (tf.exclude_src_ips || []).map(escapeAttr).join(',');

  var html = '<h3 data-i18n="gui_cache_sec_traffic_filter">Traffic Filter</h3>'
    + '<div><span data-i18n="gui_cache_tf_actions">Actions</span>: '
    + actions.map(function(a) {
        return '<label><input type="checkbox" name="tf-action" value="' + escapeAttr(a) + '"'
          + ((tf.actions || []).indexOf(a) >= 0 ? ' checked' : '') + '> ' + escapeAttr(a) + '</label>';
      }).join(' ')
    + '</div>'
    + '<div><span data-i18n="gui_cache_tf_protocols">Protocols</span>: '
    + protocols.map(function(p) {
        return '<label><input type="checkbox" name="tf-protocol" value="' + escapeAttr(p) + '"'
          + ((tf.protocols || []).indexOf(p) >= 0 ? ' checked' : '') + '> ' + escapeAttr(p) + '</label>';
      }).join(' ')
    + '</div>'
    + '<div><label><span data-i18n="gui_cache_tf_workload_env">Workload label env</span>:'
    + ' <input id="tf-env" value="' + envVals + '"></label></div>'
    + '<div><label><span data-i18n="gui_cache_tf_ports">Ports</span>:'
    + ' <input id="tf-ports" value="' + portVals + '" placeholder="22,443,..."></label></div>'
    + '<div><label><span data-i18n="gui_cache_tf_exclude_ips">Exclude src IPs</span>:'
    + ' <input id="tf-ips" value="' + ipVals + '" placeholder="10.0.0.1,..."></label></div>'
    + '<div id="tf-validation-hints" style="color:var(--danger);font-size:.8rem;"></div>';

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

document.addEventListener('input', function(e) {
  if (e.target && (e.target.id === 'tf-ips' || e.target.id === 'tf-ports')) {
    validateTrafficFilterHints();
  }
});

// ── Cache traffic_sampling section ───────────────────────────────────────────
function renderTrafficSampling(s) {
  var ts = s.traffic_sampling || {};
  var ratio = Number(ts.sample_ratio_allowed || 1);
  var maxRows = Number(ts.max_rows_per_batch || 200000);
  var html = '<h3 data-i18n="gui_cache_sec_traffic_sampling">Traffic Sampling</h3>'
    + '<div><label>sample_ratio_allowed (&gt;=1):'
    + ' <input type="number" id="ts-ratio" min="1" value="' + ratio + '"></label></div>'
    + '<div><label>max_rows_per_batch (1-200000):'
    + ' <input type="number" id="ts-max" min="1" max="200000" value="' + maxRows + '"></label></div>';
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
