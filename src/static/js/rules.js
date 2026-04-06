/* ─── Rules ───────────────────────────────────────────────────────── */
function onEvTtChange() {
  const isCount = rv('ev-tt') === 'count';
  $('ev-cnt-wrap').style.display = isCount ? '' : 'none';
  $('ev-win-wrap').style.display = isCount ? '' : 'none';
}
let _catalog = {}, _actionEvents = [];
async function loadRules() {
  showSkeleton('r-body', 7);
  const rules = await api('/api/rules');
  $('r-badge').textContent = rules.length;
  const pdm = { 2: 'Blocked', 1: 'Potential', 0: 'Allowed', '-1': 'All' };

  const cdTitle = _translations['gui_cooldown_active'] || 'Cooldown';
  const readyTitle = _translations['gui_cooldown_ready'] || 'Ready';
  const remTempl = _translations['gui_cooldown_remaining'] || '{mins}m remaining';

  let html = '';
  rules.forEach(r => {
    const typ = r.type.charAt(0).toUpperCase() + r.type.slice(1);
    const unit = { volume: ' MB', bandwidth: ' Mbps', traffic: ' conns' }[r.type] || '';
    const cond = '> ' + r.threshold_count + unit + ' (Win:' + r.threshold_window + 'm CD:' + (r.cooldown_minutes || r.threshold_window) + 'm)';

    let statusHtml = '';
    if (r.cooldown_remaining > 0) {
      const rem = remTempl.replace('{mins}', r.cooldown_remaining);
      statusHtml = `<span style="background:var(--warn);color:#1a2c32;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;">⏳ ${cdTitle} (${rem})</span>`;
    } else {
      statusHtml = `<span style="background:var(--success);color:#fff;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;">✅ ${readyTitle}</span>`;
    }

    let f = [];
    if (r.type === 'event') f.push('Event: ' + r.filter_value);
    if (r.type === 'system') f.push('Check: ' + (r.filter_value || ''));
    if (r.pd !== undefined && r.pd !== null) f.push('PD:' + (pdm[r.pd] || r.pd));
    if (r.port) f.push('Port:' + r.port);
    if (r.src_label) f.push('Src:' + r.src_label); if (r.dst_label) f.push('Dst:' + r.dst_label);
    if (r.src_ip_in) f.push('SrcIP:' + r.src_ip_in); if (r.dst_ip_in) f.push('DstIP:' + r.dst_ip_in);
    const editBtn = r.type !== 'system' ? `<button class="btn btn-primary btn-sm" onclick="editRule(${r.index},'${r.type}')" aria-label="Edit Rule" title="Edit Rule">✏️</button>` : '';
    html += `<tr><td><input type="checkbox" class="r-chk" data-idx="${r.index}"></td><td title="${typ}">${typ}</td><td title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</td><td>${statusHtml}</td><td title="${cond}">${cond}</td><td title="${escapeHtml(f.join(' | '))}">${escapeHtml(f.join(' | ')) || '—'}</td><td>${editBtn}</td></tr>`;
  });
  $('r-body').innerHTML = html || `<tr><td colspan="7"><div class="empty-state"><svg aria-hidden="true"><use href="#icon-shield"></use></svg><h3>${_translations['gui_no_rules_title'] || 'No Rules Yet'}</h3><p>${_translations['gui_no_rules_add_one'] || 'Create your first monitoring rule using the buttons above.'}</p></div></td></tr>`;
  initTableResizers();
}
function toggleAll(el) { document.querySelectorAll('.r-chk').forEach(c => c.checked = el.checked) }
async function deleteSelected() {
  const ids = [...document.querySelectorAll('.r-chk:checked')].map(c => parseInt(c.dataset.idx)).sort((a, b) => b - a);
  if (!ids.length) { toast(_translations['gui_msg_select_rules_first'] || 'Select rules first', 'err'); return }
  if (!confirm((_translations['gui_msg_confirm_delete'] || 'Delete {count} rule(s)?').replace('{count}', ids.length))) return;
  for (const i of ids) await del('/api/rules/' + i);
  toast(_translations['gui_msg_deleted'] || 'Deleted'); loadRules(); loadDashboard();
}
function openModal(id, isEdit) {
  _editIdx = isEdit ?? null; $(id).classList.add('show');
  if (id === 'm-event' && !Object.keys(_catalog).length) loadCatalog();
  if (id === 'm-event' && _editIdx === null) { updateEventFilters(); onEvTtChange(); }
  if (id === 'm-event' && _editIdx !== null) { onEvTtChange(); }
  // Update modal title
  let target;
  if (id === 'm-event') target = $('me-title');
  else if (id === 'm-traffic') target = $('mt-title');
  else if (id === 'm-bw') target = $('mb-title');
  if (target) {
    const baseKey = id === 'm-event' ? 'gui_add_event_rule' : id === 'm-traffic' ? 'gui_add_traffic_rule' : 'gui_add_bw_rule';
    const editKey = id === 'm-event' ? 'gui_edit_event_rule' : id === 'm-traffic' ? 'gui_edit_traffic_rule' : 'gui_edit_bw_rule';
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
  _actionEvents = resp.action_events || [];
  const sel = $('ev-cat'); sel.innerHTML = '<option value="" data-i18n="gui_select">Select...</option>';
  Object.keys(_catalog).forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o) });
}
function populateEvents() {
  const cat = $('ev-cat').value; const sel = $('ev-type'); sel.innerHTML = '';
  if (!cat || !_catalog[cat]) { sel.innerHTML = '<option data-i18n="gui_select_category_first">Select category first</option>'; applyI18n(sel); updateEventFilters(); return }
  Object.entries(_catalog[cat]).forEach(([k, v]) => { const o = document.createElement('option'); o.value = k; o.textContent = k + ' (' + v + ')'; sel.appendChild(o) });
  updateEventFilters();
}
function updateEventFilters() {
  const ev = $('ev-type').value;
  const showStatus = !!ev && _actionEvents.includes(ev);
  const showSeverity = !!ev && (_actionEvents.includes(ev) || ev === '*');
  $('ev-filter-row').style.display = (showStatus || showSeverity) ? '' : 'none';
  $('ev-status-group').style.display = showStatus ? '' : 'none';
  $('ev-severity-group').style.display = showSeverity ? '' : 'none';
  if (!showStatus) $('ev-status').value = 'all';
  if (!showSeverity) $('ev-severity').value = 'all';
}

/* ─── Edit Rule ───────────────────────────────────────────────────── */
async function editRule(idx, type) {
  try {
    const r = await api('/api/rules/' + idx);
    if (!r || r.error) { toast(_translations['gui_msg_rule_not_found'] || 'Rule not found', 'err'); return }
    if (type === 'event') {
      await loadCatalog();
      // Find and select category
      for (const [cat, evts] of Object.entries(_catalog)) {
        if (r.filter_value in evts) { $('ev-cat').value = cat; populateEvents(); $('ev-type').value = r.filter_value; break }
      }
      updateEventFilters();
      $('ev-status').value = r.filter_status || 'all';
      $('ev-severity').value = r.filter_severity || 'all';
      setRv('ev-tt', r.threshold_type || 'immediate');
      onEvTtChange();
      $('ev-cnt').value = r.threshold_count || 5;
      $('ev-win').value = r.threshold_window || 10;
      $('ev-cd').value = r.cooldown_minutes || 10;
      openModal('m-event', idx);
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
      openModal('m-traffic', idx);
    } else {
      $('bw-name').value = r.name || '';
      setRv('bw-mt', r.type || 'bandwidth');
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
      openModal('m-bw', idx);
    }
  } catch (e) {
    console.error(e);
    alert((_translations['gui_msg_ui_error'] || 'UI Error: {error}').replace('{error}', e.message));
  }
}

async function saveEvent() {
  const cat = $('ev-cat').value, ev = $('ev-type').value;
  if (!cat || !ev) { toast(_translations['gui_msg_select_cat_event'] || 'Select category and event', 'err'); return }
  const name = (_catalog[cat] || {})[ev] || ev;
  const data = { name, filter_value: ev, filter_status: $('ev-status').value || 'all', filter_severity: $('ev-severity').value || 'all', threshold_type: rv('ev-tt'), threshold_count: $('ev-cnt').value, threshold_window: $('ev-win').value, cooldown_minutes: $('ev-cd').value };
  if (_editIdx !== null) await put('/api/rules/' + _editIdx, data); else await post('/api/rules/event', data);
  closeModal('m-event'); toast(_translations['gui_msg_event_rule_saved'] || 'Event rule saved'); loadRules(); loadDashboard();
}
async function saveTraffic() {
  const name = $('tr-name').value.trim(); if (!name) { toast(_translations['gui_msg_name_required'] || 'Name required', 'err'); return }
  const data = { name, pd: rv('tr-pd'), port: $('tr-port').value, proto: $('tr-proto').value, src: $('tr-src').value, dst: $('tr-dst').value, ex_port: $('tr-expt').value, ex_src: $('tr-exsrc').value, ex_dst: $('tr-exdst').value, threshold_count: $('tr-cnt').value, threshold_window: $('tr-win').value, cooldown_minutes: $('tr-cd').value };
  if (_editIdx !== null) await put('/api/rules/' + _editIdx, data); else await post('/api/rules/traffic', data);
  closeModal('m-traffic'); toast(_translations['gui_msg_traffic_rule_saved'] || 'Traffic rule saved'); loadRules(); loadDashboard();
}
async function saveBW() {
  const name = $('bw-name').value.trim(); if (!name) { toast(_translations['gui_msg_name_required'] || 'Name required', 'err'); return }
  const data = {
    name, rule_type: rv('bw-mt'), pd: rv('bw-pd'),
    port: $('bw-port').value, src: $('bw-src').value, dst: $('bw-dst').value,
    ex_port: $('bw-expt').value, ex_src: $('bw-exsrc').value, ex_dst: $('bw-exdst').value,
    threshold_count: $('bw-val').value, threshold_window: $('bw-win').value, cooldown_minutes: $('bw-cd').value
  };
  if (_editIdx !== null) await put('/api/rules/' + _editIdx, { ...data, type: data.rule_type }); else await post('/api/rules/bandwidth', data);
  closeModal('m-bw'); toast(_translations['gui_msg_rule_saved'] || 'Rule saved'); loadRules(); loadDashboard();
}

function confirmBestPractices() {
  if (!confirm((_translations['gui_warn_best_practices'] || '⚠️ WARNING: This will DELETE all existing rules and replace them with best practice defaults.\n\nAre you sure you want to continue?').replace(/\\n/g, '\n'))) return;
  if (!confirm(_translations['gui_confirm_best_practices'] || 'This action cannot be undone. Confirm once more to proceed.')) return;
  runAction('best-practices');
}
