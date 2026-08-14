// app.mjs — v2 boot order: display prefs -> audit hook -> i18n -> router
// (six-area placeholder routes) -> health rail (#/overview only).
//
// Task 2 builds only the core-layer plumbing — api/router/i18n/theme/toast/
// dom/fmt/audit and this file's boot sequence. The chrome (topbar nav, user
// menu, command palette) and every area's real content are later tasks (T3
// components, T4-T9 areas). This file's placeholder mount and inline
// health-rail rendering are deliberately minimal stand-ins that those tasks
// replace — see the comments on each below.

import { el } from "./core/dom.mjs";
import { api } from "./core/api.mjs";
import { t, tf, i18n } from "./core/i18n.mjs";
import { initDisplay } from "./core/theme.mjs";
import { installAuditHook } from "./core/audit.mjs";
import { router } from "./core/router.mjs";

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
 * A minimal, real-data health readout — NOT the mockup's five-light
 * healthbar (design/v2/mockup/js/components/healthbar.mjs), which is Task
 * 3's job to port as a real component. This just proves the wiring: real
 * /api/status fields reach the DOM, attached/detached by route exactly like
 * the eventual component will be (same syncRail mechanism, same railHost).
 */
async function mountHealth(railHost) {
  railNode = null;
  try {
    const status = await api.load("status");
    railNode = el("div", { id: "health-rail", class: "rail" },
      el("span", { class: "rail-cell", "data-field": "version", text: t("gui_status_version", "Version") + ": " + status.version }),
      el("span", { class: "rail-cell", "data-field": "rules_count", text: t("gui_status_rules_count", "Rules") + ": " + status.rules_count })
    );
  } catch (e) {
    railNode = el("div", { class: "rail-error", text: String((e && e.message) || e) });
  }
  // The load races the first route mount, so ask the router where we ended
  // up rather than assuming we are still on the route that started the fetch.
  syncRail(railHost, pathOf(router.current()));
}

/**
 * Every route this task has not built real content for yet. Names the route
 * so a reviewer walking the nav can tell a gap from a bug — same intent as
 * the mockup's areas/placeholder.mjs, rebuilt without its shell.mjs
 * dependency (the shell/nav chrome is Task 3).
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
// unknown hash after. #/overview and #/investigate/* are registered
// separately below (Tasks 4 and 5 — the areas with a real implementation)
// and left out of this list so the placeholder loop does not overwrite them.
// "#/investigate" itself keeps its placeholder: the area has no landing page
// of its own, only the three sub-routes its own sub-nav links to.
const AREA_ROUTES = [
  "#/investigate",
  "#/alerting",
  "#/automation",
  "#/reports",
  "#/system",
];

async function boot() {
  initDisplay();
  installAuditHook();
  await i18n.init();

  const topbar = document.getElementById("topbar");
  const areaRoot = document.getElementById("area-root");
  const railHost = el("div", { class: "rail-host" });
  topbar.appendChild(railHost);

  router.onChange(function (path) {
    syncRail(railHost, path);
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
  AREA_ROUTES.forEach(function (route) { router.register(route, mountPlaceholder); });
  router.setFallback(mountPlaceholder);

  await Promise.all([mountHealth(railHost), router.start(areaRoot)]);
  document.body.dataset.booted = "true";
}

boot();
