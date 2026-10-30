// Quarantine (spec §6.5.1 防堵, P6d): which policy refers to each level, what the hosts' traffic was in the last week,
// then the label put on — the whole batch checked and confirmed at once. One of the two writes v6.0 makes to the PCE.
import { useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type {
  AggRow, DenySimulationView, QuarantineOutcome, QuarantinePreview, QuarantineRuleRef,
} from "../../api/generated";
import { t } from "../../i18n";
import { word } from "../alerts/common";
import { Pulled } from "../workbench/Workbench";

export interface QuarantineHost { key: string; name: string }

const LEVELS = ["Mild", "Moderate", "Severe"] as const;
const LEVEL_KEYS: Record<string, string> = { Mild: "q_level_mild", Moderate: "q_level_moderate", Severe: "q_level_severe" };
const STATE_KEYS: Record<string, string> = {
  active: "q_state_active", disabled: "q_state_disabled", draft_only: "q_state_draft_only", none: "q_state_none",
};
const STATE_HINT_KEYS: Record<string, string> = {
  active: "q_state_active_hint", disabled: "q_state_disabled_hint", draft_only: "q_state_draft_only_hint",
  none: "q_state_none_hint",
};
const STATE_TONES: Record<string, string> = { active: "ok", disabled: "warn", draft_only: "warn", none: "warn" };
const RULE_KEYS: Record<string, string> = {
  allow: "q_rule_allow", deny: "q_rule_deny", override_deny: "q_rule_override_deny", scope: "q_rule_scope",
};
const STATUS_KEYS: Record<string, string> = {
  ok: "q_status_ok", failed: "q_status_failed", skipped: "q_status_skipped", not_quarantined: "q_status_not_quarantined",
  unknown: "q_status_unknown", refused: "q_status_refused", pending: "q_status_pending",
};
const DETAIL_KEYS: Record<string, string> = {
  pce_changed: "q_detail_pce_changed", no_policy: "q_detail_no_policy", no_write_key: "q_detail_no_write_key",
};
const REASON_KEYS: Record<string, string> = { unmanaged: "q_reason_unmanaged", not_in_inventory: "q_reason_not_in_inventory" };
const TOP = 5;

function nonEmpty(keys: string[]): [string, ...string[]] {
  return keys as [string, ...string[]];
}

function actor(ref: string, names: Record<string, string>): string {
  if (ref === "all_workloads") return t("q_all_workloads");
  return names[ref] ?? (ref.startsWith("/orgs/") ? (ref.split("/").pop() ?? ref) : ref);
}

function RuleLine({ rule, names }: { rule: QuarantineRuleRef; names: Record<string, string> }) {
  const off = !rule.enabled || !rule.ruleset_enabled;
  const list = (xs: string[]) => xs.map((x) => actor(x, names)).join("、") || "—";
  return (
    <li className={off ? "muted" : undefined}>
      <strong>{rule.ruleset}</strong>：{word(RULE_KEYS, rule.rule_type)}
      {rule.rule_type !== "scope" && <> {list(rule.consumers)} → {list(rule.providers)}（{list(rule.services)}）</>}
      {off && <> {t("q_rule_off")}</>}
    </li>
  );
}

function Traffic({ title, view, rowsOf }: { title: string; view: DenySimulationView | null; rowsOf: "sources" | "destinations" }) {
  if (!view) return null;
  const sim = view.simulation;
  const rows: AggRow[] = sim[rowsOf].slice(0, TOP);
  return (
    <div className="stack" data-role={`q-traffic-${rowsOf}`}>
      <h3>{title}</h3>
      <p>{t("q_traffic_counts", { connections: sim.blocked_connections.toLocaleString(), flows: sim.blocked_flows.toLocaleString() })}</p>
      {view.pull && <Pulled info={view.pull} />}
      {sim.coverage.gaps.length > 0 && <p className="notice">{t("wb_gaps", { n: String(sim.coverage.gaps.length) })}</p>}
      {sim.coverage.truncated && <p className="notice">{t("wb_truncated")}</p>}
      <ul className="plain-list">
        {rows.map((r) => {
          const k = String(r.keys[0] ?? "");
          return <li key={k}>{r.display[0] ?? view.names[k] ?? k}　<span className="muted">{r.value.toLocaleString()}</span></li>;
        })}
      </ul>
      {sim[rowsOf].length > TOP && <p className="hint">{t("q_traffic_more", { n: String(sim[rowsOf].length - TOP) })}</p>}
    </div>
  );
}

export function QuarantineDialog({ hosts, onClose, onDone }: {
  hosts: QuarantineHost[]; onClose: () => void; onDone?: (o: QuarantineOutcome) => void;
}) {
  const [level, setLevel] = useState<string>("Severe");
  const [prev, setPrev] = useState<QuarantinePreview | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<QuarantineOutcome | null>(null);
  const keys = hosts.map((h) => h.key);
  const body = JSON.stringify(keys);

  useEffect(() => {
    let live = true;  // a slower answer for the level left behind must not replace this one
    setPrev(null);
    setError(null);
    setAck(false);
    void call("quarantine.preview", { keys: nonEmpty(JSON.parse(body) as string[]), level }).then((env) => {
      if (!live) return;
      if (env.ok && env.data) setPrev(env.data);
      else setError(env.error);
    });
    return () => { live = false; };
  }, [body, level]);

  async function apply() {
    setBusy(true);
    setError(null);
    const env = await call("quarantine.apply", { keys: nonEmpty(keys), level, acknowledge_no_policy: ack });
    setBusy(false);
    if (env.ok && env.data) {
      setOutcome(env.data);
      onDone?.(env.data);
    } else {
      setError(env.error);
    }
  }

  const policy = prev?.check.levels[level];
  const usable = prev?.targets.filter((x) => x.ok) ?? [];
  const needsAck = policy !== undefined && policy.state !== "active";
  const canApply = !!prev && prev.check.write_key && usable.length > 0 && (!needsAck || ack) && !busy && !outcome;

  return (
    <div className="card stack" data-role="quarantine" role="dialog" aria-label={t("q_title")}>
      <div className="row">
        <h2>{t("q_title")}</h2>
        <button type="button" className="btn-quiet" onClick={onClose}>{t("q_close")}</button>
      </div>
      <p className="hint">{t("q_intro")}</p>
      {prev && !prev.check.write_key && <p className="notice" data-role="q-no-write-key">{t("q_no_write_key")}</p>}
      <label>
        {t("q_level")}
        <select name="level" value={level} disabled={!!outcome} onChange={(e) => setLevel(e.target.value)}>
          {LEVELS.map((lv) => (
            <option key={lv} value={lv}>
              {t(LEVEL_KEYS[lv] ?? lv)}{prev ? `（${word(STATE_KEYS, prev.check.levels[lv]?.state ?? "none")}）` : ""}
            </option>
          ))}
        </select>
      </label>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {!prev && !error && <p className="muted">{t("loading")}</p>}
      {prev && policy && (
        <>
          <div className="stack" data-role="q-policy">
            <p>
              <span className="badge" data-tone={STATE_TONES[policy.state]}>{word(STATE_KEYS, policy.state)}</span>{" "}
              {word(STATE_HINT_KEYS, policy.state)}
            </p>
            {policy.rules.length > 0 && (
              <ul className="plain-list">
                {policy.rules.map((r, i) => <RuleLine key={`${r.ruleset}|${i}`} rule={r} names={prev.check.names} />)}
              </ul>
            )}
          </div>
          <div className="table-wrap">
            <table className="table" data-role="q-targets">
              <thead><tr><th>{t("q_col_host")}</th><th>{t("q_col_now")}</th><th>{t("q_col_note")}</th></tr></thead>
              <tbody>
                {prev.targets.map((x) => (
                  <tr key={x.key} data-ok={x.ok}>
                    <td>{x.name}</td>
                    <td>{x.current ? t(LEVEL_KEYS[x.current] ?? x.current) : "—"}</td>
                    <td>
                      {x.reason && word(REASON_KEYS, x.reason)}
                      {x.no_enforcement && t("q_no_enforcement")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint">{t("q_traffic_hint")}</p>
          <div className="host-grid">
            <Traffic title={t("q_traffic_in")} view={prev.inbound} rowsOf="sources" />
            <Traffic title={t("q_traffic_out")} view={prev.outbound} rowsOf="destinations" />
          </div>
          {needsAck && !outcome && (
            <label className="row" data-role="q-ack">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              {t("q_ack")}
            </label>
          )}
          {!outcome && (
            <button type="button" className="btn-primary" disabled={!canApply} onClick={() => void apply()} data-role="q-apply">
              {busy ? t("q_applying") : t("q_apply", { level: t(LEVEL_KEYS[level] ?? level), n: String(usable.length) })}
            </button>
          )}
        </>
      )}
      {outcome && <Outcome outcome={outcome} />}
    </div>
  );
}

export function Outcome({ outcome }: { outcome: QuarantineOutcome }) {
  return (
    <div className="stack" data-role="q-outcome">
      {outcome.label_created && <p className="hint">{t("q_label_created")}</p>}
      {outcome.label_error && <p className="notice">{t("q_label_error", { error: outcome.label_error })}</p>}
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>{t("q_col_host")}</th><th>{t("q_col_result")}</th><th>{t("q_col_before")}</th><th>{t("q_col_note")}</th></tr></thead>
          <tbody>
            {outcome.results.map((r) => (
              <tr key={r.key} data-status={r.status}>
                <td>{r.name}</td><td>{word(STATUS_KEYS, r.status)}</td>
                <td>{r.previous ? t(LEVEL_KEYS[r.previous] ?? r.previous) : "—"}</td>
                <td className="q-detail">{r.detail ? word({ ...REASON_KEYS, ...DETAIL_KEYS }, r.detail) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export { DETAIL_KEYS, LEVEL_KEYS, STATUS_KEYS, nonEmpty };
