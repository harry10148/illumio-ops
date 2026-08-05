// audit.mjs — backs window.__openAllForAudit().
//
// The coverage gate (design/v2/tools/gate_coverage.py) visits every route and
// collects [data-cov]. Anchors that only exist inside a drawer / modal / popover
// are invisible to it unless something opens them, so every component that hides
// an anchor registers an opener here. The router clears route-scoped openers on
// each navigation; global openers (palette, user menu) survive.
//
// Contract: __openAllForAudit() is idempotent — openers must no-op when their
// surface is already open — and safe on routes that registered nothing.

const routeOpeners = new Map();   // id -> fn
const globalOpeners = new Map();  // id -> fn

function run(map, errors) {
  Array.from(map.keys()).forEach(function (id) {
    try {
      const fn = map.get(id);
      if (typeof fn === "function") fn();
    } catch (e) {
      errors.push(id + ": " + String((e && e.message) || e));
    }
  });
}

export const audit = {
  /**
   * Register an opener bound to the CURRENT route. id must be stable.
   *
   * Call it synchronously, before the mount's first `await`. The router clears
   * the route registry as it navigates, so a register() that runs after an await
   * lands in whatever route the user has since moved to — the anchor is then
   * registered on the wrong page and the gate never sees it. The same rule
   * applies to every DOM insertion in an async mount: after each await, check
   * `ctx.stale()` and return if it is true.
   */
  register(id, open) { routeOpeners.set(id, open); },

  /** Register an opener that lives for the whole session (shell-level surfaces). */
  registerGlobal(id, open) { globalOpeners.set(id, open); },

  /** Router calls this before mounting a new area. */
  resetRoute() { routeOpeners.clear(); },

  /** Open everything registered for the current route. Returns a small summary. */
  openAll() {
    const errors = [];
    run(globalOpeners, errors);
    run(routeOpeners, errors);
    const opened = globalOpeners.size + routeOpeners.size;
    if (errors.length) console.warn("[__openAllForAudit] " + errors.join(" | "));
    return { opened: opened, errors: errors };
  },
};

export function installAuditHook() {
  window.__openAllForAudit = function () { return audit.openAll(); };
}
