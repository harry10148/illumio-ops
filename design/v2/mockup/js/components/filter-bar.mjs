// filter-bar.mjs — PCE-style object filter selector.
// PORT OF src/static/js/filter-bar.js (1197 lines). Provenance per section:
//
//   SERIALIZATION CORE — _objfbSerialize (src:119-152) and _objfbDeserialize
//   (src:155-220) are transcribed statement for statement, including the any-
//   direction scalar keys, the legacy port/proto backfill, the label_group
//   fail-closed rejection and the v2 mode inference. tests/design_v2/
//   test_filterbar_semantics.py executes THIS file and the production file in
//   the same browser and asserts identical output for the captured queries.
//   Changing the semantics here without changing production is a test failure,
//   which is the entire point: the previous redesign attempt died on an
//   AND/OR filter divergence.
//
//   MODEL — _OBJFB_DIRLESS (src:285), _objfbCols (:264), _objfbZoneCats
//   (:266-275), _objfbPillCol (:277-281), _objfbPillLabel (:291-297),
//   _objfbAddPill (:223-240), _objfbIsIpLike (:13-22), _objfbIsPortLike
//   (:25-30), _objfbSvcCandidates (:37-70), _objfbTxCandidates (:74-78) and the
//   window handlers (:1003-1182) are transcribed; only the object-literal
//   construction is rewritten into builders, because design/v2/tools/
//   lint_no_inline_data.py rejects literals with more than four keys.
//
//   VIEW — re-skinned to the Direction B tokens. Behaviour is unchanged:
//   two rows (include / is-not, the latter collapsed by default, src:317-337)
//   by three zones (src|dst|svc; OR mode merges to any|svc, src:264), a centre
//   AND/OR badge with the ⇄ swap button (src:366-389), a two-pane dropdown
//   (candidates + category scopes, src:537-638) and a per-pill popover for
//   direction / include / exclude / remove (src:918-979).
//   The one visual departure: production paints ten category hues on the pill
//   dot; tokens.css carries five tones and no more, so the category is stated
//   as a mono abbreviation inside the pill and the dot carries the zone's tone
//   (include = info, exclude = crit). Ten new hues would have been ten new
//   colours outside the token contract for information an abbreviation states
//   more precisely.
//
// TWO DELIBERATE CONSTRAINTS, both load-bearing:
//
//   1. This module imports NOTHING. The parity test loads it as a classic
//      script (add_script_tag with "export " stripped) so it can call the same
//      function names as the production file in the same page; an import
//      statement would make that impossible. Strings therefore arrive through
//      setFilterBarText() and data through setFilterBarSnapshots() /
//      setFilterBarBrowser(), injected by the area at mount time. Defaults are
//      the production file's own English fallbacks, so the module is usable —
//      and testable — with nothing injected at all.
//   2. No innerHTML, same as the rest of the mockup: createElement/textContent
//      only, including in destroy().
//
// NOT PORTED, and why: the 250 ms debounce, the AbortController race guard and
// the /api/filter-objects/{suggest,browse} fetches (src:537-591, 640-671,
// 744-774). All three exist to manage network latency; a snapshot-fed mockup
// has none, and faking it would make the mockup slower than the product for
// show. Candidates resolve synchronously from the injected snapshots.

// ── injection points ────────────────────────────────────────────────────────

// t(key, fallback) — replaced by the area with core/i18n.mjs's t(). The default
// returns the production file's own fallback string.
let _t = function (key, fallback) { return fallback === undefined ? key : fallback; };

export function setFilterBarText(fn) {
  _t = typeof fn === "function" ? fn : _t;
}

// The two captured payloads that stand in for the suggest/browse endpoints:
//   suggest — snapshots/fb_suggest.json  {ok, results: {<cat>: {items, truncated}}}
//   browse  — snapshots/fb_browse.json   {groups: [{key, count}], items: [...]}
// Only `label` was capturable (the other categories need a live PCE), so every
// other scope honestly reports "type to search" instead of inventing rows.
let _suggestSnap = null;
let _browseSnap = null;

export function setFilterBarSnapshots(suggestSnap, browseSnap) {
  _suggestSnap = suggestSnap || null;
  _browseSnap = browseSnap || null;
}

// openBrowser(state) — the area supplies the object-browser surface (XC-04);
// filter-bar only knows when to ask for it (src:1179-1182).
let _openBrowser = null;

export function setFilterBarBrowser(fn) {
  _openBrowser = typeof fn === "function" ? fn : null;
}

// ── instance registry (src:10-11) ───────────────────────────────────────────
const _objfbInstances = {};
let _objfbSeq = 0;

// ── token predicates (src:13-30) ────────────────────────────────────────────

export function _objfbIsIpLike(s) {
  const t = String(s).trim();
  // single IP, CIDR (/prefix) or IPv4 range (a.b.c.d-a.b.c.d, each side octet-checked)
  const octetsOk = function (ip) { return ip.split(".").every(function (o) { return +o <= 255; }); };
  const m = t.match(/^(\d{1,3}(?:\.\d{1,3}){3})(?:\/(\d{1,2})|-(\d{1,3}(?:\.\d{1,3}){3}))?$/);
  if (!m) return false;
  if (!octetsOk(m[1])) return false;
  if (m[3] && !octetsOk(m[3])) return false;
  return true;
}

// port token: 80 / 443/tcp / 1000-2000 / 1000-2000/udp (proto also accepts a number)
export function _objfbIsPortLike(s) {
  const m = String(s).trim().toLowerCase().match(/^(\d{1,5})(?:-(\d{1,5}))?(?:\/(tcp|udp|icmp|icmpv6|\d{1,3}))?$/);
  if (!m) return false;
  const lo = +m[1], hi = m[2] ? +m[2] : +m[1];
  return lo >= 1 && lo <= 65535 && hi >= 1 && hi <= 65535;
}

// ── candidate builders (src:37-78) ──────────────────────────────────────────
function _svcOpt(name, tagI18n, dflt) {
  const o = {};
  o.cat = "port";
  o.name = name;
  if (tagI18n) o.tagI18n = tagI18n;
  if (dflt) o.dflt = true;
  return o;
}

function _svcGroup(grp, items) {
  const o = {};
  o.grp = grp;
  if (items) o.items = items;
  return o;
}

function _catItem(cat, name) {
  const o = {};
  o.cat = cat;
  o.name = name;
  return o;
}

/* Service-column input guidance (spec §3.2): a bare number offers three
 * choices (no suffix = both TCP+UDP, the default) plus a range hint; a range
 * offers the same three (one only when /proto is already typed); free text
 * offers Process Name / Windows Service. src:37-70. */
export function _objfbSvcCandidates(q) {
  const t = String(q).trim().toLowerCase();
  const inRange = function (n) { return n >= 1 && n <= 65535; };
  let m = t.match(/^(\d{1,5})$/);
  if (m && inRange(+m[1])) {
    const both = _svcOpt(m[1], "gui_fb_svc_both", true);
    const tcp = _svcOpt(m[1] + "/tcp", "gui_fb_svc_tcp_only");
    const udp = _svcOpt(m[1] + "/udp", "gui_fb_svc_udp_only");
    return [_svcGroup("portproto", [both, tcp, udp]), _svcGroup("rangehint")];
  }
  m = t.match(/^(\d{1,5})-(\d{1,5})(?:\/(tcp|udp))?$/);
  if (m && inRange(+m[1]) && inRange(+m[2])) {
    const base = m[1] + "-" + m[2];
    if (m[3]) return [_svcGroup("portproto", [_svcOpt(base + "/" + m[3])])];
    const both = _svcOpt(base, "gui_fb_svc_both", true);
    const tcp = _svcOpt(base + "/tcp", "gui_fb_svc_tcp_only");
    const udp = _svcOpt(base + "/udp", "gui_fb_svc_udp_only");
    return [_svcGroup("portproto", [both, tcp, udp])];
  }
  // an explicit single port with proto (443/tcp) goes through the manual add path
  if (t && !/^\d/.test(t) && !_objfbIsPortLike(t)) {
    const free = [_catItem("process", String(q).trim()), _catItem("winservice", String(q).trim())];
    return [_svcGroup("freetext", free)];
  }
  return [];
}

// Transmission candidates (Destination side only; fixed value domain, src:73-78)
const _OBJFB_TX_VALUES = ["unicast", "broadcast", "multicast"];

export function _objfbTxCandidates(q) {
  const t = String(q).trim().toLowerCase();
  const vals = t ? _OBJFB_TX_VALUES.filter(function (v) { return v.indexOf(t) === 0; }) : _OBJFB_TX_VALUES;
  return vals.map(function (v) { return _catItem("transmission", v); });
}

// ═══════════════════════════════════════════════════════════════════════════
//  SERIALIZATION CORE — transcribed from src:119-220. Do not "improve".
// ═══════════════════════════════════════════════════════════════════════════

/* pill -> filter dict (aligned with the Phase 1 native builder keys). src:119-152 */
export function _objfbSerialize(state) {
  const out = {};
  const push = function (k, v) { (out[k] = out[k] || []).push(v); };
  const setScalar = function (k, v) { out[k] = v; };
  for (const p of state.pills) {
    const ex = p.neg ? "ex_" : "";
    if (p.cat === "service") { push(ex + "services", p.href || p.name); continue; }
    if (p.cat === "port") { push(ex + "ports", p.name); continue; }
    if (p.cat === "process") { push(ex + "process_name", p.name); continue; }
    if (p.cat === "winservice") { push(ex + "windows_service_name", p.name); continue; }
    if (p.cat === "transmission") { push(ex + "transmission", p.name); continue; }
    if (p.dir === "any") {
      // any direction: Phase 1 single-value keys (several of a kind -> last wins)
      if (p.cat === "label") setScalar(ex + "any_label", p.name);
      else if (p.cat === "iplist") setScalar(ex + "any_iplist", p.href || p.name);
      else if (p.cat === "workload") setScalar(ex + "any_workload", p.href);
      else if (p.cat === "ip") setScalar(ex + "any_ip", p.name);
      else if (p.cat === "label_group") {
        // the any direction does not support label_group (design §C): it must NOT be
        // demoted to any_label (the group name would be read as a label spec and the
        // fallback comparison fail-closes to 0 rows). _objfbAddPill blocks it earlier;
        // this is the serialization boundary's defensive refusal.
        console.warn("objfb: label_group pill is not supported for the any direction; skipped:", p.name);
      }
      continue;
    }
    const d = p.dir; // src | dst
    if (p.cat === "label") push(ex + d + "_labels", p.name);
    else if (p.cat === "label_group") push(ex + d + "_label_groups", p.name);
    else if (p.cat === "iplist") push(ex + d + "_iplists", p.href || p.name);
    else if (p.cat === "workload") push(ex + d + "_workloads", p.href);
    else if (p.cat === "ip") push(ex ? "ex_" + d + "_ip" : d + "_ip_in", p.name);
  }
  return out;
}

// pill record. Field order matches src:161's Object.assign literal so a
// stringified pill compares byte for byte with production's.
function _objfbPill(cat, name, dir, neg) {
  const p = {};
  p.cat = cat;
  p.name = name;
  p.href = null;
  p.key = null;
  p.value = null;
  p.dir = dir;
  p.neg = neg;
  return p;
}

/* filter dict -> pills (backfills setFilters from a stored query). src:155-220 */
export function _objfbDeserialize(state, dict) {
  state.pills = [];
  state.anyLabelGroupHint = false;
  state.lgroupOrBlockHint = false;
  state.scopeCat = null;
  const add = function (cat, name, dir, neg, extra) {
    const p = _objfbPill(cat, name, dir, neg);
    if (extra) Object.keys(extra).forEach(function (k) { p[k] = extra[k]; });
    state.pills.push(p);
  };
  const href = function (h) { const o = {}; o.href = h; return o; };
  const d = dict || {};
  const asList = function (v) { return Array.isArray(v) ? v : (v ? [v] : []); };
  for (const h of asList(d["services"])) add("service", h, null, false, href(h));
  for (const h of asList(d["ex_services"])) add("service", h, null, true, href(h));
  for (const tok of asList(d["ports"])) add("port", tok, null, false);
  for (const tok of asList(d["ex_ports"])) add("port", tok, null, true);
  // legacy scalar port/proto/ex_port backfilled into port pills (read compat, zero migration)
  if (d["port"]) {
    const protoName = _objfbProtoName(d["proto"]);
    add("port", protoName ? d["port"] + "/" + protoName : String(d["port"]), null, false);
  } else if (d["proto"]) {
    // proto-only legacy setting (the v1 bare Protocol select could stand alone):
    // backfilled as that proto's whole port range (1-65535/tcp|udp, semantically
    // equivalent), otherwise editing and re-saving would silently drop the filter.
    const protoName = _objfbProtoName(d["proto"]);
    if (protoName) add("port", "1-65535/" + protoName, null, false);
  }
  if (d["ex_port"]) add("port", String(d["ex_port"]), null, true);
  // Plan B: the service-family categories (str | list[str] both tolerated;
  // transmission_excludes is a retained alias)
  for (const v of asList(d["process_name"])) add("process", v, null, false);
  for (const v of asList(d["ex_process_name"])) add("process", v, null, true);
  for (const v of asList(d["windows_service_name"])) add("winservice", v, null, false);
  for (const v of asList(d["ex_windows_service_name"])) add("winservice", v, null, true);
  for (const v of asList(d["transmission"])) add("transmission", v, null, false);
  for (const v of asList(d["ex_transmission"]).concat(asList(d["transmission_excludes"]))) add("transmission", v, null, true);
  for (const dir of ["src", "dst"]) {
    for (const spec of asList(d[dir + "_labels"]).concat(asList(d[dir + "_label"]))) add("label", spec, dir, false);
    for (const spec of asList(d["ex_" + dir + "_labels"]).concat(asList(d["ex_" + dir + "_label"]))) add("label", spec, dir, true);
    // label_group: the serializer emits {ex_}{dir}_label_groups, so omitting it here
    // would make label_group pills vanish on edit and be lost for good on the next save
    for (const spec of asList(d[dir + "_label_groups"])) add("label_group", spec, dir, false);
    for (const spec of asList(d["ex_" + dir + "_label_groups"])) add("label_group", spec, dir, true);
    for (const h of asList(d[dir + "_iplists"]).concat(asList(d[dir + "_iplist"]))) add("iplist", h, dir, false, href(h));
    for (const h of asList(d["ex_" + dir + "_iplists"])) add("iplist", h, dir, true, href(h));
    for (const h of asList(d[dir + "_workloads"])) add("workload", h, dir, false, href(h));
    for (const h of asList(d["ex_" + dir + "_workloads"])) add("workload", h, dir, true, href(h));
    for (const ip of asList(d[dir + "_ip_in"]).concat(asList(d[dir + "_ip"]))) add("ip", ip, dir, false);
    for (const ip of asList(d["ex_" + dir + "_ip"])) add("ip", ip, dir, true);
  }
  for (const pair of _OBJFB_ANY_KEYS) {
    const k = pair[0], cat = pair[1];
    if (d[k]) add(cat, d[k], "any", false, cat === "iplist" || cat === "workload" ? href(d[k]) : {});
    if (d["ex_" + k]) add(cat, d["ex_" + k], "any", true, cat === "iplist" || cat === "workload" ? href(d["ex_" + k]) : {});
  }
  // v2 mode inference: purely any_* -> OR mode; mixed (v1 historic data) -> AND, with
  // the any pills placed in the Source column and a hint (spec §2 "when any is split
  // back it goes to Source with a hint"). Re-saving normalises the keys.
  const hasAny = state.pills.some(function (p) { return p.dir === "any"; });
  const hasSided = state.pills.some(function (p) { return p.dir === "src" || p.dir === "dst"; });
  if (hasAny && !hasSided) {
    state.mode = "or";
    state.movedAnyHint = false;
  } else {
    state.mode = "and";
    let moved = 0;
    for (const p of state.pills) if (p.dir === "any") { p.dir = "src"; moved++; }
    state.movedAnyHint = moved > 0;
  }
  state.exclOpen = state.pills.some(function (p) { return p.neg; });
  state.zone = null;
}

// src:170/176 — {'6': 'tcp', '17': 'udp'} as a pair table (the inline-data lint
// rejects nothing here, but one lookup for both call sites is one fewer literal).
const _OBJFB_PROTOS = [["6", "tcp"], ["17", "udp"]];

function _objfbProtoName(proto) {
  const want = String(proto || "");
  let hit = null;
  _OBJFB_PROTOS.forEach(function (pair) { if (pair[0] === want) hit = pair[1]; });
  return hit;
}

// src:201 — the any_* scalar keys and the pill category each backfills to.
const _OBJFB_ANY_KEYS = [["any_label", "label"], ["any_ip", "ip"], ["any_iplist", "iplist"], ["any_workload", "workload"]];

// ═══════════════════════════════════════════════════════════════════════════
//  MODEL
// ═══════════════════════════════════════════════════════════════════════════

// Category display metadata (src:243-254) as [cat, i18n key, abbreviation,
// English fallback]. The abbreviation replaces production's per-category dot
// colour — see the header note.
const _OBJFB_CATS = [
  ["label", "gui_fb_cat_label", "LBL", "Labels"],
  ["label_group", "gui_fb_cat_label_group", "LGR", "Label Groups"],
  ["iplist", "gui_fb_cat_iplist", "IPL", "IP Lists"],
  ["workload", "gui_fb_cat_workload", "WKL", "Workloads"],
  ["ip", "gui_fb_cat_ip", "IP", "IP/CIDR"],
  ["service", "gui_fb_cat_service", "SVC", "Services"],
  ["port", "gui_fb_cat_port", "PRT", "Port"],
  ["process", "gui_fb_cat_process", "PRC", "Process Name"],
  ["winservice", "gui_fb_cat_winservice", "WSV", "Windows Service"],
  ["transmission", "gui_fb_cat_transmission", "TX", "Transmission"],
];

function _objfbCatMeta(cat) {
  let hit = null;
  _OBJFB_CATS.forEach(function (row) { if (row[0] === cat) hit = row; });
  return hit;
}

function _objfbCatLabel(cat) {
  const row = _objfbCatMeta(cat);
  return row ? _t(row[1], row[3]) : String(cat);
}

/* v2 zone model (Plan B): col ∈ src|dst|any|svc × neg ∈ include|exclude.
 * [col, include key, exclude key, include fallback, exclude fallback]. src:257-262 */
const _OBJFB_ZONES = [
  ["src", "gui_fb_dir_src", "gui_fb_col_src_not", "Source", "Source is not"],
  ["dst", "gui_fb_dir_dst", "gui_fb_col_dst_not", "Destination", "Destination is not"],
  ["any", "gui_fb_col_any", "gui_fb_col_any_not", "Source OR Destination", "Source OR Destination is not"],
  ["svc", "gui_fb_col_svc", "gui_fb_col_svc_not", "Service", "Service is not"],
];

function _objfbZoneLabel(col, neg) {
  let hit = null;
  _OBJFB_ZONES.forEach(function (row) { if (row[0] === col) hit = row; });
  if (!hit) return col;
  return neg ? _t(hit[2], hit[4]) : _t(hit[1], hit[3]);
}

export function _objfbCols(state) {
  return state.mode === "or" ? ["any", "svc"] : ["src", "dst", "svc"];
}

export function _objfbZoneCats(state, col) {
  if (col === "svc") {
    return ["service", "port", "process", "winservice"].filter(function (c) { return state.cats.includes(c); });
  }
  const out = ["label", "label_group", "iplist", "workload", "ip"].filter(function (c) {
    return state.cats.includes(c) && !(col === "any" && c === "label_group");
  });
  // Transmission is Destination-side only (the OR mode's merged column contains
  // Destination, so it is offered there too) — spec §3.1
  if ((col === "dst" || col === "any") && state.cats.includes("transmission")) out.push("transmission");
  return out;
}

// Direction-less categories: the pill carries no src/dst/any, serialization
// ignores dir and the popover hides the direction row. transmission also
// serializes without a direction (flat key) but lives in the Destination
// column for layout purposes (_objfbPillCol). src:283-285
const _OBJFB_DIRLESS = new Set(["service", "port", "process", "winservice", "transmission"]);

export function _objfbPillCol(state, p) {
  if (p.cat === "transmission") return state.mode === "or" ? "any" : "dst";
  if (p.dir === null) return "svc";
  return p.dir;
}

// Categories the suggest endpoint supports, fixed order ('ip' has no suggest). src:289
const _OBJFB_SUGGEST_CATS = ["label", "label_group", "iplist", "workload", "service"];

/* Pill display text (spec §3.2): a port with no proto suffix means both. src:291-297 */
export function _objfbPillLabel(p) {
  if (p.cat === "port" && String(p.name).indexOf("/") < 0) return p.name + " (TCP+UDP)";
  return p.name;
}

/* add pill / remove / direction / exclude. src:223-240 */
function _objfbAddPill(state, obj) {
  const z = state.zone || _objfbZone(state.addDir, false);
  if (obj.cat === "label_group" && z.col === "any") {
    // the any (OR) direction does not support label_group: no pill, show the hint (design §C)
    state.anyLabelGroupHint = true;
    _objfbRender(state);
    return;
  }
  state.anyLabelGroupHint = false;
  const p = _objfbPill(obj.cat, obj.name,
    _OBJFB_DIRLESS.has(obj.cat) || z.col === "svc" ? null : z.col, z.neg);
  p.href = obj.href || null;
  p.key = obj.key || null;
  p.value = obj.value || null;
  state.pills.push(p);
  _objfbRender(state);
  if (state.changeCb) state.changeCb();
}

function _objfbZone(col, neg) {
  const z = {};
  z.col = col;
  z.neg = neg;
  return z;
}

// ═══════════════════════════════════════════════════════════════════════════
//  VIEW
// ═══════════════════════════════════════════════════════════════════════════

function _fbEl(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function _fbBtn(cls, text, onClick) {
  const b = _fbEl("button", cls, text);
  b.type = "button";
  if (onClick) b.addEventListener("click", onClick);
  return b;
}

function _fbClear(node) {
  while (node && node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/* Full repaint (src:306-364): two rows (include / is-not) × three zones (two in
 * OR mode), centre AND/OR badge + ⇄, exclusion row collapsed by default. The
 * dropdown is still updated in place (_objfbUpdateDropdown) so typing never
 * loses focus. */
function _objfbRender(state) {
  const c = state.container;
  _fbClear(c);
  state.dirs = state.mode === "or" ? ["any"] : ["src", "dst"];
  if (!state.dirs.includes(state.addDir)) state.addDir = state.dirs[0];
  // after a mode switch addZone may point at a column that no longer exists
  if (state.addZone && state.addZone.col !== "svc" && !_objfbCols(state).includes(state.addZone.col)) state.addZone = null;
  state.zoneEls = {};

  const grid = _fbEl("div", "fb-grid");
  // OR mode's .fb-row has 2 zones (any/svc) instead of AND's 3 (src/dst/svc);
  // the grid template must key off this or the OR row leaves its last track
  // blank (review finding #2; dev-shots/ dropped from the deliverable 2026-08-04,
  // see design/v2/tools/masking.py PII 段落 for why).
  grid.dataset.cols = String(_objfbCols(state).length);
  [false, true].forEach(function (neg) {
    const row = _fbEl("div", "fb-row" + (neg ? " fb-row-excl" : ""));
    if (neg && !state.exclOpen) row.hidden = true;
    _objfbCols(state).forEach(function (col, ci) {
      if (ci === 1) row.appendChild(_objfbBuildMid(state, neg));
      row.appendChild(_objfbBuildZone(state, col, neg));
    });
    grid.appendChild(row);
  });
  c.appendChild(grid);

  const exclBtn = _fbBtn("fb-excl", _t("gui_fb_excl_toggle", "Exclusions (is not)"), function () {
    state.exclOpen = !state.exclOpen;
    _objfbRender(state);
  });
  exclBtn.setAttribute("aria-expanded", state.exclOpen ? "true" : "false");
  c.appendChild(exclBtn);

  // hint row: OR/any is slower, any×label_group unsupported, label_group blocks
  // OR, OR->AND moved the pills. src:339-350
  const hints = _fbEl("div", "fb-hints");
  _fbHint(hints, "gui_fb_any_slow", "Source OR Destination queries are slower.",
    state.mode === "or" && state.pills.length > 0);
  _fbHint(hints, "gui_fb_any_label_group_unsupported", "Label groups are not supported in the merged column.",
    !!state.anyLabelGroupHint);
  _fbHint(hints, "gui_fb_lgroup_or_blocked", "Remove the label group pills before switching to OR.",
    !!state.lgroupOrBlockHint);
  _fbHint(hints, "gui_fb_moved_any_src", "The merged pills were moved to Source.",
    !!state.movedAnyHint);
  c.appendChild(hints);

  const pop = _fbEl("div", "fb-pop");
  pop.hidden = true;
  c.appendChild(pop);

  state.els = null;
  state.pop = pop;
  state.ddItems = [];
  state.actIdx = -1;
  state.popIdx = -1;
}

function _fbHint(host, key, fallback, show) {
  if (!show) return;
  host.appendChild(_fbEl("p", "fb-hint", _t(key, fallback)));
}

// src:366-389 — the AND/OR badge, and (AND only) the column swap.
function _objfbBuildMid(state, neg) {
  const mid = _fbEl("div", "fb-mid" + (neg ? " fb-mid-ghost" : ""));
  const mode = _fbBtn("fb-mode", state.mode === "or" ? "OR" : "AND", function () {
    _fbToggleMode(state);
  });
  mode.setAttribute("data-tone", state.mode === "or" ? "warn" : "info");
  mode.title = _t("gui_fb_mode_title", "Switch between separate and merged columns");
  mid.appendChild(mode);
  if (state.mode === "and") {
    const swap = _fbBtn("fb-swap", "⇄", function () { _fbSwapCols(state); });
    swap.title = _t("gui_fb_swap_title", "Swap Source and Destination");
    mid.appendChild(swap);
  }
  return mid;
}

// src:391-487
function _objfbBuildZone(state, col, neg) {
  const zoneKey = col + ":" + neg;
  const zone = _fbEl("div", "fb-col" + (col === "svc" ? " fb-col-svc" : ""));
  zone.dataset.zone = zoneKey;
  zone.setAttribute("data-tone", neg ? "crit" : "info");
  zone.appendChild(_fbEl("div", "fb-col-label", _objfbZoneLabel(col, neg)));

  const bar = _fbEl("div", "fb-bar" + (neg ? " fb-bar-excl" : ""));
  bar.addEventListener("click", function (e) {
    if (e.target.closest(".fb-pill") || e.target.closest(".fb-dd")) return;
    _objfbFocusZone(state, col, neg);
  });

  // an "or" separator between same-key label pills (same column already implies
  // same direction, so comparing inside the zone is enough). src:409-423
  let prevKey = null;
  state.pills.forEach(function (p, i) {
    if (_objfbPillCol(state, p) !== col || p.neg !== neg) return;
    const derivedKey = p.key || (p.cat === "label" && String(p.name).indexOf("=") > 0 ? String(p.name).split("=")[0] : null);
    if (prevKey && p.cat === "label" && derivedKey && prevKey === derivedKey) {
      bar.appendChild(_fbEl("span", "fb-or", _t("gui_fb_or", "or")));
    }
    bar.appendChild(_objfbBuildPill(state, p, i));
    prevKey = (p.cat === "label" && derivedKey) ? derivedKey : null;
  });

  const isActive = state.zone && state.zone.col === col && state.zone.neg === neg;
  if (isActive && state.scopeCat) {
    const chip = _fbEl("span", "fb-scope");
    chip.appendChild(_fbEl("span", null, _objfbCatLabel(state.scopeCat)));
    chip.appendChild(_fbBtn("fb-x", "×", function () { _objfbClearScope(state); }));
    bar.appendChild(chip);
  }

  const input = _fbEl("input", "fb-input");
  input.type = "text";
  input.autocomplete = "off";
  input.placeholder = col === "svc"
    ? _t("gui_fb_svc_placeholder", "Port, service, process…")
    : _t("gui_fb_placeholder", "Search…");
  input.setAttribute("aria-label", _t("gui_fb_search", "Filter search"));
  input.addEventListener("input", function () { _objfbFocusZone(state, col, neg); });
  input.addEventListener("keydown", function (ev) { _objfbKeydown(state, col, neg, ev); });
  bar.appendChild(input);

  const dd = _fbEl("div", "fb-dd");
  dd.hidden = true;
  const body = _fbEl("div", "fb-dd-body");
  const ddMain = _fbEl("div", "fb-dd-main");
  ddMain.setAttribute("role", "listbox");
  const ddCats = _fbEl("div", "fb-dd-cats");
  body.appendChild(ddMain);
  body.appendChild(ddCats);
  dd.appendChild(body);
  const foot = _fbEl("div", "fb-dd-foot");
  foot.appendChild(_fbEl("span", null, _t("gui_fb_kbd_hint", "↑↓ to move · Enter to add · Esc to close")));
  if (col === "svc") foot.appendChild(_fbEl("span", "fb-fmt", _t("gui_fb_fmt_hint", "port, port/proto or a range")));
  dd.appendChild(foot);
  bar.appendChild(dd);

  zone.appendChild(bar);
  const els = {};
  els.bar = bar;
  els.input = input;
  els.dd = dd;
  els.ddMain = ddMain;
  els.ddCats = ddCats;
  state.zoneEls[zoneKey] = els;
  return zone;
}

// src:489-526 — pill body opens the edit popover; × removes. Keyboard reachable.
function _objfbBuildPill(state, p, idx) {
  const el = _fbEl("span", "fb-pill");
  el.setAttribute("data-tone", p.neg ? "crit" : "info");
  el.dataset.pillIdx = String(idx);
  el.setAttribute("role", "button");
  el.setAttribute("tabindex", "0");
  const text = (p.neg ? "! " : "") + _objfbPillLabel(p);
  el.setAttribute("aria-label", _objfbCatLabel(p.cat) + " " + text);
  el.addEventListener("click", function (e) {
    if (e.target.closest(".fb-pill-x")) return;
    _objfbOpenPop(state, idx, el);
  });
  el.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.click(); }
  });

  el.appendChild(_fbEl("i", "dot"));
  const meta = _objfbCatMeta(p.cat);
  el.appendChild(_fbEl("span", "fb-cat", meta ? meta[2] : "?"));
  el.appendChild(_fbEl("span", "fb-pill-txt", text));

  const x = _fbBtn("fb-pill-x", "×", function () {
    state.pills.splice(idx, 1);
    _objfbRender(state);
    if (state.changeCb) state.changeCb();
  });
  x.setAttribute("aria-label", _t("gui_fb_remove", "Remove"));
  x.title = _t("gui_fb_remove", "Remove");
  el.appendChild(x);
  return el;
}

/* Dropdown update (src:537-591). Right pane: the zone's category scopes,
 * rebuilt each open. Left pane: empty input and no scope -> a hint; empty input
 * with a scope -> that category's browse list; non-empty input -> the synchronous
 * candidates (IP/CIDR first, manual key=value) merged with the snapshot's
 * suggest results. */
function _objfbUpdateDropdown(state) {
  const dd = state.els.dd;
  const main = state.els.ddMain;
  const q = state.els.input.value.trim();
  _fbClear(main);
  state.ddItems = [];

  _objfbRenderCatPane(state);
  dd.hidden = false;

  if (!q) {
    if (state.scopeCat === "transmission") {
      // fixed value domain, no backend query
      _objfbAddDdGroup(state, _objfbTxCandidates(""), "gui_fb_cat_transmission", "Transmission");
      _objfbFinishDd(state);
      return;
    }
    if (state.scopeCat && state.scopeCat !== "ip" && state.scopeCat !== "port") {
      _objfbRenderBrowse(state);
      return;
    }
    if (state.scopeCat === "ip" || state.scopeCat === "port") {
      // ip/port have no browse endpoint: show the typing prompt, not the generic hint
      _objfbAddDdNote(main, "gui_fb_type_to_search", "Type to search");
      state.actIdx = -1;
      return;
    }
    _objfbAddDdNote(main, "gui_fb_scope_hint", "Type to search all categories, or pick a category to narrow");
    state.actIdx = -1;
    return;
  }

  _objfbRenderDropdown(state, q);
}

/* Right pane: Search All Categories + this zone's categories + Browse all. src:594-638 */
function _objfbRenderCatPane(state) {
  const pane = state.els.ddCats;
  _fbClear(pane);
  const col = state.zone ? state.zone.col : _objfbCols(state)[0];

  const all = _fbBtn("fb-cat-item fb-cat-hd" + (!state.scopeCat ? " on" : ""),
    _t("gui_fb_cat_all", "Search All Categories"), function () { _objfbClearScope(state); });
  pane.appendChild(all);

  const totals = _objfbBrowseTotals();
  _objfbZoneCats(state, col).forEach(function (c) {
    const meta = _objfbCatMeta(c);
    if (!meta) return;
    const b = _fbBtn("fb-cat-item" + (state.scopeCat === c ? " on" : ""), null, function () {
      _objfbSetScope(state, c);
    });
    b.appendChild(_fbEl("span", "fb-cat", meta[2]));
    b.appendChild(_fbEl("span", null, _t(meta[1], meta[3])));
    if (typeof totals[c] === "number") b.appendChild(_fbEl("span", "fb-cnt", totals[c]));
    pane.appendChild(b);
  });

  pane.appendChild(_fbBtn("fb-cat-item", _t("gui_fb_browse_all", "Browse all…"), function () {
    _objfbOpenBrowser(state);
  }));
}

// Production reads /api/filter-objects/browse?type=_totals (src:550). The
// snapshot carries the same figure for the one category it could capture.
function _objfbBrowseTotals() {
  const out = {};
  if (_browseSnap && typeof _browseSnap.total === "number") out.label = _browseSnap.total;
  return out;
}

// src:640-671 + 686-737 — the browse list, grouped by label key with a load-more.
function _objfbRenderBrowse(state, append) {
  const cat = state.scopeCat;
  const main = state.els.ddMain;
  _fbClear(main);
  state.ddItems = [];
  const rows = _objfbCorpus(cat);
  if (!rows) {
    // workload/process/winservice have no browse endpoint (src:644-650); the other
    // categories simply were not capturable without a live PCE.
    _objfbAddDdNote(main, "gui_fb_type_to_search", "Type to search");
    _objfbFinishDd(state);
    return;
  }
  const shown = append ? Math.min(rows.length, (state._browseN || 20) + 20) : Math.min(rows.length, 20);
  state._browseN = shown;

  let prevKey = null;
  rows.slice(0, shown).forEach(function (it) {
    const k = cat === "label" ? (it.key || "") : null;
    if (cat === "label" && k !== prevKey) {
      main.appendChild(_fbEl("div", "fb-dd-hdr", k));
      prevKey = k;
    }
    _objfbAddDdGroupItems(state, [_objfbSuggestItem(cat, it)]);
  });
  if (shown < rows.length) {
    const more = _fbBtn("fb-dd-more", _t("gui_fb_load_more", "Load more") + " (" + shown + "/" + rows.length + ")",
      function () { _objfbRenderBrowse(state, true); });
    main.appendChild(more);
  } else if (_browseSnap && _browseSnap.total > rows.length) {
    // the capture holds one page; the rest of the collection needs the endpoint
    _objfbAddDdNote(main, "v2_iv_browse_captured", rows.length + " / " + _browseSnap.total);
  }
  main.appendChild(_fbBtn("fb-dd-more", _t("gui_fb_browse_all", "Browse all…"),
    function () { _objfbOpenBrowser(state); }));
  _objfbFinishDd(state);
}

/** The captured browse page for a category, or null when there is nothing to
 *  browse. fb_browse.json is ONE page (the endpoint's own limit=20) of a
 *  collection whose `total` is 96 — _objfbRenderBrowse says so rather than
 *  padding the list out to the total. */
export function _objfbBrowseItems(cat) {
  if (cat === "label" && _browseSnap && Array.isArray(_browseSnap.items)) return _browseSnap.items;
  return null;
}

/** Everything captured for a category: the browse page plus the suggest
 *  response (fb_suggest was captured for q=web, so role=Web only exists there).
 *  Deduped by href, browse order first. */
export function _objfbCorpus(cat) {
  const browse = _objfbBrowseItems(cat) || [];
  const snap = (_suggestSnap && _suggestSnap.results && _suggestSnap.results[cat]) || null;
  const extra = (snap && snap.items) || [];
  if (!browse.length && !extra.length) return null;
  const seen = {};
  const out = [];
  browse.concat(extra).forEach(function (it) {
    const k = it.href || it.name;
    if (seen[k]) return;
    seen[k] = true;
    out.push(it);
  });
  return out;
}

function _objfbSuggestItem(cat, it) {
  const o = {};
  o.cat = cat;
  o.name = it.name;
  o.href = it.href || null;
  o.key = it.key || null;
  o.value = it.value || null;
  return o;
}

/* Full dropdown repaint for a non-empty input (src:782-865): IP/CIDR on top,
 * manual key=value, the service-column guidance, then the suggest groups. */
function _objfbRenderDropdown(state, q) {
  const main = state.els.ddMain;
  _fbClear(main);
  state.ddItems = [];
  const zoneCats = state.zone ? _objfbZoneCats(state, state.zone.col) : state.cats;
  // a bare number/range in the svc column already produces the three-way choice,
  // so the manual "Add Port" row must not be drawn twice
  const svcGroups = (state.zone && state.zone.col === "svc" && !state.scopeCat) ? _objfbSvcCandidates(q) : [];

  if (_objfbIsIpLike(q) && (!state.scopeCat || state.scopeCat === "ip") && state.zone && state.zone.col !== "svc") {
    _objfbAddDdGroup(state, [_catItem("ip", q)], "gui_fb_add_ipcidr", "Add IP/CIDR");
  } else if (!state.scopeCat || state.scopeCat === "label") {
    const eq = q.indexOf("=");
    if (eq > 0 && eq < q.length - 1) {
      const k = q.slice(0, eq).trim();
      const v = q.slice(eq + 1).trim();
      if (k && v) {
        const item = _catItem("label", q);
        item.key = k;
        item.value = v;
        _objfbAddDdGroup(state, [item], "gui_fb_cat_label", "Labels");
      }
    }
  } else if (state.scopeCat === "process" || state.scopeCat === "winservice") {
    const meta = _objfbCatMeta(state.scopeCat);
    _objfbAddDdGroup(state, [_catItem(state.scopeCat, q.trim())], meta[1], meta[3]);
  }
  if (_objfbIsPortLike(q) && state.cats.includes("port")
    && (!state.scopeCat || state.scopeCat === "service" || state.scopeCat === "port")
    && state.zone && state.zone.col === "svc"
    && !svcGroups.some(function (g) { return g.grp === "portproto"; })) {
    _objfbAddDdGroup(state, [_catItem("port", q.trim())], "gui_fb_add_port", "Add Port");
  }
  if (state.zone && (state.zone.col === "dst" || state.zone.col === "any") && state.cats.includes("transmission")
    && (!state.scopeCat || state.scopeCat === "transmission")) {
    const txItems = _objfbTxCandidates(q);
    if (txItems.length) _objfbAddDdGroup(state, txItems, "gui_fb_cat_transmission", "Transmission");
  }
  if (state.zone && state.zone.col === "svc" && !state.scopeCat) {
    svcGroups.forEach(function (grp) {
      if (grp.grp === "rangehint") {
        _objfbAddDdNote(main, "gui_fb_svc_range_hint", "Add \"-\" and an end port for a range");
        return;
      }
      const isPP = grp.grp === "portproto";
      _objfbAddDdGroup(state, grp.items,
        isPP ? "gui_fb_grp_portproto" : "gui_fb_grp_freetext",
        isPP ? "Port and/or Protocol" : "Process / Windows Service");
    });
  }

  // suggest groups, filtered to state.cats ∩ this zone's categories (src:838-839)
  _OBJFB_SUGGEST_CATS.filter(function (c) { return state.cats.includes(c) && zoneCats.includes(c); })
    .forEach(function (cat) {
      const items = _objfbSuggest(cat, q);
      if (!items.length) return;
      const meta = _objfbCatMeta(cat);
      _objfbAddDdGroup(state, items.map(function (it) { return _objfbSuggestItem(cat, it); }), meta[1], meta[3]);
    });

  if (!state.ddItems.length) {
    main.appendChild(_fbEl("div", "fb-dd-empty", _t("gui_fb_no_match", "No match")));
  }
  _objfbFinishDd(state);
}

/** Suggest results for a category, resolved from the captured snapshots.
 *  fb_suggest.json is one captured response (label only); fb_browse.json is the
 *  label corpus the substring match runs over, so typing behaves like the
 *  product without any row being invented. */
export function _objfbSuggest(cat, q) {
  const needle = String(q || "").trim().toLowerCase();
  if (!needle) return [];
  const corpus = _objfbCorpus(cat) || [];
  return corpus.filter(function (it) {
    return String(it.name || "").toLowerCase().indexOf(needle) >= 0;
  }).slice(0, 10);
}

function _objfbFinishDd(state) {
  state.actIdx = state.ddItems.length ? 0 : -1;
  _objfbMarkActive(state);
  state.els.dd.hidden = false;
}

function _objfbAddDdNote(target, key, fallback) {
  target.appendChild(_fbEl("div", "fb-dd-note", _t(key, fallback)));
}

function _objfbAddDdGroup(state, items, headerKey, headerFallback) {
  state.els.ddMain.appendChild(_fbEl("div", "fb-dd-hdr", _t(headerKey, headerFallback)));
  _objfbAddDdGroupItems(state, items);
}

function _objfbAddDdGroupItems(state, items) {
  const main = state.els.ddMain;
  items.forEach(function (o) {
    const el = _fbEl("div", "fb-dd-item");
    el.setAttribute("role", "option");
    const meta = _objfbCatMeta(o.cat);
    el.appendChild(_fbEl("span", "fb-cat", meta ? meta[2] : "?"));
    el.appendChild(_fbEl("span", "fb-dd-txt", o.summary ? o.name + " — " + o.summary : _objfbPillLabel(o)));
    if (o.tagI18n) el.appendChild(_fbEl("span", "fb-dd-tag" + (o.dflt ? " on" : ""), _t(o.tagI18n, "")));
    el.addEventListener("mousedown", function (e) { e.preventDefault(); });
    el.addEventListener("click", function () { _objfbPickItem(state, o); });
    main.appendChild(el);
    const rec = {};
    rec.o = o;
    rec.el = el;
    state.ddItems.push(rec);
  });
}

function _objfbMarkActive(state) {
  state.ddItems.forEach(function (it, i) { it.el.classList.toggle("on", i === state.actIdx); });
  if (state.actIdx >= 0) state.ddItems[state.actIdx].el.scrollIntoView({ block: "nearest" });
}

/* Pill edit popover: direction / include / exclude / remove. src:918-979 */
function _objfbOpenPop(state, idx, pillEl) {
  const pop = state.pop;
  const p = state.pills[idx];
  if (!p || !pillEl) return;
  state.popIdx = idx;
  _fbClear(pop);

  if (state.mode === "and" && !_OBJFB_DIRLESS.has(p.cat)) {
    const seg = _fbEl("div", "fb-seg");
    ["src", "dst"].forEach(function (d) {
      seg.appendChild(_fbBtn("fb-seg-btn" + (p.dir === d ? " on" : ""), _objfbZoneLabel(d, false), function () {
        _objfbPopAction(state, idx, "dir", d);
      }));
    });
    pop.appendChild(seg);
  }

  const negSeg = _fbEl("div", "fb-seg");
  negSeg.appendChild(_fbBtn("fb-seg-btn" + (!p.neg ? " on" : ""), _t("gui_fb_include", "Include"), function () {
    _objfbPopAction(state, idx, "neg", false);
  }));
  negSeg.appendChild(_fbBtn("fb-seg-btn danger" + (p.neg ? " on" : ""), _t("gui_fb_exclude", "Exclude"), function () {
    _objfbPopAction(state, idx, "neg", true);
  }));
  pop.appendChild(negSeg);

  pop.appendChild(_fbBtn("fb-pop-rm", _t("gui_fb_remove", "Remove"), function () {
    _objfbPopAction(state, idx, "remove", null);
  }));

  const cRect = state.container.getBoundingClientRect();
  const pRect = pillEl.getBoundingClientRect();
  pop.style.left = Math.max(0, pRect.left - cRect.left) + "px";
  pop.style.top = (pRect.bottom - cRect.top + 6) + "px";
  pop.hidden = false;
}

function _objfbPopAction(state, idx, action, val) {
  const p = state.pills[idx];
  if (!p) return;
  if (action === "dir") p.dir = val;
  else if (action === "neg") { p.neg = !!val; if (p.neg) state.exclOpen = true; }
  else if (action === "remove") state.pills.splice(idx, 1);

  _objfbRender(state);
  if (state.changeCb) state.changeCb();
  if (action !== "remove") {
    const pillEl = state.container.querySelector(".fb-pill[data-pill-idx=\"" + idx + "\"]");
    if (pillEl) _objfbOpenPop(state, idx, pillEl);
  }
}

/* Focus/typing (src:982-998): clicking or typing in a zone makes it the active
 * zone, which is what decides where the next pill lands. */
function _objfbFocusZone(state, col, neg) {
  const z = state.zoneEls[col + ":" + neg];
  if (!z) return;
  const changed = !state.zone || state.zone.col !== col || state.zone.neg !== neg;
  if (changed) {
    state.scopeCat = null;
    state._browseN = 0;
    Object.keys(state.zoneEls).forEach(function (k) { state.zoneEls[k].dd.hidden = true; });
  }
  state.zone = _objfbZone(col, neg);
  state.addZone = _objfbZone(col, neg);
  if (col !== "svc" && col !== "any") state.addDir = col;
  else if (col === "any") state.addDir = "any";
  state.els = z;
  z.input.focus();
  _objfbUpdateDropdown(state);
}

// src:1013-1053
function _objfbKeydown(state, col, neg, ev) {
  if (!state.els || !state.zone || state.zone.col !== col || state.zone.neg !== neg) _objfbFocusZone(state, col, neg);
  const key = ev.key;
  if (key === "ArrowDown") {
    ev.preventDefault();
    if (state.ddItems.length) { state.actIdx = (state.actIdx + 1) % state.ddItems.length; _objfbMarkActive(state); }
  } else if (key === "ArrowUp") {
    ev.preventDefault();
    if (state.ddItems.length) { state.actIdx = (state.actIdx - 1 + state.ddItems.length) % state.ddItems.length; _objfbMarkActive(state); }
  } else if (key === "Enter") {
    ev.preventDefault();
    if (state.actIdx >= 0 && state.ddItems[state.actIdx]) {
      _objfbPickItem(state, state.ddItems[state.actIdx].o);
      return;
    }
    const q = state.els.input.value.trim();
    if (col === "svc" && _objfbIsPortLike(q) && state.cats.includes("port")) {
      _objfbPickItem(state, _catItem("port", q));
    } else if (col !== "svc" && _objfbIsIpLike(q)) {
      _objfbPickItem(state, _catItem("ip", q));
    } else if (col !== "svc") {
      const eq = q.indexOf("=");
      if (eq > 0 && eq < q.length - 1) {
        const k = q.slice(0, eq).trim();
        const v = q.slice(eq + 1).trim();
        if (k && v) {
          const item = _catItem("label", q);
          item.key = k;
          item.value = v;
          _objfbPickItem(state, item);
        }
      }
    }
  } else if (key === "Escape") {
    state.els.dd.hidden = true;
    state.actIdx = -1;
  } else if (key === "Backspace" && !state.els.input.value) {
    if (state.scopeCat) { _objfbClearScope(state); return; }
    for (let i = state.pills.length - 1; i >= 0; i--) {
      const p = state.pills[i];
      if (_objfbPillCol(state, p) === col && p.neg === neg) {
        state.pills.splice(i, 1);
        _objfbRender(state);
        if (state.changeCb) state.changeCb();
        return;
      }
    }
  }
}

// src:1111-1122 — the repaint replaces the zone DOM, so the pre-add zone has to
// be re-focused or the caret is lost.
function _objfbPickItem(state, payload) {
  const z = state.zone;
  _objfbAddPill(state, payload);
  if (z && state.zoneEls[z.col + ":" + z.neg]) {
    state.zoneEls[z.col + ":" + z.neg].input.value = "";
    _objfbFocusZone(state, z.col, z.neg);
  }
}

// src:1055-1081
function _fbToggleMode(state) {
  state.anyLabelGroupHint = false;
  state.movedAnyHint = false;
  if (state.mode === "and") {
    // label_group cannot enter any (serialization fail-closes and drops it):
    // block the switch and say so, without touching the data
    if (state.pills.some(function (p) { return p.cat === "label_group"; })) {
      state.lgroupOrBlockHint = true;
      _objfbRender(state);
      return;
    }
    state.lgroupOrBlockHint = false;
    for (const p of state.pills) if (p.dir === "src" || p.dir === "dst") p.dir = "any";
    state.mode = "or";
  } else {
    state.lgroupOrBlockHint = false;
    let moved = 0;
    for (const p of state.pills) if (p.dir === "any") { p.dir = "src"; moved++; }
    state.mode = "and";
    state.movedAnyHint = moved > 0;
  }
  state.zone = null;
  _objfbRender(state);
  if (state.changeCb) state.changeCb();
}

// src:1083-1094 — transmission pills have dir null and are naturally unaffected.
function _fbSwapCols(state) {
  if (state.mode !== "and") return;
  for (const p of state.pills) {
    if (p.dir === "src") p.dir = "dst";
    else if (p.dir === "dst") p.dir = "src";
  }
  state.zone = null;
  _objfbRender(state);
  if (state.changeCb) state.changeCb();
}

function _objfbSetScope(state, cat) {
  if (!state.zone) return;
  state.scopeCat = cat;
  state._browseN = 0;
  const z = state.zone;
  _objfbRender(state);
  _objfbFocusZone(state, z.col, z.neg);
}

function _objfbClearScope(state) {
  if (!state.zone) return;
  state.scopeCat = null;
  state._browseN = 0;
  const z = state.zone;
  _objfbRender(state);
  _objfbFocusZone(state, z.col, z.neg);
}

function _objfbOpenBrowser(state) {
  if (state.els) state.els.dd.hidden = true;
  if (_openBrowser) _openBrowser(state);
}

/** Add a pill from outside (the object browser). src:1170-1177 */
export function addPillFromBrowser(state, obj) {
  const saved = state.zone;
  state.zone = state.addZone || _objfbZone(state.addDir || _objfbCols(state)[0], false);
  _objfbAddPill(state, obj);
  state.zone = saved;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PUBLIC API — same shape as production's createFilterBar (src:80-116), so the
//  parity test can drive both files through the identical call sequence.
// ═══════════════════════════════════════════════════════════════════════════

const _OBJFB_DEFAULT_CATS = ["label", "label_group", "iplist", "workload", "ip",
  "service", "port", "process", "winservice", "transmission"];

function _objfbNewState(id, container, cats) {
  const s = {};
  s.id = id;
  s.container = container;
  s.cats = cats;
  s.pills = [];
  // mode: 'and' = separate Source/Destination columns; 'or' = one merged
  // Source OR Destination column. dirs/addDir are derived by _objfbRender and
  // kept for the object browser's benefit. zone = the active {col, neg}.
  s.mode = "and";
  s.dirs = ["src", "dst"];
  s.addDir = "src";
  s.zone = null;
  s.zoneEls = {};
  s.exclOpen = false;
  s.scopeCat = null;
  s.changeCb = null;
  return s;
}

export function createFilterBar(container, options) {
  const opts = options || {};
  const cats = opts.cats || _OBJFB_DEFAULT_CATS;
  const id = "objfb-" + (++_objfbSeq);
  const state = _objfbNewState(id, container, cats);
  _objfbInstances[id] = state;
  container.dataset.objfbId = id;
  container.classList.add("fb");
  if (opts.initial) _objfbDeserialize(state, opts.initial);
  _objfbRender(state);
  const api = {};
  api.getFilters = function () { return _objfbSerialize(state); };
  api.setFilters = function (dict) { _objfbDeserialize(state, dict); _objfbRender(state); };
  api.onChange = function (cb) { state.changeCb = cb; };
  api.destroy = function () { delete _objfbInstances[id]; _fbClear(container); };
  return api;
}

// Window handlers, named as production names them (src:1001-1182). The mockup
// does not need a CSP dispatcher — listeners are bound directly — but the
// parity test drives BOTH files through these, so the names must match.
if (typeof window !== "undefined") {
  window.createFilterBar = createFilterBar;
  window._objfbGetInstance = function (id) { return _objfbInstances[id] || null; };
  window._objfbToggleMode = function (id) { const s = _objfbInstances[id]; if (s) _fbToggleMode(s); };
  window._objfbSwapCols = function (id) { const s = _objfbInstances[id]; if (s) _fbSwapCols(s); };
  window._objfbAddPillPublic = addPillFromBrowser;

  // Close dropdowns and the popover on an outside click (src:1186-1197). A
  // handler that repaints detaches the event target first; a detached target
  // was inside the bar, so it must not be read as an outside click.
  document.addEventListener("click", function (e) {
    if (!e.target.isConnected) return;
    Object.keys(_objfbInstances).forEach(function (id) {
      const s = _objfbInstances[id];
      Object.keys(s.zoneEls).forEach(function (k) {
        if (!s.zoneEls[k].bar.contains(e.target)) s.zoneEls[k].dd.hidden = true;
      });
      if (s.pop && !s.pop.contains(e.target) && !e.target.closest(".fb-pill")) s.pop.hidden = true;
    });
  });
}

export const filterBar = {
  create: createFilterBar,
  setText: setFilterBarText,
  setSnapshots: setFilterBarSnapshots,
  setBrowser: setFilterBarBrowser,
};
