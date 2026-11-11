// VEN fleet (spec §6.5 「VEN 總覽」「VEN enforcement 推進」「心跳加速」, deferred to v6.1 and built now): the managed
// hosts the inventory holds, counted and listed; the chosen ones moved forward to a target mode, or asked to report
// traffic faster, through the write key after a preview; and what was done.
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type {
  EnforcementPreview, EnforcementPreviewRequest, FleetAction, FleetHost, FleetHostList, FleetOutcome, FleetOverview, FleetTarget, LabelPick,
  RateCheck, Tally,
} from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { DataTable, Disclosure, KpiStrip, PageHead, Panel } from "../../components/ui";
import { t, useLang } from "../../i18n";
import { modeWord as plainMode } from "../../terms";
import { registerNav } from "../../shell/nav";
import { word } from "../alerts/common";
import { Pulled } from "../workbench/Workbench";

const MAX = 50;
const MODES = ["idle", "visibility_only", "selective", "full"] as const;
const TARGETS = ["visibility_only", "selective", "full"] as const;
const ONLINE = ["online", "lost_24h", "lost_48h", "long_offline", "unknown"] as const;
// Literal maps: i18n keys are never built from data.
const MODE_KEYS: Record<string, string> = {
  full: "hosts_mode_full", selective: "hosts_mode_selective", visibility_only: "hosts_mode_visibility_only",
  idle: "hosts_mode_idle",
};
const ONLINE_KEYS: Record<string, string> = {
  online: "fleet_online_online", lost_24h: "fleet_online_lost_24h", lost_48h: "fleet_online_lost_48h",
  long_offline: "fleet_online_long_offline", unknown: "fleet_online_unknown",
};
const PROBLEM_KEYS: Record<string, string> = {
  sync_state: "rpt_ven_problem_sync_state", fw_stale: "rpt_ven_problem_fw_stale", behind: "rpt_ven_problem_behind",
  never_applied: "rpt_ven_problem_never_applied", health: "rpt_ven_problem_health",
};
const REASON_KEYS: Record<string, string> = {
  unmanaged: "fleet_reason_unmanaged", not_in_inventory: "fleet_reason_not_in_inventory",
  same_mode: "fleet_reason_same_mode", not_forward: "fleet_reason_not_forward", mode_changed: "fleet_reason_mode_changed",
};
const STATUS_KEYS: Record<string, string> = {
  ok: "fleet_status_ok", failed: "fleet_status_failed", skipped: "fleet_status_skipped",
  unknown: "fleet_status_unknown", refused: "fleet_status_refused", pending: "fleet_status_pending",
};
const DETAIL_KEYS: Record<string, string> = {
  ...REASON_KEYS, pce_changed: "fleet_detail_pce_changed", no_write_key: "fleet_detail_no_write_key",
};
const ACTION_KEYS: Record<string, string> = {
  enforcement: "fleet_action_enforcement", traffic_rate: "fleet_action_traffic_rate",
};

function modeWord(mode: string | null | undefined): string {
  return mode ? word(MODE_KEYS, mode) : t("fleet_not_reported");
}

function hostName(name: string | null, key: string): string {
  return name ?? t("fleet_unnamed", { id: key.split("/").pop()?.slice(-6) ?? key });
}

function nonEmpty<T>(xs: T[]): [T, ...T[]] {
  return xs as [T, ...T[]];
}

function TallyTable({ title, rows, wordOf, role }: {
  title: string; rows: Tally[]; wordOf: (v: string | null) => string; role: string;
}) {
  return (
    <Panel title={title} role={role}>
      <DataTable<Tally>
        rows={rows} rowKey={(r) => r.value ?? "\u0000"} empty={t("fleet_none_hosts")}
        columns={[
          { key: "v", label: "", render: (r) => wordOf(r.value) },
          { key: "n", label: t("fleet_col_hosts"), kind: "num", render: (r) => r.hosts.toLocaleString() },
        ]}
      />
    </Panel>
  );
}

function Outcome({ outcome, lang }: { outcome: FleetOutcome; lang: string }) {
  return (
    <div className="stack" data-role="fleet-outcome">
      {outcome.action === "enforcement" && outcome.results.some((r) => r.status === "ok") && (
        <p className="hint">{t("fleet_enf_heartbeat")}</p>
      )}
      {outcome.until && <p className="hint" data-role="fleet-rate-until">{t("fleet_rate_until", { at: formatTime(outcome.until, lang) })}</p>}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>{t("fleet_col_host")}</th><th>{t("fleet_col_result")}</th><th>{t("fleet_col_before")}</th><th>{t("fleet_col_note")}</th></tr></thead>
          <tbody>
            {outcome.results.map((r) => (
              <tr key={r.key} data-status={r.status}>
                <td>{hostName(r.name, r.key)}</td><td>{word(STATUS_KEYS, r.status)}</td>
                <td>{r.previous ? modeWord(r.previous) : "—"}</td>
                <td className="q-detail">{r.detail ? word(DETAIL_KEYS, r.detail) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TargetsTable({ targets }: { targets: FleetTarget[] }) {
  return (
    <div className="table-wrap">
      <table className="table" data-role="fleet-targets">
        <thead><tr><th>{t("fleet_col_host")}</th><th>{t("fleet_col_now")}</th><th>{t("fleet_col_online")}</th><th>{t("fleet_col_note")}</th></tr></thead>
        <tbody>
          {targets.map((x) => (
            <tr key={x.key} data-ok={x.ok}>
              <td>{hostName(x.name, x.key)}</td>
              <td>{x.current ? modeWord(x.current) : "—"}</td>
              <td>{x.online ? word(ONLINE_KEYS, x.online) : "—"}</td>
              <td>{x.reason ? word(REASON_KEYS, x.reason) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Blocks({ prev }: { prev: EnforcementPreview }) {
  if (prev.basis === "none") return <p className="hint" data-role="fleet-blocks-none">{t("fleet_blocks_none")}</p>;
  if (prev.basis === "deny_rules") return <p className="notice" data-role="fleet-blocks-selective">{t("fleet_blocks_selective")}</p>;
  const names = new Map(prev.targets.map((x) => [x.key, hostName(x.name, x.key)]));
  return (
    <div className="stack" data-role="fleet-blocks">
      <h3>{t("fleet_blocks_title")}</h3>
      <p className="hint">{t("fleet_blocks_rule")}</p>
      {prev.pulled && <Pulled info={prev.pulled} />}
      {prev.gaps > 0 && <p className="notice">{t("wb_gaps", { n: String(prev.gaps) })}</p>}
      {prev.truncated && <p className="notice">{t("fleet_truncated")}</p>}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>{t("fleet_col_host")}</th><th data-kind="num">{t("fleet_col_inbound")}</th>
            <th data-kind="num">{t("fleet_col_would_block")}</th><th>{t("fleet_col_top_sources")}</th></tr></thead>
          <tbody>
            {prev.blocks.map((b) => (
              <tr key={b.key} data-host={b.key}>
                <td>{names.get(b.key) ?? b.key}</td>
                <td data-kind="num">{b.inbound.toLocaleString()}</td>
                <td data-kind="num" data-role="fleet-would-block">{b.would_block === null ? "—" : b.would_block.toLocaleString()}</td>
                <td>{b.top_sources.map((s) => `${s.name}（${s.connections.toLocaleString()}）`).join("、") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EnforcementDialog({ chosen, envKey, onClose, onDone }: {
  chosen: FleetHost[]; envKey: string; onClose: () => void; onDone: () => void;
}) {
  const lang = useLang();
  const [target, setTarget] = useState<string>("full");
  const [by, setBy] = useState<"hosts" | "labels">(chosen.length ? "hosts" : "labels");
  const [picks, setPicks] = useState<LabelPick[]>([{ key: envKey, value: "" }]);
  const [asked, setAsked] = useState<string | null>(chosen.length ? "hosts" : null);
  const [prev, setPrev] = useState<EnforcementPreview | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<FleetOutcome | null>(null);
  const keys = JSON.stringify(chosen.map((h) => h.key));

  useEffect(() => {
    if (asked === null) return;
    let live = true;  // a slower answer for the target left behind must not replace this one
    setPrev(null);
    setError(null);
    setAck(false);
    const query = asked === "hosts"
      ? { target, keys: JSON.parse(keys) as string[] }
      : { target, labels: JSON.parse(asked) as NonNullable<EnforcementPreviewRequest["labels"]> };
    void call("fleet.enforcement_preview", query).then((env) => {
      if (!live) return;
      if (env.ok && env.data) setPrev(env.data);
      else setError(env.error);
    });
    return () => { live = false; };
  }, [asked, keys, target]);

  function find(e: FormEvent) {
    e.preventDefault();
    const usable = picks.filter((p) => p.key.trim() && p.value.trim()).map((p) => ({ key: p.key.trim(), value: p.value.trim() }));
    if (usable.length) setAsked(JSON.stringify(usable));
  }

  async function apply() {
    if (!prev) return;
    setBusy(true);
    setError(null);
    const hosts = prev.targets.filter((x) => x.ok && x.current).map((x) => ({ key: x.key, from_mode: x.current as string }));
    const env = await call("fleet.enforcement_apply", { target: prev.target, hosts: nonEmpty(hosts) });
    setBusy(false);
    if (env.ok && env.data) {
      setOutcome(env.data);
      onDone();
    } else {
      setError(env.error);
    }
  }

  const usable = prev?.targets.filter((x) => x.ok) ?? [];
  const canApply = !!prev && prev.target === target && prev.write_key && usable.length > 0 && ack && !busy && !outcome;
  return (
    <div className="card stack" data-role="fleet-enforce" role="dialog" aria-label={t("fleet_enf_title")}>
      <div className="row">
        <h2>{t("fleet_enf_title")}</h2>
        <button type="button" className="btn-quiet" onClick={onClose}>{t("q_close")}</button>
      </div>
      <p className="hint">{t("fleet_enf_intro")}</p>
      {prev && !prev.write_key && <p className="notice" data-role="fleet-no-write-key">{t("fleet_no_write_key")}</p>}
      <div className="row">
        <label>
          {t("fleet_enf_target")}
          <select name="target" value={target} disabled={!!outcome} onChange={(e) => setTarget(e.target.value)}>
            {TARGETS.map((m) => <option key={m} value={m}>{modeWord(m)}</option>)}
          </select>
        </label>
        <label className="row">
          <input type="radio" name="by" checked={by === "hosts"} disabled={!chosen.length || !!outcome}
                 onChange={() => { setBy("hosts"); setAsked("hosts"); }} />
          {t("fleet_enf_by_hosts", { n: String(chosen.length) })}
        </label>
        <label className="row">
          <input type="radio" name="by" checked={by === "labels"} disabled={!!outcome} onChange={() => setBy("labels")} />
          {t("fleet_enf_by_labels")}
        </label>
      </div>
      {by === "labels" && !outcome && (
        <form className="stack" onSubmit={find} data-role="fleet-labels">
          <p className="hint">{t("fleet_enf_labels_hint", { max: String(MAX) })}</p>
          {picks.map((p, i) => (
            <div className="row" key={i}>
              <input aria-label={t("fleet_enf_label_key")} placeholder={t("fleet_enf_label_key")} value={p.key}
                     onChange={(e) => setPicks(picks.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
              <input aria-label={t("fleet_enf_label_value")} placeholder={t("fleet_enf_label_value")} value={p.value}
                     name={`label-value-${i}`}
                     onChange={(e) => setPicks(picks.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
            </div>
          ))}
          <div className="row">
            <button type="button" className="btn-quiet" disabled={picks.length >= 8}
                    onClick={() => setPicks([...picks, { key: "", value: "" }])}>{t("fleet_enf_add_label")}</button>
            <button type="submit" className="btn-quiet" data-role="fleet-find">{t("fleet_enf_find")}</button>
          </div>
        </form>
      )}
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {asked !== null && !prev && !error && <p className="muted">{t("loading")}</p>}
      {prev && (
        <>
          <TargetsTable targets={prev.targets} />
          {prev.targets.length === 0 && <p className="hint">{t("fleet_enf_no_match")}</p>}
          {usable.length > 0 && <Blocks prev={prev} />}
          {!outcome && usable.length > 0 && (
            <label className="row" data-role="fleet-ack">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              {t("fleet_enf_confirm", { n: String(usable.length), mode: modeWord(prev.target) })}
            </label>
          )}
          {!outcome && (
            <button type="button" className="btn-primary" disabled={!canApply} onClick={() => void apply()} data-role="fleet-apply">
              {busy ? t("fleet_applying") : t("fleet_enf_apply", { n: String(usable.length), mode: modeWord(prev.target) })}
            </button>
          )}
        </>
      )}
      {outcome && <Outcome outcome={outcome} lang={lang} />}
    </div>
  );
}

function RateDialog({ chosen, onClose, onDone }: { chosen: FleetHost[]; onClose: () => void; onDone: () => void }) {
  const lang = useLang();
  const [check, setCheck] = useState<RateCheck | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<FleetOutcome | null>(null);
  const keys = JSON.stringify(chosen.map((h) => h.key));

  useEffect(() => {
    let live = true;
    void call("fleet.rate_check", { keys: nonEmpty(JSON.parse(keys) as string[]) }).then((env) => {
      if (!live) return;
      if (env.ok && env.data) setCheck(env.data);
      else setError(env.error);
    });
    return () => { live = false; };
  }, [keys]);

  async function apply() {
    if (!check) return;
    setBusy(true);
    setError(null);
    const env = await call("fleet.rate_apply", { keys: nonEmpty(check.targets.filter((x) => x.ok).map((x) => x.key)) });
    setBusy(false);
    if (env.ok && env.data) {
      setOutcome(env.data);
      onDone();
    } else {
      setError(env.error);
    }
  }

  const usable = check?.targets.filter((x) => x.ok) ?? [];
  return (
    <div className="card stack" data-role="fleet-rate" role="dialog" aria-label={t("fleet_rate_title")}>
      <div className="row">
        <h2>{t("fleet_rate_title")}</h2>
        <button type="button" className="btn-quiet" onClick={onClose}>{t("q_close")}</button>
      </div>
      {check && <p className="hint">{t("fleet_rate_intro", { minutes: String(check.minutes) })}</p>}
      {check && !check.write_key && <p className="notice" data-role="fleet-no-write-key">{t("fleet_no_write_key")}</p>}
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {!check && !error && <p className="muted">{t("loading")}</p>}
      {check && <TargetsTable targets={check.targets} />}
      {check && usable.some((x) => x.online !== "online") && <p className="hint">{t("fleet_rate_offline")}</p>}
      {check && !outcome && (
        <button type="button" className="btn-primary" data-role="fleet-rate-apply"
                disabled={!check.write_key || usable.length === 0 || busy} onClick={() => void apply()}>
          {busy ? t("fleet_applying") : t("fleet_rate_apply", { n: String(usable.length) })}
        </button>
      )}
      {outcome && <Outcome outcome={outcome} lang={lang} />}
      {outcome?.until && <p className="hint">{t("fleet_rate_again")}</p>}
    </div>
  );
}

function History({ actions, lang }: { actions: FleetAction[]; lang: string }) {
  return (
    <DataTable<FleetAction>
      rows={actions} rowKey={(a) => String(a.id)} empty={t("fleet_history_none")}
      columns={[
        { key: "at", label: t("fleet_col_at"), kind: "time", render: (a) => formatTime(a.at, lang) },
        { key: "by", label: t("fleet_col_by"), render: (a) => a.by },
        { key: "host", label: t("fleet_col_host"), render: (a) => <Link to={`/hosts?key=${encodeURIComponent(a.workload_href)}`}>{hostName(a.hostname, a.workload_href)}</Link> },
        { key: "action", label: t("fleet_col_action"), render: (a) => (
          <span>{word(ACTION_KEYS, a.action)}{a.action === "enforcement" ? `：${a.previous_mode ? modeWord(a.previous_mode) : "—"} → ${modeWord(a.target_mode)}` : ""}</span>) },
        { key: "result", label: t("fleet_col_result"), render: (a) => (
          <span data-result={a.result}>{word(STATUS_KEYS, a.result)}{a.detail ? ` · ${word(DETAIL_KEYS, a.detail)}` : ""}</span>) },
      ]}
    />
  );
}

interface Filter { mode: string; env: string; online: string; q: string }

function Fleet() {
  const lang = useLang();
  const [overview, setOverview] = useState<FleetOverview | null>(null);
  const [list, setList] = useState<FleetHostList | null>(null);
  const [actions, setActions] = useState<FleetAction[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [filter, setFilter] = useState<Filter>({ mode: "", env: "", online: "", q: "" });
  const [chosen, setChosen] = useState<Map<string, FleetHost>>(new Map());
  const [open, setOpen] = useState<"enforce" | "rate" | null>(null);

  const load = useCallback(async () => {
    const [o, h] = await Promise.all([call("fleet.overview"), call("fleet.history")]);
    if (o.ok && o.data) setOverview(o.data);
    else setError(o.error);
    if (h.ok && h.data) setActions(h.data.actions);
    else setError(h.error);
  }, []);

  // Only the newest filter's answer is shown (review 2026-11-06): a slower answer to an earlier filter arriving
  // last showed and chose another filter's hosts.
  const latest = useRef(0);
  const loadList = useCallback(async (f: Filter) => {
    const seq = ++latest.current;
    const query: Record<string, string> = { mode: f.mode, online: f.online, q: f.q.trim() };
    if (f.env === "\u0000") query.no_env = "true";
    else query.env = f.env;
    const env = await call("fleet.hosts", undefined, undefined, query);
    if (seq !== latest.current) return;
    if (env.ok && env.data) setList(env.data);
    else setError(env.error);
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void loadList(filter); }, [filter, loadList]);

  function toggle(h: FleetHost) {
    const next = new Map(chosen);
    if (next.has(h.key)) next.delete(h.key);
    else if (next.size < MAX) next.set(h.key, h);
    setChosen(next);
  }

  function chooseShown() {
    const next = new Map(chosen);
    for (const h of list?.hosts ?? []) if (next.size < MAX) next.set(h.key, h);
    setChosen(next);
  }

  function refresh() {
    void load();
    void loadList(filter);
  }

  const o = overview;
  const lost = o ? (o.online.lost_24h ?? 0) + (o.online.lost_48h ?? 0) + (o.online.long_offline ?? 0) : null;
  const picked = [...chosen.values()];
  const set = (k: keyof Filter) => (v: string) => setFilter({ ...filter, [k]: v });
  return (
    <section className="page" data-role="fleet">
      <PageHead title={t("nav_fleet")} purpose={t("purpose_fleet")} />
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {o && <p className="hint" data-role="fleet-fetched">{o.fetched_at ? t("fleet_inventory_at", { at: formatTime(o.fetched_at, lang) }) : t("fleet_inventory_never")}</p>}
      <KpiStrip items={[
        { key: "total", label: t("fleet_kpi_total"), value: o ? o.total : null },
        { key: "online", label: t("fleet_online_online"), value: o ? o.online.online ?? 0 : null, tone: "ok" },
        { key: "lost", label: t("fleet_kpi_lost"), value: lost, tone: lost ? "high" : "muted" },
        { key: "unknown", label: t("fleet_online_unknown"), value: o ? o.online.unknown ?? 0 : null },
        { key: "sync", label: t("fleet_kpi_sync"), value: o ? o.sync_problems : null, tone: o?.sync_problems ? "high" : "muted" },
      ]} />
      <Disclosure summary={t("fleet_online_title")}><p className="hint">{t("fleet_online_rule")}</p></Disclosure>
      {o && (
        <div className="host-grid" data-role="fleet-tallies">
          <TallyTable title={t("fleet_tally_modes")} role="fleet-modes" rows={o.modes} wordOf={modeWord} />
          <TallyTable title={t("fleet_tally_versions")} role="fleet-versions" rows={o.versions} wordOf={(v) => v ?? t("fleet_not_reported")} />
          <TallyTable title={t("fleet_tally_os")} role="fleet-os" rows={o.systems} wordOf={(v) => v ?? t("fleet_not_reported")} />
          <TallyTable title={t("fleet_tally_online")} role="fleet-online"
                      rows={ONLINE.map((s) => ({ value: s, hosts: o.online[s] ?? 0 }))} wordOf={(v) => word(ONLINE_KEYS, v ?? "")} />
          <TallyTable title={t("fleet_tally_sync")} role="fleet-sync" rows={o.sync_states} wordOf={(v) => v ?? t("fleet_not_reported")} />
        </div>
      )}
      <Panel title={t("fleet_list_title")} role="fleet-list"
             meta={list ? t("fleet_list_count", { n: list.total.toLocaleString() }) : undefined}>
        <div className="row" data-role="fleet-filter">
          <label>{t("hosts_mode")}
            <select name="mode" value={filter.mode} onChange={(e) => set("mode")(e.target.value)}>
              <option value="">{t("fleet_any")}</option>
              {MODES.map((m) => <option key={m} value={m}>{modeWord(m)}</option>)}
              <option value="unknown">{t("fleet_not_reported")}</option>
            </select>
          </label>
          <label>{t("fleet_filter_env", { key: o?.env_key ?? "env" })}
            <select name="env" value={filter.env} onChange={(e) => set("env")(e.target.value)}>
              <option value="">{t("fleet_any")}</option>
              {(o?.environments ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
              <option value={"\u0000"}>{t("fleet_no_env")}</option>
            </select>
          </label>
          <label>{t("fleet_tally_online")}
            <select name="online" value={filter.online} onChange={(e) => set("online")(e.target.value)}>
              <option value="">{t("fleet_any")}</option>
              {ONLINE.map((s) => <option key={s} value={s}>{word(ONLINE_KEYS, s)}</option>)}
            </select>
          </label>
          <label>{t("fleet_filter_q")}
            <input name="q" value={filter.q} onChange={(e) => set("q")(e.target.value)} />
          </label>
        </div>
        {list?.limit_hit && <p className="notice">{t("fleet_list_limit", { shown: String(list.hosts.length), n: list.total.toLocaleString() })}</p>}
        <div className="row" data-role="fleet-actions">
          <span data-role="fleet-chosen">{t("fleet_chosen", { n: String(chosen.size), max: String(MAX) })}</span>
          <button type="button" className="btn-quiet" onClick={chooseShown}>{t("fleet_choose_shown")}</button>
          <button type="button" className="btn-quiet" disabled={!chosen.size} onClick={() => setChosen(new Map())}>{t("fleet_clear")}</button>
          <button type="button" className="btn-primary" data-role="fleet-open-enforce" onClick={() => setOpen("enforce")}>{t("fleet_btn_enforce")}</button>
          <button type="button" className="btn-quiet" data-role="fleet-open-rate" disabled={!chosen.size} onClick={() => setOpen("rate")}>{t("fleet_btn_rate")}</button>
        </div>
        {open === "enforce" && (
          <EnforcementDialog key={JSON.stringify([...chosen.keys()])} chosen={picked} envKey={o?.env_key ?? "env"}
                             onClose={() => setOpen(null)} onDone={refresh} />
        )}
        {open === "rate" && picked.length > 0 && (
          <RateDialog key={JSON.stringify([...chosen.keys()])} chosen={picked} onClose={() => setOpen(null)} onDone={refresh} />
        )}
        <DataTable<FleetHost>
          rows={list?.hosts ?? []} rowKey={(h) => h.key} empty={list ? t("fleet_none") : t("loading")}
          columns={[
            { key: "pick", label: t("fleet_col_pick"), render: (h) => (
              <input type="checkbox" aria-label={hostName(h.name, h.key)} checked={chosen.has(h.key)}
                     disabled={!chosen.has(h.key) && chosen.size >= MAX} onChange={() => toggle(h)} />) },
            { key: "host", label: t("fleet_col_host"), render: (h) => (
              <Link to={`/hosts?key=${encodeURIComponent(h.key)}`}>{hostName(h.name, h.key)}</Link>) },
            { key: "mode", label: t("hosts_mode"), nowrap: true, render: (h) => (h.mode ? plainMode(h.mode) : t("fleet_not_reported")) },
            { key: "online", label: t("fleet_tally_online"), nowrap: true, render: (h) => word(ONLINE_KEYS, h.online) },
            { key: "beat", label: t("fleet_col_heartbeat"), kind: "time", render: (h) => (h.last_heartbeat_at ? formatTime(h.last_heartbeat_at, lang) : "—") },
            { key: "sync", label: t("hosts_policy_sync"), render: (h) => (
              <span>{h.policy_sync_state ?? "—"}{h.problems.length ? ` · ${h.problems.map((p) => word(PROBLEM_KEYS, p)).join("、")}` : ""}</span>) },
            { key: "version", label: t("fleet_tally_versions"), nowrap: true, render: (h) => h.ven_version ?? "—" },
            { key: "os", label: t("fleet_tally_os"), render: (h) => h.os_id ?? "—" },
            { key: "env", label: t("fleet_col_env"), render: (h) => h.env ?? "—" },
            { key: "app", label: t("fleet_col_app"), render: (h) => h.app ?? "—" },
          ]}
        />
      </Panel>
      <Panel title={t("fleet_history_title")} role="fleet-history"><History actions={actions} lang={lang} /></Panel>
    </section>
  );
}

registerNav({ section: "devices", path: "/fleet", labelKey: "nav_fleet", order: 20, component: Fleet });
