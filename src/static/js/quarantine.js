/* ─── Traffic & Quarantine Logic ──────────────────────────────────── */

// Sub Navigation
function switchQTab(tabStr, updateUrl = true) {
  document.querySelectorAll('.sub-nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('qbtn-' + tabStr).classList.add('active');

  document.querySelectorAll('.q-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('q-panel-' + tabStr).classList.add('active');
  if (updateUrl) updateUrlState('qtab', tabStr);

  // R4k: load trend chart whenever the traffic analyzer sub-tab is shown
  if (tabStr === 'traffic') {
    try { loadTrafficTrend(); } catch (_) {}
  }
}

// Checkboxes and Bulk Bar
function toggleQChecks(clsPrefix) {
  const isAll = document.getElementById(clsPrefix + 'all').checked;
  document.querySelectorAll('.' + clsPrefix).forEach(c => c.checked = isAll);
  updateBulkBar();
}

// CSP-friendly wrappers for inline handlers that previously did
// `_qt_page=1; renderQtPage();` and the qw equivalent. Used via
// data-on-change="qtSearchModeChanged" / "qwSearchModeChanged".
function qtSearchModeChanged() { _qt_page = 1; renderQtPage(); }
function qwSearchModeChanged() { _qw_page = 1; renderQwPage(); }

function updateBulkBar() {
  // Check both traffic and workload tables for checks
  const checked = document.querySelectorAll('.qt-chk:checked, .qw-chk:checked');
  const bar = document.getElementById('bulk-bar');
  const activePanel = document.querySelector('.panel.active');
  const onTrafficWorkloadPage = activePanel && activePanel.id === 'p-traffic-workload';
  if (!onTrafficWorkloadPage) {
    bar.classList.remove('show');
    return;
  }
  if (checked.length > 0) {
    document.getElementById('bulk-sel-count').textContent = checked.length;
    bar.classList.add('show');
  } else {
    bar.classList.remove('show');
  }
}

function _qText(key) {
  return _t(key);
}

function _buildQuarantineState(href, isBulk = false, altHref = null) {
  const state = { pairs: [], standalone: [] };

  const addPair = (sourceHref, destinationHref) => {
    const source = String(sourceHref || '').trim();
    const destination = String(destinationHref || '').trim();
    if (!source && !destination) return;
    if (state.pairs.some((pair) => pair.source === source && pair.destination === destination)) return;
    state.pairs.push({ source, destination });
  };

  const addStandalone = (targetHref) => {
    const normalized = String(targetHref || '').trim();
    if (!normalized || state.standalone.includes(normalized)) return;
    state.standalone.push(normalized);
  };

  if (isBulk) {
    document.querySelectorAll('.qt-chk:checked').forEach((checkbox) => {
      addPair(checkbox.dataset.srcHref, checkbox.dataset.dstHref);
    });
    document.querySelectorAll('.qw-chk:checked').forEach((checkbox) => {
      addStandalone(checkbox.value || checkbox.dataset.href);
    });
  } else if (altHref && href && altHref !== href) {
    addPair(href, altHref);
  } else {
    addStandalone(href);
  }

  return state;
}

function _currentQuarantineDirection() {
  const selected = document.querySelector('input[name="q-dir"]:checked');
  return selected ? selected.value : 'source';
}

function _computeQuarantineTargets(state, direction) {
  const targets = [];
  const pushUnique = (href) => {
    const normalized = String(href || '').trim();
    if (normalized && !targets.includes(normalized)) targets.push(normalized);
  };

  (state.standalone || []).forEach(pushUnique);
  (state.pairs || []).forEach((pair) => {
    if (!pair.source || !pair.destination || pair.source === pair.destination) {
      pushUnique(pair.source || pair.destination);
      return;
    }
    if (direction === 'both') {
      pushUnique(pair.source);
      pushUnique(pair.destination);
      return;
    }
    if (direction === 'destination') {
      pushUnique(pair.destination);
      return;
    }
    pushUnique(pair.source);
  });

  return targets;
}

function refreshQuarantineTargets() {
  const modal = document.getElementById('m-quarantine');
  let state = { pairs: [], standalone: [] };
  try {
    state = JSON.parse(modal.dataset.qState || '{}');
  } catch (e) { }

  const targets = _computeQuarantineTargets(state, _currentQuarantineDirection());
  document.getElementById('q-target-count').textContent = targets.length;
  document.getElementById('q-target-hrefs').value = JSON.stringify(targets);
  document.getElementById('btn-apply-q').disabled = targets.length === 0;
}

// Add event listeners to table bodies for dynamic checkbox listening
document.addEventListener('change', function (e) {
  if (e.target && (e.target.classList.contains('qt-chk') || e.target.classList.contains('qw-chk'))) {
    updateBulkBar();
  }
});

function openQuarantineModal(href, isBulk = false, altHref = null) {
  const state = _buildQuarantineState(href, isBulk, altHref);
  if ((state.pairs || []).length === 0 && (state.standalone || []).length === 0) {
    toast(_qText('gui_q_no_targets'));
    return;
  }

  const hasDualPair = (state.pairs || []).some((pair) => pair.source && pair.destination && pair.source !== pair.destination);
  document.getElementById('q-direction-grp').style.display = hasDualPair ? 'block' : 'none';
  const defaultDirection = isBulk && hasDualPair ? 'both' : 'source';
  document.querySelectorAll('input[name="q-dir"]').forEach((radio) => {
    radio.checked = radio.value === defaultDirection;
  });

  const modal = document.getElementById('m-quarantine');
  modal.dataset.qState = JSON.stringify(state);
  refreshQuarantineTargets();
  document.getElementById('m-quarantine').classList.add('show');
}

async function applyQuarantine() {
  const sev = document.getElementById('q-severity').value;
  const rawHrefs = document.getElementById('q-target-hrefs').value;
  let hrefs = [];
  try { hrefs = JSON.parse(rawHrefs); } catch (e) { }
  if (hrefs.length === 0) {
    toast(_qText('gui_q_no_targets'));
    return;
  }

  const btn = document.getElementById('btn-apply-q');
  btn.disabled = true;
  btn.innerHTML = `<svg class="icon"><use href="#icon-settings"></use></svg> ${_qText('gui_q_applying')}`;

  try {
    let r;
    if (hrefs.length === 1) {
      r = await post('/api/quarantine/apply', { href: hrefs[0], level: sev });
    } else {
      r = await post('/api/quarantine/bulk_apply', { hrefs: hrefs, level: sev });
    }

    if (r.ok || r.success) {
      toast(_qText('gui_q_applied').replace('{count}', hrefs.length).replace('{level}', sev));
      closeModal('m-quarantine');
      // Uncheck all
      document.querySelectorAll('.qt-chk, .qw-chk, #qt-chkall, #qw-chkall').forEach(c => c.checked = false);
      updateBulkBar();
      // Refresh tables
      if (document.getElementById('qbtn-workloads').classList.contains('active')) {
        runWorkloadSearch();
      }
    } else {
      throw new Error(r.error || _t('gui_q_apply_error'));
    }
  } catch (err) {
    alert(_t('gui_q_apply_error') + ': ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = _qText('gui_q_apply');
  }
}

const renderSkeletonRow = (cols) => {
  let td = `<div class="skeleton skel-text"></div><div class="skeleton skel-text short"></div>`;
  let res = `<tr class="skel-tr">`;
  for (let i = 0; i < cols; i++) res += `<td>${td}</td>`;
  return res + `</tr>`;
};

// --- Traffic Analyzer Filters Modal ---
function openQtFiltersModal() {
  // Just visually open it, values remain in the inputs
  document.getElementById('modal-qt-filters').classList.add('show');
}

function applyQtFilters() {
  closeModal('modal-qt-filters');
  runTrafficAnalyzer(); // Automatically execute query with applied filters
}

function setTrafficQueryLoading(isLoading) {
  const btn = document.getElementById('btn-run-traffic-query');
  if (!btn) return;

  if (isLoading) {
    btn.disabled = true;
    btn.dataset.prevHtml = btn.innerHTML;
    btn.innerHTML = `<span class="btn-loading-dot"></span><span data-i18n="gui_querying">${_t('gui_querying')}</span>`;
    showSpinner('q-panel-traffic', _t('gui_ta_loading_hint'));
  } else {
    btn.disabled = false;
    if (btn.dataset.prevHtml) btn.innerHTML = btn.dataset.prevHtml;
    hideSpinner('q-panel-traffic');
  }
}

// --- Traffic Analyzer Endpoint ---
async function runTrafficAnalyzer() {
  const pdRadio = document.querySelector('input[name="qt-pd-radio"]:checked');
  const pd = pdRadio ? pdRadio.value : "";
  const dpdRadio = document.querySelector('input[name="qt-dpd-radio"]:checked');
  const draftPd = dpdRadio ? dpdRadio.value : "";
  const sort = document.getElementById('qt-sort').value;
  const search = document.getElementById('qt-search').value;
  const mins = parseInt(document.getElementById('qt-mins').value);

  const srcStr = document.getElementById('qt-src').value.trim();
  const dstStr = document.getElementById('qt-dst').value.trim();
  const exSrcStr = document.getElementById('qt-exsrc').value.trim();
  const exDstStr = document.getElementById('qt-exdst').value.trim();
  const expStr = document.getElementById('qt-expt').value.trim();
  const port = document.getElementById('qt-port').value.trim();
  const proto = document.getElementById('qt-proto').value;
  const anyLabelStr = document.getElementById('qt-any-label').value.trim();
  const anyIpStr = document.getElementById('qt-any-ip').value.trim();
  const exAnyLabelStr = document.getElementById('qt-ex-any-label').value.trim();
  const exAnyIpStr = document.getElementById('qt-ex-any-ip').value.trim();

  const bd = document.getElementById('qt-body');
  bd.innerHTML = renderSkeletonRow(8);
  document.getElementById('qt-chkall').checked = false;
  updateBulkBar();
  setTrafficQueryLoading(true);

  try {
    let payload = { mins, sort_by: sort, search: search };
    payload.policy_decision = pd || '-1';
    if (draftPd) payload.draft_policy_decision = draftPd;

    if (srcStr) {
      if (srcStr.includes('=')) payload.src_label = srcStr;
      else payload.src_ip_in = srcStr;
    }
    if (dstStr) {
      if (dstStr.includes('=')) payload.dst_label = dstStr;
      else payload.dst_ip_in = dstStr;
    }
    if (exSrcStr) {
      if (exSrcStr.includes('=')) payload.ex_src_label = exSrcStr;
      else payload.ex_src_ip = exSrcStr;
    }
    if (exDstStr) {
      if (exDstStr.includes('=')) payload.ex_dst_label = exDstStr;
      else payload.ex_dst_ip = exDstStr;
    }
    if (port) payload.port = port;
    if (expStr) payload.ex_port = expStr;
    if (proto) payload.proto = proto;
    if (anyLabelStr) payload.any_label = anyLabelStr;
    if (anyIpStr) payload.any_ip = anyIpStr;
    if (exAnyLabelStr) payload.ex_any_label = exAnyLabelStr;
    if (exAnyIpStr) payload.ex_any_ip = exAnyIpStr;

    const r = await post('/api/quarantine/search', payload);

    if (!r.ok || r.error) throw new Error(r.error || _t('gui_server_error'));

    // --- Pagination Logic ---
    _qt_data = r.data || [];
    _qt_page = 1;
    renderQtPage();
    // R5 Bug 1: previously the KPI strip (tw-kpi-flows / -conns / -dst-ips
    // / -peak-bw) was never wired — it stayed on placeholder "—". Compute
    // KPIs from the same dataset the table renders from.
    updateTrafficKpis(_qt_data);

  } catch (err) {
    bd.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--danger);">${_t('gui_rs_error_prefix')}: ${escapeHtml(err.message)}</td></tr>`;
    updateTrafficKpis([]);
  } finally {
    setTrafficQueryLoading(false);
  }
}

/* R5 Bug 1: populate the 4-cell KPI strip above the traffic query results.
 * Pure DOM update, no API call — derives all 4 KPIs from the query payload
 * the user just ran (so the numbers always match the table the user sees). */
function updateTrafficKpis(data) {
  const fmtInt = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US'));
  const fmtCompact = (n) => {
    if (n == null || isNaN(n)) return '—';
    const abs = Math.abs(n);
    if (abs >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (abs >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
  };
  const fmtBw = (mbps) => {
    if (mbps == null || mbps === 0) return '—';
    if (mbps >= 1000) return (mbps / 1000).toFixed(2) + ' Gbps';
    return mbps.toFixed(1) + ' Mbps';
  };

  const rows = Array.isArray(data) ? data : [];
  const flows = rows.length;
  let conns = 0;
  let peakBw = 0;
  const dstSet = new Set();
  for (const r of rows) {
    if (r && typeof r === 'object') {
      conns += Number(r.num_connections || r.connections || 0);
      const bw = Number(r.max_bandwidth_mbps || r.avg_bandwidth_mbps || 0);
      if (bw > peakBw) peakBw = bw;
      const dstIps = (r.destination && (r.destination.ip || r.destination.ip_list)) || r.dst_ip;
      if (typeof dstIps === 'string') dstIps.split(/[,\s]+/).filter(Boolean).forEach(ip => dstSet.add(ip));
      else if (Array.isArray(dstIps)) dstIps.forEach(ip => dstSet.add(ip));
    }
  }

  const setKpi = (id, value, suffix) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (suffix) {
      const suffixSpan = el.querySelector('span');
      el.textContent = value;
      if (suffixSpan) el.appendChild(suffixSpan);
      else el.innerHTML = `${value}<span>${suffix}</span>`;
    } else {
      el.textContent = value;
    }
  };

  setKpi('tw-kpi-flows', fmtInt(flows), 'flows');
  setKpi('tw-kpi-conns', fmtCompact(conns), '');
  setKpi('tw-kpi-dst-ips', fmtInt(dstSet.size), '');
  setKpi('tw-kpi-peak-bw', fmtBw(peakBw), '');
}
window.updateTrafficKpis = updateTrafficKpis;

let _qt_data = [];
let _qt_page = 1;

function renderQtPage() {
  const bd = document.getElementById('qt-body');
  const pageSize = parseInt(document.getElementById('qt-page-size').value);
  const total = _qt_data.length;
  const start = (_qt_page - 1) * pageSize;
  const end = Math.min(start + pageSize, total);
  const pageData = _qt_data.slice(start, end);

  const pagBar = document.getElementById('qt-pagination');
  const totalLabel = document.getElementById('qt-total-count');
  const pageNumDisplay = document.getElementById('qt-page-num');

  if (total > 0) {
    pagBar.style.display = 'flex';
    totalLabel.textContent = (_t('gui_total_found')).replace('{count}', total);
    pageNumDisplay.textContent = _qt_page;
  } else {
    pagBar.style.display = 'none';
    bd.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--dim);">${_t('gui_no_traffic')}</td></tr>`;
    return;
  }

  let html = '';
  pageData.forEach((item, idx) => {
    let shref = item.source.href;
    let dhref = item.destination.href;
    let hasWorkloadTarget = !!(shref || dhref);
    let chkBox = hasWorkloadTarget
      ? `<input type="checkbox" class="qt-chk" data-src-href="${escapeHtml(shref || '')}" data-dst-href="${escapeHtml(dhref || '')}" value="${escapeHtml(shref || dhref || '')}">`
      : `<span style="color:var(--dim);font-size:10px;">${_t('gui_q_workload_only')}</span>`;

    const formatActor = (actor) => {
      let procStr = '';
      if (actor.process || actor.user) {
        let p = actor.process ? `<span style="color:var(--accent); font-weight:bold;"><i class="fas fa-microchip"></i> ${escapeHtml(actor.process)}</span>` : '';
        let u = actor.user ? `<span style="color:var(--accent2);"><i class="fas fa-user"></i> ${escapeHtml(actor.user)}</span>` : '';
        procStr = `<div style="font-size:10px; margin-top:4px;">${p}${p && u ? '<br>' : ''}${u}</div>`;
      }
      return `<strong style="font-size:11px;">${escapeHtml(actor.name)}</strong><br><small style="color:var(--dim);">${escapeHtml(actor.ip)}</small>${procStr}<div style="margin-top:2px;">${renderLabelsHtml(actor.labels)}</div>`;
    };

    const sort = document.getElementById('qt-sort').value;
    let val_str = "";
    if (sort === "bandwidth") val_str = item.formatted_bandwidth;
    else if (sort === "volume") val_str = item.formatted_volume;
    else val_str = item.formatted_connections + " " + (_t('gui_flows'));

    let svc_str = "";
    let name_part = item.service.name ? item.service.name + " " : "";
    if (item.service.port !== "All") svc_str = `${name_part}${item.service.proto}/${item.service.port}`;
    else svc_str = name_part ? `${name_part}${_t('gui_all_services')}` : (_t('gui_all_services'));

    if (svc_str.length > 25) {
      let arr = svc_str.split(',').map(s => s.trim());
      let encJson = encodeURIComponent(JSON.stringify(arr));
      svc_str = `<span onclick="showCellPopover(event, 'SVC', JSON.parse(decodeURIComponent('${encJson}')))" style="cursor:pointer; border-bottom:1px dotted var(--dim); color:var(--accent);">${escapeHtml(svc_str.substring(0, 23))}...</span>`;
    } else {
      svc_str = escapeHtml(svc_str);
    }
    // process/user belong to service object (VEN telemetry), shown in service cell
    const svc_proc = item.service.process || '';
    const svc_user = item.service.user || '';
    if (svc_proc || svc_user) {
      let p = svc_proc ? `<span style="color:var(--accent); font-weight:bold;"><i class="fas fa-microchip"></i> ${escapeHtml(svc_proc)}</span>` : '';
      let u = svc_user ? `<span style="color:var(--accent2);"><i class="fas fa-user"></i> ${escapeHtml(svc_user)}</span>` : '';
      svc_str += `<div style="font-size:10px; margin-top:3px;">${p}${p && u ? '<br>' : ''}${u}</div>`;
    }

    const rawPd = item.policy_decision || '';
    const rawDraftPd = item.draft_policy_decision || '';
    const pd_blocked = _t('gui_pd_blocked');
    const pd_potential = _t('gui_pd_potential');
    const pd_allowed = _t('gui_pd_allowed');

    const makePdBadge = (pd, isReported) => {
      const prefix = isReported ? '' : '<span style="font-size:9px;opacity:0.8;">Draft </span>';
      if (pd === 'blocked') return `<span style="background:var(--danger);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${prefix}${pd_blocked}</span>`;
      if (pd === 'potentially_blocked') return `<span style="background:var(--warn);color:#000;padding:2px 6px;border-radius:4px;font-size:10px;">${prefix}${pd_potential}</span>`;
      if (pd === 'allowed') return `<span style="background:var(--success);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${prefix}${pd_allowed}</span>`;
      if (pd === 'blocked_by_boundary') return `<span style="background:var(--danger);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${prefix}${_t('pd_blocked_by_boundary')}</span>`;
      if (pd === 'blocked_by_override_deny') return `<span style="background:var(--danger);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${prefix}${_t('pd_blocked_by_override_deny')}</span>`;
      if (pd === 'potentially_blocked_by_boundary') return `<span style="background:var(--warn);color:#000;padding:2px 6px;border-radius:4px;font-size:10px;">${prefix}${_t('pd_potentially_blocked_by_boundary')}</span>`;
      if (pd === 'potentially_blocked_by_override_deny') return `<span style="background:var(--warn);color:#000;padding:2px 6px;border-radius:4px;font-size:10px;">${prefix}${_t('pd_potentially_blocked_by_override_deny')}</span>`;
      return `<span style="background:var(--dim);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${prefix}${pd}</span>`;
    };

    let pdBadge = makePdBadge(rawPd, true);
    let draftBadge = rawDraftPd ? `<div style="margin-top:3px;">${makePdBadge(rawDraftPd, false)}</div>` : '';

    let isoBtn = '';
    if (shref && dhref) isoBtn = `<button class="btn btn-danger btn-sm" onclick="openQuarantineModal('${shref}', false, '${dhref}')"><span data-i18n="gui_btn_isolate">${_t('gui_btn_isolate')}</span></button>`;
    else if (shref || dhref) isoBtn = `<button class="btn btn-danger btn-sm" onclick="openQuarantineModal('${shref || dhref}')"><span data-i18n="gui_btn_isolate">${_t('gui_btn_isolate')}</span></button>`;

    let f_seen = item.timestamp_range ? item.timestamp_range.first_detected || "" : "";
    let l_seen = item.timestamp_range ? item.timestamp_range.last_detected || "" : "";
    if (f_seen) f_seen = formatDateZ(f_seen);
    if (l_seen) l_seen = formatDateZ(l_seen);

    html += `<tr>
          <td style="text-align:center;">${chkBox}</td>
          <td><div style="font-weight:bold;color:var(--accent2);">${val_str}</div></td>
          <td style="font-size:10px;"><div style="color:var(--dim);">F: ${f_seen}</div><div style="color:var(--dim);">L: ${l_seen}</div></td>
          <td>${formatActor(item.source)}</td>
          <td>${formatActor(item.destination)}</td>
          <td>${svc_str}</td>
          <td>${pdBadge}${draftBadge}</td>
          <td>${isoBtn}</td>
        </tr>`;
  });
  bd.innerHTML = html;
  initTableResizers();
}

function qtNextPage() {
  const pageSize = parseInt(document.getElementById('qt-page-size').value);
  if (_qt_page * pageSize < _qt_data.length) {
    _qt_page++;
    renderQtPage();
  }
}

function qtPrevPage() {
  if (_qt_page > 1) {
    _qt_page--;
    renderQtPage();
  }
}

function openQtGuideModal() {
  document.getElementById('modal-qt-guide').classList.add('show');
}

// --- Workload Search Endpoint ---
async function runWorkloadSearch() {
  const name = document.getElementById('qw-name').value;
  const ip = document.getElementById('qw-ip').value;
  const host = document.getElementById('qw-host').value;

  const bd = document.getElementById('qw-body');
  bd.innerHTML = renderSkeletonRow(6);
  document.getElementById('qw-chkall').checked = false;
  updateBulkBar();

  try {
    const payload = { name, ip_address: ip, hostname: host };
    const qp = new URLSearchParams();
    if (name) qp.append('name', name);
    if (ip) qp.append('ip_address', ip);
    if (host) qp.append('hostname', host);
    
    const r = await fetch('/api/workloads?' + qp.toString()).then(res => res.json());

    if (!r.ok && r.error) throw new Error(r.error);
    _qw_data = r.data || [];
    _qw_page = 1;
    renderQwPage();

  } catch (err) {
    bd.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--danger);">${_t('gui_rs_error_prefix')}: ${escapeHtml(err.message)}</td></tr>`;
  }
}

let _qw_data = [];
let _qw_page = 1;

function renderQwPage() {
  const bd = document.getElementById('qw-body');
  const pageSize = parseInt(document.getElementById('qw-page-size').value);
  const total = _qw_data.length;
  const start = (_qw_page - 1) * pageSize;
  const end = Math.min(start + pageSize, total);
  const pageData = _qw_data.slice(start, end);

  const pagBar = document.getElementById('qw-pagination');
  const totalLabel = document.getElementById('qw-total-count');
  const pageNumDisplay = document.getElementById('qw-page-num');

  if (total > 0) {
    pagBar.style.display = 'flex';
    totalLabel.textContent = (_t('gui_total_found_ws')).replace('{count}', total);
    pageNumDisplay.textContent = _qw_page;
  } else {
    pagBar.style.display = 'none';
    bd.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--dim);" data-i18n="gui_ws_empty">${_t('gui_ws_empty')}</td></tr>`;
    return;
  }

  let html = '';
  pageData.forEach((w) => {
    const href = w.href;
    const isOnline = w.online === true;
    const statusText = isOnline ? (_t('gui_status_online')) : (_t('gui_status_offline'));
    const statusDot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${isOnline ? 'var(--success)' : 'var(--warn)'};margin-right:6px;" title="${statusText}"></span>`;

    let hasQuarantine = false;
    if (w.labels) {
      w.labels.forEach(l => {
        if (l.key === 'Quarantine') hasQuarantine = true;
      });
    }
    let labelsHtml = renderLabelsHtml(w.labels);

    // Show all IPv4 addresses (skip IPv6 / link-local that contain ':')
    let ipStr = "";
    if (w.interfaces && w.interfaces.length > 0) {
      const v4 = w.interfaces.filter(i => i.address && i.address.includes('.') && !i.address.includes(':'));
      if (v4.length > 0) {
        ipStr = v4.map(i =>
          `<div style="white-space:nowrap;">${escapeHtml(i.address)}<span style="font-size:10px;color:var(--dim);margin-left:4px;">(${escapeHtml(i.name)})</span></div>`
        ).join('');
      }
    }

    const mgmtText = w.managed ? (_t('gui_management_managed')) : (_t('gui_management_unmanaged'));

    const isManaged = w.managed === true;
    const accelLabel = escapeHtml((w.hostname || w.name || href).replace(/'/g, "\\'"));
    const accelBtn = isManaged
      ? `<button class="btn btn-secondary btn-sm" style="margin-left:6px;" title="${_t('gui_btn_accelerate_tip')}" onclick="accelerateOne('${href}','${accelLabel}')">${_t('gui_btn_accelerate')}</button>`
      : `<button class="btn btn-secondary btn-sm" style="margin-left:6px;" disabled title="${_t('gui_accel_unmanaged_tip')}">${_t('gui_btn_accelerate')}</button>`;

    html += `<tr>
          <td style="text-align:center;"><input type="checkbox" class="qw-chk" value="${href}" data-managed="${isManaged ? '1' : '0'}"></td>
          <td>
            <div style="display:flex;align-items:center;">
              ${statusDot} <strong style="font-size:0.95rem;">${escapeHtml(w.name || w.hostname)}</strong>
            </div>
            <div style="font-size:10px;color:var(--dim);margin-top:2px;margin-left:14px;">${escapeHtml(w.hostname)}</div>
          </td>
          <td><span style="font-size:11px; color:${w.managed ? 'var(--success)' : 'var(--dim)'}; font-weight:600;">${mgmtText}</span></td>
          <td>${ipStr}</td>
          <td style="font-size:11px;">${labelsHtml || `<span style="color:var(--dim);font-size:10px;">${_t('gui_no_labels')}</span>`}</td>
          <td>
            <button class="btn btn-danger btn-sm" onclick="openQuarantineModal('${href}')"><span data-i18n="gui_btn_isolate">${_t('gui_btn_isolate')}</span></button>
            ${accelBtn}
            ${hasQuarantine ? `<span style="font-size:10px;color:var(--danger);font-weight:bold;margin-left:8px;">${_t('gui_isolated')}</span>` : ''}
          </td>
        </tr>`;
  });
  bd.innerHTML = html;
  initTableResizers();
}

function qwNextPage() {
  const pageSize = parseInt(document.getElementById('qw-page-size').value);
  if (_qw_page * pageSize < _qw_data.length) {
    _qw_page++;
    renderQwPage();
  }
}

function qwPrevPage() {
  if (_qw_page > 1) {
    _qw_page--;
    renderQwPage();
  }
}

// Listen to Radio changes if isolating
document.querySelectorAll('input[name="q-dir"]').forEach(radio => {
  radio.addEventListener('change', refreshQuarantineTargets);
});

// Background initialization
setTimeout(() => {
  // Attempt to init quarantine labels so they are ready on PCE
  fetch('/api/init_quarantine', { method: 'POST', headers: { 'X-CSRF-Token': _csrfToken() } }).catch(() => { });
}, 2000);

initUiPreferences();
init();
testConn();

// --- Accelerate (Increase Traffic Update Rate) ---

async function accelerateOne(href, label) {
  try {
    const r = await post('/api/workloads/accelerate', { hrefs: [href], duration_minutes: 0 });
    if (!r.ok) throw new Error(r.error || 'failed');
    if (typeof toast === 'function') {
      toast(_t('gui_accel_done') + ': ' + label);
    } else {
      console.info('[accelerate] done:', label);
    }
  } catch (e) {
    if (typeof toast === 'function') {
      toast(_t('gui_rs_error_prefix') + ': ' + e.message, 'error');
    } else {
      console.error('[accelerate] failed:', e.message);
    }
  }
}

// --- Bulk Accelerate state (browser-tab-bound) ---
let _accel_timer = null;       // 10-minute re-issue interval
let _accel_tick = null;        // 1-second display tick
let _accel_endTs = 0;          // epoch ms when persistent mode should stop
let _accel_hrefs = [];         // managed hrefs to send each tick

function openAccelerateModal() {
  const checked = Array.from(document.querySelectorAll('.qw-chk:checked'));
  const all = checked.map(c => ({
    href: c.value,
    managed: c.dataset.managed === '1',
  }));
  const managed = all.filter(x => x.managed);
  const skipped = all.length - managed.length;

  const summary = (_t('gui_accel_modal_summary') || '')
    .replace('{total}', all.length)
    .replace('{managed}', managed.length)
    .replace('{skipped}', skipped);
  const sumEl = document.getElementById('accel-summary');
  if (sumEl) sumEl.textContent = summary;

  _accel_hrefs = managed.map(x => x.href);
  document.getElementById('m-accelerate').classList.add('show');
}

async function _fireAccelerate(durationMinutes) {
  try {
    const r = await post('/api/workloads/accelerate', { hrefs: _accel_hrefs, duration_minutes: durationMinutes });
    if (!r.ok) throw new Error(r.error || 'failed');
    return r;
  } catch (e) {
    if (typeof toast === 'function') {
      toast(_t('gui_rs_error_prefix') + ': ' + e.message, 'error');
    } else {
      console.error('[accelerate] failed:', e.message);
    }
    return { ok: false };
  }
}

async function confirmAccelerate() {
  const dur = parseInt(
    document.querySelector('input[name="accel-dur"]:checked').value, 10
  );
  closeModal('m-accelerate');
  if (_accel_hrefs.length === 0) return;

  cancelAccelerate();   // unconditional: also cancels any prior persistent run when this submit is single-shot
  await _fireAccelerate(dur);
  if (typeof toast === 'function') {
    toast(_t('gui_accel_started').replace('{n}', _accel_hrefs.length));
  }

  if (dur > 0) {
    _accel_endTs = Date.now() + dur * 60_000;
    _accel_timer = setInterval(() => {
      if (Date.now() >= _accel_endTs) { cancelAccelerate(); return; }
      _fireAccelerate(dur);
    }, 600_000);  // every 10 minutes
    _showAccelCountdown();
  }
}

function cancelAccelerate() {
  if (_accel_timer) { clearInterval(_accel_timer); _accel_timer = null; }
  if (_accel_tick) { clearInterval(_accel_tick); _accel_tick = null; }
  _accel_endTs = 0;
  const bar = document.getElementById('accel-countdown');
  if (bar) bar.style.display = 'none';
}

function _showAccelCountdown() {
  const bar = document.getElementById('accel-countdown');
  const countEl = document.getElementById('accel-count');
  const remEl = document.getElementById('accel-remaining');
  if (!bar || !countEl || !remEl) return;

  countEl.textContent = String(_accel_hrefs.length);
  bar.style.display = 'flex';

  const fmt = (ms) => {
    const total = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };
  remEl.textContent = fmt(_accel_endTs - Date.now());
  _accel_tick = setInterval(() => {
    const left = _accel_endTs - Date.now();
    if (left <= 0) { cancelAccelerate(); return; }
    remEl.textContent = fmt(left);
  }, 1000);
}

// ─── R4k: 7-day traffic trend SVG chart ──────────────────────────────────────

/**
 * Fetch /api/traffic/trend and render an inline SVG area chart.
 * Safe to call multiple times; debounced by _trendFetching flag.
 */
let _trendFetching = false;
let _trendFlaggedOnly = false;   // R4k: hide the dominant allowed band, rescale to flagged
let _trendBuckets = null;        // last-rendered data, so the toggle re-renders without a refetch

// Toggle: drop the allowed band and rescale Y to flagged traffic so spikes show.
document.addEventListener('change', function (e) {
  if (e.target && e.target.id === 'tw-trend-flagged-only') {
    _trendFlaggedOnly = e.target.checked;
    renderTrafficTrend(_trendBuckets || []);
  }
});

async function loadTrafficTrend() {
  if (_trendFetching) return;
  _trendFetching = true;
  const meta = document.getElementById('tw-trend-meta');
  if (meta) meta.textContent = '— loading';
  try {
    const r = await get('/api/traffic/trend');
    renderTrafficTrend((r && r.buckets) ? r.buckets : []);
  } catch (_) {
    renderTrafficTrend([]);
  } finally {
    _trendFetching = false;
  }
}

function _svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

// Stacked-area series, bottom→top. Security-relevant bands ride on top so spikes
// in blocked / potentially-blocked traffic are visually obvious.
const _TREND_SERIES = [
  { key: 'allowed',   stroke: '#16a34a', fill: 'rgba(22,163,74,0.16)' },
  { key: 'potential', stroke: '#f59e0b', fill: 'rgba(245,158,11,0.28)' },
  { key: 'blocked',   stroke: '#dc2626', fill: 'rgba(220,38,38,0.42)' },
];

function renderTrafficTrend(buckets) {
  const svg  = document.getElementById('tw-trend-svg');
  const meta = document.getElementById('tw-trend-meta');
  if (!svg) return;

  const x0El = document.getElementById('tw-trend-x0');
  const x1El = document.getElementById('tw-trend-x1');

  _trendBuckets = buckets; // cache so the flagged-only toggle re-renders without a refetch

  svg.replaceChildren(); // clear previous render — no innerHTML

  if (!buckets || !buckets.length) {
    if (meta) meta.textContent = 'No history data';
    if (x0El) x0El.textContent = '—';
    if (x1El) x1El.textContent = '—';
    return;
  }

  // Back-compat: a bucket may carry only a legacy `flows` total. Treat it as allowed.
  const norm = buckets.map(b => ({
    allowed:   +b.allowed   || (b.potential == null && b.blocked == null ? (+b.flows || 0) : 0),
    potential: +b.potential || 0,
    blocked:   +b.blocked   || 0,
  }));

  // Flagged-only drops the allowed band; remaining series rescale to fill the chart.
  const series = _trendFlaggedOnly
    ? _TREND_SERIES.filter(s => s.key !== 'allowed')
    : _TREND_SERIES;
  const visKeys = series.map(s => s.key);

  const W = 800, H = 200, padX = 8, padY = 14;
  const n = norm.length;
  const totals = norm.map(b => visKeys.reduce((a, k) => a + b[k], 0));
  const maxY = Math.max(...totals, 1);
  const xAt = i => padX + (W - 2 * padX) * (i / Math.max(n - 1, 1));
  const yAt = v => H - padY - (H - 2 * padY) * (v / maxY);

  const frag = document.createDocumentFragment();

  // gridlines
  for (const p of [0.25, 0.5, 0.75]) {
    const y = (padY + (H - 2 * padY) * p).toFixed(1);
    frag.appendChild(_svgEl('line', {
      x1: padX, y1: y, x2: W - padX, y2: y,
      stroke: 'var(--border)', 'stroke-dasharray': '2 4',
    }));
  }

  // Stacked bands: each series fills between its lower and upper cumulative boundary.
  const lower = norm.map(() => 0);
  for (const s of series) {
    const upper = norm.map((b, i) => lower[i] + b[s.key]);
    const upPts  = upper.map((v, i) => [xAt(i), yAt(v)]);
    const lowPts = lower.map((v, i) => [xAt(i), yAt(v)]);
    const fwd = upPts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
    const back = lowPts.slice().reverse().map(p => `L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
    frag.appendChild(_svgEl('path', { d: `${fwd} ${back} Z`, fill: s.fill, stroke: 'none' }));
    frag.appendChild(_svgEl('path', {
      d: fwd, fill: 'none', stroke: s.stroke,
      'stroke-width': '1.5', 'stroke-linejoin': 'round',
    }));
    for (let i = 0; i < n; i++) lower[i] = upper[i];
  }

  // max label
  const label = _svgEl('text', {
    x: padX, y: padY - 2, fill: 'var(--dim)',
    'font-size': '10', 'font-family': 'var(--font-mono-2,monospace)',
  });
  label.textContent = maxY.toLocaleString();
  frag.appendChild(label);

  svg.appendChild(frag);

  const sum = k => norm.reduce((s, b) => s + b[k], 0);
  const flagged = sum('potential') + sum('blocked');
  if (meta) {
    meta.textContent = flagged
      ? `${flagged.toLocaleString()} blocked/potential · ${(sum('allowed') + flagged).toLocaleString()} flows · 7d`
      : `${(sum('allowed') + flagged).toLocaleString()} flows · 7d`;
  }
  if (x0El && buckets[0]?.ts)     x0El.textContent = String(buckets[0].ts).slice(0, 10);
  if (x1El && buckets[n - 1]?.ts) x1El.textContent = String(buckets[n - 1].ts).slice(0, 10);
}
