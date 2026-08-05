// app.mjs — boot order for the mockup shell.
//   display prefs -> audit hook -> i18n -> chrome -> health rail -> palette -> router
//
// The health rail is built here but only shown on #/overview — see syncRail().

import { el } from "./core/dom.mjs";
import { store } from "./core/store.mjs";
import { initI18n } from "./core/i18n.mjs";
import { initDisplay } from "./core/theme.mjs";
import { installAuditHook } from "./core/audit.mjs";
import { router } from "./core/router.mjs";
import { healthbar } from "./components/healthbar.mjs";
import { palette } from "./components/palette.mjs";
import { drawer } from "./components/drawer.mjs";
import { modal } from "./components/modal.mjs";
import { errorCard } from "./components/errorcard.mjs";
import { buildShell, applyStatus, seedPalette } from "./shell.mjs";
import { mountOverview } from "./areas/overview.mjs";
import { mountTraffic, mountWorkloads, mountEvents } from "./areas/investigate.mjs";
import { mountRules, mountOps } from "./areas/alerting.mjs";
import { mountAutoRules, mountAutoReports, mountAutoJobs } from "./areas/automation.mjs";
import { mountReports } from "./areas/reports.mjs";
import { mountPce, mountCache, mountSiem, mountTls, mountSecurity, mountDisplay, mountChannels, mountLogs } from "./areas/system.mjs";
import { mountPlaceholder } from "./areas/placeholder.mjs";

// XC-01 lives on the overview only (spec §1.1, amended at Gate 2). The rail is
// still built once at boot — the same snapshot pair fills the user menu, and
// rebuilding it on every visit would refetch for no reason — but it is attached
// to the chrome only while #/overview is mounted.
//
// Detach, not hide: `hidden` loses to any `display` rule (this repo has been
// bitten by exactly that), and an element that is merely invisible still shows
// up in the coverage gate's `[data-cov]` sweep on every route.
const HEALTH_ROUTE = "#/overview";
let railNode = null;

function syncRail(railHost, path) {
  if (!railNode) return;
  const on = path === HEALTH_ROUTE;
  if (on && railNode.parentNode !== railHost) railHost.appendChild(railNode);
  else if (!on && railNode.parentNode === railHost) railHost.removeChild(railNode);
}

function pathOf(route) {
  const q = String(route || "").indexOf("?");
  return q < 0 ? String(route || "") : String(route).slice(0, q);
}

async function mountHealth(railHost, menu) {
  railNode = null;
  while (railHost.firstChild) railHost.removeChild(railHost.firstChild);
  try {
    const snaps = await Promise.all([store.load("status"), store.load("dashboard_overview")]);
    applyStatus(menu, snaps[0]);
    railNode = healthbar.render(snaps[0], snaps[1]);
  } catch (e) {
    railNode = el("div", { class: "rail-error" }, errorCard({
      id: "status / dashboard_overview",
      error: e,
      onRetry: function () { return mountHealth(railHost, menu); },
    }));
  }
  // The load races the first route mount, so ask the router where we ended up
  // rather than assuming we are still on the route that started the fetch.
  syncRail(railHost, pathOf(router.current()));
}

async function boot() {
  initDisplay();
  installAuditHook();
  await initI18n();

  const shellHost = document.getElementById("shell");
  const areaRoot = document.getElementById("area-root");
  const shell = buildShell(shellHost);

  palette.install();
  seedPalette();

  // Leaving a route must not strand its overlays — or its commands — on the next
  // one. onChange runs before the new mount, so the incoming area registers its
  // own route-scoped commands after the outgoing ones have been dropped.
  router.onChange(function (path) {
    drawer.closeAll();
    modal.closeAll();
    palette.setRoute(path);
    syncRail(shell.railHost, path);
  });

  router.register("#/overview", mountOverview);
  router.register("#/investigate/traffic", mountTraffic);
  router.register("#/investigate/workloads", mountWorkloads);
  router.register("#/investigate/events", mountEvents);
  router.register("#/alerting/rules", mountRules);
  router.register("#/alerting/ops", mountOps);
  router.register("#/automation/rules", mountAutoRules);
  router.register("#/automation/reports", mountAutoReports);
  router.register("#/automation/jobs", mountAutoJobs);
  router.register("#/reports", mountReports);
  router.register("#/system/pce", mountPce);
  router.register("#/system/cache", mountCache);
  router.register("#/system/siem", mountSiem);
  router.register("#/system/tls", mountTls);
  router.register("#/system/security", mountSecurity);
  router.register("#/system/display", mountDisplay);
  router.register("#/system/channels", mountChannels);
  router.register("#/system/logs", mountLogs);
  router.setFallback(mountPlaceholder);

  await Promise.all([mountHealth(shell.railHost, shell.menu), router.start(areaRoot)]);
  document.body.dataset.booted = "true";
}

boot();
