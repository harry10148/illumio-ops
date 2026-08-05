// errorcard.mjs — XC-10. The only way the mockup reports a failed store.load().
// Errors state what failed and what to do about it; the stack lives behind a
// disclosure so the card stays readable.

import { el, spacer } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";

/**
 * errorCard({id, error, onRetry}) -> HTMLElement
 *   id      — snapshot id that failed (shown in the message)
 *   error   — Error; .detail (store.mjs) or .stack becomes the technical detail
 *   onRetry — async () => void; the button disables itself while it runs
 */
export function errorCard(opts) {
  const o = opts || {};
  const detail = String((o.error && (o.error.detail || o.error.stack)) || (o.error && o.error.message) || o.error || "");

  const retry = el("button", { class: "btn primary", type: "button", text: t("v2_err_retry") });
  retry.addEventListener("click", async function () {
    if (!o.onRetry) return;
    retry.disabled = true;
    try { await o.onRetry(); } finally { retry.disabled = false; }
  });

  return el("section", { class: "errcard", "data-cov": "XC-10", "data-tone": "crit" },
    el("h2", { text: t("v2_err_title") }),
    el("p", { text: tf("v2_err_body", { id: o.id || "?" }) }),
    el("div", { class: "row" }, o.onRetry ? retry : null, spacer()),
    el("details", null,
      el("summary", { text: t("v2_err_detail") }),
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
