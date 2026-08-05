// verifypane.mjs — the "this is a check, not a screen" marker.
//
// Several areas end a drawer or a settings page with a pane that prints the
// request body / stored fields the form would send. Those panes exist so a
// reviewer can line up "what the screen collects" against "what the backend
// receives" without a backend to run — they are a verification device for this
// mockup, and Phase 2 will NOT build them into the product.
//
// Nothing in the pane says so, which is exactly how a sample turns into a
// requirement. verifyPane() wraps the pane in a labelled block so every one of
// them carries the same disclaimer, in one place, in both languages.
//
// It does NOT go on panes that render real product data (the event viewer's raw
// JSON, the DLQ entry payload, the module log line, the rule-highlight JSON):
// those are transcriptions of screens the product already has, or endpoints the
// design deliberately wires up, and they do ship.

import { el } from "../core/dom.mjs";
import { t } from "../core/i18n.mjs";

/** verifyPane(pane) -> HTMLElement — the pane, badged. */
export function verifyPane(pane) {
  return el("div", { class: "vpane" },
    el("span", { class: "vpane-tag", text: t("v2_verify_pane") }),
    pane);
}
