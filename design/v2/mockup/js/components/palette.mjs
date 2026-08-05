// palette.mjs — XC-02. Cmd/Ctrl+K command palette.
//
// Tasks 8-12 add their own commands with palette.register({id, label, run, group}).
// The shell seeds it with the six area jumps plus the two display toggles.

import { el, clear, dismissible } from "../core/dom.mjs";
import { t } from "../core/i18n.mjs";
import { audit } from "../core/audit.mjs";

const commands = new Map();   // id -> cmd

let wrap = null;
let input = null;
let list = null;
let dispose = null;
let selected = 0;
let filtered = [];

/** Subsequence fuzzy match; lower score = tighter match. null = no match. */
function score(label, query) {
  if (!query) return 0;
  const hay = label.toLowerCase();
  const needle = query.toLowerCase();
  if (hay.indexOf(needle) >= 0) return hay.indexOf(needle);
  let i = 0, last = -1, gaps = 0;
  for (let c = 0; c < needle.length; c++) {
    i = hay.indexOf(needle.charAt(c), last + 1);
    if (i < 0) return null;
    if (last >= 0) gaps += i - last - 1;
    last = i;
  }
  return 100 + gaps;
}

function match(query) {
  const out = [];
  commands.forEach(function (cmd) {
    const s = score(cmd.label + " " + (cmd.group || "") + " " + cmd.id, query);
    if (s !== null) out.push([s, cmd]);
  });
  out.sort(function (a, b) { return a[0] - b[0]; });
  return out.map(function (pair) { return pair[1]; });
}

function renderList() {
  clear(list);
  if (!filtered.length) {
    list.appendChild(el("li", { class: "palette-empty", text: t("v2_cmd_empty") }));
    return;
  }
  filtered.forEach(function (cmd, i) {
    const row = el("li", {
      role: "option",
      "aria-selected": i === selected ? "true" : "false",
      onClick: function () { runCommand(cmd); },
    },
      el("span", { text: cmd.label }),
      cmd.group ? el("span", { class: "grp", text: cmd.group }) : null
    );
    list.appendChild(row);
  });
}

function refresh() {
  filtered = match(input.value.trim());
  if (selected >= filtered.length) selected = 0;
  renderList();
}

function runCommand(cmd) {
  close();
  try { cmd.run(); } catch (e) { console.error("[palette] " + cmd.id, e); }
}

function onKey(e) {
  if (e.key === "ArrowDown") { e.preventDefault(); selected = Math.min(selected + 1, filtered.length - 1); renderList(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); selected = Math.max(selected - 1, 0); renderList(); }
  else if (e.key === "Enter") { e.preventDefault(); if (filtered[selected]) runCommand(filtered[selected]); }
}

function build() {
  input = el("input", { type: "text", placeholder: t("v2_cmd_placeholder"), "aria-label": t("v2_cmd_open") });
  input.addEventListener("input", refresh);
  input.addEventListener("keydown", onKey);
  list = el("ul", { role: "listbox" });

  const panel = el("div", { class: "palette" },
    input,
    list,
    el("div", { class: "palette-foot" }, el("kbd", { text: t("v2_cmd_hint") }))
  );
  wrap = el("div", { class: "palette-wrap scrim", "data-cov": "XC-02", role: "dialog", hidden: true }, panel);
  document.body.appendChild(wrap);
  return panel;
}

function openPalette() {
  if (!wrap) build();
  if (!wrap.hidden) return;      // idempotent for __openAllForAudit
  wrap.hidden = false;
  input.value = "";
  selected = 0;
  refresh();
  input.focus();
  dispose = dismissible(wrap.firstChild, close);
}

function close() {
  if (!wrap || wrap.hidden) return;
  if (dispose) { dispose(); dispose = null; }
  wrap.hidden = true;
}

export const palette = {
  /**
   * register({id, label, run, group?, route?}) — later registrations replace the
   * same id. A cmd with `route` is route-scoped: setRoute() drops it as soon as
   * the user leaves that route, so "run this report" cannot linger on the alerting
   * page. Without `route` the command is global (area jumps, display toggles).
   *
   * The inline-data lint caps object literals at four keys, so a route-scoped
   * command that also wants a group must use registerFor() instead of passing
   * five keys here.
   */
  register(cmd) {
    if (!cmd || !cmd.id || typeof cmd.run !== "function") throw new Error("palette.register needs {id, label, run}");
    commands.set(cmd.id, cmd);
    if (wrap && !wrap.hidden) refresh();
    return cmd.id;
  },

  /** registerFor(route, cmd) — same as register(), with cmd.route set for you. */
  registerFor(route, cmd) {
    const scoped = Object.assign({}, cmd);
    scoped.route = route;
    return this.register(scoped);
  },

  /**
   * setRoute(path) — called by the shell on every navigation. Drops every
   * route-scoped command that does not belong to `path`.
   */
  setRoute(path) {
    let changed = false;
    Array.from(commands.values()).forEach(function (cmd) {
      if (cmd.route && cmd.route !== path) { commands.delete(cmd.id); changed = true; }
    });
    if (changed && wrap && !wrap.hidden) refresh();
  },

  unregister(id) { commands.delete(id); },
  list() { return Array.from(commands.values()); },
  open() { openPalette(); },
  close() { close(); },
  toggle() { if (wrap && !wrap.hidden) close(); else openPalette(); },

  /** Binds Cmd/Ctrl+K and creates the (hidden) dialog so XC-02 exists from boot. */
  install() {
    if (!wrap) build();
    document.addEventListener("keydown", function (e) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        palette.toggle();
      }
    });
    audit.registerGlobal("palette", openPalette);
  },
};
