// app.mjs — v3.1 boot order: display prefs -> audit hook -> i18n -> the
// left-hand shell -> palette -> the open-alert badge -> router.
//
// What v3.1 removed from this file (spec §1): the health rail and the
// attach/detach machinery around it. The rail was chrome that only ever
// belonged on one route, so app.mjs owned HEALTH_ROUTES, a module-level
// railNode and a syncRail() that moved it in and out of the shell on every
// navigation. The rail is home-page CONTENT now — areas/home.mjs builds it
// from the two snapshots it already loads — so all of that is gone. The one
// thing that load also did for the chrome, filling the user popover with the
// appliance identity, stays here as its own small fetch.

import { api } from "./core/api.mjs";
import { t, i18n } from "./core/i18n.mjs";
import { initDisplay } from "./core/theme.mjs";
import { installAuditHook } from "./core/audit.mjs";
import { router } from "./core/router.mjs";
import { el } from "./core/dom.mjs";
import { pageHead } from "./components/page.mjs";
import { palette } from "./components/palette.mjs";
import { buildShell, applyStatus, seedPalette } from "./shell.mjs";

/**
 * Fill the user popover with the appliance identity (SH-02), and hang the
 * open-alert count off the nav (spec §1: "未處理告警數以小圓標掛在調查 › 告警").
 *
 * Both are chrome, both are one GET, and neither is allowed to keep the app
 * from booting: a failure leaves the popover on its em-dashes and the badge
 * hidden, and says so on the console rather than surfacing an error card over
 * a page that is otherwise fine.
 */
function mountShellIdentity(shell) {
  const status = api.load("status").then(function (snap) {
    applyStatus(shell.menu, snap);
  }).catch(function (e) {
    console.error("[app] status failed to load", e);
  });
  const alerts = api.load("alerts", { status: "new", page_size: 1 }).then(function (snap) {
    shell.setAlertCount((snap && snap.counts && snap.counts.new) || 0);
  }).catch(function (e) {
    console.error("[app] alert count failed to load", e);
  });
  return Promise.all([status, alerts]);
}

/**
 * The fallback mount: the four area landing paths that have no page of their
 * own (AREA_ROUTES below — the nav links straight to their sub-routes), plus
 * any hash that matches nothing. Every area IS built, so this says the address
 * has no page rather than claiming the feature is missing, and it no longer
 * prints the raw hash back at whoever mistyped it.
 */
async function mountPlaceholder(root, ctx) {
  /* The route stays a data attribute for the e2e suite and for anyone reading
   * the DOM; it is not chrome (density spec R4). */
  root.appendChild(pageHead({
    route: ctx.route,
    title: t("gui_shell_wip_title", "Page not found"),
  }));
  root.appendChild(el("section", { class: "wip", "data-tone": "info" },
    el("p", { text: t("gui_shell_wip_body",
      "There is no page at this address. Pick an area from the menu on the left."
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
  "#/policy",
  "#/system",
];


// v3 route table (spec §1.1). Legacy v2 hashes stay reachable as redirects so
// bookmarks and the mail/LINE deep links keep working; they use
// router.replace so Back does not bounce through the old hash.
const LEGACY_ROUTES = {
  "#/overview": "#/home",
  "#/alerting/rules": "#/policy/alert-rules",
  "#/alerting/ops": "#/policy/ops",
  "#/alerting": "#/policy/alert-rules",
  "#/automation/rules": "#/policy/rulesets",
  "#/automation/reports": "#/reports/schedules",
  "#/automation/jobs": "#/system/jobs",
  "#/automation": "#/policy/rulesets",
};

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

  // Lazy per-route import (router.mjs's documented pattern): nothing but
  // this shell fetches until #/overview is actually visited.
  router.register("#/home", async function (el2, ctx) {
    const { mountHome } = await import("./areas/home.mjs");
    return mountHome(el2, ctx);
  });
  // v3.1 §1.1: the alert list lives at #/investigate/alerts. Task 3 gives it
  // its own module; until then both hashes mount 3B's inbox, so the nav item
  // Task 1 adds is not a link to a "page not found".
  router.register("#/investigate/alerts", async function (el2, ctx) {
    const { mountInbox } = await import("./areas/investigate.mjs");
    return mountInbox(el2, ctx);
  });
  router.register("#/investigate/inbox", async function (el2, ctx) {
    const { mountInbox } = await import("./areas/investigate.mjs");
    return mountInbox(el2, ctx);
  });
  Object.keys(LEGACY_ROUTES).forEach(function (oldRoute) {
    router.register(oldRoute, async function (el2, ctx) {
      router.replace(LEGACY_ROUTES[oldRoute], ctx.query);
    });
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
  router.register("#/policy/alert-rules", async function (el2, ctx) {
    const { mountRules } = await import("./areas/policy_rules.mjs");
    return mountRules(el2, ctx);
  });
  router.register("#/policy/ops", async function (el2, ctx) {
    const { mountOps } = await import("./areas/policy_rules.mjs");
    return mountOps(el2, ctx);
  });
  router.register("#/system/alerting", async function (el2, ctx) {
    const { mountSystemAlerting } = await import("./areas/policy_rules.mjs");
    return mountSystemAlerting(el2, ctx);
  });
  // Task 7 — the automation area's three sub-routes, each lazily importing the
  // one module they share (same pattern as investigate/alerting above).
  // "#/automation" itself keeps its placeholder, same reasoning as
  // "#/investigate": no landing page of its own, only the sub-nav's targets.
  router.register("#/policy/rulesets", async function (el2, ctx) {
    const { mountRulesets } = await import("./areas/policy_scheduler.mjs");
    return mountRulesets(el2, ctx);
  });
  router.register("#/policy/schedules", async function (el2, ctx) {
    const { mountSchedules } = await import("./areas/policy_scheduler.mjs");
    return mountSchedules(el2, ctx);
  });
  router.register("#/reports/schedules", async function (el2, ctx) {
    const { mountAutoReports } = await import("./areas/policy_scheduler.mjs");
    return mountAutoReports(el2, ctx);
  });
  router.register("#/system/jobs", async function (el2, ctx) {
    const { mountAutoJobs } = await import("./areas/policy_scheduler.mjs");
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

  await Promise.all([mountShellIdentity(shell), router.start(areaRoot)]);
  document.body.dataset.booted = "true";
}

boot();
