// shell.mjs — the chrome: brand, six-area nav (XC-14 route sync), palette
// button, user menu (XC-13, with the real sign-out form LG-03) and the host
// the health rail (XC-01) mounts into.
//
// PORT OF design/v2/mockup/js/shell.mjs. Differences from the frozen mockup:
//   1. i18n keys renamed v2_* -> gui_* (v2_ never ships in the product
//      catalogue — see the Task 5 finding C1). Every key used here now
//      exists in src/i18n_en.json / src/i18n_zh_TW.json.
//   2. Sign-out (LG-03) is ADDED, and is not a port: the mockup has no
//      sign-out affordance anywhere, and neither did the legacy GUI
//      (verified: no /logout caller existed in src/templates/index.html or
//      any of src/static/js/*.js — POST /logout was a live backend route
//      with no way to reach it from the UI). v2 is now the only GUI, so it
//      has to carry it. It is a real <form method="post" action="/logout">,
//      not a fetch(): src/gui/routes/auth.py's logout() answers with a 302
//      to /login, which a normal form submit follows and an XHR would not.
//      The hidden csrf_token field is what flask-wtf's CSRFProtect reads for
//      a form post (WTF_CSRF_FIELD_NAME default); its value comes from the
//      same meta[name=csrf-token] tag core/api.mjs uses as its own token
//      source, so both paths stay on one token.
//   3. The mockup's own header comment called the rail host "the chrome";
//      here the health rail is still owned by app.mjs (it attaches/detaches
//      per route) — this module only creates the host element.

import { el, dismissible } from "./core/dom.mjs";
import { t } from "./core/i18n.mjs";
import { router } from "./core/router.mjs";
import { theme, density, onDisplayChange } from "./core/theme.mjs";
import { palette } from "./components/palette.mjs";
import { audit } from "./core/audit.mjs";

class Area {
  constructor(id, key, route) {
    this.id = id;          // "overview" — also the nav highlight prefix
    this.key = key;        // i18n key for the localized label
    this.route = route;    // landing route of the area
  }
}

export const AREAS = [
  new Area("overview", "gui_nav_overview", "#/overview"),
  new Area("investigate", "gui_nav_investigate", "#/investigate/traffic"),
  new Area("alerting", "gui_nav_alerting", "#/alerting/rules"),
  new Area("automation", "gui_nav_automation", "#/automation/rules"),
  new Area("reports", "gui_nav_reports", "#/reports"),
  new Area("system", "gui_nav_system", "#/system/pce"),
];

export function areaOf(path) {
  const seg = String(path || "").replace(/^#\//, "").split("/")[0];
  let hit = null;
  AREAS.forEach(function (a) { if (a.id === seg) hit = a; });
  return hit;
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
 * The real sign-out control (LG-03). See this file's header note 2 for why
 * this is a form submit rather than an api.post().
 */
function signOutForm() {
  return el("form", { class: "signout", method: "post", action: "/logout", "data-cov": "LG-03" },
    el("input", { type: "hidden", name: "csrf_token", value: csrfToken() }),
    el("button", { class: "btn", type: "submit", text: t("gui_logout") })
  );
}

function userMenu() {
  const host = el("dd", { class: "mono", text: "—" });
  const version = el("dd", { class: "mono", text: "—" });
  const tz = el("dd", { class: "mono", text: "—" });

  const chip = el("button", { class: "userchip", type: "button", "aria-expanded": "false", "aria-label": t("gui_user_menu") },
    el("span", { class: "avatar", text: "OPS" }),
    el("span", null, el("b", { text: t("gui_user") }), el("small", { text: "—" }))
  );

  const wrap = el("div", { class: "usermenu", "data-cov": "XC-13" }, chip);
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

export function buildShell(mountPoint) {
  const nav = el("nav", { class: "areanav", "data-cov": "XC-14", "aria-label": t("gui_cmd_group_area") });
  const links = [];
  AREAS.forEach(function (area) {
    const a = el("a", { href: area.route },
      el("span", { text: area.id }),
      el("u", { text: t(area.key) })
    );
    links.push([area, a]);
    nav.appendChild(a);
  });

  const paletteBtn = el("button", { class: "kbd-btn", type: "button", onClick: function () { palette.open(); } },
    el("span", { text: t("gui_cmd_open") }),
    el("kbd", { text: "⌘K" })
  );

  const menu = userMenu();

  const topbar = el("div", { class: "topbar" },
    el("a", { class: "brand", href: "#/overview" },
      el("b", { text: "illumio" }), el("i"), el("span", { text: "ops" })),
    nav,
    el("div", { class: "topright" }, paletteBtn, menu.el)
  );

  const railHost = el("div", { class: "rail-host" });
  const header = el("header", { class: "chrome" }, topbar, railHost);
  mountPoint.appendChild(header);

  // XC-14: the nav highlight follows the URL hash, so a cold load of any
  // deep route (or a Back press) lands with the right area marked.
  router.onChange(function (path) {
    const active = areaOf(path);
    links.forEach(function (pair) {
      if (active && pair[0].id === active.id) pair[1].setAttribute("aria-current", "page");
      else pair[1].removeAttribute("aria-current");
    });
  });

  return { header: header, railHost: railHost, menu: menu, nav: nav };
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

/** The six area jumps plus the two display toggles. */
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
