let _eventViewerItems = [];
let _eventViewerSelectedId = null;
let _eventViewerOffset = 0;
let _eventViewerHasMore = false;
let _eventViewerCatalog = null;

function _evText(key) {
  return _t(key);
}

function _eventViewerGroupOf(eventType) {
  if (!eventType || eventType === '*') return '*';
  return String(eventType).split('.')[0];
}

function _humanizeEventViewerGroup(groupId) {
  if (!groupId || groupId === '*') return _evText('gui_ev_all_groups');
  const pretty = String(groupId)
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
  return `${pretty} (${groupId}.*)`;
}

function _eventViewerTypeOptionLabel(item) {
  if (!item) return '';
  if (item.id === '*') return item.label || _evText('gui_ev_all_event_types');
  if (item.label && item.label !== item.id) return `${item.label} · ${item.id}`;
  return item.id;
}

function _eventViewerFilteredCatalogItems() {
  const items = (_eventViewerCatalog?.items || []).filter((item) => item.id !== '*');
  const categoryId = $('ev-category')?.value || '';
  const groupId = $('ev-group')?.value || '';
  return items.filter((item) => {
    if (categoryId && item.category_id !== categoryId) return false;
    if (groupId && item.group_id !== groupId) return false;
    return true;
  });
}

function _populateEventViewerCategoryOptions() {
  const select = $('ev-category');
  if (!select || !_eventViewerCatalog) return;
  const previous = select.value || '';
  const options = [
    `<option value="">${escapeHtml(_evText('gui_ev_all_categories'))}</option>`,
    ...(_eventViewerCatalog.categories || []).map((category) =>
      `<option value="${escapeHtml(category.id)}"${category.id === previous ? ' selected' : ''}>${escapeHtml(category.label)}</option>`
    ),
  ];
  select.innerHTML = options.join('');
  if (![...select.options].some((option) => option.value === previous)) select.value = '';
}

function _populateEventViewerGroupOptions() {
  const select = $('ev-group');
  if (!select || !_eventViewerCatalog) return;
  const previous = select.value || '';
  const categoryId = $('ev-category')?.value || '';
  const groups = new Map();
  (_eventViewerCatalog.items || []).forEach((item) => {
    if (item.id === '*') return;
    if (categoryId && item.category_id !== categoryId) return;
    groups.set(item.group_id, item.group_label);
  });
  const sorted = [...groups.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  select.innerHTML = [
    `<option value="">${escapeHtml(_evText('gui_ev_all_groups'))}</option>`,
    ...sorted.map(([groupId, label]) => `<option value="${escapeHtml(groupId)}"${groupId === previous ? ' selected' : ''}>${escapeHtml(label)}</option>`),
  ].join('');
  if (![...select.options].some((option) => option.value === previous)) select.value = '';
}

function _populateEventViewerTypeOptions() {
  const select = $('ev-viewer-type');
  if (!select || !_eventViewerCatalog) return;
  const previous = select.value || '';
  const filtered = _eventViewerFilteredCatalogItems().sort((a, b) => a.label.localeCompare(b.label));
  select.innerHTML = [
    `<option value="">${escapeHtml(_evText('gui_ev_all_event_types'))}</option>`,
    ...filtered.map((item) =>
      `<option value="${escapeHtml(item.id)}"${item.id === previous ? ' selected' : ''}>${escapeHtml(_eventViewerTypeOptionLabel(item))}</option>`
    ),
  ].join('');
  if (![...select.options].some((option) => option.value === previous)) select.value = '';
}

async function ensureEventViewerCatalog() {
  if (_eventViewerCatalog) return _eventViewerCatalog;
  const response = await api('/api/event-catalog');
  const categories = response?.categories || [];
  const items = [];
  categories.forEach((category) => {
    (category.events || []).forEach((item) => {
      items.push({
        ...item,
        category_id: category.id,
        category_label: category.label,
        group_id: _eventViewerGroupOf(item.id),
        group_label: _humanizeEventViewerGroup(_eventViewerGroupOf(item.id)),
      });
    });
  });
  _eventViewerCatalog = { categories, items };
  _populateEventViewerCategoryOptions();
  _populateEventViewerGroupOptions();
  _populateEventViewerTypeOptions();
  return _eventViewerCatalog;
}

function onEventViewerCategoryChange() {
  _populateEventViewerGroupOptions();
  _populateEventViewerTypeOptions();
  loadEventViewer(true);
}

function onEventViewerGroupChange() {
  _populateEventViewerTypeOptions();
  loadEventViewer(true);
}

function _mergeEventViewerItems(existingItems, newItems) {
  const merged = [];
  const seen = new Set();
  [...(existingItems || []), ...(newItems || [])].forEach((item) => {
    const key = item?.event_id || `${item?.timestamp || ''}:${item?.event_type || ''}`;
    if (!key || seen.has(key)) return;
    seen.add(key);
    merged.push(item);
  });
  return merged;
}

function _evStatusTone(value) {
  const status = String(value || '').toLowerCase();
  if (status === 'success') return 'success';
  if (['failure', 'error', 'warn', 'warning'].includes(status)) return 'danger';
  return 'neutral';
}

function _evBadge(text, tone = 'neutral') {
  const tones = {
    success: 'background:rgba(22,102,68,.16);color:var(--success);border:1px solid rgba(22,102,68,.35);',
    danger: 'background:rgba(190,18,47,.12);color:var(--danger);border:1px solid rgba(190,18,47,.28);',
    neutral: 'background:var(--bg3);color:var(--fg);border:1px solid var(--border);',
  };
  return `<span class="ev-badge" style="${tones[tone] || tones.neutral}">${escapeHtml(text)}</span>`;
}

function _evCompactText(value, fallback = '-') {
  return value ? escapeHtml(String(value)) : fallback;
}

function _renderEventViewerDetails(item) {
  const normalizedEl = $('ev-normalized');
  const rawEl = $('ev-raw');
  if (!normalizedEl || !rawEl) return;
  if (!item) {
    normalizedEl.textContent = _evText('gui_ev_select_parsed');
    rawEl.textContent = _evText('gui_ev_select_raw');
    return;
  }
  normalizedEl.textContent = JSON.stringify(item.normalized || {}, null, 2);
  rawEl.textContent = JSON.stringify(item.raw || {}, null, 2);
}

function selectEventViewerRow(eventId) {
  _eventViewerSelectedId = eventId;
  document.querySelectorAll('#ev-body tr[data-event-id]').forEach((row) => {
    row.classList.toggle('is-selected', row.dataset.eventId === eventId);
  });
  const item = _eventViewerItems.find((entry) => entry.event_id === eventId);
  _renderEventViewerDetails(item || null);
}

function _renderEventViewerRows(items, append = false) {
  const tbody = $('ev-body');
  if (!tbody) return;

  if (!items.length && !append) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:36px;color:var(--dim);">${escapeHtml(_evText('gui_ev_no_match'))}</td></tr>`;
    _renderEventViewerDetails(null);
    return;
  }

  const rowsHtml = items.map((item) => {
    const normalized = item.normalized || {};
    return `
      <tr data-event-id="${escapeHtml(item.event_id)}" onclick="selectEventViewerRow('${escapeHtml(item.event_id)}')" style="cursor:pointer;">
        <td>${escapeHtml(formatDateZ(item.timestamp || ''))}</td>
        <td>
          <div style="font-weight:700;">${escapeHtml(item.event_type || '')}</div>
          <div style="font-size:11px;color:var(--dim);">${escapeHtml(normalized.resource_type || '')}${normalized.resource_name ? ' | ' + escapeHtml(normalized.resource_name) : ''}</div>
        </td>
        <td>${_evBadge(item.status || 'n/a', _evStatusTone(item.status))}</td>
        <td>${_evCompactText(normalized.actor)}</td>
        <td>${_evCompactText(normalized.target_name)}</td>
        <td>${_evCompactText(normalized.action)}</td>
      </tr>
    `;
  }).join('');

  if (append) {
    tbody.insertAdjacentHTML('beforeend', rowsHtml);
  } else {
    tbody.innerHTML = rowsHtml;
  }

  const preferred = _eventViewerSelectedId && _eventViewerItems.some((item) => item.event_id === _eventViewerSelectedId)
    ? _eventViewerSelectedId
    : _eventViewerItems[0]?.event_id;
  if (preferred) selectEventViewerRow(preferred);
}

function _setEventViewerMeta(summary) {
  const metaEl = $('ev-meta');
  if (!metaEl) return;
  const rangeText = `${_evText('gui_window')} ${formatDateZ(summary.query_since || '')} -> ${formatDateZ(summary.query_until || '')}`;
  const resultText = `${_evText('gui_ev_matched')} ${summary.matched_count ?? 0}, ${_evText('gui_ev_showing')} ${(_eventViewerOffset + (summary.returned_count ?? 0))}/${summary.matched_count ?? 0}`;
  metaEl.textContent = `${rangeText} | ${resultText}`;
}

function _setEventViewerLoadMore(hasMore) {
  _eventViewerHasMore = !!hasMore;
  ['ev-load-more-top', 'ev-load-more-bottom'].forEach((id) => {
    const button = $(id);
    if (!button) return;
    button.style.display = _eventViewerHasMore ? '' : 'none';
    button.disabled = !_eventViewerHasMore;
  });
}

function _eventViewerParams() {
  return new URLSearchParams({
    mins: $('ev-mins')?.value || '60',
    limit: $('ev-limit')?.value || '50',
    offset: String(_eventViewerOffset),
    search: $('ev-search')?.value || '',
    category: $('ev-category')?.value || '',
    type_group: $('ev-group')?.value || '',
    event_type: $('ev-viewer-type')?.value || '',
  });
}

async function loadEventViewer(reset = false) {
  try {
    await ensureEventViewerCatalog();
    if (reset) {
      _eventViewerOffset = 0;
      _eventViewerItems = [];
    }

    $('ev-meta').textContent = _evText('gui_ev_loading');

    const response = await api(`/api/events/viewer?${_eventViewerParams().toString()}`);
    if (!response || response.ok === false) {
      throw new Error(response?.error || _evText('gui_ev_unknown_error'));
    }

    const items = response.items || [];
    if (reset) {
      _eventViewerItems = _mergeEventViewerItems([], items);
    } else {
      _eventViewerItems = _mergeEventViewerItems(_eventViewerItems, items);
    }

    _renderEventViewerRows(reset ? _eventViewerItems : items, !reset);
    _setEventViewerMeta(response.summary || {});
    _setEventViewerLoadMore((response.summary || {}).has_more);
  } catch (error) {
    $('ev-meta').textContent = `${_evText('gui_ev_load_failed')}: ${error.message}`;
    if (reset) {
      $('ev-body').innerHTML = `<tr><td colspan="6" style="text-align:center;padding:36px;color:var(--danger);">${escapeHtml(_evText('gui_ev_failed_to_load'))}: ${escapeHtml(error.message)}</td></tr>`;
      _renderEventViewerDetails(null);
    }
    _setEventViewerLoadMore(false);
  }
}

async function loadMoreEventViewer() {
  if (!_eventViewerHasMore) return;
  _eventViewerOffset = _eventViewerItems.length;
  await loadEventViewer(false);
}
