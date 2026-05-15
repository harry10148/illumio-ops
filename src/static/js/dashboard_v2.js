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
      <div id="audit-kpi-grid" class="kpi-grid"></div>
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

  // Phase 3.1 story-card redesign moved all card labels + IDs into index.html
  // as authoritative server-rendered markup. Do NOT mutate `.cards .card`
  // label/id pairs at runtime — that was the legacy v1 behaviour and broke
  // story-cards by re-assigning `d-cooldown` / `d-pce-health` to the wrong
  // stats. The remaining responsibility here is just injecting the audit
  // summary fieldset (a sibling container that's not in the template).

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

  dashboard.dataset.layoutReady = '1';
}

async function loadDashboard() {
  await loadTranslations();
  ensureTrafficWorkloadLayout();
  ensureDashboardLayout();

  try {
    const d = await api('/api/status');
    if (d) {
      window._uiLang = (d.language === 'zh_TW') ? 'zh_TW' : 'en';
      const hostEl = $('hdr-chip-host');
      if (hostEl && d.api_url) hostEl.textContent = d.api_url;
      const chip = $('hdr-chip');
      if (chip) chip.title = `PCE: ${d.api_url || hostEl?.textContent}  |  v${d.version}`;
      const dot = $('hdr-chip-dot');
      if (dot) {
        const polled = String((d.pce_stats || {}).event_poll_status || 'unknown').toLowerCase();
        let status = 'unknown';
        if (polled === 'ok') status = 'ok';
        else if (polled === 'warn' || polled === 'degraded') status = 'warn';
        else if (polled && polled !== 'unknown') status = 'err';
        dot.setAttribute('data-status', status);
      }
      const pceStats = d.pce_stats || {};
      if (d.timezone) _timezone = d.timezone;
      applyThemeMode(getStoredThemeMode());

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

      const eventPollStatus = String(pceStats.event_poll_status || 'unknown').toUpperCase();
      const dispatchStatus = latestDispatch
        ? `${String(latestDispatch.channel || 'dispatch').toUpperCase()} ${String(latestDispatch.status || 'unknown').toUpperCase()}`
        : _t('gui_state_none');

      // Phase 3.1 story-card stats — populate the 6 sub-KPI rows.
      _dashboardSetCard('d-rules', String(d.rules_count ?? 0));
      _dashboardSetCard('d-health', d.health_check ? _t('gui_state_on') : _t('gui_state_off'),
                        d.health_check ? 'ok' : 'warn');
      _dashboardSetCard('d-event-poll', eventPollStatus,
                        (pceStats.event_poll_status || '').toLowerCase() === 'ok' ? 'ok' : '');
      _dashboardSetCard('d-dispatch', dispatchStatus,
                        latestDispatch && latestDispatch.status === 'success' ? 'ok' : '');
      _dashboardSetCard('d-unknown', String(unknownTotal), unknownTotal > 0 ? 'warn' : 'ok');
      _dashboardSetCard('d-suppressed', String(suppressedTotal), suppressedTotal > 0 ? 'warn' : 'ok');
    }
  } catch (e) {
    console.warn('[loadDashboard] status failed:', e);
  }

  await loadDashboardSnapshot();
  await loadDashboardAuditSummary();
}

async function loadDashboardSnapshot() {
  const placeholder = $('snap-placeholder');
  const content = $('snap-content');
  if (placeholder) placeholder.style.display = 'block';
  if (content) content.style.display = 'none';

  try {
    const r = await api('/api/dashboard/snapshot');
    if (!r || !r.ok || !r.snapshot) return;
    const s = r.snapshot;
    if (!s.generated_at || !placeholder || !content) return;

    placeholder.style.display = 'none';
    content.style.display = 'block';
    $('snap-generated-at').textContent = s.generated_at;
    $('snap-date-range').textContent = s.date_range || '-';

    const kpiGrid = $('snap-kpi-grid');
    if (kpiGrid) {
      kpiGrid.textContent = '';
      (s.kpis || []).forEach((k) => {
        const card = document.createElement('div');
        card.className = 'kpi-card';
        const labelEl = document.createElement('div');
        labelEl.className = 'kpi-label';
        labelEl.textContent = k.label;
        const valueEl = document.createElement('div');
        valueEl.className = 'kpi-value';
        valueEl.textContent = k.value;
        card.appendChild(labelEl);
        card.appendChild(valueEl);
        kpiGrid.appendChild(card);
      });
    }

    const findings = $('snap-findings-body');
    if (findings) {
      const rows = s.key_findings || [];
      findings.innerHTML = rows.length
        ? rows.map((f) => {
          const sev = String(f.severity || '');
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
        }).join('')
        : `<tr><td colspan="3" style="text-align:center;color:var(--dim);padding:12px;">${_t('gui_snap_no_findings')}</td></tr>`;
    }

    const policyBody = $('snap-policy-body');
    if (policyBody) {
      const rows = s.policy_summary || [];
      policyBody.innerHTML = rows.length
        ? rows.map((row) => {
          const dec = String(row['Decision'] || '');
          let color = 'var(--fg)';
          if (dec === 'allowed') color = 'var(--success)';
          else if (dec === 'blocked') color = 'var(--danger)';
          else if (dec === 'potentially_blocked') color = 'var(--warn)';
          return `<tr><td style="color:${color};font-weight:600;">${escapeHtml(dec)}</td><td>${escapeHtml(String(row['Flows'] ?? ''))}</td></tr>`;
        }).join('')
        : '<tr><td colspan="2" style="text-align:center;color:var(--dim);">-</td></tr>';
    }

    const portsBody = $('snap-ports-body');
    if (portsBody) {
      const rows = s.top_ports || [];
      portsBody.innerHTML = rows.length
        ? rows.map((row) =>
          `<tr><td>${escapeHtml(String(_pickValue(row, ['Port', 'port', 'port_proto'], '-')))}</td><td>${escapeHtml(String(_pickValue(row, ['Flow Count', 'flow_count', 'Count', 'count'], '')))}</td></tr>`
        ).join('')
        : '<tr><td colspan="2" style="text-align:center;color:var(--dim);">-</td></tr>';
    }

    const uncoveredBody = $('snap-uncovered-body');
    const uncoveredPct = $('snap-uncovered-pct');
    if (uncoveredPct && s.uncovered_pct != null) uncoveredPct.textContent = `(${_t('gui_snap_uncovered_pct').replace('{pct}', (+s.uncovered_pct).toFixed(1))})`;
    if (uncoveredBody) {
      const rows = s.top_uncovered || [];
      uncoveredBody.innerHTML = rows.length
        ? rows.map((row) => {
          const dec = String(row['Decision'] || '');
          const color = dec === 'blocked' ? 'var(--danger)' : 'var(--warn)';
          return `<tr>
            <td style="font-size:0.78rem;">${escapeHtml(row['Flow'] || '')}</td>
            <td><span style="color:${color};font-weight:600;">${escapeHtml(dec)}</span></td>
            <td>${escapeHtml(String(row['Connections'] ?? ''))}</td>
            <td style="color:var(--dim);font-size:0.78rem;">${escapeHtml(row['recommendation'] || row['Recommendation'] || '')}</td>
          </tr>`;
        }).join('')
        : `<tr><td colspan="4" style="text-align:center;color:var(--dim);padding:12px;">${_t('gui_snap_no_uncovered')}</td></tr>`;
    }

    const bwWrap = $('snap-bw-wrap');
    const bwBody = $('snap-bw-body');
    if (bwWrap) bwWrap.style.display = s.bw_data_available ? 'block' : 'none';
    if (bwBody && s.bw_data_available) {
      const rows = s.top_by_bytes || [];
      bwBody.innerHTML = rows.length
        ? rows.map((row) => {
          const bytes = _pickValue(row, ['Bytes Total', 'bytes_total', 'Bytes', 'bytes'], 0);
          const dec = String(_pickValue(row, ['Decision', 'policy_decision'], ''));
          let color = dec === 'allowed' ? 'var(--success)' : dec === 'blocked' ? 'var(--danger)' : 'var(--warn)';
          return `<tr>
            <td>${escapeHtml(String(_pickValue(row, ['Src IP', 'Source IP', 'src_ip', 'source_ip'], '')))}</td>
            <td>${escapeHtml(String(_pickValue(row, ['Dst IP', 'Destination IP', 'dst_ip', 'destination_ip'], '')))}</td>
            <td>${escapeHtml(String(_pickValue(row, ['Port', 'port', 'port_proto'], '')))}</td>
            <td>${escapeHtml(formatBytes(bytes))}</td>
            <td><span style="color:${color};font-weight:600;">${escapeHtml(dec)}</span></td>
          </tr>`;
        }).join('')
        : '<tr><td colspan="5" style="text-align:center;color:var(--dim);padding:12px;">-</td></tr>';
    }
  } catch (e) {
    console.warn('[loadDashboardSnapshot] failed:', e);
  }
}

async function loadDashboardAuditSummary() {
  const placeholder = $('audit-placeholder');
  const content = $('audit-content');
  if (!placeholder || !content) return;
  placeholder.style.display = 'block';
  content.style.display = 'none';

  try {
    const r = await api('/api/dashboard/audit_summary');
    if (!r || !r.ok || !r.summary) return;
    const s = r.summary;
    placeholder.style.display = 'none';
    content.style.display = 'block';
    $('audit-generated-at').textContent = s.generated_at || '-';
    $('audit-date-range').textContent = (s.date_range || []).filter(Boolean).join(' ~ ') || '-';

    const kpiGrid = $('audit-kpi-grid');
    if (kpiGrid) {
      kpiGrid.textContent = '';
      (s.kpis || []).slice(0, 8).forEach((k) => {
        const card = document.createElement('div');
        card.className = 'kpi-card';
        const labelEl = document.createElement('div');
        labelEl.className = 'kpi-label';
        labelEl.textContent = k.label;
        const valueEl = document.createElement('div');
        valueEl.className = 'kpi-value';
        valueEl.textContent = k.value;
        card.appendChild(labelEl);
        card.appendChild(valueEl);
        kpiGrid.appendChild(card);
      });
    }

    const attentionBody = $('audit-attention-body');
    if (attentionBody) {
      const rows = s.attention_items || [];
      attentionBody.innerHTML = rows.length
        ? rows.map((item) => {
          const risk = String(item.risk || 'INFO');
          let color = 'var(--dim)';
          if (risk === 'CRITICAL') color = '#c0392b';
          else if (risk === 'HIGH') color = 'var(--danger)';
          else if (risk === 'MEDIUM') color = 'var(--warn)';
          else if (risk === 'INFO') color = 'var(--success)';
          return `<tr>
            <td><span style="background:${color};color:#fff;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:700;">${escapeHtml(risk)}</span></td>
            <td>${escapeHtml(item.event_type || '')}</td>
            <td>${escapeHtml(item.summary || '')}</td>
          </tr>`;
        }).join('')
        : `<tr><td colspan="3" style="text-align:center;color:var(--dim);padding:12px;">${_t('gui_no_data')}</td></tr>`;
    }

    const topEventsBody = $('audit-top-events-body');
    if (topEventsBody) {
      const rows = s.top_events || [];
      topEventsBody.innerHTML = rows.length
        ? rows.map((row) => `<tr><td>${escapeHtml(row['Event Type'] || '')}</td><td>${escapeHtml(String(row['Count'] ?? ''))}</td></tr>`).join('')
        : `<tr><td colspan="2" style="text-align:center;color:var(--dim);padding:12px;">${_t('gui_no_data')}</td></tr>`;
    }
  } catch (e) {
    console.warn('[loadDashboardAuditSummary] failed:', e);
  }
}
