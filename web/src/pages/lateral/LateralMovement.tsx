// Lateral movement (spec §6.5.1, P6c): what could happen (exposure: reach now and once enforced, paths into critical
// assets and where to cut them), what is happening (detections), and what a suggested deny rule would block.
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { AssetExposure, Cut, DenyProposal, EndpointFilter, ExposureResult, LateralPage } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { SEVERITY_KEYS, SEVERITY_TONES, word } from "../alerts/common";
import { DETECTOR_KEYS, STATE_KEYS, STATE_TONES } from "../system/Lateral";
import { Pulled } from "../workbench/Workbench";
import { Simulation, type Suggestion } from "./Simulation";

type Port = [number, number];
type GroupEdge = [string | null, string | null, number, string];

const HOSTS_SHOWN = 20;
const GROUPS_SHOWN = 30;
const NAME_MAX = 22;  // a name longer than this is cut with "…" in the path diagram; the full name is its tooltip
const DAY_KEYS: Record<number, string> = { 1: "lat_days_1", 7: "lat_days_7", 30: "lat_days_30" };
const LIMIT_KEYS: Record<string, string> = { assets: "lat_limit_assets", cross_env: "lat_limit_cross_env" };
const EDGE_STATE_KEYS: Record<string, string> = {
  allowed: "lat_state_allowed", potentially_blocked: "lat_state_potentially_blocked", unknown: "lat_state_unknown",
};
const GROUP_KEYS = ["app", "env"] as const;

function endpoint(key: string): EndpointFilter {
  return key.startsWith("ip:") ? { ips: [key.slice(3)] } : { hrefs: [key] };
}

function protoName(p: number): string {
  return p === 6 ? "TCP" : p === 17 ? "UDP" : String(p);
}

export default function LateralMovement() {
  const [params] = useSearchParams();
  const lang = useLang();
  const [page, setPage] = useState<LateralPage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [days, setDays] = useState(7);
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);

  useEffect(() => {
    let live = true;
    void call("lateral.view").then((env) => {
      if (!live) return;
      if (env.ok && env.data) setPage(env.data);
      else setError(env.error);
    });
    return () => { live = false; };
  }, []);

  const section = params.get("section");
  useEffect(() => {
    if (page && section) document.getElementById(`lat-${section}`)?.scrollIntoView({ block: "start" });
  }, [page, section]);

  async function compute() {
    if (!page) return;
    const offered = page.lightweight_days.includes(days) ? days : page.lightweight_days[page.lightweight_days.length - 1] ?? 1;
    setBusy(true);
    setError(null);
    const env = await call("lateral.compute", { days: offered as 1 | 7 | 30 });
    setBusy(false);
    if (env.ok && env.data) setPage(env.data);
    else setError(env.error);
  }

  if (!page) {
    return <section className="page"><h1>{t("lat_title")}</h1>
      {error ? <p className="form-error">{t(error.message_key, error.params)}</p> : <p className="muted">{t("loading")}</p>}
    </section>;
  }

  const name = (key: string): string => page.names[key] ?? (key.startsWith("ip:") ? key.slice(3) : key);
  const portWord = ([port, proto]: Port): string => page.port_names[`${port}/${proto}`] ?? `${port}/${protoName(proto)}`;
  const ex = page.exposure;
  const offered = page.lightweight_days.includes(days) ? days : page.lightweight_days[page.lightweight_days.length - 1];

  function suggestCut(cut: Cut, asset: string) {
    const ports = (cut.ports as Port[]);
    if (cut.kind === "edge" && cut.dst) {
      const proposal: DenyProposal = { src: endpoint(cut.src), dst: endpoint(cut.dst),
        ports: ports.map(([port, proto]) => ({ port, proto })) };
      setSuggestion({ proposal, node: false, words: t("lat_rule_edge", { src: name(cut.src), dst: name(cut.dst),
        ports: ports.map(portWord).join("、") }) });
    } else {
      setSuggestion({ proposal: { src: {}, dst: endpoint(cut.src) }, node: true,
        words: t("lat_rule_node", { host: name(cut.src), asset: name(asset) }) });
    }
  }

  function suggestEdge(src: string, dst: string, ports: Port[]) {
    setSuggestion({ proposal: { src: endpoint(src), dst: endpoint(dst), ports: ports.map(([port, proto]) => ({ port, proto })) },
      node: false, words: t("lat_rule_edge", { src: name(src), dst: name(dst), ports: ports.map(portWord).join("、") }) });
  }

  return (
    <section className="page" data-role="lateral">
      <h1>{t("lat_title")}</h1>
      <div className="card stack" data-section="status">
        {page.state === "not_computed" && (
          <p className="notice">{t("lat_not_computed")} <Link to="/system/jobs">{t("lat_open_jobs")}</Link></p>
        )}
        {page.state === "collection_off" && (
          <p className="notice">{t("lat_collection_off")} <Link to="/system/collection">{t("lat_open_collection")}</Link></p>
        )}
        {(page.state === "lightweight" || page.source === "pulled") && (
          <div className="stack" data-role="lightweight">
            <p className="hint">{t("lat_lightweight_intro")}</p>
            <div className="row">
              <label>
                {t("lat_days")}
                <select name="days" value={offered} onChange={(e) => setDays(Number(e.target.value))}>
                  {page.lightweight_days.map((d) => <option key={d} value={d}>{t(DAY_KEYS[d] ?? "lat_days_7")}</option>)}
                </select>
              </label>
              <button type="button" className="btn-primary" disabled={busy} onClick={() => void compute()} data-role="lat-compute">
                {busy ? t("lat_computing") : t("lat_compute")}
              </button>
            </div>
            {busy && <p className="hint">{t("lat_computing_hint")}</p>}
          </div>
        )}
        {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
        {ex && page.computed_at && (
          <p data-role="lat-computed">{t("lat_computed", { at: formatTime(page.computed_at, lang),
            start: formatTime(ex.observation_from, lang), end: formatTime(ex.observation_to, lang), hops: String(ex.hops) })}</p>
        )}
        {page.stale && <p className="notice" data-role="lat-stale">{t("lat_stale")}</p>}
        {ex && page.last_run_failed && <p className="notice" data-role="lat-run-failed">{t("lat_run_failed")} <Link to="/system/jobs">{t("lat_open_jobs")}</Link></p>}
        {ex && page.collection_stopped && <p className="notice" data-role="lat-collection-stopped">{t("lat_collection_stopped")} <Link to="/system/collection">{t("lat_open_collection")}</Link></p>}
        {page.pull && <Pulled info={page.pull} />}
        {page.source === "pulled" && ex && (
          <p className="hint" data-role="lat-period-note">{t("lat_period_note", {
            days: String(Math.round((Date.parse(ex.observation_to) - Date.parse(ex.observation_from)) / 86_400_000)),
            setting: String(page.observation_days_setting) })}</p>
        )}
        {ex && ex.unknown_edges > 0 && <p className="hint">{t("lat_unknown_edges", { n: String(ex.unknown_edges) })}</p>}
        {ex?.limits_hit.map((l) => (
          <p key={l} className="hint" data-role="lat-limit">
            {l.startsWith("groups:") ? t("lat_limit_groups", { key: l.slice(7) }) : t(LIMIT_KEYS[l] ?? "lat_limit_other")}
          </p>
        ))}
      </div>
      {suggestion && <Simulation suggestion={suggestion} criticalSet={page.critical_set} onClose={() => setSuggestion(null)} />}
      {ex && <Compare ex={ex} critical={page.critical_set} />}
      {ex && (
        <Assets ex={ex} critical={page.critical_set} preselect={params.get("asset")} name={name} onCut={suggestCut} />
      )}
      {ex && <Reach ex={ex} name={name} focus={params.get("host")} />}
      {ex && <Groups ex={ex} />}
      {ex && (
        <div className="card stack" id="lat-cross_env" data-section="cross-env">
          <h2>{t("lat_cross_env")}</h2>
          {ex.cross_env.length === 0 ? <p className="muted">{t("lat_cross_env_none")}</p> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>{t("lat_col_src")}</th><th>{t("lat_col_dst")}</th><th>{t("lat_col_envs")}</th>
                  <th>{t("lat_col_ports")}</th><th>{t("lat_col_state")}</th><th /></tr></thead>
                <tbody>
                  {ex.cross_env.map((x) => (
                    <tr key={`${x.src}>${x.dst}`}>
                      <td>{name(x.src)}</td><td>{name(x.dst)}</td><td className="nowrap">{x.src_env} → {x.dst_env}</td>
                      <td>{(x.ports as Port[]).map(portWord).join("、")}</td><td>{word(EDGE_STATE_KEYS, x.state)}</td>
                      <td><button type="button" className="btn-quiet" data-role="sim-cross"
                        onClick={() => suggestEdge(x.src, x.dst, x.ports as Port[])}>{t("lat_simulate")}</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {ex.cross_env_total > ex.cross_env.length && (
            <p className="hint">{t("lat_cross_env_more", { shown: String(ex.cross_env.length), total: String(ex.cross_env_total) })}</p>
          )}
        </div>
      )}
      {ex && (
        <div className="card stack" id="lat-footholds" data-section="footholds">
          <h2>{t("lat_footholds")}</h2>
          <p className="hint">{t("lat_footholds_hint")}</p>
          {!page.ransomware_unsupported && page.ransomware_unread > 0 && (
            <p className="notice" data-role="rw-unread">{t("lat_rw_unread", { n: String(page.ransomware_unread),
              total: String(page.ransomware_rated) })}</p>
          )}
          {page.ransomware_unsupported ? <p className="notice">{t("rpt_rw_unsupported")}</p>
            : ex.footholds.length === 0 && page.ransomware_rated === 0 ? <p className="muted" data-role="rw-not-rated">{t("lat_rw_not_rated")}</p>
            : ex.footholds.length === 0 ? <p className="muted">{t(page.ransomware_unread > 0 ? "lat_footholds_none_read" : "lat_footholds_none")}</p> : (
              <ul className="plain-list">
                {ex.footholds.map((f) => (
                  <li key={`${f.host}|${f.port}/${f.proto}`}>
                    <Link to={`/hosts?key=${encodeURIComponent(f.host)}`}>{name(f.host)}</Link>　{f.name}（{f.port}/{protoName(f.proto)}）
                    {f.severity && <span className="badge">{word(SEVERITY_KEYS, f.severity.toLowerCase())}</span>}
                  </li>
                ))}
              </ul>
            )}
        </div>
      )}
      <Happening page={page} />
    </section>
  );
}

function Compare({ ex, critical }: { ex: ExposureResult; critical: boolean }) {
  const pivotsNow = ex.hosts.filter((h) => h.pivot_now).length;
  const pivotsEnf = ex.hosts.filter((h) => h.pivot_enforced).length;
  const assetsNow = ex.assets.filter((a) => a.sources_now > 0).length;
  const assetsEnf = ex.assets.filter((a) => a.sources_enforced > 0).length;
  return (
    <div className="lat-compare" data-section="compare">
      <div className="card">
        <h2>{t("lat_now")}</h2>
        <p className="hint">{t("lat_now_hint")}</p>
        <dl className="host-facts">
          <dt>{t("lat_edges")}</dt><dd data-role="edges-now">{ex.edges_now.toLocaleString()}</dd>
          <dt>{t("lat_assets_reachable")}</dt><dd data-role="assets-now">{critical ? assetsNow : t("lat_not_set")}</dd>
          <dt>{t("lat_pivots")}</dt><dd>{pivotsNow}</dd>
        </dl>
      </div>
      <div className="card">
        <h2>{t("lat_enforced")}</h2>
        <p className="hint">{t("lat_enforced_hint")}</p>
        <dl className="host-facts">
          <dt>{t("lat_edges")}</dt><dd data-role="edges-enforced">{ex.edges_enforced.toLocaleString()}</dd>
          <dt>{t("lat_assets_reachable")}</dt><dd data-role="assets-enforced">{critical ? assetsEnf : t("lat_not_set")}</dd>
          <dt>{t("lat_pivots")}</dt><dd>{pivotsEnf}</dd>
        </dl>
      </div>
    </div>
  );
}

function short(s: string): string {
  return s.length > NAME_MAX ? `${s.slice(0, NAME_MAX - 1)}…` : s;
}

/** The shortest paths into one asset, drawn in columns by hops from it: the asset on the right. */
function PathDiagram({ asset, name, cuts }: { asset: AssetExposure; name: (k: string) => string; cuts: Cut[] }) {
  const cutEdges = new Set(cuts.filter((c) => c.kind === "edge").map((c) => `${c.src}>${c.dst}`));
  const cutNodes = new Set(cuts.filter((c) => c.kind === "node").map((c) => c.src));
  const dist = new Map<string, number>();
  const edges = new Map<string, [string, string]>();
  for (const p of asset.paths) {
    p.forEach((k, i) => dist.set(k, Math.min(dist.get(k) ?? Infinity, p.length - 1 - i)));
    p.slice(1).forEach((b, i) => edges.set(`${p[i]}>${b}`, [p[i] ?? "", b]));
  }
  const maxD = Math.max(0, ...dist.values());
  const cols: string[][] = Array.from({ length: maxD + 1 }, () => []);
  for (const [k, d] of [...dist.entries()].sort((a, b) => name(a[0]).localeCompare(name(b[0])))) cols[d]?.push(k);
  const W = 190, H = 34, GAP = 70;
  const pos = new Map<string, { x: number; y: number }>();
  cols.forEach((col, d) => col.forEach((k, i) => pos.set(k, { x: (maxD - d) * (W + GAP), y: i * (H + 12) })));
  const width = (maxD + 1) * W + maxD * GAP;
  const height = Math.max(...cols.map((c) => c.length)) * (H + 12);
  return (
    <svg className="lat-paths" viewBox={`-2 -2 ${width + 4} ${height + 4}`} width={width + 4} height={height + 4}
      role="img" aria-label={t("lat_paths")} data-role="path-diagram">
      <defs>
        <marker id="lat-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" className="lat-arrow" />
        </marker>
      </defs>
      {[...edges].map(([e, [a, b]]) => {
        const p = pos.get(a), q = pos.get(b);
        if (!p || !q) return null;
        return <line key={e} x1={p.x + W} y1={p.y + H / 2} x2={q.x} y2={q.y + H / 2} markerEnd="url(#lat-arrow)"
          className={cutEdges.has(e) ? "lat-edge lat-edge-cut" : "lat-edge"} />;
      })}
      {[...pos.entries()].map(([k, p]) => (
        <g key={k} transform={`translate(${p.x},${p.y})`}>
          <rect width={W} height={H} rx={6} className={k === asset.key ? "lat-node lat-node-asset"
            : cutNodes.has(k) ? "lat-node lat-node-cut" : "lat-node"} />
          <text x={10} y={H / 2 + 5} className="lat-node-text"><title>{name(k)}</title>{short(name(k))}</text>
        </g>
      ))}
    </svg>
  );
}

function Assets({ ex, critical, preselect, name, onCut }: {
  ex: ExposureResult; critical: boolean; preselect: string | null; name: (k: string) => string;
  onCut: (c: Cut, asset: string) => void;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const key = chosen ?? (preselect && ex.assets.some((a) => a.key === preselect) ? preselect : ex.assets[0]?.key ?? null);
  const asset = ex.assets.find((a) => a.key === key) ?? null;
  return (
    <div className="card stack" id="lat-assets" data-section="assets">
      <h2>{t("lat_assets")}</h2>
      {!critical ? (
        <p className="notice" data-role="critical-not-set">{t("lat_critical_not_set")} <Link to="/system/lateral">{t("lat_open_settings")}</Link></p>
      ) : ex.assets.length === 0 ? <p className="muted">{t("lat_assets_none")}</p> : (
        <>
          <label>
            {t("lat_asset")}
            <select name="asset" value={key ?? ""} onChange={(e) => setChosen(e.target.value)}>
              {ex.assets.map((a) => <option key={a.key} value={a.key}>{name(a.key)}（{a.sources_now}）</option>)}
            </select>
          </label>
          {asset && (
            <div className="stack" data-role="asset" data-asset={asset.key}>
              <p data-role="asset-sources">{t("lat_asset_sources", { asset: name(asset.key), now: String(asset.sources_now),
                enforced: String(asset.sources_enforced), hops: String(ex.hops) })}</p>
              {asset.sources_now === 0 ? <p className="muted">{t("lat_asset_unreachable")}</p>
                : asset.paths.length === 0 ? <p className="hint">{t("lat_asset_numbers_only")}</p> : (
                  <>
                    <h3>{t("lat_paths")}</h3>
                    <div className="lat-paths-wrap"><PathDiagram asset={asset} name={name} cuts={asset.cuts} /></div>
                    <ul className="plain-list" data-role="paths">
                      {asset.paths.map((p) => <li key={p.join(">")} className="lat-path">{p.map(name).join(" → ")}</li>)}
                    </ul>
                    <h3>{t("lat_cuts")}</h3>
                    {asset.cuts.length === 0 ? <p className="muted">{t("lat_cuts_none")}</p> : (
                      <ul className="plain-list" data-role="cuts">
                        {asset.cuts.map((c) => (
                          <li key={`${c.kind}|${c.src}|${c.dst ?? ""}`} className="lat-cut">
                            {c.kind === "edge" && c.dst
                              ? t("lat_cut_edge", { src: name(c.src), dst: name(c.dst), ports: (c.ports as Port[]).map(
                                ([p, pr]) => `${p}/${protoName(pr)}`).join("、"), asset: name(asset.key),
                              before: String(c.before), after: String(c.after) })
                              : t("lat_cut_node", { host: name(c.src), asset: name(asset.key), before: String(c.before),
                                after: String(c.after) })}
                            {" "}
                            <button type="button" className="btn-quiet" data-role="sim-cut" onClick={() => onCut(c, asset.key)}>
                              {t("lat_simulate")}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Reach({ ex, name, focus }: { ex: ExposureResult; name: (k: string) => string; focus: string | null }) {
  const focusAt = focus ? ex.hosts.findIndex((h) => h.key === focus) : -1;
  const [all, setAll] = useState(focusAt >= HOSTS_SHOWN);
  useEffect(() => {
    if (focus) document.querySelector(`[data-host="${CSS.escape(focus)}"]`)?.scrollIntoView({ block: "center" });
  }, [focus]);
  const shown = all ? ex.hosts : ex.hosts.slice(0, HOSTS_SHOWN);
  const pivots = ex.hosts.filter((h) => h.pivot_now);
  return (
    <>
      <div className="card stack" id="lat-reach" data-section="reach">
        <h2>{t("lat_reach")}</h2>
        <p className="hint">{t("lat_reach_hint", { hops: String(ex.hops) })}</p>
        {focus && focusAt < 0 && <p className="hint">{t("lat_host_not_in_graph", { host: name(focus) })}</p>}
        <div className="table-wrap">
          <table className="table" data-role="reach">
            <thead><tr><th>{t("lat_col_host")}</th><th>{t("lat_now")}</th><th>{t("lat_enforced")}</th><th>{t("lat_pivot")}</th></tr></thead>
            <tbody>
              {shown.map((h) => (
                <tr key={h.key} data-host={h.key} className={h.key === focus ? "lat-focus" : undefined}>
                  <td><Link to={`/hosts?key=${encodeURIComponent(h.key)}`}>{name(h.key)}</Link></td>
                  <td className="wb-num">{h.reach_now}</td><td className="wb-num">{h.reach_enforced}</td>
                  <td>{h.pivot_now ? t("lat_pivot_yes") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!all && ex.hosts.length > HOSTS_SHOWN && (
          <button type="button" className="btn-quiet" data-role="lat-more" onClick={() => setAll(true)}>
            {t("lat_more", { n: String(ex.hosts.length - HOSTS_SHOWN) })}
          </button>
        )}
      </div>
      <div className="card stack" id="lat-pivots" data-section="pivots">
        <h2>{t("lat_pivots")}</h2>
        <p className="hint">{t("lat_pivots_hint")}</p>
        {pivots.length === 0 ? <p className="muted">{t("lat_pivots_none")}</p> : (
          <ul className="plain-list">
            {pivots.map((h) => (
              <li key={h.key}>
                <Link to={`/hosts?key=${encodeURIComponent(h.key)}`}>{name(h.key)}</Link>
                <span className="hint">{h.pivot_enforced ? t("lat_pivot_still") : t("lat_pivot_gone")}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function Groups({ ex }: { ex: ExposureResult }) {
  const [by, setBy] = useState<(typeof GROUP_KEYS)[number]>("app");
  const groups = ex.groups ?? {};
  const keys = Object.keys(groups);
  const label = by === "app" ? "app" : keys.find((k) => k !== "app") ?? "env";
  const g = groups[label];
  const view = useMemo(() => {
    if (!g) return null;
    const edges = g.edges as GroupEdge[];
    const weight = new Map<string, number>();
    for (const [a, b, n] of edges) {
      weight.set(String(a), (weight.get(String(a)) ?? 0) + n);
      weight.set(String(b), (weight.get(String(b)) ?? 0) + n);
    }
    const ranked = g.groups.map(String).sort((a, b) => (weight.get(b) ?? 0) - (weight.get(a) ?? 0) || a.localeCompare(b));
    const shown = ranked.slice(0, GROUPS_SHOWN);
    const cell = new Map(edges.map(([a, b, n, st]) => [`${String(a)}>${String(b)}`, { n, st }]));
    return { shown, total: ranked.length, cell };
  }, [g]);
  const groupName = (s: string) => (s === "null" ? t("lat_group_none") : s);
  return (
    <div className="card stack" id="lat-groups" data-section="groups">
      <div className="row">
        <h2>{t("lat_groups")}</h2>
        <select name="group-by" value={by} onChange={(e) => setBy(e.target.value as (typeof GROUP_KEYS)[number])}>
          <option value="app">{t("lat_group_app")}</option>
          <option value="env">{t("lat_group_env")}</option>
        </select>
      </div>
      {!view ? <p className="muted" data-role="groups-later">{t("lat_groups_later")}</p> : (
        <>
          <p className="hint">{t("lat_groups_hint")}</p>
          <div className="table-wrap">
            <table className="table lat-matrix" data-role="matrix">
              <thead><tr><th>{t("lat_groups_from_to")}</th>{view.shown.map((c) => <th key={c}>{groupName(c)}</th>)}</tr></thead>
              <tbody>
                {view.shown.map((r) => (
                  <tr key={r}>
                    <th>{groupName(r)}</th>
                    {view.shown.map((c) => {
                      const x = view.cell.get(`${r}>${c}`);
                      return <td key={c} className="wb-num" data-state={x?.st}>{x ? x.n : ""}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {view.total > view.shown.length && (
            <p className="hint">{t("lat_groups_more", { shown: String(view.shown.length), total: String(view.total) })}</p>
          )}
        </>
      )}
    </div>
  );
}

function Happening({ page }: { page: LateralPage }) {
  const lang = useLang();
  return (
    <div className="card stack" id="lat-detections" data-section="detections">
      <h2>{t("lat_happening")}</h2>
      {!page.detections_available ? (
        <p className="notice" data-role="detections-need-mode">{t("lat_detections_need_mode")} <Link to="/system/collection">{t("lat_open_collection")}</Link></p>
      ) : (
        <>
          {page.detectors.length > 0 && (
            <ul className="status-list">
              {page.detectors.filter((d) => d.state !== "ok").map((d) => (
                <li key={d.detector}>
                  <span className="status-name">{word(DETECTOR_KEYS, d.detector)}</span>
                  <span className="badge" data-tone={STATE_TONES[d.state] ?? "neutral"}>{word(STATE_KEYS, d.state)}</span>
                  {d.reason_key && <span className="hint">{t(d.reason_key, Object.fromEntries(Object.entries(d.params).map(([k, v]) => [k, String(v)])))}</span>}
                </li>
              ))}
            </ul>
          )}
          {page.detect_state === "failed" && <p className="notice" data-role="detect-failed">{t("lat_detect_failed")} <Link to="/system/jobs">{t("lat_open_jobs")}</Link></p>}
          {page.detect_state === "not_run" && page.detections.length === 0 ? <p className="notice" data-role="detect-not-run">{t("lat_detect_not_run")}</p>
            : page.detections.length === 0 ? <p className="muted">{t(page.detect_state === "failed" ? "lat_detections_none_before" : "lat_detections_none")}</p> : (
            <ul className="focus-list" data-role="detections">
              {page.detections.map((d) => {
                const p = Object.fromEntries(Object.entries(d.params).filter(([, v]) => v !== null && typeof v !== "object")
                  .map(([k, v]) => [k, String(v).startsWith("ip:") ? String(v).slice(3) : String(v)]));
                return (
                  <li key={`${d.detector}|${d.subject}|${d.first_seen}`} className="focus-item">
                    <div className="row">
                      <span className="badge" data-tone={SEVERITY_TONES[d.severity]}>{word(SEVERITY_KEYS, d.severity)}</span>
                      {d.critical_asset && <span className="badge">{t("lat_critical_badge")}</span>}
                      <strong>{t(d.title_key, p)}</strong>
                    </div>
                    <p className="hint">{t("lat_seen", { first: formatTime(d.first_seen, lang), last: formatTime(d.last_seen, lang) })}</p>
                    {d.link_q && <Link to={`/investigate?${new URLSearchParams({ q: d.link_q }).toString()}`}>{t("lat_open_workbench")}</Link>}
                  </li>
                );
              })}
            </ul>
          )}
          {page.detections_total > page.detections.length && (
            <p className="hint">{t("lat_detections_more", { shown: String(page.detections.length), total: String(page.detections_total) })}</p>
          )}
        </>
      )}
    </div>
  );
}

registerNav({ section: "main", path: "/lateral", labelKey: "nav_lateral", order: 14, component: LateralMovement });
