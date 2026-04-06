/* ─── Settings ────────────────────────────────────────────────────── */
let _settings = {};
let _security = {};
async function loadSettings() {
  _settings = await api('/api/settings');
  try { _security = await api('/api/security'); } catch (e) { _security = {}; }

  const s = _settings, a = s.api || {}, e = s.email || {}, sm = s.smtp || {}, al = s.alerts || {}, st = s.settings || {}, rpt = s.report || {};
  const sec = _security || {};
  const active = al.active || [];
  const profiles = s.pce_profiles || [];
  const activePceId = s.active_pce_id || null;

  const profileOptions = profiles.map(p =>
    `<option value="${p.id}" ${p.id === activePceId ? 'selected' : ''}>${escapeHtml(p.name)}</option>`
  ).join('');
  const profileRows = profiles.map(p => `
    <tr>
      <td>${escapeHtml(p.name)}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(p.url)}">${escapeHtml(p.url)}</td>
      <td>${p.org_id || ''}</td>
      <td>
        ${p.id !== activePceId ? `<button class="btn btn-primary btn-sm" onclick="activatePceProfile(${p.id})" data-i18n="gui_pce_activate">Activate</button>` : `<span style="color:var(--success);font-weight:600">✓</span>`}
        <button class="btn btn-sm" style="margin-left:4px" onclick="deletePceProfile(${p.id})" data-i18n="gui_pce_delete_profile">Delete</button>
      </td>
    </tr>`).join('');

  $('s-form').innerHTML = `
<fieldset><legend data-i18n="gui_pce_profiles">PCE Profiles</legend>
  ${profiles.length > 0 ? `
  <div style="overflow-x:auto;margin-bottom:12px">
    <table class="rule-table" style="width:100%">
      <thead><tr><th data-i18n="gui_pce_name">Name</th><th data-i18n="gui_url">URL</th><th data-i18n="gui_org_id">Org ID</th><th style="width:160px"></th></tr></thead>
      <tbody>${profileRows}</tbody>
    </table>
  </div>` : ''}
  <details style="margin-top:4px"><summary style="cursor:pointer;color:var(--accent)" data-i18n="gui_pce_add">Add PCE Profile</summary>
  <div style="padding:12px 0 0">
    <div class="form-row">
      <div class="form-group"><label data-i18n="gui_pce_name">Profile Name</label><input id="s-pce-name" placeholder="My PCE"></div>
      <div class="form-group"><label data-i18n="gui_url">URL</label><input id="s-pce-url" placeholder="https://pce.example.com:8443"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label data-i18n="gui_org_id">Org ID</label><input id="s-pce-org" value="1"></div>
      <div class="form-group"><label data-i18n="gui_api_key">API Key</label><input id="s-pce-key"></div>
      <div class="form-group"><label data-i18n="gui_api_secret">API Secret</label><input id="s-pce-secret" type="password"></div>
    </div>
    <div class="chk" style="margin-bottom:8px"><label><input type="checkbox" id="s-pce-ssl" checked> <span data-i18n="gui_verify_ssl">Verify SSL</span></label></div>
    <button class="btn btn-primary btn-sm" onclick="addPceProfile()" data-i18n="gui_pce_add">Add PCE Profile</button>
  </div></details>
  ${activePceId ? `<p style="margin-top:8px;color:var(--dim);font-size:0.85em">⚡ <span data-i18n="gui_pce_active">Active PCE</span>: <strong>${escapeHtml((profiles.find(p=>p.id===activePceId)||{}).name||'')}</strong> — <span data-i18n="gui_pce_save_profile" style="font-style:italic">Saving settings will update this profile.</span></p>` : ''}
</fieldset>
<fieldset><legend data-i18n="gui_api_conn">API Connection</legend>
  <div class="form-row"><div class="form-group"><label data-i18n="gui_url">URL</label><input id="s-url" value="${a.url || ''}"></div><div class="form-group"><label data-i18n="gui_org_id">Org ID</label><input id="s-org" value="${a.org_id || ''}"></div></div>
  <div class="form-row"><div class="form-group"><label data-i18n="gui_api_key">API Key</label><input id="s-key" value="${a.key || ''}"></div><div class="form-group"><label data-i18n="gui_api_secret">API Secret</label><input id="s-sec" type="password" value="${a.secret || ''}"></div></div>
  <div class="chk"><label><input type="checkbox" id="s-ssl" ${a.verify_ssl ? 'checked' : ''}> <span data-i18n="gui_verify_ssl">Verify SSL</span></label></div>
</fieldset>
<fieldset><legend data-i18n="gui_email_smtp">Email & SMTP</legend>
  <div class="form-row"><div class="form-group"><label data-i18n="gui_sender">Sender</label><input id="s-sender" value="${e.sender || ''}"></div><div class="form-group"><label data-i18n="gui_recipients">Recipients (comma)</label><input id="s-rcpt" value="${(e.recipients || []).join(', ')}"></div></div>
  <div class="form-row"><div class="form-group"><label data-i18n="gui_smtp_host">SMTP Host</label><input id="s-smhost" value="${sm.host || ''}"></div><div class="form-group"><label data-i18n="gui_port">Port</label><input id="s-smport" value="${sm.port || 25}"></div></div>
  <div class="form-row"><div class="form-group"><label data-i18n="gui_user">User</label><input id="s-smuser" value="${sm.user || ''}"></div><div class="form-group"><label data-i18n="gui_password">Password</label><input id="s-smpass" type="password" value="${sm.password || ''}"></div></div>
  <div style="display:flex;gap:20px"><div class="chk"><label><input type="checkbox" id="s-tls" ${sm.enable_tls ? 'checked' : ''}> STARTTLS</label></div><div class="chk"><label><input type="checkbox" id="s-auth" ${sm.enable_auth ? 'checked' : ''}> Auth</label></div></div>
</fieldset>
<fieldset><legend data-i18n="gui_alert_channels">Alert Channels</legend>
  <div style="display:flex;gap:20px;margin-bottom:12px"><div class="chk"><label><input type="checkbox" id="s-amail" ${active.includes('mail') ? 'checked' : ''}> <span data-i18n="gui_mail">Mail</span></label></div><div class="chk"><label><input type="checkbox" id="s-aline" ${active.includes('line') ? 'checked' : ''}> <span data-i18n="gui_line">LINE</span></label></div><div class="chk"><label><input type="checkbox" id="s-awh" ${active.includes('webhook') ? 'checked' : ''}> <span data-i18n="gui_webhook">Webhook</span></label></div></div>
  <div class="form-row"><div class="form-group"><label data-i18n="gui_line_token">LINE Token</label><input id="s-ltok" value="${al.line_channel_access_token || ''}"></div><div class="form-group"><label data-i18n="gui_line_target_id">LINE Target ID</label><input id="s-ltgt" value="${al.line_target_id || ''}"></div></div>
  <div class="form-group"><label data-i18n="gui_webhook_url">Webhook URL</label><input id="s-whurl" value="${al.webhook_url || ''}"></div>
  <div class="chk" style="margin-top:12px"><label><input type="checkbox" id="s-hc" ${st.enable_health_check !== false ? 'checked' : ''}> <span data-i18n="gui_enable_hc">Enable PCE Health Check</span></label></div>
</fieldset>
<fieldset><legend data-i18n="gui_lang_settings">Display & General</legend>
  <div class="form-row">
    <div class="form-group">
      <label data-i18n="gui_timezone">Timezone</label>
      <select id="s-timezone" style="width:100%; padding:8px; border-radius:var(--radius); background:var(--bg3); border:1px solid var(--border); color:var(--fg);">
        <option value="local" ${st.timezone === 'local' || !st.timezone ? 'selected' : ''}>Local Browser Time</option>
        <option value="UTC" ${st.timezone === 'UTC' ? 'selected' : ''}>UTC</option>
        <option value="UTC-12" ${st.timezone === 'UTC-12' ? 'selected' : ''}>UTC-12</option>
        <option value="UTC-11" ${st.timezone === 'UTC-11' ? 'selected' : ''}>UTC-11</option>
        <option value="UTC-10" ${st.timezone === 'UTC-10' ? 'selected' : ''}>UTC-10</option>
        <option value="UTC-9" ${st.timezone === 'UTC-9' ? 'selected' : ''}>UTC-9</option>
        <option value="UTC-8" ${st.timezone === 'UTC-8' ? 'selected' : ''}>UTC-8</option>
        <option value="UTC-7" ${st.timezone === 'UTC-7' ? 'selected' : ''}>UTC-7</option>
        <option value="UTC-6" ${st.timezone === 'UTC-6' ? 'selected' : ''}>UTC-6</option>
        <option value="UTC-5" ${st.timezone === 'UTC-5' ? 'selected' : ''}>UTC-5</option>
        <option value="UTC-4" ${st.timezone === 'UTC-4' ? 'selected' : ''}>UTC-4</option>
        <option value="UTC-3" ${st.timezone === 'UTC-3' ? 'selected' : ''}>UTC-3</option>
        <option value="UTC-2" ${st.timezone === 'UTC-2' ? 'selected' : ''}>UTC-2</option>
        <option value="UTC-1" ${st.timezone === 'UTC-1' ? 'selected' : ''}>UTC-1</option>
        <option value="UTC+1" ${st.timezone === 'UTC+1' ? 'selected' : ''}>UTC+1</option>
        <option value="UTC+2" ${st.timezone === 'UTC+2' ? 'selected' : ''}>UTC+2</option>
        <option value="UTC+3" ${st.timezone === 'UTC+3' ? 'selected' : ''}>UTC+3</option>
        <option value="UTC+4" ${st.timezone === 'UTC+4' ? 'selected' : ''}>UTC+4</option>
        <option value="UTC+5" ${st.timezone === 'UTC+5' ? 'selected' : ''}>UTC+5</option>
        <option value="UTC+5.5" ${st.timezone === 'UTC+5.5' ? 'selected' : ''}>UTC+5.5</option>
        <option value="UTC+6" ${st.timezone === 'UTC+6' ? 'selected' : ''}>UTC+6</option>
        <option value="UTC+7" ${st.timezone === 'UTC+7' ? 'selected' : ''}>UTC+7</option>
        <option value="UTC+8" ${st.timezone === 'UTC+8' ? 'selected' : ''}>UTC+8</option>
        <option value="UTC+9" ${st.timezone === 'UTC+9' ? 'selected' : ''}>UTC+9</option>
        <option value="UTC+9.5" ${st.timezone === 'UTC+9.5' ? 'selected' : ''}>UTC+9.5</option>
        <option value="UTC+10" ${st.timezone === 'UTC+10' ? 'selected' : ''}>UTC+10</option>
        <option value="UTC+11" ${st.timezone === 'UTC+11' ? 'selected' : ''}>UTC+11</option>
        <option value="UTC+12" ${st.timezone === 'UTC+12' ? 'selected' : ''}>UTC+12</option>
        <option value="UTC+13" ${st.timezone === 'UTC+13' ? 'selected' : ''}>UTC+13</option>
        <option value="UTC+14" ${st.timezone === 'UTC+14' ? 'selected' : ''}>UTC+14</option>
      </select>
    </div>

    <div class="form-group">
      <label data-i18n="gui_language">Language</label>
      <div class="radio-group">
        <label><input type="radio" name="s-lang" value="en" ${st.language !== 'zh_TW' ? 'checked' : ''}> <span data-i18n="gui_lang_en">English</span></label>
        <label><input type="radio" name="s-lang" value="zh_TW" ${st.language === 'zh_TW' ? 'checked' : ''}> <span data-i18n="gui_lang_zh">繁體中文</span></label>
      </div>
    </div>
    <div class="form-group">
      <label>Theme</label>
      <div class="radio-group">
        <label><input type="radio" name="s-theme" value="dark" ${st.theme !== 'light' ? 'checked' : ''}> <span data-i18n="gui_theme_dark">Dark Theme</span></label>
        <label><input type="radio" name="s-theme" value="light" ${st.theme === 'light' ? 'checked' : ''}> <span data-i18n="gui_theme_light">Light Theme</span></label>
      </div>
    </div>
  </div>
</fieldset>
<fieldset><legend data-i18n="gui_report_output">Report Output</legend>
  <div class="form-row">
    <div class="form-group" style="flex:2">
      <label data-i18n="gui_report_output_dir">Output Directory</label>
      <input id="s-rpt-dir" value="${rpt.output_dir || 'reports/'}">
      <small style="color:var(--dim)" data-i18n="gui_report_output_dir_hint">Path where generated reports are saved (relative to project root or absolute).</small>
    </div>
    <div class="form-group" style="flex:1">
      <label data-i18n="gui_retention_days">Retention (days)</label>
      <input id="s-rpt-retention" type="number" min="0" value="${rpt.retention_days ?? 30}">
      <small style="color:var(--dim)" data-i18n="gui_retention_hint">0 = keep forever</small>
    </div>
  </div>
</fieldset>
<fieldset><legend data-i18n="gui_web_security">Web GUI Security</legend>
  <div class="form-row">
    <div class="form-group"><label data-i18n="gui_username">Username</label><input id="s-sec-user" value="${sec.username || 'admin'}"></div>
    <div class="form-group"><label data-i18n="gui_allowed_ips">Allowed IPs (comma separated IP or CIDR)</label><input id="s-sec-ips" value="${(sec.allowed_ips || []).join(', ')}" placeholder="e.g. 192.168.1.100, 10.0.0.0/8"></div>
  </div>
  <p style="color:var(--dim); font-size:0.85em; margin-bottom:12px;" data-i18n="gui_leave_blank_pass">Leave passwords blank to keep current password.</p>
  <div class="form-row">
    <div class="form-group"><label data-i18n="gui_old_password">Old Password</label><input id="s-sec-oldpass" type="password"></div>
    <div class="form-group"><label data-i18n="gui_new_password">New Password</label><input id="s-sec-newpass" type="password"></div>
  </div>
</fieldset>`;
  // Auto-detect browser timezone and pre-select if currently set to 'local'
  const tzSel = $('s-timezone');
  if (tzSel && (tzSel.value === 'local' || !tzSel.value)) {
    const detected = _detectBrowserTimezone();
    const opt = Array.from(tzSel.options).find(o => o.value === detected);
    if (opt) tzSel.value = detected;
  }
  await loadTranslations();
}
async function saveSettings() {
  const active = []; if ($('s-amail').checked) active.push('mail'); if ($('s-aline').checked) active.push('line'); if ($('s-awh').checked) active.push('webhook');
  const theme = rv('s-theme');
  const lang = rv('s-lang');
  applyThemeMode(getStoredThemeMode());
  await post('/api/settings', {
    api: { url: $('s-url').value, org_id: $('s-org').value, key: $('s-key').value, secret: $('s-sec').value, verify_ssl: $('s-ssl').checked },
    email: { sender: $('s-sender').value, recipients: $('s-rcpt').value.split(',').map(s => s.trim()).filter(Boolean) },
    smtp: { host: $('s-smhost').value, port: parseInt($('s-smport').value) || 25, user: $('s-smuser').value, password: $('s-smpass').value, enable_tls: $('s-tls').checked, enable_auth: $('s-auth').checked },
    alerts: { active, line_channel_access_token: $('s-ltok').value, line_target_id: $('s-ltgt').value, webhook_url: $('s-whurl').value },
    settings: { language: lang, theme: theme, timezone: $('s-timezone').value, enable_health_check: $('s-hc').checked },
    report: { output_dir: $('s-rpt-dir').value.trim(), retention_days: parseInt($('s-rpt-retention').value) || 0 }
  });

  const ips_raw = $('s-sec-ips').value.split(',').map(s => s.trim()).filter(Boolean);
  await post('/api/security', {
    username: $('s-sec-user').value.trim(),
    old_password: $('s-sec-oldpass').value,
    new_password: $('s-sec-newpass').value,
    allowed_ips: ips_raw
  });

  // Clear password fields after save
  $('s-sec-oldpass').value = '';
  $('s-sec-newpass').value = '';
  await loadTranslations();
  if (typeof renderQtPage === 'function') renderQtPage();
  if (typeof renderQwPage === 'function') renderQwPage();
  if (typeof renderDashboardQueries === 'function') renderDashboardQueries();
  toast(_translations['gui_msg_settings_saved'] || 'Settings saved');
}

/* ─── PCE Profile Management ──────────────────────────────────────── */
async function addPceProfile() {
  const name = ($('s-pce-name') || {}).value?.trim();
  const url  = ($('s-pce-url')  || {}).value?.trim();
  if (!name || !url) { toast(_translations['gui_msg_name_required'] || 'Name and URL required', 'err'); return; }
  const data = {
    action: 'add', name, url,
    org_id:     ($('s-pce-org')    || {}).value?.trim() || '1',
    key:        ($('s-pce-key')    || {}).value || '',
    secret:     ($('s-pce-secret') || {}).value || '',
    verify_ssl: ($('s-pce-ssl')    || {}).checked !== false,
  };
  const r = await post('/api/pce-profiles', data);
  if (r && r.ok) { toast(_translations['gui_pce_add'] || 'PCE profile added'); await loadSettings(); }
}

async function activatePceProfile(id) {
  const r = await post('/api/pce-profiles', { action: 'activate', id });
  if (r && r.ok) {
    const name = (_settings.pce_profiles || []).find(p => p.id === id)?.name || '';
    toast((_translations['gui_pce_switched'] || 'Switched to {name}').replace('{name}', name));
    await loadSettings();
  }
}

async function deletePceProfile(id) {
  if (!confirm(_translations['gui_msg_confirm_delete'] || 'Delete this profile?')) return;
  const r = await post('/api/pce-profiles', { action: 'delete', id });
  if (r && r.ok) { toast(_translations['gui_pce_delete_profile'] || 'Deleted'); await loadSettings(); }
}
