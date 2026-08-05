// drawer.mjs — right-side editing surface. Areas own the body; the drawer owns
// the frame, the scrim, Escape handling and the save/cancel row.

import { el, spacer, closeButton, dismissible } from "../core/dom.mjs";
import { t } from "../core/i18n.mjs";
import { audit } from "../core/audit.mjs";

const open_ = new Set();

/**
 * drawer.open({title, body, onSave}) -> handle
 *   title  — string
 *   body   — HTMLElement placed in the scrollable area
 *   onSave — optional async () => void|false; false keeps the drawer open
 * handle: {el, close()}
 */
function open(opts) {
  const o = opts || {};
  const scrim = el("div", { class: "scrim" });
  const panel = el("aside", { class: "drawer", role: "dialog", "aria-modal": "false", "aria-label": o.title || "" });

  const handle = { el: panel, close: close };

  function close() {
    if (!open_.has(handle)) return;
    open_.delete(handle);
    dispose();
    if (scrim.parentNode) scrim.parentNode.removeChild(scrim);
    if (panel.parentNode) panel.parentNode.removeChild(panel);
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
