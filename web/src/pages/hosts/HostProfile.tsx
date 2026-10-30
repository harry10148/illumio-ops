// Host profile (spec §6.5.3, P6b): what the store holds about one host, and its traffic and events as workbench
// requests (the same numbers as the workbench; lightweight mode reads them from the PCE the same way).
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type {
  Coverage, DimensionTop, EndpointFilter, EventRow, FlowCondition1, FlowRow, HostProfile as Profile, HostRansomware, HostTamper,
  PullInfo, QuarantineAction, QuarantineOutcome, SegmentDimension,
} from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { SEVERITY_KEYS, word } from "../alerts/common";
import type { Req } from "../workbench/conditions";
import { DETAIL_KEYS, LEVEL_KEYS, Outcome, QuarantineDialog, STATUS_KEYS, nonEmpty } from "../quarantine/QuarantineDialog";
import { Pulled } from "../workbench/Workbench";

// Literal maps: i18n keys are never built from data.
const MODE_KEYS: Record<string, string> = {
  full: "hosts_mode_full", selective: "hosts_mode_selective", visibility_only: "hosts_mode_visibility_only",
  idle: "hosts_mode_idle",
};
const PATTERN_KEYS: Record<string, string> = {
  regular_cycle: "tamper_pattern_regular_cycle", burst: "tamper_pattern_burst", sporadic: "tamper_pattern_sporadic",
  too_few: "tamper_pattern_too_few",
};
const ACTION_KEYS: Record<string, string> = {
  add_rule: "tamper_action_add_rule", delete_rule: "tamper_action_delete_rule", add_chain: "tamper_action_add_chain",
  delete_chain: "tamper_action_delete_chain", add_table: "tamper_action_add_table", delete_table: "tamper_action_delete_table",
};
const CLASS_KEYS: Record<string, string> = {
  priority: "rpt_rw_sec_priority", safe_to_block: "rpt_rw_sec_safe", suspicious: "rpt_rw_sec_suspicious",
  protected: "hosts_rw_protected", unknown: "hosts_rw_unknown",
};
const DETAILS_KEYS: Record<string, string> = {
  stale: "hosts_rw_details_stale", missing: "hosts_rw_details_missing", not_rated: "hosts_rw_details_not_rated",
};
const ALLOW_KEYS: Record<string, string> = { error: "rpt_rw_allow_error", partial: "rpt_rw_allow_partial" };
const PERIODS: [string, number][] = [["wb_period_1h", 1], ["wb_period_1d", 24], ["wb_period_7d", 168]];
const READINGS_SHOWN = 50;
const HISTORY_SHOWN = 10;

function period(hours: number): { start: string; end: string } {
  const end = new Date();
  return { start: new Date(end.getTime() - hours * 3600_000).toISOString(), end: end.toISOString() };
}

function investigate(req: Req): string {
  return `/investigate?${new URLSearchParams({ q: JSON.stringify(req) }).toString()}`;
}

/** What the numbers below do not include (a gap in the collection, a PCE answer cut at its limit): never silent. */
function Caveats({ coverage, limitHit }: { coverage: Coverage; limitHit?: boolean }) {
  return (
    <>
      {coverage.gaps.length > 0 && <p className="notice" data-role="caveat">{t("wb_gaps", { n: String(coverage.gaps.length) })}</p>}
      {coverage.truncated && <p className="notice" data-role="caveat">{t("wb_truncated")}</p>}
      {limitHit && <p className="hint" data-role="caveat">{t("wb_limit_hit")}</p>}
    </>
  );
}

function shownKey(key: string, display: string | null | undefined): string {
  return display ?? (key.startsWith("ip:") ? key.slice(3) : key || "—");
}

/** One single-level ranking about this host: the workbench's dimension top for the same conditions. */
function HostTop({ title, req, dimension, hostLinks, onPulled }: {
  title: string; req: Req; dimension: SegmentDimension; hostLinks: boolean; onPulled: (p: PullInfo) => void;
}) {
  const [top, setTop] = useState<DimensionTop | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const body = useMemo(() => JSON.stringify(req), [req]);

  useEffect(() => {
    let live = true;
    setTop(null);
    setError(null);
    void call("workbench.dimension", { request: JSON.parse(body) as Req, dimension, label_key: null }).then((env) => {
      if (!live) return;
      if (env.ok && env.data) {
        setTop(env.data);
        if (env.data.pulled) onPulled(env.data.pulled);
      } else setError(env.error);
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body, dimension]);

  return (
    <div className="card stack" data-section={dimension}>
      <div className="row">
        <h3>{title}</h3>
        <Link to={investigate({ ...JSON.parse(body) as Req, view: "ranking", group_by: [{ dimension }] } as Req)}>
          {t("hosts_open_workbench")}
        </Link>
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {!top && !error && <p className="muted">{t("loading")}</p>}
      {top && <Caveats coverage={top.coverage} />}
      {top && top.rows.length === 0 && <p className="muted">{t("wb_dim_none")}</p>}
      {top && top.rows.length > 0 && (
        <table className="table">
          <tbody>
            {top.rows.map((r) => {
              const key = String(r.keys[0] ?? "");
              const label = shownKey(key, r.display[0]);
              return (
                <tr key={key}>
                  <td>{hostLinks && key ? <Link to={`/hosts?${new URLSearchParams({ key }).toString()}`}>{label}</Link> : label}</td>
                  <td className="wb-num">{r.value.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {top?.limit_hit && <p className="hint">{t("wb_dim_top", { n: String(top.rows.length) })}</p>}
    </div>
  );
}

function Events({ href, span, onPulled }: { href: string; span: { start: string; end: string }; onPulled: (p: PullInfo) => void }) {
  const lang = useLang();
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [caveat, setCaveat] = useState<{ coverage: Coverage; limitHit: boolean } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const req = useMemo<Req>(() => ({ mode: "events", view: "detail", host_hrefs: [href], limit: 50, ...span }), [href, span]);

  useEffect(() => {
    let live = true;
    setRows(null);
    void call("workbench.run", { request: req }).then((env) => {
      if (!live) return;
      if (env.ok && env.data) {
        setRows((env.data.result.detail ?? []) as EventRow[]);
        setCaveat({ coverage: env.data.result.coverage, limitHit: env.data.result.limit_hit });
        if (env.data.pulled) onPulled(env.data.pulled);
      } else setError(env.error);
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req]);

  return (
    <div className="card stack" data-section="events">
      <div className="row"><h3>{t("hosts_events")}</h3><Link to={investigate(req)}>{t("hosts_open_workbench")}</Link></div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {!rows && !error && <p className="muted">{t("loading")}</p>}
      {caveat && <Caveats coverage={caveat.coverage} limitHit={caveat.limitHit} />}
      {rows && rows.length === 0 && <p className="muted">{t("wb_empty")}</p>}
      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>{t("evidence_col_time")}</th><th>{t("evidence_col_event_type")}</th>
              <th>{t("evidence_col_severity")}</th><th>{t("evidence_col_actor")}</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.href}><td className="nowrap">{formatTime(r.timestamp, lang)}</td><td>{r.event_type}</td>
                  <td>{r.severity ?? "—"}</td><td>{r.created_by_name ?? r.created_by_kind ?? "—"}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Tamper({ hostKey, href, tamper, onChange }: {
  hostKey: string; href: string; tamper: HostTamper; onChange: (p: Profile) => void;
}) {
  const lang = useLang();
  const [reason, setReason] = useState("");
  const [process, setProcess] = useState("");
  const [onlyPattern, setOnlyPattern] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const readings = [...tamper.readings].reverse();
  const notes = tamper.annotations.filter((a) => a.host_href === href || a.host_href === null);
  const kind = tamper.pattern.kind;

  const add = async (e: FormEvent) => {
    e.preventDefault();
    const env = await call("hosts.tamper_note_add", { key: hostKey, reason: reason.trim(),
      process: process.trim() || null, pattern: onlyPattern ? kind : null });
    if (env.ok && env.data) {
      setReason("");
      setProcess("");
      setError(null);
      onChange(env.data);
    } else setError(env.error);
  };
  const remove = async (id: number) => {
    const env = await call("hosts.tamper_note_remove", { key: hostKey }, { note_id: String(id) });
    if (env.ok && env.data) onChange(env.data);
    else setError(env.error);
  };

  return (
    <div className="card stack" data-section="tamper">
      <h2>{t("hosts_tamper")}</h2>
      {tamper.readings.length === 0 ? <p className="muted">{t("hosts_tamper_none")}</p> : (
        <>
          <p data-role="tamper-pattern">
            {t("hosts_tamper_pattern", { pattern: word(PATTERN_KEYS, kind), n: String(tamper.pattern.n) })}
            {tamper.pattern.median_minutes !== null && <> {t("hosts_tamper_median", { m: String(Math.round(tamper.pattern.median_minutes)) })}</>}
          </p>
          {tamper.signal_capability !== "supported" && <p className="hint">{t("hosts_tamper_no_signal")}</p>}
          <h3>{t("hosts_tamper_readings")}</h3>
          <div className="table-wrap">
            <table className="table" data-role="tamper-readings">
              <thead><tr><th>{t("evidence_col_time")}</th><th>{t("hosts_tamper_process")}</th><th>{t("hosts_tamper_actions")}</th></tr></thead>
              <tbody>
                {readings.slice(0, READINGS_SHOWN).map((r, i) => (
                  <tr key={i}>
                    <td className="nowrap">{formatTime(r.at, lang)}</td>
                    <td>{r.has_process_info ? `${r.process}${r.pid !== null ? ` (PID ${r.pid})` : ""}` : t("hosts_tamper_no_process")}</td>
                    <td>{r.actions.length ? r.actions.map((a) => word(ACTION_KEYS, a)).join("、")
                      : r.num_events !== null ? t("hosts_tamper_num_events", { n: String(r.num_events) }) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {readings.length > READINGS_SHOWN && <p className="hint">{t("hosts_tamper_shown", { n: String(READINGS_SHOWN), total: String(readings.length) })}</p>}
          {tamper.timeline.length > 0 && (
            <>
              <h3>{t("hosts_tamper_timeline")}</h3>
              <table className="table">
                <tbody>
                  {tamper.timeline.map((e, i) => (
                    <tr key={i}><td className="nowrap">{formatTime(e.at, lang)}</td><td>{e.event_type}</td><td>{e.summary}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <h3>{t("hosts_tamper_guidance")}</h3>
          <ul className="stack" data-role="tamper-guidance">
            {tamper.guidance.map((c) => (
              <li key={c.text}>
                <p className="hint">{t(c.purpose_key)}</p>
                <div className="row">
                  <code className="cmd">{c.text}</code>
                  <button type="button" className="btn-quiet" onClick={() => void navigator.clipboard?.writeText(c.text)}>
                    {t("hosts_copy")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <h3>{t("hosts_tamper_notes")}</h3>
      <p className="hint">{t("hosts_tamper_notes_hint")}</p>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      <ul className="stack" data-role="tamper-notes">
        {notes.map((n) => (
          <li key={n.id} className="row">
            <span>{n.reason}</span>
            {n.pattern && <span className="badge">{word(PATTERN_KEYS, n.pattern)}</span>}
            {n.process && <span className="badge">{n.process}</span>}
            {n.host_href === null && <span className="badge">{t("hosts_tamper_note_all")}</span>}
            <span className="hint">{t("hosts_tamper_explains", { n: String(tamper.explained[String(n.id)] ?? 0) })}</span>
            <button type="button" className="btn-quiet" onClick={() => void remove(n.id)}>{t("wb_remove")}</button>
          </li>
        ))}
      </ul>
      <form className="row" onSubmit={(e) => void add(e)} data-role="tamper-note-form">
        <input name="reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("hosts_tamper_reason")} required />
        <input name="process" value={process} onChange={(e) => setProcess(e.target.value)} placeholder={t("hosts_tamper_process_opt")} />
        <label className="row">
          <input type="checkbox" checked={onlyPattern} onChange={(e) => setOnlyPattern(e.target.checked)} />
          {t("hosts_tamper_only_pattern", { pattern: word(PATTERN_KEYS, kind) })}
        </label>
        <button type="submit" className="btn-quiet">{t("hosts_tamper_note_add")}</button>
      </form>
    </div>
  );
}

function Ransomware({ hostKey, initial }: { hostKey: string; initial: HostRansomware }) {
  const [rw, setRw] = useState<HostRansomware>(initial);
  const [asked, setAsked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const b = rw.breakdown;
  const ask = async () => {
    setBusy(true);
    const env = await call("hosts.ransomware_allows", { key: hostKey });
    setBusy(false);
    if (env.ok && env.data) {
      setRw(env.data);
      setAsked(true);
      setError(null);
    } else setError(env.error);
  };
  const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v)}%`);
  return (
    <div className="card stack" data-section="ransomware">
      <h2>{t("hosts_ransomware")}</h2>
      <p>
        {t("rpt_rw_col_pce_percent")}：{pct(b.pce_percent)}　{t("rpt_rw_col_computed")}：{pct(b.computed_percent)}
      </p>
      {b.contradiction && <p className="notice">{t("hosts_rw_contradiction")}</p>}
      {b.approximate && <p className="hint">{t("rpt_rw_quality_approx")}</p>}
      {b.services.length === 0 ? <p className="muted">{t("hosts_rw_none")}</p> : (
        <div className="table-wrap">
          <table className="table" data-role="rw-services">
            <thead><tr><th>{t("rpt_col_name")}</th><th>{t("rpt_col_service")}</th><th>{t("evidence_col_severity")}</th>
              <th>{t("rpt_rw_col_state")}</th><th>{t("rpt_rw_col_weight")}</th><th>{t("rpt_rw_col_coverage")}</th>
              <th>{t("rpt_rw_col_contribution")}</th><th>{t("hosts_rw_traffic")}</th>{asked && <th>{t("rpt_rw_col_rules")}</th>}</tr></thead>
            <tbody>
              {b.services.map((s) => {
                const k = `${s.port}/${s.proto}`;
                const rules = rw.allow_rules[k];
                const status = rw.allow_status?.[k];
                return (
                  <tr key={k}>
                    <td>{s.name}</td><td className="nowrap">{k}</td>
                    <td>{s.severity ? word(SEVERITY_KEYS, s.severity.toLowerCase()) : "—"}</td>
                    <td>{s.protection_state ?? "—"}{s.port_status ? ` · ${s.port_status}` : ""}</td>
                    <td className="wb-num">{s.weight ?? "—"}</td>
                    <td className="wb-num">{s.coverage === null ? "—" : `${Math.round(s.coverage * 100)}%`}</td>
                    <td className="wb-num">{s.contribution === null ? "—" : s.contribution.toFixed(1)}</td>
                    <td>{word(CLASS_KEYS, s.traffic)}{s.recent_sources ? ` (${s.recent_sources})` : ""}</td>
                    {asked && (
                      <td>
                        {status && ALLOW_KEYS[status] ? t(ALLOW_KEYS[status]) : null}
                        {rules === undefined ? "—" : rules.length === 0 ? (status === "ok" ? t("rpt_rw_allow_none") : null)
                          : rules.map((r) => `${r.ruleset_name}：${r.description || r.href.split("/").pop()}`).join("、")}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="hint">{t("hosts_rw_allow_hint")}</p>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {!asked && b.services.length > 0 && (
        <button type="button" className="btn-quiet" disabled={busy} onClick={() => void ask()} data-role="rw-allows">
          {busy ? t("loading") : t("hosts_rw_allow_button")}
        </button>
      )}
    </div>
  );
}

/** Quarantine (P6d): the level the inventory holds, put one on or take it off, and what was done to this host. */
function QuarantineSection({ hostKey, name, current }: { hostKey: string; name: string; current: string | null }) {
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<QuarantineAction[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [outcome, setOutcome] = useState<QuarantineOutcome | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    void call("quarantine.history", undefined, undefined, { key: hostKey }).then((env) => {
      if (live && env.ok && env.data) setHistory(env.data.actions.slice(0, HISTORY_SHOWN));
    });
    return () => { live = false; };
  }, [hostKey, version]);

  async function remove() {
    setConfirming(false);
    setError(null);
    const env = await call("quarantine.remove", { keys: nonEmpty([hostKey]) });
    if (env.ok && env.data) setOutcome(env.data);
    else setError(env.error);
    setVersion((v) => v + 1);
  }

  return (
    <div className="card stack" data-section="quarantine">
      <h2>{t("q_title")}</h2>
      <p data-role="q-current">{current ? t("q_current", { level: t(LEVEL_KEYS[current] ?? current) }) : t("q_current_none")}</p>
      <p className="hint">{t("q_inventory_lag")}</p>
      <div className="row">
        <button type="button" className="btn-quiet" data-role="q-open" onClick={() => setOpen(true)}>{t("q_open")}</button>
        {!confirming && (
          <button type="button" className="btn-quiet" data-role="q-remove" onClick={() => setConfirming(true)}>{t("q_remove")}</button>
        )}
        {confirming && (
          <button type="button" className="btn-primary" data-role="q-remove-confirm" onClick={() => void remove()}>
            {t("q_remove_confirm", { host: name })}
          </button>
        )}
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {outcome && <Outcome outcome={outcome} />}
      {open && <QuarantineDialog hosts={[{ key: hostKey, name }]} onClose={() => setOpen(false)}
        onDone={() => setVersion((v) => v + 1)} />}
      {history && history.length > 0 && (
        <>
          <h3>{t("q_history")}</h3>
          <ul className="plain-list" data-role="q-history">
            {history.map((a) => (
              <li key={a.id}>
                {formatTime(a.at, lang)} · {a.by} · {a.action === "apply" ? t("q_history_apply", { level: t(LEVEL_KEYS[a.level ?? ""] ?? a.level ?? "") })
                  : t("q_history_remove")} · {word(STATUS_KEYS, a.result)}{a.detail ? ` · ${word(DETAIL_KEYS, a.detail)}` : ""}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function HostProfile() {
  const [params] = useSearchParams();
  const key = params.get("key") ?? "";
  const lang = useLang();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [hours, setHours] = useState(24);
  const [pulled, setPulled] = useState<PullInfo | null>(null);
  const span = useMemo(() => period(hours), [hours]);
  const [seenAs, setSeenAs] = useState<string | null>(null);

  useEffect(() => {
    let live = true;  // a slower answer for the host left behind must not replace this one
    setProfile(null);
    setError(null);
    void call("hosts.profile", undefined, undefined, { key }).then((env) => {
      if (!live) return;
      if (env.ok && env.data) setProfile(env.data);
      else setError(env.error);
    });
    return () => { live = false; };
  }, [key]);

  // No name in the store (lightweight mode keeps no flows): the name or address its own traffic carries.
  useEffect(() => {
    setSeenAs(null);
    if (!profile || profile.name !== profile.key) return;
    let live = true;
    const ask = async (s: "src" | "dst") => {
      const env = await call("workbench.run", { request: { mode: "flows", view: "detail", limit: 1, ...span,
        condition: { [s]: { hrefs: [profile.key] } } } });
      const row = env.ok && env.data ? (env.data.result.detail?.[0] as FlowRow | undefined) : undefined;
      return row ? (s === "dst" ? row.dst_hostname ?? row.dst_ip : row.src_hostname ?? row.src_ip) : null;
    };
    void (async () => {
      const found = (await ask("dst")) ?? (await ask("src"));
      if (live && found) setSeenAs(found);
    })();
    return () => { live = false; };
  }, [profile, span]);

  if (error) return <section className="page"><p className="form-error">{t(error.message_key, error.params)}</p></section>;
  if (!profile) return <section className="page"><p className="muted">{t("loading")}</p></section>;

  const side: EndpointFilter = profile.address ? { ips: [profile.address] } : { hrefs: [profile.key] };
  const flows = (condition: FlowCondition1): Req => ({ mode: "flows", view: "detail", condition, metric: "connections",
    group_by: [], limit: 200, ...span });
  const into = flows({ dst: side });
  const blocked = flows({ dst: side, decisions: ["potentially_blocked"] });
  const id = profile.identity;
  const mode = id?.enforcement_mode ?? null;

  return (
    <section className="page" data-role="host-profile">
      <div className="page-head">
        <h1>{seenAs ?? profile.name}</h1>
        <label>
          {t("wb_period")}
          <select name="period" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {PERIODS.map(([k, h]) => <option key={k} value={h}>{t(k)}</option>)}
          </select>
        </label>
      </div>
      <div className="card stack" data-section="identity">
        {!profile.managed && <p className="notice">{t("hosts_unmanaged")}</p>}
        {profile.managed && !profile.in_inventory && <p className="notice">{t("hosts_not_in_inventory")}</p>}
        {id && (
          <dl className="host-facts">
            <dt>{t("hosts_mode")}</dt><dd data-role="host-mode">{mode ? word(MODE_KEYS, mode) : "—"}</dd>
            <dt>{t("hosts_os")}</dt><dd>{id.os_id ?? "—"}</dd>
            <dt>{t("hosts_ven")}</dt><dd>{[id.ven_version, id.agent_status].filter(Boolean).join(" · ") || "—"}</dd>
            <dt>{t("hosts_heartbeat")}</dt><dd>{id.last_heartbeat_at ? formatTime(id.last_heartbeat_at, lang) : "—"}</dd>
            <dt>{t("hosts_policy_sync")}</dt><dd>{id.policy_sync_state ?? "—"}</dd>
            <dt>{t("hosts_labels")}</dt>
            <dd>{Object.entries(profile.labels).map(([k, v]) => <span key={k} className="badge">{k}={v}</span>)}</dd>
          </dl>
        )}
        {profile.exposure && (
          <p data-role="host-exposure">
            {t("hosts_exposure", { now: String(profile.exposure.reach_now), enforced: String(profile.exposure.reach_enforced) })}
            {profile.exposure.pivot_now && <> {t("hosts_pivot")}</>}
            {profile.exposure.asset && <> {t("hosts_asset_sources", { n: String(profile.exposure.asset.sources_now) })}</>}
            {" "}
            <Link to={`/lateral?${new URLSearchParams({ [profile.exposure.asset ? "asset" : "host"]: profile.key }).toString()}`}
              data-role="open-lateral">{t("lat_on_page")}</Link>
          </p>
        )}
      </div>
      {pulled && <Pulled info={pulled} />}
      <div className="host-grid">
        <HostTop title={t("hosts_who_connects")} req={into} dimension="src_host" hostLinks onPulled={setPulled} />
        <HostTop title={t("hosts_ports")} req={into} dimension="service" hostLinks={false} onPulled={setPulled} />
        <HostTop title={t("hosts_outbound")} req={flows({ src: side })} dimension="dst_host" hostLinks onPulled={setPulled} />
        <HostTop title={t("hosts_mode_switch")} req={blocked} dimension="src_host" hostLinks onPulled={setPulled} />
        <HostTop title={t("hosts_mode_switch_ports")} req={blocked} dimension="service" hostLinks={false} onPulled={setPulled} />
      </div>
      {mode === "full" && <p className="hint">{t("hosts_mode_switch_full")}</p>}
      {profile.managed && profile.in_inventory && (
        <QuarantineSection hostKey={profile.key} name={seenAs ?? profile.name} current={profile.labels["Quarantine"] ?? null} />
      )}
      {profile.managed && <Events href={profile.key} span={span} onPulled={setPulled} />}
      {profile.tamper && <Tamper hostKey={profile.key} href={profile.key} tamper={profile.tamper} onChange={setProfile} />}
      {profile.ransomware_unsupported && <p className="notice">{t("rpt_rw_unsupported")}</p>}
      {profile.ransomware_details && profile.ransomware_details !== "ok" && (
        <p className="notice" data-role="rw-details">{word(DETAILS_KEYS, profile.ransomware_details)}</p>
      )}
      {profile.ransomware && profile.ransomware_details !== "not_rated" && profile.ransomware_details !== "missing" && (
        <Ransomware hostKey={profile.key} initial={profile.ransomware} />
      )}
    </section>
  );
}

registerNav({ section: "main", path: "/hosts", labelKey: "hosts_title", order: 16, component: HostProfile, hidden: true });
