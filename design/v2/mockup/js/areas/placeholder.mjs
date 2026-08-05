// placeholder.mjs — every route this task has not built yet.
// Names the area, the route, and the task that will replace it, so a reviewer
// walking the nav always knows whether they are looking at a gap or a bug.

import { el } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { areaOf } from "../shell.mjs";

export function areaHead(title, route) {
  return el("div", { class: "area-head" },
    el("h1", { text: title }),
    el("code", { text: route })
  );
}

export async function mountPlaceholder(root, ctx) {
  const area = areaOf(ctx.route);
  const name = area ? t(area.key) : ctx.route;
  root.appendChild(areaHead(name, ctx.route));
  root.appendChild(el("section", { class: "wip", "data-tone": "info" },
    el("h2", { text: t("v2_shell_wip_title") }),
    el("p", { text: tf("v2_shell_wip_body", { area: name }) }),
    el("p", null, el("span", { class: "route", text: t("v2_shell_route") + " " + ctx.route }))
  ));
}
