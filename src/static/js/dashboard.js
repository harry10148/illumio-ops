/* ─── Dashboard ───────────────────────────────────────────────────── */
function formatBytes(bytes) {
  if (bytes == null || isNaN(bytes)) return '—';
  bytes = parseFloat(bytes);
  if (bytes < 0) return '—';
  if (bytes >= 1024 ** 4) return (bytes / 1024 ** 4).toFixed(2) + ' TB';
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(2) + ' GB';
  if (bytes >= 1024 ** 2) return (bytes / 1024 ** 2).toFixed(1) + ' MB';
  if (bytes >= 1024)      return (bytes / 1024).toFixed(1) + ' KB';
  return bytes + ' B';
}
function formatVolumeMB(mb) {
  if (mb == null || isNaN(mb)) return '—';
  mb = parseFloat(mb);
  if (mb < 0) return '—';
  const bytes = mb * 1024 * 1024;
  return formatBytes(bytes);
}
/* ─── Reports Logic ─────────────────────────────────────────────── */
async function loadReports() {
  showSkeleton('rt-body', 4);
  const r = await api('/api/reports');
  if(!r||!r.reports) return;
  const tbody = $('rt-body');
  tbody.innerHTML = '';
  if(r.reports.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><svg aria-hidden="true"><use href="#icon-play"></use></svg><h3>${_translations['gui_reports_empty_title'] || 'No Reports'}</h3><p>${_translations['gui_reports_empty'] || 'Generate your first report using the buttons above.'}</p></div></td></tr>`;
    return;
  }
  r.reports.forEach(rp => {
    const d = new Date(rp.mtime*1000).toLocaleString();
    const sz = (rp.size/1024).toFixed(1)+' KB';
    let actionBtn = '';
    if(rp.filename.endsWith('.html')) {
      actionBtn = `<a href="/reports/${escapeHtml(rp.filename)}" target="_blank" class="btn btn-sm btn-secondary">${_translations['gui_btn_view'] || 'View'}</a>`;
    } else {
      actionBtn = `<a href="/reports/${escapeHtml(rp.filename)}" download class="btn btn-sm btn-primary">${_translations['gui_btn_download'] || 'Download'}</a>`;
    }
    const delBtn = `<button class="btn btn-sm btn-danger" onclick="deleteReport('${escapeHtml(rp.filename)}')" title="Delete" style="padding:4px 8px;line-height:1;">✕</button>`;
    tbody.innerHTML += `<tr>
      <td><input type="checkbox" class="rt-chk" value="${escapeHtml(rp.filename)}" onchange="onReportCheckChange()"></td>
      <td>${escapeHtml(rp.filename)}</td>
      <td>${d}</td>
      <td>${sz}</td>
      <td><div style="display:flex;gap:6px;align-items:center;">${actionBtn}${delBtn}</div></td>
    </tr>`;
  });
  // Reset master check
  const master = $('rt-chkall');
  if (master) master.checked = false;
  onReportCheckChange();
}

function toggleReportChecks(master) {
  document.querySelectorAll('.rt-chk').forEach(cb => cb.checked = master.checked);
  onReportCheckChange();
}

function onReportCheckChange() {
  const checked = document.querySelectorAll('.rt-chk:checked');
  const btn = $('btn-bulk-del-reports');
  if (btn) {
    btn.style.display = checked.length > 0 ? '' : 'none';
    const span = btn.querySelector('span');
    if (span) {
      const t = _translations['gui_delete_selected'] || 'Delete Selected';
      span.textContent = `${t} (${checked.length})`;
    }
  }
}

async function deleteSelectedReports() {
  const checked = document.querySelectorAll('.rt-chk:checked');
  const filenames = [...checked].map(cb => cb.value);
  if (filenames.length === 0) return;

  const confirmMsg = (_translations['gui_delete_selected_confirm'] || 'Delete {count} reports?').replace('{count}', filenames.length);
  if (!confirm(confirmMsg)) return;

  try {
    const r = await post('/api/reports/bulk-delete', { filenames });
    if (r.ok || r.success) {
      toast((_translations['gui_deleted_count'] || 'Deleted {count} items').replace('{count}', (r.deleted || []).length));
      if (r.errors && r.errors.length > 0) {
        toast((_translations['gui_delete_partial'] || 'Some items failed to delete'), 'warn');
      }
      await loadReports();
    } else {
      toast(r.error || 'Bulk delete failed', 'err');
    }
  } catch (err) {
    toast('Bulk delete error: ' + err.message, 'err');
  }
}

async function deleteReport(filename) {
  const confirmMsg = (_translations['gui_delete_confirm'] || 'Delete "{filename}"?').replace('{filename}', filename);
  if (!confirm(confirmMsg)) return;
  const r = await window.fetch(`/api/reports/${encodeURIComponent(filename)}`, { method: 'DELETE', headers: { 'X-CSRF-Token': _csrfToken() } });
  const j = await r.json().catch(() => ({}));
  if (j.ok) {
    toast((_translations['gui_deleted_ok'] || 'Deleted: {filename}').replace('{filename}', filename));
    loadReports();
  } else {
    toast((_translations['gui_delete_failed'] || 'Delete failed: {error}').replace('{error}', j.error || '?'), true);
  }
}

/* ─── Report Schedules Logic ────────────────────────────────────────── */
let _schedules = [];
let _editSchedId = null;

async function loadSchedules() {
  const r = await api('/api/report-schedules');
  if (!r || !r.schedules) return;
  _schedules = r.schedules;
  renderSchedules();
}

function renderSchedules() {
  const tbody = $('sched-body');
  if (_schedules.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--dim)">${_translations['gui_sched_empty'] || 'No report schedules.'}</td></tr>`;
    return;
  }
  const typeLabels = { traffic: 'Traffic', audit: 'Audit', ven_status: 'VEN Status', policy_usage: 'Policy Usage' };
  tbody.innerHTML = _schedules.map(s => {
    const typeLabel = typeLabels[s.report_type] || s.report_type;
    let freq = s.schedule_type;
    if (s.schedule_type === 'weekly') freq += ` (${(s.day_of_week||'').slice(0,3)})`;
    else if (s.schedule_type === 'monthly') freq += ` (day ${s.day_of_month||1})`;
    const _localH = _utcToLocal(s.hour || 0);
    freq += ` ${String(_localH).padStart(2,'0')}:${String(s.minute||0).padStart(2,'0')} ${_tzDisplayLabel()}`;

    const lastRun = s.last_run ? s.last_run.slice(0,16).replace('T',' ') : (_translations['gui_sched_status_never'] || 'Never run');
    let statusBadge = '';
    if (s.last_status === 'success') statusBadge = `<span style="color:var(--green);font-weight:700;">${_translations['gui_sched_status_success']||'Success'}</span>`;
    else if (s.last_status === 'failed') statusBadge = `<span style="color:var(--red);font-weight:700;" title="${escapeHtml(s.last_error||'')}">${_translations['gui_sched_status_failed']||'Failed'}</span>`;
    else statusBadge = `<span style="color:var(--dim);">${_translations['gui_sched_status_never']||'Never run'}</span>`;

    const enabledBadge = s.enabled
      ? `<span style="color:var(--green);font-weight:700;">ON</span>`
      : `<span style="color:var(--dim);">OFF</span>`;

    const toggleLabel = s.enabled ? (_translations['gui_sched_disable']||'Disable') : (_translations['gui_sched_enable']||'Enable');
    return `<tr>
      <td style="font-weight:600;">${escapeHtml(s.name||'')}</td>
      <td>${escapeHtml(typeLabel)}</td>
      <td style="font-size:0.85rem;">${escapeHtml(freq)}</td>
      <td style="font-size:0.85rem;">${escapeHtml(lastRun)}</td>
      <td>${statusBadge}</td>
      <td>${enabledBadge}</td>
      <td>
        <div style="display:flex;gap:4px;flex-wrap:wrap;">
          <button class="btn btn-sm btn-primary" onclick="runScheduleNow(${s.id})" style="padding:3px 7px;font-size:0.8rem;" title="${_translations['gui_sched_run']||'Run'}">${_translations['gui_sched_run']||'Run'}</button>
          <button class="btn btn-sm btn-secondary" onclick="editSchedule(${s.id})" style="padding:3px 7px;font-size:0.8rem;">${_translations['gui_sched_edit']||'Edit'}</button>
          <button class="btn btn-sm" onclick="toggleSchedule(${s.id})" style="padding:3px 7px;font-size:0.8rem;background:var(--accent2);color:var(--bg);">${escapeHtml(toggleLabel)}</button>
          <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${s.id},'${escapeHtml(s.name||'')}')" style="padding:3px 7px;font-size:0.8rem;">✕</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

function onSchedFreqChange() {
  const f = $('sched-freq').value;
  $('row-day-of-week').style.display  = (f === 'weekly')  ? '' : 'none';
  $('row-day-of-month').style.display = (f === 'monthly') ? '' : 'none';
}

function onSchedReportTypeChange() {
  const isTraffic = $('sched-report-type').value === 'traffic';
  $('sched-filter-section').style.display = isTraffic ? '' : 'none';
}

function onSchedEmailChange() {
  $('row-recipients').style.display = $('sched-email').checked ? '' : 'none';
}

function openSchedModal(sched) {
  _editSchedId = sched ? sched.id : null;
  $('sched-modal-title').textContent = sched
    ? (_translations['gui_sched_modal_edit'] || 'Edit Report Schedule')
    : (_translations['gui_sched_modal_add'] || 'Add Report Schedule');
  $('sched-id').value       = sched ? sched.id : '';
  $('sched-name').value     = sched ? (sched.name || '') : '';
  $('sched-report-type').value = sched ? (sched.report_type || 'traffic') : 'traffic';
  $('sched-freq').value     = sched ? (sched.schedule_type || 'weekly') : 'weekly';
  $('sched-dow').value      = sched ? (sched.day_of_week || 'monday') : 'monday';
  $('sched-dom').value      = sched ? (sched.day_of_month || 1) : 1;
  $('sched-hour').value     = sched ? _utcToLocal(sched.hour !== undefined ? sched.hour : 8) : 8;
  $('sched-tz-label').textContent = _tzDisplayLabel();
  $('sched-minute').value   = sched ? (sched.minute !== undefined ? sched.minute : 0) : 0;
  $('sched-lookback').value = sched ? (sched.lookback_days || 7) : 7;
  $('sched-max-reports').value = sched ? (sched.max_reports !== undefined ? sched.max_reports : 30) : 30;

  const fmt = sched ? (sched.format || ['html']) : ['html'];
  $('sched-format').value = fmt.length > 1 ? 'all' : (fmt[0] || 'html');

  const emailOn = sched ? !!sched.email_report : false;
  $('sched-email').checked = emailOn;
  const recips = sched && sched.email_recipients ? sched.email_recipients.join('\n') : '';
  $('sched-recipients').value = recips;
  $('row-recipients').style.display = emailOn ? '' : 'none';

  // Show filter section only for traffic reports; reset then populate from saved schedule
  const isTraffic = (sched ? (sched.report_type || 'traffic') : 'traffic') === 'traffic';
  $('sched-filter-section').style.display = isTraffic ? '' : 'none';
  ['sched-pd-blocked','sched-pd-potential','sched-pd-allowed'].forEach(id => {
    const el = document.getElementById(id); if (el) el.checked = false;
  });
  ['sched-proto','sched-src','sched-dst','sched-port','sched-ex-src','sched-ex-dst','sched-ex-port'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  if (isTraffic && sched && sched.filters) _populateSchedFilters(sched.filters);

  onSchedFreqChange();
  $('m-sched').classList.add('show');
}

function editSchedule(id) {
  const s = _schedules.find(x => x.id === id);
  if (s) openSchedModal(s);
}

async function saveSchedule() {
  const name = $('sched-name').value.trim();
  if (!name) { toast(_translations['gui_msg_name_required'] || 'Name is required.', true); return; }

  const fmt_val = $('sched-format').value;
  const fmt = fmt_val === 'all' ? ['html', 'csv'] : [fmt_val];
  const recipsRaw = $('sched-recipients').value.trim();
  const recipients = recipsRaw ? recipsRaw.split('\n').map(r => r.trim()).filter(Boolean) : [];

  const schedFilters = $('sched-report-type').value === 'traffic' ? _collectSchedFilters() : null;
  const payload = {
    name,
    report_type: $('sched-report-type').value,
    schedule_type: $('sched-freq').value,
    day_of_week: $('sched-dow').value,
    day_of_month: parseInt($('sched-dom').value) || 1,
    hour: _localToUtc(parseInt($('sched-hour').value) || 8),
    minute: parseInt($('sched-minute').value) || 0,
    lookback_days: parseInt($('sched-lookback').value) || 7,
    max_reports: parseInt($('sched-max-reports').value) || 30,
    format: fmt,
    email_report: $('sched-email').checked,
    email_recipients: recipients,
    enabled: true,
    ...(schedFilters ? { filters: schedFilters } : {}),
  };

  const _headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken() };
  let r;
  try {
    if (_editSchedId) {
      r = await api(`/api/report-schedules/${_editSchedId}`, { method: 'PUT', headers: _headers, body: JSON.stringify(payload) });
    } else {
      r = await api('/api/report-schedules', { method: 'POST', headers: _headers, body: JSON.stringify(payload) });
    }
  } catch (err) {
    toast('Network error: ' + err.message, true);
    return;
  }
  if (r && r.ok) {
    closeModal('m-sched');
    toast(_translations['gui_sched_saved'] || 'Schedule saved.');
    loadSchedules();
  } else {
    toast((r && r.error) || 'Failed to save schedule.', true);
  }
}

async function toggleSchedule(id) {
  const r = await api(`/api/report-schedules/${id}/toggle`, { method: 'POST', headers: { 'X-CSRF-Token': _csrfToken() } });
  if (r && r.ok) {
    toast(_translations['gui_sched_toggled'] || 'Schedule updated.');
    loadSchedules();
  }
}

async function deleteSchedule(id, name) {
  const msg = (_translations['gui_sched_confirm_delete'] || 'Delete schedule "{name}"?').replace('{name}', name);
  if (!confirm(msg)) return;
  const r = await api(`/api/report-schedules/${id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': _csrfToken() } });
  if (r && r.ok) {
    toast(_translations['gui_sched_deleted'] || 'Schedule deleted.');
    loadSchedules();
  }
}

async function runScheduleNow(id) {
  const r = await api(`/api/report-schedules/${id}/run`, { method: 'POST', headers: { 'X-CSRF-Token': _csrfToken() } });
  if (r && r.ok) {
    toast(_translations['gui_sched_run_ok'] || 'Schedule started.');
    setTimeout(loadSchedules, 3000);
  } else {
    toast((_translations['gui_sched_run_failed'] || 'Schedule failed: {error}').replace('{error}', (r && r.error) || '?'), true);
  }
}

/* ─── Report Generation Progress Overlay ─────────────────────────── */

function _showGenProgress(typeLabel) {
  let el = document.getElementById('_gen-progress-overlay');
  if (!el) {
    el = document.createElement('div');
    el.id = '_gen-progress-overlay';
    el.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:9000',
      'background:rgba(0,0,0,.52)', 'display:flex',
      'align-items:center', 'justify-content:center',
    ].join(';');
    el.innerHTML = `
      <div style="background:var(--bg2,#fff);border-radius:14px;padding:36px 48px;
                  text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.3);max-width:340px;width:90%;">
        <div id="_gen-spinner" style="width:52px;height:52px;border:5px solid var(--border,#e0e0e0);
             border-top-color:var(--primary,#FF5500);border-radius:50%;
             animation:spin .8s linear infinite;margin:0 auto 20px;"></div>
        <div id="_gen-label" style="font-size:1rem;font-weight:600;color:var(--fg,#333);margin-bottom:8px;"></div>
        <div id="_gen-step" style="font-size:0.8rem;color:var(--dim,#999);min-height:1.2em;"></div>
      </div>`;
    document.body.appendChild(el);
  }
  document.getElementById('_gen-label').textContent = typeLabel;
  document.getElementById('_gen-step').textContent = '';
  el.style.display = 'flex';
}

function _updateGenStep(msg) {
  const el = document.getElementById('_gen-step');
  if (el) el.textContent = msg;
}

function _hideGenProgress(success, msg) {
  const el = document.getElementById('_gen-progress-overlay');
  if (!el) return;
  if (success !== null) {
    // Show brief result state before hiding
    const spinner = document.getElementById('_gen-spinner');
    const step    = document.getElementById('_gen-step');
    if (spinner) spinner.style.borderTopColor = success ? 'var(--success,#28a745)' : 'var(--danger,#dc3545)';
    if (step)    step.textContent = msg || '';
    setTimeout(() => { el.style.display = 'none'; }, 900);
  } else {
    el.style.display = 'none';
  }
}

/* ─── Report Generation Modal ──────────────────────────────────────── */
let _genReportType = null;

function openReportGenModal(type) {
  _genReportType = type;
  const meta = {
    traffic:      { titleKey: 'gui_gen_traffic_title', title: 'Generate Traffic Report',       icon: '#icon-play',   dates: true  },
    audit:        { titleKey: 'gui_gen_audit_title',   title: 'Generate Audit Summary',        icon: '#icon-shield', dates: true  },
    ven:          { titleKey: 'gui_gen_ven_title',     title: 'Generate VEN Status Report',    icon: '#icon-cpu',    dates: false },
    policy_usage: { titleKey: 'gui_gen_pu_title',      title: 'Generate Policy Usage Report',  icon: '#icon-shield', dates: true  },
  };
  const m = meta[type] || meta.traffic;
  $('m-gen-title').innerHTML =
    `<svg class="icon" aria-hidden="true"><use href="${m.icon}"></use></svg> ${_translations[m.titleKey] || m.title}`;
  
  if (type === 'traffic') {
    $('m-gen-source-row').style.display = '';
    $('m-gen-filters').style.display = '';
    toggleTrafficSource();
    // Reset filter fields
    ['rpt-pd-blocked','rpt-pd-potential','rpt-pd-allowed'].forEach(id => {
      const el = document.getElementById(id); if (el) el.checked = false;
    });
    ['rpt-proto','rpt-src','rpt-dst','rpt-port','rpt-ex-src','rpt-ex-dst','rpt-ex-port'].forEach(id => {
      const el = document.getElementById(id); if (el) el.value = '';
    });
  } else {
    $('m-gen-source-row').style.display = 'none';
    $('m-gen-csv-upload').style.display = 'none';
    $('m-gen-dates').style.display = m.dates ? '' : 'none';
    $('m-gen-filters').style.display = 'none';
  }
  
  $('m-gen-note').style.display  = m.dates ? 'none' : '';

  if (m.dates) {
    const now = new Date();
    const weekAgo = new Date(now); weekAgo.setDate(now.getDate() - 7);
    const fmt = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    if (!$('m-gen-start').value) $('m-gen-start').value = fmt(weekAgo);
    if (!$('m-gen-end').value)   $('m-gen-end').value   = fmt(now);
  }
  $('m-gen-report').classList.add('show');
}

function toggleTrafficSource() {
  const src = document.querySelector('input[name="traffic-source"]:checked').value;
  if (src === 'csv') {
    $('m-gen-dates').style.display = 'none';
    $('m-gen-csv-upload').style.display = '';
  } else {
    $('m-gen-dates').style.display = '';
    $('m-gen-csv-upload').style.display = 'none';
  }
}

async function confirmReportGen() {
  const typeLabels = {
    traffic:      _translations['gui_gen_traffic_title'] || 'Generating Traffic Report…',
    audit:        _translations['gui_gen_audit_title']   || 'Generating Audit Report…',
    ven:          _translations['gui_gen_ven_title']     || 'Generating VEN Status Report…',
    policy_usage: _translations['gui_gen_pu_title']      || 'Generating Policy Usage Report…',
  };
  _showGenProgress(typeLabels[_genReportType] || 'Generating Report…');
  closeModal('m-gen-report');
  if      (_genReportType === 'traffic')      await _doGenerateTraffic();
  else if (_genReportType === 'audit')        await _doGenerateAudit();
  else if (_genReportType === 'ven')          await _doGenerateVen();
  else if (_genReportType === 'policy_usage') await _doGeneratePolicyUsage();
}

function _collectReportFilters() {
  const get = id => {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
  };
  const pdBlocked  = document.getElementById('rpt-pd-blocked');
  const pdPotential = document.getElementById('rpt-pd-potential');
  const pdAllowed  = document.getElementById('rpt-pd-allowed');

  let pds = [];
  if (pdBlocked  && pdBlocked.checked)   pds.push('blocked');
  if (pdPotential && pdPotential.checked) pds.push('potentially_blocked');
  if (pdAllowed  && pdAllowed.checked)   pds.push('allowed');
  if (!pds.length) pds = null; // null means all

  const src    = get('rpt-src');
  const dst    = get('rpt-dst');
  const port   = get('rpt-port');
  const proto  = get('rpt-proto');
  const exSrc  = get('rpt-ex-src');
  const exDst  = get('rpt-ex-dst');
  const exPort = get('rpt-ex-port');

  // Heuristic: if value contains digit+dot or slash, treat as IP/CIDR; else as label key:value
  const parseSrcDst = val => {
    if (!val) return { labels: [], ip: '' };
    if (/[\d.\/:]/.test(val)) return { labels: [], ip: val };
    return { labels: [val], ip: '' };
  };

  const srcP   = parseSrcDst(src);
  const dstP   = parseSrcDst(dst);
  const exSrcP = parseSrcDst(exSrc);
  const exDstP = parseSrcDst(exDst);

  const hasFilter = pds || src || dst || port || proto || exSrc || exDst || exPort;
  if (!hasFilter) return null;

  return {
    policy_decisions: pds,
    src_labels:    srcP.labels,
    dst_labels:    dstP.labels,
    src_ip:        srcP.ip,
    dst_ip:        dstP.ip,
    port:          port,
    proto:         proto ? parseInt(proto) : null,
    ex_src_labels: exSrcP.labels,
    ex_src_ip:     exSrcP.ip,
    ex_dst_labels: exDstP.labels,
    ex_dst_ip:     exDstP.ip,
    ex_port:       exPort,
  };
}

function _collectSchedFilters() {
  const get = id => {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
  };
  const pdBlocked  = document.getElementById('sched-pd-blocked');
  const pdPotential = document.getElementById('sched-pd-potential');
  const pdAllowed  = document.getElementById('sched-pd-allowed');

  let pds = [];
  if (pdBlocked  && pdBlocked.checked)   pds.push('blocked');
  if (pdPotential && pdPotential.checked) pds.push('potentially_blocked');
  if (pdAllowed  && pdAllowed.checked)   pds.push('allowed');
  if (!pds.length) pds = null;

  const src    = get('sched-src');
  const dst    = get('sched-dst');
  const port   = get('sched-port');
  const proto  = get('sched-proto');
  const exSrc  = get('sched-ex-src');
  const exDst  = get('sched-ex-dst');
  const exPort = get('sched-ex-port');

  const parseSrcDst = val => {
    if (!val) return { labels: [], ip: '' };
    if (/[\d.\/:]/.test(val)) return { labels: [], ip: val };
    return { labels: [val], ip: '' };
  };

  const srcP   = parseSrcDst(src);
  const dstP   = parseSrcDst(dst);
  const exSrcP = parseSrcDst(exSrc);
  const exDstP = parseSrcDst(exDst);

  const hasFilter = pds || src || dst || port || proto || exSrc || exDst || exPort;
  if (!hasFilter) return null;

  return {
    policy_decisions: pds,
    src_labels:    srcP.labels,
    dst_labels:    dstP.labels,
    src_ip:        srcP.ip,
    dst_ip:        dstP.ip,
    port:          port,
    proto:         proto ? parseInt(proto) : null,
    ex_src_labels: exSrcP.labels,
    ex_src_ip:     exSrcP.ip,
    ex_dst_labels: exDstP.labels,
    ex_dst_ip:     exDstP.ip,
    ex_port:       exPort,
  };
}

function _populateSchedFilters(filters) {
  if (!filters) return;
  const setChk = (id, arr, val) => {
    const el = document.getElementById(id);
    if (el) el.checked = Array.isArray(arr) && arr.includes(val);
  };
  setChk('sched-pd-blocked',  filters.policy_decisions, 'blocked');
  setChk('sched-pd-potential', filters.policy_decisions, 'potentially_blocked');
  setChk('sched-pd-allowed',  filters.policy_decisions, 'allowed');
  const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
  const srcLabel = (filters.src_labels || []).join('');
  setVal('sched-src',    srcLabel || filters.src_ip || '');
  const dstLabel = (filters.dst_labels || []).join('');
  setVal('sched-dst',    dstLabel || filters.dst_ip || '');
  setVal('sched-port',   filters.port || '');
  setVal('sched-proto',  filters.proto != null ? String(filters.proto) : '');
  const exSrcLabel = (filters.ex_src_labels || []).join('');
  setVal('sched-ex-src', exSrcLabel || filters.ex_src_ip || '');
  const exDstLabel = (filters.ex_dst_labels || []).join('');
  setVal('sched-ex-dst', exDstLabel || filters.ex_dst_ip || '');
  setVal('sched-ex-port', filters.ex_port || '');
}

async function _doGenerateTraffic() {
  const src = document.querySelector('input[name="traffic-source"]:checked')?.value || 'api';
  try {
    if (src === 'csv') {
      const fileInput = $('m-gen-csv-file');
      if (!fileInput.files || fileInput.files.length === 0) {
        _hideGenProgress(false, 'No file selected');
        toast('Please select a CSV file first.', 'err');
        return;
      }
      _updateGenStep(_translations['gui_gen_step_parsing'] || 'Parsing CSV file…');
      const formData = new FormData();
      formData.append('source', 'csv');
      formData.append('format', 'all');
      formData.append('file', fileInput.files[0]);

      _updateGenStep(_translations['gui_gen_step_analysing'] || 'Running analysis modules…');
      const r = await fetch('/api/reports/generate', {
        method: 'POST',
        headers: { 'X-CSRF-Token': _csrfToken() },
        body: formData
      }).then(res => res.json());

      if (r.ok) {
        const msg = `${r.record_count} flows`;
        _hideGenProgress(true, msg);
        toast(`Traffic Report generated from CSV! ${msg}.`);
        loadReports();
      } else {
        _hideGenProgress(false, r.error || 'Generation failed');
        toast(r.error || 'Generation failed', 'err');
      }
    } else {
      const startVal = $('m-gen-start').value, endVal = $('m-gen-end').value;
      if (!startVal || !endVal || startVal > endVal) {
        _hideGenProgress(false, 'Invalid date range');
        toast(_translations['gui_invalid_date_range'] || 'Invalid date range.', 'err');
        return;
      }
      const startDate = new Date(startVal + 'T00:00:00Z').toISOString();
      const endDate   = new Date(endVal   + 'T23:59:59Z').toISOString();

      _updateGenStep(_translations['gui_gen_step_fetching'] || 'Fetching traffic from PCE…');
      // Simulate step progression for long-running API calls
      const _stepTimer = setTimeout(() => _updateGenStep(_translations['gui_gen_step_analysing'] || 'Running analysis modules…'), 5000);

      const reportFilters = _collectReportFilters();
      const r = await post('/api/reports/generate', {
        source: 'api', format: 'all',
        start_date: startDate, end_date: endDate,
        ...(reportFilters ? { filters: reportFilters } : {}),
      });
      clearTimeout(_stepTimer);
      if (r.ok) {
        const msg = `${r.record_count} flows`;
        _hideGenProgress(true, msg);
        toast(`Traffic Report generated! ${msg}.`);
        loadReports();
      } else {
        _hideGenProgress(false, r.error || 'Generation failed');
        toast(r.error || 'Generation failed', 'err');
      }
    }
  } catch(e) {
    _hideGenProgress(false, e.message);
    toast('Error: ' + e, 'err');
  }
}

async function _doGenerateAudit() {
  const startVal = $('m-gen-start').value, endVal = $('m-gen-end').value;
  if (!startVal || !endVal || startVal > endVal) {
    _hideGenProgress(false, 'Invalid date range');
    toast(_translations['gui_invalid_date_range'] || 'Invalid date range.', 'err');
    return;
  }
  const startDate = new Date(startVal + 'T00:00:00Z').toISOString();
  const endDate   = new Date(endVal   + 'T23:59:59Z').toISOString();
  _updateGenStep(_translations['gui_gen_step_fetching'] || 'Fetching audit events from PCE…');
  try {
    const _stepTimer = setTimeout(() => _updateGenStep(_translations['gui_gen_step_analysing'] || 'Running analysis modules…'), 3000);
    const r = await post('/api/audit_report/generate', {start_date:startDate, end_date:endDate});
    clearTimeout(_stepTimer);
    if (r.ok) {
      const msg = `${r.record_count} events`;
      _hideGenProgress(true, msg);
      toast(`Audit Report generated! ${msg}.`);
      loadReports();
    } else {
      _hideGenProgress(false, r.error || 'Generation failed');
      toast(r.error || 'Generation failed', 'err');
    }
  } catch(e) {
    _hideGenProgress(false, e.message);
    toast('Error: ' + e, 'err');
  }
}

async function _doGenerateVen() {
  _updateGenStep(_translations['gui_gen_step_fetching'] || 'Fetching VEN status from PCE…');
  try {
    const r = await post('/api/ven_status_report/generate', {});
    if (r.ok) {
      const kpiText = (r.kpis || []).map(k => `${k.label}: ${k.value}`).join(' | ');
      _hideGenProgress(true, kpiText || 'Done');
      toast(`VEN Status Report generated! ${kpiText}`);
      loadReports();
    } else {
      _hideGenProgress(false, r.error || 'Generation failed');
      toast(r.error || 'Generation failed', 'err');
    }
  } catch(e) {
    _hideGenProgress(false, e.message);
    toast('Error: ' + e, 'err');
  }
}

async function _doGeneratePolicyUsage() {
  _updateGenStep(_translations['gui_gen_step_fetching'] || 'Fetching policy data from PCE…');
  try {
    const start = $('m-gen-start') ? $('m-gen-start').value : null;
    const end   = $('m-gen-end')   ? $('m-gen-end').value   : null;
    const r = await post('/api/policy_usage_report/generate', { start_date: start, end_date: end });
    if (r.ok) {
      const kpiText = (r.kpis || []).map(k => `${k.label}: ${k.value}`).join(' | ');
      _hideGenProgress(true, kpiText || 'Done');
      toast(`Policy Usage Report generated! ${r.record_count} rules analysed.`);
      loadReports();
    } else {
      _hideGenProgress(false, r.error || 'Generation failed');
      toast(r.error || 'Generation failed', 'err');
    }
  } catch(e) {
    _hideGenProgress(false, e.message);
    toast('Error: ' + e, 'err');
  }
}

async function loadDashboard() {
  // Status section — failures must not block queries/translations from loading
  try {
    const d = await api('/api/status');
    if (d) {
      const _urlEl = $('hdr-meta-url');
      if (_urlEl && d.api_url) _urlEl.textContent = d.api_url;
      const _badge = $('hdr-meta');
      if (_badge) _badge.title = `PCE: ${d.api_url || _urlEl?.textContent}  |  v${d.version}`;
      $('d-rules').textContent = d.rules_count;
      $('d-health').textContent = d.health_check ? 'ON' : 'OFF';
      $('d-lang').textContent = (d.language || 'en').toUpperCase();
      if (d.timezone) _timezone = d.timezone;
      applyThemeMode(getStoredThemeMode());

      if (d.cooldowns && d.cooldowns.length > 0) {
        const activeCds = d.cooldowns.filter(c => c.remaining_mins > 0).length;
        if (activeCds > 0) {
          const title = _translations['gui_cooldown_title'] || 'Rules in Cooldown';
          $('cd-field').style.display = 'block';
          $('cd-list').innerHTML = `<div class="card" style="border-color:var(--warn);"><div class="label" style="color:var(--warn);"><span style="margin-right:4px;">⏳</span>${title}</div><div class="value" style="color:var(--warn);">${activeCds}</div></div>`;
        } else {
          $('cd-field').style.display = 'none';
          $('cd-list').innerHTML = '';
        }
      } else {
        $('cd-field').style.display = 'none';
        $('cd-list').innerHTML = '';
      }
    }
  } catch (e) {
    console.warn('[loadDashboard] status failed:', e);
  }

  await loadTranslations();
  await loadDashboardQueries();
  await loadDashboardSnapshot();
}

async function loadDashboardSnapshot() {
  try {
    const r = await api('/api/dashboard/snapshot');
    if (!r || !r.ok || !r.snapshot) return;
    const s = r.snapshot;

    // ── Legacy header cards ───────────────────────────────────────────
    const kpis = s.kpis || [];
    const tk = kpis.find(k => k.label === 'Total Flows');
    const rk = kpis.find(k => k.label && k.label.toLowerCase().includes('ransomware'));
    if (tk) { $('card-flows').style.display = 'block'; $('d-flows').textContent = tk.value; }
    if (rk) {
      $('card-ransom').style.display = 'block'; $('d-ransom').textContent = rk.value;
      let rc = 'var(--success)';
      if (rk.value.includes('High') || rk.value.includes('Critical')) rc = 'var(--danger)';
      else if (rk.value.includes('Medium')) rc = 'var(--warn)';
      $('d-ransom').style.color = rc;
    }

    // ── Traffic Report Summary section ────────────────────────────────
    if (!s.generated_at) return;  // snapshot has no traffic report data
    $('snap-placeholder').style.display = 'none';
    $('snap-content').style.display = 'block';
    $('snap-generated-at').textContent = s.generated_at;
    $('snap-date-range').textContent   = s.date_range || '—';

    // KPI cards
    const kpiGrid = $('snap-kpi-grid');
    kpiGrid.innerHTML = '';
    (s.kpis || []).forEach(k => {
      const card = document.createElement('div');
      card.style.cssText = 'background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px 14px;';
      card.innerHTML = `<div style="font-size:0.72rem;color:var(--dim);text-transform:uppercase;letter-spacing:.04em;">${escapeHtml(k.label)}</div>`
                     + `<div style="font-size:1.1rem;font-weight:700;margin-top:4px;color:var(--fg);">${escapeHtml(k.value)}</div>`;
      kpiGrid.appendChild(card);
    });

    // KPI card labels are already translated server-side (mod12 generates them in English)
    // Dynamic text uses _translations for i18n

    // Key Findings
    const fb = $('snap-findings-body');
    const findings = s.key_findings || [];
    if (findings.length) {
      fb.innerHTML = findings.map(f => {
        const sev = f.severity || '';
        let sevColor = 'var(--dim)';
        if (sev === 'CRITICAL') sevColor = '#c0392b';
        else if (sev === 'HIGH') sevColor = 'var(--danger)';
        else if (sev === 'MEDIUM') sevColor = 'var(--warn)';
        else if (sev === 'INFO') sevColor = 'var(--success)';
        return `<tr>
          <td><span style="background:${sevColor};color:#fff;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:700;">${escapeHtml(sev)}</span></td>
          <td>${escapeHtml(f.finding || '')}</td>
          <td style="color:var(--dim);font-style:italic;">${escapeHtml(f.action || '')}</td>
        </tr>`;
      }).join('');
    } else {
      fb.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--dim);padding:12px;">${_translations['gui_snap_no_findings'] || 'No findings.'}</td></tr>`;
    }

    // Policy Breakdown
    const pb = $('snap-policy-body');
    const psum = s.policy_summary || [];
    if (psum.length) {
      pb.innerHTML = psum.map(row => {
        const dec = row['Decision'] || '';
        let dColor = 'var(--fg)';
        if (dec === 'allowed') dColor = 'var(--success)';
        else if (dec === 'blocked') dColor = 'var(--danger)';
        else if (dec === 'potentially_blocked') dColor = 'var(--warn)';
        return `<tr><td style="color:${dColor};font-weight:600;">${escapeHtml(dec)}</td><td>${escapeHtml(String(row['Flows'] ?? ''))}</td></tr>`;
      }).join('');
    } else {
      pb.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--dim);">—</td></tr>';
    }

    // Top Ports
    const portsB = $('snap-ports-body');
    const ports = s.top_ports || [];
    if (ports.length) {
      portsB.innerHTML = ports.map(row =>
        `<tr><td>${escapeHtml(String(row['Port'] ?? ''))}</td><td>${escapeHtml(String(row['Flow Count'] ?? ''))}</td></tr>`
      ).join('');
    } else {
      portsB.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--dim);">—</td></tr>';
    }

    // Top Uncovered Flows
    const uncovB = $('snap-uncovered-body');
    const uncovered = s.top_uncovered || [];
    if (s.uncovered_pct != null) {
      $('snap-uncovered-pct').textContent = `(${(+s.uncovered_pct).toFixed(1)}% uncovered)`;
    }
    if (uncovered.length) {
      uncovB.innerHTML = uncovered.map(row => {
        const dec = row['Decision'] || '';
        let dColor = dec === 'blocked' ? 'var(--danger)' : 'var(--warn)';
        return `<tr>
          <td style="font-size:0.78rem;">${escapeHtml(row['Flow'] || '')}</td>
          <td><span style="color:${dColor};font-weight:600;">${escapeHtml(dec)}</span></td>
          <td>${escapeHtml(String(row['Connections'] ?? ''))}</td>
          <td style="color:var(--dim);font-size:0.78rem;">${escapeHtml(row['recommendation'] || row['Recommendation'] || '')}</td>
        </tr>`;
      }).join('');
    } else {
      uncovB.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--dim);padding:12px;">${_translations['gui_snap_no_uncovered'] || 'No uncovered flows.'}</td></tr>`;
    }

    // Top Bandwidth / Bytes
    if (s.bw_data_available) {
      $('snap-bw-wrap').style.display = 'block';
      const bwB = $('snap-bw-body');
      const bwRows = s.top_by_bytes || [];
      if (bwRows.length) {
        bwB.innerHTML = bwRows.map(row => {
          const bytes = row['Bytes Total'] ?? row['bytes_total'] ?? 0;
          const bytesStr = formatBytes(bytes);
          const dec = row['Decision'] || row['policy_decision'] || '';
          let dColor = dec === 'allowed' ? 'var(--success)' : dec === 'blocked' ? 'var(--danger)' : 'var(--warn)';
          return `<tr>
            <td>${escapeHtml(row['Src IP'] || '')}</td>
            <td>${escapeHtml(row['Dst IP'] || '')}</td>
            <td>${escapeHtml(String(row['Port'] ?? ''))}</td>
            <td>${escapeHtml(bytesStr)}</td>
            <td><span style="color:${dColor};font-weight:600;">${escapeHtml(dec)}</span></td>
          </tr>`;
        }).join('');
      } else {
        bwB.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--dim);padding:12px;">—</td></tr>';
      }
    }

  } catch(e) {
    console.warn('Dashboard Snapshot Error:', e);
  }
}
async function testConn() {
  slog('Testing PCE connection...');
  const r = await post('/api/actions/test-connection', {});
  if (r.ok) { $('d-api').textContent = 'Connected'; $('d-api').className = 'value ok'; slog('✅ Connected (HTTP ' + r.status + ')') }
  else { $('d-api').textContent = 'Error'; $('d-api').className = 'value err'; slog('❌ ' + (r.error || r.body)) }
}

async function loadDashboardQueries() {
  const rt = await window.fetch('/api/dashboard/queries');
  _dashboardQueries = await rt.json() || [];
  renderDashboardQueries();
  // Load cached results (no auto-query)
  for (let i = 0; i < _dashboardQueries.length; i++) _restoreCachedTop10(i);
}

function renderDashboardQueries() {
  const container = $('d-queries-container');
  let html = '';
  if (_dashboardQueries.length === 0) {
    html = `<div style="text-align:center;padding:20px;color:var(--dim);font-size:0.9rem;">${_translations['gui_top10_empty'] || 'No data.'}</div>`;
  } else {
    _dashboardQueries.forEach((q, i) => {
      let badgeColor = "var(--primary)";
      if (q.pd === 2) badgeColor = "var(--danger)";
      else if (q.pd === 1) badgeColor = "var(--warn)";
      else if (q.pd === 0) badgeColor = "var(--success)";

      let rankLabel = q.rank_by === 'bandwidth' ? (_translations['gui_rank_bw'] || 'Max Bandwidth (Mbps)') : (q.rank_by === 'volume' ? (_translations['gui_rank_vol'] || 'Total Volume') : (_translations['gui_rank_conn'] || 'Connection Count'));
      html += `
      <div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;">
         <div style="display:flex;align-items:center;min-height:30px;">
            <strong style="margin-right:12px;font-size:0.95rem;color:var(--accent2);">${escapeHtml(q.name)}</strong>
            <span style="font-size:10px;background:${badgeColor};color:#fff;padding:2px 6px;border-radius:4px;margin-right:8px;">PD: ${q.pd === 3 ? (_translations['gui_pd_all'] || 'All') : (q.pd === 2 ? (_translations['gui_pd_blocked'] || 'Blocked') : (q.pd === 1 ? (_translations['gui_pd_potential'] || 'Potential') : (_translations['gui_pd_allowed'] || 'Allowed')))}</span>
            <span style="font-size:10px;background:var(--dim);color:#fff;padding:2px 6px;border-radius:4px;margin-right:8px;">${rankLabel}</span>
            <span style="flex:1"></span>
            <span id="d-qstate-${i}" style="color:var(--dim);font-size:0.8rem;margin-right:12px;"></span>
            <button class="btn btn-sm" style="background:var(--bg);border:1px solid var(--border);margin-right:6px;" onclick="openQueryModal(${i})" aria-label="Edit Query Widget" title="Edit Query Widget">✏️</button>
            <button class="btn btn-primary btn-sm" onclick="runTop10Query(${i})" data-i18n="gui_run_btn">Run</button>
         </div>
         
          <table class="rule-table" style="margin-top:10px;border-top:1px solid var(--border);font-size:0.8rem;">
           <thead><tr>
             <th style="width:25px">#</th>
             <th style="width:100px" data-i18n="gui_value">Value</th>
             <th style="width:110px">First/Last Seen</th>
             <th>Source</th>
             <th>Destination</th>
             <th style="width:70px">Service</th>
             <th style="width:70px" data-i18n="gui_policy_dec">Decision</th>
             <th style="width:140px">Actions</th>
           </tr></thead>
           <tbody id="d-qbody-${i}">
            <tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_translations['gui_top10_empty'] || 'No data. Click Run to query.'}</td></tr>
          </tbody>
         </table>
      </div>`;
    });
  }
  container.innerHTML = html;
  initTableResizers();

  if (typeof applyLang === "function") applyLang();
  else loadTranslations().catch(console.error);
}

function openQueryModal(idx = -1) {
  $('dq-idx').value = idx;
  if (idx < 0) {
    $('mq-title').textContent = _translations['gui_add_query_widget'] || 'Add Query Widget';
    $('dq-name').value = '';
    $('dq-rank').value = 'count';
    document.querySelector('input[name="dq-pd"][value="3"]').checked = true;
    $('dq-port').value = ''; $('dq-proto').value = '';
    $('dq-src').value = ''; $('dq-dst').value = '';
    $('dq-expt').value = ''; $('dq-exsrc').value = ''; $('dq-exdst').value = '';
    $('dq-any-label').value = ''; $('dq-any-ip').value = '';
    $('dq-ex-any-label').value = ''; $('dq-ex-any-ip').value = '';
  } else {
    $('mq-title').textContent = 'Edit Query Widget';
    const q = _dashboardQueries[idx];
    $('dq-name').value = q.name || '';
    $('dq-rank').value = q.rank_by || 'count';
    const pdRad = document.querySelector(`input[name="dq-pd"][value="${q.pd}"]`);
    if (pdRad) pdRad.checked = true;
    $('dq-port').value = q.port || '';
    $('dq-proto').value = q.proto || '';
    $('dq-src').value = (q.src_label || '') + (q.src_ip_in ? (q.src_label ? ', ' : '') + q.src_ip_in : '');
    $('dq-dst').value = (q.dst_label || '') + (q.dst_ip_in ? (q.dst_label ? ', ' : '') + q.dst_ip_in : '');
    $('dq-expt').value = q.ex_port || '';
    $('dq-exsrc').value = (q.ex_src_label || '') + (q.ex_src_ip ? (q.ex_src_label ? ', ' : '') + q.ex_src_ip : '');
    $('dq-exdst').value = (q.ex_dst_label || '') + (q.ex_dst_ip ? (q.ex_dst_label ? ', ' : '') + q.ex_dst_ip : '');
    $('dq-any-label').value = q.any_label || '';
    $('dq-any-ip').value = q.any_ip || '';
    $('dq-ex-any-label').value = q.ex_any_label || '';
    $('dq-ex-any-ip').value = q.ex_any_ip || '';
  }
  let btn = document.querySelector('#m-query .modal-actions');
  let isEdit = idx >= 0;
  if (isEdit && !document.getElementById('m-query-del')) {
    let delBtn = document.createElement('button');
    delBtn.id = 'm-query-del';
    delBtn.className = 'btn btn-danger';
    delBtn.innerText = _translations['gui_delete'] || 'Delete';
    delBtn.style.marginRight = 'auto';
    delBtn.onclick = () => deleteTop10Query(idx);
    btn.insertBefore(delBtn, btn.firstChild);
  } else if (!isEdit && document.getElementById('m-query-del')) {
    document.getElementById('m-query-del').remove();
  }

  const m = $('m-query');
  if (m) m.classList.add('show');
}

async function saveDashboardQuery() {
  const idx = parseInt($('dq-idx').value);
  const pdMatch = document.querySelector('input[name="dq-pd"]:checked');
  const d = {
    idx: idx >= 0 ? idx : null,
    name: $('dq-name').value,
    rank_by: $('dq-rank').value,
    pd: pdMatch ? parseInt(pdMatch.value) : 3,
    port: parseInt($('dq-port').value) || null,
    proto: parseInt($('dq-proto').value) || null,
    src: $('dq-src').value, dst: $('dq-dst').value,
    ex_port: parseInt($('dq-expt').value) || null,
    ex_src: $('dq-exsrc').value, ex_dst: $('dq-exdst').value,
    any_label: $('dq-any-label').value.trim() || null,
    any_ip: $('dq-any-ip').value.trim() || null,
    ex_any_label: $('dq-ex-any-label').value.trim() || null,
    ex_any_ip: $('dq-ex-any-ip').value.trim() || null,
  };

  const r = await post('/api/dashboard/queries', d);

  if (r.ok) {
    _clearAllTop10Cache();
    const m = $('m-query');
    if (m) m.classList.remove('show');
    await loadDashboardQueries();
  }
  else alert("Error: " + r.error);
}

async function deleteTop10Query(idx) {
  if (!confirm("Delete this widget?")) return;
  const r = await fetch('/api/dashboard/queries/' + idx, { method: 'DELETE', headers: { 'X-CSRF-Token': _csrfToken() } }).then(res => res.json());
  if (r.ok) {
    _clearAllTop10Cache();
    const m = $('m-query');
    if (m) m.classList.remove('show');
    await loadDashboardQueries();
  }
  else alert("Delete failed");
}

/* ── Top 10 cache helpers ── */
function _top10CacheKey(idx) { return 'top10_cache_' + idx; }

function _saveTop10Cache(idx, data, total) {
  try {
    localStorage.setItem(_top10CacheKey(idx), JSON.stringify({ data, total, ts: Date.now() }));
  } catch (_) { /* quota exceeded — ignore */ }
}

function _clearAllTop10Cache() {
  for (let i = 0; i < 50; i++) localStorage.removeItem(_top10CacheKey(i));
}

function _restoreCachedTop10(idx) {
  const raw = localStorage.getItem(_top10CacheKey(idx));
  if (!raw) return;
  try {
    const c = JSON.parse(raw);
    if (c.data && c.data.length) {
      _renderTop10Body(idx, c.data, c.total, c.ts);
    } else {
      const ms = $(`d-qstate-${idx}`);
      if (ms) ms.textContent = (_translations['gui_top10_no_records'] || 'No records found.') + '  (' + _fmtCacheTs(c.ts) + ')';
    }
  } catch (_) { /* corrupt cache — ignore */ }
}

function _fmtCacheTs(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleString();
}

function _renderTop10Body(idx, data, total, ts) {
  const ms = $(`d-qstate-${idx}`), bd = $(`d-qbody-${idx}`);
  if (!ms || !bd) return;

  let html = '';
  data.forEach((m, i) => {
    const pBadge = m.pd === 2 ? `<span style="background:var(--danger);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${_translations['gui_pd_blocked'] || 'Blocked'}</span>` :
      m.pd === 1 ? `<span style="background:var(--warn);color:#000;padding:2px 6px;border-radius:4px;font-size:10px;">${_translations['gui_pd_potential'] || 'Potential'}</span>` :
        m.pd === 0 ? `<span style="background:var(--success);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${_translations['gui_pd_allowed'] || 'Allowed'}</span>` : m.pd;

    const sLabels = renderLabelsHtml(m.s_labels);
    const dLabels = renderLabelsHtml(m.d_labels);

    let isoBtn = '';
    if (m.s_href && m.d_href) {
      isoBtn = `<button class="btn btn-secondary btn-sm" onclick="openQuarantineModal('${m.s_href}', false, '${m.d_href}')"><span data-i18n="gui_btn_isolate">Isolate</span></button>`;
    } else if (m.s_href || m.d_href) {
      isoBtn = `<button class="btn btn-secondary btn-sm" onclick="openQuarantineModal('${m.s_href || m.d_href}')"><span data-i18n="gui_btn_isolate">Isolate</span></button>`;
    }

    const formatActor = (name, ip, href, labelsHtml, process, user) => {
      let procStr = '';
      if (process || user) {
        let p = process ? `<span style="color:var(--accent); font-weight:bold;"><i class="fas fa-microchip"></i> Process: ${escapeHtml(process)}</span>` : '';
        let u = user ? `<span style="color:var(--accent2);"><i class="fas fa-user"></i> User: ${escapeHtml(user)}</span>` : '';
        let sep = (p && u) ? '<br>' : '';
        procStr = `<div style="font-size:10px; margin-top:4px;">${p}${sep}${u}</div>`;
      }
      let a = href ? `<a href="#" style="color:var(--text);font-weight:bold;font-size:11px;">${escapeHtml(name)}</a>` : `<strong style="font-size:11px;">${escapeHtml(name)}</strong>`;
      return `${a}<br><small style="color:var(--dim);">${escapeHtml(ip)}</small>${procStr}<div style="margin-top:2px;">${labelsHtml}</div>`;
    };

    let svc_str = escapeHtml(m.svc);
    if (m.svc.length > 25) {
      let arr = m.svc.split(',').map(s => s.trim());
      let encJson = encodeURIComponent(JSON.stringify(arr));
      svc_str = `<span onclick="showCellPopover(event, 'SVC', JSON.parse(decodeURIComponent('${encJson}')))" style="cursor:pointer; border-bottom:1px dotted var(--dim); color:var(--accent);">${escapeHtml(m.svc.substring(0, 23))}...</span>`;
    }

    html += `
      <tr>
        <td>${i + 1}</td>
        <td style="font-weight:bold;color:#6f42c1;">${m.val_fmt}</td>
        <td style="font-size:10px;white-space:nowrap;">${formatDateZ(m.first_seen)}<br>${formatDateZ(m.last_seen)}</td>
        <td>${formatActor(m.s_name, m.s_ip, m.s_href, sLabels, m.s_process, m.s_user)}</td>
        <td>${formatActor(m.d_name, m.d_ip, m.d_href, dLabels, m.d_process, m.d_user)}</td>
        <td>${svc_str}</td>
        <td>${pBadge}</td>
        <td>${isoBtn}</td>
      </tr>`;
  });
  bd.innerHTML = html;
  let status = (_translations['gui_top10_found'] || 'Found {count} records. (Top 10)').replace('{count}', total);
  if (ts) status += '  (' + _fmtCacheTs(ts) + ')';
  ms.textContent = status;
  initTableResizers();
}

async function runAllQueries() {
  for (let i = 0; i < _dashboardQueries.length; i++) {
    await runTop10Query(i);
  }
}

async function runTop10Query(idx) {
  const q = _dashboardQueries[idx];
  const ms = $(`d-qstate-${idx}`), bd = $(`d-qbody-${idx}`);
  if (!ms || !bd) return;

  const payload = { ...q, mins: parseInt($('d-global-min').value) || 30 };

  ms.textContent = _translations['gui_top10_querying'] || 'Querying...';
  bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_translations['gui_top10_loading'] || 'Loading...'}</td></tr>`;

  try {
    const r = await post('/api/dashboard/top10', payload);
    if (!r.ok) throw new Error(r.error || 'Unknown error');

    if (r.data && r.data.length) {
      _saveTop10Cache(idx, r.data, r.total);
      _renderTop10Body(idx, r.data, r.total, Date.now());
    } else {
      _saveTop10Cache(idx, [], 0);
      bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_translations['gui_top10_no_records'] || 'No records found.'}</td></tr>`;
      ms.textContent = (_translations['gui_done'] || 'Done.') + '  (' + _fmtCacheTs(Date.now()) + ')';
    }
  } catch (e) {
    ms.textContent = 'Error: ' + e.message;
    bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:20px;">${_translations['gui_top10_error'] || 'Error querying data.'}</td></tr>`;
  }
}

