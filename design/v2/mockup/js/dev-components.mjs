// dev-components.mjs — harness for mockup/dev-components.html.
// NOT part of the shell and NOT in the nav: it exists so a reviewer can exercise
// every shared component against real snapshot data before Tasks 8-12 consume them.

import { el } from "./core/dom.mjs";
import { store } from "./core/store.mjs";
import { initI18n, t, tf } from "./core/i18n.mjs";
import { initDisplay, theme, density } from "./core/theme.mjs";
import { installAuditHook, audit } from "./core/audit.mjs";
import { since, num } from "./core/fmt.mjs";
import { toast } from "./core/toast.mjs";
import { drawer } from "./components/drawer.mjs";
import { modal } from "./components/modal.mjs";
import { table, col } from "./components/table.mjs";
import { progress } from "./components/progress.mjs";
import { palette } from "./components/palette.mjs";
import { withErrorCard } from "./components/errorcard.mjs";

const PAGE_SIZE = 8;

function button(label, run) {
  const b = el("button", { class: "btn", type: "button", text: label });
  b.addEventListener("click", run);
  return b;
}

function section(title, meta, body) {
  return el("section", { class: "panel" },
    el("div", { class: "panel-h" }, el("h3", { text: title }), el("span", { class: "meta", text: meta })),
    el("div", { class: "panel-b" }, body)
  );
}

/* ---- table 1: reports list (type / file / size — Task-6 straggler headers) -- */
function reportsTable(host, reports) {
  const columns = [
    col("report_type", t("gui_col_type"), { width: 190 }),
    col("filename", t("gui_col_filename"), { title: function (r) { return r.filename; } }),
    col("size", t("gui_col_size"), { width: 84, align: "n", cell: function (r) { return Math.round(r.size / 1024) + "K"; } }),
  ];
  let index = 0;
  let handle = null;
  function page(i) {
    index = Math.max(0, i);
    const slice = reports.slice(index * PAGE_SIZE, index * PAGE_SIZE + PAGE_SIZE);
    const p = { index: index, size: PAGE_SIZE, total: reports.length };
    if (handle) handle.update(slice, p);
    else handle = table.render(host, { columns: columns, rows: slice, page: p, onPage: page });
  }
  page(0);
}

/* ---- table 2: dispatch history (ch / subject / age) ------------------------ */
function dispatchTable(host, status, asOf) {
  const rows = (status.dispatch_history || []).slice(-12).reverse().map(function (d) {
    const row = {};
    row.channel = d.channel;
    row.subject = d.subject;
    row.age = since(d.timestamp, asOf);
    row._tone = d.status === "success" ? "ok" : "crit";
    return row;
  });
  const columns = [
    col("channel", t("v2_col_channel"), { width: 90 }),
    col("subject", t("v2_col_subject"), { title: function (r) { return r.subject; } }),
    col("age", t("v2_col_age"), { width: 70, align: "n" }),
  ];
  table.render(host, { columns: columns, rows: rows, page: 0 });
}

async function boot() {
  initDisplay();
  installAuditHook();
  await initI18n();
  palette.install();

  const root = document.getElementById("dev-root");

  /* display + overlays */
  const controls = el("div", { class: "dev-row" },
    button(t("gui_theme"), function () { theme.toggle(); }),
    button(t("gui_density"), function () { density.toggle(); }),
    button(t("v2_cmd_open"), function () { palette.open(); }),
    button("toast · ok", function () { toast.ok(t("gui_msg_settings_saved")); }),
    button("toast · crit", function () { toast.crit(t("gui_it_save_failed")); }),
    button("drawer", function () {
      drawer.open({
        title: t("gui_tab_settings"),
        body: el("div", null,
          el("p", { class: "dev-note", text: t("v2_cmd_placeholder") }),
          el("input", { class: "field", type: "text", placeholder: t("gui_search") })
        ),
        onSave: function () { toast.ok(t("gui_msg_settings_saved")); },
      });
    }),
    button("modal", function () {
      modal.confirm({
        title: t("gui_confirm_delete"),
        impact: [t("gui_ov_alert_channels") + " · 2", t("gui_ov_job_health") + " · 14"],
        onOk: function () { toast.warn(tf("gui_deleted_ok", { filename: "demo.html" })); },
      });
    }),
    button("progress", function () {
      const p = progress.start(t("gui_tab_reports"), [t("gui_search"), t("gui_ov_traffic"), t("gui_col_filename")]);
      let n = 0;
      const tick = window.setInterval(function () {
        n += 1;
        p.step(n);
        if (n >= 3) { window.clearInterval(tick); p.done(); }
      }, 700);
    })
  );
  root.appendChild(section("components", "drawer · modal · progress · toast · palette", controls));

  /* tables + error card, all snapshot-driven */
  const t1 = el("div");
  const t2 = el("div");
  const t3 = el("div");
  root.appendChild(section("table · " + t("gui_tab_reports"), "reports_list.json", t1));
  root.appendChild(section("table · " + t("gui_ov_recent_events"), "status.json", t2));
  root.appendChild(section("errorcard · XC-10", "store.load(\"__missing__\")", t3));

  await withErrorCard(t1, "reports_list",
    function () { return store.load("reports_list"); },
    function (data) { reportsTable(t1, (data.reports || []).slice()); });

  await withErrorCard(t2, "status",
    function () { return Promise.all([store.load("status"), store.load("dashboard_overview")]); },
    function (pair) { dispatchTable(t2, pair[0], pair[1].as_of); });

  await withErrorCard(t3, "__missing__",
    function () { return store.load("__missing__"); },
    function () { });

  /* skeleton + empty states, side by side */
  const states = el("div", { class: "dev-grid" });
  const skel = el("div");
  const empty = el("div");
  states.appendChild(skel);
  states.appendChild(empty);
  root.appendChild(section("table states", "rows = null · rows = []", states));
  const stateCols = [col("a", t("gui_col_type"), { width: 120 }), col("b", t("gui_col_filename"), null)];
  table.render(skel, { columns: stateCols, rows: null, page: 0 });
  table.render(empty, { columns: stateCols, rows: [], page: 0 });

  const reportCount = num((await store.load("reports_list")).reports.length);
  const summary = el("div", { class: "dev-row" },
    el("span", { class: "dev-note", text: "reports_list · " + reportCount + " rows" }),
    button("__openAllForAudit()", function () {
      const r = audit.openAll();
      toast.info("opened " + r.opened + " · errors " + r.errors.length);
    })
  );
  root.appendChild(summary);
}

boot();
