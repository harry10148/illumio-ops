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
  // 單一 IP、CIDR（/prefix），或 IPv4 range（a.b.c.d-a.b.c.d，兩側各自過八位組檢查）。
  const octetsOk = (ip) => ip.split('.').every(o => +o <= 255);
  const m = t.match(/^(\d{1,3}(?:\.\d{1,3}){3})(?:\/(\d{1,2})|-(\d{1,3}(?:\.\d{1,3}){3}))?$/);
  if (!m) return false;
  if (!octetsOk(m[1])) return false;
  if (m[3] && !octetsOk(m[3])) return false;
  return true;
}

// port token：80 / 443/tcp / 1000-2000 / 1000-2000/udp（proto 也收數字）
function _objfbIsPortLike(s) {
  const m = String(s).trim().toLowerCase().match(/^(\d{1,5})(?:-(\d{1,5}))?(?:\/(tcp|udp|icmp|icmpv6|\d{1,3}))?$/);
  if (!m) return false;
  const lo = +m[1], hi = m[2] ? +m[2] : +m[1];
  return lo >= 1 && lo <= 65535 && hi >= 1 && hi <= 65535;
}

/* ── Service 欄輸入引導（spec §3.2）：純函式，回傳分組候選供下拉渲染。
 * 數字 → 三選一（無尾碼＝兩者 TCP+UDP，預設）+ 範圍起點提示；
 * 範圍 → 三選一（已帶 /proto 則單一候選）；
 * 文字 → Process Name / Windows Service 自由值（Policy Services 走既有 suggest 流程，不在此函式）。
 */
function _objfbSvcCandidates(q) {
  const t = String(q).trim().toLowerCase();
  const inRange = (n) => n >= 1 && n <= 65535;
  let m = t.match(/^(\d{1,5})$/);
  if (m && inRange(+m[1])) {
    return [
      { grp: 'portproto', items: [
        { cat: 'port', name: m[1], tagI18n: 'gui_fb_svc_both', dflt: true },
        { cat: 'port', name: `${m[1]}/tcp`, tagI18n: 'gui_fb_svc_tcp_only' },
        { cat: 'port', name: `${m[1]}/udp`, tagI18n: 'gui_fb_svc_udp_only' },
      ] },
      { grp: 'rangehint' },
    ];
  }
  m = t.match(/^(\d{1,5})-(\d{1,5})(?:\/(tcp|udp))?$/);
  if (m && inRange(+m[1]) && inRange(+m[2])) {
    const base = `${m[1]}-${m[2]}`;
    return [{ grp: 'portproto', items: m[3]
      ? [{ cat: 'port', name: `${base}/${m[3]}` }]
      : [
        { cat: 'port', name: base, tagI18n: 'gui_fb_svc_both', dflt: true },
        { cat: 'port', name: `${base}/tcp`, tagI18n: 'gui_fb_svc_tcp_only' },
        { cat: 'port', name: `${base}/udp`, tagI18n: 'gui_fb_svc_udp_only' },
      ] }];
  }
  // 明確帶 proto 的單埠（443/tcp）交給 _objfbIsPortLike 的手動加入路徑，不出三選一
  if (t && !/^\d/.test(t) && !_objfbIsPortLike(t)) {
    return [{ grp: 'freetext', items: [
      { cat: 'process', name: String(q).trim() },
      { cat: 'winservice', name: String(q).trim() },
    ] }];
  }
  return [];
}

/* ── Transmission 候選（僅 Destination 側面板；值域固定，無後端查詢）── */
const _OBJFB_TX_VALUES = ['unicast', 'broadcast', 'multicast'];
function _objfbTxCandidates(q) {
  const t = String(q).trim().toLowerCase();
  const vals = t ? _OBJFB_TX_VALUES.filter((v) => v.startsWith(t)) : _OBJFB_TX_VALUES;
  return vals.map((v) => ({ cat: 'transmission', name: v }));
}

function createFilterBar(container, options) {
  const opts = options || {};
  const cats = opts.cats || ['label', 'label_group', 'iplist', 'workload', 'ip',
    'service', 'port', 'process', 'winservice', 'transmission'];
  const id = 'objfb-' + (++_objfbSeq);
  const state = {
    id, container, cats,
    pills: [],          // {cat, name, href, key, value, dir, neg}
    mode: 'and',        // 'and'＝Source/Destination 分欄；'or'＝合併 Source OR Destination 欄
    dirs: ['src', 'dst'],  // object-browser.js 相容（依 mode 派生，_objfbRender 維護）
    addDir: 'src',         // object-browser.js 相容：外部加 pill 的方向
    zone: null,         // 作用中欄位 {col, neg}；col ∈ src|dst|any|svc
    zoneEls: {},        // `${col}:${neg}` → {fbar, input, dd}
    exclOpen: false,    // is-not 排除列展開狀態（modal 預設收合，spec §3.1）
    scopeCat: null,
    changeCb: null,
    _abort: null,
    _suggest: null,
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
    if (p.cat === 'service') { push(`${ex}services`, p.href || p.name); continue; }
    if (p.cat === 'port')    { push(`${ex}ports`, p.name); continue; }
    if (p.cat === 'process')      { push(`${ex}process_name`, p.name); continue; }
    if (p.cat === 'winservice')   { push(`${ex}windows_service_name`, p.name); continue; }
    if (p.cat === 'transmission') { push(`${ex}transmission`, p.name); continue; }
    if (p.dir === 'any') {
      // any 方向：Phase 1 單值 key（多個同類取最後值）
      if (p.cat === 'label')         setScalar(`${ex}any_label`, p.name);
      else if (p.cat === 'iplist')   setScalar(`${ex}any_iplist`, p.href || p.name);
      else if (p.cat === 'workload') setScalar(`${ex}any_workload`, p.href);
      else if (p.cat === 'ip')       setScalar(`${ex}any_ip`, p.name);
      else if (p.cat === 'label_group') {
        // any 方向不支援 label_group（design §C）：不得降格成 any_label
        // （group 名被當 label spec，fallback 比對 fail-closed 0 筆）。
        // 正常流程在 _objfbAddPill 已擋，這裡是序列化邊界的防禦性拒絕。
        console.warn('objfb: label_group pill is not supported for the any direction; skipped:', p.name);
      }
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
  for (const h of asList(d['services'])) add('service', h, null, false, { href: h });
  for (const h of asList(d['ex_services'])) add('service', h, null, true, { href: h });
  for (const tok of asList(d['ports'])) add('port', tok, null, false);
  for (const tok of asList(d['ex_ports'])) add('port', tok, null, true);
  // 舊 scalar port/proto/ex_port 回填成 port pill（讀取相容，零遷移）
  if (d['port']) {
    const protoName = { '6': 'tcp', '17': 'udp' }[String(d['proto'] || '')] || null;
    add('port', protoName ? `${d['port']}/${protoName}` : String(d['port']), null, false);
  }
  if (d['ex_port']) add('port', String(d['ex_port']), null, true);
  // Plan B：service 家族新類別（str | list[str] 皆容忍；transmission_excludes 為續留別名）
  for (const v of asList(d['process_name'])) add('process', v, null, false);
  for (const v of asList(d['ex_process_name'])) add('process', v, null, true);
  for (const v of asList(d['windows_service_name'])) add('winservice', v, null, false);
  for (const v of asList(d['ex_windows_service_name'])) add('winservice', v, null, true);
  for (const v of asList(d['transmission'])) add('transmission', v, null, false);
  for (const v of asList(d['ex_transmission']).concat(asList(d['transmission_excludes']))) add('transmission', v, null, true);
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
  // v2 模式判定：純 any_* → OR 模式；混雜（v1 歷史資料）→ AND，any pill 放
  // Source 欄並提示（spec §2「any 拆回時放 Source 欄並提示」）。重存後 key 隨之正規化。
  const hasAny = state.pills.some((p) => p.dir === 'any');
  const hasSided = state.pills.some((p) => p.dir === 'src' || p.dir === 'dst');
  if (hasAny && !hasSided) {
    state.mode = 'or';
    state.movedAnyHint = false;
  } else {
    state.mode = 'and';
    let moved = 0;
    for (const p of state.pills) if (p.dir === 'any') { p.dir = 'src'; moved++; }
    state.movedAnyHint = moved > 0;
  }
  state.exclOpen = state.pills.some((p) => p.neg);
  state.zone = null;
}

/* ── 加 pill / 移除 / 方向 / 排除（handler 掛 window，供 dispatcher 委派）── */
function _objfbAddPill(state, obj) {
  const z = state.zone || { col: state.addDir, neg: false };
  if (obj.cat === 'label_group' && z.col === 'any') {
    // any（OR）方向不支援 label_group：不建 pill，顯示提示（design §C）
    state.anyLabelGroupHint = true;
    _objfbRender(state);
    return;
  }
  state.anyLabelGroupHint = false;
  state.pills.push({
    cat: obj.cat, name: obj.name, href: obj.href || null,
    key: obj.key || null, value: obj.value || null,
    dir: _OBJFB_DIRLESS.has(obj.cat) || z.col === 'svc' ? null : z.col,
    neg: z.neg,
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
  service:     { i18n: 'gui_fb_cat_service',     dot: 'objfb-dot-service',  fallback: 'Services' },
  port:        { i18n: 'gui_fb_cat_port',        dot: 'objfb-dot-port',     fallback: 'Port' },
  process:      { i18n: 'gui_fb_cat_process',      dot: 'objfb-dot-process', fallback: 'Process Name' },
  winservice:   { i18n: 'gui_fb_cat_winservice',   dot: 'objfb-dot-winsvc',  fallback: 'Windows Service' },
  transmission: { i18n: 'gui_fb_cat_transmission', dot: 'objfb-dot-tx',      fallback: 'Transmission' },
};
/* ── v2 zone 模型（Plan B）：col ∈ src|dst|any|svc × neg ∈ include|exclude。
 * [include i18n, exclude i18n, include fallback, exclude fallback] ── */
const _OBJFB_ZONE_LABELS = {
  src: ['gui_fb_dir_src', 'gui_fb_col_src_not', 'Source', 'Source is not'],
  dst: ['gui_fb_dir_dst', 'gui_fb_col_dst_not', 'Destination', 'Destination is not'],
  any: ['gui_fb_col_any', 'gui_fb_col_any_not', 'Source OR Destination', 'Source OR Destination is not'],
  svc: ['gui_fb_col_svc', 'gui_fb_col_svc_not', 'Service', 'Service is not'],
};

function _objfbCols(state) { return state.mode === 'or' ? ['any', 'svc'] : ['src', 'dst', 'svc']; }

function _objfbZoneCats(state, col) {
  if (col === 'svc') {
    return ['service', 'port', 'process', 'winservice'].filter((c) => state.cats.includes(c));
  }
  const out = ['label', 'label_group', 'iplist', 'workload', 'ip'].filter((c) =>
    state.cats.includes(c) && !(col === 'any' && c === 'label_group'));
  // Transmission 僅 Destination 側（OR 模式合併欄包含 Destination，一併提供）——spec §3.1
  if ((col === 'dst' || col === 'any') && state.cats.includes('transmission')) out.push('transmission');
  return out;
}

function _objfbPillCol(state, p) {
  if (p.cat === 'transmission') return state.mode === 'or' ? 'any' : 'dst';
  if (p.dir === null) return 'svc';
  return p.dir;
}

// 無方向類別：pill 不帶 src/dst/any、序列化不吃 dir、popover 不顯示方向列
// 無方向類別：pill 不帶 src/dst/any、序列化不吃 dir。transmission 序列化亦無方向
// （flat key），但版面歸 Destination 欄（_objfbPillCol，Task 3）。
const _OBJFB_DIRLESS = new Set(['service', 'port', 'process', 'winservice', 'transmission']);

// suggest 端支援的類別，固定順序（'ip' 不支援 suggest，不列入）；
// _objfbQuerySuggest 與 _objfbRenderDropdown 皆以此清單交集 state.cats。
const _OBJFB_SUGGEST_CATS = ['label', 'label_group', 'iplist', 'workload', 'service'];
/* ── pill 顯示文字（spec §3.2）：port 無 proto 尾碼＝兩者；新類別帶語意前綴 ── */
function _objfbPillLabel(p) {
  if (p.cat === 'port' && !String(p.name).includes('/')) return `${p.name} (TCP+UDP)`;
  if (p.cat === 'process') return `proc: ${p.name}`;
  if (p.cat === 'winservice') return `winsvc: ${p.name}`;
  if (p.cat === 'transmission') return `TX: ${p.name}`;
  return p.name;
}

function _objfbApplyI18n(root) {
  if (typeof window.i18nApply === 'function') window.i18nApply(root);
}

/* ── 完整重繪（v2）：兩列（include / is-not）× 三欄（OR 模式兩欄）zone，
 * 中央 AND/OR 徽章 + ⇄ 鈕，排除列預設收合。下拉候選仍由 _objfbUpdateDropdown
 * 局部更新（作用中 zone 的 dd），避免每鍵重建失焦。 ── */
function _objfbRender(state) {
  const c = state.container;
  c.innerHTML = '';
  state.dirs = state.mode === 'or' ? ['any'] : ['src', 'dst'];
  if (!state.dirs.includes(state.addDir)) state.addDir = state.dirs[0];
  state.zoneEls = {};

  const grid = document.createElement('div');
  grid.className = 'objfb-grid';
  for (const neg of [false, true]) {
    const row = document.createElement('div');
    row.className = 'objfb-row' + (neg ? ' objfb-row-excl' : '');
    if (neg && !state.exclOpen) row.hidden = true;
    _objfbCols(state).forEach((col, ci) => {
      if (ci === 1) row.appendChild(_objfbBuildMid(state, neg));
      row.appendChild(_objfbBuildZone(state, col, neg));
    });
    grid.appendChild(row);
  }
  c.appendChild(grid);

  const exclBtn = document.createElement('button');
  exclBtn.type = 'button';
  exclBtn.className = 'objfb-excl-toggle';
  exclBtn.setAttribute('aria-expanded', state.exclOpen ? 'true' : 'false');
  exclBtn.setAttribute('data-i18n', 'gui_fb_excl_toggle');
  exclBtn.textContent = 'Exclusions (is not)';
  exclBtn.setAttribute('data-on-click', '_objfbToggleExcl');
  exclBtn.dataset.args = JSON.stringify([state.id]);
  c.appendChild(exclBtn);

  // 提示列：OR/any 較慢、any×label_group 不支援、label_group 擋 OR、OR→AND 搬移
  const mkHint = (i18nKey, hidden) => {
    const el = document.createElement('div');
    el.className = 'objfb-hint';
    el.setAttribute('data-i18n', i18nKey);
    el.hidden = hidden;
    c.appendChild(el);
  };
  mkHint('gui_fb_any_slow', !(state.mode === 'or' && state.pills.length > 0));
  mkHint('gui_fb_any_label_group_unsupported', !state.anyLabelGroupHint);
  mkHint('gui_fb_lgroup_or_blocked', !state.lgroupOrBlockHint);
  mkHint('gui_fb_moved_any_src', !state.movedAnyHint);

  const pop = document.createElement('div');
  pop.className = 'objfb-pop';
  c.appendChild(pop);

  state.els = null;   // 作用中 zone 的 {fbar, input, dd}；_objfbFocusZone 指定
  state.pop = pop;
  state.ddItems = [];
  state.actIdx = -1;
  state.popIdx = -1;

  _objfbApplyI18n(c);
}

function _objfbBuildMid(state, neg) {
  const mid = document.createElement('div');
  // 排除列的中央控制只佔位對齊（比照 mockup visibility:hidden）
  mid.className = 'objfb-mid' + (neg ? ' objfb-mid-ghost' : '');
  const mode = document.createElement('button');
  mode.type = 'button';
  mode.className = 'objfb-mode' + (state.mode === 'or' ? ' or' : '');
  mode.textContent = state.mode === 'or' ? 'OR' : 'AND';
  mode.setAttribute('data-i18n-title', 'gui_fb_mode_title');
  mode.setAttribute('data-on-click', '_objfbToggleMode');
  mode.dataset.args = JSON.stringify([state.id]);
  mid.appendChild(mode);
  if (state.mode === 'and') {
    const swap = document.createElement('button');
    swap.type = 'button';
    swap.className = 'objfb-swap';
    swap.textContent = '⇄';
    swap.setAttribute('data-i18n-title', 'gui_fb_swap_title');
    swap.setAttribute('data-on-click', '_objfbSwapCols');
    swap.dataset.args = JSON.stringify([state.id]);
    mid.appendChild(swap);
  }
  return mid;
}

function _objfbBuildZone(state, col, neg) {
  const zoneKey = col + ':' + neg;
  const zone = document.createElement('div');
  zone.className = 'objfb-col' + (col === 'svc' ? ' objfb-col-svc' : '');
  zone.dataset.zone = zoneKey;

  const lbl = document.createElement('div');
  lbl.className = 'objfb-col-label';
  const zmeta = _OBJFB_ZONE_LABELS[col];
  lbl.setAttribute('data-i18n', zmeta[neg ? 1 : 0]);
  lbl.textContent = zmeta[neg ? 3 : 2];
  zone.appendChild(lbl);

  const fbar = document.createElement('div');
  fbar.className = 'objfb-fbar' + (neg ? ' objfb-fbar-excl' : '');
  fbar.setAttribute('data-on-click', '_objfbZoneClick');
  fbar.dataset.args = JSON.stringify([state.id, col, neg]);

  // 同 key label pill 之間插入 or 分隔（zone 內比對即可——同欄已隱含同方向）
  let prevKey = null;
  state.pills.forEach((p, i) => {
    if (_objfbPillCol(state, p) !== col || p.neg !== neg) return;
    const derivedKey = p.key || (p.cat === 'label' && String(p.name).includes('=') ? String(p.name).split('=')[0] : null);
    if (prevKey && p.cat === 'label' && derivedKey && prevKey === derivedKey) {
      const orEl = document.createElement('span');
      orEl.className = 'objfb-or';
      orEl.setAttribute('data-i18n', 'gui_fb_or');
      orEl.textContent = 'or';
      fbar.appendChild(orEl);
    }
    fbar.appendChild(_objfbBuildPill(state, p, i));
    prevKey = (p.cat === 'label' && derivedKey) ? derivedKey : null;
  });

  const isActive = state.zone && state.zone.col === col && state.zone.neg === neg;
  if (isActive && state.scopeCat) {
    const chip = document.createElement('span');
    chip.className = 'objfb-scope-chip';
    const label = document.createElement('span');
    const meta = _OBJFB_CATS[state.scopeCat];
    if (meta && meta.i18n) label.setAttribute('data-i18n', meta.i18n);
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
  input.setAttribute('data-i18n-placeholder', col === 'svc' ? 'gui_fb_svc_placeholder' : 'gui_fb_placeholder');
  input.placeholder = 'Search…';
  input.setAttribute('aria-label', 'Filter search');
  input.setAttribute('data-on-input', '_objfbInput');
  input.dataset.args = JSON.stringify([state.id, col, neg]);
  input.setAttribute('data-on-keydown', '_objfbKeydown');
  input.setAttribute('data-pass-event', '1');
  fbar.appendChild(input);

  const dd = document.createElement('div');
  dd.className = 'objfb-dd';
  dd.setAttribute('role', 'listbox');
  fbar.appendChild(dd);

  zone.appendChild(fbar);
  state.zoneEls[zoneKey] = { fbar, input, dd };
  return zone;
}

function _objfbBuildPill(state, p, idx) {
  const el = document.createElement('span');
  el.className = 'objfb-pill' + (p.neg ? ' objfb-excl' : '') + (p.dir === 'any' ? ' objfb-any' : '');
  el.setAttribute('data-on-click', '_objfbPillClick');
  el.dataset.args = JSON.stringify([state.id, idx]);
  el.setAttribute('data-pass-event', '1');
  el.dataset.pillIdx = String(idx);

  const dot = document.createElement('i');
  const meta = _OBJFB_CATS[p.cat];
  dot.className = 'objfb-cat-dot ' + (meta ? meta.dot : 'objfb-dot-ip');
  el.appendChild(dot);

  const txt = document.createElement('span');
  txt.className = 'objfb-pill-txt';
  txt.textContent = (p.neg ? '! ' : '') + _objfbPillLabel(p);
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
 * 空輸入且無 scope：顯示類別 chip 列（含 totals）。空輸入且有 scope：該類別
 * 的全量瀏覽清單（載入更多）。非空輸入：委派 _objfbRenderDropdown 立即畫出
 * 同步可得的候選（IP/CIDR 置頂、手動 key=value），並觸發 debounce suggest
 * 查詢（250ms 後打後端、結果回來時再由 _objfbRenderDropdown 併入分類分組）。
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
    if (state.scopeCat === 'transmission') {
      // 值域固定、無後端查詢：直接列出三個候選
      _objfbRenderTxList(state);
      return;
    }
    if (state.scopeCat && state.scopeCat !== 'ip' && state.scopeCat !== 'port') {
      // 有 scope：空輸入即瀏覽該類別（process/winservice 同 workload：無瀏覽端點，顯示輸入提示）
      _objfbRenderBrowse(state);
      return;
    }
    // 無 scope：類別 chip 列（含 totals）
    _objfbRenderCatChips(state);
    return;
  }

  _objfbRenderDropdown(state, q);
  state._debouncedSuggest(q);
}

/* ── 空輸入瀏覽（案 C）：無 scope 顯示類別 chip（含各類總數），點 chip 設
 * scope 進入該類別的全量分頁清單；label 依 key 插入組頭。totals 每實例
 * 快取一次（TTL 交給後端 module cache）。 ── */
function _objfbRenderCatChips(state) {
  const dd = state.els.dd;
  dd.innerHTML = '';
  state.ddItems = [];
  const catsWrap = document.createElement('div');
  catsWrap.className = 'objfb-dd-cats';
  const zoneCol = state.zone ? state.zone.col : _objfbCols(state)[0];
  for (const c of _objfbZoneCats(state, zoneCol).filter((c) => c !== 'ip' && c !== 'port' && state.cats.includes(c))) {
    const meta = _OBJFB_CATS[c];
    if (!meta) continue;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'objfb-cat-btn';
    const dot = document.createElement('i');
    dot.className = 'objfb-cat-dot ' + meta.dot;
    b.appendChild(dot);
    const label = document.createElement('span');
    if (meta.i18n) label.setAttribute('data-i18n', meta.i18n);
    label.textContent = meta.fallback;
    b.appendChild(label);
    const n = state._totals && state._totals[c];
    if (typeof n === 'number') {
      const cnt = document.createElement('span');
      cnt.className = 'objfb-chip-cnt';
      cnt.textContent = ` (${n})`;
      b.appendChild(cnt);
    }
    b.setAttribute('data-on-click', '_objfbSetScope');
    b.dataset.args = JSON.stringify([state.id, c]);
    catsWrap.appendChild(b);
  }
  dd.appendChild(catsWrap);
  const note = document.createElement('div');
  note.className = 'objfb-dd-note';
  note.setAttribute('data-i18n', 'gui_fb_scope_hint');
  dd.appendChild(note);
  const browseAll = document.createElement('button');
  browseAll.type = 'button';
  browseAll.className = 'objfb-dd-more';
  browseAll.setAttribute('data-i18n', 'gui_fb_browse_all');
  browseAll.textContent = 'Browse all…';
  browseAll.setAttribute('data-on-click', '_objfbOpenBrowser');
  browseAll.dataset.args = JSON.stringify([state.id]);
  dd.appendChild(browseAll);
  _objfbApplyI18n(dd);
  dd.classList.add('open');
  state.actIdx = -1;
  if (!state._totals) {
    fetch('/api/filter-objects/browse?type=_totals', { credentials: 'same-origin' })
      .then(r => r.json())
      .then(body => {
        if (body.ok && body.totals) {
          state._totals = body.totals;
          if (state.els && !state.els.input.value.trim() && !state.scopeCat) _objfbRenderCatChips(state);
        }
      })
      .catch(() => {});
  }
}

function _objfbRenderBrowse(state, append) {
  const cat = state.scopeCat;
  const dd = state.els.dd;
  if (cat === 'workload' || cat === 'process' || cat === 'winservice') {
    dd.innerHTML = '';
    state.ddItems = [];
    _objfbAddDdNote(dd, 'gui_fb_type_to_search', 'Type to search');
    _objfbApplyI18n(dd);
    dd.classList.add('open');
    return;
  }
  const offset = append && state._browse && state._browse.type === cat ? state._browse.items.length : 0;
  fetch(`/api/filter-objects/browse?type=${cat}&offset=${offset}&limit=20`, { credentials: 'same-origin' })
    .then(r => r.json())
    .then(body => {
      // 已改變，放棄
      if (!state.els || state.els.input.value.trim() || state.scopeCat !== cat) return;
      if (!body.ok) throw new Error(body.error || 'browse');
      const prev = (append && state._browse && state._browse.type === cat) ? state._browse.items : [];
      state._browse = { type: cat, items: prev.concat(body.items), total: body.total, groups: body.groups || null };
      _objfbRenderBrowseList(state);
    })
    .catch(() => {
      if (!state.els) return;
      dd.innerHTML = '';
      state.ddItems = [];
      _objfbAddDdNote(dd, 'gui_fb_browse_error', 'Browse unavailable');
      _objfbApplyI18n(dd);
      dd.classList.add('open');
    });
}

function _objfbRenderTxList(state) {
  const dd = state.els.dd;
  dd.innerHTML = '';
  state.ddItems = [];
  _objfbAddDdGroup(state, _objfbTxCandidates(state.els.input.value.trim()),
    'gui_fb_cat_transmission', 'Transmission');
  _objfbApplyI18n(dd);
  state.actIdx = state.ddItems.length ? 0 : -1;
  _objfbMarkActive(state);
  dd.classList.add('open');
}

function _objfbRenderBrowseList(state) {
  const dd = state.els.dd;
  const b = state._browse;
  dd.innerHTML = '';
  state.ddItems = [];
  let prevKey = null;
  let batch = [];
  const flush = () => {
    if (!batch.length) return;
    const hdrText = b.type === 'label' ? prevKey : null;
    if (hdrText !== null) {
      const h = document.createElement('div');
      h.className = 'objfb-dd-hdr';
      h.textContent = hdrText;
      dd.appendChild(h);
    }
    _objfbAddDdGroupItems(state, batch);
    batch = [];
  };
  for (const it of b.items) {
    const k = b.type === 'label' ? (it.key || '') : null;
    if (b.type === 'label' && k !== prevKey) { flush(); prevKey = k; }
    batch.push(Object.assign({ cat: b.type }, it));
  }
  flush();
  if (b.items.length < b.total) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'objfb-dd-more';
    more.setAttribute('data-i18n', 'gui_fb_load_more');
    more.textContent = 'Load more';
    const cnt = document.createElement('span');
    cnt.textContent = ` (${b.items.length}/${b.total})`;
    more.appendChild(cnt);
    more.setAttribute('data-on-click', '_objfbBrowseMore');
    more.dataset.args = JSON.stringify([state.id]);
    dd.appendChild(more);
  }
  const browseAll = document.createElement('button');
  browseAll.type = 'button';
  browseAll.className = 'objfb-dd-more';
  browseAll.setAttribute('data-i18n', 'gui_fb_browse_all');
  browseAll.textContent = 'Browse all…';
  browseAll.setAttribute('data-on-click', '_objfbOpenBrowser');
  browseAll.dataset.args = JSON.stringify([state.id]);
  dd.appendChild(browseAll);
  _objfbApplyI18n(dd);
  state.actIdx = state.ddItems.length ? 0 : -1;
  _objfbMarkActive(state);
  dd.classList.add('open');
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
  // （'ip' 不是 suggest 類別，不列入）與作用中 zone 的可用類別（zoneCats）；
  // 有 scope 時 scope 本身若非 suggest 類別（process/winservice/transmission）
  // 直接放棄查詢——後端無對應端點。
  if (scope && !_OBJFB_SUGGEST_CATS.includes(scope)) return; // process/winservice/transmission 無後端 suggest
  const zoneCats = state.zone ? _objfbZoneCats(state, state.zone.col) : state.cats;
  const types = scope ? scope : _OBJFB_SUGGEST_CATS.filter((c) =>
    state.cats.includes(c) && zoneCats.includes(c)).join(',');
  if (!types) return;
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
  const zoneCats = state.zone ? _objfbZoneCats(state, state.zone.col) : state.cats;

  if (_objfbIsIpLike(q) && !state.scopeCat && state.zone && state.zone.col !== 'svc') {
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
  } else if (state.scopeCat === 'process' || state.scopeCat === 'winservice') {
    // process/winservice 無後端瀏覽/suggest：手動輸入即為候選
    const meta = _OBJFB_CATS[state.scopeCat];
    _objfbAddDdGroup(state, [{ cat: state.scopeCat, name: q.trim() }], meta.i18n, meta.fallback);
  }
  if (_objfbIsPortLike(q) && state.cats.includes('port') && (!state.scopeCat || state.scopeCat === 'service' || state.scopeCat === 'port') &&
      state.zone && state.zone.col === 'svc') {
    _objfbAddDdGroup(state, [{ cat: 'port', name: q.trim() }], 'gui_fb_add_port', 'Add Port');
  }
  if (state.zone && (state.zone.col === 'dst' || state.zone.col === 'any') && state.cats.includes('transmission')) {
    const txItems = _objfbTxCandidates(q);
    if (txItems.length) _objfbAddDdGroup(state, txItems, 'gui_fb_cat_transmission', 'Transmission');
  }

  const sug = (state._suggestQ === q) ? state._suggest : null;
  if (sug) {
    if (sug._error) {
      _objfbAddDdNote(dd, 'gui_fb_offline', 'PCE unreachable');
    } else {
      // 迭代清單須照 state.cats 過濾，否則被排除的分類（如規則 modal 排除的
      // label_group）仍會出現在下拉，選取後儲存會被後端拒絕；另交集作用中 zone
      // 的可用類別（zoneCats），避免例如 Service 欄出現 label 建議。
      for (const cat of _OBJFB_SUGGEST_CATS.filter((c) =>
          state.cats.includes(c) && zoneCats.includes(c))) {
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
  _objfbAddDdGroupItems(state, items);
}

// 不帶組頭的 items 渲染（_objfbAddDdGroup 拆出共用；原函式改呼叫此函式）
function _objfbAddDdGroupItems(state, items) {
  const dd = state.els.dd;
  for (const o of items) {
    const el = document.createElement('div');
    el.className = 'objfb-dd-item';
    el.setAttribute('role', 'option');
    const meta = _OBJFB_CATS[o.cat];
    const dot = document.createElement('i');
    dot.className = 'objfb-cat-dot ' + (meta ? meta.dot : 'objfb-dot-ip');
    el.appendChild(dot);
    const txt = document.createElement('span');
    txt.textContent = o.summary ? `${o.name} — ${o.summary}` : o.name;
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
  const pop = state.pop;
  const p = state.pills[idx];
  if (!p || !pillEl) return;
  state.popIdx = idx;
  pop.innerHTML = '';

  if (state.mode === 'and' && !_OBJFB_DIRLESS.has(p.cat)) {
    const dirRow = document.createElement('div');
    dirRow.className = 'objfb-pop-row';
    const dirSeg = document.createElement('div');
    dirSeg.className = 'objfb-pop-seg';
    for (const d of ['src', 'dst']) {
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
  }

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

/* ── 焦點/輸入（取代 v1 的方向分段鈕）：點/輸入任一 zone 即成為作用中 zone ── */
function _objfbFocusZone(state, col, neg) {
  const z = state.zoneEls[col + ':' + neg];
  if (!z) return;
  const changed = !state.zone || state.zone.col !== col || state.zone.neg !== neg;
  if (changed) {
    state.scopeCat = null;
    for (const k in state.zoneEls) state.zoneEls[k].dd.classList.remove('open');
  }
  state.zone = { col, neg };
  if (col !== 'svc' && col !== 'any') state.addDir = col;      // object-browser.js 相容
  else if (col === 'any') state.addDir = 'any';
  state.els = z;
  z.input.focus();
  _objfbUpdateDropdown(state);
}

// 掛載 window（CSP dispatcher 查找 window[fnName]）
window.createFilterBar = createFilterBar;

window._objfbZoneClick = function (id, col, neg) {
  const s = _objfbInstances[id];
  if (s) _objfbFocusZone(s, col, neg);
};

window._objfbInput = function (id, col, neg) {
  const s = _objfbInstances[id];
  if (s) _objfbFocusZone(s, col, neg);
};

window._objfbKeydown = function (id, col, neg, ev) {
  const s = _objfbInstances[id];
  if (!s || !ev) return;
  if (!s.zone || s.zone.col !== col || s.zone.neg !== neg) _objfbFocusZone(s, col, neg);
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
      if (col === 'svc' && _objfbIsPortLike(q) && s.cats.includes('port')) {
        window._objfbPickItem(id, { cat: 'port', name: q });
      } else if (col !== 'svc' && _objfbIsIpLike(q)) {
        window._objfbPickItem(id, { cat: 'ip', name: q });
      } else if (col !== 'svc') {
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
    if (s.scopeCat) { window._objfbClearScope(id); return; }
    for (let i = s.pills.length - 1; i >= 0; i--) {
      const p = s.pills[i];
      if (_objfbPillCol(s, p) === col && p.neg === neg) { window._objfbRemovePill(id, i); return; }
    }
  }
};

window._objfbToggleMode = function (id) {
  const s = _objfbInstances[id];
  if (!s) return;
  s.anyLabelGroupHint = false;
  s.movedAnyHint = false;
  if (s.mode === 'and') {
    // label_group 不能進 any（序列化 fail-closed 會丟棄）：擋切換並提示，不動資料
    if (s.pills.some((p) => p.cat === 'label_group')) {
      s.lgroupOrBlockHint = true;
      _objfbRender(s);
      return;
    }
    s.lgroupOrBlockHint = false;
    for (const p of s.pills) if (p.dir === 'src' || p.dir === 'dst') p.dir = 'any';
    s.mode = 'or';
  } else {
    s.lgroupOrBlockHint = false;
    let moved = 0;
    for (const p of s.pills) if (p.dir === 'any') { p.dir = 'src'; moved++; }
    s.mode = 'and';
    s.movedAnyHint = moved > 0;  // any 拆回 AND：pill 放 Source 欄並提示（spec §2）
  }
  s.zone = null;
  _objfbRender(s);
  if (s.changeCb) s.changeCb();
};

window._objfbSwapCols = function (id) {
  const s = _objfbInstances[id];
  if (!s || s.mode !== 'and') return;
  // transmission pill dir=null，天然不受對調影響（僅 Destination 側，spec §3.1）
  for (const p of s.pills) {
    if (p.dir === 'src') p.dir = 'dst';
    else if (p.dir === 'dst') p.dir = 'src';
  }
  s.zone = null;
  _objfbRender(s);
  if (s.changeCb) s.changeCb();
};

window._objfbToggleExcl = function (id) {
  const s = _objfbInstances[id];
  if (!s) return;
  s.exclOpen = !s.exclOpen;
  _objfbRender(s);
};

window._objfbPillClick = function (id, idx, ev, pillEl) {
  const s = _objfbInstances[id];
  // 注意：不可比照 v1 guard 檢查 s.els——v2 下 state.els 只在某 zone 被 focus 過才非
  // null，使用者可能直接點擊既有 pill（未先聚焦任何 zone），此時仍須能開 popover。
  if (!s) return;
  _objfbOpenPop(s, idx, pillEl);
};

window._objfbPickItem = function (id, payload) {
  const s = _objfbInstances[id];
  if (!s) return;
  const z = s.zone;
  _objfbAddPill(s, payload);
  // _objfbAddPill 觸發 _objfbRender，重繪後 zone DOM 換新、state.els 被清空
  // （見 _objfbRender），須以 z（加入前的作用中 zone）重新 focus 才能保留輸入焦點。
  if (z && s.zoneEls[z.col + ':' + z.neg]) {
    s.zoneEls[z.col + ':' + z.neg].input.value = '';
    _objfbFocusZone(s, z.col, z.neg);
  }
};

window._objfbRemovePill = function (id, idx) { const s = _objfbInstances[id]; if (s) { s.pills.splice(idx, 1); _objfbRender(s); if (s.changeCb) s.changeCb(); } };

window._objfbPopAction = function (id, idx, action, val) {
  const s = _objfbInstances[id];
  if (!s) return;
  const p = s.pills[idx];
  if (!p) return;
  if (action === 'dir') p.dir = val;
  else if (action === 'neg') { p.neg = !!val; if (p.neg) s.exclOpen = true; }
  else if (action === 'remove') s.pills.splice(idx, 1);

  _objfbRender(s);
  if (s.changeCb) s.changeCb();
  if (action !== 'remove') {
    const pillEl = s.container.querySelector('.objfb-pill[data-pill-idx="' + idx + '"]');
    if (pillEl) _objfbOpenPop(s, idx, pillEl);
  }
};

window._objfbSetScope = function (id, cat) {
  const s = _objfbInstances[id];
  if (!s || !s.zone) return;
  s.scopeCat = cat;
  const z = s.zone;
  _objfbRender(s);
  // _objfbFocusZone 重新指向重繪後的 zone DOM（見 _objfbPickItem 註解），
  // 同 col/neg 故不會清 scopeCat（_objfbFocusZone 的 changed 判斷為 false）。
  _objfbFocusZone(s, z.col, z.neg);
};

window._objfbClearScope = function (id) {
  const s = _objfbInstances[id];
  if (!s || !s.zone) return;
  s.scopeCat = null;
  const z = s.zone;
  _objfbRender(s);
  _objfbFocusZone(s, z.col, z.neg);
};

window._objfbBrowseMore = function (id) {
  const s = _objfbInstances[id];
  if (s) _objfbRenderBrowse(s, true);
};

// 供 object-browser.js（Modal 物件庫）取回實例、代為加入 pill。
window._objfbGetInstance = function (id) { return _objfbInstances[id] || null; };
window._objfbAddPillPublic = function (state, obj) {
  // object-browser.js 以 fb.addDir 指定方向；映射回 zone 模型（include 列）
  const saved = state.zone;
  state.zone = { col: state.addDir || _objfbCols(state)[0], neg: false };
  _objfbAddPill(state, obj);
  state.zone = saved;
};

window._objfbOpenBrowser = function (id) {
  const s = _objfbInstances[id];
  if (s && s.els) { s.els.dd.classList.remove('open'); window.openObjectBrowser(id); }
};

// 點擊 bar/popover 以外區域時關閉下拉與 popover（沿用 codebase 既有的
// document-level outside-click 慣例，見 utils.js/dashboard.js/events.js）。
document.addEventListener('click', function (e) {
  for (const id in _objfbInstances) {
    const s = _objfbInstances[id];
    for (const k in s.zoneEls) {
      if (!s.zoneEls[k].fbar.contains(e.target)) s.zoneEls[k].dd.classList.remove('open');
    }
    if (s.pop && !s.pop.contains(e.target) && !e.target.closest('.objfb-pill')) s.pop.classList.remove('open');
  }
});
