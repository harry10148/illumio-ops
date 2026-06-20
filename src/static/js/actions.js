function _alertChannelTone(channel) {
  if (!channel.enabled) return 'var(--dim)';
  if (!channel.configured) return 'var(--warn)';
  if (channel.last_status === 'success') return 'var(--success)';
  if (channel.last_status === 'failed') return 'var(--danger)';
  if (channel.last_status === 'skipped') return 'var(--warn)';
  return 'var(--accent2)';
}

function _renderAlertChannelStatus(channels) {
  const target = $('a-test-alert-status');
  if (!target) return;
  if (!channels || !channels.length) {
    target.textContent = _t('gui_action_no_plugins');
    return;
  }

  target.innerHTML = channels.map(channel => {
    const issues = [];
    if (!channel.enabled) issues.push(_t('gui_action_plugin_disabled'));
    if (!channel.configured && channel.missing_required && channel.missing_required.length) {
      issues.push(`${_t('gui_action_plugin_missing_prefix')} ${channel.missing_required.join(', ')}`);
    }
    if (channel.last_status) issues.push(`${_t('gui_action_plugin_last_prefix')}=${channel.last_status}`);
    if (channel.last_error) issues.push(channel.last_error);
    const detail = issues.length ? issues.join(' | ') : _t('gui_action_plugin_ready');
    const when = channel.last_timestamp
      ? ` ${_t('gui_action_plugin_at')} ${formatDateZ(channel.last_timestamp) || channel.last_timestamp}`
      : '';
    const targetText = channel.last_target ? ` -> ${channel.last_target}` : '';
    return `<div style="margin-bottom:6px;color:${_alertChannelTone(channel)};"><strong>${escapeHtml(channel.display_name || channel.name)}</strong>: ${escapeHtml(detail)}${escapeHtml(targetText)}${escapeHtml(when)}</div>`;
  }).join('');
}

async function loadAlertTestActions() {
  const container = $('a-test-alert-actions');
  const statusBox = $('a-test-alert-status');
  if (!container || !statusBox) return;

  try {
    const status = await api('/api/status');
    const channels = status.alert_channels || [];
    container.innerHTML = `<button class="btn btn-primary" onclick="runAction('test-alert')">${_t('gui_action_send_all')}</button>` +
      channels.map(channel => `
        <button
          class="btn btn-secondary"
          style="${(!channel.enabled || !channel.configured) ? 'opacity:0.72;' : ''}"
          onclick="runPluginTestAlert('${escapeHtml(channel.name)}')"
          title="${escapeHtml(channel.description || '')}"
        >${_t('gui_action_test_prefix')} ${escapeHtml(channel.display_name || channel.name)}</button>
      `).join('');
    _renderAlertChannelStatus(channels);
  } catch (e) {
    statusBox.textContent = _t('gui_action_failed_load_plugin_status');
  }
}

async function runAction(name, body = {}) {
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + '] ' + _t('gui_action_running').replace('{name}', name);
  const r = await post('/api/actions/' + name, body);
  alog(r.output || _t('gui_action_done'));
  if (r.results && r.results.length) {
    r.results.forEach(result => {
      alog(`${result.channel}: ${result.status}${result.target ? ' -> ' + result.target : ''}${result.error ? ' | ' + result.error : ''}`);
    });
  }
  if (name === 'best-practices') { loadRules(); loadDashboard(); }
  if (name === 'test-alert') { await loadDashboard(); await loadAlertTestActions(); }
  toast(_t('gui_action_completed').replace('{name}', name));
}

async function runPluginTestAlert(channel) {
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + '] ' + _t('gui_action_send_test_alert_via').replace('{channel}', channel);
  const r = await post('/api/actions/test-alert', { channel });
  alog(r.output || _t('gui_action_done'));
  if (r.results && r.results.length) {
    r.results.forEach(result => {
      alog(`${result.channel}: ${result.status}${result.target ? ' -> ' + result.target : ''}${result.error ? ' | ' + result.error : ''}`);
    });
  }
  await loadDashboard();
  await loadAlertTestActions();
  toast(_t('gui_action_test_alert_completed').replace('{channel}', channel));
}

async function runDebug() {
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + '] ' + _t('gui_action_debug_running');
  const r = await post('/api/actions/debug', { mins: $('a-debug-mins').value, pd_sel: $('a-debug-pd').value });
  alog(r.output || _t('gui_action_done'));
  toast(_t('gui_action_debug_completed'));
}

async function resetWatermark() {
  if (!confirm(_t('gui_reset_watermark_confirm'))) return;
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + '] ' + _t('gui_reset_watermark_label');
  const r = await post('/api/actions/reset-watermark', {});
  alog(r.output || _t('gui_action_done'));
  toast(r.output || _t('gui_action_done'));
}

async function stopGui() {
  hdrMenuClose();
  if (!confirm(_t('gui_action_stop_gui_confirm'))) return;
  try { await post('/api/shutdown', {}); } catch (e) { }
  document.body.innerHTML =
    '<div style="display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px">' +
    `<h1 style="color:var(--accent2)">${_t('gui_action_gui_stopped_title')}</h1>` +
    `<p style="color:var(--dim)">${_t('gui_action_gui_stopped_body')}</p>` +
    '</div>';
}

function hdrMenuToggle() {
  const panel = document.getElementById('hdr-menu-panel');
  const btn = document.getElementById('hdr-menu-btn');
  if (!panel || !btn) return;
  const willOpen = panel.hidden;
  panel.hidden = !willOpen;
  btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
  if (willOpen) {
    setTimeout(() => {
      document.addEventListener('click', _hdrMenuOutsideClick, { capture: true });
      document.addEventListener('keydown', _hdrMenuEsc, { capture: true });
    }, 0);
  } else {
    document.removeEventListener('click', _hdrMenuOutsideClick, { capture: true });
    document.removeEventListener('keydown', _hdrMenuEsc, { capture: true });
  }
}

function hdrMenuClose() {
  const panel = document.getElementById('hdr-menu-panel');
  const btn = document.getElementById('hdr-menu-btn');
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  if (btn) btn.setAttribute('aria-expanded', 'false');
  document.removeEventListener('click', _hdrMenuOutsideClick, { capture: true });
  document.removeEventListener('keydown', _hdrMenuEsc, { capture: true });
}

function _hdrMenuOutsideClick(ev) {
  const panel = document.getElementById('hdr-menu-panel');
  const btn = document.getElementById('hdr-menu-btn');
  if (!panel || !btn) return;
  if (panel.contains(ev.target) || btn.contains(ev.target)) return;
  hdrMenuClose();
}

function _hdrMenuEsc(ev) {
  if (ev.key === 'Escape') {
    hdrMenuClose();
    const btn = document.getElementById('hdr-menu-btn');
    if (btn) btn.focus();
  }
}
