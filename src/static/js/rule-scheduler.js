// ═══ Rule Scheduler ═══
// Safe escaping for text used inside HTML attribute values (e.g. data-args).
// escapeHtml() is wrong here: it converts ' → &#039;, which the HTML parser re-decodes to ' before JS runs, breaking the string.
const jsStr = s => (s == null ? '' : String(s))
  .replace(/\\/g, '\\\\')    // \ → \\
  .replace(/'/g, "\\'")      // ' → \'
  .replace(/\r?\n|\r/g, ' ') // newlines → space
  .replace(/"/g, '&quot;');  // " → &quot; (keeps HTML attribute valid)

// Build a single-quoted-HTML-attribute-safe data-args value from a JS array.
// JSON.stringify already escapes inner double-quotes; we then HTML-escape the
// characters that would break a single-quoted attribute value.
const rsDataArgs = arr => JSON.stringify(arr)
  .replace(/&/g, '&amp;')
  .replace(/'/g, '&#39;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;');
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
        ? '<span class="rs-badge rs-badge-block" style="font-size:.7rem;">Override Deny</span>'
        : item.rule_type === 'deny'
          ? '<span class="rs-badge rs-badge-off" style="font-size:.7rem;">Deny</span>'
          : '<span class="rs-badge rs-badge-on" style="font-size:.7rem;">Allow</span>';
      const stBadge = item.enabled
        ? '<span class="rs-badge rs-badge-on">ON</span>'
        : '<span class="rs-badge rs-badge-off">OFF</span>';
      const rsName = item.rs_name.length > 20 ? escapeHtml(item.rs_name.substring(0, 20)) + '…' : escapeHtml(item.rs_name);
      tr.innerHTML =
        '<td></td>' +
        '<td style="color:var(--accent2);font-weight:600;">' + escapeHtml(String(item.rule_id)) + '</td>' +
        '<td></td>' +
        '<td>' + stBadge + '</td>' +
        '<td>' + rsName + '</td>' +
        '<td>' + ruleTypeBadge + ' ' + escapeHtml(item.description || '(' + _t('gui_rs_no_desc') + ')') + '</td>';
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
        ? '<span class="rs-mark-rs" title="' + _t('gui_rs_sch_badge_sched') + '">★</span>'
        : rs.schedule_type === 2
          ? '<span class="rs-mark-child" title="' + _t('gui_rs_sch_badge_child') + '">●</span>'
          : '';
      const provBadge = rs.provision_state === 'DRAFT'
        ? '<span class="rs-badge rs-badge-draft">DRAFT</span>'
        : '<span class="rs-badge rs-badge-active">ACTIVE</span>';
      const statusBadge = rs.enabled
        ? '<span class="rs-badge rs-badge-on">ON</span>'
        : '<span class="rs-badge rs-badge-off">OFF</span>';
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.onclick = function() { rsViewRuleset(rs.id); };
      if (rs.id === rsSelectedRsId) tr.style.background = 'rgba(255,85,0,.1)';
      tr.innerHTML =
        '<td>' + schMark + '</td>' +
        '<td>' + escapeHtml(String(rs.id)) + '</td>' +
        '<td>' + provBadge + '</td>' +
        '<td>' + statusBadge + '</td>' +
        '<td>' + escapeHtml(String(rs.rules_count)) + '</td>' +
        '<td>' + escapeHtml(rs.name) + '</td>';
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
        ? '<span class="rs-badge rs-badge-draft">DRAFT</span>'
        : '<span class="rs-badge rs-badge-active">ACTIVE</span>';
      const st = r.enabled
        ? '<span class="rs-badge rs-badge-on">ON</span>'
        : '<span class="rs-badge rs-badge-off">OFF</span>';
      const schIcon = r.is_scheduled ? '<span class="rs-mark-child" title="' + _t('gui_rs_sch_badge_child') + '">●</span>' : '';
      const descLabel = _t('gui_rs_col_desc');
      const noDesc = _t('gui_rs_no_desc');
      const descHtml = r.description
        ? '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([descLabel, r.description]) + '\'>' + rsTruncate(r.description, 30) + '</td>'
        : '<td><span style="color:var(--dim)">' + noDesc + '</span></td>';

      const srcLabel = _t('gui_rs_col_source');
      const dstLabel = _t('gui_rs_col_dest');
      const svcLabel = _t('gui_rs_col_service');
      const srcHtml = '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([srcLabel, r.source]) + '\'>' + rsTruncate(r.source, 25) + '</td>';
      const dstHtml = '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([dstLabel, r.dest]) + '\'>' + rsTruncate(r.dest, 25) + '</td>';
      const svcHtml = '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([svcLabel, r.service]) + '\'>' + rsTruncate(r.service, 25) + '</td>';

      const ruleTypeBadge = r.rule_type === 'override_deny'
        ? '<span class="rs-badge rs-badge-block">' + _t('gui_rs_rule_type_override_deny') + '</span>'
        : r.rule_type === 'deny'
          ? '<span class="rs-badge rs-badge-off">' + _t('gui_rs_rule_type_deny') + '</span>'
          : '<span class="rs-badge rs-badge-on">' + _t('gui_rs_rule_type_allow') + '</span>';
      const ruleSchedArgs = rsDataArgs([
        r.href,
        r.description || (_t('gui_rs_type_rule') + ' ' + r.id),
        false,
        rsRow.name,
        r.source,
        r.dest,
        r.service,
      ]);
      tr.innerHTML =
        '<td>' + schIcon + '</td>' +
        '<td style="color:var(--dim);font-size:.8rem;">' + (r.no || '') + '</td>' +
        '<td>' + r.id + '</td>' +
        '<td>' + prov + '</td>' +
        '<td>' + st + '</td>' +
        '<td>' + ruleTypeBadge + '</td>' +
        descHtml + srcHtml + dstHtml + svcHtml +
        '<td><button class="btn btn-sm btn-primary" data-action="rsOpenScheduleModal" data-args=\'' + ruleSchedArgs + '\'>' + _t('gui_rs_schedule_btn') + '</button></td>';
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

/* ── Truncate helper ── */
function rsTruncate(s, max) {
  if (!s) return '<span style="color:var(--dim)">' + _t('gui_rs_all') + '</span>';
  const t = escapeHtml(s);
  return t.length > max ? t.substring(0, max) + '...' : t;
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
// inside an .rs-clickable cell (e.g. the inner <span> from rsTruncate) are
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
        ? '<span class="rs-badge rs-badge-deleted">' + _t('gui_rs_status_deleted') + '</span>'
        : s.live_enabled === true
          ? '<span class="rs-badge rs-badge-on">ON</span>'
          : s.live_enabled === false
            ? '<span class="rs-badge rs-badge-off">OFF</span>'
            : '<span style="color:var(--dim)">--</span>';
      // Action badge
      let actionBadge = '';
      if (s.type === 'recurring') {
        actionBadge = s.action === 'allow'
          ? '<span class="rs-badge rs-badge-allow">' + _t('gui_rs_enable_label') + '</span>'
          : '<span class="rs-badge rs-badge-block">' + _t('gui_rs_disable_label') + '</span>';
      } else {
        actionBadge = '<span class="rs-badge rs-badge-expire">' + _t('gui_rs_expire') + '</span>';
      }
      // Timing - map day names for i18n
      const dayMap = {'Monday': _t('gui_rs_mon'),'Tuesday': _t('gui_rs_tue'),'Wednesday': _t('gui_rs_wed'),'Thursday': _t('gui_rs_thu'),'Friday': _t('gui_rs_fri'),'Saturday': _t('gui_rs_sat'),'Sunday': _t('gui_rs_sun')};
      let timing = '';
      const tzLabel = s.timezone && s.timezone !== 'local' ? s.timezone : _t('gui_rs_local_tz');
      if (s.type === 'recurring') {
        const days = (s.days || []).length === 7 ? _t('gui_rs_everyday') : (s.days || []).map(d => dayMap[d] || d.substring(0, 3)).join(', ');
        timing = days + ' ' + (s.start || '') + ' - ' + (s.end || '') + ' <span style="color:var(--accent2);font-size:.75rem;">(' + escapeHtml(tzLabel) + ')</span>';
      } else {
        timing = _t('gui_rs_until') + ' ' + (s.expire_at || '').replace('T', ' ') + ' <span style="color:var(--accent2);font-size:.75rem;">(' + escapeHtml(tzLabel) + ')</span>';
      }
      // Description (rule desc or RS name)
      const descText = escapeHtml(s.detail_name || s.name || '');
      const rsName = escapeHtml(s.detail_rs || '');
      const srcText = escapeHtml(s.detail_src || _t('gui_rs_all'));
      const dstText = escapeHtml(s.detail_dst || _t('gui_rs_all'));
      const svcText = escapeHtml(s.detail_svc || _t('gui_rs_all'));

      const descLabel = _t('gui_rs_col_desc');
      const srcLabel = _t('gui_rs_col_source');
      const dstLabel = _t('gui_rs_col_dest');
      const svcLabel = _t('gui_rs_col_service');
      tr.innerHTML =
        '<td><input type="checkbox" class="rs-sch-cb" value="' + escapeHtml(s.href) + '"></td>' +
        '<td>' + typeStr + '</td>' +
        '<td>' + liveBadge + '</td>' +
        '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([_t('gui_rs_col_name'), rsName]) + '\'>' + rsTruncate(s.detail_rs, 20) + '</td>' +
        '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([descLabel, descText]) + '\'>' + rsTruncate(s.detail_name || s.name, 20) + '</td>' +
        '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([srcLabel, srcText]) + '\'>' + rsTruncate(s.detail_src, 20) + '</td>' +
        '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([dstLabel, dstText]) + '\'>' + rsTruncate(s.detail_dst, 20) + '</td>' +
        '<td class="rs-clickable" data-action="rsShowPopup" data-args=\'' + rsDataArgs([svcLabel, svcText]) + '\'>' + rsTruncate(s.detail_svc, 20) + '</td>' +
        '<td>' + actionBadge + '</td>' +
        '<td style="font-size:.8rem;">' + timing + '</td>' +
        '<td>' + s.id + '</td>' +
        '<td><button class="rs-edit-btn" data-action="rsEditSchedule" data-args=\'' + rsDataArgs([s.id]) + '\'>' + _t('gui_rs_col_edit') + '</button></td>';
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
