// shell.mjs — the chrome: brand, six-area nav (XC-14 route sync), palette button,
// user menu (XC-13) and the host the health rail (XC-01) mounts into.

import { el, dismissible } from "./core/dom.mjs";
import { t } from "./core/i18n.mjs";
import { router } from "./core/router.mjs";
import { theme, density, onDisplayChange } from "./core/theme.mjs";
import { palette } from "./components/palette.mjs";
import { audit } from "./core/audit.mjs";

class Area {
  constructor(id, key, route) {
    this.id = id;          // "overview" — also the nav highlight prefix
    this.key = key;        // i18n key for the Chinese label
    this.route = route;    // landing route of the area
  }
}

export const AREAS = [
  new Area("overview", "v2_nav_overview", "#/overview"),
  new Area("investigate", "v2_nav_investigate", "#/investigate/traffic"),
  new Area("alerting", "v2_nav_alerting", "#/alerting/rules"),
  new Area("automation", "v2_nav_automation", "#/automation/rules"),
  new Area("reports", "v2_nav_reports", "#/reports"),
  new Area("system", "v2_nav_system", "#/system/pce"),
];

export function areaOf(path) {
  const seg = String(path || "").replace(/^#\//, "").split("/")[0];
  let hit = null;
  AREAS.forEach(function (a) { if (a.id === seg) hit = a; });
  return hit;
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
  onDisplayChange(sync);
  return el("div", { class: "grp" }, el("div", { class: "eyebrow", text: labelText }), box);
}

function userMenu() {
  const host = el("dd", { class: "mono", text: "—" });
  const version = el("dd", { class: "mono", text: "—" });
  const tz = el("dd", { class: "mono", text: "—" });

  const chip = el("button", { class: "userchip", type: "button", "aria-expanded": "false", "aria-label": t("v2_user_menu") },
    el("span", { class: "avatar", text: "OPS" }),
    el("span", null, el("b", { text: t("gui_user") }), el("small", { text: "—" }))
  );

  const wrap = el("div", { class: "usermenu", "data-cov": "XC-13" }, chip);
  let pop = null;
  let dispose = null;

  function close() {
    if (!pop) return;
    dispose();
    dispose = null;
    wrap.removeChild(pop);
    pop = null;
    chip.setAttribute("aria-expanded", "false");
  }

  function open() {
    if (pop) return;
    pop = el("div", { class: "usermenu-pop", role: "menu" },
      segmented(t("gui_theme"), [["dark", t("gui_theme_dark")], ["light", t("gui_theme_light")]],
        function () { return theme.get(); }, function (v) { theme.set(v); }),
      segmented(t("gui_density"), [["cozy", t("v2_density_cozy")], ["compact", t("v2_density_compact")]],
        function () { return density.get(); }, function (v) { density.set(v); }),
      el("dl", null,
        el("div", null, el("dt", { text: t("v2_user_pce") }), host),
        el("div", null, el("dt", { text: t("v2_user_version") }), version),
        el("div", null, el("dt", { text: t("v2_user_timezone") }), tz)
      )
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
  return menu;
}

export function buildShell(mountPoint) {
  const nav = el("nav", { class: "areanav", "data-cov": "XC-14", "aria-label": t("v2_cmd_group_area") });
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
    el("span", { text: t("v2_cmd_open") }),
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

  router.onChange(function (path) {
    const active = areaOf(path);
    links.forEach(function (pair) {
      if (active && pair[0].id === active.id) pair[1].setAttribute("aria-current", "page");
      else pair[1].removeAttribute("aria-current");
    });
  });

  return { header: header, railHost: railHost, menu: menu };
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
      group: t("v2_cmd_group_area"),
      run: function () { router.go(area.route); },
    });
  });
  palette.register({
    id: "display:theme",
    label: t("v2_cmd_theme"),
    group: t("v2_cmd_group_display"),
    run: function () { theme.toggle(); },
  });
  palette.register({
    id: "display:density",
    label: t("v2_cmd_density"),
    group: t("v2_cmd_group_display"),
    run: function () { density.toggle(); },
  });
}
