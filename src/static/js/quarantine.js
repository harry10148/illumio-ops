/* ─── Traffic & Quarantine Logic ──────────────────────────────────── */

// Sub Navigation
function switchQTab(tabStr, updateUrl = true) {
  document.querySelectorAll('.sub-nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('qbtn-' + tabStr).classList.add('active');

  document.querySelectorAll('.q-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('q-panel-' + tabStr).classList.add('active');
  if (updateUrl) updateUrlState('qtab', tabStr);
}

// Checkboxes and Bulk Bar
function toggleQChecks(clsPrefix) {
  const isAll = document.getElementById(clsPrefix + 'all').checked;
  document.querySelectorAll('.' + clsPrefix).forEach(c => c.checked = isAll);
  updateBulkBar();
}

function updateBulkBar() {
  // Check both traffic and workload tables for checks
  const checked = document.querySelectorAll('.qt-chk:checked, .qw-chk:checked');
  const bar = document.getElementById('bulk-bar');
  if (checked.length > 0) {
    document.getElementById('bulk-sel-count').textContent = checked.length;
    bar.classList.add('show');
  } else {
    bar.classList.remove('show');
  }
}

// Add event listeners to table bodies for dynamic checkbox listening
document.addEventListener('change', function (e) {
  if (e.target && (e.target.classList.contains('qt-chk') || e.target.classList.contains('qw-chk'))) {
    updateBulkBar();
  }
});

function openQuarantineModal(href, isBulk = false, altHref = null) {
  let targetHrefs = [];
  document.getElementById('q-direction-grp').style.display = 'none';

  if (isBulk) {
    const checked = document.querySelectorAll('.qt-chk:checked, .qw-chk:checked');
    checked.forEach(c => {
      let h = c.value || c.dataset.href;
      if (h && !targetHrefs.includes(h)) targetHrefs.push(h);
    });
    if (targetHrefs.length === 0) return;
  } else {
    if (altHref && href && altHref !== href) {
      // Traffic analyzer flow - need to pick source or dest
      document.getElementById('q-direction-grp').style.display = 'block';
      window._qTempHrefs = { source: href, destination: altHref };
      targetHrefs = [document.querySelector('input[name="q-dir"]:checked').value === 'source' ? href : altHref];
    } else {
      targetHrefs = [href];
    }
  }
  document.getElementById('q-target-count').textContent = targetHrefs.length;
  document.getElementById('q-target-hrefs').value = JSON.stringify(targetHrefs);

  document.getElementById('m-quarantine').classList.add('show');
}

async function applyQuarantine() {
  const sev = document.getElementById('q-severity').value;
  const rawHrefs = document.getElementById('q-target-hrefs').value;
  let hrefs = [];
  try { hrefs = JSON.parse(rawHrefs); } catch (e) { }
  if (hrefs.length === 0) return;

  const btn = document.getElementById('btn-apply-q');
  btn.disabled = true;
  btn.innerHTML = `<svg class="icon"><use href="#icon-settings"></use></svg> Applying...`;

  try {
    let r;
    if (hrefs.length === 1) {
      r = await post('/api/quarantine/apply', { href: hrefs[0], level: sev });
    } else {
      r = await post('/api/quarantine/bulk_apply', { hrefs: hrefs, level: sev });
    }

    if (r.ok || r.success) {
      toast(`Isolated ${hrefs.length} workload(s) with ${sev} rules.`);
      closeModal('m-quarantine');
      // Uncheck all
      document.querySelectorAll('.qt-chk, .qw-chk, #qt-chkall, #qw-chkall').forEach(c => c.checked = false);
      updateBulkBar();
      // Refresh tables
      if (document.getElementById('qbtn-workloads').classList.contains('active')) {
        runWorkloadSearch();
      }
    } else {
      throw new Error(r.error || "Failed to apply quarantine");
    }
  } catch (err) {
    alert("Quarantine Apply Error: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `Apply Isolation`;
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

// --- Traffic Analyzer Endpoint ---
async function runTrafficAnalyzer() {
  const pdRadio = document.querySelector('input[name="qt-pd-radio"]:checked');
  const pd = pdRadio ? pdRadio.value : "-1";
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

  try {
    let payload = { mins, sort_by: sort, search: search, policy_decision: pd };

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

    if (!r.ok || r.error) throw new Error(r.error || 'Server error');

    // --- Pagination Logic ---
    _qt_data = r.data || [];
    _qt_page = 1;
    renderQtPage();

  } catch (err) {
    bd.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--danger);">Error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

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
    totalLabel.textContent = (_translations['gui_total_found'] || 'Total {count} records').replace('{count}', total);
    pageNumDisplay.textContent = _qt_page;
  } else {
    pagBar.style.display = 'none';
    bd.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--dim);">${_translations['gui_no_traffic'] || 'No anomalous traffic found matching criteria.'}</td></tr>`;
    return;
  }

  let html = '';
  pageData.forEach((item, idx) => {
    let shref = item.source.href;
    let dhref = item.destination.href;
    let targetHref = shref || dhref || "";
    let chkBox = targetHref ? `<input type="checkbox" class="qt-chk" value="${targetHref}">` : `<span style="color:var(--dim);font-size:10px;">${_translations['gui_management_unmanaged'] || 'Unmanaged'}</span>`;

    const formatActor = (actor) => {
      return `<strong style="font-size:11px;">${escapeHtml(actor.name)}</strong><br><small style="color:var(--dim);">${escapeHtml(actor.ip)}</small><div style="margin-top:2px;">${renderLabelsHtml(actor.labels)}</div>`;
    };

    const sort = document.getElementById('qt-sort').value;
    let val_str = "";
    if (sort === "bandwidth") val_str = item.formatted_bandwidth;
    else if (sort === "volume") val_str = item.formatted_volume;
    else val_str = item.formatted_connections + " " + (_translations['gui_flows'] || "flows");

    let svc_str = "";
    let name_part = item.service.name ? item.service.name + " " : "";
    if (item.service.port !== "All") svc_str = `${name_part}${item.service.proto}/${item.service.port}`;
    else svc_str = name_part ? `${name_part}${_translations['gui_all_services'] || "All Services"}` : (_translations['gui_all_services'] || "All Services");

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
    let pdBadge = '';
    const pd_blocked = _translations['gui_pd_blocked'] || 'Blocked';
    const pd_potential = _translations['gui_pd_potential'] || 'Potential';
    const pd_allowed = _translations['gui_pd_allowed'] || 'Allowed';

    if (rawPd === 'blocked') pdBadge = `<span style="background:var(--danger);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${pd_blocked}</span>`;
    else if (rawPd === 'potentially_blocked') pdBadge = `<span style="background:var(--warn);color:#000;padding:2px 6px;border-radius:4px;font-size:10px;">${pd_potential}</span>`;
    else pdBadge = `<span style="background:var(--success);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">${pd_allowed}</span>`;

    let isoBtn = '';
    if (shref && dhref) isoBtn = `<button class="btn btn-secondary btn-sm" onclick="openQuarantineModal('${shref}', false, '${dhref}')"><span data-i18n="gui_btn_isolate">Isolate</span></button>`;
    else if (shref || dhref) isoBtn = `<button class="btn btn-secondary btn-sm" onclick="openQuarantineModal('${shref || dhref}')"><span data-i18n="gui_btn_isolate">Isolate</span></button>`;

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
          <td>${pdBadge}</td>
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
    bd.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--danger);">Error: ${escapeHtml(err.message)}</td></tr>`;
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
    totalLabel.textContent = (_translations['gui_total_found_ws'] || 'Total {count} workloads').replace('{count}', total);
    pageNumDisplay.textContent = _qw_page;
  } else {
    pagBar.style.display = 'none';
    bd.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--dim);" data-i18n="gui_ws_empty">${_translations['gui_ws_empty'] || 'Search by IP or Name to find workloads in the PCE.'}</td></tr>`;
    return;
  }

  let html = '';
  pageData.forEach((w) => {
    const href = w.href;
    const isOnline = w.online === true;
    const statusText = isOnline ? (_translations['gui_status_online'] || 'Online') : (_translations['gui_status_offline'] || 'Offline');
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

    const mgmtText = w.managed ? (_translations['gui_management_managed'] || 'Managed') : (_translations['gui_management_unmanaged'] || 'Unmanaged');

    html += `<tr>
          <td style="text-align:center;"><input type="checkbox" class="qw-chk" value="${href}"></td>
          <td>
            <div style="display:flex;align-items:center;">
              ${statusDot} <strong style="font-size:0.95rem;">${escapeHtml(w.name || w.hostname)}</strong>
            </div>
            <div style="font-size:10px;color:var(--dim);margin-top:2px;margin-left:14px;">${escapeHtml(w.hostname)}</div>
          </td>
          <td><span style="font-size:11px; color:${w.managed ? 'var(--success)' : 'var(--dim)'}">${mgmtText}</span></td>
          <td>${ipStr}</td>
          <td style="font-size:11px;">${labelsHtml || '<span style="color:var(--dim);font-size:10px;">No Labels</span>'}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="openQuarantineModal('${href}')"><span data-i18n="gui_btn_isolate">Isolate</span></button>
            ${hasQuarantine ? `<span style="font-size:10px;color:var(--danger);font-weight:bold;margin-left:8px;">Isolated</span>` : ''}
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
  radio.addEventListener('change', (e) => {
    if (window._qTempHrefs) {
      let tgt = e.target.value === 'source' ? window._qTempHrefs.source : window._qTempHrefs.destination;
      document.getElementById('q-target-hrefs').value = JSON.stringify([tgt]);
    }
  });
});

// Background initialization
setTimeout(() => {
  // Attempt to init quarantine labels so they are ready on PCE
  fetch('/api/init_quarantine', { method: 'POST', headers: { 'X-CSRF-Token': _csrfToken() } }).catch(() => { });
}, 2000);

initUiPreferences();
init();
testConn();
