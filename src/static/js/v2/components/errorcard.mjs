// errorcard.mjs — XC-10. The only way the mockup reports a failed store.load().
// Errors state what failed and what to do about it; the stack lives behind a
// disclosure so the card stays readable.
//
// PORT OF design/v2/mockup/js/components/errorcard.mjs, verbatim except i18n
// keys renamed v2_err_* -> gui_errcard_* (v2_ never ships in the product
// catalogue; err_ alone collided with the unrelated gui_err_* HTTP-error
// strings already in src/i18n_en.json, hence errcard_ instead of just err_).
//
// No destroy() here, deliberately: errorCard() returns a bare HTMLElement —
// same contract as the mockup — with no subscription, timer or document-level
// listener outside the card's own retry button (which is garbage-collected
// with the card when its host clears/replaces it). There is nothing for a
// destroy() to release, so adding a stub one would violate this task's own
// self-review bar ("a working destroy(), or just a stub?").

import { el, spacer } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";

/**
 * errorCard({id, error, onRetry}) -> HTMLElement
 *   id      — snapshot id that failed (shown in the message)
 *   error   — Error; .detail (store-map.mjs) or .stack becomes the technical detail
 *   onRetry — async () => void; the button disables itself while it runs
 */
export function errorCard(opts) {
  const o = opts || {};
  const detail = String((o.error && (o.error.detail || o.error.stack)) || (o.error && o.error.message) || o.error || "");

  const retry = el("button", { class: "btn primary", type: "button", text: t("gui_errcard_retry") });
  retry.addEventListener("click", async function () {
    if (!o.onRetry) return;
    retry.disabled = true;
    try { await o.onRetry(); } finally { retry.disabled = false; }
  });

  return el("section", { class: "errcard", "data-cov": "XC-10", "data-tone": "crit" },
    el("h2", { text: t("gui_errcard_title") }),
    el("p", { text: tf("gui_errcard_body", { id: o.id || "?" }) }),
    el("div", { class: "row" }, o.onRetry ? retry : null, spacer()),
    el("details", null,
      el("summary", { text: t("gui_errcard_detail") }),
      el("pre", { text: detail })
    )
  );
}

/**
 * withErrorCard(host, id, load, render) — run `load`, render on success, drop an
 * XC-10 card (wired to a real retry) on failure. Returns the loaded value or null.
 */
export async function withErrorCard(host, id, load, render) {
  try {
    const data = await load();
    await render(data);
    return data;
  } catch (e) {
    while (host.firstChild) host.removeChild(host.firstChild);
    host.appendChild(errorCard({
      id: id,
      error: e,
      onRetry: function () { return withErrorCard(host, id, load, render); },
    }));
    return null;
  }
}
