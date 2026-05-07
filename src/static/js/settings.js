/* ─── Settings ────────────────────────────────────────────────────── */
let _settings = {};
let _security = {};
let _alertPlugins = {};

function _pluginInputId(pluginName, key) {
  return `s-plugin-${pluginName}-${String(key).replace(/[^a-zA-Z0-9]+/g, '-')}`;
}

function _pluginFieldMeta(pluginName, key) {
  const plugin = _alertPlugins[pluginName] || {};
  return (plugin.fields || []).find(item => item.key === key) || null;
}

function _getNestedValue(source, path) {
  return (path || []).reduce((acc, part) => (acc && acc[part] !== undefined ? acc[part] : undefined), source);
}

function _setNestedValue(target, path, value) {
  let cursor = target;
  for (let i = 0; i < path.length - 1; i += 1) {
    const part = path[i];
    if (!cursor[part] || typeof cursor[part] !== 'object') cursor[part] = {};
    cursor = cursor[part];
  }
  cursor[path[path.length - 1]] = value;
}

function _pluginFieldBinding(pluginName, key) {
  const field = _pluginFieldMeta(pluginName, key);
  return Array.isArray(field?.config_path) ? field.config_path : null;
}

function _pluginFieldValueType(field) {
  if (!field) return 'string';
  if (field.value_type) return field.value_type;
  if (field.input_type === 'checkbox') return 'boolean';
  if (field.input_type === 'number') return 'integer';
  if (field.input_type === 'list') return 'string_list';
  return 'string';
}

function _pluginFieldValue(pluginName, key, settings) {
  const field = _pluginFieldMeta(pluginName, key);
  const binding = _pluginFieldBinding(pluginName, key);
  if (!binding) return '';
  const value = _getNestedValue(settings, binding);
  const valueType = _pluginFieldValueType(field);
  if (valueType === 'string_list') {
    const delimiter = field?.list_delimiter || ',';
    return Array.isArray(value) ? value.join(`${delimiter} `) : (value ?? '');
  }
  if (valueType === 'boolean') return !!value;
  return value ?? '';
}

function _renderPluginField(pluginName, field, settings) {
  const inputId = _pluginInputId(pluginName, field.key);
  const currentValue = _pluginFieldValue(pluginName, field.key, settings);
  const inputType = field.input_type || (field.secret ? 'password' : 'text');
  const helpHtml = field.help ? `<div style="color:var(--dim);font-size:0.82em;margin-top:6px;line-height:1.5;">${escapeHtml(field.help)}</div>` : '';
  const requiredBadge = field.required ? '<span style="color:var(--danger);font-size:0.78em;margin-left:6px;">required</span>' : '';

  if (inputType === 'checkbox') {
    return `
      <div class="chk" style="margin-top:8px;">
        <label>
          <input type="checkbox" id="${inputId}" ${currentValue ? 'checked' : ''}>
          <span>${escapeHtml(field.label || field.key)}</span>${requiredBadge}
        </label>
        ${helpHtml}
      </div>
    `;
  }

  if (inputType === 'list') {
    return `
      <div class="form-group">
        <label>${escapeHtml(field.label || field.key)}${requiredBadge}</label>
        <textarea
          id="${inputId}"
          rows="2"
          placeholder="${escapeHtml(field.placeholder || '')}"
        >${escapeHtml(String(currentValue ?? ''))}</textarea>
        ${helpHtml}
      </div>
    `;
  }

  const htmlType = field.secret ? 'password' : (inputType === 'number' ? 'number' : 'text');
  return `
    <div class="form-group">
      <label>${escapeHtml(field.label || field.key)}${requiredBadge}</label>
      <input
        id="${inputId}"
        type="${htmlType}"
        value="${escapeHtml(String(currentValue ?? ''))}"
        placeholder="${escapeHtml(field.placeholder || '')}"
      >
      ${helpHtml}
    </div>
  `;
}

function _renderAlertPluginCards(active, settings) {
  return Object.entries(_alertPlugins).map(([pluginName, plugin]) => {
    const fields = plugin.fields || [];
    const rows = [];
    for (let i = 0; i < fields.length; i += 2) {
      rows.push(`
        <div class="form-row">
          ${_renderPluginField(pluginName, fields[i], settings)}
          ${fields[i + 1] ? _renderPluginField(pluginName, fields[i + 1], settings) : '<div class="form-group"></div>'}
        </div>
      `);
    }
    return `
      <div class="card" style="margin-top:10px; padding:16px 18px;">
        <div style="display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:10px;">
          <div>
            <div style="font-weight:800; color:var(--fg);">${escapeHtml(plugin.display_name || plugin.name || pluginName)}</div>
            <div style="color:var(--dim); font-size:0.88em; line-height:1.6; margin-top:4px;">${escapeHtml(plugin.description || '')}</div>
          </div>
          <div class="chk" style="margin:0;">
            <label>
              <input type="checkbox" id="s-plugin-enabled-${pluginName}" ${active.includes(pluginName) ? 'checked' : ''}>
              <span>Enabled</span>
            </label>
          </div>
        </div>
        ${rows.join('')}
      </div>
    `;
  }).join('');
}

function _collectAlertPluginConfig() {
  const payload = { active: [], email: {}, smtp: {}, alerts: {} };
  Object.entries(_alertPlugins).forEach(([pluginName, plugin]) => {
    if ($(`s-plugin-enabled-${pluginName}`)?.checked) payload.active.push(pluginName);
    (plugin.fields || []).forEach(field => {
      const input = $(_pluginInputId(pluginName, field.key));
      if (!input) return;
      const binding = _pluginFieldBinding(pluginName, field.key);
      if (!binding) return;
      const valueType = _pluginFieldValueType(field);
      let value;
      if (valueType === 'boolean') {
        value = !!input.checked;
      } else if (valueType === 'integer') {
        const parsed = parseInt(input.value, 10);
        value = Number.isFinite(parsed) ? parsed : null;
      } else if (valueType === 'number') {
        const parsed = Number(input.value);
        value = Number.isFinite(parsed) ? parsed : null;
      } else if (valueType === 'string_list') {
        const delimiter = field.list_delimiter || ',';
        value = String(input.value || '').split(delimiter).map(s => s.trim()).filter(Boolean);
      } else {
        value = input.value;
      }
      _setNestedValue(payload, binding, value);
    });
  });
  return payload;
}

let _tlsStatus = {};

async function loadSettings() {
  _settings = await api('/api/settings');
  try { _security = await api('/api/security'); } catch (e) { _security = {}; }
  try { _alertPlugins = (await api('/api/alert-plugins')).plugins || {}; } catch (e) { _alertPlugins = {}; }
  try { _tlsStatus = await api('/api/tls/status'); } catch (e) { _tlsStatus = {}; }

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
<fieldset><legend data-i18n="gui_alert_channels">Alert Channels</legend>
  ${_renderAlertPluginCards(active, s)}
</fieldset>
<fieldset><legend data-i18n="gui_lang_settings">Display & General</legend>
  <div class="form-row">
    <div class="form-group">
      <label data-i18n="gui_timezone">Timezone</label>
      <select id="s-timezone" style="width:100%; padding:8px; border-radius:var(--radius); background:var(--bg3); border:1px solid var(--border); color:var(--fg);">
        <option value="local" ${st.timezone === 'local' || !st.timezone ? 'selected' : ''}>${_t('gui_local_browser_time')}</option>
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
<fieldset><legend data-i18n="gui_tls_title">TLS / HTTPS</legend>
  <div class="chk" style="margin-bottom:10px"><label><input type="checkbox" id="s-tls-enabled" ${_tlsStatus.enabled ? 'checked' : ''}> <span data-i18n="gui_tls_enable">Enable HTTPS</span></label></div>
  <div id="s-tls-options" style="display:${_tlsStatus.enabled ? 'block' : 'none'}">
    <div class="chk" style="margin-bottom:10px"><label><input type="checkbox" id="s-tls-selfsigned" ${_tlsStatus.self_signed ? 'checked' : ''} onchange="toggleTlsMode()"> <span data-i18n="gui_tls_self_signed">Use self-signed certificate</span></label></div>
    <div id="s-tls-custom" style="display:${_tlsStatus.self_signed ? 'none' : 'block'}">
      <div class="form-row">
        <div class="form-group"><label data-i18n="gui_tls_cert_file">Certificate File Path</label><input id="s-tls-cert" value="${escapeHtml(_tlsStatus.cert_file || '')}" placeholder="/path/to/cert.pem"></div>
        <div class="form-group"><label data-i18n="gui_tls_key_file">Private Key File Path</label><input id="s-tls-key" value="${escapeHtml(_tlsStatus.key_file || '')}" placeholder="/path/to/key.pem"></div>
      </div>
    </div>
    <div id="s-tls-auto-renew-row" style="display:${_tlsStatus.self_signed ? 'block' : 'none'};margin-top:6px;">
      <div class="chk" style="margin-bottom:6px"><label><input type="checkbox" id="s-tls-auto-renew" ${_tlsStatus.auto_renew !== false ? 'checked' : ''}> <span data-i18n="gui_tls_auto_renew">Auto-renew on startup before expiry</span></label></div>
      <div class="form-row" style="align-items:center;gap:8px;">
        <div class="form-group" style="flex:0 0 auto;max-width:180px;">
          <label data-i18n="gui_tls_auto_renew_days">Renew when days left ≤</label>
          <input id="s-tls-auto-renew-days" type="number" min="1" max="365" value="${_tlsStatus.auto_renew_days ?? 30}">
        </div>
        <small style="color:var(--dim)" data-i18n="gui_tls_auto_renew_hint">Self-signed certs default to 5 years; auto-renew regenerates them when they get close to expiring.</small>
      </div>
    </div>
    <div id="s-tls-cert-info"></div>
  </div>
</fieldset>
<fieldset><legend data-i18n="gui_web_security">Web GUI Security</legend>
  <div class="form-row">
    <div class="form-group"><label data-i18n="gui_username">Username</label><input id="s-sec-user" value="${sec.username || 'admin'}"></div>
    <div class="form-group"><label data-i18n="gui_allowed_ips">Allowed IPs (comma separated IP or CIDR)</label><input id="s-sec-ips" value="${(sec.allowed_ips || []).join(', ')}" placeholder="e.g. 192.168.1.100, 10.0.0.0/8"></div>
  </div>
  <p style="color:var(--dim); font-size:0.85em; margin-bottom:12px;" data-i18n="gui_leave_blank_pass">Leave password blank to keep current password.</p>
  <div class="form-row">
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

  // TLS toggle logic
  const tlsEn = $('s-tls-enabled');
  if (tlsEn) tlsEn.addEventListener('change', () => {
    const opts = $('s-tls-options');
    if (opts) opts.style.display = tlsEn.checked ? 'block' : 'none';
  });

  // Render cert info if available
  _renderTlsCertInfo();
}

function toggleTlsMode() {
  const selfSigned = $('s-tls-selfsigned');
  const custom = $('s-tls-custom');
  const autoRenewRow = $('s-tls-auto-renew-row');
  const isSelfSigned = !!(selfSigned && selfSigned.checked);
  if (custom) custom.style.display = isSelfSigned ? 'none' : 'block';
  // Auto-renew only applies to self-signed certs we control.
  if (autoRenewRow) autoRenewRow.style.display = isSelfSigned ? 'block' : 'none';
}

function _renderTlsCertInfo() {
  const el = $('s-tls-cert-info');
  if (!el) return;
  const info = _tlsStatus.cert_info;
  if (!info || !info.exists) {
    el.innerHTML = _tlsStatus.enabled
      ? '<p style="color:var(--dim);font-size:0.88em;margin-top:8px;">' + (_t('gui_tls_no_cert')) + '</p>'
      : '';
    return;
  }
  const expiredBadge = info.expired
    ? `<span style="color:var(--danger);font-weight:600;margin-left:8px;">${_t('gui_tls_expired')}</span>`
    : (info.expiring_soon ? `<span style="color:var(--warn, orange);font-weight:600;margin-left:8px;">${_t('gui_tls_expiring_soon')}</span>` : '');
  const days = _tlsStatus.days_remaining;
  // Show days-remaining row when openssl was able to read expiry; omit
  // otherwise so we don't show a misleading "0" for missing info.
  const daysRow = (typeof days === 'number')
    ? `<div><strong data-i18n="gui_tls_days_remaining">Days Remaining</strong>: ${days}</div>`
    : '';
  const renewBtn = _tlsStatus.self_signed
    ? `<button class="btn btn-primary btn-sm" style="margin-top:10px" onclick="renewTlsCert()" data-i18n="gui_tls_renew">Renew Now</button>`
    : '';
  el.innerHTML = `
    <div class="card" style="margin-top:10px;padding:14px 18px;">
      <div style="font-weight:700;margin-bottom:6px;" data-i18n="gui_tls_cert_info">Certificate Info</div>
      <div style="font-size:0.88em;color:var(--dim);line-height:1.8;">
        <div><strong>Subject:</strong> ${escapeHtml(info.subject || '-')}</div>
        <div><strong data-i18n="gui_tls_valid_from">Valid From</strong>: ${escapeHtml(info.not_before || '-')}</div>
        <div><strong data-i18n="gui_tls_valid_until">Valid Until</strong>: ${escapeHtml(info.not_after || '-')}${expiredBadge}</div>
        ${daysRow}
      </div>
      ${renewBtn}
    </div>`;
}

async function renewTlsCert() {
  if (!confirm(_t('gui_tls_renew_confirm'))) return;
  try {
    const r = await post('/api/tls/renew', {});
    if (r && r.ok) {
      toast(_t('gui_tls_renewed'));
      _tlsStatus.cert_info = r.cert_info;
      _renderTlsCertInfo();
    } else {
      toast(r?.error || _t('gui_tls_renew_failed'), 'err');
    }
  } catch (e) {
    toast(_t('gui_tls_renew_failed_detail').replace('{error}', e.message), 'err');
  }
}

async function saveSettings() {
  const pluginConfig = _collectAlertPluginConfig();
  const theme = rv('s-theme');
  const lang = rv('s-lang');
  applyThemeMode(getStoredThemeMode());
  const settingsPayload = {
    api: { url: $('s-url').value, org_id: $('s-org').value, key: $('s-key').value, secret: $('s-sec').value, verify_ssl: $('s-ssl').checked },
    settings: { language: lang, theme: theme, timezone: $('s-timezone').value },
    report: { output_dir: $('s-rpt-dir').value.trim(), retention_days: parseInt($('s-rpt-retention').value) || 0 }
  };
  Object.entries(pluginConfig).forEach(([key, value]) => {
    if (key === 'active') return;
    settingsPayload[key] = value;
  });
  settingsPayload.alerts = { ...(settingsPayload.alerts || {}), active: pluginConfig.active };
  await post('/api/settings', settingsPayload);

  const ips_raw = $('s-sec-ips').value.split(',').map(s => s.trim()).filter(Boolean);
  await post('/api/security', {
    username: $('s-sec-user').value.trim(),
    new_password: $('s-sec-newpass').value,
    allowed_ips: ips_raw
  });

  // Save TLS settings
  const tlsEnabled = $('s-tls-enabled')?.checked || false;
  const tlsSelfSigned = $('s-tls-selfsigned')?.checked || false;
  // auto_renew defaults to true; only treat an explicit uncheck as opt-out.
  const autoRenewEl = $('s-tls-auto-renew');
  const autoRenew = autoRenewEl ? autoRenewEl.checked : true;
  const autoRenewDays = parseInt($('s-tls-auto-renew-days')?.value, 10) || 30;
  await post('/api/tls/config', {
    enabled: tlsEnabled,
    self_signed: tlsSelfSigned,
    cert_file: $('s-tls-cert')?.value?.trim() || '',
    key_file: $('s-tls-key')?.value?.trim() || '',
    auto_renew: autoRenew,
    auto_renew_days: autoRenewDays,
  });

  // Clear password field after save
  $('s-sec-newpass').value = '';
  await loadTranslations();
  if (typeof renderQtPage === 'function') renderQtPage();
  if (typeof renderQwPage === 'function') renderQwPage();
  if (typeof renderDashboardQueries === 'function') renderDashboardQueries();
  toast(_t('gui_msg_settings_saved'));
}

/* ─── PCE Profile Management ──────────────────────────────────────── */
async function addPceProfile() {
  const name = ($('s-pce-name') || {}).value?.trim();
  const urlInput = $('s-pce-url');
  const url  = (urlInput || {}).value?.trim();
  if (!name || !url) { toast(_t('gui_msg_name_required'), 'err'); return; }
  if (urlInput && !/^https?:\/\//.test(url)) {
    setFieldError(urlInput, _t('error_invalid_url') || 'URL must start with http:// or https://');
    return;
  }
  if (urlInput) clearFieldError(urlInput);
  const data = {
    action: 'add', name, url,
    org_id:     ($('s-pce-org')    || {}).value?.trim() || '1',
    key:        ($('s-pce-key')    || {}).value || '',
    secret:     ($('s-pce-secret') || {}).value || '',
    verify_ssl: ($('s-pce-ssl')    || {}).checked !== false,
  };
  const r = await post('/api/pce-profiles', data);
  if (r && r.ok) { toast(_t('gui_pce_add')); await loadSettings(); }
}

async function activatePceProfile(id) {
  const r = await post('/api/pce-profiles', { action: 'activate', id });
  if (r && r.ok) {
    const name = (_settings.pce_profiles || []).find(p => p.id === id)?.name || '';
    toast((_t('gui_pce_switched')).replace('{name}', name));
    await loadSettings();
  }
}

async function deletePceProfile(id) {
  if (!confirm(_t('gui_msg_confirm_delete'))) return;
  const r = await post('/api/pce-profiles', { action: 'delete', id });
  if (r && r.ok) { toast(_t('gui_pce_delete_profile')); await loadSettings(); }
}
