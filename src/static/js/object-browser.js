'use strict';
/* Modal 物件庫（案 C 深挖入口）：類別分頁 + 搜尋 + 分頁表格 + 勾選多選。
 * 開啟：window.openObjectBrowser(fbId)（filter-bar 下拉底部入口）。
 * 資料：空搜尋走 /api/filter-objects/browse 分頁；有字走 suggest（limit 25）。
 * 加入：勾選項以 _objfbAddPill 逐一加為 pill（service 無方向）。CSP：無 inline。
 */
const _ob = {
  fbId: null, cat: null, q: '', offset: 0, limit: 20,
  items: [], total: 0, selected: {}, zone: null,
};

const _OB_PAGE_TYPES = ['label', 'label_group', 'iplist', 'workload', 'service'];

// 目標欄位顯示 key（v2 zone 模型：方向/排除由開啟瀏覽器的欄位決定，視窗內不再二次選擇）
const _OB_ZONE_I18N = {
  'src:false': 'gui_fb_dir_src', 'dst:false': 'gui_fb_dir_dst',
  'any:false': 'gui_fb_col_any', 'svc:false': 'gui_fb_col_svc',
  'src:true': 'gui_fb_col_src_not', 'dst:true': 'gui_fb_col_dst_not',
  'any:true': 'gui_fb_col_any_not', 'svc:true': 'gui_fb_col_svc_not',
};

window.openObjectBrowser = function (fbId) {
  const fb = window._objfbGetInstance ? window._objfbGetInstance(fbId) : null;
  if (!fb) return;
  _ob.fbId = fbId;
  _ob.zone = fb.addZone || { col: fb.addDir || 'src', neg: false };
  // any（OR 合併欄）不支援 label_group（序列化 fail-closed 丟棄），分頁一併隱藏
  _ob.cats = _OB_PAGE_TYPES.filter(c => fb.cats.includes(c) &&
    !(c === 'label_group' && _ob.zone.col === 'any'));
  _ob.cat = fb.scopeCat && _ob.cats.includes(fb.scopeCat) ? fb.scopeCat : _ob.cats[0];
  _ob.q = '';
  _ob.offset = 0;
  _ob.selected = {};
  document.getElementById('modal-obj-browser').classList.add('show');
  _obRender();
  _obFetch();
};

function _obFetch() {
  const cat = _ob.cat;
  if (cat === 'workload' && !_ob.q) {
    _ob.items = []; _ob.total = 0;
    _obRenderTable('gui_fb_type_to_search');
    return;
  }
  const url = _ob.q
    ? `/api/filter-objects/suggest?q=${encodeURIComponent(_ob.q)}&types=${cat}&limit=25`
    : `/api/filter-objects/browse?type=${cat}&offset=${_ob.offset}&limit=${_ob.limit}`;
  fetch(url, { credentials: 'same-origin' })
    .then(r => r.json())
    .then(body => {
      if (_ob.q) {
        const r_ = (body.results || {})[cat] || {};
        _ob.items = r_.items || []; _ob.total = _ob.items.length;
      } else {
        _ob.items = body.items || []; _ob.total = body.total || 0;
      }
      _obRenderTable(null);
    })
    .catch(() => _obRenderTable('gui_fb_browse_error'));
}

function _obRender() {
  const body = document.getElementById('ob-body');
  body.innerHTML = '';
  // 類別分頁
  const tabs = document.createElement('div');
  tabs.className = 'ob-tabs';
  for (const c of _ob.cats) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'ob-tab' + (c === _ob.cat ? ' on' : '');
    b.setAttribute('data-i18n', 'gui_fb_cat_' + c);
    b.textContent = c;
    b.setAttribute('data-on-click', '_obSetCat');
    b.dataset.args = JSON.stringify([c]);
    tabs.appendChild(b);
  }
  body.appendChild(tabs);
  // 搜尋框
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.id = 'ob-search';
  inp.className = 'ob-search';
  inp.autocomplete = 'off';
  inp.setAttribute('data-i18n-placeholder', 'gui_ob_search_ph');
  inp.setAttribute('data-on-input', '_obSearchInput');
  body.appendChild(inp);
  // 表格容器 + 分頁列 + 方向列
  const tbl = document.createElement('div');
  tbl.id = 'ob-table';
  body.appendChild(tbl);
  const foot = document.createElement('div');
  foot.id = 'ob-foot';
  foot.className = 'ob-foot';
  body.appendChild(foot);
  if (typeof window.i18nApply === 'function') window.i18nApply(body);
}

function _obRenderTable(noteKey) {
  const tbl = document.getElementById('ob-table');
  tbl.innerHTML = '';
  if (noteKey) {
    const n = document.createElement('div');
    n.className = 'objfb-dd-note';
    n.setAttribute('data-i18n', noteKey);
    tbl.appendChild(n);
  } else {
    for (const it of _ob.items) {
      const row = document.createElement('label');
      row.className = 'ob-row';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      const key = it.href || it.name;
      cb.checked = !!_ob.selected[key];
      cb.setAttribute('data-on-change', '_obToggle');
      cb.dataset.args = JSON.stringify([key, it]);
      row.appendChild(cb);
      const txt = document.createElement('span');
      txt.className = 'ob-row-txt';
      txt.textContent = it.summary ? `${it.name} — ${it.summary}` : it.name;
      row.appendChild(txt);
      tbl.appendChild(row);
    }
  }
  _obRenderFoot();
  if (typeof window.i18nApply === 'function') window.i18nApply(tbl);
}

function _obRenderFoot() {
  const foot = document.getElementById('ob-foot');
  foot.innerHTML = '';
  // 分頁（僅 browse 模式）
  if (!_ob.q && _ob.total > _ob.limit) {
    const pager = document.createElement('span');
    pager.className = 'ob-pager';
    const prev = document.createElement('button');
    prev.type = 'button'; prev.textContent = '‹';
    prev.disabled = _ob.offset <= 0;
    prev.setAttribute('data-on-click', '_obPage');
    prev.dataset.args = JSON.stringify([-1]);
    const next = document.createElement('button');
    next.type = 'button'; next.textContent = '›';
    next.disabled = _ob.offset + _ob.limit >= _ob.total;
    next.setAttribute('data-on-click', '_obPage');
    next.dataset.args = JSON.stringify([1]);
    const info = document.createElement('span');
    info.setAttribute('data-i18n', 'gui_ob_page');
    info.textContent = 'Page';
    const nums = document.createElement('span');
    nums.textContent = ` ${Math.floor(_ob.offset / _ob.limit) + 1} / ${Math.ceil(_ob.total / _ob.limit)}（${_ob.total}）`;
    pager.appendChild(prev); pager.appendChild(info); pager.appendChild(nums); pager.appendChild(next);
    foot.appendChild(pager);
  }
  // 已選數 + 目標欄位（方向/排除由開啟瀏覽器的欄位決定，不再於視窗內選擇；
  // service 家族 pill 無方向，一律歸 Service 欄）
  const right = document.createElement('span');
  right.className = 'ob-foot-right';
  const selCnt = document.createElement('span');
  selCnt.setAttribute('data-i18n', 'gui_ob_selected');
  selCnt.textContent = 'Selected';
  const selNum = document.createElement('span');
  selNum.textContent = ` ${Object.keys(_ob.selected).length}`;
  right.appendChild(selCnt); right.appendChild(selNum);
  const tgt = document.createElement('span');
  tgt.className = 'ob-dir-hint';
  const tgtPfx = document.createElement('span');
  tgtPfx.setAttribute('data-i18n', 'gui_ob_target');
  tgtPfx.textContent = 'Add to:';
  tgt.appendChild(tgtPfx);
  tgt.appendChild(document.createTextNode(' '));
  const zoneCol = _ob.cat === 'service' ? 'svc' : _ob.zone.col;
  const tgtZone = document.createElement('span');
  tgtZone.setAttribute('data-i18n', _OB_ZONE_I18N[`${zoneCol}:${_ob.zone.neg}`] || 'gui_fb_dir_src');
  tgt.appendChild(tgtZone);
  right.appendChild(tgt);
  foot.appendChild(right);
  if (typeof window.i18nApply === 'function') window.i18nApply(foot);
}

window._obSetCat = function (c) { _ob.cat = c; _ob.q = ''; _ob.offset = 0; _ob.selected = {}; _obRender(); _obFetch(); };
window._obPage = function (delta) { _ob.offset = Math.max(0, _ob.offset + delta * _ob.limit); _obFetch(); };
window._obToggle = function (key, it) {
  if (_ob.selected[key]) delete _ob.selected[key];
  else _ob.selected[key] = it;
  _obRenderFoot();
};
window._obSearchInput = function () {
  const v = document.getElementById('ob-search').value.trim();
  _ob.q = v;
  _ob.offset = 0;
  if (!_ob._deb) _ob._deb = window.debounce(_obFetch, 250);
  _ob._deb();
};
window._obAddSelected = function () {
  const fb = window._objfbGetInstance ? window._objfbGetInstance(_ob.fbId) : null;
  if (fb) {
    // 目標欄位由 fb.addZone（開啟瀏覽器時的欄位）決定，_objfbAddPillPublic 直接讀取
    for (const it of Object.values(_ob.selected)) {
      window._objfbAddPillPublic(fb, Object.assign({ cat: _ob.cat }, it));
    }
  }
  closeModal('modal-obj-browser');
};
