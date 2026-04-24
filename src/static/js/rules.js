/* ─── Rules ───────────────────────────────────────────────────────── */
function onEvTtChange() {
  const isCount = rv('ev-tt') === 'count';
  $('ev-cnt-wrap').style.display = isCount ? '' : 'none';
  $('ev-win-wrap').style.display = isCount ? '' : 'none';
}

function onBwMetricTypeChange() {
  const type = rv('bw-mt') || 'bandwidth';
  const label = $('bw-val-label');
  const input = $('bw-val');
  const help = $('bw-val-help');
  if (!label || !input || !help) return;

  if (type === 'volume') {
    label.textContent = _t('gui_bw_value_volume');
    input.placeholder = _t('gui_bw_placeholder_volume');
    help.textContent = _t('gui_bw_help_volume');
  } else {
    label.textContent = _t('gui_bw_value_bandwidth');
    input.placeholder = _t('gui_bw_placeholder_bandwidth');
    help.textContent = _t('gui_bw_help_bandwidth');
  }
}

function _serializeMatchFields(matchFields) {
  return Object.entries(matchFields || {}).map(([key, value]) => `${key}=${value}`).join('\n');
}

function _parseMatchFields(text) {
  const result = {};
  for (const rawLine of String(text || '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const idx = line.indexOf('=');
    if (idx <= 0) {
      const msg = (_t('gui_ev_matcher_invalid')).replace('{line}', line);
      throw new Error(msg);
    }
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (!key || !value) {
      const msg = (_t('gui_ev_matcher_invalid')).replace('{line}', line);
      throw new Error(msg);
    }
    result[key] = value;
  }
  return result;
}

let _catalog = {}, _actionEvents = [], _severityFilterEvents = [];
let _catalogCategories = [], _eventMetaById = {};
async function loadRules() {
  showSkeleton('r-body', 7);
  const rules = await api('/api/rules');
  $('r-badge').textContent = rules.length;
  const pdm = { 2: 'Blocked', 1: 'Potential', 0: 'Allowed', '-1': 'All' };

  const cdTitle = _t('gui_cooldown_active');
  const readyTitle = _t('gui_cooldown_ready');
  const remTempl = _t('gui_cooldown_remaining');

  let html = '';
  rules.forEach(r => {
    const typ = r.type.charAt(0).toUpperCase() + r.type.slice(1);
    const unit = { volume: ' MB', bandwidth: ' Mbps', traffic: ' conns' }[r.type] || '';
    const throttleLabel = r.throttle ? ' TH:' + r.throttle : '';
    const cond = '> ' + r.threshold_count + unit + ' (Win:' + r.threshold_window + 'm CD:' + (r.cooldown_minutes || r.threshold_window) + 'm' + throttleLabel + ')';
    const suppressedCount = ((r.throttle_state && r.throttle_state.cooldown_suppressed) || 0) + ((r.throttle_state && r.throttle_state.throttle_suppressed) || 0);
    const nextAllowedAt = r.throttle_state && r.throttle_state.next_allowed_at ? formatDateZ(r.throttle_state.next_allowed_at) : '';

    let statusHtml = '';
    if (r.cooldown_remaining > 0) {
      const rem = remTempl.replace('{mins}', r.cooldown_remaining);
      statusHtml = `<span style="background:var(--warn);color:#1a2c32;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;">⏳ ${cdTitle} (${rem})</span>`;
    } else {
      statusHtml = `<span style="background:var(--success);color:#fff;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;">✅ ${readyTitle}</span>`;
    }
    if (suppressedCount > 0) {
      const detail = nextAllowedAt ? ` until ${nextAllowedAt}` : '';
      statusHtml += `<div style="margin-top:4px;color:var(--dim);font-size:0.75rem;">Suppressed ${suppressedCount}${escapeHtml(detail)}</div>`;
    }

    let f = [];
    if (r.type === 'event') f.push('Event: ' + r.filter_value);
    if (r.type === 'system') {
      const healthLabel = _t('gui_system_health_type');
      const pceLabel = _t('gui_system_health_pce');
      f.push(healthLabel + ': ' + (r.filter_value === 'pce_health' ? pceLabel : (r.filter_value || '')));
    }
    if (r.pd !== undefined && r.pd !== null) f.push('PD:' + (pdm[r.pd] || r.pd));
    if (r.port) f.push('Port:' + r.port);
    if (r.src_label) f.push('Src:' + r.src_label); if (r.dst_label) f.push('Dst:' + r.dst_label);
    if (r.src_ip_in) f.push('SrcIP:' + r.src_ip_in); if (r.dst_ip_in) f.push('DstIP:' + r.dst_ip_in);
    if (r.throttle) f.push('Throttle:' + r.throttle);
    if (suppressedCount > 0) f.push('Suppressed:' + suppressedCount);
    if (r.match_fields && Object.keys(r.match_fields).length) f.push('Match:' + Object.keys(r.match_fields).join(', '));
    const editBtn = `<button class="btn btn-primary btn-sm" onclick="editRule(${r.index},'${r.type}')" aria-label="Edit Rule" title="Edit Rule">✏️</button>`;
    html += `<tr><td><input type="checkbox" class="r-chk" data-idx="${r.index}"></td><td title="${typ}">${typ}</td><td title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</td><td>${statusHtml}</td><td title="${cond}">${cond}</td><td title="${escapeHtml(f.join(' | '))}">${escapeHtml(f.join(' | ')) || '—'}</td><td>${editBtn}</td></tr>`;
  });
  $('r-body').innerHTML = html || `<tr><td colspan="7"><div class="empty-state"><svg aria-hidden="true"><use href="#icon-shield"></use></svg><h3>${_t('gui_no_rules_title')}</h3><p>${_t('gui_no_rules_add_one')}</p></div></td></tr>`;
  initTableResizers();
  if (typeof loadAlertTestActions === 'function') loadAlertTestActions();
}
function toggleAll(el) { document.querySelectorAll('.r-chk').forEach(c => c.checked = el.checked) }
async function deleteSelected() {
  const ids = [...document.querySelectorAll('.r-chk:checked')].map(c => parseInt(c.dataset.idx)).sort((a, b) => b - a);
  if (!ids.length) { toast(_t('gui_msg_select_rules_first'), 'err'); return }
  if (!confirm((_t('gui_msg_confirm_delete')).replace('{count}', ids.length))) return;
  for (const i of ids) await del('/api/rules/' + i);
  toast(_t('gui_msg_deleted')); loadRules(); loadDashboard();
}
function openModal(id, isEdit) {
  _editIdx = isEdit ?? null; $(id).classList.add('show');
  if (id === 'm-event' && !Object.keys(_catalog).length) loadCatalog();
  if (id === 'm-event' && _editIdx === null) {
    $('ev-cat').value = '';
    populateEvents();
    $('ev-status').value = 'all';
    $('ev-severity').value = 'all';
    $('ev-match-fields').value = '';
    $('ev-throttle').value = '';
    $('ev-advanced').open = false;
    onEvTtChange();
  }
  if (id === 'm-event' && _editIdx !== null) { onEvTtChange(); }
  if (id === 'm-traffic' && _editIdx === null) $('tr-throttle').value = '';
  if (id === 'm-bw' && _editIdx === null) {
    $('bw-throttle').value = '';
    setRv('bw-mt', 'bandwidth');
    onBwMetricTypeChange();
  }
  if (id === 'm-system' && _editIdx === null) {
    $('sys-name').value = _t('rule_pce_health');
    $('sys-type').value = 'pce_health';
    $('sys-cd').value = 30;
    $('sys-throttle').value = '';
  }
  // Update modal title
  let target;
  if (id === 'm-event') target = $('me-title');
  else if (id === 'm-traffic') target = $('mt-title');
  else if (id === 'm-bw') target = $('mb-title');
  else if (id === 'm-system') target = $('ms-title');
  if (target) {
    const baseKey = id === 'm-event' ? 'gui_add_event_rule' : id === 'm-traffic' ? 'gui_add_traffic_rule' : id === 'm-bw' ? 'gui_add_bw_rule' : 'gui_add_system_health_rule';
    const editKey = id === 'm-event' ? 'gui_edit_event_rule' : id === 'm-traffic' ? 'gui_edit_traffic_rule' : id === 'm-bw' ? 'gui_edit_bw_rule' : 'gui_edit_system_health_rule';
    const key = _editIdx !== null ? editKey : baseKey;
    target.setAttribute('data-i18n', key);
    if (_translations[key]) target.textContent = _translations[key];
  }
}
function closeModal(id) { $(id).classList.remove('show'); _editIdx = null }

/* Escape key closes topmost modal */
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    const open = [...document.querySelectorAll('.modal-bg.show')];
    if (open.length) { const last = open[open.length - 1]; last.classList.remove('show'); _editIdx = null; }
  }
});
/* Backdrop click closes modal */
document.querySelectorAll('.modal-bg').forEach(bg => {
  bg.addEventListener('click', e => { if (e.target === e.currentTarget) { bg.classList.remove('show'); _editIdx = null; } });
});

/* ─── Rules search/filter (W2.1) ─────────────────────────────────── */
let _filterDebounce = null;
function filterRules() {
  clearTimeout(_filterDebounce);
  _filterDebounce = setTimeout(_doFilterRules, 150);
}
function _doFilterRules() {
  const q = ($('r-search').value || '').toLowerCase().trim();
  const rows = $('r-body')?.querySelectorAll('tr') || [];
  let shown = 0, total = rows.length;
  rows.forEach(tr => {
    if (!q) { tr.style.display = ''; shown++; _clearHighlight(tr); return; }
    const text = tr.textContent.toLowerCase();
    if (text.includes(q)) { tr.style.display = ''; shown++; _highlightRow(tr, q); }
    else { tr.style.display = 'none'; _clearHighlight(tr); }
  });
  const counter = $('r-search-count');
  counter.textContent = q ? `${shown}/${total}` : '';
}
function _highlightRow(tr, q) {
  tr.querySelectorAll('td').forEach(td => {
    if (td.querySelector('input,button,span[style]')) return; // skip checkbox/button/badge cells
    const orig = td.textContent;
    if (!orig.toLowerCase().includes(q)) return;
    const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`, 'gi');
    td.innerHTML = orig.replace(re, '<mark>$1</mark>');
  });
}
function _clearHighlight(tr) {
  tr.querySelectorAll('mark').forEach(m => m.replaceWith(m.textContent));
}

/* ─── Skeleton / Spinner helpers ─────────────────────────────────── */
function showSkeleton(tbodyId, cols, rows = 4) {
  const el = $(tbodyId); if (!el) return;
  el.innerHTML = Array.from({length: rows}, () =>
    `<tr>${Array.from({length: cols}, () => '<td><span class="skeleton skel-text" style="display:inline-block;width:' + (40 + Math.random()*40) + '%;height:14px"></span></td>').join('')}</tr>`
  ).join('');
}
function showSpinner(containerId, label) {
  let ov = document.querySelector(`#${containerId} .spinner-overlay`);
  if (!ov) {
    const c = $(containerId); if (!c) return;
    c.style.position = 'relative';
    ov = document.createElement('div');
    ov.className = 'spinner-overlay';
    ov.innerHTML = `<div class="spinner"></div><div class="spinner-label"></div>`;
    c.appendChild(ov);
  }
  ov.querySelector('.spinner-label').textContent = label || '';
  ov.classList.add('active');
}
function hideSpinner(containerId) {
  const ov = document.querySelector(`#${containerId} .spinner-overlay`);
  if (ov) ov.classList.remove('active');
}

async function loadCatalog() {
  const resp = await api('/api/event-catalog');
  _catalog = resp.catalog || resp;
  _catalogCategories = resp.categories || [];
  _actionEvents = resp.action_events || [];
  _severityFilterEvents = resp.severity_filter_events || [];
  _eventMetaById = {};
  if (_catalogCategories.length) {
    _catalogCategories.forEach(category => {
      (category.events || []).forEach(event => {
        _eventMetaById[event.id] = { ...event, category_id: category.id, category_label: category.label };
      });
    });
  } else {
    Object.entries(_catalog).forEach(([categoryLabel, events]) => {
      Object.entries(events || {}).forEach(([eventId, description]) => {
        _eventMetaById[eventId] = {
          id: eventId,
          label: description,
          description,
          source: 'vendor_baseline',
          supports_status: _actionEvents.includes(eventId),
          supports_severity: _severityFilterEvents.includes(eventId),
          category_id: categoryLabel,
          category_label: categoryLabel
        };
      });
    });
    _catalogCategories = Object.keys(_catalog).map(label => ({ id: label, label, events: Object.keys(_catalog[label] || {}).map(id => _eventMetaById[id]) }));
  }
  const sel = $('ev-cat'); sel.innerHTML = '<option value="" data-i18n="gui_select">Select...</option>';
  _catalogCategories.forEach(category => {
    const o = document.createElement('option');
    o.value = category.id;
    o.textContent = category.label;
    sel.appendChild(o);
  });
}
function populateEvents() {
  const cat = $('ev-cat').value;
  const sel = $('ev-type');
  sel.innerHTML = '';
  const category = _catalogCategories.find(item => item.id === cat);
  if (!cat || !category) {
    sel.innerHTML = '<option data-i18n="gui_select_category_first">Select category first</option>';
    applyI18n(sel);
    updateEventFilters();
    return;
  }
  (category.events || []).forEach(meta => {
    const o = document.createElement('option');
    o.value = meta.id;
    o.textContent = meta.label && meta.label !== meta.id
      ? `${meta.id} | ${meta.label}`
      : meta.id;
    sel.appendChild(o);
  });
  updateEventFilters();
}

function _renderEventInfo(eventId) {
  const box = $('ev-info');
  if (!box) return;
  const relEl = $('ev-info-related');
  if (!eventId) {
    box.style.display = 'none';
    $('ev-info-id').textContent = '';
    $('ev-info-title').textContent = '';
    $('ev-info-desc').textContent = '';
    $('ev-info-capabilities').textContent = '';
    $('ev-info-badges').innerHTML = '';
    if (relEl) { while (relEl.firstChild) relEl.removeChild(relEl.firstChild); relEl.style.display = 'none'; }
    return;
  }

  const meta = _eventMetaById[eventId] || {};
  const badges = [];
  if (meta.supports_status) badges.push(`<span style="padding:2px 8px;border-radius:999px;font-size:.72rem;font-weight:700;background:#EFF6FF;color:#1D4ED8;border:1px solid #93C5FD;">${_t('gui_ev_status_filter_badge')}</span>`);
  if (meta.supports_severity) badges.push(`<span style="padding:2px 8px;border-radius:999px;font-size:.72rem;font-weight:700;background:#FEF2F2;color:#B91C1C;border:1px solid #FCA5A5;">${_t('gui_ev_severity_filter_badge')}</span>`);

  const title = meta.label || eventId;
  const desc = (meta.description && meta.description !== title) ? meta.description : '';
  $('ev-info-id').textContent = eventId;
  $('ev-info-title').textContent = title;
  $('ev-info-desc').textContent = desc;
  $('ev-info-desc').style.display = desc ? '' : 'none';

  const capEl = $('ev-info-capabilities');
  capEl.textContent = (meta.tips) || (
    meta.supports_status || meta.supports_severity
      ? _t('gui_ev_capability_filters')
      : _t('gui_ev_capability_basic')
  );

  if (relEl) {
    while (relEl.firstChild) relEl.removeChild(relEl.firstChild);
    const related = meta.related_events || [];
    if (related.length) {
      const label = document.createElement('span');
      label.textContent = _t('gui_ev_see_also');
      relEl.appendChild(label);
      related.forEach(e => {
        const chip = document.createElement('code');
        chip.textContent = e;
        chip.style.cssText = 'background:var(--bg);border:1px solid var(--border);border-radius:3px;padding:1px 5px;';
        relEl.appendChild(chip);
      });
      relEl.style.display = 'flex';
    } else {
      relEl.style.display = 'none';
    }
  }

  $('ev-info-badges').innerHTML = badges.join('');
  box.style.display = '';
}

function updateEventFilters() {
  const ev = $('ev-type').value;
  const meta = _eventMetaById[ev] || {};
  const showStatus = !!ev && !!meta.supports_status;
  const showSeverity = !!ev && !!meta.supports_severity;
  $('ev-filter-row').style.display = (showStatus || showSeverity) ? '' : 'none';
  $('ev-status-group').style.display = showStatus ? '' : 'none';
  $('ev-severity-group').style.display = showSeverity ? '' : 'none';
  if (!showStatus) $('ev-status').value = 'all';
  if (!showSeverity) $('ev-severity').value = 'all';
  _renderEventInfo(ev);
}

/* ─── Edit Rule ───────────────────────────────────────────────────── */
async function editRule(idx, type) {
  try {
    const r = await api('/api/rules/' + idx);
    if (!r || r.error) { toast(_t('gui_msg_rule_not_found'), 'err'); return }
    if (type === 'event') {
      await loadCatalog();
      // Find and select category
      for (const category of _catalogCategories) {
        if ((category.events || []).some(event => event.id === r.filter_value)) {
          $('ev-cat').value = category.id;
          populateEvents();
          $('ev-type').value = r.filter_value;
          break;
        }
      }
      updateEventFilters();
      $('ev-status').value = r.filter_status || 'all';
      $('ev-severity').value = r.filter_severity || 'all';
      $('ev-match-fields').value = _serializeMatchFields(r.match_fields || {});
      setRv('ev-tt', r.threshold_type || 'immediate');
      onEvTtChange();
      $('ev-cnt').value = r.threshold_count || 5;
      $('ev-win').value = r.threshold_window || 10;
      $('ev-cd').value = r.cooldown_minutes || 10;
      $('ev-throttle').value = r.throttle || '';
      $('ev-advanced').open = !!(r.match_fields && Object.keys(r.match_fields).length);
      openModal('m-event', idx);
    } else if (type === 'system') {
      $('sys-name').value = r.name || (_t('rule_pce_health'));
      $('sys-type').value = r.filter_value || 'pce_health';
      $('sys-cd').value = r.cooldown_minutes || 30;
      $('sys-throttle').value = r.throttle || '';
      openModal('m-system', idx);
    } else if (type === 'traffic') {
      $('tr-name').value = r.name || '';
      setRv('tr-pd', String(r.pd ?? 2));
      $('tr-port').value = r.port || '';
      $('tr-proto').value = r.proto ? String(r.proto) : '';
      $('tr-src').value = r.src_label || r.src_ip_in || '';
      $('tr-dst').value = r.dst_label || r.dst_ip_in || '';
      $('tr-expt').value = r.ex_port || '';
      $('tr-exsrc').value = r.ex_src_label || r.ex_src_ip || '';
      $('tr-exdst').value = r.ex_dst_label || r.ex_dst_ip || '';
      $('tr-cnt').value = r.threshold_count || 10;
      $('tr-win').value = r.threshold_window || 10;
      $('tr-cd').value = r.cooldown_minutes || 10;
      $('tr-throttle').value = r.throttle || '';
      openModal('m-traffic', idx);
    } else {
      $('bw-name').value = r.name || '';
      setRv('bw-mt', r.type || 'bandwidth');
      onBwMetricTypeChange();
      setRv('bw-pd', String(r.pd ?? -1));
      $('bw-port').value = r.port || '';
      $('bw-src').value = r.src_label || r.src_ip_in || '';
      $('bw-dst').value = r.dst_label || r.dst_ip_in || '';
      $('bw-expt').value = r.ex_port || '';
      $('bw-exsrc').value = r.ex_src_label || r.ex_src_ip || '';
      $('bw-exdst').value = r.ex_dst_label || r.ex_dst_ip || '';
      $('bw-val').value = r.threshold_count || 100;
      $('bw-win').value = r.threshold_window || 10;
      $('bw-cd').value = r.cooldown_minutes || 30;
      $('bw-throttle').value = r.throttle || '';
      openModal('m-bw', idx);
    }
  } catch (e) {
    console.error(e);
    alert((_t('gui_msg_ui_error')).replace('{error}', e.message));
  }
}

async function saveEvent() {
  const cat = $('ev-cat').value, ev = $('ev-type').value;
  if (!cat || !ev) { toast(_t('gui_msg_select_cat_event'), 'err'); return }
  const meta = _eventMetaById[ev] || {};
  const name = meta.label || meta.description || ev;
  let matchFields;
  try {
    matchFields = _parseMatchFields($('ev-match-fields').value);
  } catch (error) {
    toast(error.message, 'err');
    return;
  }
  const data = {
    name,
    filter_value: ev,
    filter_status: $('ev-status').value || 'all',
    filter_severity: $('ev-severity').value || 'all',
    match_fields: matchFields,
    threshold_type: rv('ev-tt'),
    threshold_count: $('ev-cnt').value,
    threshold_window: $('ev-win').value,
    cooldown_minutes: $('ev-cd').value,
    throttle: $('ev-throttle').value.trim()
  };
  if (_editIdx !== null) await put('/api/rules/' + _editIdx, data); else await post('/api/rules/event', data);
  closeModal('m-event'); toast(_t('gui_msg_event_rule_saved')); loadRules(); loadDashboard();
}
async function saveSystemRule() {
  const name = $('sys-name').value.trim() || (_t('rule_pce_health'));
  const data = {
    name,
    filter_value: $('sys-type').value || 'pce_health',
    cooldown_minutes: $('sys-cd').value || 30,
    throttle: $('sys-throttle').value.trim()
  };
  if (_editIdx !== null) {
    await put('/api/rules/' + _editIdx, data);
  } else {
    await post('/api/rules/system', data);
  }
  closeModal('m-system'); toast(_t('gui_msg_system_rule_saved')); loadRules(); loadDashboard();
}
async function saveTraffic() {
  const name = $('tr-name').value.trim(); if (!name) { toast(_t('gui_msg_name_required'), 'err'); return }
  const data = { name, pd: rv('tr-pd'), port: $('tr-port').value, proto: $('tr-proto').value, src: $('tr-src').value, dst: $('tr-dst').value, ex_port: $('tr-expt').value, ex_src: $('tr-exsrc').value, ex_dst: $('tr-exdst').value, threshold_count: $('tr-cnt').value, threshold_window: $('tr-win').value, cooldown_minutes: $('tr-cd').value, throttle: $('tr-throttle').value.trim() };
  if (_editIdx !== null) await put('/api/rules/' + _editIdx, data); else await post('/api/rules/traffic', data);
  closeModal('m-traffic'); toast(_t('gui_msg_traffic_rule_saved')); loadRules(); loadDashboard();
}
async function saveBW() {
  const name = $('bw-name').value.trim(); if (!name) { toast(_t('gui_msg_name_required'), 'err'); return }
  const data = {
    name, rule_type: rv('bw-mt'), pd: rv('bw-pd'),
    port: $('bw-port').value, src: $('bw-src').value, dst: $('bw-dst').value,
    ex_port: $('bw-expt').value, ex_src: $('bw-exsrc').value, ex_dst: $('bw-exdst').value,
    threshold_count: $('bw-val').value, threshold_window: $('bw-win').value, cooldown_minutes: $('bw-cd').value, throttle: $('bw-throttle').value.trim()
  };
  if (_editIdx !== null) await put('/api/rules/' + _editIdx, { ...data, type: data.rule_type }); else await post('/api/rules/bandwidth', data);
  closeModal('m-bw'); toast(_t('gui_msg_rule_saved')); loadRules(); loadDashboard();
}

function confirmBestPractices() {
  const promptText = (
    _t('gui_best_practices_mode_prompt')
  ).replace(/\\n/g, '\n');
  const choice = window.prompt(promptText, '1');
  if (choice === null) return;

  const normalized = String(choice).trim().toLowerCase();
  let mode = '';
  if (['1', 'append', 'append_missing', 'safe'].includes(normalized)) mode = 'append_missing';
  if (['2', 'replace', 'overwrite'].includes(normalized)) mode = 'replace';
  if (!mode) {
    toast(_t('gui_best_practices_mode_invalid'), 'err');
    return;
  }

  if (mode === 'replace') {
    if (!confirm((_t('gui_warn_best_practices')).replace(/\\n/g, '\n'))) return;
    if (!confirm(_t('gui_confirm_best_practices'))) return;
  } else if (!confirm((_t('gui_best_practices_append_confirm')).replace(/\\n/g, '\n'))) {
    return;
  }

  runAction('best-practices', { mode });
}
