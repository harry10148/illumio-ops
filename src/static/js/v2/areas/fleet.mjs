/**
 * #/investigate/fleet — the VEN fleet page (plugger port, subproject 1 of 4).
 *
 * Everything here reads the snapshot the ven_summary job wrote. The page never
 * asks the PCE anything; the one write is the progression drawer's apply,
 * which goes through POST /api/fleet/progress/apply.
 *
 * Two things this page refuses to do, both because the backend cannot honestly
 * support them:
 *
 *   - It never renders 0 for a fleet that has not been analysed. "No snapshot
 *     yet" and "nothing out there" look identical as numbers and mean opposite
 *     things to whoever is on call.
 *   - Apply never says the VENs have the policy. The PCE takes the change and
 *     each VEN applies it on its next heartbeat; until then the PCE shows them
 *     syncing. The drawer says what actually happened: it was sent.
 */
import { el, clear } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { pageHead, section, crumbsFor, chip } from "../components/page.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { table } from "../components/table.mjs";
import { drawer } from "../components/drawer.mjs";
import { toast } from "../core/toast.mjs";

const ROUTE = "#/investigate/fleet";
const R_PCE = "#/system/pce";

const BUCKETS = [
  "idle_compat_pass", "idle_compat_warn", "idle_compat_fail", "idle_compat_unknown",
  "visibility_ready", "visibility_not_ready", "selective", "full",
];
const TO_MODES = ["visibility_only", "selective", "full"];
const SCORE_PARTS = ["online", "enforcement", "version", "heartbeat", "compat"];
const PAGE_SIZE = 100;

function num(v) { return String(Number(v || 0)); }

// Keys are spelled out, never glued together from a prefix and a value. The
// i18n audit reads the source for literal keys, so a key built by
// concatenation at runtime is invisible to it: a bucket whose string went
// missing would ship showing its own identifier and no gate would notice.
// (The audit reads comments too — writing the bad form here, even as an
// example, is itself a finding. It was.)
// These maps are also the only place the backend's bucket and reason
// vocabularies are bound to copy.
const BUCKET_KEYS = {
  idle_compat_pass: "gui_fleet_b_idle_compat_pass",
  idle_compat_warn: "gui_fleet_b_idle_compat_warn",
  idle_compat_fail: "gui_fleet_b_idle_compat_fail",
  idle_compat_unknown: "gui_fleet_b_idle_compat_unknown",
  visibility_ready: "gui_fleet_b_visibility_ready",
  visibility_not_ready: "gui_fleet_b_visibility_not_ready",
  selective: "gui_fleet_b_selective",
  full: "gui_fleet_b_full",
};

const PART_KEYS = {
  online: "gui_fleet_c_online",
  enforcement: "gui_fleet_c_enforcement",
  version: "gui_fleet_c_version",
  heartbeat: "gui_fleet_c_heartbeat",
  compat: "gui_fleet_c_compat",
};

const REASON_KEYS = {
  unknown_href: "gui_fleet_r_unknown_href",
  not_managed: "gui_fleet_r_not_managed",
  already_target: "gui_fleet_r_already_target",
  invalid_transition: "gui_fleet_r_invalid_transition",
  over_cap: "gui_fleet_r_over_cap",
};

function bucketLabel(b) {
  const key = BUCKET_KEYS[b];
  return key ? t(key) : String(b || "");
}

function reasonLabel(r) {
  // A reason the backend grows before this page learns about it still has to
  // say something; printing the raw token beats printing nothing.
  const key = REASON_KEYS[String(r || "")];
  return key ? t(key) : String(r || "");
}

// ── IV-16 · summary cards ───────────────────────────────────────────────────

function scoreCard(fleet) {
  const hs = fleet.health_score || {};
  const body = el("div", { class: "kv-list" });
  if (hs.score === null || hs.score === undefined) {
    body.appendChild(el("p", { class: "note", text: t("gui_fleet_score_unknown") }));
  } else {
    body.appendChild(el("b", { class: "big", text: num(hs.score) }));
  }
  if (hs.partial) {
    const missing = SCORE_PARTS.filter(function (k) {
      const c = (hs.components || {})[k];
      return c && c.present === false;
    }).map(function (k) { return t(PART_KEYS[k]); });
    body.appendChild(chip(t("gui_fleet_partial"), "warn"));
    // Naming which parts are absent is the whole point of the chip. "Partial"
    // on its own tells the reader the number is qualified but not how.
    body.appendChild(el("p", { class: "note",
      text: tf("gui_fleet_partial_missing", { names: missing.join("、") || "—" }) }));
  }
  return section(t("gui_fleet_score"), null, body);
}

function versionsCard(fleet) {
  const v = fleet.versions || {};
  const list = el("div", { class: "kv-list" });
  const target = el("div", { class: "kv" }, el("span", { text: t("gui_fleet_target") }));
  if (v.target) {
    target.appendChild(el("b", { text: String(v.target) }));
  } else {
    target.appendChild(el("span", null,
      el("i", { text: t("gui_fleet_target_unset") }),
      el("a", { href: R_PCE, text: t("gui_fleet_set_target") })));
  }
  list.appendChild(target);
  list.appendChild(el("div", { class: "kv" },
    el("span", { text: t("gui_fleet_on_target") }), el("b", { text: num(v.on_target) })));
  // needs_upgrade is null, not 0, when no target is set — "nobody needs an
  // upgrade" is not something we know without a target to compare against.
  list.appendChild(el("div", { class: "kv" },
    el("span", { text: t("gui_fleet_needs_upgrade") }),
    el("b", { text: v.needs_upgrade === null || v.needs_upgrade === undefined
      ? "—" : num(v.needs_upgrade) })));
  return section(t("gui_fleet_versions"), null, list);
}

function pipelineCard(fleet, onPick) {
  const pipe = fleet.pipeline || {};
  const grid = el("div", { class: "kv-list" });
  BUCKETS.forEach(function (b) {
    const cell = pipe[b] || {};
    grid.appendChild(el("div", { class: "kv" },
      el("a", { href: "#", text: bucketLabel(b),
        onClick: function (e) { e.preventDefault(); onPick(b); } }),
      el("b", { text: num(cell.count) })));
  });
  return section(t("gui_fleet_pipeline"), null, grid);
}

// ── IV-18 · version distribution ────────────────────────────────────────────

function versionTable(fleet) {
  const v = fleet.versions || {};
  const dist = v.distribution || {};
  const rows = (v.ordered || []).map(function (ver) {
    const entry = dist[ver] || {};
    const os = Object.keys(entry.os_breakdown || {}).sort().map(function (k) {
      return k + " " + num(entry.os_breakdown[k]);
    }).join(" · ");
    return { version: ver || "—", count: num(entry.count), os: os || "—" };
  });
  const host = el("div");
  table.render(host, {
    columns: [
      { key: "version", label: t("gui_fleet_col_version") },
      { key: "count", label: t("gui_fleet_col_count"), align: "n" },
      { key: "os", label: t("gui_fleet_col_os") },
    ],
    rows: rows,
  });
  return section(t("gui_fleet_versions"), null, host);
}

// ── IV-19 · label coverage ──────────────────────────────────────────────────

function gapsBlock(fleet) {
  const gaps = fleet.coverage_gaps || {};
  const wrap = el("div");
  [["gui_fleet_by_app", gaps.by_app], ["gui_fleet_by_env", gaps.by_env]].forEach(function (pair) {
    const list = el("div", { class: "kv-list" });
    const data = pair[1] || {};
    Object.keys(data).sort().forEach(function (name) {
      const modes = data[name] || {};
      const detail = Object.keys(modes).sort().map(function (m) {
        return (m || "—") + " " + num(modes[m]);
      }).join(" · ");
      list.appendChild(el("div", { class: "kv" },
        el("span", { text: name }), el("b", { text: detail })));
    });
    if (!Object.keys(data).length) list.appendChild(el("p", { class: "note", text: "—" }));
    wrap.appendChild(el("h4", { class: "eyebrow", text: t(pair[0]) }));
    wrap.appendChild(list);
  });
  wrap.appendChild(el("div", { class: "kv" },
    el("span", { text: t("gui_fleet_unlabeled") }),
    el("b", { text: num((gaps.unlabeled || {}).count) })));
  return section(t("gui_fleet_gaps"), null, wrap);
}

// ── IV-20 · the progression drawer ──────────────────────────────────────────

function progressDrawer(state, onDone) {
  const body = el("div", { class: "body" });
  const modeSel = el("select", { "data-field": "to_mode" },
    TO_MODES.map(function (m) { return el("option", { value: m, text: m }); }));
  body.appendChild(el("div", { class: "field" },
    el("label", { text: t("gui_fleet_to_mode") }), modeSel));
  body.appendChild(el("p", { class: "note",
    text: tf("gui_fleet_cap_note", { n: num(state.cap || 200) }) }));

  const out = el("div", { "data-field": "preview_out" });
  const ticks = new Map();   // href -> checkbox
  let previewed = null;

  function rowFor(r, checked) {
    const box = el("input", { type: "checkbox", "data-field": "pick" });
    box.checked = checked;
    ticks.set(r.href, box);
    return el("div", { class: "kv" }, box,
      el("span", { text: r.hostname || r.href }),
      el("b", { text: (r.from || "—") + " → " + (r.to || "—") }));
  }

  function paintPreview(d) {
    clear(out);
    previewed = d;
    const groups = [
      ["gui_fleet_eligible", d.eligible || [], true],
      ["gui_fleet_deferred", d.deferred || [], false],
    ];
    groups.forEach(function (g) {
      if (!g[1].length) return;
      out.appendChild(el("h4", { class: "eyebrow", text: t(g[0]) }));
      // Offline hosts arrive unticked: the change is legal and the PCE will
      // take it, but it lands whenever that VEN next reports in. Ticking them
      // for the operator would be choosing on their behalf.
      if (g[0] === "gui_fleet_deferred") {
        out.appendChild(el("p", { class: "note", text: t("gui_fleet_deferred_note") }));
      }
      g[1].forEach(function (r) { out.appendChild(rowFor(r, g[2])); });
    });
    if ((d.skipped || []).length) {
      out.appendChild(el("h4", { class: "eyebrow", text: t("gui_fleet_skipped") }));
      (d.skipped || []).forEach(function (r) {
        out.appendChild(el("div", { class: "kv" },
          el("span", { text: r.hostname || r.href }),
          el("i", { text: reasonLabel(r.reason) })));
      });
    }
    applyBtn.textContent = tf("gui_fleet_apply", { n: num(picked().length) });
    applyBtn.disabled = !picked().length;
  }

  function picked() {
    const out_ = [];
    ticks.forEach(function (box, href) { if (box.checked) out_.push(href); });
    return out_;
  }

  const previewBtn = el("button", { class: "btn", type: "button",
    "data-field": "preview", text: t("gui_fleet_preview"), onClick: function () {
      const payload = { to_mode: modeSel.value };
      if (state.picked && state.picked.length) payload.hrefs = state.picked.slice();
      else payload.bucket = state.bucket;
      api.post("/api/fleet/progress/preview", payload).then(function (d) {
        if (!d || d.ok !== true) { toast.crit((d && d.error) || t("gui_fleet_preview_failed")); return; }
        ticks.clear();
        paintPreview(d);
      });
    } });

  const applyBtn = el("button", { class: "btn primary", type: "button",
    "data-field": "apply", text: tf("gui_fleet_apply", { n: "0" }), onClick: function () {
      const hrefs = picked();
      if (!hrefs.length || !previewed) return;
      applyBtn.disabled = true;
      api.post("/api/fleet/progress/apply", { to_mode: modeSel.value, hrefs: hrefs })
        .then(function (d) {
          if (!d || d.ok !== true) {
            toast.crit((d && d.error) || t("gui_fleet_apply_failed"));
            applyBtn.disabled = false;
            return;
          }
          // "Sent", not "applied": the VENs have not seen it yet.
          toast.ok(tf("gui_fleet_applied", { n: num((d.applied || []).length) })
            + " " + t("gui_fleet_pending_heartbeat"));
          onDone();
        });
    } });

  body.appendChild(el("div", { class: "actions" }, previewBtn, applyBtn));
  body.appendChild(out);

  const records = el("div", { "data-field": "records" });
  body.appendChild(el("h4", { class: "eyebrow", text: t("gui_fleet_records") }));
  body.appendChild(records);
  api.load("fleet_records").then(function (d) {
    clear(records);
    const rows = (d && d.records) || [];
    if (!rows.length) {
      records.appendChild(el("p", { class: "note", text: t("gui_fleet_no_records") }));
      return;
    }
    rows.forEach(function (r) {
      records.appendChild(el("div", { class: "kv" },
        el("span", { text: String(r.at || "—") }),
        el("b", { text: (r.to_mode || "—") + " · " + num((r.items || []).length) })));
    });
  });

  return { title: t("gui_fleet_progress_btn"), body: body };
}

// ── mount ───────────────────────────────────────────────────────────────────

export async function mountFleet(root, ctx) {
  const state = { torn: false, bucket: "selective", page: 0, picked: [], cap: 200 };
  const board = el("div", { class: "board" });

  root.appendChild(pageHead({
    // pageHead 不帶 cov：IV-16 指的是摘要卡列，一個 anchor 只能指一個東西。
    route: ROUTE, crumbs: crumbsFor(ROUTE),
    title: t("gui_fleet_title"), sub: t("gui_fleet_subtitle"),
    actions: [el("button", { class: "btn primary", type: "button",
      "data-field": "open_progress", text: t("gui_fleet_progress_btn"),
      onClick: function () { openDrawer(); } })],
  }));
  root.appendChild(board);

  function openDrawer() {
    const handle = drawer.open(progressDrawer(state, function () {
      handle.close();
      paint();
    }));
    return handle;
  }
  drawer.registerAudit("fleet-progress", openDrawer);

  function paintList(host, fleet) {
    clear(host);
    const chips = el("div", { class: "seg" });
    BUCKETS.forEach(function (b) {
      chips.appendChild(el("button", { type: "button", text: bucketLabel(b),
        "aria-pressed": state.bucket === b ? "true" : "false",
        onClick: function () { state.bucket = b; state.page = 0; state.picked = []; paint(); } }));
    });
    host.appendChild(chips);

    if (fleet.index_truncated) {
      // The counts above came from the analysis, not the index, so they stay
      // true; only the per-host list is gone. Saying nothing here would read
      // as an empty bucket.
      host.appendChild(el("p", { class: "note", text: t("gui_fleet_index_truncated") }));
      return;
    }

    const tableHost = el("div");
    host.appendChild(tableHost);
    api.load("fleet_list", { bucket: state.bucket, offset: state.page * PAGE_SIZE,
      limit: PAGE_SIZE }).then(function (d) {
      if (state.torn || ctx.stale()) return;
      const rows = ((d && d.rows) || []).map(function (r) {
        return {
          hostname: r.hostname || "—", mode: r.mode || "—",
          online: r.online ? "✓" : "—", version: r.version || "—",
          compat: r.compat || "—",
          hslh: r.hslh === null || r.hslh === undefined ? "—" : String(Math.round(r.hslh * 10) / 10),
          app: r.app || "—", env: r.env || "—",
        };
      });
      const total = Number((d && d.total) || 0);
      // 分頁交給 table 自己的 foot：這一頁再做一份等於兩個分頁器，而且兩份
      // 的頁數算法遲早分岔。
      table.render(tableHost, {
        columns: [
          { key: "hostname", label: t("gui_fleet_col_hostname") },
          { key: "mode", label: t("gui_fleet_col_mode") },
          { key: "online", label: t("gui_fleet_col_online") },
          { key: "version", label: t("gui_fleet_col_version") },
          { key: "compat", label: t("gui_fleet_col_compat") },
          { key: "hslh", label: t("gui_fleet_col_hslh"), align: "n" },
          { key: "app", label: t("gui_fleet_col_app") },
          { key: "env", label: t("gui_fleet_col_env") },
        ],
        rows: rows,
        page: { index: state.page, size: PAGE_SIZE, total: total },
        onPage: function (next) {
          const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
          state.page = Math.max(0, Math.min(next, pages - 1));
          paint();
        },
      });
    });
  }

  async function paint() {
    if (state.torn) return;
    clear(board);
    await withErrorCard(board, "fleet", function () { return api.load("fleet"); },
      function (d) {
        if (state.torn || ctx.stale()) return;
        if (!d || d.available !== true) {
          // Not analysed yet. Deliberately no numbers: a 0 here is a lie.
          const box = el("div", { class: "empty", "data-cov": "IV-16" },
            el("span", { class: "et", text: t("gui_fleet_no_snapshot") }),
            el("p", { text: t("gui_fleet_no_snapshot_body") }));
          if (d && d.next_run_at) {
            box.appendChild(el("p", { class: "note",
              text: tf("gui_fleet_next_run", { at: String(d.next_run_at) }) }));
          }
          board.appendChild(box);
          return;
        }
        const fleet = d.fleet || {};
        if (fleet.last_error) {
          board.appendChild(el("div", { class: "banner", "data-tone": "warn",
            text: tf("gui_fleet_last_error", { error: String(fleet.last_error) }) }));
        }
        const cards = el("div", { class: "cards", "data-cov": "IV-16" });
        cards.appendChild(scoreCard(fleet));
        cards.appendChild(versionsCard(fleet));
        cards.appendChild(pipelineCard(fleet, function (b) {
          state.bucket = b; state.page = 0; state.picked = []; paint();
        }));
        board.appendChild(cards);

        const listHost = el("section", { "data-cov": "IV-17" });
        board.appendChild(listHost);
        paintList(listHost, fleet);

        const vhost = el("section", { "data-cov": "IV-18" });
        vhost.appendChild(versionTable(fleet));
        board.appendChild(vhost);

        const ghost = el("section", { "data-cov": "IV-19" });
        ghost.appendChild(gapsBlock(fleet));
        board.appendChild(ghost);

        const dhost = el("section", { "data-cov": "IV-20", hidden: true });
        board.appendChild(dhost);
      });
  }

  // ctx 只有 route / query / stale()；離場靠 router.onChange，比照 alerts.mjs。
  const unsubscribe = router.onChange(function () {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    drawer.closeAll();
  });
  await paint();
}
