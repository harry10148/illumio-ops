// Deny rule simulation (spec §6.5.1 防堵, P6c): what a suggested deny rule would block in the observed traffic and
// how it changes who can reach each critical asset. Read-only: nothing is written to the PCE.
import { useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { AggRow, DenyProposal, DenySimulationView, FlowRow } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { Pulled } from "../workbench/Workbench";

export interface Suggestion {
  proposal: DenyProposal;
  words: string;   // the rule in the reader's words: names, never hrefs
  node: boolean;   // a host cut: only the traffic into the host is counted
}

const SHOWN = 10;

function protoName(p: number): string {
  return p === 6 ? "TCP" : p === 17 ? "UDP" : String(p);
}

function csvCell(v: string | number): string {
  // A cell a spreadsheet would read as a formula (a hostname from the PCE starting with =, +, -, @) is kept as text.
  const raw = String(v);
  const s = typeof v === "string" && /^[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** The sample as CSV, built here: the list the rule would block, to hand to whoever writes the rule. */
function exportCsv(rows: FlowRow[]): void {
  const head = [t("lat_csv_src"), t("lat_csv_dst"), t("lat_csv_port"), t("lat_csv_proto"), t("lat_csv_decision"),
    t("lat_csv_connections"), t("lat_csv_first"), t("lat_csv_last")];
  const lines = rows.map((r) => [r.src_hostname ?? r.src_ip, r.dst_hostname ?? r.dst_ip, r.port ?? "", protoName(r.proto),
    r.policy_decision, r.num_connections, r.first_detected, r.last_detected].map(csvCell).join(","));
  const blob = new Blob([`﻿${[head.map(csvCell).join(","), ...lines].join("\n")}\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "deny-rule-simulation.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function Ranked({ title, rows, names, role }: { title: string; rows: AggRow[]; names: Record<string, string>; role: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <div className="stack" data-role={role}>
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="muted">{t("lat_sim_none")}</p> : (
        <ul className="plain-list">
          {shown.map((r) => {
            const key = String(r.keys[0] ?? "");
            return <li key={key}>{r.display[0] ?? names[key] ?? key}　<span className="muted">{r.value.toLocaleString()}</span></li>;
          })}
        </ul>
      )}
      {rows.length > SHOWN && !all && (
        <button type="button" className="btn-quiet" onClick={() => setAll(true)}>{t("lat_more", { n: String(rows.length - SHOWN) })}</button>
      )}
    </div>
  );
}

export function Simulation({ suggestion, criticalSet, onClose }: {
  suggestion: Suggestion; criticalSet: boolean; onClose: () => void;
}) {
  const lang = useLang();
  const [res, setRes] = useState<DenySimulationView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const body = JSON.stringify(suggestion.proposal);

  useEffect(() => {
    let live = true;  // a slower answer for the suggestion left behind must not replace this one
    setRes(null);
    setError(null);
    void call("lateral.simulate", { proposal: JSON.parse(body) as DenyProposal }).then((env) => {
      if (!live) return;
      if (env.ok && env.data) setRes(env.data);
      else setError(env.error);
    });
    return () => { live = false; };
  }, [body]);

  const sim = res?.simulation;
  const names = res?.names ?? {};
  return (
    <div className="card stack" data-role="simulation">
      <div className="row">
        <h2>{t("lat_sim_title")}</h2>
        <button type="button" className="btn-quiet" onClick={onClose}>{t("lat_sim_close")}</button>
      </div>
      <p data-role="sim-rule"><strong>{suggestion.words}</strong></p>
      <p className="hint">{t("lat_sim_readonly")}</p>
      {suggestion.node && <p className="hint" data-role="sim-node">{t("lat_sim_node_inbound")}</p>}
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {!sim && !error && <p className="muted">{t("lat_sim_running")}</p>}
      {sim && (
        <>
          {res?.pull && <Pulled info={res.pull} />}
          <p data-role="sim-counts">{t("lat_sim_counts", { connections: sim.blocked_connections.toLocaleString(),
            flows: sim.blocked_flows.toLocaleString(), start: formatTime(String(sim.window[0]), lang),
            end: formatTime(String(sim.window[1]), lang) })}</p>
          {sim.coverage.gaps.length > 0 && <p className="notice" data-role="caveat">{t("wb_gaps", { n: String(sim.coverage.gaps.length) })}</p>}
          {sim.coverage.truncated && <p className="notice" data-role="caveat">{t("wb_truncated")}</p>}
          {sim.limit_hit && <p className="hint" data-role="caveat">{t("lat_sim_limit_hit")}</p>}
          {sim.reach_change.length === 0 ? (
            <p className="muted" data-role="sim-no-assets">{t(criticalSet ? "lat_sim_no_assets" : "lat_sim_assets_unset")}</p>
          ) : (
            <div className="table-wrap">
              <table className="table" data-role="sim-reach">
                <thead><tr><th>{t("lat_asset")}</th><th>{t("lat_sim_before")}</th><th>{t("lat_sim_after")}</th></tr></thead>
                <tbody>
                  {sim.reach_change.map((c) => (
                    <tr key={c.asset} data-changed={c.after !== c.before}>
                      <td>{names[c.asset] ?? c.asset}</td><td className="wb-num">{c.before}</td><td className="wb-num">{c.after}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="host-grid">
            <Ranked title={t("lat_sim_sources")} rows={sim.sources} names={names} role="sim-sources" />
            <Ranked title={t("lat_sim_destinations")} rows={sim.destinations} names={names} role="sim-destinations" />
          </div>
          <div className="row">
            <span className="hint">{t("lat_sim_sample", { n: String(sim.sample.length) })}</span>
            <button type="button" className="btn-quiet" disabled={sim.sample.length === 0} data-role="sim-csv"
              onClick={() => exportCsv(sim.sample)}>{t("lat_sim_csv")}</button>
          </div>
        </>
      )}
    </div>
  );
}
