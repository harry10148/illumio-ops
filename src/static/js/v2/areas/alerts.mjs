// alerts.mjs — #/investigate/alerts: the list, and one alert's page.
//
// Spec: docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md
// §3. This module replaces 3B's investigate hub, which was a five-step
// workflow — inbox, alert detail, alert-scoped traffic page, per-row rule
// panel, action row — spread across investigate.mjs. The user ruled that
// workflow out: there is no inbox and no investigation flow, only "see the
// recent alerts, click one, read that one".
//
// So the alert page is a NARRATIVE with a fixed order, not a panel wall:
//
//   what happened     one paragraph assembled from the rule, the main flow
//                     direction and the coverage conclusion, plus three
//                     figures taken straight from the payload and the
//                     verdicts. It is a template, not free prose — every
//                     piece is a value the record actually carries.
//   who was talking   the flows, with "which rule covers this" filled in per
//                     row as the PCE answers (AT-04 below).
//   what to do        two or three concrete actions, the first recommended.
//   more              dispatch record and raw data, collapsed.
//
// Two things about the rule column that are contracts, not decoration:
//
//   1. The explains run in PARALLEL and land per row. One flow the PCE will
//      not answer for must not empty the table or hold up the other seven,
//      so every request is settled independently and a failure writes "the
//      PCE did not answer" into ITS row. Nothing is swallowed: the reason
//      still reaches the console.
//   2. Only the first N flows are asked about. Asking about all of them
//      would be N requests against a PCE for a page the operator opened to
//      read, so the table says how many it asked about and offers the whole
//      set in traffic search.

import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { t, tf } from "../core/i18n.mjs";
import { el, clear } from "../core/dom.mjs";
import { num, stamp } from "../core/fmt.mjs";
import { toast } from "../core/toast.mjs";
import { drawer } from "../components/drawer.mjs";
import { palette } from "../components/palette.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { audit } from "../core/audit.mjs";
import { pageHead, section, sideCard, listRow, listFoot, chip, crumbsFor } from "../components/page.mjs";

const ROUTE = "#/investigate/alerts";
const R_TRAFFIC = "#/investigate/traffic";
const R_RULESETS = "#/policy/rulesets";
const R_ALERT_RULES = "#/policy/alert-rules";
const R_WORKLOADS = "#/investigate/workloads";

// spec §3: the page asks the PCE about the first N flows on load.
const EXPLAIN_N = 8;
// spec §3 right column: "similar alerts" counts the last week's alerts that
// came from the same rule.
const SIMILAR_DAYS = 7;

const STATUSES = ["new", "ack", "done"];
// Static keys, so scripts/audit_i18n_usage.py can see them — a key built by
// concatenation is invisible to it.
const STATUS_KEY = {
  new: "gui_alert_status_new",
  ack: "gui_alert_status_ack",
  done: "gui_alert_status_done",
};
const TYPE_KEY = {
  event: "gui_hub_type_event",
  traffic: "gui_hub_type_traffic",
  bandwidth: "gui_hub_type_bandwidth",
  system: "gui_hub_type_system",
};
const SEVERITY_TONE = { critical: "crit", error: "crit", warning: "warn", warn: "warn", info: "info" };

function sevTone(sev) { return SEVERITY_TONE[String(sev || "").toLowerCase()] || "info"; }
function statusTone(status) { return status === "done" ? "ok" : status === "ack" ? "info" : "warn"; }
function statusText(status) { return t(STATUS_KEY[status] || "gui_alert_status_new"); }
function typeText(type) { const k = TYPE_KEY[String(type || "")]; return k ? t(k) : String(type || "—"); }

function errText(r) {
  if (r && r.error) return String(r.error);
  if (r && r.message) return String(r.message);
  return t("gui_err_generic");
}

function hhmm(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

/** The day, under the clock time — NOT fmt.since(), which needs a reference
 *  instant and returns an em-dash without one. */
function day(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

/** The summary without the rule name it usually opens with — the row already
 *  carries the rule name as its title, and printing it twice one line apart
 *  reads as a rendering bug. */
function summaryTail(a) {
  const summary = String(a.summary || "");
  const rule = String(a.rule_name || "");
  if (rule && summary.indexOf(rule) === 0) {
    return summary.slice(rule.length).replace(/^\s*[·|,-]\s*/, "");
  }
  return summary;
}

// ── flows ───────────────────────────────────────────────────────────────────
//
// A payload flow is a row of the same shape GET /api/quarantine/search
// returns (src/analyzer.py puts `top_matches` straight into `raw_data`), so
// the fields read here are the ones design/v2/snapshots/traffic_search.json
// captured from a real PCE.

function endpointOf(side, fallback) {
  const s = side || fallback || {};
  const wl = s.workload || {};
  return {
    name: s.name || wl.name || wl.hostname || s.ip || "—",
    ip: s.ip || "",
    href: s.href || wl.href || null,
  };
}

function flowOf(raw) {
  const svc = raw.service || {};
  return {
    src: endpointOf(raw.source, raw.src),
    dst: endpointOf(raw.destination, raw.dst),
    port: svc.port,
    proto: svc.proto || "TCP",
    connections: Number(raw.num_connections || 0),
    decision: String(raw.policy_decision || ""),
  };
}

/**
 * Ask the PCE which rules cover each flow, in parallel, and hand each answer
 * back through `onVerdict(index, verdict)` as it lands.
 *
 * A verdict is {kind, ruleset, ruleset_href, rule_href}, where kind is:
 *   "allow"       at least one rule allows it
 *   "none"        the PCE answered, and nothing covers it
 *   "unresolved"  the PCE could not resolve one of the endpoints
 *   "error"       the PCE did not answer at all
 */
function explainFlows(flows, onVerdict) {
  return Promise.allSettled(flows.map(function (f) {
    return api.post("/api/policy/explain", {
      src: { href: f.src.href || null, ip: f.src.ip || null },
      dst: { href: f.dst.href || null, ip: f.dst.ip || null },
      port: f.port, proto: f.proto, basis: "active",
    });
  })).then(function (settled) {
    settled.forEach(function (outcome, i) {
      onVerdict(i, verdictOf(outcome));
    });
  });
}

function verdictOf(outcome) {
  if (outcome.status !== "fulfilled") {
    // Not swallowed — the row says the PCE did not answer, and the reason
    // stays on the console for whoever has to find out why.
    console.error("[alerts] policy explain failed", outcome.reason);
    return { kind: "error" };
  }
  const res = outcome.value;
  if (!res || res.ok !== true) {
    console.error("[alerts] policy explain refused", res);
    return { kind: "error" };
  }
  const allow = res.allow || [];
  if (allow.length) {
    const hit = allow[0];
    return {
      kind: "allow",
      ruleset: hit.ruleset_name || "",
      ruleset_href: hit.ruleset_href || "",
      rule_href: hit.rule_href || "",
    };
  }
  if (res.source === "none") return { kind: "unresolved" };
  return { kind: "none" };
}

const VERDICT = {
  allow: { key: "gui_al_verdict_allow", tone: "ok" },
  none: { key: "gui_al_verdict_none", tone: "crit" },
  unresolved: { key: "gui_al_verdict_unresolved", tone: "neutral" },
  error: { key: "gui_al_verdict_error", tone: "neutral" },
};

function verdictCell(verdict) {
  const spec = VERDICT[verdict.kind] || VERDICT.error;
  const cell = el("td", { class: "verdict" }, chip(t(spec.key), spec.tone));
  if (verdict.ruleset) cell.appendChild(el("small", { title: verdict.ruleset, text: verdict.ruleset }));
  return cell;
}

// ── the narrative ───────────────────────────────────────────────────────────

/**
 * How many connections this alert is actually about.
 *
 * NOT the sum over the flows on screen. `payload.raw_data` is the analyzer's
 * `top_matches[:TOP_MATCHES_LIMIT]` — a sample — while `payload.count` is the
 * figure the rule fired on (src/analyzer.py accumulates `res["max_val"] +=
 * m_conn` across EVERY matching flow, and writes it as `count`). An alert that
 * matched forty flows would otherwise announce the total of the ten it kept.
 * The sum is the fallback for a record with no count.
 */
function connectionsOf(a, flows) {
  const count = Number((a.payload || {}).count);
  if (isFinite(count) && count > 0) return count;
  return flows.reduce(function (n, f) { return n + f.connections; }, 0);
}

/** spec §3: "{scope} {what}" — the alert's own numbers, never "Alert #42". */
function headline(a, flows) {
  if (!flows.length) {
    return tf("gui_al_head_plain", { rule: a.rule_name || "—" });
  }
  return tf("gui_al_head_flows", {
    scope: scopeOf(flows), n: num(connectionsOf(a, flows)), rule: a.rule_name || "—",
  });
}

/** The app label the flows share, or the busiest destination's name. */
function scopeOf(flows) {
  const counts = {};
  flows.forEach(function (f) {
    const name = f.dst.name || "";
    if (!name) return;
    counts[name] = (counts[name] || 0) + f.connections;
  });
  const names = Object.keys(counts).sort(function (x, y) { return counts[y] - counts[x]; });
  return names[0] || "—";
}

/** One paragraph, assembled from values the record carries. */
function narrative(a, flows, asked, verdicts) {
  const answered = verdicts.filter(function (v) { return v && v.kind !== "error"; });
  const covered = answered.filter(function (v) { return v.kind === "allow"; }).length;
  const pieces = [tf("gui_al_story_rule", {
    rule: a.rule_name || "—",
    when: stamp(a.fired_at || ""),
    criteria: a.criteria || t("gui_al_story_no_criteria"),
  })];
  if (flows.length) {
    pieces.push(tf("gui_al_story_flows", {
      pairs: num(flows.length),
      top: flows[0].src.name + " → " + flows[0].dst.name,
    }));
    pieces.push(answered.length
      ? tf("gui_al_story_covered", { covered: num(covered), asked: num(answered.length) })
      : t("gui_al_story_no_answer"));
  }
  return pieces.join(" ");
}

function figures(a, flows, verdicts) {
  const connections = connectionsOf(a, flows);
  const covered = verdicts.filter(function (v) { return v && v.kind === "allow"; }).length;
  const box = el("div", { class: "figs" });
  [
    [num(connections), t("gui_al_fig_connections"), true],
    [num(flows.length), t("gui_al_fig_pairs"), false],
    [num(covered), t("gui_al_fig_covered"), false],
  ].forEach(function (row) {
    box.appendChild(el("div", null,
      el("b", { class: row[2] ? "hot" : null, text: row[0] }),
      el("span", { text: row[1] })));
  });
  return box;
}

// ── the pages ───────────────────────────────────────────────────────────────

function installTeardown(state) {
  const unsubscribe = router.onChange(function (path) {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    drawer.closeAll();
    palette.setRoute(path);
  });
}

function segStatus(current, onPick) {
  const box = el("div", { class: "seg", "data-cov": "AT-02", role: "group", "aria-label": t("gui_hub_status") });
  STATUSES.forEach(function (st) {
    box.appendChild(el("button", {
      type: "button", "data-status": st, text: statusText(st),
      "aria-pressed": current === st ? "true" : "false",
      onClick: function () { onPick(st); },
    }));
  });
  return box;
}

function mountList(root, ctx, state) {
  const board = el("div", { class: "board" });
  root.appendChild(board);

  function params() {
    return { status: state.status, type: state.type, page: state.page + 1, page_size: 25 };
  }

  function filters(counts) {
    const box = el("div", { class: "toolbar" });
    const seg = el("div", { class: "seg" });
    [["", "gui_pd_all"], ["new", "gui_alert_status_new"], ["ack", "gui_alert_status_ack"], ["done", "gui_alert_status_done"]]
      .forEach(function (pair) {
        seg.appendChild(el("button", {
          type: "button", text: t(pair[1]),
          "aria-pressed": state.status === pair[0] ? "true" : "false",
          onClick: function () { state.status = pair[0]; state.page = 0; paint(); },
        }));
      });
    box.appendChild(seg);
    box.appendChild(el("span", { class: "count", text: tf("gui_al_counts", {
      open: num(counts.new || 0), done: num(counts.done || 0),
    }) }));
    return box;
  }

  async function paint() {
    if (state.torn) return;
    clear(board);
    await withErrorCard(board, "alerts", function () { return api.load("alerts", params()); }, function (d) {
      if (state.torn || ctx.stale()) return;
      const items = d.items || [];
      const wrap = el("section", { "data-cov": "AT-01" });
      wrap.appendChild(filters(d.counts || {}));
      if (!items.length) {
        wrap.appendChild(el("div", { class: "empty" },
          el("span", { class: "et", text: t("gui_al_list_empty_title") }),
          el("p", { text: t("gui_al_list_empty_body") })));
        board.appendChild(wrap);
        return;
      }
      const list = el("div", { class: "list" });
      items.forEach(function (a) {
        list.appendChild(listRow({
          href: ROUTE + "?id=" + encodeURIComponent(a.id),
          tone: sevTone(a.severity),
          when: { main: hhmm(a.fired_at), sub: day(a.fired_at) },
          title: a.rule_name || "—",
          sub: summaryTail(a),
          who: [[t("gui_type"), el("span", { text: typeText(a.type) })]],
          status: chip(statusText(a.status), statusTone(a.status)),
        }));
      });
      wrap.appendChild(list);
      wrap.appendChild(listFoot(
        tf("gui_al_list_foot", { shown: num(items.length), total: num(d.total || items.length) }),
        el("a", { href: R_ALERT_RULES, text: t("gui_al_manage_rules") })
      ));
      board.appendChild(wrap);
    });
  }

  return paint();
}

function mountAlert(root, ctx, state, id, head) {
  const board = el("div", { class: "board" });
  root.appendChild(board);

  async function setStatus(alert, next) {
    const res = await api.patch("/api/alerts/" + encodeURIComponent(alert.id), { status: next });
    if (state.torn) return;
    if (!res || res.ok !== true) { toast.crit(errText(res)); return; }
    // api.load caches per (id, params). Dropping exactly this alert's entry is
    // what stops the next visit rendering the status it had before the write.
    api.invalidate("alert_detail", { id: id });
    toast.ok(t("gui_hub_status_saved"));
    alert.status = next;
    repaint(alert);
  }

  /** The head is the alert's own sentence, so it is rewritten with the page. */
  function paintHead(alert, flows) {
    const h2 = head.querySelector("h2");
    if (h2) h2.textContent = headline(alert, flows);
    const text = head.querySelector(".phead-text");
    const old = text.querySelector("p");
    const sub = el("p", { text: tf("gui_al_page_sub", {
      rule: alert.rule_name || "—",
      when: stamp(alert.fired_at || ""),
      criteria: alert.criteria || t("gui_al_story_no_criteria"),
    }) });
    if (old) text.replaceChild(sub, old); else text.appendChild(sub);
    // Into .phead-main, not .phead: the head is a column, so appending here
    // would stack the control under the subtitle instead of putting it on the
    // title's right where §5.1 says the action row lives.
    const row = head.querySelector(".phead-main");
    const oldActions = row.querySelector(".actions");
    const actions = el("div", { class: "actions" }, segStatus(alert.status, function (next) {
      setStatus(alert, next);
    }));
    if (oldActions) row.replaceChild(actions, oldActions); else row.appendChild(actions);
  }

  function repaint(alert) {
    if (state.torn || ctx.stale()) return;
    const raw = ((alert.payload || {}).raw_data) || [];
    paintHead(alert, raw.map(flowOf));
    clear(board);
    board.appendChild(alertPage(alert, setStatus, state, ctx));
  }

  return withErrorCard(board, "alert " + id, function () {
    return api.load("alert_detail", { id: id });
  }, function (d) {
    if (state.torn || ctx.stale()) return;
    repaint((d && d.alert) || {});
  });
}

function alertPage(a, onStatus, state, ctx) {
  const raw = ((a.payload || {}).raw_data) || [];
  const flows = raw.map(flowOf);
  const asked = flows.slice(0, EXPLAIN_N);
  // Verdicts live on the state, not on this call: repaint() rebuilds the whole
  // page after a status write, and a fresh array would re-ask the PCE about
  // every flow on each click — eight rule_search calls per button press.
  if (!state.verdicts || state.verdicts.length !== asked.length) {
    state.verdicts = asked.map(function () { return null; });
  }
  const verdicts = state.verdicts;
  const alreadyAsked = verdicts.some(function (v) { return v !== null; });

  const wrap = el("div", { class: "detail", "data-cov": "AT-03" });
  const story = el("div", { class: "story" });
  const side = el("aside", { class: "side" });
  wrap.appendChild(story);
  wrap.appendChild(side);

  // ── what happened ─────────────────────────────────────────────────────
  const lede = el("div", { class: "lede" });
  const ledeText = el("p", { text: narrative(a, flows, asked, verdicts) });
  lede.appendChild(ledeText);
  const figsHost = { node: figures(a, flows, verdicts) };
  lede.appendChild(figsHost.node);
  story.appendChild(section(t("gui_al_sect_what"), null, lede));

  // ── who was talking ───────────────────────────────────────────────────
  let table = null;
  if (asked.length) {
    table = el("div", { class: "flows", "data-cov": "AT-04" });
    const tbody = el("tbody");
    asked.forEach(function (f, i) {
      const tr = el("tr", null,
        el("td", { class: "ep" }, el("b", { text: f.src.name }), f.src.ip ? el("span", { class: "mono", text: f.src.ip }) : null),
        el("td", { class: "arrow", "aria-hidden": "true", text: "→" }),
        el("td", { class: "ep" }, el("b", { text: f.dst.name }), f.dst.ip ? el("span", { class: "mono", text: f.dst.ip }) : null),
        el("td", { class: "svc mono", text: (f.port || "—") + "/" + f.proto }),
        el("td", { class: "n", text: num(f.connections) }),
        el("td", { class: "verdict" }, el("span", { class: "note", text: t("gui_al_verdict_asking") })));
      tbody.appendChild(tr);
      f._cell = tr.lastChild;
      f._row = tr;
    });
    table.appendChild(el("table", null,
      el("thead", null, el("tr", null,
        el("th", { text: t("gui_al_col_source") }),
        el("th", { "aria-hidden": "true" }),
        el("th", { text: t("gui_al_col_destination") }),
        el("th", { text: t("gui_al_col_service") }),
        el("th", { class: "n", text: t("gui_al_col_connections") }),
        el("th", { text: t("gui_al_col_verdict") }))),
      tbody));
    table.appendChild(el("div", { class: "flows-foot" },
      el("span", { text: tf("gui_al_flows_foot", { shown: num(asked.length), total: num(flows.length) }) }),
      el("a", { href: R_TRAFFIC + "?alert=" + encodeURIComponent(a.id), text: t("gui_al_open_in_traffic") })));
    story.appendChild(section(t("gui_al_sect_who"), null, table));
  } else if ((a.payload || {}).parsed_data) {
    story.appendChild(section(t("gui_al_sect_who"), null, eventFacts(a)));
  }

  // ── what to do ────────────────────────────────────────────────────────
  const todo = el("div", { class: "todo", "data-cov": "AT-05" });
  story.appendChild(section(t("gui_al_sect_todo"), null, todo));
  paintActions(todo, a, asked, verdicts, onStatus);

  // ── more ──────────────────────────────────────────────────────────────
  story.appendChild(moreBlock(a));

  // ── right column ──────────────────────────────────────────────────────
  side.appendChild(sideCard(t("gui_al_side_progress"), progressList(a)));
  side.appendChild(sideCard(t("gui_al_side_scope"), scopeList(a, flows)));
  const similar = el("div", { class: "kv-list" }, el("span", { class: "note", text: t("gui_al_side_similar_loading") }));
  side.appendChild(sideCard(t("gui_al_side_similar"), similar));
  loadSimilar(similar, a, state);

  // Verdicts land per row (header note 1). The lede and the figures are
  // rebuilt from the same array, so the paragraph's "N of M covered" and the
  // third figure move with the table instead of freezing at load time.
  if (asked.length && alreadyAsked) {
    asked.forEach(function (f, i) {
      if (!verdicts[i] || !f._cell || !f._row) return;
      const cell = verdictCell(verdicts[i]);
      f._row.replaceChild(cell, f._cell);
      f._cell = cell;
    });
    ledeText.textContent = narrative(a, flows, asked, verdicts);
    const fresh = figures(a, flows, verdicts);
    lede.replaceChild(fresh, figsHost.node);
    figsHost.node = fresh;
    paintActions(todo, a, asked, verdicts, onStatus);
  } else if (asked.length) {
    explainFlows(asked, function (i, verdict) {
      if (state.torn || ctx.stale()) return;
      verdicts[i] = verdict;
      const f = asked[i];
      if (f._cell && f._row) {
        const cell = verdictCell(verdict);
        f._row.replaceChild(cell, f._cell);
        f._cell = cell;
      }
      ledeText.textContent = narrative(a, flows, asked, verdicts);
      const fresh = figures(a, flows, verdicts);
      lede.replaceChild(fresh, figsHost.node);
      figsHost.node = fresh;
      paintActions(todo, a, asked, verdicts, onStatus);
    });
  }
  return wrap;
}

function eventFacts(a) {
  const rows = ((a.payload || {}).parsed_data) || [];
  const box = el("div", { class: "kv-list" });
  rows.slice(0, 5).forEach(function (r) {
    box.appendChild(el("div", { class: "kv" },
      el("span", { text: t("gui_al_ev_actor") }), el("b", { text: r.actor || r.actor_user || "—" })));
    box.appendChild(el("div", { class: "kv" },
      el("span", { text: t("gui_al_ev_action") }), el("b", { text: r.action || r.event_type || "—" })));
    box.appendChild(el("div", { class: "kv" },
      el("span", { text: t("gui_al_ev_resource") }), el("b", { text: r.resource_name || r.target_name || "—" })));
  });
  return box;
}

/**
 * spec §3: two or three concrete actions, the first one recommended, each
 * naming its object. An action only appears when the record can actually
 * carry it out — isolate needs a workload href, "change the policy" needs a
 * ruleset the PCE named.
 */
function paintActions(host, a, flows, verdicts, onStatus) {
  clear(host);
  const acts = [];
  const hit = verdicts.filter(function (v) { return v && v.kind === "allow" && v.ruleset_href; })[0];
  if (hit) {
    acts.push({
      title: tf("gui_al_act_policy", { name: hit.ruleset }),
      verb: t("gui_al_act_open"),
      sub: t("gui_al_act_policy_sub"),
      run: function () {
        router.go(R_RULESETS, { rs: String(hit.ruleset_href).split("/").pop(), rule: hit.rule_href || "" });
      },
    });
  } else if (flows.length) {
    acts.push({
      title: t("gui_al_act_new_ruleset"),
      verb: t("gui_al_act_open"),
      sub: t("gui_al_act_new_ruleset_sub"),
      run: function () { router.go(R_RULESETS); },
    });
  }
  const target = flows.filter(function (f) { return f.dst.href; })[0];
  if (target) {
    acts.push({
      title: tf("gui_al_act_isolate", { name: target.dst.name }),
      verb: t("gui_al_act_find"),
      sub: t("gui_al_act_isolate_sub"),
      run: function () { router.go(R_WORKLOADS, { q: target.dst.name }); },
    });
  }
  acts.push({
    title: a.status === "done" ? t("gui_al_act_reopen") : t("gui_al_act_done"),
    verb: a.status === "done" ? t("gui_al_act_reopen_verb") : t("gui_al_act_done_verb"),
    sub: a.status === "done" ? t("gui_al_act_reopen_sub") : t("gui_al_act_done_sub"),
    run: function () { onStatus(a, a.status === "done" ? "new" : "done"); },
  });

  acts.forEach(function (act, i) {
    host.appendChild(el("div", { class: "act" + (i ? "" : " lead") },
      el("div", null, el("b", { text: act.title }), el("span", { text: act.sub })),
      el("button", {
        class: i ? "btn" : "btn primary", type: "button",
        text: act.verb, "aria-label": act.title, onClick: act.run,
      })));
  });
}

function moreBlock(a) {
  const body = el("div", { class: "body" });
  body.appendChild(el("h4", { class: "eyebrow", text: t("gui_hub_dispatch") }));
  const list = el("div", { class: "kv-list" });
  (a.dispatch || []).forEach(function (d) {
    list.appendChild(el("div", { class: "kv" },
      el("span", { text: d.channel || "—" }),
      chip(d.status || "—", d.status === "success" ? "ok" : d.status === "failed" ? "crit" : "neutral")));
  });
  if (!(a.dispatch || []).length) list.appendChild(el("p", { class: "note", text: t("gui_al_no_dispatch") }));
  body.appendChild(list);
  body.appendChild(el("div", { class: "kv" },
    el("span", { text: t("gui_hub_criteria") }), el("b", { text: a.criteria || "—" })));
  return el("details", { class: "more" },
    el("summary", { text: t("gui_al_more") }),
    body);
}

function progressList(a) {
  const ul = el("ul", { class: "timeline" });
  const sent = (a.dispatch || []).filter(function (d) { return d.status === "success"; }).length;
  [
    [t("gui_al_step_fired"), stamp(a.fired_at || ""), true],
    [t("gui_al_step_sent"), tf("gui_al_step_sent_n", { n: num(sent) }), sent > 0],
    [statusText(a.status),
     a.status_at ? stamp(a.status_at) : t("gui_al_step_open"),
     a.status !== "new"],
  ].forEach(function (row) {
    ul.appendChild(el("li", { class: row[2] ? "on" : null },
      el("i", { "aria-hidden": "true" }),
      el("div", null, el("b", { text: row[0] }), el("small", { text: row[1] }))));
  });
  return ul;
}

function scopeList(a, flows) {
  const names = {};
  flows.forEach(function (f) { if (f.dst.name) names[f.dst.name] = true; });
  const box = el("div", { class: "kv-list" });
  [
    [t("gui_type"), typeText(a.type)],
    [t("gui_hub_severity"), String(a.severity || "—")],
    [t("gui_al_scope_targets"), String(Object.keys(names).length || "—")],
  ].forEach(function (row) {
    box.appendChild(el("div", { class: "kv" }, el("span", { text: row[0] }), el("b", { text: row[1] })));
  });
  return box;
}

/**
 * "How often has this rule fired lately" — counted in the browser from the
 * alert list this backend already serves (spec §4: no new endpoint).
 */
function loadSimilar(host, a, state) {
  const sinceIso = new Date(Date.now() - SIMILAR_DAYS * 86400000).toISOString();
  api.load("alerts", { type: a.type || "", page: 1, page_size: 200, since: sinceIso })
    .then(function (d) {
      if (state.torn) return;
      const same = (d.items || []).filter(function (x) { return String(x.rule_id) === String(a.rule_id); });
      const done = same.filter(function (x) { return x.status === "done"; }).length;
      clear(host);
      host.appendChild(el("p", { text: tf("gui_al_side_similar_n", {
        n: num(same.length), days: num(SIMILAR_DAYS), done: num(done),
      }) }));
    })
    .catch(function (e) {
      if (state.torn) return;
      console.error("[alerts] similar-alert count failed", e);
      clear(host);
      host.appendChild(el("p", { class: "note", text: t("gui_al_side_similar_unknown") }));
    });
}

// ── mount ───────────────────────────────────────────────────────────────────

export async function mountAlerts(root, ctx) {
  const state = {
    torn: false,
    status: ctx.query.get("status") || "",
    type: ctx.query.get("type") || "",
    page: 0,
  };
  installTeardown(state);
  const id = ctx.query.get("id");
  audit.register("al-more", function () {
    const d = root.querySelector("details.more");
    if (d) d.open = true;
  });
  palette.registerFor(ROUTE, {
    id: "al:rules", label: t("gui_al_manage_rules"), group: t("gui_cmd_group_area"),
    run: function () { router.go(R_ALERT_RULES); },
  });

  // The head is appended before the first await: `.phead h2` is what says a
  // page exists while its data is still loading (components/page.mjs note 2).
  // On an alert page it starts as a placeholder and is rewritten with the
  // record — the title is the alert's own sentence, which cannot be known
  // before the load, and rendering the head late would leave the route with
  // no page at all for the duration.
  const head = pageHead({
    route: ROUTE,
    crumbs: id ? crumbsFor(ROUTE).concat([["#" + id, null]]) : crumbsFor(ROUTE),
    title: id ? t("gui_al_page_loading") : t("gui_nav_alerts"),
    sub: id ? null : t("gui_al_list_sub"),
  });
  root.appendChild(head);

  if (!id) return mountList(root, ctx, state);
  return mountAlert(root, ctx, state, id, head);
}
