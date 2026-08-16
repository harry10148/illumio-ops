// app.mjs — v2 boot order: display prefs -> audit hook -> i18n -> chrome ->
// palette -> health rail (#/overview only) -> router.
//
// Task 11 (switchover) replaced this file's two Task-2 stand-ins with the
// real things, now that v2 is the only GUI:
//   - the chrome. Task 2 mounted nothing but a bare rail host into #topbar;
//     shell.mjs now builds the brand, the six-area nav (XC-14), the palette
//     button, the user menu (XC-13) and the sign-out form (LG-03).
//   - the health rail. Task 2 rendered two /api/status fields inline as
//     proof of wiring; components/healthbar.mjs (XC-01, ported in Task 3)
//     now renders the real five lights from the same two snapshots that
//     fill the user menu, with an XC-10 error card on failure.
// The attach/detach mechanism around the rail (syncRail) is unchanged.

import { api } from "./core/api.mjs";
import { t, tf, i18n } from "./core/i18n.mjs";
import { initDisplay } from "./core/theme.mjs";
import { installAuditHook } from "./core/audit.mjs";
import { router } from "./core/router.mjs";
import { el } from "./core/dom.mjs";
import { healthbar } from "./components/healthbar.mjs";
import { palette } from "./components/palette.mjs";
import { errorCard } from "./components/errorcard.mjs";
import { buildShell, applyStatus, seedPalette } from "./shell.mjs";

// XC-01 (health rail) lives on the overview only (spec §1.1, amended at Gate
// 2). Detach, not hide: `hidden` loses to any `display` rule, and a merely
// invisible element still shows up in the coverage gate's `[data-cov]` sweep
// on every route — this mirrors design/v2/mockup/js/app.mjs's syncRail.
const HEALTH_ROUTE = "#/overview";
let railNode = null;

function pathOf(route) {
  const q = String(route || "").indexOf("?");
  return q < 0 ? String(route || "") : String(route).slice(0, q);
}

function syncRail(railHost, path) {
  if (!railNode) return;
  const on = path === HEALTH_ROUTE;
  if (on && railNode.parentNode !== railHost) railHost.appendChild(railNode);
  else if (!on && railNode.parentNode === railHost) railHost.removeChild(railNode);
}

/**
 * Build the five-light rail (XC-01) from the two live snapshots, and fill the
 * user menu from the same status payload — one pair of loads, two consumers,
 * exactly as design/v2/mockup/js/app.mjs does it.
 *
 * On failure the rail slot carries an XC-10 error card whose retry re-runs
 * this same function, so a transient /api/status or
 * /api/dashboard/overview_summary failure is recoverable without a reload.
 */
async function mountHealth(railHost, menu) {
  // A retry re-enters here: drop whatever the previous attempt left attached
  // (rail or error card) before building the replacement, or the two stack up.
  if (railNode && railNode.parentNode === railHost) railHost.removeChild(railNode);
  if (railNode && typeof railNode.destroy === "function") railNode.destroy();
  railNode = null;
  try {
    const snaps = await Promise.all([api.load("status"), api.load("dashboard_overview")]);
    applyStatus(menu, snaps[0]);
    railNode = healthbar.render(snaps[0], snaps[1]);
  } catch (e) {
    railNode = el("div", { class: "rail-error" }, errorCard({
      id: "status / dashboard_overview",
      error: e,
      onRetry: function () { return mountHealth(railHost, menu); },
    }));
  }
  // The load races the first route mount, so ask the router where we ended
  // up rather than assuming we are still on the route that started the fetch.
  syncRail(railHost, pathOf(router.current()));
}

/**
 * Every route this task has not built real content for yet. Names the route
 * so a reviewer walking the nav can tell a gap from a bug — same intent as
 * the mockup's areas/placeholder.mjs, rebuilt without its shell.mjs
 * dependency. The four routes still on it (AREA_ROUTES below) are area
 * landing paths that have no page of their own by design, not gaps.
 */
async function mountPlaceholder(root, ctx) {
  root.appendChild(el("div", { class: "area-head" },
    el("h1", { text: t("gui_shell_wip_title", "Coming soon") }),
    el("code", { text: ctx.route })
  ));
  root.appendChild(el("section", { class: "wip", "data-tone": "info" },
    el("p", { text: tf("gui_shell_wip_body", { route: ctx.route },
      "This area has not been built yet. Route: {route}"
    ) })
  ));
}

// The six functional areas the plan replaces the legacy 8-tab GUI with
// (docs/superpowers/plans/2026-08-06-phase2a-gui.md Tasks 4-9). Each area's
// own task registers its real sub-routes (e.g. #/investigate/traffic); the
// fallback mount below covers any of those before that task lands, and any
// unknown hash after. #/overview, #/investigate/*, #/alerting/*,
// #/automation/*, #/reports and #/system/* are registered separately below
// (Tasks 4, 5, 6, 7, 8 and 9 — every area now has a real implementation) and
// left out of this list so the placeholder loop does not overwrite them.
// "#/investigate", "#/automation" and "#/system" themselves keep their
// placeholder: none of the three has a landing page of its own, only the
// sub-routes their own sub-nav links to.
const AREA_ROUTES = [
  "#/investigate",
  "#/alerting",
  "#/automation",
  "#/system",
];

async function boot() {
  initDisplay();
  installAuditHook();
  await i18n.init();

  const shellHost = document.getElementById("shell");
  const areaRoot = document.getElementById("area-root");
  const shell = buildShell(shellHost);

  // The palette dialog (XC-02) and its Cmd/Ctrl+K binding exist from boot, on
  // every route — the six area jumps and the two display toggles are global
  // commands; each area adds its own route-scoped ones and drops them again
  // in its own teardown (areas/*.mjs installTeardown -> palette.setRoute).
  palette.install();
  seedPalette();

  router.onChange(function (path) {
    syncRail(shell.railHost, path);
  });

  // Lazy per-route import (router.mjs's documented pattern): nothing but
  // this shell fetches until #/overview is actually visited.
  router.register("#/overview", async function (el2, ctx) {
    const { mountOverview } = await import("./areas/overview.mjs");
    return mountOverview(el2, ctx);
  });
  // Task 5 — the investigate area's three sub-routes, each lazily importing
  // the one module they share. Registered before the placeholder loop would
  // be harmless either way (the loop only registers "#/investigate" itself),
  // but they are grouped with #/overview because they are real areas.
  router.register("#/investigate/traffic", async function (el2, ctx) {
    const { mountTraffic } = await import("./areas/investigate.mjs");
    return mountTraffic(el2, ctx);
  });
  router.register("#/investigate/workloads", async function (el2, ctx) {
    const { mountWorkloads } = await import("./areas/investigate.mjs");
    return mountWorkloads(el2, ctx);
  });
  router.register("#/investigate/events", async function (el2, ctx) {
    const { mountEvents } = await import("./areas/investigate.mjs");
    return mountEvents(el2, ctx);
  });
  router.register("#/alerting/rules", async function (el2, ctx) {
    const { mountRules } = await import("./areas/alerting.mjs");
    return mountRules(el2, ctx);
  });
  router.register("#/alerting/ops", async function (el2, ctx) {
    const { mountOps } = await import("./areas/alerting.mjs");
    return mountOps(el2, ctx);
  });
  // Task 7 — the automation area's three sub-routes, each lazily importing the
  // one module they share (same pattern as investigate/alerting above).
  // "#/automation" itself keeps its placeholder, same reasoning as
  // "#/investigate": no landing page of its own, only the sub-nav's targets.
  router.register("#/automation/rules", async function (el2, ctx) {
    const { mountAutoRules } = await import("./areas/automation.mjs");
    return mountAutoRules(el2, ctx);
  });
  router.register("#/automation/reports", async function (el2, ctx) {
    const { mountAutoReports } = await import("./areas/automation.mjs");
    return mountAutoReports(el2, ctx);
  });
  router.register("#/automation/jobs", async function (el2, ctx) {
    const { mountAutoJobs } = await import("./areas/automation.mjs");
    return mountAutoJobs(el2, ctx);
  });
  // Task 8 — the reports area's single route.
  router.register("#/reports", async function (el2, ctx) {
    const { mountReports } = await import("./areas/reports.mjs");
    return mountReports(el2, ctx);
  });
  // Task 9 — the system area's eight sub-routes, each lazily importing the
  // one module they share (same pattern as investigate/alerting/automation
  // above). "#/system" itself keeps its placeholder, same reasoning as
  // "#/investigate"/"#/automation": no landing page of its own, only the
  // sub-nav's eight targets.
  router.register("#/system/pce", async function (el2, ctx) {
    const { mountPce } = await import("./areas/system.mjs");
    return mountPce(el2, ctx);
  });
  router.register("#/system/cache", async function (el2, ctx) {
    const { mountCache } = await import("./areas/system.mjs");
    return mountCache(el2, ctx);
  });
  router.register("#/system/siem", async function (el2, ctx) {
    const { mountSiem } = await import("./areas/system.mjs");
    return mountSiem(el2, ctx);
  });
  router.register("#/system/tls", async function (el2, ctx) {
    const { mountTls } = await import("./areas/system.mjs");
    return mountTls(el2, ctx);
  });
  router.register("#/system/security", async function (el2, ctx) {
    const { mountSecurity } = await import("./areas/system.mjs");
    return mountSecurity(el2, ctx);
  });
  router.register("#/system/display", async function (el2, ctx) {
    const { mountDisplay } = await import("./areas/system.mjs");
    return mountDisplay(el2, ctx);
  });
  router.register("#/system/channels", async function (el2, ctx) {
    const { mountChannels } = await import("./areas/system.mjs");
    return mountChannels(el2, ctx);
  });
  router.register("#/system/logs", async function (el2, ctx) {
    const { mountLogs } = await import("./areas/system.mjs");
    return mountLogs(el2, ctx);
  });
  AREA_ROUTES.forEach(function (route) { router.register(route, mountPlaceholder); });
  router.setFallback(mountPlaceholder);

  await Promise.all([mountHealth(shell.railHost, shell.menu), router.start(areaRoot)]);
  document.body.dataset.booted = "true";
}

boot();
