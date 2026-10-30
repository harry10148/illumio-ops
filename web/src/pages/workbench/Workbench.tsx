import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type {
  AggRow, DimensionTop, EventRow, FlowRow, PullInfo, SegmentDimension, SegmentMetric, SegmentResult, WorkbenchMeta,
} from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { type Dim, EVENT_DIMS, FLOW_DIMS, OPEN_BY_DEFAULT, type Req, addValue, chips, chosen, dimId } from "./conditions";

// Literal maps: i18n keys are never built from data.
const DIM_KEYS: Record<string, string> = {
  src_host: "wb_dim_src_host", dst_host: "wb_dim_dst_host", src_label: "wb_dim_src_label", dst_label: "wb_dim_dst_label",
  service: "wb_dim_service", initiator_process: "wb_dim_initiator_process", initiator_user: "wb_dim_initiator_user",
  service_process: "wb_dim_service_process", service_user: "wb_dim_service_user", decision: "wb_dim_decision",
  direction: "wb_dim_direction", event_type: "wb_dim_event_type", event_host: "wb_dim_event_host",
  event_severity: "wb_dim_event_severity", actor: "wb_dim_actor",
};
const METRIC_KEYS: Record<string, string> = {
  flows: "wb_metric_flows", connections: "wb_metric_connections", distinct_dst: "wb_metric_distinct_dst",
  distinct_src: "wb_metric_distinct_src", distinct_ports: "wb_metric_distinct_ports", bytes: "wb_metric_bytes",
  events: "wb_metric_events",
};
const HOST_DIMS = new Set<string>(["src_host", "dst_host", "event_host"]);
const HOST_KEY = /^(\/orgs\/\d+\/workloads\/|ip:)/;  // what the host profile takes (an event's VEN href is not)
const PERIODS: [string, number][] = [["wb_period_1h", 1], ["wb_period_1d", 24], ["wb_period_7d", 168], ["wb_period_30d", 720]];

function lastHours(hours: number): { start: string; end: string } {
  const end = new Date();
  return { start: new Date(end.getTime() - hours * 3600_000).toISOString(), end: end.toISOString() };
}

function emptyFlows(hours: number): Req {
  return { mode: "flows", view: "ranking", condition: {}, metric: "flows", group_by: [{ dimension: "src_host" }],
    limit: 200, ...lastHours(hours) };
}

function decode(q: string | null): Req | null {
  if (!q) return null;
  try {
    return JSON.parse(q) as Req;
  } catch {
    return null;
  }
}

function hostOf(row: FlowRow, side: "src" | "dst"): string {
  return (side === "src" ? row.src_hostname : row.dst_hostname) ?? (side === "src" ? row.src_ip : row.dst_ip);
}

function Coverage({ result, bytes }: { result: SegmentResult; bytes: boolean }) {
  const c = result.coverage;
  const fc = result.field_coverage;
  return (
    <div className="stack" data-role="coverage">
      {c.gaps.length > 0 && <p className="notice">{t("wb_gaps", { n: String(c.gaps.length) })}</p>}
      {c.truncated && <p className="notice">{t("wb_truncated")}</p>}
      {c.source !== "store" && <p className="hint">{t("wb_from_pce")}</p>}
      {result.limit_hit && <p className="hint">{t("wb_limit_hit")}</p>}
      {bytes && fc && fc.total > 0 && fc.bytes < fc.total && (
        <p className="hint">{t("wb_bytes_coverage", { pct: String(Math.round((fc.bytes / fc.total) * 100)) })}</p>
      )}
      {result.latency_seconds !== null && result.latency_seconds > 1800 && (
        <p className="hint">{t("wb_latency", { minutes: String(Math.round(result.latency_seconds / 60)) })}</p>
      )}
    </div>
  );
}

function Pulled({ info }: { info: PullInfo }) {
  const lang = useLang();
  return (
    <div className="stack" data-role="pulled">
      <p className="hint">{t("wb_pulled", { start: formatTime(info.start, lang), end: formatTime(info.end, lang),
        rows: info.rows.toLocaleString(), at: formatTime(info.read_at, lang) })}</p>
      {info.capped && info.unread_from && <p className="notice">{t("wb_pulled_capped", { from: formatTime(info.unread_from, lang) })}</p>}
      {info.truncated_windows > 0 && <p className="notice">{t("wb_pulled_truncated", { n: String(info.truncated_windows) })}</p>}
    </div>
  );
}

function DimensionBox({ req, dim, open, onToggle, onPick, names }: {
  req: Req; dim: Dim; open: boolean; onToggle: () => void; onPick: (d: Dim, row: AggRow) => void;
  names: Record<string, string>;
}) {
  const [top, setTop] = useState<DimensionTop | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const body = useMemo(() => JSON.stringify(req), [req]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setTop(null);
    setError(null);
    void call("workbench.dimension", { request: JSON.parse(body) as Req, dimension: dim.dimension,
      label_key: dim.labelKey ?? null }).then((env) => {
      if (!live) return;
      if (env.ok && env.data) setTop(env.data);
      else setError(env.error);
    });
    return () => { live = false; };
  }, [open, body, dim.dimension, dim.labelKey]);

  const name = t(DIM_KEYS[dim.dimension] ?? dim.dimension);
  const title = dim.labelKey ? `${name}：${dim.labelKey}` : name;
  return (
    <div className="wb-dim" data-dim={dimId(dim)}>
      <button type="button" className="wb-dim-head" aria-expanded={open} onClick={onToggle}>{title}</button>
      {open && (
        <div className="wb-dim-body">
          {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
          {!top && !error && <p className="muted">{t("loading")}</p>}
          {top && top.rows.length === 0 && <p className="muted">{t("wb_dim_none")}</p>}
          {top && top.rows.map((row) => {
            const key = String(row.keys[0] ?? "");
            const label = row.display[0] ?? names[key] ?? (key.startsWith("ip:") ? key.slice(3) : key || "—");
            const pickable = dim.dimension !== "direction" && key !== "";
            const on = pickable && chosen(req, dim, key);
            return (
              <div key={key} className="wb-dim-item">
                <button type="button" className="wb-dim-row" data-chosen={on} disabled={!pickable || on}
                  onClick={() => onPick(dim, row)} title={label}>
                  <span className="wb-dim-label">{label}</span>
                  <span className="wb-dim-value">{row.value.toLocaleString()}</span>
                </button>
                {HOST_DIMS.has(dim.dimension) && HOST_KEY.test(key) && (
                  <Link className="wb-dim-host" to={`/hosts?${new URLSearchParams({ key }).toString()}`}
                    aria-label={t("hosts_title")} title={t("hosts_title")}>↗</Link>
                )}
              </div>
            );
          })}
          {top?.limit_hit && <p className="hint">{t("wb_dim_top", { n: String(top.rows.length) })}</p>}
        </div>
      )}
    </div>
  );
}

function Detail({ result, mode }: { result: SegmentResult; mode: Req["mode"] }) {
  const lang = useLang();
  const rows = result.detail ?? [];
  if (rows.length === 0) return <p className="muted">{t("wb_empty")}</p>;
  if (mode === "events") {
    return (
      <div className="table-wrap">
        <table className="table" data-role="wb-detail">
          <thead><tr><th>{t("evidence_col_time")}</th><th>{t("evidence_col_event_type")}</th><th>{t("evidence_col_status")}</th>
            <th>{t("evidence_col_severity")}</th><th>{t("evidence_col_actor")}</th></tr></thead>
          <tbody>
            {(rows as EventRow[]).map((r) => (
              <tr key={r.href}><td className="nowrap">{formatTime(r.timestamp, lang)}</td><td>{r.event_type}</td>
                <td>{r.status ?? "—"}</td><td>{r.severity ?? "—"}</td><td>{r.created_by_name ?? r.created_by_kind ?? "—"}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="table" data-role="wb-detail">
        <thead><tr><th>{t("evidence_col_last")}</th><th>{t("evidence_col_src")}</th><th>{t("evidence_col_dst")}</th>
          <th>{t("evidence_col_port")}</th><th>{t("evidence_col_decision")}</th><th>{t("evidence_col_connections")}</th>
          <th>{t("wb_col_initiator")}</th><th>{t("wb_col_service_side")}</th></tr></thead>
        <tbody>
          {(rows as FlowRow[]).map((r) => (
            <tr key={r.record_key}>
              <td className="nowrap">{formatTime(r.last_detected, lang)}</td>
              <td>{hostOf(r, "src")}</td><td>{hostOf(r, "dst")}</td>
              <td className="nowrap">{r.port ?? "—"}/{r.proto}</td><td>{r.policy_decision}</td>
              <td>{r.num_connections.toLocaleString()}</td>
              <td>{[r.initiator_process, r.initiator_user].filter(Boolean).join(" · ") || "—"}</td>
              <td>{[r.service_process, r.service_user].filter(Boolean).join(" · ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Ranking({ result, heads }: { result: SegmentResult; heads: string[] }) {
  const levels = heads.length - 1;
  const rows = result.ranking ?? [];
  if (rows.length === 0) return <p className="muted">{t("wb_empty")}</p>;
  const shownKey = (r: AggRow, i: number) => {
    const k = r.keys[i];
    const s = r.display[i] ?? (typeof k === "string" && k.startsWith("ip:") ? k.slice(3) : k);
    return s === null || s === undefined || s === "" ? "—" : String(s);
  };
  return (
    <div className="table-wrap">
      <table className="table" data-role="wb-ranking">
        <thead><tr>{heads.map((h, i) => <th key={i} className={i === heads.length - 1 ? "wb-num" : ""}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const prev = rows[i - 1];
            const first = levels === 1 || !prev || shownKey(prev, 0) !== shownKey(r, 0);
            return (
              <tr key={i}>
                <td className={first ? "" : "muted"}>{first ? shownKey(r, 0) : ""}</td>
                {levels === 2 && <td>{shownKey(r, 1)}</td>}
                <td className="wb-num">{r.value.toLocaleString()}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Workbench() {
  const [params, setParams] = useSearchParams();
  // react-router hands out a new setSearchParams whenever the address changes: kept in a ref so writing the
  // conditions to the address does not run the query a second time (lab acceptance 2026-10-30)
  const setParamsRef = useRef(setParams);
  setParamsRef.current = setParams;
  const [meta, setMeta] = useState<WorkbenchMeta | null>(null);
  const [req, setReq] = useState<Req | null>(null);
  const [alertId, setAlertId] = useState<string | null>(null);
  const [result, setResult] = useState<SegmentResult | null>(null);
  const [pulled, setPulled] = useState<PullInfo | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set(OPEN_BY_DEFAULT));
  const [names, setNames] = useState<Record<string, string>>({});
  const [text, setText] = useState("");
  const lang = useLang();

  // start: the URL's request, else an alert's evidence, else the last day
  useEffect(() => {
    void call("workbench.meta").then((env) => { if (env.ok && env.data) setMeta(env.data); });
    const fromUrl = decode(params.get("q"));
    const alert = params.get("alert");
    if (fromUrl) {
      setReq(fromUrl);
      setAlertId(alert);
    } else if (alert) {
      void call("workbench.from_alert", undefined, { alert_id: alert }).then((env) => {
        if (env.ok && env.data) {
          setReq({ ...env.data.request, view: "detail" });
          setAlertId(alert);
        } else {
          setError(env.error);
          setReq(emptyFlows(24));
        }
      });
    } else setReq(emptyFlows(24));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // only the latest query's answer is shown: a slower earlier one arriving last must not replace it
  const runSeq = useRef(0);
  const run = useCallback(async (r: Req) => {
    const seq = ++runSeq.current;
    setBusy(true);
    const env = await call("workbench.run", { request: r });
    if (seq !== runSeq.current) return;
    setBusy(false);
    if (env.ok && env.data) {
      setResult(env.data.result);
      setPulled(env.data.pulled);
      setError(null);
    } else setError(env.error);
  }, []);

  useEffect(() => {
    if (!req) return;
    const next = new URLSearchParams();
    next.set("q", JSON.stringify(req));
    if (alertId) next.set("alert", alertId);
    setParamsRef.current(next, { replace: true });
    void run(req);
  }, [req, alertId, run]);

  if (!req) return <section className="page"><p className="muted">{t("loading")}</p></section>;

  const update = (patch: Partial<Req>) => setReq({ ...req, ...patch } as Req);
  const pick = (d: Dim, row: AggRow) => {
    const next = addValue(req, d, row);
    const key = String(row.keys[0] ?? "");
    if (row.display[0]) setNames({ ...names, [key]: row.display[0] });
    if (next) setReq(next);
  };
  const dims: Dim[] = req.mode === "events" ? EVENT_DIMS.map((d) => ({ dimension: d }))
    : [...FLOW_DIMS.slice(0, 2).map((d) => ({ dimension: d })),
       ...(meta?.label_keys ?? []).flatMap((k) => [{ dimension: "src_label" as SegmentDimension, labelKey: k },
         { dimension: "dst_label" as SegmentDimension, labelKey: k }]),
       ...FLOW_DIMS.slice(2).map((d) => ({ dimension: d }))];
  const groupDims = req.mode === "events" ? EVENT_DIMS : FLOW_DIMS.filter((d) => d !== "direction");
  const metrics: SegmentMetric[] = req.mode === "events" ? ["events"]
    : ["flows", "connections", "distinct_dst", "distinct_src", "distinct_ports", "bytes"];
  const setGroup = (i: number, value: string) => {
    const g = [...(req.group_by ?? [])];
    if (value === "") g.splice(i);
    else g[i] = { dimension: value as SegmentDimension };
    update({ group_by: (g.length ? g : [{ dimension: groupDims[0] }]) as Req["group_by"] });
  };
  const switchMode = (mode: Req["mode"]) => {
    const { start, end } = req;
    setAlertId(null);
    setReq(mode === "events"
      ? { mode: "events", view: "detail", start, end, limit: 200 }
      : { ...emptyFlows(24), start, end });
  };
  const search = (e: FormEvent) => {
    e.preventDefault();
    if (req.mode === "events") update({ actor: text.trim() || null });
    else update({ condition: { ...(req.condition ?? {}), text: text.trim() || null } });
    setText("");
  };

  return (
    <section className="page wb" data-role="workbench">
      <div className="page-head">
        <h1>{t("nav_workbench")}</h1>
        <div className="row" role="group" aria-label={t("wb_mode")}>
          <button type="button" className={req.mode === "flows" ? "btn-primary" : "btn-quiet"} onClick={() => switchMode("flows")}>
            {t("wb_mode_flows")}
          </button>
          <button type="button" className={req.mode === "events" ? "btn-primary" : "btn-quiet"} onClick={() => switchMode("events")}>
            {t("wb_mode_events")}
          </button>
        </div>
      </div>
      <div className="card stack" data-role="conditions">
        <div className="row">
          <label>
            {t("wb_period")}
            <select name="period" value="" onChange={(e) => update(lastHours(Number(e.target.value)))}>
              <option value="">{`${formatTime(req.start, lang)} – ${formatTime(req.end, lang)}`}</option>
              {PERIODS.map(([k, h]) => <option key={k} value={h}>{t(k)}</option>)}
            </select>
          </label>
          <form className="row" onSubmit={search}>
            <input name="search" value={text} onChange={(e) => setText(e.target.value)}
              placeholder={t(req.mode === "events" ? "wb_search_actor" : "wb_search")} />
            <button type="submit" className="btn-quiet">{t("wb_search_add")}</button>
          </form>
        </div>
        <ul className="chips" data-role="chips">
          {alertId && (
            <li className="chip" data-chip="alert">
              <Link to={`/alerts/${alertId}`}>{t("wb_from_alert", { id: alertId })}</Link>
              <button type="button" className="btn-quiet" aria-label={t("wb_remove")} onClick={() => setAlertId(null)}>✕</button>
            </li>
          )}
          {chips(req, names).map((c) => (
            <li key={c.id} className="chip" data-chip={c.id}>
              <span>{t(c.labelKey)}{c.value && <> = {c.value}</>}</span>
              <button type="button" className="btn-quiet" aria-label={t("wb_remove")} onClick={() => setReq(c.remove(req))}>✕</button>
            </li>
          ))}
        </ul>
        {busy && meta?.mode === "lightweight" && <p className="hint" data-role="pulling">{t("wb_pulling")}</p>}
        {pulled && <Pulled info={pulled} />}
      </div>
      <div className="wb-body">
        <aside className="wb-dims card" data-role="dimensions">
          <p className="hint">{t("wb_dims_hint")}</p>
          {dims.map((d) => (
            <DimensionBox key={`${req.mode}:${dimId(d)}`} req={{ ...req, view: "detail", group_by: [] } as Req} dim={d}
              open={open.has(dimId(d))} names={names} onPick={pick}
              onToggle={() => {
                const s = new Set(open);
                if (s.has(dimId(d))) s.delete(dimId(d));
                else s.add(dimId(d));
                setOpen(s);
              }} />
          ))}
        </aside>
        <div className="wb-main card stack">
          <div className="row">
            <div className="row" role="tablist">
              {(["detail", "ranking"] as const).map((v) => (
                <button key={v} type="button" role="tab" aria-selected={req.view === v}
                  className={req.view === v ? "btn-primary" : "btn-quiet"}
                  onClick={() => update(v === "ranking"
                    ? { view: v, group_by: (req.group_by?.length ? req.group_by : [{ dimension: groupDims[0] }]) as Req["group_by"] }
                    : { view: v, group_by: [] })}>
                  {t(v === "detail" ? "wb_view_detail" : "wb_view_ranking")}
                </button>
              ))}
            </div>
            {req.view === "ranking" && (
              <>
                {[0, 1].map((i) => (
                  <label key={i}>
                    {t(i === 0 ? "wb_group_1" : "wb_group_2")}
                    <select name={`group_${i}`} value={req.group_by?.[i]?.dimension ?? ""} onChange={(e) => setGroup(i, e.target.value)}>
                      {i === 1 && <option value="">{t("wb_group_none")}</option>}
                      {groupDims.map((d) => <option key={d} value={d}>{t(DIM_KEYS[d] ?? d)}</option>)}
                    </select>
                  </label>
                ))}
                {req.mode === "flows" && (
                  <label>
                    {t("wb_metric")}
                    <select name="metric" value={req.metric ?? "flows"} onChange={(e) => update({ metric: e.target.value as SegmentMetric })}>
                      {metrics.map((m) => <option key={m} value={m}>{t(METRIC_KEYS[m] ?? m)}</option>)}
                    </select>
                  </label>
                )}
              </>
            )}
            {busy && <span className="muted">{t("loading")}</span>}
          </div>
          {error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
          {result && (
            <>
              <Coverage result={result} bytes={req.mode === "flows" && req.metric === "bytes"} />
              {result.view === "ranking"
                ? <Ranking result={result} heads={[...(req.group_by ?? []).map((g) => t(DIM_KEYS[g.dimension] ?? g.dimension)),
                    t(METRIC_KEYS[req.mode === "events" ? "events" : (req.metric ?? "flows")] ?? "")]} />
                : <Detail result={result} mode={req.mode} />}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

registerNav({ section: "main", path: "/investigate", labelKey: "nav_workbench", order: 15, component: Workbench });
