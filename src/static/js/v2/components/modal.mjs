// modal.mjs — destructive-action confirmation. A confirm dialog here always
// states its blast radius: `impact` is a list of concrete consequences, not prose.
//
// PORT OF design/v2/mockup/js/components/modal.mjs. Differences from the
// mockup (see drawer.mjs's header for the shared rationale — both dialogs
// follow the same a11y/teardown contract):
//
//   1. aria-modal="true" was already correct here; added a real focus trap
//      (dom.mjs's trapFocus()) and opener-focus restoration on close, same as
//      drawer.mjs.
//   2. Teardown contract: `handle.destroy` aliases `handle.close`, and
//      `handle.onClose(fn)` registers a once-only teardown callback — same
//      shape as drawer.mjs, for symmetry (a component mounted inside a modal
//      body gets torn down the same way).
//   3. Bug fix (Phase 1 review finding): the OK button called
//      `await o.onOk()` unconditionally, which threw a TypeError whenever a
//      caller omitted `onOk` (a plain "acknowledge and dismiss" confirm).
//      Guarded so a missing onOk is treated as "nothing to run, just close".

import { el, spacer, closeButton, dismissible, trapFocus } from "../core/dom.mjs";
import { t } from "../core/i18n.mjs";
import { audit } from "../core/audit.mjs";

const open_ = new Set();

/**
 * modal.confirm({title, impact, onOk, alt}) -> handle
 *   title  — string
 *   impact — string[]: one line per consequence ("18 台 workload 進入隔離")
 *   onOk   — optional async () => void|false; false keeps the modal open
 *   alt    — optional {label, onAlt}: a third choice, rendered as a button
 *            between cancel and OK; onAlt behaves like onOk (async, false
 *            keeps the modal open). Omitted whenever the decision is a plain
 *            two-way confirm — the footer is then unchanged from today.
 * handle: {el, close(), destroy(), onClose(fn)}
 */
function confirm(opts) {
  const o = opts || {};
  const opener = document.activeElement;
  const wrap = el("div", { class: "modal-wrap scrim" });
  const box = el("div", { class: "modal", "data-tone": "crit", role: "dialog", "aria-modal": "true" });

  const closeCallbacks = [];
  const handle = {
    el: box,
    close: close,
    onClose(fn) { if (typeof fn === "function") closeCallbacks.push(fn); },
  };
  handle.destroy = close;

  function close() {
    if (!open_.has(handle)) return;
    open_.delete(handle);
    dispose();
    disposeTrap();
    if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
    if (opener && typeof opener.focus === "function") opener.focus();
    closeCallbacks.forEach(function (fn) {
      try { fn(); } catch (e) { console.error("[modal] onClose callback failed", e); }
    });
  }

  const ok = el("button", { class: "btn danger", type: "button", text: t("gui_confirm") });
  ok.addEventListener("click", async function () {
    ok.disabled = true;
    try {
      const r = o.onOk ? await o.onOk() : undefined;
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
  /* Optional third choice, built before the footer so it can be dropped into
   * the same call. Omitted by every existing caller, and absent from the DOM
   * when omitted — a confirm stays two buttons unless the decision genuinely
   * has a third answer. */
  const alt = o.alt && o.alt.label
    ? el("button", { class: "btn", type: "button", text: o.alt.label })
    : null;
  if (alt) {
    alt.addEventListener("click", async function () {
      alt.disabled = true;
      try {
        const r = o.alt.onAlt ? await o.alt.onAlt() : undefined;
        if (r !== false) close();
      } finally { alt.disabled = false; }
    });
  }

  box.appendChild(el("footer", { class: "modal-f" },
    spacer(),
    el("button", { class: "btn ghost", type: "button", text: t("gui_cancel"), onClick: close }),
    alt,
    ok
  ));

  wrap.appendChild(box);
  document.body.appendChild(wrap);
  wrap.addEventListener("mousedown", function (e) { if (e.target === wrap) close(); });
  const dispose = dismissible(box, close);
  const disposeTrap = trapFocus(box);
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
