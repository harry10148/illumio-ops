'use strict';
/* PCE 風格 filter 物件選擇器元件（Phase 3）。
 * 可重複實例化：createFilterBar(container, options) → { getFilters, setFilters, onChange, destroy }。
 * CSP：動態 pill/下拉用 data-action/data-on-* 委派（_event_dispatcher），handler 掛 window.*。
 * suggest 查詢（debounce 250ms + AbortController 取消舊請求 + 離線降級）見 _objfbQuerySuggest /
 * _objfbRenderDropdown；其餘為 pill 資料模型 + 序列化 + 生命週期。
 */

// 每個 FilterBar 實例存於此註冊表，供 window handler 依 container id 找回實例
const _objfbInstances = {};
let _objfbSeq = 0;

function _objfbIsIpLike(s) {
  const t = String(s).trim();
  return /^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/.test(t) &&
    t.split('/')[0].split('.').every(o => +o <= 255);
}

function createFilterBar(container, options) {
  const opts = options || {};
  const dirs = opts.dirs || ['src', 'dst', 'any'];
  const cats = opts.cats || ['label', 'label_group', 'iplist', 'workload', 'ip'];
  const id = 'objfb-' + (++_objfbSeq);
  const state = {
    id, container, dirs, cats,
    pills: [],          // {cat, name, href, key, value, dir, neg}
    addDir: dirs[0],
    scopeCat: null,
    changeCb: null,
    // 進行中 suggest fetch 的 AbortController
    _abort: null,
    // 最近一次 suggest 回應（依分類分組），或 {_error:true}
    _suggest: null,
    // _suggest 對應的查詢字串（供比對是否過期）
    _suggestQ: null,
  };
  state._debouncedSuggest = window.debounce((q) => _objfbQuerySuggest(state, q), 250);
  _objfbInstances[id] = state;
  container.dataset.objfbId = id;
  container.classList.add('objfb-bar');
  if (opts.initial) _objfbDeserialize(state, opts.initial);
  _objfbRender(state);
  return {
    getFilters: () => _objfbSerialize(state),
    setFilters: (dict) => { _objfbDeserialize(state, dict); _objfbRender(state); },
    onChange: (cb) => { state.changeCb = cb; },
    destroy: () => { delete _objfbInstances[id]; container.innerHTML = ''; },
  };
}

/* ── 序列化：pill → filter dict（對齊 Phase 1 native builder key）── */
function _objfbSerialize(state) {
  const out = {};
  const push = (k, v) => { (out[k] = out[k] || []).push(v); };
  const setScalar = (k, v) => { out[k] = v; };
  for (const p of state.pills) {
    const ex = p.neg ? 'ex_' : '';
    if (p.dir === 'any') {
      // any 方向：Phase 1 單值 key（多個同類取最後值）
      if (p.cat === 'label')         setScalar(`${ex}any_label`, p.name);
      else if (p.cat === 'iplist')   setScalar(`${ex}any_iplist`, p.href || p.name);
      else if (p.cat === 'workload') setScalar(`${ex}any_workload`, p.href);
      else if (p.cat === 'ip')       setScalar(`${ex}any_ip`, p.name);
      else if (p.cat === 'label_group') setScalar(`${ex}any_label`, p.name);
      continue;
    }
    const d = p.dir; // src | dst
    if (p.cat === 'label')            push(`${ex}${d}_labels`, p.name);
    else if (p.cat === 'label_group') push(`${ex}${d}_label_groups`, p.name);
    else if (p.cat === 'iplist')      push(`${ex}${d}_iplists`, p.href || p.name);
    else if (p.cat === 'workload')    push(`${ex}${d}_workloads`, p.href);
    else if (p.cat === 'ip')          push(ex ? `ex_${d}_ip` : `${d}_ip_in`, p.name);
  }
  return out;
}

/* ── 反序列化：filter dict → pill（供 setFilters 回填既有查詢定義）── */
function _objfbDeserialize(state, dict) {
  state.pills = [];
  const add = (cat, name, dir, neg, extra) =>
    state.pills.push(Object.assign({ cat, name, href: null, key: null, value: null, dir, neg }, extra || {}));
  const d = dict || {};
  const asList = (v) => Array.isArray(v) ? v : (v ? [v] : []);
  for (const dir of ['src', 'dst']) {
    for (const spec of asList(d[`${dir}_labels`]).concat(asList(d[`${dir}_label`]))) add('label', spec, dir, false);
    for (const spec of asList(d[`ex_${dir}_labels`]).concat(asList(d[`ex_${dir}_label`]))) add('label', spec, dir, true);
    // label_group：序列化端有送（{ex_}{dir}_label_groups），漏在這裡會使
    // 編輯回填時 label_group pill 靜默消失、再存檔即永久遺失
    for (const spec of asList(d[`${dir}_label_groups`])) add('label_group', spec, dir, false);
    for (const spec of asList(d[`ex_${dir}_label_groups`])) add('label_group', spec, dir, true);
    for (const h of asList(d[`${dir}_iplists`]).concat(asList(d[`${dir}_iplist`]))) add('iplist', h, dir, false, { href: h });
    for (const h of asList(d[`ex_${dir}_iplists`])) add('iplist', h, dir, true, { href: h });
    for (const h of asList(d[`${dir}_workloads`])) add('workload', h, dir, false, { href: h });
    for (const h of asList(d[`ex_${dir}_workloads`])) add('workload', h, dir, true, { href: h });
    for (const ip of asList(d[`${dir}_ip_in`]).concat(asList(d[`${dir}_ip`]))) add('ip', ip, dir, false);
    for (const ip of asList(d[`ex_${dir}_ip`])) add('ip', ip, dir, true);
  }
  for (const [k, cat] of [['any_label', 'label'], ['any_ip', 'ip'], ['any_iplist', 'iplist'], ['any_workload', 'workload']]) {
    if (d[k]) add(cat, d[k], 'any', false, cat === 'iplist' || cat === 'workload' ? { href: d[k] } : {});
    if (d['ex_' + k]) add(cat, d['ex_' + k], 'any', true, cat === 'iplist' || cat === 'workload' ? { href: d['ex_' + k] } : {});
  }
}

/* ── 加 pill / 移除 / 方向 / 排除（handler 掛 window，供 dispatcher 委派）── */
function _objfbAddPill(state, obj) {
  state.pills.push({
    cat: obj.cat, name: obj.name, href: obj.href || null,
    key: obj.key || null, value: obj.value || null, dir: state.addDir, neg: false,
  });
  _objfbRender(state);
  if (state.changeCb) state.changeCb();
}

/* ── 類別展示 metadata（下拉分類捷徑 / pill 色點；cat 字串需與序列化契約一致）── */
const _OBJFB_CATS = {
  label:       { i18n: 'gui_fb_cat_label',       dot: 'objfb-dot-label',    fallback: 'Labels' },
  label_group: { i18n: 'gui_fb_cat_label_group', dot: 'objfb-dot-lgroup',   fallback: 'Label Groups' },
  iplist:      { i18n: 'gui_fb_cat_iplist',      dot: 'objfb-dot-iplist',  fallback: 'IP Lists' },
  workload:    { i18n: 'gui_fb_cat_workload',    dot: 'objfb-dot-workload', fallback: 'Workloads' },
  ip:          { i18n: null,                     dot: 'objfb-dot-ip',       fallback: 'IP/CIDR' },
};
const _OBJFB_DIR_TAG = { src: 'S', dst: 'D', any: 'S/D' };

// suggest 端支援的類別，固定順序（'ip' 不支援 suggest，不列入）；
// _objfbQuerySuggest 與 _objfbRenderDropdown 皆以此清單交集 state.cats。
const _OBJFB_SUGGEST_CATS = ['label', 'label_group', 'iplist', 'workload'];

function _objfbApplyI18n(root) {
  if (typeof window.i18nApply === 'function') window.i18nApply(root);
}

/* ── 完整重繪：方向分段 + pill 搜尋列（pill + scope chip + input + 下拉）+ any 提示 + 編輯 popover ──
 * 呼叫時機：初始化、setFilters、加入/移除/編輯 pill 之後。下拉候選（輸入中）改由
 * _objfbUpdateDropdown 局部更新，避免每個按鍵都整段重建導致輸入框失焦。
 */
function _objfbRender(state) {
  const c = state.container;
  c.innerHTML = '';

  // 方向分段按鈕
  const dirSeg = document.createElement('div');
  dirSeg.className = 'objfb-dir-seg';
  dirSeg.setAttribute('role', 'group');
  for (const d of state.dirs) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'objfb-dir-btn' + (state.addDir === d ? ' on' : '');
    b.setAttribute('data-i18n', 'gui_fb_dir_' + d);
    b.textContent = d;
    b.setAttribute('data-on-click', '_objfbAddDir');
    b.dataset.args = JSON.stringify([state.id, d]);
    dirSeg.appendChild(b);
  }
  c.appendChild(dirSeg);

  // 搜尋列：pill 容器 + 輸入框 + 下拉
  const fbar = document.createElement('div');
  fbar.className = 'objfb-fbar';
  fbar.setAttribute('data-on-click', '_objfbInput');
  fbar.dataset.args = JSON.stringify([state.id]);

  // 追蹤同側同 key label pill，插入 or 分隔
  let prevKeyDir = null;
  state.pills.forEach((p, i) => {
    const derivedKey = p.key || (p.cat === 'label' && String(p.name).includes('=') ? String(p.name).split('=')[0] : null);
    if (prevKeyDir && p.cat === 'label' && derivedKey && prevKeyDir.dir === p.dir && prevKeyDir.key === derivedKey) {
      const orEl = document.createElement('span');
      orEl.className = 'objfb-or';
      orEl.setAttribute('data-i18n', 'gui_fb_or');
      orEl.textContent = 'or';
      fbar.appendChild(orEl);
    }
    fbar.appendChild(_objfbBuildPill(state, p, i));
    prevKeyDir = derivedKey ? { dir: p.dir, key: derivedKey } : null;
  });

  if (state.scopeCat) {
    const chip = document.createElement('span');
    chip.className = 'objfb-scope-chip';
    const label = document.createElement('span');
    const meta = _OBJFB_CATS[state.scopeCat];
    if (meta) label.setAttribute('data-i18n', meta.i18n);
    label.textContent = meta ? meta.fallback : state.scopeCat;
    chip.appendChild(label);
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'objfb-scope-x';
    x.textContent = '×';
    x.setAttribute('data-on-click', '_objfbClearScope');
    x.dataset.args = JSON.stringify([state.id]);
    chip.appendChild(x);
    fbar.appendChild(chip);
  }

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'objfb-input';
  input.autocomplete = 'off';
  input.setAttribute('data-i18n-placeholder', 'gui_fb_placeholder');
  input.placeholder = 'Search…';
  input.setAttribute('aria-label', 'Filter search');
  input.setAttribute('data-on-input', '_objfbInput');
  input.dataset.args = JSON.stringify([state.id]);
  input.setAttribute('data-on-keydown', '_objfbKeydown');
  input.setAttribute('data-pass-event', '1');
  fbar.appendChild(input);

  const dd = document.createElement('div');
  dd.className = 'objfb-dd';
  dd.setAttribute('role', 'listbox');
  fbar.appendChild(dd);

  c.appendChild(fbar);

  // any 方向較慢提示（有任一 pill 時顯示）
  const hint = document.createElement('div');
  hint.className = 'objfb-hint';
  hint.setAttribute('data-i18n', 'gui_fb_any_slow');
  hint.hidden = !state.pills.some(p => p.dir === 'any');
  c.appendChild(hint);

  // pill 編輯 popover（隱藏，點 pill 時填內容並開啟）
  const pop = document.createElement('div');
  pop.className = 'objfb-pop';
  c.appendChild(pop);

  state.els = { dirSeg, fbar, input, dd, hint, pop };
  state.ddItems = [];
  state.actIdx = -1;
  state.popIdx = -1;

  _objfbApplyI18n(c);
}

function _objfbBuildPill(state, p, idx) {
  const el = document.createElement('span');
  el.className = 'objfb-pill' + (p.neg ? ' objfb-excl' : '') + (p.dir === 'any' ? ' objfb-any' : '');
  el.setAttribute('data-on-click', '_objfbPillClick');
  el.dataset.args = JSON.stringify([state.id, idx]);
  el.setAttribute('data-pass-event', '1');

  const dirTag = document.createElement('span');
  dirTag.className = 'objfb-pill-dir';
  dirTag.textContent = _OBJFB_DIR_TAG[p.dir] || p.dir;
  el.appendChild(dirTag);

  const dot = document.createElement('i');
  const meta = _OBJFB_CATS[p.cat];
  dot.className = 'objfb-cat-dot ' + (meta ? meta.dot : 'objfb-dot-ip');
  el.appendChild(dot);

  const txt = document.createElement('span');
  txt.className = 'objfb-pill-txt';
  txt.textContent = (p.neg ? '! ' : '') + p.name;
  el.appendChild(txt);

  const x = document.createElement('button');
  x.type = 'button';
  x.className = 'objfb-pill-x';
  x.setAttribute('aria-label', 'remove');
  x.setAttribute('data-i18n-title', 'gui_fb_remove');
  x.textContent = '×';
  x.setAttribute('data-on-click', '_objfbRemovePill');
  x.dataset.args = JSON.stringify([state.id, idx]);
  el.appendChild(x);

  return el;
}

/* ── 下拉局部更新（不重繪整個 bar，保留輸入框焦點/游標）──
 * 空輸入：顯示類別捷徑。非空輸入：委派 _objfbRenderDropdown 立即畫出同步
 * 可得的候選（IP/CIDR 置頂、手動 key=value），並觸發 debounce suggest 查詢
 * （250ms 後打後端、結果回來時再由 _objfbRenderDropdown 併入分類分組）。
 */
function _objfbUpdateDropdown(state) {
  const dd = state.els.dd;
  const q = state.els.input.value.trim();
  dd.innerHTML = '';
  state.ddItems = [];

  if (!q) {
    if (state._abort) { state._abort.abort(); state._abort = null; }
    state._suggest = null;
    state._suggestQ = null;
    const catsWrap = document.createElement('div');
    catsWrap.className = 'objfb-dd-cats';
    for (const c of state.cats.filter((c) => c !== 'ip')) {
      const meta = _OBJFB_CATS[c];
      if (!meta) continue;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'objfb-cat-btn';
      const dot = document.createElement('i');
      dot.className = 'objfb-cat-dot ' + meta.dot;
      b.appendChild(dot);
      const label = document.createElement('span');
      label.setAttribute('data-i18n', meta.i18n);
      label.textContent = meta.fallback;
      b.appendChild(label);
      b.setAttribute('data-on-click', '_objfbSetScope');
      b.dataset.args = JSON.stringify([state.id, c]);
      catsWrap.appendChild(b);
    }
    dd.appendChild(catsWrap);
    const note = document.createElement('div');
    note.className = 'objfb-dd-note';
    note.setAttribute('data-i18n', 'gui_fb_scope_hint');
    dd.appendChild(note);
    _objfbApplyI18n(dd);
    dd.classList.add('open');
    state.actIdx = -1;
    return;
  }

  _objfbRenderDropdown(state, q);
  state._debouncedSuggest(q);
}

/* ── suggest 查詢：debounce 250ms 後由 state._debouncedSuggest 呼叫。
 * AbortController 取消上一個尚未回應的請求，避免競態下舊回應覆蓋新輸入的下拉。
 * GET 端點（Phase 2）不需 CSRF header，直接 fetch，不走 utils.js 的 get()
 * （get() 目前不支援傳入 signal）。
 */
function _objfbQuerySuggest(state, q) {
  if (state._abort) state._abort.abort();
  const ctrl = new AbortController();
  state._abort = ctrl;
  const scope = state.scopeCat;
  // 無 scope（自由輸入）時 types 須由 state.cats 導出，交集 suggest 端支援的類別
  // （'ip' 不是 suggest 類別，不列入）；有 scope 時 scope 本身已受
  // _objfbUpdateDropdown 的分類快選鈕過濾，天然是 state.cats 的子集。
  const types = scope ? scope : _OBJFB_SUGGEST_CATS.filter((c) => state.cats.includes(c)).join(',');
  const url = `/api/filter-objects/suggest?q=${encodeURIComponent(q)}&types=${types}&limit=10`;
  fetch(url, { signal: ctrl.signal, credentials: 'same-origin' })
    .then(r => r.json())
    .then(body => {
      state._suggest = body.results || {};
      state._suggestQ = q;
      _objfbRenderDropdown(state, q);
    })
    .catch(e => {
      // 已被更新的輸入取消，交給後繼請求畫下拉
      if (e.name === 'AbortError') return;
      state._suggest = { _error: true };
      state._suggestQ = q;
      _objfbRenderDropdown(state, q);
    });
}

/* ── 下拉完整重繪（非空輸入）：IP/CIDR 置頂 + 手動 key=value 加入 + suggest
 * 分類分組（label/label_group/iplist/workload）。workload 類遇
 * results.workload.error === 'pce_unreachable' 時顯示 gui_fb_offline 警示、
 * 其他類照常；整體 fetch 失敗（_error）顯示同一警示但不影響自由輸入。
 * 輸入框當下內容與 q 不符（使用者已改變輸入）時略過，避免過期回應覆蓋畫面。
 */
function _objfbRenderDropdown(state, q) {
  if (!state.els || state.els.input.value.trim() !== q) return;
  const dd = state.els.dd;
  dd.innerHTML = '';
  state.ddItems = [];

  if (_objfbIsIpLike(q) && !state.scopeCat) {
    _objfbAddDdGroup(state, [{ cat: 'ip', name: q }], 'gui_fb_add_ipcidr', 'Add IP/CIDR');
  } else if (!state.scopeCat || state.scopeCat === 'label') {
    const eq = q.indexOf('=');
    if (eq > 0 && eq < q.length - 1) {
      const k = q.slice(0, eq).trim();
      const v = q.slice(eq + 1).trim();
      if (k && v) {
        _objfbAddDdGroup(state, [{ cat: 'label', name: q, key: k, value: v }], 'gui_fb_cat_label', 'Labels');
      }
    }
  }

  const sug = (state._suggestQ === q) ? state._suggest : null;
  if (sug) {
    if (sug._error) {
      _objfbAddDdNote(dd, 'gui_fb_offline', 'PCE unreachable');
    } else {
      // 迭代清單須照 state.cats 過濾，否則被排除的分類（如規則 modal 排除的
      // label_group）仍會出現在下拉，選取後儲存會被後端拒絕。
      for (const cat of _OBJFB_SUGGEST_CATS.filter((c) => state.cats.includes(c))) {
        const r = sug[cat];
        if (!r) continue;
        if (cat === 'workload' && r.error === 'pce_unreachable') {
          _objfbAddDdNote(dd, 'gui_fb_offline', 'PCE unreachable');
          continue;
        }
        if (r.items && r.items.length) {
          const meta = _OBJFB_CATS[cat];
          _objfbAddDdGroup(state, r.items.map((it) => Object.assign({ cat }, it)), meta.i18n, meta.fallback);
        }
      }
    }
  }

  if (!state.ddItems.length) {
    const empty = document.createElement('div');
    empty.className = 'objfb-dd-empty';
    empty.setAttribute('data-i18n', 'gui_fb_no_match');
    dd.appendChild(empty);
  }

  _objfbApplyI18n(dd);
  state.actIdx = state.ddItems.length ? 0 : -1;
  _objfbMarkActive(state);
  dd.classList.add('open');
}

function _objfbAddDdNote(dd, i18nKey, fallback) {
  const note = document.createElement('div');
  note.className = 'objfb-dd-note';
  note.setAttribute('data-i18n', i18nKey);
  note.textContent = fallback;
  dd.appendChild(note);
}

function _objfbAddDdGroup(state, items, headerI18nKey, headerFallback) {
  const dd = state.els.dd;
  const h = document.createElement('div');
  h.className = 'objfb-dd-hdr';
  h.setAttribute('data-i18n', headerI18nKey);
  h.textContent = headerFallback;
  dd.appendChild(h);
  for (const o of items) {
    const el = document.createElement('div');
    el.className = 'objfb-dd-item';
    el.setAttribute('role', 'option');
    const meta = _OBJFB_CATS[o.cat];
    const dot = document.createElement('i');
    dot.className = 'objfb-cat-dot ' + (meta ? meta.dot : 'objfb-dot-ip');
    el.appendChild(dot);
    const txt = document.createElement('span');
    txt.textContent = o.name;
    el.appendChild(txt);
    el.setAttribute('data-on-click', '_objfbPickItem');
    el.dataset.args = JSON.stringify([state.id, o]);
    dd.appendChild(el);
    state.ddItems.push({ o, el });
  }
}

function _objfbMarkActive(state) {
  state.ddItems.forEach((it, i) => it.el.classList.toggle('act', i === state.actIdx));
  if (state.actIdx >= 0) state.ddItems[state.actIdx].el.scrollIntoView({ block: 'nearest' });
}

/* ── pill 編輯 popover：改方向 / 包含(gui_fb_include)排除(gui_fb_exclude) / 移除 ── */
function _objfbOpenPop(state, idx, pillEl) {
  const pop = state.els.pop;
  const p = state.pills[idx];
  if (!p || !pillEl) return;
  state.popIdx = idx;
  pop.innerHTML = '';

  const dirRow = document.createElement('div');
  dirRow.className = 'objfb-pop-row';
  const dirSeg = document.createElement('div');
  dirSeg.className = 'objfb-pop-seg';
  for (const d of state.dirs) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'objfb-pop-btn' + (p.dir === d ? ' on' : '');
    b.setAttribute('data-i18n', 'gui_fb_dir_' + d);
    b.setAttribute('data-on-click', '_objfbPopAction');
    b.dataset.args = JSON.stringify([state.id, idx, 'dir', d]);
    dirSeg.appendChild(b);
  }
  dirRow.appendChild(dirSeg);
  pop.appendChild(dirRow);

  const negRow = document.createElement('div');
  negRow.className = 'objfb-pop-row';
  const negSeg = document.createElement('div');
  negSeg.className = 'objfb-pop-seg';
  const incBtn = document.createElement('button');
  incBtn.type = 'button';
  incBtn.className = 'objfb-pop-btn' + (!p.neg ? ' on' : '');
  incBtn.setAttribute('data-i18n', 'gui_fb_include');
  incBtn.setAttribute('data-on-click', '_objfbPopAction');
  incBtn.dataset.args = JSON.stringify([state.id, idx, 'neg', false]);
  const excBtn = document.createElement('button');
  excBtn.type = 'button';
  excBtn.className = 'objfb-pop-btn objfb-pop-btn-danger' + (p.neg ? ' on' : '');
  excBtn.setAttribute('data-i18n', 'gui_fb_exclude');
  excBtn.setAttribute('data-on-click', '_objfbPopAction');
  excBtn.dataset.args = JSON.stringify([state.id, idx, 'neg', true]);
  negSeg.appendChild(incBtn);
  negSeg.appendChild(excBtn);
  negRow.appendChild(negSeg);
  pop.appendChild(negRow);

  const rm = document.createElement('button');
  rm.type = 'button';
  rm.className = 'objfb-pop-rm';
  rm.setAttribute('data-i18n', 'gui_fb_remove');
  rm.setAttribute('data-on-click', '_objfbPopAction');
  rm.dataset.args = JSON.stringify([state.id, idx, 'remove', null]);
  pop.appendChild(rm);

  const cRect = state.container.getBoundingClientRect();
  const pRect = pillEl.getBoundingClientRect();
  pop.style.left = Math.max(0, pRect.left - cRect.left) + 'px';
  pop.style.top = (pRect.bottom - cRect.top + 6) + 'px';
  pop.classList.add('open');

  _objfbApplyI18n(pop);
}

// 掛載 window（CSP dispatcher 查找 window[fnName]）
window.createFilterBar = createFilterBar;
window._objfbAddDir = function (id, dir) { const s = _objfbInstances[id]; if (s) { s.addDir = dir; _objfbRender(s); } };

window._objfbInput = function (id) {
  const s = _objfbInstances[id];
  if (!s || !s.els) return;
  s.els.input.focus();
  _objfbUpdateDropdown(s);
};

window._objfbKeydown = function (id, ev) {
  const s = _objfbInstances[id];
  if (!s || !s.els || !ev) return;
  const key = ev.key;
  if (key === 'ArrowDown') {
    ev.preventDefault();
    if (s.ddItems.length) { s.actIdx = (s.actIdx + 1) % s.ddItems.length; _objfbMarkActive(s); }
  } else if (key === 'ArrowUp') {
    ev.preventDefault();
    if (s.ddItems.length) { s.actIdx = (s.actIdx - 1 + s.ddItems.length) % s.ddItems.length; _objfbMarkActive(s); }
  } else if (key === 'Enter') {
    ev.preventDefault();
    if (s.actIdx >= 0 && s.ddItems[s.actIdx]) {
      window._objfbPickItem(id, s.ddItems[s.actIdx].o);
    } else {
      const q = s.els.input.value.trim();
      if (_objfbIsIpLike(q)) {
        window._objfbPickItem(id, { cat: 'ip', name: q });
      } else {
        const eq = q.indexOf('=');
        if (eq > 0 && eq < q.length - 1) {
          const k = q.slice(0, eq).trim();
          const v = q.slice(eq + 1).trim();
          if (k && v) window._objfbPickItem(id, { cat: 'label', name: q, key: k, value: v });
        }
      }
    }
  } else if (key === 'Escape') {
    s.els.dd.classList.remove('open');
    s.actIdx = -1;
  } else if (key === 'Backspace' && !s.els.input.value) {
    if (s.scopeCat) window._objfbClearScope(id);
    else if (s.pills.length) window._objfbRemovePill(id, s.pills.length - 1);
  }
};

window._objfbPillClick = function (id, idx, ev, pillEl) {
  const s = _objfbInstances[id];
  if (!s || !s.els) return;
  _objfbOpenPop(s, idx, pillEl);
};

window._objfbPickItem = function (id, payload) {
  const s = _objfbInstances[id];
  if (!s) return;
  _objfbAddPill(s, payload);
  if (s.els) { s.els.input.value = ''; s.els.input.focus(); _objfbUpdateDropdown(s); }
};

window._objfbRemovePill = function (id, idx) { const s = _objfbInstances[id]; if (s) { s.pills.splice(idx, 1); _objfbRender(s); if (s.changeCb) s.changeCb(); } };

window._objfbPopAction = function (id, idx, action, val) {
  const s = _objfbInstances[id];
  if (!s) return;
  const p = s.pills[idx];
  if (!p) return;
  if (action === 'dir') p.dir = val;
  else if (action === 'neg') p.neg = !!val;
  else if (action === 'remove') s.pills.splice(idx, 1);

  _objfbRender(s);
  if (s.changeCb) s.changeCb();
  if (action !== 'remove') {
    const pillEls = s.els.fbar.querySelectorAll('.objfb-pill');
    if (pillEls[idx]) _objfbOpenPop(s, idx, pillEls[idx]);
  }
};

window._objfbSetScope = function (id, cat) {
  const s = _objfbInstances[id];
  if (!s) return;
  s.scopeCat = cat;
  _objfbRender(s);
  s.els.input.focus();
  _objfbUpdateDropdown(s);
};

window._objfbClearScope = function (id) {
  const s = _objfbInstances[id];
  if (!s) return;
  s.scopeCat = null;
  _objfbRender(s);
  s.els.input.focus();
  _objfbUpdateDropdown(s);
};

// 點擊 bar/popover 以外區域時關閉下拉與 popover（沿用 codebase 既有的
// document-level outside-click 慣例，見 utils.js/dashboard.js/events.js）。
document.addEventListener('click', function (e) {
  for (const id in _objfbInstances) {
    const s = _objfbInstances[id];
    if (!s.els) continue;
    if (!s.els.fbar.contains(e.target)) s.els.dd.classList.remove('open');
    if (!s.els.pop.contains(e.target) && !e.target.closest('.objfb-pill')) s.els.pop.classList.remove('open');
  }
});
