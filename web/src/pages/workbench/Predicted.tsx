// The predicted-block view (spec §6.5.3, §6.6 F1, P6e): the request's flows recomputed on the PCE against the draft
// policy, each with the rule that would block it. Asked for with a button (about a minute), not on every click; the
// answer stays tied to the conditions it was computed for.
import { useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { ActorRef, PredictedView, RuleRef, ServiceRef } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { word } from "../alerts/common";
import type { Req } from "./conditions";

const SHOWN = 50;
const DECISION_KEYS: Record<string, string> = {
  allowed: "decision_allowed", potentially_blocked: "decision_potentially_blocked", blocked: "decision_blocked",
  blocked_by_boundary: "wb_pred_blocked_by_boundary", blocked_by_override_deny: "wb_pred_blocked_by_override_deny",
  potentially_blocked_by_boundary: "wb_pred_pb_by_boundary",
  potentially_blocked_by_override_deny: "wb_pred_pb_by_override_deny",
  allowed_across_boundary: "wb_pred_allowed_across_boundary", unknown: "decision_unknown",
};
const RULE_TYPE_KEYS: Record<string, string> = {
  allow: "wb_pred_rule_allow", deny: "wb_pred_rule_deny", override_deny: "wb_pred_rule_override_deny",
};

function actor(a: ActorRef): string {
  const text = a.kind === "all_workloads" ? t("wb_pred_all_workloads")
    : a.kind === "label" && a.key ? `${a.key}=${a.value ?? ""}`
      : a.name ?? (a.href ? (a.href.split("/").pop() ?? a.href) : "?");
  return a.exclusion ? t("wb_pred_except", { what: text }) : text;
}

function protoName(p: number): string {
  return p === 6 ? "TCP" : p === 17 ? "UDP" : p === 1 ? "ICMP" : String(p);
}

function service(s: ServiceRef): string {
  if (s.name) return s.name;
  const proto = s.proto === null ? "" : protoName(s.proto);
  return `${s.port ?? "*"}${s.to_port ? `-${s.to_port}` : ""}${proto ? `/${proto}` : ""}`;
}

export function ruleText(r: RuleRef): string {
  const list = (xs: string[]) => xs.join("、") || "—";
  return `${r.ruleset_name}：${word(RULE_TYPE_KEYS, r.rule_type)} ${list(r.consumers.map(actor))} → `
    + `${list(r.providers.map(actor))}（${list(r.services.map(service))}）${r.enabled ? "" : t("wb_pred_rule_off")}`;
}

/** The connection as the page shows it: hostname, else the address (never an href). */
function end(host: string | null, ip: string): string {
  return host ?? ip;
}

export function Predicted({ req }: { req: Req }) {
  const lang = useLang();
  const [view, setView] = useState<PredictedView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [all, setAll] = useState(false);
  const [asked, setAsked] = useState<string | null>(null);  // the request as sent: the server's copy adds defaults

  async function run() {
    setBusy(true);
    setError(null);
    const sent = JSON.stringify(req);
    const env = await call("workbench.predicted", { request: req as PredictedView["request"] });
    setBusy(false);
    if (env.ok && env.data) {
      setView(env.data);
      setAsked(sent);
      setAll(false);
    } else {
      setError(env.error);
    }
  }

  const changed = view !== null && asked !== JSON.stringify(req);
  const pb = view?.predicted;
  const rows = pb ? (all ? pb.rows : pb.rows.slice(0, SHOWN)) : [];
  return (
    <div className="card stack" data-role="predicted">
      <div className="row">
        <h2>{t("wb_pred_title")}</h2>
        <button type="button" className="btn-quiet" disabled={busy} onClick={() => void run()} data-role="pred-run">
          {busy ? t("wb_pred_running") : view ? t("wb_pred_again") : t("wb_pred_run")}
        </button>
      </div>
      <p className="hint">{t("wb_pred_hint")}</p>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {pb && (
        <>
          <p className="hint" data-role="pred-at">{t("wb_pred_at", { at: formatTime(pb.computed_at, lang) })}</p>
          {changed && <p className="notice" data-role="pred-stale">{t("wb_pred_stale")}</p>}
          {pb.unsupported && <p className="notice" data-role="pred-unsupported">{t("wb_pred_unsupported")}</p>}
          {pb.capped && <p className="notice">{t("wb_pred_capped")}</p>}
          {pb.limit_hit && <p className="hint">{t("wb_pred_limit", { n: String(pb.rows.length) })}</p>}
          {pb.missing_rules.length > 0 && <p className="hint">{t("wb_pred_missing_rules", { n: String(pb.missing_rules.length) })}</p>}
          {!pb.unsupported && pb.rows.length === 0 && <p className="muted">{t("wb_pred_none")}</p>}
          {rows.length > 0 && (
            <div className="table-wrap">
              <table className="table" data-role="pred-rows">
                <thead><tr><th>{t("evidence_col_src")}</th><th>{t("evidence_col_dst")}</th><th>{t("evidence_col_port")}</th>
                  <th>{t("wb_pred_col_now")}</th><th>{t("wb_pred_col_draft")}</th><th>{t("wb_pred_col_rules")}</th></tr></thead>
                <tbody>
                  {rows.map((r) => {
                    // the rule that blocks it (enforced or not yet), else the one that allows it
                    const hrefs = r.blocking_rules.length > 0 ? r.blocking_rules : r.allow_rules;
                    return (
                      <tr key={r.flow.record_key} data-draft={r.draft_decision}>
                        <td>{end(r.flow.src_hostname, r.flow.src_ip)}</td>
                        <td>{end(r.flow.dst_hostname, r.flow.dst_ip)}</td>
                        <td className="nowrap">{r.flow.port ?? "—"}/{protoName(r.flow.proto)}</td>
                        <td>{word(DECISION_KEYS, r.flow.policy_decision)}</td>
                        <td>{word(DECISION_KEYS, r.draft_decision)}</td>
                        <td className="pred-rules">
                          {hrefs.map((h) => <div key={h}>{pb.rules[h] ? ruleText(pb.rules[h]) : t("wb_pred_rule_gone")}</div>)}
                          {r.essential_service_rules.length > 0 && <div className="hint">{t("wb_pred_essential")}</div>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!all && pb.rows.length > SHOWN && (
            <button type="button" className="btn-quiet" onClick={() => setAll(true)}>{t("wb_pred_more", { n: String(pb.rows.length - SHOWN) })}</button>
          )}
        </>
      )}
    </div>
  );
}
