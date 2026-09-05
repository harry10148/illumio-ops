// shell.mjs — the chrome: a left-hand navigation (SH-01) that owns the brand,
// the five areas AND their sub-items, the command-palette entry (SH-03) and
// the user popover (SH-02, with the real sign-out form LG-03).
//
// v3.1 (spec docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md
// §1) replaced 3B's top bar. What changed, and why it is not a restyle:
//
//   1. Sub-navigation moved HERE. Every area used to draw its own `.subnav`
//      from its own private SUB_ROUTES table — five tables, five copies of the
//      same loop, and no single place that could answer "what is under
//      System?". NAV below is that single place; the areas draw content only.
//   2. The health rail left the chrome entirely. It is home-page content now
//      (spec §1: "健康燈不再是頂欄元件"), so this module no longer creates a
//      host for it and app.mjs no longer attaches or detaches one.
//   3. The palette entry and the user menu moved to the foot of the nav.
//
// Unchanged and deliberately so: sign-out is still a real
// <form method="post" action="/logout"> whose CSRF field is filled at SUBMIT
// time from core/api.mjs's own token refresh — see signOutForm() for what a
// stale field costs (src/gui/__init__.py answers /logout's CSRFError with a
// JSON 400, so logout_user() never runs and the operator believes a live
// session is dead).

import { el, dismissible, clear } from "./core/dom.mjs";
import { t } from "./core/i18n.mjs";
import { api } from "./core/api.mjs";
import { router } from "./core/router.mjs";
import { theme, density, onDisplayChange } from "./core/theme.mjs";
import { palette } from "./components/palette.mjs";
import { audit } from "./core/audit.mjs";

// The five areas and every sub-item under them (spec §1). `route` is where the
// area link goes; `children` are [href, i18n key] pairs, rendered only while
// that area is the current one. The System list is the ten routes system.mjs
// and policy_scheduler.mjs register between them.
export const NAV = [
  { id: "home", key: "gui_nav_home", route: "#/home", children: [] },
  {
    id: "investigate", key: "gui_nav_investigate", route: "#/investigate/alerts",
    children: [
      ["#/investigate/alerts", "gui_nav_alerts"],
      ["#/investigate/traffic", "gui_nav_traffic_search"],
      ["#/investigate/workloads", "gui_workload_search"],
      ["#/investigate/events", "gui_event_viewer"],
    ],
  },
  {
    id: "policy", key: "gui_nav_policy", route: "#/policy/alert-rules",
    children: [
      ["#/policy/alert-rules", "gui_policy_tab_alert_rules"],
      ["#/policy/rulesets", "gui_policy_tab_rulesets"],
      ["#/policy/schedules", "gui_policy_tab_schedules"],
      ["#/policy/ops", "gui_actions"],
    ],
  },
  {
    id: "reports", key: "gui_nav_reports", route: "#/reports",
    children: [
      ["#/reports", "gui_nav_reports"],
      ["#/reports/schedules", "gui_tab_report_schedules"],
    ],
  },
  {
    id: "system", key: "gui_nav_system", route: "#/system/pce",
    children: [
      ["#/system/pce", "gui_settings_tab_pce"],
      ["#/system/cache", "gui_it_cache"],
      ["#/system/siem", "gui_siem_forwarder"],
      ["#/system/tls", "gui_tls_title"],
      ["#/system/security", "gui_settings_tab_security"],
      ["#/system/display", "gui_settings_tab_display"],
      ["#/system/channels", "gui_settings_tab_channels"],
      ["#/system/alerting", "gui_system_tab_alerting"],
      ["#/system/jobs", "gui_ov_job_health"],
      ["#/system/logs", "gui_ml_title"],
    ],
  },
];

// The unread-alert badge hangs off this sub-item, and off its AREA link while
// that area is collapsed — so the count is visible from every page, not only
// from inside Investigate.
const ALERTS_ROUTE = "#/investigate/alerts";

class Area {
  constructor(id, key, route) {
    this.id = id;          // "investigate" — also the nav highlight prefix
    this.key = key;        // i18n key for the localized label
    this.route = route;    // landing route of the area
  }
}

// Kept as its own export: the command palette seeds one jump per area, and the
// e2e suites name areas rather than NAV rows. Derived, so the two can never
// disagree.
export const AREAS = NAV.map(function (a) { return new Area(a.id, a.key, a.route); });

export function areaOf(path) {
  const seg = String(path || "").replace(/^#\//, "").split("/")[0];
  let hit = null;
  AREAS.forEach(function (a) { if (a.id === seg) hit = a; });
  return hit;
}

function pathOf(route) {
  const q = String(route || "").indexOf("?");
  return q < 0 ? String(route || "") : String(route).slice(0, q);
}

function csrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") : "";
}

function segmented(labelText, options, get, set) {
  const box = el("div", { class: "seg" });
  const buttons = [];
  options.forEach(function (pair) {
    const b = el("button", { type: "button", text: pair[1] });
    b.addEventListener("click", function () { set(pair[0]); });
    buttons.push([pair[0], b]);
    box.appendChild(b);
  });
  function sync() {
    const now = get();
    buttons.forEach(function (pair) { pair[1].setAttribute("aria-pressed", pair[0] === now ? "true" : "false"); });
  }
  sync();
  const unsubscribe = onDisplayChange(sync);
  return { el: el("div", { class: "grp" }, el("div", { class: "eyebrow", text: labelText }), box), destroy: unsubscribe };
}

/**
 * The real sign-out control (LG-03). See this file's header note for why this
 * is a form submit rather than an api.post().
 *
 * The hidden field is filled at SUBMIT time, not at build time. A token
 * snapshotted when the menu opened can be one the server has since stopped
 * accepting (core/api.mjs refreshes the app's token on any csrf_error, and
 * this form never hears about it). api.csrf() is that same refresh — this
 * module adds no second CSRF implementation — and form.submit() then submits
 * WITHOUT re-firing this handler, so the native 302-following post still
 * happens exactly once.
 */
function signOutForm() {
  const token = el("input", { type: "hidden", name: "csrf_token", value: csrfToken() });
  const submit = el("button", { class: "btn", type: "submit", text: t("gui_logout") });
  const form = el("form", { class: "signout", method: "post", action: "/logout", "data-cov": "LG-03" },
    token, submit);
  let submitting = false;
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    submit.disabled = true;
    api.csrf().then(function (fresh) {
      token.value = fresh || csrfToken();
      form.submit();
    });
  });
  return form;
}

function userMenu() {
  const host = el("dd", { class: "mono", text: "—" });
  const version = el("dd", { class: "mono", text: "—" });
  const tz = el("dd", { class: "mono", text: "—" });

  const chip = el("button", {
    class: "who", type: "button", "data-cov": "SH-02",
    "aria-expanded": "false", "aria-label": t("gui_shell_user_menu"),
  },
    el("b", { text: t("gui_user") }),
    el("small", { text: "—" })
  );

  const wrap = el("div", { class: "usermenu" }, chip);
  let pop = null;
  let dispose = null;
  let segments = [];

  function close() {
    if (!pop) return;
    dispose();
    dispose = null;
    // The two segmented controls subscribe to onDisplayChange while they are
    // on screen; dropping the popover without unsubscribing would leave one
    // more dead listener behind every time the menu is opened and closed.
    segments.forEach(function (s) { s.destroy(); });
    segments = [];
    wrap.removeChild(pop);
    pop = null;
    chip.setAttribute("aria-expanded", "false");
  }

  function open() {
    if (pop) return;
    const themeSeg = segmented(t("gui_theme"), [["dark", t("gui_theme_dark")], ["light", t("gui_theme_light")]],
      function () { return theme.get(); }, function (v) { theme.set(v); });
    const densitySeg = segmented(t("gui_density"), [["cozy", t("gui_density_cozy")], ["compact", t("gui_density_compact")]],
      function () { return density.get(); }, function (v) { density.set(v); });
    segments = [themeSeg, densitySeg];
    pop = el("div", { class: "usermenu-pop", role: "menu" },
      themeSeg.el,
      densitySeg.el,
      el("dl", null,
        el("div", null, el("dt", { text: t("gui_user_pce") }), host),
        el("div", null, el("dt", { text: t("gui_user_version") }), version),
        el("div", null, el("dt", { text: t("gui_user_timezone") }), tz)
      ),
      signOutForm()
    );
    wrap.appendChild(pop);
    chip.setAttribute("aria-expanded", "true");
    dispose = dismissible(wrap, close);
  }

  chip.addEventListener("click", function () { if (pop) close(); else open(); });
  audit.registerGlobal("usermenu", open);

  const menu = {};
  menu.el = wrap;
  menu.host = host;
  menu.version = version;
  menu.tz = tz;
  menu.chip = chip;
  menu.open = open;
  menu.close = close;
  return menu;
}

/** A small round count, or nothing at all while the number is zero/unknown. */
function countNode() {
  return el("span", { class: "cnt", hidden: true });
}

export function buildShell(mountPoint) {
  const nav = el("nav", { class: "sidenav", "data-cov": "SH-01", "aria-label": t("gui_cmd_group_area") });

  nav.appendChild(el("div", { class: "brand" },
    el("b", { text: "illumio" }), el("i"), el("span", { text: "ops" })));

  // One [area link, its (initially empty) sub host, its collapsed-state count]
  // per area. The sub host is filled on route change and emptied again when
  // the area stops being current, so the DOM only ever holds one area's
  // children — "the nav is not a sitemap" (spec §1).
  const rows = [];
  NAV.forEach(function (area) {
    const cnt = countNode();
    const link = el("a", { href: area.route },
      el("span", { text: t(area.key) }),
      area.id === "investigate" ? cnt : null);
    const sub = el("div", { class: "sub", hidden: true });
    nav.appendChild(link);
    nav.appendChild(sub);
    rows.push({ area: area, link: link, sub: sub, cnt: cnt, subCnt: null });
  });

  nav.appendChild(el("div", { class: "spacer" }));

  const paletteBtn = el("button", {
    class: "kbd-row", type: "button", "data-cov": "SH-03",
    onClick: function () { palette.open(); },
  },
    el("span", { text: t("gui_shell_search_jump") }),
    el("kbd", { text: "⌘K" })
  );
  nav.appendChild(paletteBtn);

  const menu = userMenu();
  nav.appendChild(menu.el);
  mountPoint.appendChild(nav);

  let alertCount = null;

  function paintCounts() {
    rows.forEach(function (row) {
      [row.cnt, row.subCnt].forEach(function (node) {
        if (!node) return;
        const show = alertCount !== null && alertCount > 0;
        node.textContent = show ? String(alertCount) : "";
        node.hidden = !show;
      });
    });
    // While Investigate is expanded the badge belongs to its Alerts child, not
    // to the area row, or the same number is printed twice one line apart.
    const investigate = rows.filter(function (r) { return r.area.id === "investigate"; })[0];
    if (investigate && investigate.subCnt) investigate.cnt.hidden = true;
  }

  // SH-01: the highlight and the expanded sub-list both follow the URL hash,
  // so a cold load of a deep route (or a Back press) lands with the right area
  // open. `aria-current="page"` marks the ONE current page; an area whose
  // child is current is an ancestor, and says so with "true".
  function syncNav(route) {
    const path = pathOf(route);
    const active = areaOf(path);
    rows.forEach(function (row) {
      const isArea = active && row.area.id === active.id;
      row.subCnt = null;
      clear(row.sub);
      row.sub.hidden = true;
      const children = NAV.filter(function (a) { return a.id === row.area.id; })[0].children;
      // Exactly ONE link in the whole nav may say aria-current="page", and it
      // is the deepest one that matches. #/reports is both an area landing
      // route and one of that area's sub-items, so without this the area link
      // and its child would both claim to be the page.
      const childIsCurrent = isArea && children.some(function (pair) { return pair[0] === path; });
      if (row.area.route === path && !childIsCurrent) row.link.setAttribute("aria-current", "page");
      else if (isArea) row.link.setAttribute("aria-current", "true");
      else row.link.removeAttribute("aria-current");
      if (!isArea || !children.length) return;
      children.forEach(function (pair) {
        const a = el("a", { href: pair[0], text: t(pair[1]) });
        if (pair[0] === path) a.setAttribute("aria-current", "page");
        if (pair[0] === ALERTS_ROUTE) {
          row.subCnt = countNode();
          a.appendChild(row.subCnt);
        }
        row.sub.appendChild(a);
      });
      row.sub.hidden = false;
    });
    paintCounts();
  }

  router.onChange(syncNav);
  syncNav(router.current());

  return {
    nav: nav,
    menu: menu,
    /** Write the open-alert count onto the nav; null hides the badge. */
    setAlertCount: function (n) {
      alertCount = (n === null || n === undefined || isNaN(Number(n))) ? null : Number(n);
      paintCounts();
    },
  };
}

/** Fill the user menu with the appliance identity from the status snapshot. */
export function applyStatus(menu, status) {
  const url = String((status && status.api_url) || "");
  menu.host.textContent = url.replace(/^https?:\/\//, "") || "—";
  menu.version.textContent = "v" + ((status && status.version) || "—");
  menu.tz.textContent = (status && status.timezone) || "—";
  const small = menu.chip.querySelector("small");
  if (small) small.textContent = url.replace(/^https?:\/\//, "");
}

/** The five area jumps plus the two display toggles. */
export function seedPalette() {
  AREAS.forEach(function (area) {
    palette.register({
      id: "go:" + area.id,
      label: t(area.key) + " · " + area.route,
      group: t("gui_cmd_group_area"),
      run: function () { router.go(area.route); },
    });
  });
  palette.register({
    id: "display:theme",
    label: t("gui_cmd_theme"),
    group: t("gui_cmd_group_display"),
    run: function () { theme.toggle(); },
  });
  palette.register({
    id: "display:density",
    label: t("gui_cmd_density"),
    group: t("gui_cmd_group_display"),
    run: function () { density.toggle(); },
  });
}
