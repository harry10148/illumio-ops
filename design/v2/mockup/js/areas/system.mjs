// system.mjs — #/system/{pce,cache,siem,tls,security,display,channels,logs}.
// Anchors SY-01…SY-18 plus XC-05 (theme/density) and XC-06 (timezone/language).
//
// Every sub-route uses ONE page shape — sectioned cards over a docked save row —
// because the product's settings surfaces are three different shapes today
// (settings.js's four sub-panels with a sticky bar, integrations.js's cache form
// with a bare Save button and no dirty tracking at all, and the SIEM section
// with a second Save of its own). One shape means "where do I press save" has
// the same answer on all eight pages.
//
// THE DIRTY LEDGER is this area's one deliberate device. The product's bar can
// only say how many SECTIONS are dirty (settings.js:24-61) and integrations.js
// cannot say anything (grep: no dirty flag, no beforeunload, cacheSave posts
// whatever the form happens to hold). Here the bar names every changed key with
// its old and new value, because a settings page that cannot tell you what you
// are about to write is a page you have to verify somewhere else.
//
// HONESTY RULES (Task 7 report §9.9):
//   * Nothing here writes. Save commits the in-memory baseline, prints the exact
//     request body in the page's 送出內容 pane and says the request was not sent.
//   * Secrets are never reconstructed. The snapshots carry the server's redaction
//     (***MASKED*** plus the __set/__length siblings); the forms show set/not-set
//     and the length, never a value.
//   * Anything not transcribed from the product is marked DESIGN-ADDED where it
//     is decided.

import { el, clear, spacer } from "../core/dom.mjs";
import { t, tf, i18n } from "../core/i18n.mjs";
import { num } from "../core/fmt.mjs";
import { store } from "../core/store.mjs";
import { router } from "../core/router.mjs";
import { toast } from "../core/toast.mjs";
import { theme, density } from "../core/theme.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { verifyPane } from "../components/verifypane.mjs";
import { areaHead } from "./placeholder.mjs";

const R_PCE = "#/system/pce";
const R_CACHE = "#/system/cache";
const R_SIEM = "#/system/siem";
const R_TLS = "#/system/tls";
const R_SECURITY = "#/system/security";
const R_DISPLAY = "#/system/display";
const R_CHANNELS = "#/system/channels";
const R_LOGS = "#/system/logs";

// index.html:1975-1983 (integrations sub-tabs) + :1994-2008 (settings sub-tabs).
// The product splits the same concerns across two top-level tabs; v2 keeps one
// sub-nav so "where do I configure X" has a single list.
const SUB_ROUTES = [
  [R_PCE, "gui_settings_tab_pce"],
  [R_CACHE, "gui_it_cache"],
  [R_SIEM, "gui_siem_forwarder"],
  [R_TLS, "gui_tls_title"],
  [R_SECURITY, "gui_settings_tab_security"],
  [R_DISPLAY, "gui_settings_tab_display"],
  [R_CHANNELS, "gui_settings_tab_channels"],
  [R_LOGS, "gui_ml_title"],
];

// ── shared chrome ───────────────────────────────────────────────────────────
function panel(cov, title) {
  const head = el("div", { class: "panel-h" }, el("h3", { title: title, text: title }));
  const body = el("div", { class: "panel-b" });
  const root = el("section", { class: "panel", "data-cov": cov || null }, head, body);
  root.head = head;
  root.body = body;
  return root;
}

function withMeta(p, text) {
  p.head.appendChild(el("span", { class: "meta", title: text, text: text }));
  return p;
}

function note(text) { return el("p", { class: "note", text: text }); }
function btn(cls, text, onClick) { return el("button", { class: cls, type: "button", text: text, onClick: onClick }); }
function badge(text, tn) { return el("span", { class: "badge", "data-tone": tn }, el("i", { class: "dot" }), el("span", { text: text })); }
function sectionHead(text) { return el("h4", { class: "eyebrow", text: text }); }

function sysTop(active) {
  const head = areaHead(t("v2_nav_system"), active);
  const nav = el("nav", { class: "subnav wrap", "aria-label": t("v2_nav_system") });
  SUB_ROUTES.forEach(function (pair) {
    const a = el("a", { href: pair[0], text: t(pair[1]) });
    if (pair[0] === active) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });
  head.appendChild(nav);
  return head;
}

function labelled(labelText, control, hint) {
  const box = el("div", { class: "fld" });
  const lab = el("label", null, el("span", { text: labelText }));
  box.appendChild(lab);
  box.appendChild(control);
  if (hint) box.appendChild(el("small", { class: "hint", text: hint }));
  box.lab = lab;
  return box;
}

function textField(value) {
  const input = el("input", { class: "field", type: "text" });
  input.value = value === null || value === undefined ? "" : String(value);
  return input;
}

function numberField(value, min, max) {
  const input = el("input", { class: "field", type: "number" });
  if (min !== null && min !== undefined) input.min = String(min);
  if (max !== null && max !== undefined) input.max = String(max);
  input.value = value === null || value === undefined ? "" : String(value);
  return input;
}

function passwordField(placeholder) {
  const input = el("input", { class: "field", type: "password", placeholder: placeholder || "" });
  return input;
}

function checkField(value) {
  const input = el("input", { type: "checkbox" });
  input.checked = !!value;
  return input;
}

function checkRow(labelText, input, hint) {
  const row = el("div", { class: "fld" }, el("label", { class: "chk" }, input, el("span", { text: labelText })));
  if (hint) row.appendChild(el("small", { class: "hint", text: hint }));
  return row;
}

function selectField(pairs, value, translate) {
  const sel = el("select", { class: "field" });
  pairs.forEach(function (pair) {
    const opt = el("option", { value: pair[0], text: translate === false ? pair[1] : t(pair[1]) });
    if (String(value) === String(pair[0])) opt.selected = true;
    sel.appendChild(opt);
  });
  return sel;
}

function radioGroup(name, pairs, value, onChange) {
  const box = el("div", { class: "radios" });
  pairs.forEach(function (pair) {
    const input = el("input", { type: "radio", name: name, value: pair[0] });
    if (String(value) === String(pair[0])) input.checked = true;
    if (onChange) input.addEventListener("change", function () { if (input.checked) onChange(input.value); });
    box.appendChild(el("label", null, input, el("span", { text: t(pair[1]) })));
  });
  return box;
}

function drawerSpec(title, body, onSave) {
  const spec = {};
  spec.title = title;
  spec.body = body;
  if (onSave) spec.onSave = onSave;
  return spec;
}

function confirmSpec(title, impact, onOk) {
  const spec = {};
  spec.title = title;
  spec.impact = impact;
  spec.onOk = onOk;
  return spec;
}

function cmdSpec(id, label, run) {
  const spec = {};
  spec.id = id;
  spec.label = label;
  spec.run = run;
  return spec;
}

function buildCell(fn) { const o = {}; o.cell = fn; return o; }
function widthCell(width, fn) { const o = {}; o.width = width; if (fn) o.cell = fn; return o; }
function buildTable(columns, rows) { const spec = {}; spec.columns = columns; spec.rows = rows; return spec; }

function pagedTable(columns, rows, page, onPage) {
  const spec = {};
  spec.columns = columns;
  spec.rows = rows;
  spec.page = page;
  spec.onPage = onPage;
  return spec;
}

function pageSpec(index, size, total) {
  const p = {};
  p.index = index;
  p.size = size;
  p.total = total;
  return p;
}

function loadAll(ids) {
  return Promise.all(ids.map(function (id) { return store.load(id); })).then(function (list) {
    const out = {};
    ids.forEach(function (id, i) { out[id] = list[i]; });
    return out;
  });
}

function showValue(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** A backend field this form deliberately does not control, with the reason. */
function roField(key, value, noteText) {
  const li = el("li");
  li.appendChild(el("code", { class: "c", text: key }));
  const v = el("span", { class: "s", text: showValue(value) });
  v.dataset.field = key;
  li.appendChild(v);
  li.appendChild(el("span", { class: "r", text: noteText }));
  return li;
}

function roList(rows) { return el("ul", { class: "stack rofields" }, rows); }

function kvRow(label, value, tn) {
  const b = el("b", { text: showValue(value) });
  if (tn) b.dataset.tone = tn;
  return el("div", { class: "kv" }, el("span", { text: label }), b);
}

// ══════════════════════════════════════════════════ the settings form ════════

/* readCtl / writeCtl are the only two places that know what an <input> means,
 * so a new control type is one edit rather than one edit per page. */
function readCtl(c) {
  if (c.type === "checkbox") return c.checked;
  return c.value;
}

function writeCtl(c, v) {
  if (c.type === "checkbox") c.checked = !!v;
  else c.value = v === null || v === undefined ? "" : String(v);
}

/* Coercion mirrors what the shipping save handlers do before they POST:
 * numbers through Number() (integrations.js:272-283), checkboxes through
 * .checked (:270), everything else raw. `kind` is set by the caller because the
 * DOM cannot tell a comma list from a plain string. */
// The mask a secret wears everywhere it is displayed. Nothing in this area ever
// prints a typed secret: not the dirty ledger, not the payload pane. The ledger
// is the reason this exists — it names every changed key with its old and new
// value, and "new value" for a credential must never be the credential.
const SECRET_MASK = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022";

function coerce(item) {
  const raw = readCtl(item.c);
  if (item.kind === "secret") return String(raw).length ? SECRET_MASK : "";
  if (item.kind === "number") return raw === "" ? null : Number(raw);
  if (item.kind === "bool") return !!raw;
  if (item.kind === "list") {
    return String(raw).split(",").map(function (s) { return s.trim(); }).filter(function (s) { return s.length > 0; });
  }
  if (item.kind === "ports") {
    // Trim and drop the blanks BEFORE Number(): "".split(",") is [""], and
    // Number("") is 0, so an empty field would otherwise serialise as [0] — a
    // port filter that silently matches port 0 instead of matching nothing.
    return String(raw).split(",").map(function (s) { return s.trim(); })
      .filter(function (s) { return s.length > 0; })
      .map(function (s) { return Number(s); })
      .filter(function (n) { return isFinite(n); });
  }
  return raw;
}

/** What the ledger is allowed to show for one tracked control. */
function ledgerValue(item, raw) {
  if (item.kind !== "secret") return showValue(raw);
  return String(raw === null || raw === undefined ? "" : raw).length ? SECRET_MASK : "\u2014";
}

function makeForm(method, endpoint) {
  const items = [];
  const api = {};
  let bodyFn = null;
  let syncFn = null;

  const count = el("b", { class: "mono" });
  const label = el("span");
  const diff = el("div", { class: "savediff" });
  const discard = btn("btn ghost", t("v2_sy_discard"), function () { api.discard(); });
  const save = btn("btn primary", t("gui_save"), function () { api.save(); });
  const bar = el("div", { class: "savebar", "data-tone": "neutral" },
    el("span", { class: "dot" }), label, count, diff, spacer(), discard, save);
  const payload = el("pre", { class: "codepane tall" });

  // The bar is fixed to the viewport bottom, so it would sit on top of the last
  // panel; `dock` is the in-flow placeholder that reserves its height.
  const dock = el("div", { class: "savedock" }, bar);
  api.bar = bar;
  api.dock = dock;
  api.payload = payload;

  /** track(key, control, kind) — kind: text|number|bool|list|ports */
  api.track = function (key, control, kind) {
    const item = {};
    item.key = key;
    item.c = control;
    item.kind = kind || "text";
    item.base = readCtl(control);
    control.dataset.field = key;
    control.addEventListener("input", api.sync);
    control.addEventListener("change", api.sync);
    items.push(item);
    return control;
  };

  api.changed = function () {
    return items.filter(function (i) { return String(readCtl(i.c)) !== String(i.base); });
  };

  api.values = function () {
    const out = {};
    items.forEach(function (i) { out[i.key] = coerce(i); });
    return out;
  };

  api.setBody = function (fn) { bodyFn = fn; return api; };
  api.onSync = function (fn) { syncFn = fn; return api; };

  api.sync = function () {
    const changes = api.changed();
    bar.dataset.tone = changes.length ? "warn" : "neutral";
    count.textContent = changes.length ? String(changes.length) : "";
    label.textContent = changes.length ? t("v2_sy_dirty") : t("v2_sy_clean");
    discard.disabled = !changes.length;
    save.disabled = !changes.length;
    clear(diff);
    changes.slice(0, 5).forEach(function (i) {
      diff.appendChild(el("span", { class: "chg" },
        el("code", { text: i.key }),
        el("s", { text: ledgerValue(i, i.base) }),
        el("i", { text: "→" }),
        el("b", { text: ledgerValue(i, readCtl(i.c)) })));
    });
    if (changes.length > 5) diff.appendChild(el("span", { class: "chg", text: tf("v2_sy_more", { n: changes.length - 5 }) }));
    const body = bodyFn ? bodyFn(api.values()) : api.values();
    payload.textContent = method + " " + endpoint + "\n" + JSON.stringify(body, null, 2);
    if (syncFn) syncFn(changes);
  };

  api.discard = function () {
    items.forEach(function (i) { writeCtl(i.c, i.base); });
    api.sync();
    toast.info(t("v2_sy_discarded"));
  };

  api.save = function () {
    const n = api.changed().length;
    items.forEach(function (i) { i.base = readCtl(i.c); });
    api.sync();
    toast.ok(tf("v2_sy_saved", { n: n, endpoint: endpoint }));
    if (api.afterSave) api.afterSave();
  };

  return api;
}

/** The 送出內容 pane every settings page ends with. */
function payloadPanel(form, srcNote) {
  const p = panel(null, t("v2_sy_payload"));
  p.body.appendChild(verifyPane(form.payload));
  p.body.appendChild(note(t("v2_sy_mock_save")));
  if (srcNote) p.body.appendChild(note(srcNote));
  return p;
}

async function sysPage(root, ctx, route, snaps, build) {
  root.appendChild(sysTop(route));
  const board = el("div", { class: "board" });
  root.appendChild(board);
  await withErrorCard(board, route + " (" + snaps.length + ")",
    function () { return loadAll(snaps); },
    function (d) {
      if (ctx.stale()) return;
      build(board, d, root);
    });
}

// ══════════════════════════════════════════════════ SY-01 / SY-18  PCE ═══════

/* settings.js:370-383 — the add form. addPceProfile (:753-773) posts
 * {action:'add', name, url, org_id, key, secret, verify_ssl}; the backend also
 * supports 'update' (config.py:459-471) but no UI reaches it. */
function pceDrawer() {
  const body = el("div");
  const form = makeForm("POST", "/api/pce-profiles");
  const name = textField("");
  const url = textField("");
  const org = textField("1");
  const key = passwordField("");
  const secret = passwordField("");
  const ssl = checkField(true);

  form.setBody(function (v) {
    const b = {};
    b.action = "add";
    b.name = v.name;
    b.url = v.url;
    b.org_id = v.org_id || "1";
    b.key = v.key;
    b.secret = v.secret;
    b.verify_ssl = v.verify_ssl;
    return b;
  });

  body.appendChild(note(t("v2_sy_pce_add_src")));
  body.appendChild(sectionHead(t("gui_pce_add")));
  body.appendChild(labelled(t("gui_pce_name"), form.track("name", name)));
  body.appendChild(labelled(t("gui_url"), form.track("url", url), t("v2_sy_pce_url_rule")));
  body.appendChild(labelled(t("gui_org_id"), form.track("org_id", org)));
  body.appendChild(labelled(t("gui_api_key"), form.track("key", key, "secret")));
  body.appendChild(labelled(t("gui_api_secret"), form.track("secret", secret, "secret"), t("v2_sy_secret_hint")));
  body.appendChild(checkRow(t("gui_verify_ssl"), form.track("verify_ssl", ssl, "bool")));
  body.appendChild(sectionHead(t("v2_sy_payload")));
  body.appendChild(verifyPane(form.payload));
  body.appendChild(note(t("v2_sy_mock_save")));
  form.sync();
  return drawerSpec(t("gui_pce_add"), body, function () {
    toast.info(t("v2_sy_mock_save"));
    return true;
  });
}

async function mountPce(root, ctx) {
  const handles = {};
  drawer.registerAudit("sy-pce-add", function () { return drawer.open(pceDrawer()); });
  modal.registerAudit("sy-pce-activate", function () { return handles.activate ? handles.activate() : null; });
  palette.registerFor(R_PCE, cmdSpec("sy:pce-add", t("gui_pce_add"), function () { drawer.open(pceDrawer()); }));

  await sysPage(root, ctx, R_PCE, ["settings", "pce_profiles", "status"], function (board, d, host) {
    const s = d.settings || {};
    const api = s.api || {};
    const profiles = (d.pce_profiles && d.pce_profiles.profiles) || [];
    const activeId = (d.pce_profiles && d.pce_profiles.active_pce_id) || null;

    const form = makeForm("POST", "/api/settings");
    form.bar.dataset.cov = "SY-18";

    // ── SY-01 profiles ─────────────────────────────────────────────────
    const profPanel = panel("SY-01", t("gui_settings_tab_pce"));
    withMeta(profPanel, tf("v2_sy_pce_meta", { n: profiles.length }));
    const profHost = el("div");
    profPanel.body.appendChild(profHost);
    profPanel.head.appendChild(btn("btn", t("gui_pce_add"), function () { drawer.open(pceDrawer()); }));

    /* settings.js:775-783 activatePceProfile fires with NO confirmation.
     * DESIGN-ADDED: switching the active PCE re-points every query, report and
     * alert on the appliance, so v2 states the blast radius first. */
    handles.activate = function () {
      const p = profiles[0] || null;
      const nameText = p ? p.name : t("v2_sy_pce_none");
      return modal.confirm(confirmSpec(t("gui_pce_activate"), [
        tf("v2_sy_pce_i_switch", { name: nameText }),
        t("v2_sy_pce_i_queries"),
        t("v2_sy_pce_i_cache"),
        t("v2_sy_pce_i_nocfm"),
      ], function () {
        toast.info(t("v2_sy_mock_save"));
        return true;
      }));
    };

    if (!profiles.length) {
      profHost.appendChild(el("div", { class: "empty" },
        el("span", { class: "et", text: t("v2_sy_pce_none") }),
        el("p", { text: t("v2_sy_pce_none_body") })));
      profPanel.body.appendChild(btn("btn ghost", t("gui_pce_activate"), handles.activate));
    } else {
      const columns = [
        col("name", t("gui_pce_name"), widthCell(160)),
        col("url", t("gui_url"), buildCell(function (p) { return el("span", { title: p.url, text: p.url }); })),
        col("org_id", t("gui_org_id"), widthCell(80)),
        col("act", t("gui_actions"), widthCell(190, function (p) {
          const box = el("div", { class: "rowacts" });
          if (p.id !== activeId) box.appendChild(btn("btn", t("gui_pce_activate"), handles.activate));
          else box.appendChild(badge(t("gui_pce_active"), "ok"));
          box.appendChild(btn("btn danger", t("gui_pce_delete_profile"), function () {
            modal.confirm(confirmSpec(t("gui_msg_confirm_delete"),
              [tf("v2_sy_pce_i_del", { name: p.name })], function () {
                toast.info(t("v2_sy_mock_save"));
                return true;
              }));
          }));
          return box;
        })),
      ];
      table.render(profHost, buildTable(columns, profiles));
    }
    profPanel.body.appendChild(note(t("v2_sy_pce_switch_bug")));
    board.appendChild(profPanel);

    // ── API connection (settings.js:386-390) ───────────────────────────
    const connPanel = panel(null, t("gui_api_conn"));
    const url = textField(api.url);
    const org = textField(api.org_id);
    // Never re-displayed: the snapshot's api.key is already the server's mask
    // (config.py:428-431). An empty box plus the state row below says more and
    // leaks nothing.
    const key = passwordField(t("v2_sy_secret_keep"));
    const secret = passwordField(t("v2_sy_secret_keep"));
    const ssl = checkField(api.verify_ssl);
    connPanel.body.appendChild(labelled(t("gui_url"), form.track("url", url), t("gui_url_help")));
    connPanel.body.appendChild(labelled(t("gui_org_id"), form.track("org_id", org), t("gui_org_id_help")));
    connPanel.body.appendChild(labelled(t("gui_api_key"), form.track("key", key, "secret"), t("gui_api_key_help")));
    connPanel.body.appendChild(labelled(t("gui_api_secret"), form.track("secret", secret, "secret"), t("gui_api_secret_help")));
    connPanel.body.appendChild(checkRow(t("gui_verify_ssl"), form.track("verify_ssl", ssl, "bool")));
    // The captured settings snapshot carries the server's redaction, not values:
    // config.py:428-431 replaces every secret with asterisks and adds __set /
    // __length siblings. The form states set/not-set instead of pretending.
    connPanel.body.appendChild(sectionHead(t("v2_sy_secret_state")));
    connPanel.body.appendChild(roList([
      roField("api.key", secretState(api, "key"), t("v2_sy_secret_short")),
      roField("api.secret", secretState(api, "secret"), t("v2_sy_secret_short")),
      roField("api.profile", api.profile, t("v2_sy_pce_profile_field")),
      roField("active_pce_id", activeId, t("v2_sy_pce_active_field")),
    ]));
    connPanel.body.appendChild(note(t("v2_sy_secret_note")));
    connPanel.body.appendChild(note(t("v2_sy_pce_save_note")));
    board.appendChild(connPanel);

    form.setBody(function (v) {
      const b = {};
      const apiPart = {};
      apiPart.url = v.url;
      apiPart.org_id = v.org_id;
      apiPart.key = v.key;
      apiPart.secret = v.secret;
      apiPart.verify_ssl = v.verify_ssl;
      b.api = apiPart;
      return b;
    });

    board.appendChild(payloadPanel(form, t("v2_sy_pce_payload_src")));
    host.appendChild(form.dock);
    form.sync();
  });
}

/** config.py:428-431 — <field>__set / <field>__length are what the redactor
 *  leaves behind. The product's forms ignore them and put the mask in the box. */
function secretState(obj, key) {
  const set = obj[key + "__set"];
  const len = obj[key + "__length"];
  if (set) return tf("v2_sy_secret_set", { n: Number(len || 0) });
  return t("v2_sy_secret_unset");
}

// ══════════════════════════════════════════ SY-02…06 / SY-17  cache ══════════

// integrations.js:460-461 — the two fixed checkbox sets of the traffic filter.
const TF_ACTIONS = ["blocked", "potentially_blocked", "allowed"];
const TF_PROTOCOLS = ["TCP", "UDP", "ICMP"];

/* validateIp, integrations.js:521-526, transcribed exactly — including the two
 * things it gets wrong, which the hint under the field now says out loud:
 *   · CIDR is REJECTED (there is no "/" in either character class) even though
 *     gui_cache_exclude_src_ips_help promises "CIDR or exact", and
 *     config_models.py:219-227 rejects it server-side too.
 *   · The IPv6 branch accepts any hex-and-colon string, so "::::" passes. */
function validateIp(s) {
  if (/^(\d{1,3}\.){3}\d{1,3}$/.test(s)) {
    return s.split(".").every(function (o) { return Number(o) <= 255; });
  }
  return /^[\da-fA-F:]+$/.test(s) && s.indexOf(":") >= 0;
}

/** integrations.js:528-541 — hints joined with " · ", one per offending token. */
function trafficFilterHints(ipsRaw, portsRaw) {
  const hints = [];
  String(ipsRaw || "").split(",").map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length > 0; })
    .forEach(function (ip) { if (!validateIp(ip)) hints.push(t("gui_err_invalid_ip") + ": " + ip); });
  String(portsRaw || "").split(",").map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length > 0; })
    .forEach(function (p) {
      const n = Number(p);
      if (!Number.isInteger(n) || n < 1 || n > 65535) hints.push(t("gui_err_port_range") + ": " + p);
    });
  return hints;
}

/** integrations.js:161-166 — the lag readout's own duration format. */
function fmtLag(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m";
  return Math.floor(s / 3600) + "h";
}

async function mountCache(root, ctx) {
  const handles = {};
  modal.registerAudit("sy-cache-retention", function () { return handles.retention ? handles.retention() : null; });
  modal.registerAudit("sy-cache-restart", function () { return handles.restart ? handles.restart() : null; });
  palette.registerFor(R_CACHE, cmdSpec("sy:retention", t("gui_retention_now"), function () { if (handles.retention) handles.retention(); }));

  await sysPage(root, ctx, R_CACHE,
    ["cache_settings", "cache_status", "cache_lag", "cache_throughput", "cache_health"],
    function (board, d, host) {
      const s = d.cache_settings || {};
      const st = d.cache_status || {};
      const tp = d.cache_throughput || {};
      const tf0 = s.traffic_filter || {};
      const ts = s.traffic_sampling || {};
      const form = makeForm("PUT", "/api/cache/settings");

      // ── SY-17 status cards + lag row ─────────────────────────────────
      const statPanel = panel("SY-17", t("gui_cache_status"));
      const cards = el("div", { class: "kpirow" });
      /* integrations.js:117 — only card 1 changes tone (enabled/disabled);
       * cards 2-4 are hardcoded card-ok, so no threshold is invented here. */
      cards.appendChild(kpiCell(t("gui_cache_status"), s.enabled ? t("gui_cache_enabled") : t("gui_cache_disabled"), null, s.enabled ? "ok" : "crit"));
      cards.appendChild(kpiCell(t("gui_ov_events"), num(st.events), oneHour(tp.events_1h), null));
      cards.appendChild(kpiCell(t("gui_cache_card_traffic_raw"), num(st.traffic_raw), oneHour(tp.traffic_raw_1h), null));
      cards.appendChild(kpiCell(t("gui_cache_card_traffic_agg"), num(st.traffic_agg), oneHour(tp.traffic_agg_1h), null));
      statPanel.body.appendChild(cards);
      statPanel.body.appendChild(note(t("v2_sy_cache_1h_bug")));

      // integrations.js:157-180 — one entry per source; last_status="error"
      // overrides the level colour and appends ⚠, because a failed ingest still
      // bumps last_sync_at and would otherwise read as healthy (:168-169).
      const lag = (d.cache_lag && d.cache_lag.sources) || [];
      const lagRow = el("div", { class: "strip", "data-tone": "info" },
        el("span", { text: t("gui_cache_ingest_lag") }));
      lag.forEach(function (row) {
        const bad = row.last_status === "error";
        const tn = bad ? "crit" : (row.level === "warning" ? "warn" : (row.level === "ok" ? "ok" : "neutral"));
        const item = el("span", { class: "lagitem", "data-tone": tn, title: row.last_error || "" },
          el("span", { text: row.source }),
          el("b", { text: fmtLag(row.lag_seconds) + (bad ? " ⚠" : "") }));
        lagRow.appendChild(item);
      });
      if (!lag.length) lagRow.appendChild(el("span", { text: t("gui_it_none") }));
      statPanel.body.appendChild(lagRow);
      statPanel.body.appendChild(note(t("v2_sy_cache_lag_note")));
      // The capacity figures the retention and disk-free thresholds below are
      // judged against (/api/cache/health, cache_health.json). They are the
      // reading that makes disk_free_warn_gb a number worth setting.
      const cap = (d.cache_health && d.cache_health.capacity) || {};
      statPanel.body.appendChild(sectionHead(t("v2_sy_cache_capacity")));
      statPanel.body.appendChild(kvRow(t("v2_sy_cache_db_bytes"), mib(cap.db_bytes)));
      statPanel.body.appendChild(kvRow(t("v2_sy_cache_disk_free"), mib(cap.disk_free_bytes),
        Number(cap.disk_free_bytes || 0) / 1073741824 < Number(s.disk_free_warn_gb || 0) ? "warn" : "ok"));
      statPanel.body.appendChild(kvRow(t("v2_sy_cache_siem_pending"), num(cap.siem_pending),
        Number(cap.siem_pending || 0) > Number(s.siem_pending_warn_rows || 0) ? "warn" : "ok"));
      board.appendChild(statPanel);

      // ── SY-03 restart banner + SY-04 retention ───────────────────────
      const opsPanel = panel("SY-03", t("gui_it_restart_monitor"));
      const banner = el("div", { class: "strip", "data-tone": "warn", hidden: true },
        el("span", { text: t("gui_it_restart_saved") }));
      banner.appendChild(spacer());
      banner.appendChild(btn("btn primary", t("gui_it_restart_monitor"), function () { handles.restart(); }));
      banner.appendChild(btn("btn ghost", t("gui_dismiss"), function () { banner.hidden = true; }));
      opsPanel.body.appendChild(banner);
      /* showRestartBanner is called on EVERY successful save (integrations.js:300)
       * and the backend hardcodes requires_restart:true
       * (gui/settings_helpers.py:23) — there is no per-field restart detection,
       * so the banner cannot tell you whether YOUR change needs one. */
      opsPanel.body.appendChild(note(t("v2_sy_cache_restart_always")));
      handles.restart = function () {
        return modal.confirm(confirmSpec(t("gui_it_restart_monitor"), [
          t("v2_sy_restart_i_poll"),
          t("v2_sy_restart_i_rate"),
          t("v2_sy_restart_i_409"),
        ], function () {
          toast.info(t("v2_sy_mock_save"));
          banner.hidden = true;
          return true;
        }));
      };
      opsPanel.body.appendChild(el("div", { class: "typechips" },
        btn("btn", t("v2_sy_cache_show_banner"), function () { banner.hidden = false; }),
        btn("btn primary", t("gui_it_restart_monitor"), function () { handles.restart(); })));
      opsPanel.body.appendChild(note(t("gui_daemon_external_restart_hint")));

      const retPanel = panel("SY-04", t("gui_retention_now"));
      retPanel.body.appendChild(note(t("gui_it_retention_confirm")));
      /* cacheRetentionNow (integrations.js:437-452) sends no body — the days come
       * from server-side config — and reports only four of the six counters
       * RetentionWorker.run_once returns (retention.py:67-110). */
      handles.retention = function () {
        return modal.confirm(confirmSpec(t("gui_retention_now"), [
          tf("v2_sy_ret_i_events", { n: s.events_retention_days }),
          tf("v2_sy_ret_i_raw", { n: s.traffic_raw_retention_days }),
          tf("v2_sy_ret_i_agg", { n: s.traffic_agg_retention_days }),
          t("v2_sy_ret_i_nobody"),
          t("v2_sy_ret_i_409"),
        ], function () {
          toast.info(t("v2_sy_mock_save"));
          return true;
        }));
      };
      retPanel.body.appendChild(btn("btn danger", t("gui_retention_now"), handles.retention));
      retPanel.body.appendChild(note(t("v2_sy_ret_counters")));
      const row1 = el("div", { class: "brow c2 top" }, opsPanel, retPanel);
      board.appendChild(row1);

      // ── SY-02 the settings form ──────────────────────────────────────
      const cfgPanel = panel("SY-02", t("gui_cache_settings"));
      const enabled = checkField(s.enabled);
      const dbPath = textField(s.db_path);
      const evRet = numberField(s.events_retention_days, 1, null);
      const rawRet = numberField(s.traffic_raw_retention_days, 1, null);
      const aggRet = numberField(s.traffic_agg_retention_days, 1, null);
      const arcOn = checkField(s.archive_enabled);
      const arcDir = textField(s.archive_dir);
      const arcInt = numberField(s.archive_interval_hours, 1, null);
      const arcGzip = numberField(s.archive_gzip_after_days, 1, null);
      const arcRet = numberField(s.archive_retention_days, 0, null);
      const evPoll = numberField(s.events_poll_interval_seconds, 30, null);
      const trPoll = numberField(s.traffic_poll_interval_seconds, 60, null);
      const rate = numberField(s.rate_limit_per_minute, 10, 500);
      const asyncTh = numberField(s.async_threshold_events, 1, 10000);

      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_basic")));
      cfgPanel.body.appendChild(checkRow(t("gui_cache_enabled"), form.track("enabled", enabled, "bool")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_db_path"), form.track("db_path", dbPath), t("gui_cache_db_path_help")));
      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_retention")));
      cfgPanel.body.appendChild(labelled(t("gui_ov_events"), form.track("events_retention_days", evRet, "number"), t("gui_cache_events_retention_days_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_card_traffic_raw"), form.track("traffic_raw_retention_days", rawRet, "number"), t("gui_cache_traffic_raw_retention_days_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_card_traffic_agg"), form.track("traffic_agg_retention_days", aggRet, "number"), t("gui_cache_traffic_agg_retention_days_help")));
      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_archive")));
      cfgPanel.body.appendChild(checkRow(t("gui_cache_archive_enabled"), form.track("archive_enabled", arcOn, "bool")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_archive_dir"), form.track("archive_dir", arcDir), t("gui_cache_archive_dir_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_archive_interval_hours"), form.track("archive_interval_hours", arcInt, "number"), t("gui_cache_archive_interval_hours_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_archive_gzip_after_days"), form.track("archive_gzip_after_days", arcGzip, "number"), t("gui_cache_archive_gzip_after_days_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_archive_retention_days"), form.track("archive_retention_days", arcRet, "number"), t("gui_cache_archive_retention_days_help")));
      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_polling")));
      // integrations.js:237/240/248/251 print these four labels as raw snake_case
      // with no data-i18n. v2 gives them proper keys (see the supplement) and
      // keeps the stored key visible in the <code> slot, which is where it belongs.
      cfgPanel.body.appendChild(labelled(t("v2_sy_cache_ev_poll"), form.track("events_poll_interval_seconds", evPoll, "number"), t("gui_cache_events_poll_interval_seconds_help")));
      cfgPanel.body.appendChild(labelled(t("v2_sy_cache_tr_poll"), form.track("traffic_poll_interval_seconds", trPoll, "number"), t("gui_cache_traffic_poll_interval_seconds_help")));
      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_throughput")));
      cfgPanel.body.appendChild(labelled(t("v2_sy_cache_rate"), form.track("rate_limit_per_minute", rate, "number"), t("gui_cache_rate_limit_per_minute_help")));
      cfgPanel.body.appendChild(labelled(t("v2_sy_cache_async"), form.track("async_threshold_events", asyncTh, "number"), t("gui_cache_async_threshold_events_help")));
      cfgPanel.body.appendChild(note(t("v2_sy_cache_label_fix")));

      // ── SY-05 traffic filter ─────────────────────────────────────────
      const tfPanel = panel("SY-05", t("gui_cache_sec_traffic_filter"));
      const actionBoxes = [];
      const protoBoxes = [];
      const actionRow = el("div", { class: "daychips" });
      TF_ACTIONS.forEach(function (v) {
        const box = checkField((tf0.actions || []).indexOf(v) >= 0);
        box.dataset.field = "traffic_filter.actions";
        box.addEventListener("change", form.sync);
        actionBoxes.push([v, box]);
        actionRow.appendChild(el("label", null, box, el("span", { text: v })));
      });
      const protoRow = el("div", { class: "daychips" });
      TF_PROTOCOLS.forEach(function (v) {
        const box = checkField((tf0.protocols || []).indexOf(v) >= 0);
        box.dataset.field = "traffic_filter.protocols";
        box.addEventListener("change", form.sync);
        protoBoxes.push([v, box]);
        protoRow.appendChild(el("label", null, box, el("span", { text: v })));
      });
      const tfEnv = textField((tf0.workload_label_env || []).join(","));
      const tfPorts = textField((tf0.ports || []).join(","));
      const tfIps = textField((tf0.exclude_src_ips || []).join(","));
      const hintBox = el("p", { class: "note", "data-tone": "crit" });

      tfPanel.body.appendChild(labelled(t("gui_cache_tf_actions"), actionRow));
      tfPanel.body.appendChild(labelled(t("gui_cache_tf_protocols"), protoRow));
      tfPanel.body.appendChild(labelled(t("gui_cache_tf_workload_env"), form.track("traffic_filter.workload_label_env", tfEnv, "list"), t("gui_cache_workload_label_env_help")));
      tfPanel.body.appendChild(labelled(t("gui_cache_tf_ports"), form.track("traffic_filter.ports", tfPorts, "ports"), t("gui_cache_ports_help")));
      tfPanel.body.appendChild(labelled(t("gui_cache_tf_exclude_ips"), form.track("traffic_filter.exclude_src_ips", tfIps, "list"), t("gui_cache_exclude_src_ips_help")));
      tfPanel.body.appendChild(hintBox);
      tfPanel.body.appendChild(note(t("v2_sy_tf_cidr_bug")));
      tfPanel.body.appendChild(note(t("v2_sy_tf_presave")));

      // ── SY-06 sampling ───────────────────────────────────────────────
      const tsPanel = panel("SY-06", t("gui_cache_sec_traffic_sampling"));
      const tsRatio = numberField(ts.sample_ratio_allowed, 1, null);
      const tsMax = numberField(ts.max_rows_per_batch, 1, 200000);
      tsPanel.body.appendChild(labelled(t("gui_cache_ts_ratio"), form.track("traffic_sampling.sample_ratio_allowed", tsRatio, "number"), t("gui_cache_ts_ratio_help")));
      tsPanel.body.appendChild(labelled(t("gui_cache_ts_max_rows"), form.track("traffic_sampling.max_rows_per_batch", tsMax, "number"), t("gui_cache_ts_max_rows_help")));
      tsPanel.body.appendChild(note(t("v2_sy_ts_note")));

      board.appendChild(el("div", { class: "brow c2 top" }, cfgPanel, el("div", { class: "board" }, tfPanel, tsPanel)));

      /* Six keys of PceCacheSettings have no control anywhere in buildCacheForm
       * (integrations.js:182-262). They survive only because cacheSave merges
       * over the cached settings object (:269). Dropping a backend field on the
       * floor is exactly how the previous redesign lost data, so they are listed
       * here with their values and the reason they are read-only. */
      const gapPanel = panel(null, t("v2_sy_cache_nogui"));
      gapPanel.body.appendChild(roList([
        roField("archive_review_max_days", s.archive_review_max_days, t("v2_sy_cache_nogui_note")),
        roField("cache_read_max_rows", s.cache_read_max_rows, t("v2_sy_cache_nogui_note")),
        roField("disk_free_warn_gb", s.disk_free_warn_gb, t("v2_sy_cache_nogui_note")),
        roField("flow_delta_enabled", s.flow_delta_enabled, t("v2_sy_cache_nogui_note")),
        roField("flow_obs_retention_hours", s.flow_obs_retention_hours, t("v2_sy_cache_nogui_note")),
        roField("siem_pending_warn_rows", s.siem_pending_warn_rows, t("v2_sy_cache_nogui_note")),
      ]));
      gapPanel.body.appendChild(note(t("v2_sy_cache_nogui_body")));
      board.appendChild(gapPanel);

      /* cacheSave (integrations.js:264-297) starts from the cached settings
       * object and overwrites the controlled keys, so the body always carries
       * every key of the section — including the six above. */
      form.setBody(function (v) {
        const b = {};
        Object.keys(s).forEach(function (k) { b[k] = s[k]; });
        Object.keys(v).forEach(function (k) { if (k.indexOf(".") < 0) b[k] = v[k]; });
        const filter = {};
        filter.actions = actionBoxes.filter(function (p) { return p[1].checked; }).map(function (p) { return p[0]; });
        filter.protocols = protoBoxes.filter(function (p) { return p[1].checked; }).map(function (p) { return p[0]; });
        filter.workload_label_env = v["traffic_filter.workload_label_env"];
        filter.ports = v["traffic_filter.ports"];
        filter.exclude_src_ips = v["traffic_filter.exclude_src_ips"];
        b.traffic_filter = filter;
        const sampling = {};
        sampling.sample_ratio_allowed = v["traffic_sampling.sample_ratio_allowed"];
        sampling.max_rows_per_batch = v["traffic_sampling.max_rows_per_batch"];
        b.traffic_sampling = sampling;
        return b;
      });
      form.onSync(function () {
        const hints = trafficFilterHints(tfIps.value, tfPorts.value);
        hintBox.textContent = hints.join(" · ");
        hintBox.hidden = !hints.length;
      });
      form.afterSave = function () { banner.hidden = false; };

      board.appendChild(payloadPanel(form, t("v2_sy_cache_payload_src")));
      host.appendChild(form.dock);
      form.sync();
    });
}

/** Bytes as GiB — the unit disk_free_warn_gb is expressed in. */
function mib(bytes) {
  const n = Number(bytes);
  if (!isFinite(n) || n <= 0) return "—";
  return (n / 1073741824).toFixed(1) + " GiB";
}

function oneHour(v) {
  if (v === null || v === undefined) return null;
  return tf("gui_ov_cache_ingest_1h", { n: num(v) });
}

function kpiCell(k, v, d, tn) {
  const cell = el("div", { class: "kpicell", "data-tone": tn || null });
  cell.appendChild(el("span", { class: "k", text: k }));
  cell.appendChild(el("span", { class: "v", text: v }));
  cell.appendChild(el("span", { class: "d", text: d || "" }));
  return cell;
}

// ══════════════════════════════════════════ SY-07…10  SIEM forwarder ═════════

// integrations.js:858 (select#md-transport) / :861 (select#md-format).
const SIEM_TRANSPORTS = [["udp", "udp"], ["tcp", "tcp"], ["tls", "tls"], ["hec", "hec"]];
const SIEM_FORMATS = [["cef", "cef"], ["json", "json"], ["syslog_cef", "syslog_cef"], ["syslog_json", "syslog_json"]];
// integrations.js:817 (_SIEM_DEFAULT_PORTS) — the port is only rewritten when the
// current value is still one of the defaults (:914-922).
const SIEM_PORTS = [["udp", 514], ["tcp", 514], ["tls", 6514], ["hec", 8088]];
const SIEM_SOURCE_TYPES = [["audit", "v2_sy_siem_st_audit"], ["traffic", "v2_sy_siem_st_traffic"]];

function defaultPort(transport) {
  let hit = 514;
  SIEM_PORTS.forEach(function (p) { if (p[0] === transport) hit = p[1]; });
  return hit;
}

/* buildDestModal, integrations.js:819-904. Every field of the modal is here in
 * its order, plus the two keys the modal never shows (`profile`, `mask_pii`,
 * config_models.py:285/302-310) as read-only rows — a create silently accepts
 * their defaults, and that is worth seeing before you press save. */
function destDrawer(dest, isEdit) {
  const body = el("div", { "data-cov": "SY-08" });
  const dst = dest || {};
  const form = makeForm(isEdit ? "PUT" : "POST",
    isEdit ? "/api/siem/destinations/" + encodeURIComponent(dst.name || "") : "/api/siem/destinations");

  const name = textField(dst.name || "");
  if (isEdit) name.readOnly = true;
  const enabled = checkField(dst.enabled === undefined ? true : dst.enabled);
  const transport = selectField(SIEM_TRANSPORTS, dst.transport || "udp", false);
  const format = selectField(SIEM_FORMATS, dst.format || "cef", false);
  const hostField = textField(dst.host || "");
  hostField.placeholder = "192.168.1.10";
  const port = numberField(dst.port === undefined ? 514 : dst.port, 1, 65535);
  const tlsVerify = checkField(dst.tls_verify === undefined ? true : dst.tls_verify);
  const tlsCa = textField(dst.tls_ca_bundle || "");
  tlsCa.placeholder = "/etc/ssl/certs/ca-bundle.crt";
  const hecToken = passwordField(t("v2_sy_secret_keep"));
  const batch = numberField(dst.batch_size === undefined ? 100 : dst.batch_size, 1, 10000);
  const retries = numberField(dst.max_retries === undefined ? 10 : dst.max_retries, 0, null);

  const stBoxes = [];
  const stRow = el("div", { class: "daychips" });
  SIEM_SOURCE_TYPES.forEach(function (pair) {
    const box = checkField((dst.source_types || ["audit", "traffic"]).indexOf(pair[0]) >= 0);
    box.dataset.field = "source_types";
    box.addEventListener("change", form.sync);
    stBoxes.push([pair[0], box]);
    stRow.appendChild(el("label", null, box, el("span", { text: t(pair[1]) })));
  });

  const tlsSection = el("div", null,
    sectionHead(t("gui_siem_sec_tls")),
    checkRow(t("gui_siem_tls_verify"), form.track("tls_verify", tlsVerify, "bool"), t("v2_sy_siem_tls_prod")),
    labelled(t("gui_siem_ca_bundle"), form.track("tls_ca_bundle", tlsCa)));
  const hecSection = el("div", null,
    sectionHead(t("gui_siem_sec_hec")),
    labelled(t("gui_siem_hec_token"), form.track("hec_token", hecToken, "secret"), t("v2_sy_secret_hint")),
    roList([roField("hec_token", secretState(dst, "hec_token"), t("v2_sy_secret_short"))]));

  /* siemToggleCondFields, integrations.js:906-923 — TLS block for tls|hec, HEC
   * block for hec only, and the port default swap. The hidden sections are still
   * SUBMITTED by siemSaveDest (:941-943), which is why they stay in the payload
   * pane instead of disappearing from it. */
  function onTransport() {
    const v = transport.value;
    tlsSection.hidden = !(v === "tls" || v === "hec");
    hecSection.hidden = v !== "hec";
    const cur = Number(port.value);
    if (cur === 514 || cur === 6514 || cur === 8088) port.value = String(defaultPort(v));
    form.sync();
  }
  transport.addEventListener("change", onTransport);

  form.setBody(function (v) {
    const b = {};
    b.name = v.name;
    b.enabled = v.enabled;
    b.transport = v.transport;
    b.format = v.format;
    b.host = String(v.host || "").trim();
    b.port = v.port;
    b.tls_verify = v.tls_verify;
    b.tls_ca_bundle = String(v.tls_ca_bundle || "").trim() || null;
    b.hec_token = v.hec_token || null;
    b.batch_size = v.batch_size;
    b.max_retries = v.max_retries;
    b.source_types = stBoxes.filter(function (p) { return p[1].checked; }).map(function (p) { return p[0]; });
    if (!b.source_types.length) b.source_types = ["audit", "traffic"];
    return b;
  });

  body.appendChild(note(t("v2_sy_siem_dest_src")));
  body.appendChild(sectionHead(t("gui_siem_sec_basic")));
  body.appendChild(labelled(t("gui_siem_name"), form.track("name", name), isEdit ? t("v2_sy_siem_name_ro") : t("v2_sy_siem_name_new")));
  body.appendChild(checkRow(t("gui_siem_enabled"), form.track("enabled", enabled, "bool")));
  body.appendChild(labelled(t("gui_siem_source_types"), stRow, t("v2_sy_siem_st_fallback")));
  body.appendChild(sectionHead(t("gui_siem_sec_transport")));
  body.appendChild(labelled(t("gui_siem_transport"), form.track("transport", transport), t("gui_siem_transport_help")));
  body.appendChild(labelled(t("gui_siem_format"), form.track("format", format), t("gui_siem_format_help")));
  body.appendChild(labelled(t("gui_siem_host"), form.track("host", hostField)));
  body.appendChild(labelled(t("gui_siem_port"), form.track("port", port, "number"), t("v2_sy_siem_port_auto")));
  body.appendChild(tlsSection);
  body.appendChild(hecSection);
  body.appendChild(sectionHead(t("gui_siem_sec_advanced")));
  body.appendChild(labelled(t("gui_siem_batch_size"), form.track("batch_size", batch, "number")));
  body.appendChild(labelled(t("gui_siem_max_retries"), form.track("max_retries", retries, "number")));
  body.appendChild(note(t("v2_sy_secret_note")));
  body.appendChild(sectionHead(t("v2_sy_siem_nomodal")));
  body.appendChild(roList([
    roField("profile", dst.profile, t("v2_sy_siem_profile_note")),
    roField("mask_pii", dst.mask_pii, t("v2_sy_siem_maskpii_note")),
  ]));
  body.appendChild(sectionHead(t("v2_sy_payload")));
  body.appendChild(verifyPane(form.payload));
  body.appendChild(el("div", { class: "typechips" },
    btn("btn", t("gui_siem_test_inline"), function () { toast.info(t("v2_sy_siem_test_mock")); })));
  body.appendChild(note(t("v2_sy_siem_test_saved")));
  body.appendChild(note(t("v2_sy_mock_save")));

  onTransport();
  form.sync();
  return drawerSpec(t(isEdit ? "gui_siem_modal_title_edit" : "gui_siem_modal_title_add"), body, function () {
    toast.info(t("v2_sy_mock_save"));
    return true;
  });
}

/** _siemStatusBadge, integrations.js:665-676 — disabled beats failed beats ok. */
function destTone(dest, st) {
  if (!dest.enabled) return "warn";
  if (Number((st && st.failed) || 0) > 0) return "crit";
  return "ok";
}

function destStatusText(dest, st) {
  if (!dest.enabled) return t("gui_siem_status_disabled");
  if (Number((st && st.failed) || 0) > 0) return t("gui_siem_status_error");
  return t("gui_siem_status_healthy");
}

/* The DLQ detail view (dlqView, integrations.js:1290-1376). siem_dlq.json is
 * empty on this appliance — every destination is delivering — so the drawer
 * states the fields the endpoint returns (siem/web.py:258-286) instead of
 * inventing a quarantined record to look at. */
function dlqDrawer(entry) {
  const body = el("div", { "data-cov": "SY-10" });
  if (!entry) {
    body.appendChild(el("div", { class: "empty" },
      el("span", { class: "et", text: t("gui_it_dlq_empty_title") }),
      el("p", { text: t("gui_it_dlq_empty_body") })));
    body.appendChild(sectionHead(t("v2_sy_dlq_fields")));
    body.appendChild(roList([
      roField("destination", null, t("v2_sy_dlq_f_dest")),
      roField("source_id", null, t("v2_sy_dlq_f_id")),
      roField("quarantined_at", null, t("v2_sy_dlq_f_at")),
      roField("retries", null, t("v2_sy_dlq_f_retries")),
      roField("last_error", null, t("v2_sy_dlq_f_err")),
      roField("payload", null, t("v2_sy_dlq_f_payload")),
      roField("payload_source", null, t("v2_sy_dlq_f_src")),
    ]));
    body.appendChild(note(t("v2_sy_dlq_src_dropped")));
    return drawerSpec(t("gui_dlq_modal_title"), body);
  }
  body.appendChild(kvRow(t("gui_dlq_dt_destination"), entry.destination || entry.source_table));
  body.appendChild(kvRow(t("gui_dlq_dt_event_id"), entry.source_id));
  body.appendChild(kvRow(t("gui_dlq_dt_failed_at"), entry.quarantined_at));
  body.appendChild(kvRow(t("gui_dlq_dt_retries"), entry.retries));
  body.appendChild(sectionHead(t("gui_dlq_dt_reason")));
  body.appendChild(el("pre", { class: "codepane", text: String(entry.last_error || "—") }));
  body.appendChild(sectionHead(t("gui_dlq_dt_payload")));
  body.appendChild(el("pre", { class: "codepane tall", text: JSON.stringify(entry.payload || null, null, 2) }));
  return drawerSpec(t("gui_dlq_modal_title"), body);
}

async function mountSiem(root, ctx) {
  const handles = {};
  drawer.registerAudit("sy-siem-dest", function () { return handles.editDest ? handles.editDest() : null; });
  drawer.registerAudit("sy-siem-dlq", function () { return drawer.open(dlqDrawer(null)); });
  modal.registerAudit("sy-siem-purge", function () { return handles.purge ? handles.purge() : null; });
  palette.registerFor(R_SIEM, cmdSpec("sy:siem-add", t("gui_siem_add"), function () { drawer.open(destDrawer(null, false)); }));

  await sysPage(root, ctx, R_SIEM,
    ["siem_forwarder", "siem_destinations", "siem_status", "siem_dlq"],
    function (board, d, host) {
      const fw = d.siem_forwarder || {};
      const dests = (d.siem_destinations && d.siem_destinations.destinations) || [];
      const statuses = (d.siem_status && d.siem_status.status) || [];
      const byName = {};
      statuses.forEach(function (s) { byName[s.destination] = s; });
      const form = makeForm("PUT", "/api/siem/forwarder");

      // KPI strip — integrations.js:607-652
      let sent = 0;
      let dlq = 0;
      let sent1h = 0;
      let failed1h = 0;
      let latencyNum = 0;
      let latencyDen = 0;
      statuses.forEach(function (s) {
        sent += Number(s.sent || 0);
        dlq += Number(s.dlq || 0);
        sent1h += Number(s.sent_1h || 0);
        failed1h += Number(s.failed_1h || 0);
        latencyNum += Number(s.avg_latency_ms || 0) * Number(s.sent_1h || 0);
        latencyDen += Number(s.sent_1h || 0);
      });
      const rate1h = sent1h + failed1h > 0 ? (sent1h / (sent1h + failed1h) * 100).toFixed(1) + "%" : "—";
      const avgMs = latencyDen > 0 ? Math.round(latencyNum / latencyDen) : null;
      const kpis = el("div", { class: "kpirow" },
        kpiCell(t("v2_sy_siem_sent"), num(sent), null, null),
        kpiCell(t("gui_ov_siem_success_1h"), rate1h, null, failed1h > 0 ? "crit" : "ok"),
        kpiCell(t("gui_ov_dlq_total"), num(dlq), null, dlq > 0 ? "warn" : null),
        kpiCell(t("gui_ov_siem_latency"), avgMs === null ? "—" : (avgMs < 1000 ? avgMs + "ms" : (avgMs / 1000).toFixed(1) + "s"), null, null));
      board.appendChild(kpis);

      // ── SY-07 forwarder ──────────────────────────────────────────────
      const fwPanel = panel("SY-07", t("gui_siem_forwarder"));
      const fwOn = checkField(fw.enabled);
      const tick = numberField(fw.dispatch_tick_seconds, 1, null);
      const dlqMax = numberField(fw.dlq_max_per_dest, 100, null);
      fwPanel.body.appendChild(checkRow(t("gui_siem_enabled"), form.track("enabled", fwOn, "bool")));
      fwPanel.body.appendChild(labelled(t("gui_siem_dispatch_tick"), form.track("dispatch_tick_seconds", tick, "number"), t("gui_siem_dispatch_tick_help")));
      fwPanel.body.appendChild(labelled(t("gui_siem_dlq_max"), form.track("dlq_max_per_dest", dlqMax, "number"), t("gui_siem_dlq_max_help")));
      fwPanel.body.appendChild(note(t("v2_sy_siem_fw_src")));
      form.setBody(function (v) {
        const b = {};
        b.enabled = v.enabled;
        b.dispatch_tick_seconds = v.dispatch_tick_seconds;
        b.dlq_max_per_dest = v.dlq_max_per_dest;
        return b;
      });

      // ── SY-08 / SY-09 destinations ───────────────────────────────────
      const destPanel = panel("SY-08", t("gui_siem_destinations"));
      withMeta(destPanel, tf("v2_sy_siem_dest_meta", { n: dests.length }));
      destPanel.head.appendChild(btn("btn", t("gui_siem_add"), function () { drawer.open(destDrawer(null, false)); }));
      handles.editDest = function () { return drawer.open(destDrawer(dests[0] || null, dests.length > 0)); };
      const destHost = el("div");
      destPanel.body.appendChild(destHost);
      const columns = [
        col("name", t("gui_siem_th_name"), buildCell(function (p) {
          return el("span", { class: "idc" }, el("b", { text: p.name }),
            el("small", { text: p.enabled ? t("gui_enabled") : t("gui_disabled") }));
        })),
        col("transport", t("gui_siem_th_transport"), widthCell(120, function (p) {
          const box = el("span", { class: "chips" }, el("span", null, el("b", { text: p.transport })));
          // integrations.js:736-737 — UDP has no ACK, so DLQ confirmation cannot exist.
          if (/udp/i.test(String(p.transport))) box.appendChild(el("span", { class: "off", title: t("v2_sy_siem_noack_help"), text: t("v2_sy_siem_noack") }));
          return box;
        })),
        col("format", t("gui_siem_th_format"), widthCell(110, function (p) { return el("code", { class: "mono", text: p.format }); })),
        col("host", t("gui_siem_th_host"), widthCell(160)),
        col("port", t("gui_siem_th_port"), widthCell(70)),
        col("status", t("gui_siem_th_status"), widthCell(120, function (p) {
          return badge(destStatusText(p, byName[p.name]), destTone(p, byName[p.name]));
        })),
        col("act", t("gui_siem_th_actions"), widthCell(200, function (p) {
          const box = el("div", { class: "rowacts" });
          // SY-09: the product's test posts to the SAVED destination and alerts
          // the latency (integrations.js:976-990); there is nothing to post to.
          box.appendChild(btn("btn ghost", t("gui_siem_test"), function () { toast.info(tf("v2_sy_siem_test_req", { name: p.name })); }));
          box.appendChild(btn("btn ghost", t("gui_siem_edit"), function () { drawer.open(destDrawer(p, true)); }));
          box.appendChild(btn("btn danger", t("gui_siem_delete"), function () {
            modal.confirm(confirmSpec(t("gui_confirm_delete"),
              [tf("v2_sy_siem_i_del", { name: p.name }), t("v2_sy_siem_i_dlq")], function () {
                toast.info(t("v2_sy_mock_save"));
                return true;
              }));
          }));
          return box;
        })),
      ];
      table.render(destHost, buildTable(columns, dests));
      const testPanel = panel("SY-09", t("gui_siem_test"));
      testPanel.body.appendChild(note(t("v2_sy_siem_test_body")));
      testPanel.body.appendChild(el("ul", { class: "stack" },
        el("li", null, el("code", { class: "c", text: "POST" }), el("span", { class: "s", text: "/api/siem/destinations/<name>/test" })),
        el("li", null, el("code", { class: "c", text: "ok" }), el("span", { class: "s", text: t("v2_sy_siem_test_ok") })),
        el("li", null, el("code", { class: "c", text: "latency_ms" }), el("span", { class: "s", text: t("v2_sy_siem_test_latency") })),
        el("li", null, el("code", { class: "c", text: "error" }), el("span", { class: "s", text: t("v2_sy_siem_test_err") }))));
      testPanel.body.appendChild(note(t("v2_sy_siem_test_saved")));

      board.appendChild(el("div", { class: "brow c2" }, fwPanel, testPanel));
      board.appendChild(destPanel);

      // ── SY-10 DLQ ────────────────────────────────────────────────────
      const dlqPanel = panel("SY-10", t("v2_sy_dlq_title"));
      const entries = (d.siem_dlq && d.siem_dlq.entries) || [];
      const destPairs = [["", t("gui_dlq_filter_all")]].concat(dests.map(function (p) { return [p.name, p.name]; }));
      const destSel = selectField(destPairs, "", false);
      const reason = el("input", { class: "field", placeholder: t("gui_dlq_filter_reason") });
      dlqPanel.body.appendChild(el("div", { class: "qrow" },
        el("div", { class: "qf" }, el("label", { text: t("gui_dlq_filter_dest") }), destSel),
        el("div", { class: "qf grow" }, el("label", { text: t("gui_dlq_filter_reason") }), reason),
        el("div", { class: "qf" }, el("label", { text: " " }), btn("btn", t("gui_dlq_search"), function () { toast.info(t("v2_sy_dlq_search_mock")); }))));
      const dlqHost = el("div");
      dlqPanel.body.appendChild(dlqHost);
      const dlqCols = [
        col("destination", t("gui_dlq_th_dest"), widthCell(140)),
        col("source_id", t("gui_dlq_th_event_id"), widthCell(160)),
        col("last_error", t("gui_dlq_th_reason")),
        col("quarantined_at", t("gui_dlq_th_failed_at"), widthCell(150)),
        col("retries", t("gui_dlq_th_retries"), widthCell(70)),
        col("act", "", widthCell(150, function (e) {
          const box = el("div", { class: "rowacts" });
          box.appendChild(btn("btn ghost", t("gui_dlq_view"), function () { drawer.open(dlqDrawer(e)); }));
          box.appendChild(btn("btn ghost", t("gui_dlq_replay"), function () { toast.info(t("v2_sy_dlq_replay_mock")); }));
          return box;
        })),
      ];
      table.render(dlqHost, buildTable(dlqCols, entries));
      /* dlqPurgeSelected (integrations.js:1245-1259) does NOT send the selected
       * ids: its body is {dest, older_than_days:0}, which purges the WHOLE
       * destination while the confirm says "Purge N entries". The impact list
       * states what actually happens. */
      handles.purge = function () {
        return modal.confirm(confirmSpec(t("gui_dlq_purge_selected"), [
          t("v2_sy_dlq_i_all"),
          t("v2_sy_dlq_i_body"),
          t("v2_sy_dlq_i_typed"),
          t("v2_sy_dlq_i_norecover"),
        ], function () {
          toast.info(t("v2_sy_mock_save"));
          return true;
        }));
      };
      dlqPanel.body.appendChild(el("div", { class: "typechips" },
        btn("btn ghost", t("gui_dlq_select_all"), function () { toast.info(t("v2_sy_dlq_search_mock")); }),
        btn("btn ghost", t("gui_dlq_replay_selected"), function () { toast.info(t("v2_sy_dlq_replay_mock")); }),
        btn("btn", t("gui_dlq_purge_selected"), handles.purge),
        btn("btn danger", t("gui_dlq_purge_all"), handles.purge),
        btn("btn ghost", t("gui_dlq_export"), function () { toast.info(t("v2_sy_dlq_export_mock")); }),
        btn("btn ghost", t("gui_dlq_view"), function () { drawer.open(dlqDrawer(entries[0] || null)); })));
      dlqPanel.body.appendChild(note(t("v2_sy_dlq_paging")));
      dlqPanel.body.appendChild(note(t("v2_sy_dlq_reason_client")));
      board.appendChild(dlqPanel);

      board.appendChild(payloadPanel(form, t("v2_sy_siem_payload_src")));
      host.appendChild(form.dock);
      form.sync();
    });
}

// ══════════════════════════════════════════════════════ SY-11  TLS ═══════════

const CSR_ALGS = [["rsa-2048", "RSA-2048"], ["ecdsa-p256", "ECDSA P-256"]];

/** humanizeDays, settings.js:114-127 — months under 60 days, years above. */
function humanizeDays(n) {
  const days = Number(n);
  if (!isFinite(days) || days < 0) return "";
  if (days < 60) {
    const months = Math.max(1, Math.round(days / 30));
    return tf("gui_tls_days_humanized", { n: days, label: tf("gui_tls_days_label_months", { m: months }) });
  }
  const years = Math.floor(days / 365);
  const months = Math.round((days % 365) / 30);
  const label = years >= 1 ? tf("gui_tls_days_label_years", { y: years, m: months }) : tf("gui_tls_days_label_months", { m: months });
  return tf("gui_tls_days_humanized", { n: days, label: label });
}

async function mountTls(root, ctx) {
  const handles = {};
  modal.registerAudit("sy-tls-renew", function () { return handles.renew ? handles.renew() : null; });
  palette.registerFor(R_TLS, cmdSpec("sy:tls-renew", t("gui_tls_renew"), function () { if (handles.renew) handles.renew(); }));

  await sysPage(root, ctx, R_TLS, ["tls_status"], function (board, d, host) {
    const s = d.tls_status || {};
    const info = s.cert_info || {};
    const form = makeForm("POST", "/api/tls/config");

    // ── status card (settings.js:558-591) ────────────────────────────
    const statPanel = panel("SY-11", t("gui_tls_cert_info"));
    const tn = info.expired ? "crit" : (info.expiring_soon ? "warn" : "ok");
    statPanel.dataset.tone = tn;
    if (!info.exists) {
      statPanel.body.appendChild(el("div", { class: "empty" }, el("span", { class: "et", text: t("gui_tls_no_cert") })));
    } else {
      statPanel.body.appendChild(el("div", { class: "lead" },
        el("span", { class: "n", text: String(s.days_remaining === undefined ? "—" : s.days_remaining) }),
        el("span", { class: "u", text: t("gui_tls_days_remaining") }),
        badge(info.expired ? t("gui_tls_expired") : (info.expiring_soon ? t("gui_tls_expiring_soon") : t("gui_enabled")), tn)));
      statPanel.body.appendChild(note(humanizeDays(s.days_remaining)));
      statPanel.body.appendChild(kvRow(t("v2_sy_tls_subject"), info.subject));
      statPanel.body.appendChild(kvRow(t("gui_tls_valid_from"), info.not_before));
      statPanel.body.appendChild(kvRow(t("gui_tls_valid_until"), info.not_after));
      statPanel.body.appendChild(kvRow(t("v2_sy_tls_path"), info.path));
      statPanel.body.appendChild(kvRow(t("gui_tls_self_signed"), String(!!s.self_signed)));
      statPanel.body.appendChild(kvRow(t("v2_sy_tls_validity"), s.default_validity_days));
    }
    /* renewTlsCert (settings.js:593-607) is offered only for a self-signed cert;
     * config.py:339-340 rejects the call for a CA-signed one. */
    handles.renew = function () {
      return modal.confirm(confirmSpec(t("gui_tls_renew"), [
        t("gui_tls_renew_confirm"),
        t("v2_sy_tls_i_restart"),
        t("v2_sy_tls_i_selfonly"),
        t("v2_sy_tls_i_rate"),
      ], function () {
        toast.info(t("v2_sy_mock_save"));
        return true;
      }));
    };
    if (s.self_signed) statPanel.body.appendChild(btn("btn primary", t("gui_tls_renew"), handles.renew));
    else statPanel.body.appendChild(note(t("v2_sy_tls_no_renew")));
    statPanel.body.appendChild(note(t("v2_sy_tls_subject_literal")));
    board.appendChild(statPanel);

    // ── TLS config form ──────────────────────────────────────────────
    const cfgPanel = panel(null, t("gui_tls_title"));
    const enabled = checkField(s.enabled);
    const selfSigned = checkField(s.self_signed);
    const certFile = textField(s.cert_file);
    certFile.placeholder = "/path/to/cert.pem";
    const keyFile = textField(s.key_file);
    keyFile.placeholder = "/path/to/key.pem";
    const autoRenew = checkField(s.auto_renew !== false);
    const autoDays = numberField(s.auto_renew_days === undefined ? 30 : s.auto_renew_days, 1, 365);

    const customBox = el("div", null,
      labelled(t("gui_tls_cert_file"), form.track("cert_file", certFile), t("gui_tls_cert_file_help")),
      labelled(t("gui_tls_key_file"), form.track("key_file", keyFile), t("gui_tls_key_file_help")));
    const renewBox = el("div", null,
      checkRow(t("gui_tls_auto_renew"), form.track("auto_renew", autoRenew, "bool")),
      labelled(t("gui_tls_auto_renew_days"), form.track("auto_renew_days", autoDays, "number"), t("gui_tls_auto_renew_hint")));

    // toggleTlsMode settings.js:548-556 — custom paths for a CA cert, auto-renew
    // for a self-signed one; never both.
    function onMode() {
      customBox.hidden = !!selfSigned.checked;
      renewBox.hidden = !selfSigned.checked;
    }
    selfSigned.addEventListener("change", onMode);

    cfgPanel.body.appendChild(checkRow(t("gui_tls_enable"), form.track("enabled", enabled, "bool")));
    cfgPanel.body.appendChild(checkRow(t("gui_tls_self_signed"), form.track("self_signed", selfSigned, "bool")));
    cfgPanel.body.appendChild(customBox);
    cfgPanel.body.appendChild(renewBox);
    cfgPanel.body.appendChild(note(t("gui_tls_saved_restart_hint")));
    onMode();

    form.setBody(function (v) {
      const b = {};
      b.enabled = v.enabled;
      b.self_signed = v.self_signed;
      b.cert_file = v.cert_file;
      b.key_file = v.key_file;
      b.auto_renew = v.auto_renew;
      b.auto_renew_days = v.auto_renew_days;
      return b;
    });

    // ── CSR (settings.js:483-512, generateCsr :609-632) ──────────────
    const csrPanel = panel(null, t("gui_tls_csr_title"));
    csrPanel.body.appendChild(note(t("gui_tls_csr_hint")));
    const cn = textField("");
    cn.placeholder = "pce.example.com";
    const org = textField("");
    org.placeholder = "Example Corp";
    const country = textField("");
    country.maxLength = 2;
    const sanDns = textField("");
    sanDns.placeholder = "pce.example.com, pce2.example.com";
    const sanIp = textField("");
    sanIp.placeholder = "192.168.1.10, 10.0.0.5";
    const alg = selectField(CSR_ALGS, "rsa-2048", false);
    const csrOut = el("pre", { class: "codepane" });
    function paintCsr() {
      const b = {};
      b.cn = cn.value;
      b.o = org.value;
      b.c = country.value;
      b.san_dns = sanDns.value;
      b.san_ip = sanIp.value;
      b.key_algorithm = alg.value;
      csrOut.textContent = "POST /api/tls/generate-csr\n" + JSON.stringify(b, null, 2);
    }
    [cn, org, country, sanDns, sanIp, alg].forEach(function (c) {
      c.addEventListener("input", paintCsr);
      c.addEventListener("change", paintCsr);
    });
    cn.dataset.field = "cn";
    org.dataset.field = "o";
    country.dataset.field = "c";
    sanDns.dataset.field = "san_dns";
    sanIp.dataset.field = "san_ip";
    alg.dataset.field = "key_algorithm";
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_cn"), cn, t("v2_sy_tls_cn_required")));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_o"), org));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_c"), country));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_san_dns"), sanDns));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_san_ip"), sanIp));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_key_alg"), alg));
    csrPanel.body.appendChild(el("div", { class: "typechips" },
      btn("btn primary", t("gui_tls_csr_generate"), function () {
        if (!cn.value.trim()) {
          toast.crit(t("gui_tls_csr_cn_required"));
          return;
        }
        toast.info(t("v2_sy_tls_csr_mock"));
      }),
      btn("btn ghost", t("gui_tls_csr_copy"), function () { toast.info(t("v2_sy_tls_csr_mock")); }),
      btn("btn ghost", t("gui_tls_csr_download"), function () { toast.info(t("v2_sy_tls_csr_mock")); })));
    csrPanel.body.appendChild(el("div", { class: "fld" },
      el("label", null, el("span", { text: t("gui_tls_csr_pem_label") })), verifyPane(csrOut)));
    // config.py:373 accepts an `ou` field that no input in the product produces.
    csrPanel.body.appendChild(roList([roField("ou", null, t("v2_sy_tls_ou_note"))]));
    paintCsr();

    // ── import (settings.js:513-520, importSignedCert :652-671) ──────
    const impPanel = panel(null, t("gui_tls_import_title"));
    impPanel.body.appendChild(note(t("gui_tls_import_hint")));
    const pem = el("textarea", { class: "field ta", rows: "6", placeholder: "-----BEGIN CERTIFICATE-----" });
    pem.dataset.field = "cert_pem";
    impPanel.body.appendChild(pem);
    impPanel.body.appendChild(btn("btn primary", t("gui_tls_import_btn"), function () {
      if (!pem.value.trim()) {
        toast.crit(t("gui_tls_import_pem_required"));
        return;
      }
      toast.info(t("v2_sy_tls_import_mock"));
    }));
    impPanel.body.appendChild(note(t("v2_sy_tls_import_paste")));

    board.appendChild(el("div", { class: "brow c2 top" }, cfgPanel, el("div", { class: "board" }, csrPanel, impPanel)));
    board.appendChild(payloadPanel(form, t("v2_sy_tls_payload_src")));
    host.appendChild(form.dock);
    form.sync();
  });
}

// ═══════════════════════════════════════════ SY-12 / SY-16  security ═════════

async function mountSecurity(root, ctx) {
  const handles = {};
  modal.registerAudit("sy-stop-gui", function () { return handles.stop ? handles.stop() : null; });
  palette.registerFor(R_SECURITY, cmdSpec("sy:stop-gui", t("v2_sy_stop_btn"), function () { if (handles.stop) handles.stop(); }));

  await sysPage(root, ctx, R_SECURITY, ["security", "status"], function (board, d, host) {
    const sec = d.security || {};
    const form = makeForm("POST", "/api/security");

    const secPanel = panel("SY-12", t("gui_web_security"));
    const user = textField(sec.username || "illumio");
    const ips = textField((sec.allowed_ips || []).join(", "));
    ips.placeholder = "192.168.1.100, 10.0.0.0/8";
    const pw = passwordField("");
    const pw2 = passwordField("");
    const pwHint = el("p", { class: "note", "data-tone": "crit", hidden: true });

    secPanel.body.appendChild(labelled(t("gui_username"), form.track("username", user), t("v2_sy_sec_user_default")));
    secPanel.body.appendChild(labelled(t("gui_allowed_ips"), form.track("allowed_ips", ips, "list"), t("v2_sy_sec_lockout")));
    secPanel.body.appendChild(note(t("gui_leave_blank_pass")));
    secPanel.body.appendChild(labelled(t("gui_new_password"), form.track("new_password", pw, "secret"), t("v2_sy_sec_pw_rule")));
    secPanel.body.appendChild(labelled(t("gui_new_password_confirm"), form.track("confirm_password", pw2, "secret")));
    secPanel.body.appendChild(pwHint);
    /* auth_setup is returned by GET /api/security (config.py:50) and rendered
     * nowhere in settings.js — the operator cannot tell whether the appliance
     * still holds its bootstrap password. It is a status row here. */
    secPanel.body.appendChild(sectionHead(t("v2_sy_sec_state")));
    secPanel.body.appendChild(roList([
      roField("auth_setup", sec.auth_setup, t("v2_sy_sec_authsetup")),
      roField("old_password", null, t("v2_sy_sec_oldpw")),
    ]));
    secPanel.body.appendChild(note(t("v2_sy_sec_rotate")));
    board.appendChild(secPanel);

    form.setBody(function (v) {
      const b = {};
      b.username = String(v.username || "").trim();
      b.new_password = v.new_password;
      b.allowed_ips = v.allowed_ips;
      return b;
    });
    // saveSettings settings.js:675-680 blocks the POST when the two boxes differ.
    /* settings.js:675-680 checks the mismatch and nothing else, so a seven-
     * character password with an empty confirm box reports "does not match" —
     * true, but not the reason the save will fail. Length is reported first, and
     * the mismatch only once the confirm box has something in it. */
    form.onSync(function () {
      const short = pw.value.length > 0 && pw.value.length < 12;
      const bad = pw2.value.length > 0 && pw.value !== pw2.value;
      pwHint.hidden = !(short || bad);
      pwHint.textContent = short ? t("login_err_pw_short") : (bad ? t("gui_password_mismatch") : "");
    });

    // ── SY-16 stop the GUI ───────────────────────────────────────────
    const stopPanel = panel("SY-16", t("v2_sy_stop_btn"));
    stopPanel.dataset.tone = "crit";
    stopPanel.body.appendChild(note(t("gui_action_stop_gui_confirm")));
    const stopped = el("div", { class: "strip", "data-tone": "crit", hidden: true },
      el("b", { text: t("gui_action_gui_stopped_title") }),
      el("span", { text: t("gui_action_gui_stopped_body") }));
    /* stopGui (actions.js:118-127) swallows the response, so the 403 the backend
     * returns in persistent mode (admin.py:49-50) never reaches the operator —
     * the page claims the GUI stopped either way. The impact list says so. */
    handles.stop = function () {
      return modal.confirm(confirmSpec(t("v2_sy_stop_btn"), [
        t("gui_action_stop_gui_confirm"),
        t("v2_sy_stop_i_sigint"),
        t("v2_sy_stop_i_persistent"),
        t("v2_sy_stop_i_cli"),
      ], function () {
        stopped.hidden = false;
        toast.warn(t("v2_sy_stop_mock"));
        return true;
      }));
    };
    stopPanel.body.appendChild(btn("btn danger", t("v2_sy_stop_btn"), handles.stop));
    stopPanel.body.appendChild(stopped);
    stopPanel.body.appendChild(note(t("v2_sy_stop_swallow")));
    board.appendChild(stopPanel);

    board.appendChild(payloadPanel(form, t("v2_sy_sec_payload_src")));
    host.appendChild(form.dock);
    form.sync();
  });
}

// ═════════════════════════════════════ SY-13 / XC-05 / XC-06  display ════════

/* settings.js:407-436 — the timezone list, in the product's own order. `local`
 * means "use the browser's zone" and is what an unset value falls back to. */
const TIMEZONES = ["local", "UTC", "UTC-12", "UTC-11", "UTC-10", "UTC-9", "UTC-8", "UTC-7", "UTC-6",
  "UTC-5", "UTC-4", "UTC-3", "UTC-2", "UTC-1", "UTC+1", "UTC+2", "UTC+3", "UTC+4", "UTC+5", "UTC+5.5",
  "UTC+6", "UTC+7", "UTC+8", "UTC+9", "UTC+9.5", "UTC+10", "UTC+11", "UTC+12", "UTC+13", "UTC+14"];

const LANG_OPTS = [["en", "gui_lang_en"], ["zh_TW", "gui_lang_zh"]];
const THEME_OPTS = [["dark", "gui_theme_dark"], ["light", "gui_theme_light"]];
const DENSITY_OPTS = [["cozy", "v2_density_cozy"], ["compact", "v2_density_compact"]];

async function mountDisplay(root, ctx) {
  palette.registerFor(R_DISPLAY, cmdSpec("sy:theme", t("v2_cmd_theme"), function () { theme.toggle(); }));

  await sysPage(root, ctx, R_DISPLAY, ["settings", "status"], function (board, d, host) {
    const s = d.settings || {};
    const st = s.settings || {};
    const rpt = s.report || {};
    const form = makeForm("POST", "/api/settings");

    // ── XC-05 theme + density: these two switch the page for real ────
    const skinPanel = panel("XC-05", t("gui_theme"));
    const themeCtl = radioGroup("sy-theme", THEME_OPTS, theme.get(), function (v) { theme.set(v); });
    const densityCtl = radioGroup("sy-density", DENSITY_OPTS, density.get(), function (v) { density.set(v); });
    themeCtl.dataset.field = "settings.theme";
    densityCtl.dataset.field = "v2.density";
    skinPanel.body.appendChild(labelled(t("gui_theme"), themeCtl, t("v2_sy_disp_theme_live")));
    skinPanel.body.appendChild(labelled(t("gui_density"), densityCtl, t("v2_sy_disp_density_new")));
    skinPanel.body.appendChild(kvRow(t("v2_sy_disp_stored_theme"), st.theme));
    // settings.js:448 renders this label as a raw literal "Theme" with no
    // data-i18n; the density control has no product counterpart at all.
    skinPanel.body.appendChild(note(t("v2_sy_disp_theme_literal")));
    skinPanel.body.appendChild(note(t("v2_sy_disp_theme_apply")));

    // ── XC-06 timezone + language ────────────────────────────────────
    const localePanel = panel("XC-06", t("gui_lang_settings"));
    const tzPairs = TIMEZONES.map(function (v) { return [v, v === "local" ? t("gui_local_browser_time") : v]; });
    const tz = selectField(tzPairs, st.timezone || "local", false);
    // Seeded from i18n.lang — the RUNTIME language actually driving every t()
    // call on this page — not from st.language (the settings snapshot, which
    // this mockup never writes back to). Seeding from st.language made the
    // radio lie after a toggle: it kept showing the settings-snapshot language
    // forever, one click behind reality, and re-clicking the "already checked"
    // (per the DOM, though wrong) option fired no change event at all.
    const langCtl = radioGroup("sy-lang", LANG_OPTS, i18n.lang === "zh" ? "zh_TW" : "en", function (v) {
      // A language toggle that does not change the page is decoration. This one
      // flips i18n.lang and re-mounts the route. The captured product catalogue
      // only carries the appliance's ACTIVE language (zh-Hant), so in EN mode
      // only the keys that exist in i18n-supplement.json actually switch — the
      // note under the control says exactly that.
      i18n.lang = v === "zh_TW" ? "zh" : "en";
      router.go(R_DISPLAY);
    });
    langCtl.dataset.field = "settings.language";
    localePanel.body.appendChild(labelled(t("gui_timezone"), form.track("settings.timezone", tz), t("v2_sy_disp_tz_local")));
    localePanel.body.appendChild(labelled(t("gui_language"), langCtl, t("v2_sy_disp_lang_reload")));
    localePanel.body.appendChild(kvRow(t("v2_sy_disp_ui_lang"), (d.status && d.status.language) || "—"));
    localePanel.body.appendChild(kvRow(t("v2_sy_disp_ui_tz"), (d.status && d.status.timezone) || "—"));
    localePanel.body.appendChild(note(t("v2_sy_disp_lang_partial")));
    board.appendChild(el("div", { class: "brow c2" }, skinPanel, localePanel));

    // ── SY-13 the rest of the display section ────────────────────────
    const dispPanel = panel("SY-13", t("gui_settings_tab_display"));
    const health = checkField(st.enable_health_check);
    const outDir = textField(rpt.output_dir || "reports/");
    const keepDays = numberField(rpt.retention_days === undefined ? 30 : rpt.retention_days, 0, null);
    dispPanel.body.appendChild(sectionHead(t("gui_report_output")));
    dispPanel.body.appendChild(labelled(t("gui_report_output_dir"), form.track("report.output_dir", outDir), t("gui_report_output_dir_hint")));
    dispPanel.body.appendChild(labelled(t("gui_retention_days"), form.track("report.retention_days", keepDays, "number"), t("gui_retention_hint")));
    dispPanel.body.appendChild(note(t("gui_err_report_output_dir_forbidden")));
    dispPanel.body.appendChild(sectionHead(t("v2_sy_disp_other")));
    // enable_health_check lives in settings.settings but has no control in
    // _renderDisplaySection; it is editable here rather than dropped.
    dispPanel.body.appendChild(checkRow(t("v2_sy_disp_health"), form.track("settings.enable_health_check", health, "bool"), t("v2_sy_disp_health_new")));
    dispPanel.body.appendChild(note(t("v2_sy_disp_dashq")));
    board.appendChild(dispPanel);

    form.setBody(function (v) {
      const b = {};
      const settingsPart = {};
      settingsPart.language = st.language === "zh_TW" ? "zh_TW" : "en";
      settingsPart.theme = theme.get();
      settingsPart.timezone = v["settings.timezone"];
      settingsPart.enable_health_check = v["settings.enable_health_check"];
      b.settings = settingsPart;
      const reportPart = {};
      reportPart.output_dir = String(v["report.output_dir"] || "").trim();
      reportPart.retention_days = v["report.retention_days"];
      b.report = reportPart;
      return b;
    });

    board.appendChild(payloadPanel(form, t("v2_sy_disp_payload_src")));
    host.appendChild(form.dock);
    form.sync();
  });
}

// ═══════════════════════════════════════════════ SY-14  alert channels ═══════

/* _renderPluginField, settings.js:180-226. input_type drives the control;
 * value_type drives the coercion at collect time (:274-287). A `secret` field
 * is a password box in the product WITH the server's mask inside it — here the
 * box is empty and the mask's own metadata (__set/__length) is stated instead. */
function pluginControl(field, value) {
  const kind = field.input_type || (field.secret ? "password" : "text");
  if (kind === "checkbox") return checkField(!!value);
  if (kind === "list") {
    const area = el("textarea", { class: "field ta", rows: "2", placeholder: field.placeholder || "" });
    area.value = Array.isArray(value) ? value.join((field.list_delimiter || ",") + " ") : String(value || "");
    return area;
  }
  if (field.secret) {
    const box = passwordField(t("v2_sy_secret_keep"));
    return box;
  }
  if (kind === "number") {
    const n = numberField(value, null, null);
    n.placeholder = field.placeholder || "";
    return n;
  }
  const input = textField(value === null || value === undefined ? "" : value);
  input.placeholder = field.placeholder || "";
  return input;
}

function fieldKind(field) {
  if (field.secret) return "secret";
  const vt = field.value_type || "";
  if (vt === "boolean" || field.input_type === "checkbox") return "bool";
  if (vt === "integer" || vt === "number" || field.input_type === "number") return "number";
  if (vt === "string_list" || field.input_type === "list") return "list";
  return "text";
}

/** _pluginFieldValue settings.js:166-178 — the value lives at config_path. */
function nestedValue(root, path) {
  let cur = root;
  (path || []).forEach(function (seg) {
    cur = cur && typeof cur === "object" ? cur[seg] : undefined;
  });
  return cur;
}

async function mountChannels(root, ctx) {
  palette.registerFor(R_CHANNELS, cmdSpec("sy:test-channels", t("gui_set_test_send"), function () { toast.info(t("v2_sy_ch_test_mock")); }));

  await sysPage(root, ctx, R_CHANNELS, ["alert_plugins", "settings", "status"], function (board, d, host) {
    const plugins = (d.alert_plugins && d.alert_plugins.plugins) || {};
    const s = d.settings || {};
    const active = (s.alerts && s.alerts.active) || [];
    const form = makeForm("POST", "/api/settings");
    const names = Object.keys(plugins).sort();
    const toggles = [];
    const fieldItems = [];

    const wrap = panel("SY-14", t("gui_alert_channels"));
    withMeta(wrap, tf("v2_sy_ch_meta", { live: active.length, total: names.length }));
    const grid = el("div", { class: "chgrid" });
    names.forEach(function (name) {
      const p = plugins[name] || {};
      const on = active.indexOf(name) >= 0;
      const card = el("article", { class: "chcard", "data-tone": on ? "ok" : "neutral" });
      const toggle = checkField(on);
      toggles.push([name, toggle]);
      form.track("active." + name, toggle, "bool");
      card.appendChild(el("div", { class: "chcard-h" },
        el("span", { class: "dot" }),
        el("b", { text: p.display_name || name }),
        el("code", { text: name }),
        spacer(),
        btn("btn ghost", t("gui_set_test_send"), function () { toast.info(tf("v2_sy_ch_test_req", { name: name })); })));
      card.appendChild(note(p.description || ""));
      card.appendChild(el("label", { class: "chk" }, toggle, el("span", { text: t("gui_enabled") })));
      (p.fields || []).forEach(function (f) {
        const value = nestedValue(s, f.config_path);
        const ctl = pluginControl(f, value);
        const kind = fieldKind(f);
        form.track(f.key, ctl, kind);
        fieldItems.push([f, ctl]);
        const labelText = f.label + (f.required ? " *" : "");
        if (kind === "bool") card.appendChild(checkRow(labelText, ctl, f.help || null));
        else card.appendChild(labelled(labelText, ctl, f.help || null));
        if (f.secret) {
          const holder = nestedValue(s, (f.config_path || []).slice(0, -1)) || {};
          const leaf = (f.config_path || [])[(f.config_path || []).length - 1];
          card.appendChild(roList([roField(f.key, secretState(holder, leaf), t("v2_sy_secret_short"))]));
        }
      });
      grid.appendChild(card);
    });
    wrap.body.appendChild(grid);
    wrap.body.appendChild(note(t("v2_sy_ch_schema_src")));
    wrap.body.appendChild(note(t("v2_sy_ch_secret_fix")));
    wrap.body.appendChild(note(t("v2_sy_ch_test_skipped")));
    board.appendChild(wrap);

    /* _collectAlertPluginConfig settings.js:263-292 writes each value back to
     * its config_path and collects the enabled names into alerts.active; the
     * POST body then merges email / smtp / alerts (settings.js:689-698). */
    form.setBody(function (v) {
      const b = {};
      const parts = {};
      fieldItems.forEach(function (pair) {
        const f = pair[0];
        const path = f.config_path || [];
        const section = path.length > 1 ? path[0] : "alerts";
        const leaf = path[path.length - 1];
        if (!parts[section]) parts[section] = {};
        parts[section][leaf] = v[f.key];
      });
      Object.keys(parts).forEach(function (k) { b[k] = parts[k]; });
      if (!b.alerts) b.alerts = {};
      b.alerts.active = toggles.filter(function (p) { return p[1].checked; }).map(function (p) { return p[0]; });
      return b;
    });

    board.appendChild(payloadPanel(form, t("v2_sy_ch_payload_src")));
    host.appendChild(form.dock);
    form.sync();
  });
}

// ══════════════════════════════════════════════════ SY-15  module logs ═══════

const LOG_LEVELS = [["", "v2_sy_log_all"], ["INFO", "INFO"], ["WARNING", "WARNING"], ["ERROR", "ERROR"], ["DEBUG", "DEBUG"]];

function logDrawer(entry, moduleName) {
  const body = el("div", { "data-cov": "SY-15" });
  if (!entry) {
    body.appendChild(el("div", { class: "empty" }, el("span", { class: "et", text: t("gui_ml_empty") })));
    return drawerSpec(t("gui_ml_title"), body);
  }
  body.appendChild(kvRow(t("v2_sy_log_module"), moduleName));
  body.appendChild(kvRow(t("v2_sy_log_ts"), entry.ts));
  body.appendChild(kvRow(t("v2_sy_log_level"), entry.level));
  body.appendChild(sectionHead(t("v2_sy_log_msg")));
  body.appendChild(el("pre", { class: "codepane tall", text: String(entry.msg || "") }));
  // module-log.js:84 — the product's whole rendering of a line.
  body.appendChild(sectionHead(t("v2_sy_log_raw")));
  body.appendChild(el("pre", { class: "codepane", text: entry.ts + " [" + entry.level + "] " + entry.msg }));
  body.appendChild(note(t("v2_sy_log_raw_note")));
  return drawerSpec(t("gui_ml_title"), body);
}

async function mountLogs(root, ctx) {
  const handles = {};
  drawer.registerAudit("sy-log-detail", function () { return handles.first ? handles.first() : null; });

  await sysPage(root, ctx, R_LOGS, ["logs_index", "module_log_sample"], function (board, d) {
    const modules = (d.logs_index && d.logs_index.modules) || [];
    const sample = d.module_log_sample || {};
    const sampleModule = sample.module || (modules[0] && modules[0].name) || "";
    const entries = (sample.entries || []).slice().reverse();  // module-log.js:81-86, newest first

    const p = panel("SY-15", t("gui_ml_title"));
    withMeta(p, tf("v2_sy_log_meta", { n: entries.length }));
    const modSel = selectField(modules.map(function (m) {
      const label = (m.i18n_key ? t(m.i18n_key) : (m.label || m.name)) + (m.count ? " (" + m.count + ")" : "");
      return [m.name, label];
    }), sampleModule, false);
    const levelPairs = LOG_LEVELS.map(function (pair) { return [pair[0], pair[0] ? pair[1] : t(pair[1])]; });
    const levelSel = selectField(levelPairs, "", false);
    const search = el("input", { class: "field", placeholder: t("gui_search") });
    const host = el("div");
    const raw = el("pre", { class: "console" });

    function rows() {
      const mod = modSel.value;
      if (mod !== sampleModule) return [];
      const lvl = levelSel.value;
      const q = search.value.toLowerCase().trim();
      return entries.filter(function (e) {
        if (lvl && e.level !== lvl) return false;
        if (q && String(e.msg).toLowerCase().indexOf(q) < 0) return false;
        return true;
      });
    }

    const PAGE = 40;
    let pageIndex = 0;

    function paint() {
      const list = rows();
      // The endpoint hands back 500 lines in one response; rendering all of them
      // as table rows makes an 8000px page nobody scrolls. The product's own
      // viewer gets away with it by being a fixed-height <pre> — the table pages.
      const pages = Math.max(1, Math.ceil(list.length / PAGE));
      if (pageIndex >= pages) pageIndex = pages - 1;
      const slice = list.slice(pageIndex * PAGE, pageIndex * PAGE + PAGE);
      const columns = [
        col("ts", t("v2_sy_log_ts"), widthCell(170, function (e) { return el("code", { class: "mono", text: e.ts }); })),
        col("level", t("v2_sy_log_level"), widthCell(90, function (e) {
          return badge(e.level, e.level === "ERROR" ? "crit" : (e.level === "WARNING" ? "warn" : "info"));
        })),
        col("msg", t("v2_sy_log_msg"), buildCell(function (e) { return el("span", { title: e.msg, text: e.msg }); })),
        col("act", "", widthCell(80, function (e) {
          return btn("btn ghost", t("gui_dlq_view"), function () { drawer.open(logDrawer(e, modSel.value)); });
        })),
      ];
      table.render(host, pagedTable(columns, slice, pageSpec(pageIndex, PAGE, list.length), function (next) {
        pageIndex = Math.max(0, Math.min(next, pages - 1));
        paint();
      }));
      raw.textContent = list.map(function (e) { return e.ts + " [" + e.level + "] " + e.msg; }).join("\n") || t("gui_ml_empty");
      if (modSel.value !== sampleModule) {
        raw.textContent = tf("v2_sy_log_nosnap", { module: sampleModule });
      }
    }

    function reset() { pageIndex = 0; paint(); }
    modSel.addEventListener("change", reset);
    levelSel.addEventListener("change", reset);
    search.addEventListener("input", reset);
    handles.first = function () { return drawer.open(logDrawer(entries[0] || null, sampleModule)); };

    p.body.appendChild(el("div", { class: "qrow" },
      el("div", { class: "qf" }, el("label", { text: t("gui_ml_title") }), modSel),
      el("div", { class: "qf" }, el("label", { text: t("v2_sy_log_level") }), levelSel),
      el("div", { class: "qf grow" }, el("label", { text: t("gui_search") }), search),
      el("div", { class: "qf" }, el("label", { text: " " }), btn("btn", t("gui_rs_refresh"), paint))));
    p.body.appendChild(host);
    p.body.appendChild(note(t("v2_sy_log_filters_new")));
    p.body.appendChild(sectionHead(t("v2_sy_log_raw")));
    p.body.appendChild(raw);
    p.body.appendChild(note(t("v2_sy_log_cap")));
    p.body.appendChild(note(t("v2_sy_log_i18n_gap")));
    board.appendChild(p);
    paint();
  });
}

export { mountPce, mountCache, mountSiem, mountTls, mountSecurity, mountDisplay, mountChannels, mountLogs };
