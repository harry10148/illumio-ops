// ═══ Rule Scheduler ═══
// Tiny DOM-builder helper used in place of string-concatenated HTML.
// Avoids the escaping pitfalls of innerHTML for user-supplied values.
function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v == null) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k.startsWith('data-')) el.dataset[k.slice(5)] = v;
      else el.setAttribute(k, v);
    }
  }
  for (const c of children) {
    if (c == null || c === false) continue;
    if (Array.isArray(c)) {
      for (const cc of c) {
        if (cc == null || cc === false) continue;
        el.appendChild(cc instanceof Node ? cc : document.createTextNode(String(cc)));
      }
    } else {
      el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
  }
  return el;
}
let rsCurrentPage = 1;
let rsSearchQuery = '';
let rsSearchScope = 'rs_name';
let rsSelectedRsId = null;

/* ── Timezone select helper (uses shared populateTzSelect from utils.js) ── */
function rsPopulateTzSelect(selectId, selectedValue) {
  populateTzSelect(selectId, selectedValue);
}

function rsLoadTab() {
  rsSearchRulesets('');
  rsInitResizer();
}

/* ── Split-pane resizer ── */
function rsInitResizer() {
  const resizer = $('rs-resizer');
  const left = $('rs-left');
  const split = $('rs-split');
  if (!resizer || !left || !split) return;
  let startX, startW;
  function onMouseDown(e) {
    startX = e.clientX; startW = left.offsetWidth;
    resizer.classList.add('active');
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    e.preventDefault();
  }
  function onMouseMove(e) {
    const dx = e.clientX - startX;
    const newW = Math.max(180, Math.min(startW + dx, split.offsetWidth - 200));
    left.style.width = newW + 'px';
  }
  function onMouseUp() {
    resizer.classList.remove('active');
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
  }
  resizer.addEventListener('mousedown', onMouseDown);
}

/* ── Sub-tab switching ── */
function rsSubTab(which) {
  document.querySelectorAll('#p-rule-scheduler .rs-subview').forEach(el => el.style.display = 'none');
  $('rs-' + which).style.display = '';
  ['browse', 'schedules', 'logs'].forEach(t => {
    const btn = $('rs-tab-' + t);
    if (btn) btn.className = t === which ? 'btn btn-primary rs-active' : 'btn';
  });
  if (which === 'schedules') rsLoadSchedules();
  if (which === 'logs') rsLoadLogHistory();
}

function rulesSubTab(which) {
  document.querySelectorAll('#p-rules .rules-subview').forEach(el => el.style.display = 'none');
  $('rules-sv-' + which).style.display = '';
  ['rules', 'actions'].forEach(t => {
    const btn = $('rules-tab-' + t);
    if (btn) btn.className = t === which ? 'btn btn-primary rs-active' : 'btn';
  });
}

function reportsSubTab(which) {
  document.querySelectorAll('#p-reports .reports-subview').forEach(el => el.style.display = 'none');
  $('reports-sv-' + which).style.display = '';
  ['list', 'schedules'].forEach(t => {
    const btn = $('reports-tab-' + t);
    if (btn) btn.className = t === which ? 'btn btn-primary rs-active' : 'btn';
  });
  if (which === 'list') loadReports();
  if (which === 'schedules') loadSchedules();
}

/* ── Search & fetch rulesets ── */
function rsDoSearch() {
  const scope = $('rs-search-scope') ? $('rs-search-scope').value : 'rs_name';
  const q = $('rs-search') ? $('rs-search').value.trim() : '';
  if (scope === 'rule_id' || scope === 'rule_desc') {
    rsFetchRulesBySearch(q, scope === 'rule_id' ? 'id' : 'desc');
  } else {
    rsSearchQuery = (scope === 'rs_id') ? q : q;
    rsSearchScope = scope;
    rsCurrentPage = 1;
    rsFetchRulesets();
  }
}

function rsResetSearch() {
  if ($('rs-search')) $('rs-search').value = '';
  rsSearchQuery = '';
  rsSearchScope = 'rs_name';
  rsCurrentPage = 1;
  rsFetchRulesets();
}

function rsSearchRulesets(q) {
  if (q === undefined) q = ($('rs-search') ? $('rs-search').value.trim() : '');
  rsSearchQuery = q;
  rsCurrentPage = 1;
  rsFetchRulesets();
}

async function rsFetchRulesBySearch(q, scope) {
  const tbody = $('rs-rulesets-body');
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--dim);padding:24px;">' + _t('gui_rs_searching') + '</td></tr>';
  $('rs-pagination').innerHTML = '';
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000);
    const res = await fetch('/api/rule_scheduler/rules/search?' + new URLSearchParams({ q, scope }), { signal: ctrl.signal });
    clearTimeout(timer);
    const data = await res.json();
    tbody.innerHTML = '';
    if (!data.items.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--dim);padding:24px;">' + _t('gui_rs_no_results') + '</td></tr>';
      return;
    }
    data.items.forEach(item => {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.onclick = function() { rsViewRuleset(item.rs_id); };
      const ruleTypeBadge = item.rule_type === 'override_deny'
        ? h('span', { class: 'rs-badge rs-badge-block', style: { fontSize: '.7rem' } }, 'Override Deny')
        : item.rule_type === 'deny'
          ? h('span', { class: 'rs-badge rs-badge-off', style: { fontSize: '.7rem' } }, 'Deny')
          : h('span', { class: 'rs-badge rs-badge-on', style: { fontSize: '.7rem' } }, 'Allow');
      const stBadge = item.enabled
        ? h('span', { class: 'rs-badge rs-badge-on' }, 'ON')
        : h('span', { class: 'rs-badge rs-badge-off' }, 'OFF');
      const rsNameStr = item.rs_name.length > 20 ? item.rs_name.substring(0, 20) + '…' : item.rs_name;
      tr.replaceChildren(
        h('td'),
        h('td', { style: { color: 'var(--accent2)', fontWeight: '600' } }, String(item.rule_id)),
        h('td'),
        h('td', null, stBadge),
        h('td', null, rsNameStr),
        h('td', null, ruleTypeBadge, ' ', item.description || '(' + _t('gui_rs_no_desc') + ')'),
      );
      tbody.appendChild(tr);
    });
    $('rs-pagination').innerHTML = '<span class="rs-pg-info">' + data.items.length + ' ' + _t('gui_rs_rule_results') + '</span>';
    initTableResizers();
  } catch (e) {
    const msg = e.name === 'AbortError' ? _t('gui_rs_request_timed_out') : e.message;
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:24px;">' + escapeHtml(msg) + '</td></tr>';
  }
}

async function rsFetchRulesets() {
  const params = new URLSearchParams({ q: rsSearchQuery, page: rsCurrentPage, size: 50 });
  const tbody = $('rs-rulesets-body');
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--dim);padding:24px;">' + _t('gui_rs_loading_rulesets') + '</td></tr>';
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000);
    const res = await fetch('/api/rule_scheduler/rulesets?' + params, { signal: ctrl.signal });
    clearTimeout(timer);
    const data = await res.json();
    const tbody = $('rs-rulesets-body');
    tbody.innerHTML = '';
    if (data.error) {
      toast(_t('gui_rs_warn_prefix') + ': ' + data.error, true);
    }
    data.items.forEach(rs => {
      const schMark = rs.schedule_type === 1
        ? h('span', { class: 'rs-mark-rs', title: _t('gui_rs_sch_badge_sched') }, '★')
        : rs.schedule_type === 2
          ? h('span', { class: 'rs-mark-child', title: _t('gui_rs_sch_badge_child') }, '●')
          : null;
      const provBadge = rs.provision_state === 'DRAFT'
        ? h('span', { class: 'rs-badge rs-badge-draft' }, 'DRAFT')
        : h('span', { class: 'rs-badge rs-badge-active' }, 'ACTIVE');
      const statusBadge = rs.enabled
        ? h('span', { class: 'rs-badge rs-badge-on' }, 'ON')
        : h('span', { class: 'rs-badge rs-badge-off' }, 'OFF');
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.onclick = function() { rsViewRuleset(rs.id); };
      if (rs.id === rsSelectedRsId) tr.style.background = 'rgba(255,85,0,.1)';
      tr.replaceChildren(
        h('td', null, schMark),
        h('td', null, String(rs.id)),
        h('td', null, provBadge),
        h('td', null, statusBadge),
        h('td', null, String(rs.rules_count)),
        h('td', null, rs.name),
      );
      tbody.appendChild(tr);
    });
    // Pagination
    const pg = $('rs-pagination');
    const totalPages = Math.ceil(data.total / data.size) || 1;
    pg.innerHTML = '<span class="rs-pg-info">' + _t('gui_rs_pagination')
      .replace('{page}', data.page)
      .replace('{totalPages}', totalPages)
      .replace('{total}', data.total) + '</span>';
    if (data.page > 1) {
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm';
      btn.textContent = _t('gui_rs_prev');
      btn.addEventListener('click', () => { rsCurrentPage--; rsFetchRulesets(); });
      pg.appendChild(btn);
    }
    if (data.page < totalPages) {
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm';
      btn.textContent = _t('gui_rs_next');
      btn.addEventListener('click', () => { rsCurrentPage++; rsFetchRulesets(); });
      pg.appendChild(btn);
    }
    initTableResizers();
  } catch (e) {
    const msg = e.name === 'AbortError' ? _t('gui_rs_request_timed_out_unreachable') : e.message;
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:24px;">' + escapeHtml(msg) + '</td></tr>';
    toast(_t('gui_rs_error_loading_rulesets').replace('{error}', msg), true);
  }
}

/* ── View ruleset detail (right pane) ── */
async function rsViewRuleset(rsId) {
  rsSelectedRsId = rsId;
  // Highlight selected row
  const rows = $('rs-rulesets-body').querySelectorAll('tr');
  rows.forEach(r => r.style.background = '');
  rows.forEach(r => { if (r.onclick && r.querySelector('td:nth-child(2)') && r.querySelector('td:nth-child(2)').textContent == rsId) r.style.background = 'rgba(255,85,0,.1)'; });

  $('rs-right-placeholder').style.display = 'none';
  $('rs-detail').style.display = '';
  $('rs-detail-title').textContent = _t('gui_rs_loading');
  $('rs-detail-meta').innerHTML = '';
  $('rs-rules-body').innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--dim);padding:24px;">' + _t('gui_rs_loading_rules') + '</td></tr>';
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000);
    const res = await fetch('/api/rule_scheduler/rulesets/' + rsId, { signal: ctrl.signal });
    clearTimeout(timer);
    const data = await res.json();
    const rsRow = data.ruleset;

    $('rs-detail-title').textContent = rsRow.name;
    const provBadge = rsRow.provision_state === 'DRAFT'
      ? '<span class="rs-badge rs-badge-draft">DRAFT</span>'
      : '<span class="rs-badge rs-badge-active">ACTIVE</span>';
    const statusBadge = rsRow.enabled
      ? '<span class="rs-badge rs-badge-on">ON</span>'
      : '<span class="rs-badge rs-badge-off">OFF</span>';
    const schRsBadge = rsRow.is_scheduled ? ' &nbsp; <span class="rs-mark-rs" title="' + _t('gui_rs_sch_badge_sched') + '">★ ' + _t('gui_rs_sch_badge_sched') + '</span>' : '';
    const detailMeta = $('rs-detail-meta');
    detailMeta.innerHTML = 'ID: ' + rsRow.id + ' &nbsp; ' + provBadge + ' &nbsp; ' + statusBadge + schRsBadge + ' &nbsp; ';
    const schedBtn = document.createElement('button');
    schedBtn.className = 'btn btn-sm btn-primary';
    schedBtn.textContent = _t('gui_rs_schedule_rs_btn');
    schedBtn.addEventListener('click', () => rsOpenScheduleModal(rsRow.href, rsRow.name, true, rsRow.name));
    detailMeta.appendChild(schedBtn);

    const tbody = $('rs-rules-body');
    tbody.innerHTML = '';

    data.rules.forEach(r => {
      const tr = document.createElement('tr');
      const prov = r.provision_state === 'DRAFT'
        ? h('span', { class: 'rs-badge rs-badge-draft' }, 'DRAFT')
        : h('span', { class: 'rs-badge rs-badge-active' }, 'ACTIVE');
      const st = r.enabled
        ? h('span', { class: 'rs-badge rs-badge-on' }, 'ON')
        : h('span', { class: 'rs-badge rs-badge-off' }, 'OFF');
      const schIcon = r.is_scheduled
        ? h('span', { class: 'rs-mark-child', title: _t('gui_rs_sch_badge_child') }, '●')
        : null;
      const descLabel = _t('gui_rs_col_desc');
      const noDesc = _t('gui_rs_no_desc');
      const clickableTd = (label, value, max) => {
        const td = h('td', { class: 'rs-clickable' }, rsTruncateNode(value, max));
        td.dataset.action = 'rsShowPopup';
        td.dataset.args = JSON.stringify([label, value == null ? '' : String(value)]);
        return td;
      };
      const descTd = r.description
        ? clickableTd(descLabel, r.description, 30)
        : h('td', null, h('span', { style: { color: 'var(--dim)' } }, noDesc));

      const srcLabel = _t('gui_rs_col_source');
      const dstLabel = _t('gui_rs_col_dest');
      const svcLabel = _t('gui_rs_col_service');
      const srcTd = clickableTd(srcLabel, r.source, 25);
      const dstTd = clickableTd(dstLabel, r.dest, 25);
      const svcTd = clickableTd(svcLabel, r.service, 25);

      const ruleTypeBadge = r.rule_type === 'override_deny'
        ? h('span', { class: 'rs-badge rs-badge-block' }, _t('gui_rs_rule_type_override_deny'))
        : r.rule_type === 'deny'
          ? h('span', { class: 'rs-badge rs-badge-off' }, _t('gui_rs_rule_type_deny'))
          : h('span', { class: 'rs-badge rs-badge-on' }, _t('gui_rs_rule_type_allow'));
      const schedBtn = h('button', { class: 'btn btn-sm btn-primary' }, _t('gui_rs_schedule_btn'));
      schedBtn.dataset.action = 'rsOpenScheduleModal';
      schedBtn.dataset.args = JSON.stringify([
        r.href,
        r.description || (_t('gui_rs_type_rule') + ' ' + r.id),
        false,
        rsRow.name,
        r.source,
        r.dest,
        r.service,
      ]);
      tr.replaceChildren(
        h('td', null, schIcon),
        h('td', { style: { color: 'var(--dim)', fontSize: '.8rem' } }, r.no || ''),
        h('td', null, String(r.id)),
        h('td', null, prov),
        h('td', null, st),
        h('td', null, ruleTypeBadge),
        descTd, srcTd, dstTd, svcTd,
        h('td', null, schedBtn),
      );
      tbody.appendChild(tr);
    });
    initTableResizers();

  } catch (e) {
    const msg = e.name === 'AbortError' ? _t('gui_rs_request_timed_out') : e.message;
    $('rs-detail-title').textContent = _t('gui_rs_error_prefix');
    $('rs-rules-body').innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--danger);padding:24px;">' + escapeHtml(msg) + '</td></tr>';
    toast(_t('gui_rs_error_loading_ruleset_detail').replace('{error}', msg), true);
  }
}

/* ── Truncate helper (returns a DOM Node for safe insertion) ── */
function rsTruncateNode(s, max) {
  if (!s) return h('span', { style: { color: 'var(--dim)' } }, _t('gui_rs_all'));
  const str = String(s);
  return document.createTextNode(str.length > max ? str.substring(0, max) + '...' : str);
}

/* ── Detail popup for clickable cells ──
 * Invoked via the global event dispatcher (see _event_dispatcher.js).
 * `this` is bound to the clicked cell; bubbling is left intact and the
 * outside-click handler below uses closest('.rs-clickable') to ignore
 * clicks that originate inside any clickable cell. */
function rsShowPopup(title, text) {
  const popup = $('rs-detail-popup');
  $('rs-popup-title').textContent = title;
  $('rs-popup-body').textContent = String(text == null ? '' : text).replace(/\\'/g, "'");
  popup.style.display = 'block';
  // Position near the cell that was clicked
  const rect = (this && this.getBoundingClientRect) ? this.getBoundingClientRect() : { right: 0, left: 0, top: 0 };
  let left = rect.right + 8;
  let top = rect.top;
  if (left + 420 > window.innerWidth) left = rect.left - 430;
  if (left < 0) left = 8;
  if (top + 200 > window.innerHeight) top = window.innerHeight - 210;
  popup.style.left = left + 'px';
  popup.style.top = top + 'px';
}

function rsClosePopup() {
  $('rs-detail-popup').style.display = 'none';
}

// Close popup on outside click. Use closest() so clicks on elements nested
// inside an .rs-clickable cell (e.g. the inner <span> from rsTruncateNode) are
// treated as clicks on the cell and don't dismiss the popup.
document.addEventListener('click', function(e) {
  const popup = $('rs-detail-popup');
  if (popup && popup.style.display === 'block' && !popup.contains(e.target) && !e.target.closest('.rs-clickable')) {
    popup.style.display = 'none';
  }
});

/* ── Schedule modal ── */
function rsOpenScheduleModal(href, name, isRs, detailRs, src, dst, svc) {
  $('rs-sch-href').value = href;
  $('rs-sch-name').value = name;
  $('rs-sch-is-rs').value = isRs ? '1' : '0';
  $('rs-sch-detail-rs').value = detailRs || '';
  $('rs-sch-detail-src').value = src || _t('gui_rs_all');
  $('rs-sch-detail-dst').value = dst || _t('gui_rs_all');
  $('rs-sch-detail-svc').value = svc || _t('gui_rs_all');
  $('rs-sch-edit-id').value = '';
  // Show target label
  $('rs-sch-target-label').textContent = (isRs ? '[' + _t('gui_rs_type_ruleset') + '] ' : '[' + _t('gui_rs_type_rule') + '] ') + name;
  // Reset form
  document.querySelector('input[name="rs-sch-type"][value="recurring"]').checked = true;
  document.querySelector('input[name="rs-sch-action"][value="allow"]').checked = true;
  document.querySelectorAll('.rs-day-cb').forEach(cb => { cb.checked = ['Monday','Tuesday','Wednesday','Thursday','Friday'].includes(cb.value); });
  $('rs-sch-start').value = '08:00';
  $('rs-sch-end').value = '18:00';
  rsPopulateTzSelect('rs-sch-timezone');
  rsPopulateTzSelect('rs-sch-timezone-ot');
  rsSchTypeChanged();
  openModal('m-rs-schedule');
}

function rsSchTypeChanged() {
  const isRecurring = document.querySelector('input[name="rs-sch-type"]:checked').value === 'recurring';
  $('rs-sch-recurring-fields').style.display = isRecurring ? '' : 'none';
  $('rs-sch-onetime-fields').style.display = isRecurring ? 'none' : '';
}

async function rsSaveSchedule() {
  const type = document.querySelector('input[name="rs-sch-type"]:checked').value;
  const body = {
    href: $('rs-sch-href').value,
    name: $('rs-sch-name').value,
    is_ruleset: $('rs-sch-is-rs').value === '1',
    detail_rs: $('rs-sch-detail-rs').value,
    detail_src: $('rs-sch-detail-src').value,
    detail_dst: $('rs-sch-detail-dst').value,
    detail_svc: $('rs-sch-detail-svc').value,
    detail_name: $('rs-sch-name').value,
    type: type
  };
  if (type === 'recurring') {
    body.action = document.querySelector('input[name="rs-sch-action"]:checked').value;
    body.days = [...document.querySelectorAll('.rs-day-cb:checked')].map(cb => cb.value);
    body.start = $('rs-sch-start').value;
    body.end = $('rs-sch-end').value;
    body.timezone = $('rs-sch-timezone').value || 'local';
    if (!body.start || !body.end || body.days.length === 0) {
      return toast(_t('gui_rs_fill_days_time'), true);
    }
  } else {
    const expVal = $('rs-sch-expire').value;
    if (!expVal) return toast(_t('gui_rs_set_expire'), true);
    body.expire_at = expVal.replace('T', ' ');
    body.timezone = $('rs-sch-timezone-ot').value || 'local';
  }
  // If editing, include id
  const editId = $('rs-sch-edit-id').value;
  if (editId) body.id = parseInt(editId);
  try {
    const res = await fetch('/api/rule_scheduler/schedules', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken() }, body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.ok) {
      closeModal('m-rs-schedule');
      toast(_t('gui_rs_saved') + ' (ID: ' + data.id + ')');
      rsFetchRulesets();
      rsLoadSchedules();
    } else {
      toast(_t('gui_rs_error_prefix') + ': ' + (data.error || _t('gui_rs_unknown')), true);
    }
  } catch (e) {
    toast(_t('gui_rs_error_save_failed').replace('{error}', e.message), true);
  }
}

/* ── Schedules list ── */
async function rsLoadSchedules() {
  const tbody = $('rs-schedules-body');
  tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;color:var(--dim);padding:24px;">' + _t('gui_rs_loading_schedules') + '</td></tr>';
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000);
    const res = await fetch('/api/rule_scheduler/schedules', { signal: ctrl.signal });
    clearTimeout(timer);
    const list = await res.json();
    const tbody = $('rs-schedules-body');
    tbody.innerHTML = '';
    list.forEach(s => {
      const tr = document.createElement('tr');
      // Type
      const typeStr = s.is_ruleset ? _t('gui_rs_type_ruleset') : _t('gui_rs_type_rule');
      // Live status badge
      const liveBadge = s.pce_status === 'deleted'
        ? h('span', { class: 'rs-badge rs-badge-deleted' }, _t('gui_rs_status_deleted'))
        : s.live_enabled === true
          ? h('span', { class: 'rs-badge rs-badge-on' }, 'ON')
          : s.live_enabled === false
            ? h('span', { class: 'rs-badge rs-badge-off' }, 'OFF')
            : h('span', { style: { color: 'var(--dim)' } }, '--');
      // Action badge
      let actionBadge;
      if (s.type === 'recurring') {
        actionBadge = s.action === 'allow'
          ? h('span', { class: 'rs-badge rs-badge-allow' }, _t('gui_rs_enable_label'))
          : h('span', { class: 'rs-badge rs-badge-block' }, _t('gui_rs_disable_label'));
      } else {
        actionBadge = h('span', { class: 'rs-badge rs-badge-expire' }, _t('gui_rs_expire'));
      }
      // Timing - map day names for i18n
      const dayMap = {'Monday': _t('gui_rs_mon'),'Tuesday': _t('gui_rs_tue'),'Wednesday': _t('gui_rs_wed'),'Thursday': _t('gui_rs_thu'),'Friday': _t('gui_rs_fri'),'Saturday': _t('gui_rs_sat'),'Sunday': _t('gui_rs_sun')};
      const tzLabel = s.timezone && s.timezone !== 'local' ? s.timezone : _t('gui_rs_local_tz');
      const tzSpan = h('span', { style: { color: 'var(--accent2)', fontSize: '.75rem' } }, '(' + tzLabel + ')');
      let timingChildren;
      if (s.type === 'recurring') {
        const days = (s.days || []).length === 7 ? _t('gui_rs_everyday') : (s.days || []).map(d => dayMap[d] || d.substring(0, 3)).join(', ');
        timingChildren = [days + ' ' + (s.start || '') + ' - ' + (s.end || '') + ' ', tzSpan];
      } else {
        timingChildren = [_t('gui_rs_until') + ' ' + (s.expire_at || '').replace('T', ' ') + ' ', tzSpan];
      }
      // Description (rule desc or RS name) - raw text; DOM API escapes via textContent.
      const descLabel = _t('gui_rs_col_desc');
      const srcLabel = _t('gui_rs_col_source');
      const dstLabel = _t('gui_rs_col_dest');
      const svcLabel = _t('gui_rs_col_service');
      const popupTd = (label, value, displaySource, max) => {
        const td = h('td', { class: 'rs-clickable' }, rsTruncateNode(displaySource, max));
        td.dataset.action = 'rsShowPopup';
        td.dataset.args = JSON.stringify([label, value == null ? '' : String(value)]);
        return td;
      };
      const cb = h('input', { type: 'checkbox', class: 'rs-sch-cb', value: s.href || '' });
      const editBtn = h('button', { class: 'rs-edit-btn' }, _t('gui_rs_col_edit'));
      editBtn.dataset.action = 'rsEditSchedule';
      editBtn.dataset.args = JSON.stringify([s.id]);
      tr.replaceChildren(
        h('td', null, cb),
        h('td', null, typeStr),
        h('td', null, liveBadge),
        popupTd(_t('gui_rs_col_name'), s.detail_rs || '', s.detail_rs, 20),
        popupTd(descLabel, s.detail_name || s.name || '', s.detail_name || s.name, 20),
        popupTd(srcLabel, s.detail_src || _t('gui_rs_all'), s.detail_src, 20),
        popupTd(dstLabel, s.detail_dst || _t('gui_rs_all'), s.detail_dst, 20),
        popupTd(svcLabel, s.detail_svc || _t('gui_rs_all'), s.detail_svc, 20),
        h('td', null, actionBadge),
        h('td', { style: { fontSize: '.8rem' } }, ...timingChildren),
        h('td', null, String(s.id)),
        h('td', null, editBtn),
      );
      tbody.appendChild(tr);
    });
    initTableResizers();
  } catch (e) {
    const msg = e.name === 'AbortError' ? _t('gui_rs_request_timed_out_unreachable') : e.message;
    tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;color:var(--danger);padding:24px;">' + escapeHtml(msg) + '</td></tr>';
    toast(_t('gui_rs_error_loading_schedules').replace('{error}', msg), true);
  }
}

/* ── Edit schedule (load into modal) ── */
async function rsEditSchedule(id) {
  try {
    const res = await fetch('/api/rule_scheduler/schedules');
    const list = await res.json();
    const s = list.find(x => String(x.id) === String(id));
    if (!s) return toast('Schedule not found', true);
    $('rs-sch-href').value = s.href || '';
    $('rs-sch-name').value = s.detail_name || s.name || '';
    $('rs-sch-is-rs').value = s.is_ruleset ? '1' : '0';
    $('rs-sch-detail-rs').value = s.detail_rs || '';
    $('rs-sch-detail-src').value = s.detail_src || _t('gui_rs_all');
    $('rs-sch-detail-dst').value = s.detail_dst || _t('gui_rs_all');
    $('rs-sch-detail-svc').value = s.detail_svc || _t('gui_rs_all');
    $('rs-sch-edit-id').value = s.id;
    $('rs-sch-target-label').textContent = (s.is_ruleset ? '[' + _t('gui_rs_type_ruleset') + '] ' : '[' + _t('gui_rs_type_rule') + '] ') + (s.detail_name || s.name || '');
    // Set type
    const typeRadio = document.querySelector('input[name="rs-sch-type"][value="' + (s.type || 'recurring') + '"]');
    if (typeRadio) typeRadio.checked = true;
    rsSchTypeChanged();
    rsPopulateTzSelect('rs-sch-timezone', s.timezone);
    rsPopulateTzSelect('rs-sch-timezone-ot', s.timezone);
    if (s.type === 'recurring') {
      const actionRadio = document.querySelector('input[name="rs-sch-action"][value="' + (s.action || 'allow') + '"]');
      if (actionRadio) actionRadio.checked = true;
      document.querySelectorAll('.rs-day-cb').forEach(cb => { cb.checked = (s.days || []).includes(cb.value); });
      $('rs-sch-start').value = s.start || '08:00';
      $('rs-sch-end').value = s.end || '18:00';
    } else {
      const exp = (s.expire_at || '').replace(' ', 'T');
      $('rs-sch-expire').value = exp;
    }
    openModal('m-rs-schedule');
  } catch (e) {
    toast(_t('gui_rs_error_loading_schedule_for_editing').replace('{error}', e.message), true);
  }
}

function rsToggleAll(master) {
  document.querySelectorAll('.rs-sch-cb').forEach(cb => cb.checked = master.checked);
}

async function rsDeleteSelected() {
  const hrefs = [...document.querySelectorAll('.rs-sch-cb:checked')].map(cb => cb.value);
  if (hrefs.length === 0) return toast(_t('gui_rs_no_selection'), true);
  if (!confirm(_t('gui_rs_confirm_delete').replace('{count}', hrefs.length))) return;
  try {
    const res = await fetch('/api/rule_scheduler/schedules/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken() }, body: JSON.stringify({ hrefs })
    });
    const data = await res.json();
    if (data.ok) {
      toast(_t('gui_rs_deleted').replace('{count}', data.deleted.length));
      rsLoadSchedules();
    }
  } catch (e) {
    toast(_t('gui_rs_error_delete_failed').replace('{error}', e.message), true);
  }
}

/* ── Logs / Manual check ── */
function rsClearLog() {
  const log = $('rs-log-output');
  if (log) log.textContent = '';
}

async function rsLoadLogHistory() {
  const log = $('rs-log-output');
  try {
    const res = await fetch('/api/rule_scheduler/logs');
    const data = await res.json();
    const history = data.history || [];
    if (!history.length) {
      log.textContent = _t('gui_rs_execution_history_empty');
      return;
    }
    // Show newest first
    const lines = [];
    for (let i = history.length - 1; i >= 0; i--) {
      const entry = history[i];
      lines.push('═══ ' + entry.timestamp + ' ═══');
      lines.push(...(entry.logs || []));
      lines.push('');
    }
    log.textContent = lines.join('\n');
  } catch (e) {
    log.textContent = _t('gui_rs_error_loading_history').replace('{error}', e.message);
  }
}

async function rsRunCheck() {
  const log = $('rs-log-output');
  log.textContent = _t('gui_rs_running_check') + '\n';
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 60000);
    const res = await fetch('/api/rule_scheduler/check', { method: 'POST', signal: ctrl.signal, headers: { 'X-CSRF-Token': _csrfToken() } });
    clearTimeout(timer);
    const data = await res.json();
    log.textContent = (data.logs || []).join('\n') || _t('gui_rs_no_output');
    // Refresh full history view after manual check
    await rsLoadLogHistory();
  } catch (e) {
    const msg = e.name === 'AbortError' ? _t('gui_rs_check_timed_out_unreachable') : e.message;
    log.textContent = _t('gui_rs_error_prefix') + ': ' + msg;
  }
}
