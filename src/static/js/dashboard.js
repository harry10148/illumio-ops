/* ─── Humanize helpers ─────────────────────────────────────────────── */
function humanTimeAgo(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr), now = new Date();
  const sec = Math.round((now - d) / 1000);
  if (sec < 5) return _t('gui_time_just_now');
  if (sec < 60) return _t('gui_time_seconds_ago').replace('{count}', sec);
  const min = Math.round(sec / 60);
  if (min < 60) return _t('gui_time_minutes_ago').replace('{count}', min);
  const hr = Math.round(min / 60);
  if (hr < 24) return _t('gui_time_hours_ago').replace('{count}', hr);
  const day = Math.round(hr / 24);
  return _t('gui_time_days_ago').replace('{count}', day);
}

/* ─── Dashboard ───────────────────────────────────────────────────── */
function _dashboardCardTone(el, tone = '') {
  if (!el) return;
  el.className = tone ? `value ${tone}` : 'value';
}

function _dashboardSetCard(id, value, tone = '') {
  const el = $(id);
  if (!el) return;
  el.textContent = value;
  _dashboardCardTone(el, tone);
}

function _pickValue(row, keys, fallback = '') {
  if (!row) return fallback;
  for (const key of keys) {
    const val = row[key];
    if (val !== undefined && val !== null && val !== '') return val;
  }
  return fallback;
}

function _buildAuditSummaryFieldset() {
  const fieldset = document.createElement('fieldset');
  fieldset.id = 'audit-fieldset';
  fieldset.style.marginBottom = '18px';
  fieldset.innerHTML = `
    <legend style="font-size:1.05rem;" data-i18n="gui_dashboard_audit_summary">Latest Audit Report Summary</legend>
    <div id="audit-placeholder" style="text-align:center;padding:24px;color:var(--dim);font-size:0.9rem;" data-i18n="gui_dashboard_no_audit_summary">
      No audit report summary found. Generate an Audit Report to populate this section.
    </div>
    <div id="audit-content" style="display:none;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
        <span style="color:var(--dim);font-size:0.82rem;"><span data-i18n="gui_snap_generated">Generated:</span> <span id="audit-generated-at">-</span></span>
        <span style="color:var(--dim);font-size:0.82rem;"><span data-i18n="gui_snap_date_range">Date Range:</span> <span id="audit-date-range">-</span></span>
      </div>
      <div id="audit-kpi-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:16px;"></div>
      <div style="display:grid;grid-template-columns:1.1fr .9fr;gap:14px;">
        <div>
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:6px;color:var(--accent2);" data-i18n="gui_dashboard_audit_attention">Attention Required</div>
          <table class="rule-table" style="font-size:0.8rem;">
            <thead>
              <tr>
                <th style="width:90px" data-i18n="gui_snap_col_severity">Severity</th>
                <th data-i18n="gui_event_type">Event Type</th>
                <th data-i18n="gui_summary">Summary</th>
              </tr>
            </thead>
            <tbody id="audit-attention-body">
              <tr><td colspan="3" style="text-align:center;color:var(--dim);padding:12px;" data-i18n="gui_no_data">No data</td></tr>
            </tbody>
          </table>
        </div>
        <div>
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:6px;color:var(--accent2);" data-i18n="gui_dashboard_audit_top_events">Top Event Types</div>
          <table class="rule-table" style="font-size:0.8rem;">
            <thead>
              <tr>
                <th data-i18n="gui_event_type">Event Type</th>
                <th data-i18n="gui_count">Count</th>
              </tr>
            </thead>
            <tbody id="audit-top-events-body">
              <tr><td colspan="2" style="text-align:center;color:var(--dim);padding:12px;" data-i18n="gui_no_data">No data</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
  return fieldset;
}

function _buildPolicyUsageSummaryFieldset() {
  const fieldset = document.createElement('fieldset');
  fieldset.id = 'policy-usage-fieldset';
  fieldset.style.marginBottom = '18px';
  fieldset.innerHTML = `
    <legend style="font-size:1.05rem;" data-i18n="gui_dashboard_policy_usage_summary">Latest Policy Usage Summary</legend>
    <div id="policy-usage-placeholder" style="text-align:center;padding:24px;color:var(--dim);font-size:0.9rem;" data-i18n="gui_dashboard_no_policy_usage_summary">
      No policy usage report summary found. Generate a Policy Usage Report to populate this section.
    </div>
    <div id="policy-usage-content" style="display:none;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
        <span style="color:var(--dim);font-size:0.82rem;"><span data-i18n="gui_snap_generated">Generated:</span> <span id="policy-usage-generated-at">-</span></span>
        <span style="color:var(--dim);font-size:0.82rem;"><span data-i18n="gui_snap_date_range">Date Range:</span> <span id="policy-usage-date-range">-</span></span>
      </div>
      <div id="policy-usage-kpi-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:16px;"></div>
      <div style="margin-bottom:16px;">
        <div style="font-weight:700;font-size:0.9rem;margin-bottom:6px;color:var(--accent2);" data-i18n="gui_pu_top_hit_ports">Top Hit Ports</div>
        <table class="rule-table" style="font-size:0.8rem;">
          <thead><tr><th data-i18n="gui_pu_col_port_proto">Port / Proto</th><th data-i18n="gui_pu_col_flows">Flows</th></tr></thead>
          <tbody id="policy-usage-top-ports-body">
            <tr><td colspan="2" style="text-align:center;color:var(--dim);padding:12px;" data-i18n="gui_no_data">No data</td></tr>
          </tbody>
        </table>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
        <div>
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:6px;color:var(--accent2);" data-i18n="gui_pu_pending_rules">Pending Rules</div>
          <table class="rule-table" style="font-size:0.8rem;">
            <thead><tr><th data-i18n="gui_rs_type_rule">Rule</th><th data-i18n="gui_rs_type_ruleset">Ruleset</th></tr></thead>
            <tbody id="policy-usage-pending-body">
              <tr><td colspan="2" style="text-align:center;color:var(--dim);padding:12px;" data-i18n="gui_no_data">No data</td></tr>
            </tbody>
          </table>
        </div>
        <div>
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:6px;color:var(--accent2);" data-i18n="gui_pu_failed_rules">Failed Rules</div>
          <table class="rule-table" style="font-size:0.8rem;">
            <thead><tr><th data-i18n="gui_rs_type_rule">Rule</th><th data-i18n="gui_rs_type_ruleset">Ruleset</th></tr></thead>
            <tbody id="policy-usage-failed-body">
              <tr><td colspan="2" style="text-align:center;color:var(--dim);padding:12px;" data-i18n="gui_no_data">No data</td></tr>
            </tbody>
          </table>
        </div>
        <div>
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:6px;color:var(--accent2);" data-i18n="gui_pu_reused_rules">Reused Rules</div>
          <table class="rule-table" style="font-size:0.8rem;">
            <thead><tr><th data-i18n="gui_rs_type_rule">Rule</th><th data-i18n="gui_rs_type_ruleset">Ruleset</th></tr></thead>
            <tbody id="policy-usage-reused-body">
              <tr><td colspan="2" style="text-align:center;color:var(--dim);padding:12px;" data-i18n="gui_no_data">No data</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
  return fieldset;
}

function ensureTrafficWorkloadLayout() {
  const panel = $('p-traffic-workload');
  const dashboard = $('p-dashboard');
  if (!panel || !dashboard || panel.dataset.layoutReady === '1') return;

  const subNav = dashboard.querySelector('.sub-nav');
  const trafficPanel = $('q-panel-traffic');
  const workloadPanel = $('q-panel-workloads');
  const legacyButton = $('qbtn-legacy');
  const legacyPanel = $('q-panel-legacy');
  const snapshotFieldset = $('snap-fieldset');

  if (snapshotFieldset && legacyPanel && snapshotFieldset.parentElement === legacyPanel) {
    dashboard.insertBefore(snapshotFieldset, legacyPanel);
  }
  if (subNav) panel.appendChild(subNav);
  if (trafficPanel) panel.appendChild(trafficPanel);
  if (workloadPanel) panel.appendChild(workloadPanel);
  if (legacyButton) panel.querySelector('.sub-nav')?.appendChild(legacyButton);
  if (legacyPanel) panel.appendChild(legacyPanel);

  panel.dataset.layoutReady = '1';
}

function ensureDashboardLayout() {
  const dashboard = $('p-dashboard');
  if (!dashboard || dashboard.dataset.layoutReady === '1') return;

  const cards = dashboard.querySelectorAll('.cards .card');
  if (cards[0]) {
    const label = cards[0].querySelector('.label');
    if (label) label.textContent = _t('gui_dashboard_rules');
  }
  if (cards[1]) {
    const label = cards[1].querySelector('.label');
    const value = cards[1].querySelector('.value');
    if (label) label.textContent = _t('gui_dashboard_cooldown');
    if (value) value.id = 'd-cooldown';
  }
  if (cards[2]) {
    const label = cards[2].querySelector('.label');
    const value = cards[2].querySelector('.value');
    if (label) label.textContent = _t('gui_dashboard_pce_health');
    if (value) value.id = 'd-pce-health';
  }
  cards.forEach((card, idx) => {
    if (idx > 2) card.style.display = 'none';
  });

  const cdField = $('cd-field');
  if (cdField) cdField.style.display = 'none';

  if (!$('audit-fieldset')) {
    const snapFieldset = $('snap-fieldset');
    const auditFieldset = _buildAuditSummaryFieldset();
    if (snapFieldset) {
      snapFieldset.insertAdjacentElement('afterend', auditFieldset);
    } else {
      dashboard.appendChild(auditFieldset);
    }
  }

  if (!$('policy-usage-fieldset')) {
    const auditFieldset = $('audit-fieldset');
    const policyUsageFieldset = _buildPolicyUsageSummaryFieldset();
    if (auditFieldset) {
      auditFieldset.insertAdjacentElement('afterend', policyUsageFieldset);
    } else {
      dashboard.appendChild(policyUsageFieldset);
    }
  }

  dashboard.dataset.layoutReady = '1';
}

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
    tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><svg aria-hidden="true"><use href="#icon-play"></use></svg><h3>${_t('gui_reports_empty_title')}</h3><p>${_t('gui_reports_empty')}</p></div></td></tr>`;
    return;
  }
  r.reports.forEach(rp => {
    const d = new Date(rp.mtime*1000).toLocaleString();
    const sz = (rp.size/1024).toFixed(1)+' KB';
    const attackMeta = _buildAttackSummaryMeta(rp.attack_summary_counts || {});
    const metaLine = rp.report_type === 'policy_usage'
      ? (_buildPolicyUsageReportMeta(rp) + attackMeta)
      : (rp.summary
          ? `<div style="font-size:0.76rem;color:var(--dim);margin-top:4px;">${escapeHtml(rp.summary)}</div>${attackMeta}`
          : attackMeta);
    const viewLabel = _t('gui_btn_view');
    const downloadLabel = _t('gui_btn_download');
    const deleteLabel = _t('gui_btn_delete');
    let actionBtn = '';
    const fnAttr = `data-fn="${escapeHtml(rp.filename)}"`;
    if(rp.filename.endsWith('.html')) {
      actionBtn = `<a href="/reports/${escapeHtml(rp.filename)}" target="_blank" class="btn btn-sm btn-secondary">${viewLabel}</a>` +
                  `<button class="btn btn-sm btn-primary" ${fnAttr} onclick="blobDownloadReport(this.dataset.fn)">${downloadLabel}</button>`;
    } else {
      actionBtn = `<button class="btn btn-sm btn-primary" ${fnAttr} onclick="blobDownloadReport(this.dataset.fn)">${downloadLabel}</button>`;
    }
    const delBtn = `<button class="btn btn-sm btn-danger" data-fn="${escapeHtml(rp.filename)}" onclick="deleteReport(this.dataset.fn)" title="${deleteLabel}" aria-label="${deleteLabel}" style="padding:4px 8px;line-height:1;">&times;</button>`;
    tbody.innerHTML += `<tr>
      <td><input type="checkbox" class="rt-chk" value="${escapeHtml(rp.filename)}" onchange="onReportCheckChange()"></td>
      <td><div>${escapeHtml(rp.filename)}</div>${metaLine}</td>
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
      const t = _t('gui_delete_selected');
      span.textContent = `${t} (${checked.length})`;
    }
  }
}

async function deleteSelectedReports() {
  const checked = document.querySelectorAll('.rt-chk:checked');
  const filenames = [...checked].map(cb => cb.value);
  if (filenames.length === 0) return;

  const confirmMsg = (_t('gui_delete_selected_confirm')).replace('{count}', filenames.length);
  if (!confirm(confirmMsg)) return;

  try {
    const r = await post('/api/reports/bulk-delete', { filenames });
    if (r.ok || r.success) {
      toast((_t('gui_deleted_count')).replace('{count}', (r.deleted || []).length));
      if (r.errors && r.errors.length > 0) {
        toast((_t('gui_delete_partial')), 'warn');
      }
      await loadReports();
    } else {
      toast(r.error || _t('gui_bulk_delete_failed'), 'err');
    }
  } catch (err) {
    toast(_t('gui_bulk_delete_error').replace('{error}', err.message), 'err');
  }
}

async function blobDownloadReport(filename) {
  try {
    // Use fetch + blob to avoid HTTPS self-signed cert download block in Chrome/Edge.
    // GET request — no CSRF token needed (only required for state-changing methods).
    const resp = await fetch(`/reports/${encodeURIComponent(filename)}?download=1`, {
      credentials: 'same-origin'
    });
    if (resp.redirected && resp.url.includes('/login')) {
      toast((_t('gui_err_unauthorized')), true);
      return;
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch(e) {
    toast((_t('gui_download_failed')).replace('{error}', e.message), true);
  }
}

async function deleteReport(filename) {
  const confirmMsg = (_t('gui_delete_confirm')).replace('{filename}', filename);
  if (!confirm(confirmMsg)) return;
  const r = await window.fetch(`/api/reports/${encodeURIComponent(filename)}`, { method: 'DELETE', headers: { 'X-CSRF-Token': _csrfToken() } });
  const j = await r.json().catch(() => ({}));
  if (j.ok) {
    toast((_t('gui_deleted_ok')).replace('{filename}', filename));
    loadReports();
  } else {
    toast((_t('gui_delete_failed')).replace('{error}', j.error || '?'), true);
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
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--dim)">${_t('gui_sched_empty')}</td></tr>`;
    return;
  }
  const typeLabels = {
    traffic: _t('gui_sched_rt_traffic'),
    audit: _t('gui_sched_rt_audit'),
    ven_status: _t('gui_sched_rt_ven'),
    policy_usage: _t('gui_sched_rt_pu'),
  };
  tbody.innerHTML = _schedules.map(s => {
    const typeLabel = typeLabels[s.report_type] || s.report_type;
    const freqBaseMap = {
      daily: _t('gui_sched_freq_daily'),
      weekly: _t('gui_sched_freq_weekly'),
      monthly: _t('gui_sched_freq_monthly'),
    };
    let freq = freqBaseMap[s.schedule_type] || s.schedule_type;
    if (s.schedule_type === 'weekly') freq += ` (${s.day_of_week || ''})`;
    else if (s.schedule_type === 'monthly') freq += ` (${_t('gui_sched_day_of_month')} ${s.day_of_month || 1})`;
    const tzLabel = s.timezone && s.timezone !== 'local' ? s.timezone : _tzDisplayLabel();
    freq += ` ${String(s.hour||0).padStart(2,'0')}:${String(s.minute||0).padStart(2,'0')} (${tzLabel})`;

    const lastRunRaw = s.last_run ? s.last_run.slice(0,16).replace('T',' ') : '';
    const lastRun = s.last_run
      ? `<span title="${escapeHtml(lastRunRaw)}">${escapeHtml(humanTimeAgo(s.last_run))}</span>`
      : escapeHtml(_t('gui_sched_status_never'));
    let statusBadge = '';
    if (s.last_status === 'success') statusBadge = `<span style="color:var(--green);font-weight:700;">${_t('gui_sched_status_success')}</span>`;
    else if (s.last_status === 'failed') statusBadge = `<span style="color:var(--red);font-weight:700;" title="${escapeHtml(s.last_error||'')}">${_t('gui_sched_status_failed')}</span>`;
    else if (s.last_status === 'running') statusBadge = `<span style="color:var(--accent);font-weight:700;">${_t('sched_running')}</span>`;
    else statusBadge = `<span style="color:var(--dim);">${_t('gui_sched_status_never')}</span>`;

    const enabledBadge = s.enabled
      ? `<span style="color:var(--green);font-weight:700;">${_t('sched_enabled_short')}</span>`
      : `<span style="color:var(--dim);">${_t('sched_disabled_short')}</span>`;

    const toggleLabel = s.enabled ? (_t('gui_sched_disable')) : (_t('gui_sched_enable'));
    return `<tr>
      <td style="font-weight:600;">${escapeHtml(s.name||'')}</td>
      <td>${escapeHtml(typeLabel)}</td>
      <td style="font-size:0.85rem;">${escapeHtml(freq)}</td>
      <td style="font-size:0.85rem;">${lastRun}</td>
      <td>${statusBadge}</td>
      <td>${enabledBadge}</td>
      <td>
        <div style="display:flex;gap:4px;flex-wrap:wrap;">
          <button class="btn btn-sm btn-primary" onclick="runScheduleNow(${s.id})" style="padding:3px 7px;font-size:0.8rem;" title="${_t('gui_sched_run')}">${_t('gui_sched_run')}</button>
          <button class="btn btn-sm btn-secondary" onclick="editSchedule(${s.id})" style="padding:3px 7px;font-size:0.8rem;">${_t('gui_sched_edit')}</button>
          <button class="btn btn-sm" onclick="toggleSchedule(${s.id})" style="padding:3px 7px;font-size:0.8rem;background:var(--accent2);color:var(--bg);">${escapeHtml(toggleLabel)}</button>
          <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${s.id},'${escapeHtml(s.name||'')}')" style="padding:3px 7px;font-size:0.8rem;">&times;</button>
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
    ? (_t('gui_sched_modal_edit'))
    : (_t('gui_sched_modal_add'));
  $('sched-id').value       = sched ? sched.id : '';
  $('sched-name').value     = sched ? (sched.name || '') : '';
  $('sched-report-type').value = sched ? (sched.report_type || 'traffic') : 'traffic';
  $('sched-freq').value     = sched ? (sched.schedule_type || 'weekly') : 'weekly';
  $('sched-dow').value      = sched ? (sched.day_of_week || 'monday') : 'monday';
  $('sched-dom').value      = sched ? (sched.day_of_month || 1) : 1;
  $('sched-hour').value     = sched ? (sched.hour !== undefined ? sched.hour : 8) : 8;
  populateTzSelect('sched-timezone', sched ? (sched.timezone || _timezone || 'local') : (_timezone || 'local'));
  $('sched-minute').value   = sched ? (sched.minute !== undefined ? sched.minute : 0) : 0;
  $('sched-lookback').value = sched ? (sched.lookback_days || 7) : 7;
  $('sched-max-reports').value = sched ? (sched.max_reports !== undefined ? sched.max_reports : 30) : 30;
  $('sched-cron-expr').value = sched ? (sched.cron_expr || '') : '';

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
  if (!name) { toast(_t('gui_msg_name_required'), true); return; }

  const fmt_val = $('sched-format').value;
  const fmt = fmt_val === 'all' ? ['html', 'csv', 'pdf', 'xlsx'] : [fmt_val];
  const recipsRaw = $('sched-recipients').value.trim();
  const recipients = recipsRaw ? recipsRaw.split('\n').map(r => r.trim()).filter(Boolean) : [];

  const schedFilters = $('sched-report-type').value === 'traffic' ? _collectSchedFilters() : null;
  const payload = {
    name,
    report_type: $('sched-report-type').value,
    schedule_type: $('sched-freq').value,
    day_of_week: $('sched-dow').value,
    day_of_month: parseInt($('sched-dom').value) || 1,
    hour: parseInt($('sched-hour').value) || 0,
    minute: parseInt($('sched-minute').value) || 0,
    timezone: $('sched-timezone').value || 'local',
    lookback_days: parseInt($('sched-lookback').value) || 7,
    max_reports: parseInt($('sched-max-reports').value) || 30,
    format: fmt,
    email_report: $('sched-email').checked,
    email_recipients: recipients,
    enabled: true,
    ...(schedFilters ? { filters: schedFilters } : {}),
    ...($('sched-cron-expr').value.trim() ? { cron_expr: $('sched-cron-expr').value.trim() } : {}),
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
    toast(_t('gui_network_error').replace('{error}', err.message), true);
    return;
  }
  if (r && r.ok) {
    closeModal('m-sched');
    toast(_t('gui_sched_saved'));
    loadSchedules();
  } else {
    toast((r && r.error) || _t('gui_sched_save_failed'), true);
  }
}

async function toggleSchedule(id) {
  const r = await api(`/api/report-schedules/${id}/toggle`, { method: 'POST', headers: { 'X-CSRF-Token': _csrfToken() } });
  if (r && r.ok) {
    toast(_t('gui_sched_toggled'));
    loadSchedules();
  }
}

async function deleteSchedule(id, name) {
  const msg = (_t('gui_sched_confirm_delete')).replace('{name}', name);
  if (!confirm(msg)) return;
  const r = await api(`/api/report-schedules/${id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': _csrfToken() } });
  if (r && r.ok) {
    toast(_t('gui_sched_deleted'));
    loadSchedules();
  }
}

async function runScheduleNow(id) {
  const r = await api(`/api/report-schedules/${id}/run`, { method: 'POST', headers: { 'X-CSRF-Token': _csrfToken() } });
  if (r && r.ok) {
    toast(_t('gui_sched_run_ok'));
    setTimeout(loadSchedules, 3000);
  } else {
    toast((_t('gui_sched_run_failed')).replace('{error}', (r && r.error) || '?'), true);
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

function _formatPolicyUsageExecutionSummary(stats, notes) {
  const s = stats || {};
  const parts = [];
  if ((s.cached_rules || 0) > 0) parts.push(`cache ${s.cached_rules}`);
  if ((s.submitted_rules || 0) > 0) parts.push(`new ${s.submitted_rules}`);
  if ((s.pending_jobs || 0) > 0) parts.push(`pending ${s.pending_jobs}`);
  if ((s.failed_jobs || 0) > 0) parts.push(`failed ${s.failed_jobs}`);
  if (!parts.length && Array.isArray(notes) && notes.length) return notes[0];
  return parts.join(' | ');
}

function _formatPolicyUsageRuleLabel(item) {
  const it = item || {};
  return it.rule_no || it.rule_id || it.ruleset_name || it.description || it.rule_href || 'rule';
}

function _formatPolicyUsageDetailPreview(stats, maxItems = 2) {
  const s = stats || {};
  const segments = [];
  const pushSegment = (label, items) => {
    if (!Array.isArray(items) || !items.length) return;
    const preview = items.slice(0, maxItems).map(_formatPolicyUsageRuleLabel).join(', ');
    const suffix = items.length > maxItems ? ` +${items.length - maxItems}` : '';
    segments.push(`${label}: ${preview}${suffix}`);
  };
  pushSegment('pending', s.pending_rule_details || []);
  pushSegment('failed', s.failed_rule_details || []);
  pushSegment('reused', s.reused_rule_details || []);
  return segments.join(' | ');
}

function _buildPolicyUsageReportMeta(rp) {
  const stats = Object.assign({}, rp.execution_stats || {});
  if (!stats.reused_rule_details && Array.isArray(rp.reused_rule_details)) stats.reused_rule_details = rp.reused_rule_details;
  if (!stats.pending_rule_details && Array.isArray(rp.pending_rule_details)) stats.pending_rule_details = rp.pending_rule_details;
  if (!stats.failed_rule_details && Array.isArray(rp.failed_rule_details)) stats.failed_rule_details = rp.failed_rule_details;

  const summary = _formatPolicyUsageExecutionSummary(stats, []);
  const detailPreview = _formatPolicyUsageDetailPreview(stats);
  const badges = [];
  if ((stats.cached_rules || 0) > 0) badges.push(`<span style="display:inline-block;padding:2px 7px;border-radius:999px;background:#edf7ed;color:#1b5e20;font-size:0.72rem;">cache ${stats.cached_rules}</span>`);
  if ((stats.submitted_rules || 0) > 0) badges.push(`<span style="display:inline-block;padding:2px 7px;border-radius:999px;background:#e3f2fd;color:#0d47a1;font-size:0.72rem;">new ${stats.submitted_rules}</span>`);
  if ((stats.pending_jobs || 0) > 0) badges.push(`<span style="display:inline-block;padding:2px 7px;border-radius:999px;background:#fff4e5;color:#8a4b00;font-size:0.72rem;">pending ${stats.pending_jobs}</span>`);
  if ((stats.failed_jobs || 0) > 0) badges.push(`<span style="display:inline-block;padding:2px 7px;border-radius:999px;background:#fdecea;color:#b42318;font-size:0.72rem;">failed ${stats.failed_jobs}</span>`);

  const lines = [];
  if (badges.length) lines.push(`<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">${badges.join('')}</div>`);
  if (detailPreview) lines.push(`<div style="font-size:0.76rem;color:var(--dim);margin-top:4px;">${escapeHtml(detailPreview)}</div>`);
  else if (summary) lines.push(`<div style="font-size:0.76rem;color:var(--dim);margin-top:4px;">${escapeHtml(summary)}</div>`);
  else if (rp.summary) lines.push(`<div style="font-size:0.76rem;color:var(--dim);margin-top:4px;">${escapeHtml(rp.summary)}</div>`);
  return lines.join('');
}

function _buildAttackSummaryMeta(counts) {
  const c = counts || {};
  const boundary = c.boundary_breaches || 0;
  const pivot = c.suspicious_pivot_behavior || 0;
  const blast = c.blast_radius || 0;
  const blind = c.blind_spots || 0;
  const actions = c.action_matrix || 0;
  const total = boundary + pivot + blast + blind + actions;
  if (!total) return '';

  const badges = [
    `B ${boundary}`,
    `P ${pivot}`,
    `R ${blast}`,
    `S ${blind}`,
    `A ${actions}`,
  ]
    .map(t => `<span style="display:inline-block;padding:2px 6px;border-radius:999px;background:#1a2c32;color:#d6d7d7;font-size:0.7rem;">${escapeHtml(t)}</span>`)
    .join('');
  const title = _t('gui_attack_summary_title');
  return `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;" title="${title}">${badges}</div>`;
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
    traffic:      { titleKey: 'gui_gen_traffic_title', icon: '#icon-play',   dates: true  },
    audit:        { titleKey: 'gui_gen_audit_title',   icon: '#icon-shield', dates: true  },
    ven:          { titleKey: 'gui_gen_ven_title',     icon: '#icon-cpu',    dates: false },
    policy_usage: { titleKey: 'gui_gen_pu_title',      icon: '#icon-shield', dates: true  },
  };
  const m = meta[type] || meta.traffic;
  $('m-gen-title').innerHTML =
    `<svg class="icon" aria-hidden="true"><use href="${m.icon}"></use></svg> ${_t(m.titleKey)}`;
  
  if (type === 'traffic') {
    $('m-gen-source-row').style.display = '';
    $('m-gen-filters').style.display = '';
    $('m-gen-profile-row').style.display = '';
    $('m-gen-clip-row').style.display = '';
    toggleTrafficSource();
    // Reset filter fields
    ['rpt-pd-blocked','rpt-pd-potential','rpt-pd-allowed'].forEach(id => {
      const el = document.getElementById(id); if (el) el.checked = false;
    });
    ['rpt-proto','rpt-src','rpt-dst','rpt-port','rpt-ex-src','rpt-ex-dst','rpt-ex-port',
     'rpt-any-label','rpt-any-ip','rpt-ex-any-label','rpt-ex-any-ip'].forEach(id => {
      const el = document.getElementById(id); if (el) el.value = '';
    });
  } else {
    $('m-gen-source-row').style.display = 'none';
    $('m-gen-csv-upload').style.display = 'none';
    $('m-gen-dates').style.display = m.dates ? '' : 'none';
    $('m-gen-filters').style.display = 'none';
    $('m-gen-profile-row').style.display = 'none';
    $('m-gen-clip-row').style.display = 'none';
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
    $('m-gen-clip-row').style.display = 'none';
  } else {
    $('m-gen-dates').style.display = '';
    $('m-gen-csv-upload').style.display = 'none';
    $('m-gen-clip-row').style.display = '';
  }
}

async function confirmReportGen() {
  const typeLabels = {
    traffic:      _t('gui_gen_traffic_title'),
    audit:        _t('gui_gen_audit_title'),
    ven:          _t('gui_gen_ven_title'),
    policy_usage: _t('gui_gen_pu_title'),
  };
  _showGenProgress(typeLabels[_genReportType] || _t('gui_gen_fallback_title'));
  closeModal('m-gen-report');
  if      (_genReportType === 'traffic')      await _doGenerateTraffic();
  else if (_genReportType === 'audit')        await _doGenerateAudit();
  else if (_genReportType === 'ven')          await _doGenerateVen();
  else if (_genReportType === 'policy_usage') await _doGeneratePolicyUsageClean();
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

  const src        = get('rpt-src');
  const dst        = get('rpt-dst');
  const port       = get('rpt-port');
  const proto      = get('rpt-proto');
  const exSrc      = get('rpt-ex-src');
  const exDst      = get('rpt-ex-dst');
  const exPort     = get('rpt-ex-port');
  const anyLabel   = get('rpt-any-label');
  const anyIp      = get('rpt-any-ip');
  const exAnyLabel = get('rpt-ex-any-label');
  const exAnyIp    = get('rpt-ex-any-ip');

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

  const hasFilter = pds || src || dst || port || proto || exSrc || exDst || exPort || anyLabel || anyIp || exAnyLabel || exAnyIp;
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
    any_label:     anyLabel || null,
    any_ip:        anyIp || null,
    ex_any_label:  exAnyLabel || null,
    ex_any_ip:     exAnyIp || null,
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

  const src        = get('sched-src');
  const dst        = get('sched-dst');
  const port       = get('sched-port');
  const proto      = get('sched-proto');
  const exSrc      = get('sched-ex-src');
  const exDst      = get('sched-ex-dst');
  const exPort     = get('sched-ex-port');
  const anyLabel   = get('sched-any-label');
  const anyIp      = get('sched-any-ip');
  const exAnyLabel = get('sched-ex-any-label');
  const exAnyIp    = get('sched-ex-any-ip');

  const parseSrcDst = val => {
    if (!val) return { labels: [], ip: '' };
    if (/[\d.\/:]/.test(val)) return { labels: [], ip: val };
    return { labels: [val], ip: '' };
  };

  const srcP   = parseSrcDst(src);
  const dstP   = parseSrcDst(dst);
  const exSrcP = parseSrcDst(exSrc);
  const exDstP = parseSrcDst(exDst);

  const hasFilter = pds || src || dst || port || proto || exSrc || exDst || exPort || anyLabel || anyIp || exAnyLabel || exAnyIp;
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
    any_label:     anyLabel || null,
    any_ip:        anyIp || null,
    ex_any_label:  exAnyLabel || null,
    ex_any_ip:     exAnyIp || null,
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
  setVal('sched-ex-port',     filters.ex_port || '');
  setVal('sched-any-label',   filters.any_label || '');
  setVal('sched-any-ip',      filters.any_ip || '');
  setVal('sched-ex-any-label', filters.ex_any_label || '');
  setVal('sched-ex-any-ip',   filters.ex_any_ip || '');
}

async function _doGenerateTraffic() {
  const src = document.querySelector('input[name="traffic-source"]:checked')?.value || 'api';
  try {
    if (src === 'csv') {
      const fileInput = $('m-gen-csv-file');
      if (!fileInput.files || fileInput.files.length === 0) {
        const msg = _t('gui_csv_required');
        _hideGenProgress(false, msg);
        toast(_t('gui_err_no_csv'), 'err');
        return;
      }
      _updateGenStep(_t('gui_gen_step_parsing'));
      const formData = new FormData();
      formData.append('source', 'csv');
      const fmtEl = document.getElementById('m-gen-format');
      formData.append('format', fmtEl ? fmtEl.value : 'all');
      const profileElCsv = document.getElementById('m-gen-profile');
      formData.append('traffic_report_profile', profileElCsv ? profileElCsv.value : 'security_risk');
      const langElCsv = document.getElementById('m-gen-lang');
      formData.append('lang', langElCsv ? langElCsv.value : 'en');
      formData.append('file', fileInput.files[0]);

      _updateGenStep(_t('gui_gen_step_analysing'));
      const r = await fetch('/api/reports/generate', {
        method: 'POST',
        headers: { 'X-CSRF-Token': _csrfToken() },
        body: formData
      }).then(res => res.json());

      if (r.ok) {
        const msg = `${r.record_count} flows`;
        _hideGenProgress(true, msg);
        toast((_t('gui_toast_traffic_done')).replace('{msg}', msg));
        loadReports();
      } else {
        const fail = _t('gui_toast_traffic_fail');
        _hideGenProgress(false, r.error || fail);
        toast(r.error || fail, 'err');
      }
    } else {
      const startVal = $('m-gen-start').value, endVal = $('m-gen-end').value;
      if (!startVal || !endVal || startVal > endVal) {
        const msg = _t('gui_invalid_date_range');
        _hideGenProgress(false, msg);
        toast(msg, 'err');
        return;
      }
      const startDate = new Date(startVal + 'T00:00:00Z').toISOString();
      const endDate   = new Date(endVal   + 'T23:59:59Z').toISOString();

      _updateGenStep(_t('gui_gen_step_fetching'));
      // Simulate step progression for long-running API calls
      const _stepTimer = setTimeout(() => _updateGenStep(_t('gui_gen_step_analysing')), 5000);

      const reportFilters = _collectReportFilters();
      const fmtEl2 = document.getElementById('m-gen-format');
      const profileEl = document.getElementById('m-gen-profile');
      const langEl = document.getElementById('m-gen-lang');
      const clipEl = document.getElementById('m-gen-clip-to-cache');
      const clipToCache = !!(clipEl && clipEl.checked);
      const r = await post('/api/reports/generate', {
        source: 'api', format: fmtEl2 ? fmtEl2.value : 'all',
        start_date: startDate, end_date: endDate,
        traffic_report_profile: profileEl ? profileEl.value : 'security_risk',
        lang: langEl ? langEl.value : 'en',
        clip_to_cache: clipToCache,
        ...(reportFilters ? { filters: reportFilters } : {}),
      });
      clearTimeout(_stepTimer);
      if (r.ok) {
        const msg = `${r.record_count} flows`;
        _hideGenProgress(true, msg);
        toast((_t('gui_toast_traffic_done')).replace('{msg}', msg));
        loadReports();
      } else {
        const fail = _t('gui_toast_traffic_fail');
        _hideGenProgress(false, r.error || fail);
        toast(r.error || fail, 'err');
      }
    }
  } catch(e) {
    _hideGenProgress(false, e.message);
    toast((_t('gui_toast_traffic_error')).replace('{error}', e.message), 'err');
  }
}

async function _doGenerateAudit() {
  const startVal = $('m-gen-start').value, endVal = $('m-gen-end').value;
  if (!startVal || !endVal || startVal > endVal) {
    const msg = _t('gui_invalid_date_range');
    _hideGenProgress(false, msg);
    toast(msg, 'err');
    return;
  }
  const startDate = new Date(startVal + 'T00:00:00Z').toISOString();
  const endDate   = new Date(endVal   + 'T23:59:59Z').toISOString();
  const fmtEl = document.getElementById('m-gen-format');
  const fmt = fmtEl ? fmtEl.value : 'html';
  const langElAudit = document.getElementById('m-gen-lang');
  _updateGenStep(_t('gui_gen_step_fetching'));
  try {
    const _stepTimer = setTimeout(() => _updateGenStep(_t('gui_gen_step_analysing')), 3000);
    const r = await post('/api/audit_report/generate', {start_date:startDate, end_date:endDate, format:fmt, lang: langElAudit ? langElAudit.value : 'en'});
    clearTimeout(_stepTimer);
    if (r.ok) {
      const msg = `${r.record_count} events`;
      _hideGenProgress(true, msg);
      toast((_t('gui_toast_audit_done')).replace('{msg}', msg));
      loadReports();
    } else {
      const fail = _t('gui_toast_audit_fail');
      _hideGenProgress(false, r.error || fail);
      toast(r.error || fail, 'err');
    }
  } catch(e) {
    _hideGenProgress(false, e.message);
    toast((_t('gui_toast_audit_error')).replace('{error}', e.message), 'err');
  }
}

async function _doGenerateVen() {
  const fmtEl = document.getElementById('m-gen-format');
  const fmt = fmtEl ? fmtEl.value : 'html';
  const langElVen = document.getElementById('m-gen-lang');
  _updateGenStep(_t('gui_gen_step_fetching'));
  try {
    const r = await post('/api/ven_status_report/generate', {format:fmt, lang: langElVen ? langElVen.value : 'en'});
    if (r.ok) {
      const kpiText = (r.kpis || []).map(k => `${k.label}: ${k.value}`).join(' | ');
      _hideGenProgress(true, kpiText || (_t('gui_gen_done')));
      const doneMsg = kpiText
        ? (_t('gui_toast_ven_done_kpi')).replace('{kpi}', kpiText)
        : (_t('gui_toast_ven_done'));
      toast(doneMsg);
      loadReports();
    } else {
      const fail = _t('gui_toast_ven_fail');
      _hideGenProgress(false, r.error || fail);
      toast(r.error || fail, 'err');
    }
  } catch(e) {
    _hideGenProgress(false, e.message);
    toast((_t('gui_toast_ven_error')).replace('{error}', e.message), 'err');
  }
}

async function _doGeneratePolicyUsage() {
  _updateGenStep(_t('gui_gen_step_fetching'));
  try {
    const start = $('m-gen-start') ? $('m-gen-start').value : null;
    const end   = $('m-gen-end')   ? $('m-gen-end').value   : null;
    const langElPu = document.getElementById('m-gen-lang');
    const r = await post('/api/policy_usage_report/generate', { start_date: start, end_date: end, lang: langElPu ? langElPu.value : 'en' });
    if (r.ok) {
      const kpiText = (r.kpis || []).map(k => `${k.label}: ${k.value}`).join(' | ');
      _hideGenProgress(true, kpiText || (_t('gui_gen_done')));
      toast((_t('gui_toast_pu_done')).replace('{count}', r.record_count));
      loadReports();
    } else {
      const fail = _t('gui_toast_pu_fail');
      _hideGenProgress(false, r.error || fail);
      toast(r.error || fail, 'err');
    }
  } catch(e) {
    _hideGenProgress(false, e.message);
    toast((_t('gui_toast_pu_error')).replace('{error}', e.message), 'err');
  }
}

async function _doGeneratePolicyUsageClean() {
  const fmtEl = document.getElementById('m-gen-format');
  const fmt = fmtEl ? fmtEl.value : 'html';
  _updateGenStep(_t('gui_gen_step_fetching'));
  try {
    const start = $('m-gen-start') ? $('m-gen-start').value : null;
    const end   = $('m-gen-end')   ? $('m-gen-end').value   : null;
    const langElPuClean = document.getElementById('m-gen-lang');
    const r = await post('/api/policy_usage_report/generate', { start_date: start, end_date: end, format: fmt, lang: langElPuClean ? langElPuClean.value : 'en' });
    if (r.ok) {
      const kpiText = (r.kpis || []).map(k => `${k.label}: ${k.value}`).join(' | ');
      const execText = _formatPolicyUsageExecutionSummary(r.execution_stats, r.execution_notes);
      const detailText = _formatPolicyUsageDetailPreview({
        reused_rule_details: r.reused_rule_details || [],
        pending_rule_details: r.pending_rule_details || [],
        failed_rule_details: r.failed_rule_details || [],
      }, 3);
      const summaryText = [kpiText, execText, detailText].filter(Boolean).join(' | ');
      _hideGenProgress(true, summaryText || (_t('gui_gen_done')));
      const doneMsg = summaryText
        ? (_t('gui_toast_pu_done_detail'))
            .replace('{count}', r.record_count)
            .replace('{detail}', summaryText)
        : (_t('gui_toast_pu_done'))
            .replace('{count}', r.record_count);
      toast(doneMsg);
      loadReports();
    } else {
      const fail = _t('gui_toast_pu_fail');
      _hideGenProgress(false, r.error || fail);
      toast(r.error || fail, 'err');
    }
  } catch (e) {
    _hideGenProgress(false, e.message);
    toast((_t('gui_toast_pu_error')).replace('{error}', e.message), 'err');
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
      const pceStats = d.pce_stats || {};
      const dispatchHistory = Array.isArray(d.dispatch_history) ? d.dispatch_history : [];
      const latestDispatch = dispatchHistory.length ? dispatchHistory[dispatchHistory.length - 1] : null;
      const unknownTotal = Object.values(d.unknown_events || {}).reduce((total, entry) => {
        if (entry && typeof entry === 'object') return total + (parseInt(entry.count, 10) || 0);
        return total + (parseInt(entry, 10) || 0);
      }, 0);
      const suppressedTotal = Object.values(d.throttle_state || {}).reduce((total, entry) => {
        const cooldown = parseInt(entry.cooldown_suppressed, 10) || 0;
        const throttle = parseInt(entry.throttle_suppressed, 10) || 0;
        return total + cooldown + throttle;
      }, 0);
      const setCard = (id, value, tone = '') => {
        const el = $(id);
        if (!el) return;
        el.textContent = value;
        el.className = tone ? `value ${tone}` : 'value';
      };
      const eventPollStatus = String(pceStats.event_poll_status || 'unknown').toUpperCase();
      const dispatchStatus = latestDispatch
        ? `${String(latestDispatch.channel || 'dispatch').toUpperCase()} ${String(latestDispatch.status || 'unknown').toUpperCase()}`
        : _t('gui_state_none');
      setCard('d-rules', String(d.rules_count ?? 0));
      setCard('d-health', d.health_check ? _t('gui_state_on') : _t('gui_state_off'), d.health_check ? 'ok' : 'warn');
      setCard('d-event-poll', eventPollStatus, (pceStats.event_poll_status || '').toLowerCase() === 'ok' ? 'ok' : '');
      setCard('d-dispatch', dispatchStatus, latestDispatch && latestDispatch.status === 'success' ? 'ok' : '');
      setCard('d-unknown', String(unknownTotal), unknownTotal > 0 ? 'warn' : 'ok');
      setCard('d-suppressed', String(suppressedTotal), suppressedTotal > 0 ? 'warn' : 'ok');
      if (d.timezone) _timezone = d.timezone;
      applyThemeMode(getStoredThemeMode());

      if (d.cooldowns && d.cooldowns.length > 0) {
        const activeCds = d.cooldowns.filter(c => c.remaining_mins > 0).length;
        if (activeCds > 0) {
          const title = _t('gui_cooldown_title');
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

  await loadDashboardQueries();
  await loadDashboardSnapshot();
  await loadDashboardPolicyUsageSummary();
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
      fb.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--dim);padding:12px;">${_t('gui_snap_no_findings')}</td></tr>`;
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
        `<tr><td>${escapeHtml(String(_pickValue(row, ['Port', 'port', 'port_proto'], '-')))}</td><td>${escapeHtml(String(_pickValue(row, ['Flow Count', 'flow_count', 'Count', 'count'], '')))}</td></tr>`
      ).join('');
    } else {
      portsB.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--dim);">—</td></tr>';
    }

    // Top Uncovered Flows
    const uncovB = $('snap-uncovered-body');
    const uncovered = s.top_uncovered || [];
    if (s.uncovered_pct != null) {
      $('snap-uncovered-pct').textContent = `(${_t('gui_snap_uncovered_pct').replace('{pct}', (+s.uncovered_pct).toFixed(1))})`;
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
      uncovB.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--dim);padding:12px;">${_t('gui_snap_no_uncovered')}</td></tr>`;
    }

    // Top Bandwidth / Bytes
    if (s.bw_data_available) {
      $('snap-bw-wrap').style.display = 'block';
      const bwB = $('snap-bw-body');
      const bwRows = s.top_by_bytes || [];
      if (bwRows.length) {
        bwB.innerHTML = bwRows.map(row => {
          const bytes = _pickValue(row, ['Bytes Total', 'bytes_total', 'Bytes', 'bytes'], 0);
          const bytesStr = formatBytes(bytes);
          const dec = _pickValue(row, ['Decision', 'policy_decision'], '');
          let dColor = dec === 'allowed' ? 'var(--success)' : dec === 'blocked' ? 'var(--danger)' : 'var(--warn)';
          return `<tr>
            <td>${escapeHtml(String(_pickValue(row, ['Src IP', 'Source IP', 'src_ip', 'source_ip'], '')))}</td>
            <td>${escapeHtml(String(_pickValue(row, ['Dst IP', 'Destination IP', 'dst_ip', 'destination_ip'], '')))}</td>
            <td>${escapeHtml(String(_pickValue(row, ['Port', 'port', 'port_proto'], '')))}</td>
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

async function loadDashboardPolicyUsageSummary() {
  try {
    const r = await api('/api/dashboard/policy_usage_summary');
    if (!r || !r.ok || !r.summary) return;
    const s = r.summary;

    const placeholder = $('policy-usage-placeholder');
    const content = $('policy-usage-content');
    if (placeholder) placeholder.style.display = 'none';
    if (content) content.style.display = 'block';

    if ($('policy-usage-generated-at')) $('policy-usage-generated-at').textContent = s.generated_at || '-';
    if ($('policy-usage-date-range')) $('policy-usage-date-range').textContent = (s.date_range || []).join(' ~ ') || '-';

    const stats = s.execution_stats || {};
    const cards = [
      [_t('gui_pu_stat_hit_rules'), stats.hit_rules || 0],
      [_t('gui_pu_stat_unused_rules'), stats.unused_rules || 0],
      [_t('gui_pu_stat_cached_reuse'), stats.cached_rules || 0],
      [_t('gui_pu_stat_new_queries'), stats.submitted_rules || 0],
      [_t('gui_pu_stat_pending_jobs'), stats.pending_jobs || 0],
      [_t('gui_pu_stat_failed_jobs'), stats.failed_jobs || 0],
    ];
    const grid = $('policy-usage-kpi-grid');
    if (grid) {
      grid.innerHTML = cards.map(([label, value]) =>
        `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px 14px;">
          <div style="font-size:0.72rem;color:var(--dim);text-transform:uppercase;letter-spacing:.04em;">${escapeHtml(String(label))}</div>
          <div style="font-size:1.1rem;font-weight:700;margin-top:4px;color:var(--fg);">${escapeHtml(String(value))}</div>
        </div>`
      ).join('');
    }

    const renderRows = (bodyId, rows) => {
      const body = $(bodyId);
      if (!body) return;
      if (!rows || !rows.length) {
        body.innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--dim);padding:12px;">${_t('gui_no_data')}</td></tr>`;
        return;
      }
      body.innerHTML = rows.map(row => {
        const rule = _formatPolicyUsageRuleLabel(row);
        const ruleset = row.ruleset_name || '—';
        return `<tr><td>${escapeHtml(String(rule))}</td><td>${escapeHtml(String(ruleset))}</td></tr>`;
      }).join('');
    };

    const topPortsBody = $('policy-usage-top-ports-body');
    if (topPortsBody) {
      const topPorts = s.top_hit_ports || [];
      if (!topPorts.length) {
        topPortsBody.innerHTML = `<tr><td colspan="2" style="text-align:center;color:var(--dim);padding:12px;">${_t('gui_no_data')}</td></tr>`;
      } else {
        topPortsBody.innerHTML = topPorts.map(item => {
          const label = _pickValue(item, ['port_proto', 'Port / Proto', 'port', 'Port'], '-');
          const count = _pickValue(item, ['flow_count', 'Flow Count', 'count', 'Count'], 0);
          return `<tr><td>${escapeHtml(String(label))}</td><td>${escapeHtml(String(count))}</td></tr>`;
        }).join('');
      }
    }

    renderRows('policy-usage-pending-body', s.pending_rule_details || []);
    renderRows('policy-usage-failed-body', s.failed_rule_details || []);
    renderRows('policy-usage-reused-body', s.reused_rule_details || []);
  } catch (e) {
    console.warn('Policy Usage Summary Error:', e);
  }
}

async function testConn() {
  slog(_t('gui_test_conn_running'));
  const r = await post('/api/actions/test-connection', {});
  if (r.ok) {
    const okText = _t('status_ok');
    $('d-api').textContent = okText;
    $('d-api').className = 'value ok';
    slog(okText + ' (HTTP ' + r.status + ')');
  } else {
    $('d-api').textContent = _t('status_error');
    $('d-api').className = 'value err';
    slog(r.error || r.body);
  }
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
    html = `<div style="text-align:center;padding:20px;color:var(--dim);font-size:0.9rem;">${_t('gui_top10_empty')}</div>`;
  } else {
    _dashboardQueries.forEach((q, i) => {
      let badgeColor = "var(--primary)";
      if (q.pd === 2) badgeColor = "var(--danger)";
      else if (q.pd === 1) badgeColor = "var(--warn)";
      else if (q.pd === 0) badgeColor = "var(--success)";

      let rankLabel = q.rank_by === 'bandwidth' ? (_t('gui_rank_bw')) : (q.rank_by === 'volume' ? (_t('gui_rank_vol')) : (_t('gui_rank_conn')));
      html += `
      <div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;">
         <div style="display:flex;align-items:center;min-height:30px;">
            <strong style="margin-right:12px;font-size:0.95rem;color:var(--accent2);">${escapeHtml(q.name)}</strong>
            <span style="font-size:10px;background:${badgeColor};color:#fff;padding:2px 6px;border-radius:4px;margin-right:8px;">${_t('gui_pd_short')}: ${q.pd === 3 ? (_t('gui_pd_all')) : (q.pd === 2 ? (_t('gui_pd_blocked')) : (q.pd === 1 ? (_t('gui_pd_potential')) : (_t('gui_pd_allowed'))))}</span>
            <span style="font-size:10px;background:var(--dim);color:#fff;padding:2px 6px;border-radius:4px;margin-right:8px;">${rankLabel}</span>
            <span style="flex:1"></span>
            <span id="d-qstate-${i}" style="color:var(--dim);font-size:0.8rem;margin-right:12px;"></span>
            <button class="btn btn-sm" style="background:var(--bg);border:1px solid var(--border);margin-right:6px;" onclick="openQueryModal(${i})" aria-label="${_t('gui_edit_query_widget')}" title="${_t('gui_edit_query_widget')}">✏️</button>
            <button class="btn btn-primary btn-sm" onclick="runTop10Query(${i})">${_t('gui_run_btn')}</button>
         </div>
         
          <table class="rule-table" style="margin-top:10px;border-top:1px solid var(--border);font-size:0.8rem;">
           <thead><tr>
             <th style="width:25px">#</th>
             <th style="width:100px">${_t('gui_value')}</th>
             <th style="width:110px">${_t('gui_first_last_seen')}</th>
             <th>${_t('gui_source_identity')}</th>
             <th>${_t('gui_destination_identity')}</th>
             <th style="width:70px">${_t('gui_service_port')}</th>
             <th style="width:70px">${_t('gui_policy_dec')}</th>
             <th style="width:140px">${_t('gui_actions')}</th>
           </tr></thead>
           <tbody id="d-qbody-${i}">
            <tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_t('gui_top10_empty')}</td></tr>
          </tbody>
         </table>
      </div>`;
    });
  }
  container.innerHTML = html;
  initTableResizers();

  if (typeof applyLang === "function") applyLang();
}

// Quick-window preset for Ranking Summary (top10) — sets d-global-min and
// re-runs the query so the user sees the new range immediately.
function setTop10Window(mins) {
  const el = document.getElementById('d-global-min');
  if (el) el.value = String(mins);
  if (typeof runAllQueries === 'function') runAllQueries();
}
window.setTop10Window = setTop10Window;

function openQueryModal(idx = -1) {
  $('dq-idx').value = idx;
  if (idx < 0) {
    $('mq-title').textContent = _t('gui_add_query_widget');
    $('dq-name').value = '';
    $('dq-rank').value = 'count';
    document.querySelector('input[name="dq-pd"][value="3"]').checked = true;
    $('dq-port').value = ''; $('dq-proto').value = '';
    $('dq-src').value = ''; $('dq-dst').value = '';
    $('dq-expt').value = ''; $('dq-exsrc').value = ''; $('dq-exdst').value = '';
    $('dq-any-label').value = ''; $('dq-any-ip').value = '';
    $('dq-ex-any-label').value = ''; $('dq-ex-any-ip').value = '';
  } else {
    $('mq-title').textContent = _t('gui_edit_query_widget');
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
    delBtn.innerText = _t('gui_delete');
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
  else alert((_t('error_generic')).replace('{error}', r.error));
}

async function deleteTop10Query(idx) {
  if (!confirm(_t('gui_confirm_delete_widget'))) return;
  const r = await fetch('/api/dashboard/queries/' + idx, { method: 'DELETE', headers: { 'X-CSRF-Token': _csrfToken() } }).then(res => res.json());
  if (r.ok) {
    _clearAllTop10Cache();
    const m = $('m-query');
    if (m) m.classList.remove('show');
    await loadDashboardQueries();
  }
  else alert(_t('error_deleting'));
}

/* ── Top 10 cache helpers ── */
function _top10CacheKey(idx) { return 'top10_cache_' + idx; }

function _saveTop10Cache(idx, data, total, source) {
  try {
    localStorage.setItem(_top10CacheKey(idx), JSON.stringify({ data, total, ts: Date.now(), source: source || 'api' }));
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
      _renderTop10Body(idx, c.data, c.total, c.ts, c.source || 'api');
    } else {
      const ms = $(`d-qstate-${idx}`);
      if (ms) _setStatusWithSourceBadge(ms,
        (_t('gui_top10_no_records')) + '  (' + _fmtCacheTs(c.ts) + ')',
        c.source || 'api');
    }
  } catch (_) { /* corrupt cache — ignore */ }
}

// Render a small chip indicating where the data came from. Built via DOM
// methods (createElement + textContent) to avoid innerHTML XSS surface.
function _setStatusWithSourceBadge(el, statusText, source) {
  el.textContent = '';
  const s = (source || 'api').toLowerCase();
  const colorMap = { cache: '#22C55E', mixed: '#EAB308', api: '#60A5FA' };
  const titleMap = {
    cache: _t('gui_source_badge_cache'),
    mixed: _t('gui_source_badge_mixed'),
    api: _t('gui_source_badge_api'),
  };
  const badge = document.createElement('span');
  badge.textContent = s;
  badge.title = titleMap[s] || titleMap.api;
  badge.style.cssText = 'display:inline-block;background:' + (colorMap[s] || colorMap.api) +
    ';color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;' +
    'letter-spacing:0.3px;text-transform:uppercase;vertical-align:middle;margin-right:6px;';
  el.appendChild(badge);
  el.appendChild(document.createTextNode(statusText));
}

function _fmtCacheTs(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleString();
}

function _renderTop10Body(idx, data, total, ts, source) {
  const ms = $(`d-qstate-${idx}`), bd = $(`d-qbody-${idx}`);
  if (!ms || !bd) return;

  let html = '';
  data.forEach((m, i) => {
    const pd_blocked = _t('gui_pd_blocked');
    const pd_potential = _t('gui_pd_potential');
    const pd_allowed = _t('gui_pd_allowed');
    const draftPrefix = _t('gui_draft');
    const pBadge = m.pd === 2 ? `<span style="background:var(--danger);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${pd_blocked}</span>` :
      m.pd === 1 ? `<span style="background:var(--warn);color:#000;padding:2px 6px;border-radius:4px;font-size:10px;">${pd_potential}</span>` :
        m.pd === 0 ? `<span style="background:var(--success);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${pd_allowed}</span>` : m.pd;
    const draftPdMap = {
      allowed: _t('gui_pd_allowed'),
      potentially_blocked: _t('gui_pd_potential'),
      blocked_by_boundary: _t('pd_blocked_by_boundary'),
      blocked_by_override_deny: _t('pd_blocked_by_override_deny'),
      potentially_blocked_by_boundary: _t('pd_potentially_blocked_by_boundary'),
      potentially_blocked_by_override_deny: _t('pd_potentially_blocked_by_override_deny'),
      allowed_across_boundary: _t('pd_allowed_across_boundary'),
    };
    const draftPdColor = {
      allowed: 'var(--success)', allowed_across_boundary: 'var(--success)',
      potentially_blocked: 'var(--warn)', potentially_blocked_by_boundary: 'var(--warn)', potentially_blocked_by_override_deny: 'var(--warn)',
      blocked_by_boundary: 'var(--danger)', blocked_by_override_deny: 'var(--danger)',
    };
    const draftPdTextColor = {
      potentially_blocked: '#000', potentially_blocked_by_boundary: '#000', potentially_blocked_by_override_deny: '#000',
    };
    const draftBadge = m.draft_pd && draftPdMap[m.draft_pd] ? `<div style="margin-top:3px;"><span style="background:${draftPdColor[m.draft_pd] || 'var(--secondary)'};color:${draftPdTextColor[m.draft_pd] || '#fff'};padding:2px 6px;border-radius:4px;font-size:10px;opacity:0.8;">${draftPrefix} ${draftPdMap[m.draft_pd]}</span></div>` : '';

    const sLabels = renderLabelsHtml(m.s_labels);
    const dLabels = renderLabelsHtml(m.d_labels);

    let isoBtn = '';
    if (m.s_href && m.d_href) {
      isoBtn = `<button class="btn btn-danger btn-sm" onclick="openQuarantineModal('${escapeHtml(m.s_href)}', false, '${escapeHtml(m.d_href)}')"><span data-i18n="gui_btn_isolate">${_t('gui_btn_isolate')}</span></button>`;
    } else if (m.s_href || m.d_href) {
      isoBtn = `<button class="btn btn-danger btn-sm" onclick="openQuarantineModal('${escapeHtml(m.s_href || m.d_href)}')"><span data-i18n="gui_btn_isolate">${_t('gui_btn_isolate')}</span></button>`;
    }

    const formatActor = (name, ip, href, labelsHtml, process, user) => {
      let procStr = '';
      if (process || user) {
        let p = process ? `<span style="color:var(--accent); font-weight:bold;"><i class="fas fa-microchip"></i> ${escapeHtml(process)}</span>` : '';
        let u = user ? `<span style="color:var(--accent2);"><i class="fas fa-user"></i> ${escapeHtml(user)}</span>` : '';
        procStr = `<div style="font-size:10px; margin-top:4px;">${p}${p && u ? '<br>' : ''}${u}</div>`;
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
    // Fallback: if flow_direction unknown, surface process/user in service cell
    if (m.svc_process || m.svc_user) {
      let p = m.svc_process ? `<span style="color:var(--accent); font-weight:bold;"><i class="fas fa-microchip"></i> ${escapeHtml(m.svc_process)}</span>` : '';
      let u = m.svc_user ? `<span style="color:var(--accent2);"><i class="fas fa-user"></i> ${escapeHtml(m.svc_user)}</span>` : '';
      svc_str += `<div style="font-size:10px; margin-top:3px;">${p}${p && u ? '<br>' : ''}${u}</div>`;
    }

    html += `
      <tr>
        <td>${i + 1}</td>
        <td style="font-weight:bold;color:#6f42c1;">${m.val_fmt}</td>
        <td style="font-size:10px;white-space:nowrap;">${formatDateZ(m.first_seen)}<br>${formatDateZ(m.last_seen)}</td>
        <td>${formatActor(m.s_name, m.s_ip, m.s_href, sLabels, m.s_process, m.s_user)}</td>
        <td>${formatActor(m.d_name, m.d_ip, m.d_href, dLabels, m.d_process, m.d_user)}</td>
        <td>${svc_str}</td>
        <td>${pBadge}${draftBadge}</td>
        <td>${isoBtn}</td>
      </tr>`;
  });
  bd.innerHTML = html;
  let status = (_t('gui_top10_found')).replace('{count}', total);
  if (ts) status += '  (' + _fmtCacheTs(ts) + ')';
  _setStatusWithSourceBadge(ms, status, source || 'api');
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

  ms.textContent = _t('gui_top10_querying');
  bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_t('gui_top10_loading')}</td></tr>`;

  try {
    const r = await post('/api/dashboard/top10', payload);
    if (!r.ok) throw new Error(r.error || _t('gui_ev_unknown_error'));

    if (r.data && r.data.length) {
      _saveTop10Cache(idx, r.data, r.total, r.source);
      _renderTop10Body(idx, r.data, r.total, Date.now(), r.source);
    } else {
      _saveTop10Cache(idx, [], 0, r.source);
      bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_t('gui_top10_no_records')}</td></tr>`;
      _setStatusWithSourceBadge(ms, (_t('gui_done')) + '  (' + _fmtCacheTs(Date.now()) + ')', r.source);
    }
  } catch (e) {
    ms.textContent = (_t('error_generic')).replace('{error}', e.message);
    bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:20px;">${_t('gui_top10_error')}</td></tr>`;
  }
}

// ---------------------------------------------------------------------------
// Live Plotly dashboard charts (Phase 11)
// ---------------------------------------------------------------------------
async function loadDashboardCharts() {
  const charts = ["traffic_timeline", "policy_decisions", "ven_status", "rule_hits"];
  for (const id of charts) {
    try {
      const resp = await fetch(`/api/dashboard/chart/${id}`,
                               { headers: { "X-CSRFToken": _csrfToken() } });
      if (!resp.ok) continue;
      const fig = await resp.json();
      const el = document.getElementById(`chart-${id.replace(/_/g, '-')}`);
      if (el && typeof Plotly !== 'undefined') {
        Plotly.react(el, fig.data, fig.layout, { responsive: true });
      }
    } catch (_) {}
  }
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    loadDashboardCharts();
    setInterval(loadDashboardCharts, 60000);
  });
} else {
  loadDashboardCharts();
  setInterval(loadDashboardCharts, 60000);
}
