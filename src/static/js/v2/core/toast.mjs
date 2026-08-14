// toast.mjs — transient confirmations. One host, newest at the bottom.
// Tone comes from the shared vocabulary so a toast reads like every other mark.

import { el } from "./dom.mjs";

let host = null;

function ensureHost() {
  if (!host || !host.isConnected) {
    host = el("div", { class: "toast-host", role: "status", "aria-live": "polite" });
    document.body.appendChild(host);
  }
  return host;
}

/** show(message, tone?, ms?) -> dismiss(). tone: ok|warn|crit|info|neutral */
export function show(message, tn, ms) {
  const node = el("div", { class: "toast", "data-tone": tn || "info" },
    el("span", { class: "dot" }),
    el("span", { text: message })
  );
  ensureHost().appendChild(node);
  const timer = window.setTimeout(dismiss, ms || 4000);
  function dismiss() {
    window.clearTimeout(timer);
    if (node.parentNode) node.parentNode.removeChild(node);
  }
  return dismiss;
}

export const toast = {
  show,
  ok(m, ms) { return show(m, "ok", ms); },
  warn(m, ms) { return show(m, "warn", ms); },
  crit(m, ms) { return show(m, "crit", ms); },
  info(m, ms) { return show(m, "info", ms); },
};
