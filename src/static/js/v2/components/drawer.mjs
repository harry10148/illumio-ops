// drawer.mjs — right-side editing surface. Areas own the body; the drawer owns
// the frame, the scrim, Escape handling and the save/cancel row.
//
// PORT OF design/v2/mockup/js/components/drawer.mjs. Two differences from the
// mockup, both required by this task's a11y/teardown brief:
//
//   1. aria-modal="true" (the mockup shipped "false") + a real focus trap:
//      Tab/Shift+Tab is confined to the panel via dom.mjs's shared
//      trapFocus(), and the element that had focus before open() is captured
//      as `opener` and refocused when the drawer closes.
//   2. Teardown contract: `handle.destroy` is an alias for `handle.close`
//      (every v2 component exposes destroy()), and `handle.onClose(fn)`
//      registers a callback that runs exactly once whenever the drawer goes
//      away, however it closes (Save, Cancel, Esc, scrim click, or a caller
//      calling handle.close()/.destroy() directly). This is how a component
//      mounted *inside* a drawer gets torn down: the opener does
//        const handle = drawer.open({ title, body: hostEl, onSave });
//        const fb = createFilterBar(hostEl, opts);
//        handle.onClose(() => fb.destroy());
//      Tasks 4-9 follow this exact pattern for any stateful component (a
//      FilterBar, a chart with a ResizeObserver, …) mounted in a drawer body.

import { el, spacer, closeButton, dismissible, trapFocus } from "../core/dom.mjs";
import { t } from "../core/i18n.mjs";
import { audit } from "../core/audit.mjs";

const open_ = new Set();

/**
 * drawer.open({title, body, onSave}) -> handle
 *   title  — string
 *   body   — HTMLElement placed in the scrollable area
 *   onSave — optional async () => void|false; false keeps the drawer open
 * handle: {el, close(), destroy(), onClose(fn)}
 */
function open(opts) {
  const o = opts || {};
  const opener = document.activeElement;
  const scrim = el("div", { class: "scrim" });
  const panel = el("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": o.title || "" });

  const closeCallbacks = [];
  const handle = {
    el: panel,
    close: close,
    /** onClose(fn) — register a teardown callback; runs once, on any close path. */
    onClose(fn) { if (typeof fn === "function") closeCallbacks.push(fn); },
  };
  handle.destroy = close;

  function close() {
    if (!open_.has(handle)) return;
    open_.delete(handle);
    dispose();
    disposeTrap();
    if (scrim.parentNode) scrim.parentNode.removeChild(scrim);
    if (panel.parentNode) panel.parentNode.removeChild(panel);
    if (opener && typeof opener.focus === "function") opener.focus();
    closeCallbacks.forEach(function (fn) {
      try { fn(); } catch (e) { console.error("[drawer] onClose callback failed", e); }
    });
  }

  const save = el("button", { class: "btn primary", type: "button", text: t("gui_save") });
  save.addEventListener("click", async function () {
    save.disabled = true;
    try {
      const r = await o.onSave();
      if (r !== false) close();
    } finally { save.disabled = false; }
  });

  panel.appendChild(el("header", { class: "drawer-h" },
    el("h2", { text: o.title || "" }),
    spacer(),
    closeButton(t("gui_close"), close)
  ));
  panel.appendChild(el("div", { class: "drawer-b" }, o.body || null));
  panel.appendChild(el("footer", { class: "drawer-f" },
    spacer(),
    el("button", { class: "btn ghost", type: "button", text: t("gui_cancel"), onClick: close }),
    o.onSave ? save : null
  ));

  scrim.addEventListener("mousedown", close);
  document.body.appendChild(scrim);
  document.body.appendChild(panel);
  const dispose = dismissible(panel, close);
  const disposeTrap = trapFocus(panel);
  open_.add(handle);
  return handle;
}

export const drawer = {
  open: open,
  /** Close everything — used by the router between routes. */
  closeAll() { Array.from(open_).forEach(function (h) { h.close(); }); },
  /**
   * registerAudit(id, factory) — makes this drawer reachable by
   * window.__openAllForAudit(); the opener is idempotent.
   */
  registerAudit(id, factory) {
    let live = null;
    audit.register(id, function () {
      if (live && open_.has(live)) return;
      live = factory();
    });
  },
};
