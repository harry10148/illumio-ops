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
    target.textContent = 'No alert plugins available.';
    return;
  }

  target.innerHTML = channels.map(channel => {
    const issues = [];
    if (!channel.enabled) issues.push('disabled');
    if (!channel.configured && channel.missing_required && channel.missing_required.length) {
      issues.push(`missing ${channel.missing_required.join(', ')}`);
    }
    if (channel.last_status) issues.push(`last=${channel.last_status}`);
    if (channel.last_error) issues.push(channel.last_error);
    const detail = issues.length ? issues.join(' | ') : 'ready';
    const when = channel.last_timestamp ? ` at ${formatDateZ(channel.last_timestamp) || channel.last_timestamp}` : '';
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
    container.innerHTML = `<button class="btn btn-primary" onclick="runAction('test-alert')">Send All</button>` +
      channels.map(channel => `
        <button
          class="btn btn-secondary"
          style="${(!channel.enabled || !channel.configured) ? 'opacity:0.72;' : ''}"
          onclick="runPluginTestAlert('${escapeHtml(channel.name)}')"
          title="${escapeHtml(channel.description || '')}"
        >Test ${escapeHtml(channel.display_name || channel.name)}</button>
      `).join('');
    _renderAlertChannelStatus(channels);
  } catch (e) {
    statusBox.textContent = 'Failed to load alert plugin status.';
  }
}

async function runAction(name, body = {}) {
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + '] Running ' + name + '...';
  const r = await post('/api/actions/' + name, body);
  alog(r.output || 'Done.');
  if (r.results && r.results.length) {
    r.results.forEach(result => {
      alog(`${result.channel}: ${result.status}${result.target ? ' -> ' + result.target : ''}${result.error ? ' | ' + result.error : ''}`);
    });
  }
  if (name === 'best-practices') { loadRules(); loadDashboard(); }
  if (name === 'test-alert') { await loadDashboard(); await loadAlertTestActions(); }
  toast('??' + name + ' completed');
}

async function runPluginTestAlert(channel) {
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + `] Sending test alert via ${channel}...`;
  const r = await post('/api/actions/test-alert', { channel });
  alog(r.output || 'Done.');
  if (r.results && r.results.length) {
    r.results.forEach(result => {
      alog(`${result.channel}: ${result.status}${result.target ? ' -> ' + result.target : ''}${result.error ? ' | ' + result.error : ''}`);
    });
  }
  await loadDashboard();
  await loadAlertTestActions();
  toast(`Test alert completed: ${channel}`);
}

async function runDebug() {
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + '] Running debug mode...';
  const r = await post('/api/actions/debug', { mins: $('a-debug-mins').value, pd_sel: $('a-debug-pd').value });
  alog(r.output || 'Done.');
  toast('??Debug completed');
}

async function stopGui() {
  if (!confirm('Stop the Web GUI server? The browser page will close.')) return;
  try { await post('/api/shutdown', {}); } catch (e) { }
  document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px"><h1 style="color:var(--accent2)">Web GUI Stopped</h1><p style="color:var(--dim)">You may close this tab. Restart from CLI or use --gui.</p></div>';
}
