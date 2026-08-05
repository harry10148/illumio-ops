// progress.mjs — XC-07's mechanism. One docked card, bottom right, collapsible.
//
//   const p = progress.start(label, steps);   // steps: string[] or a count
//   p.step(n);                                // n is 1-based; marks 1..n done
//   p.done();                                 // or p.fail(message)
//
// Long report generation is the reason this exists: the user must be able to
// collapse it and keep working while the job runs.

import { el, clear, spacer } from "../core/dom.mjs";
import { t } from "../core/i18n.mjs";

function labelsOf(steps) {
  if (Array.isArray(steps)) return steps.slice();
  const out = [];
  const n = Number(steps) || 0;
  for (let i = 1; i <= n; i++) out.push(String(i));
  return out;
}

export const progress = {
  /** start(label, steps) -> {el, step(n), done(), fail(msg), collapse(on)} */
  start(label, steps) {
    const names = labelsOf(steps);
    const card = el("div", { class: "progress", "data-tone": "info", "data-collapsed": "false", role: "status" });
    const count = el("span", { class: "count" });
    const bar = el("div", { class: "progress-bar" });
    const olist = el("ol");

    const toggle = el("button", { class: "iconbtn", type: "button", title: t("v2_progress_collapse"), text: "–" });
    toggle.addEventListener("click", function () {
      const now = card.dataset.collapsed === "true";
      card.dataset.collapsed = now ? "false" : "true";
      toggle.textContent = now ? "–" : "+";
      toggle.title = now ? t("v2_progress_collapse") : t("v2_progress_expand");
    });

    card.appendChild(el("div", { class: "progress-h" }, el("b", { text: label }), count, spacer(), toggle));
    card.appendChild(bar);
    card.appendChild(olist);
    document.body.appendChild(card);

    let at = 0;

    function paint() {
      clear(bar);
      clear(olist);
      names.forEach(function (name, i) {
        bar.appendChild(el("i", { class: i < at ? "on" : null }));
        const state = i < at ? "done" : (i === at ? "active" : "todo");
        olist.appendChild(el("li", { "data-state": state },
          el("span", { class: "mk", text: i < at ? "✓" : (i === at ? "›" : "·") }),
          el("span", { text: name })
        ));
      });
      count.textContent = Math.min(at, names.length) + "/" + names.length;
    }

    function remove() {
      if (card.parentNode) card.parentNode.removeChild(card);
    }

    paint();

    const handle = {};
    handle.el = card;
    handle.step = function (n) {
      at = Math.max(0, Math.min(Number(n) || 0, names.length));
      paint();
    };
    handle.done = function (hold) {
      at = names.length;
      card.dataset.tone = "ok";
      paint();
      window.setTimeout(remove, hold === undefined ? 1600 : hold);
    };
    handle.fail = function (message) {
      card.dataset.tone = "crit";
      paint();
      if (message) {
        olist.appendChild(el("li", { "data-state": "active" },
          el("span", { class: "mk", text: "×" }), el("span", { text: message })));
      }
    };
    handle.collapse = function (on) {
      card.dataset.collapsed = on ? "true" : "false";
      toggle.textContent = on ? "+" : "–";
    };
    handle.close = remove;
    return handle;
  },
};
