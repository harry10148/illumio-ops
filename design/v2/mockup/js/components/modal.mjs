// modal.mjs — destructive-action confirmation. A confirm dialog here always
// states its blast radius: `impact` is a list of concrete consequences, not prose.

import { el, spacer, closeButton, dismissible } from "../core/dom.mjs";
import { t } from "../core/i18n.mjs";
import { audit } from "../core/audit.mjs";

const open_ = new Set();

/**
 * modal.confirm({title, impact, onOk}) -> handle
 *   title  — string
 *   impact — string[]: one line per consequence ("18 台 workload 進入隔離")
 *   onOk   — async () => void|false; false keeps the modal open
 * handle: {el, close()}
 */
function confirm(opts) {
  const o = opts || {};
  const wrap = el("div", { class: "modal-wrap scrim" });
  const box = el("div", { class: "modal", "data-tone": "crit", role: "dialog", "aria-modal": "true" });
  const handle = { el: box, close: close };

  function close() {
    if (!open_.has(handle)) return;
    open_.delete(handle);
    dispose();
    if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
  }

  const ok = el("button", { class: "btn danger", type: "button", text: t("gui_confirm") });
  ok.addEventListener("click", async function () {
    ok.disabled = true;
    try {
      const r = await o.onOk();
      if (r !== false) close();
    } finally { ok.disabled = false; }
  });

  const impact = o.impact || [];
  box.appendChild(el("header", { class: "modal-h" },
    el("h2", { text: o.title || "" }),
    spacer(),
    closeButton(t("gui_close"), close)
  ));
  box.appendChild(el("div", { class: "modal-b" },
    el("ul", { class: "impact" }, impact.map(function (line) { return el("li", { text: line }); }))
  ));
  box.appendChild(el("footer", { class: "modal-f" },
    spacer(),
    el("button", { class: "btn ghost", type: "button", text: t("gui_cancel"), onClick: close }),
    ok
  ));

  wrap.appendChild(box);
  document.body.appendChild(wrap);
  wrap.addEventListener("mousedown", function (e) { if (e.target === wrap) close(); });
  const dispose = dismissible(box, close);
  open_.add(handle);
  return handle;
}

export const modal = {
  confirm: confirm,
  closeAll() { Array.from(open_).forEach(function (h) { h.close(); }); },
  /** registerAudit(id, factory) — idempotent opener for window.__openAllForAudit(). */
  registerAudit(id, factory) {
    let live = null;
    audit.register(id, function () {
      if (live && open_.has(live)) return;
      live = factory();
    });
  },
};
