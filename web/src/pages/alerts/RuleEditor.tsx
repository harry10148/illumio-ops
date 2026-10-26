import { type FormEvent, type ReactElement, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type {
  DetectorKind, EventRule, FlowCondition, LabelChoice, RulePreview, RuleWrite, Severity, SystemCheck, ThresholdType,
} from "../../api/generated";
import { ConditionEditor } from "../../components/ConditionEditor";
import { t } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { SEVERITY_KEYS, TYPE_KEYS, word } from "./common";

type Rule = RuleWrite["rule"];
type RuleType = Rule["type"];

const NEW_ID = "0".repeat(32);
const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];
const DETECTORS: DetectorKind[] = ["fanout", "new_admin_connection", "pivot_chain", "blocked_surge", "non_admin_group",
                                   "cross_env", "account_fanout", "unexpected_initiator"];
const DETECTOR_KEYS: Record<string, string> = {
  fanout: "detector_name_fanout", new_admin_connection: "detector_name_new_admin_connection",
  pivot_chain: "detector_name_pivot_chain", blocked_surge: "detector_name_blocked_surge",
  non_admin_group: "detector_name_non_admin_group", cross_env: "detector_name_cross_env",
  account_fanout: "detector_name_account_fanout", unexpected_initiator: "detector_name_unexpected_initiator",
};
const CHECKS: SystemCheck[] = ["pce_health", "collection_failing", "data_loss", "job_failing", "disk_low"];
const CHECK_KEYS: Record<string, string> = {
  pce_health: "rule_system_pce_health", collection_failing: "rule_system_collection_failing",
  data_loss: "rule_system_data_loss", job_failing: "rule_system_job_failing", disk_low: "rule_system_disk_low",
};

function blank(type: RuleType): Rule {
  const base = { id: NEW_ID, name: "", pack_key: null, enabled: true, notify: true, cooldown_minutes: 30, throttle: null };
  const condition: FlowCondition = {};
  switch (type) {
    case "event":
      return { ...base, type, severity: null, event_types: [""], status: "all", event_severity: "all", match_fields: {},
               threshold: "immediate", threshold_count: 1, window_minutes: 10 };
    case "traffic":
      return { ...base, type, severity: "medium", condition, threshold_connections: 25, window_minutes: 10 };
    case "bandwidth":
      return { ...base, type, severity: "medium", condition, threshold_mbps: 100, window_minutes: 60 };
    case "volume":
      return { ...base, type, severity: "medium", condition, threshold_mb: 1024, window_minutes: 60 };
    case "system":
      return { ...base, type, severity: "high", check: "pce_health", cooldown_minutes: 60 };
    default:
      return { ...base, type: "lateral", severity: null, detectors: ["fanout"], min_severity: "medium",
               critical_assets_only: false, cooldown_minutes: 0 };
  }
}

function Num({ name, value, onChange }: { name: string; value: number; onChange: (n: number) => void }) {
  return <input name={name} inputMode="decimal" className="narrow" value={String(value)}
                onChange={(e) => onChange(Number(e.target.value))} />;
}

export function RuleEditor() {
  const { id = "new" } = useParams();
  const navigate = useNavigate();
  const [revision, setRevision] = useState<number | null>(null);
  const [rule, setRule] = useState<Rule | null>(id === "new" ? blank("event") : null);
  const [choices, setChoices] = useState<LabelChoice[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [preview, setPreview] = useState<RulePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    void call("alert_rules.list").then((env) => {
      if (!env.ok || !env.data) { setError(env.error); return; }
      setRevision(env.data.revision);
      if (id !== "new") {
        const found = env.data.items.find((i) => i.rule.id === id);
        if (found) setRule(found.rule);
        else setError({ code: "not_found", message_key: "err_not_found", params: {}, field: null });
      }
    });
    void call("system.lateral.get").then((env) => { if (env.ok && env.data) setChoices(env.data.label_choices); });
  }, [id]);

  if (!rule || revision === null) {
    return (
      <section className="page">
        <h1>{t("rule_editor_title")}</h1>
        {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      </section>
    );
  }
  const set = (patch: Partial<Rule>) => { setRule({ ...rule, ...patch } as Rule); setPreview(null); };
  const fieldError = (name: string) => error?.field && error.field.includes(name)
    ? <span className="form-error" data-field={error.field}>{t(error.message_key, error.params)}</span> : null;

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!rule || revision === null || localError) return;
    setBusy(true);
    const env = id === "new"
      ? await call("alert_rules.create", { revision, rule })
      : await call("alert_rules.update", { revision, rule }, { rule_id: id });
    setBusy(false);
    if (env.ok && env.data) navigate("/alerts/rules");
    else setError(env.error);
  }

  async function remove() {
    if (revision === null) return;
    const env = await call("alert_rules.delete", { revision }, { rule_id: id });
    if (env.ok) navigate("/alerts/rules");
    else { setError(env.error); setConfirmDelete(false); }
  }

  async function runPreview() {
    if (!rule) return;
    const env = await call("alert_rules.preview", { rule, hours: 24 });
    if (env.ok && env.data) { setPreview(env.data); setError(null); } else setError(env.error);
  }

  const flow = rule.type === "traffic" || rule.type === "bandwidth" || rule.type === "volume";
  return (
    <section className="page stack">
      <p><Link to="/alerts/rules">{t("rules_back")}</Link></p>
      <h1>{id === "new" ? t("rule_editor_new") : t("rule_editor_title")}</h1>
      <form className="card stack" onSubmit={save} data-role="rule-editor">
        {id === "new" && (
          <label>
            {t("rule_type")}
            <select name="type" value={rule.type} onChange={(e) => setRule(blank(e.target.value as RuleType))}>
              {Object.keys(TYPE_KEYS).map((k) => <option key={k} value={k}>{word(TYPE_KEYS, k)}</option>)}
            </select>
          </label>
        )}
        <label>
          {t("rule_name")}
          <input name="name" value={rule.name} maxLength={120} onChange={(e) => set({ name: e.target.value })}
                 placeholder={rule.pack_key ? t(rule.pack_key) : ""} />
          {fieldError("name")}
        </label>

        {rule.type === "event" && <EventFields rule={rule} set={set} fieldError={fieldError} />}

        {flow && (
          <>
            <p className="sentence">
              {t("rule_window_in")} <Num name="window_minutes" value={rule.window_minutes} onChange={(n) => set({ window_minutes: n })} />{" "}
              {t("rule_minutes_at_least")}{" "}
              {rule.type === "traffic" && <><Num name="threshold" value={rule.threshold_connections} onChange={(n) => set({ threshold_connections: n })} /> {t("rule_unit_connections")}</>}
              {rule.type === "bandwidth" && <><Num name="threshold" value={rule.threshold_mbps} onChange={(n) => set({ threshold_mbps: n })} /> {t("rule_unit_mbps")}</>}
              {rule.type === "volume" && <><Num name="threshold" value={rule.threshold_mb} onChange={(n) => set({ threshold_mb: n })} /> {t("rule_unit_mb")}</>}
            </p>
            {fieldError("window_minutes")}
            <p className="hint">{t(rule.type === "traffic" ? "rule_traffic_hint" : "rule_bytes_hint")}</p>
            <ConditionEditor value={rule.condition} choices={choices} onChange={(condition) => set({ condition })}
                             onInvalid={setLocalError} />
            {localError && <p className="form-error" data-field={localError}>{t("rule_ports_invalid")}</p>}
            {fieldError("condition")}
          </>
        )}

        {rule.type === "system" && (
          <label>
            {t("rule_check")}
            <select name="check" value={rule.check} onChange={(e) => set({ check: e.target.value as SystemCheck })}>
              {CHECKS.map((c) => <option key={c} value={c}>{t(CHECK_KEYS[c] ?? c)}</option>)}
            </select>
          </label>
        )}

        {rule.type === "lateral" && (
          <>
            <fieldset>
              <legend>{t("rule_detectors")}</legend>
              <div className="form-grid">
                {DETECTORS.map((d) => (
                  <label key={d} className="check">
                    <input type="checkbox" name={`detector_${d}`} checked={rule.detectors.includes(d)}
                           onChange={(e) => set({ detectors: (e.target.checked ? [...rule.detectors, d]
                             : rule.detectors.filter((x) => x !== d)) as [DetectorKind, ...DetectorKind[]] })} />
                    {t(DETECTOR_KEYS[d] ?? d)}
                  </label>
                ))}
              </div>
              {fieldError("detectors")}
            </fieldset>
            <label>
              {t("rule_min_severity")}
              <select name="min_severity" value={rule.min_severity} onChange={(e) => set({ min_severity: e.target.value as Severity })}>
                {SEVERITIES.map((s) => <option key={s} value={s}>{word(SEVERITY_KEYS, s)}</option>)}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" name="critical_assets_only" checked={rule.critical_assets_only}
                     onChange={(e) => set({ critical_assets_only: e.target.checked })} />
              {t("rule_critical_only")}
            </label>
          </>
        )}

        <label>
          {t("rule_severity")}
          <select name="severity" value={rule.severity ?? ""} onChange={(e) => set({ severity: (e.target.value || null) as Severity | null })}>
            {(rule.type === "event" || rule.type === "lateral") && (
              <option value="">{t(rule.type === "event" ? "rule_severity_from_event" : "rule_severity_from_detection")}</option>
            )}
            {SEVERITIES.map((s) => <option key={s} value={s}>{word(SEVERITY_KEYS, s)}</option>)}
          </select>
          {fieldError("severity")}
        </label>
        <div className="form-grid">
          <label>
            {t("rule_cooldown")}
            <Num name="cooldown_minutes" value={rule.cooldown_minutes} onChange={(n) => set({ cooldown_minutes: n })} />
            <span className="hint">{t("rule_cooldown_hint")}</span>
          </label>
          <label className="check">
            <input type="checkbox" name="throttle_on" checked={rule.throttle !== null}
                   onChange={(e) => set({ throttle: e.target.checked ? { count: 1, period_minutes: 15 } : null })} />
            {t("rule_throttle")}
          </label>
          {rule.throttle && (
            <p className="sentence">
              {t("rule_throttle_at_most")} <Num name="throttle_count" value={rule.throttle.count}
                onChange={(n) => set({ throttle: { ...rule.throttle!, count: n } })} /> {t("rule_throttle_per")}{" "}
              <Num name="throttle_period" value={rule.throttle.period_minutes}
                   onChange={(n) => set({ throttle: { ...rule.throttle!, period_minutes: n } })} /> {t("rule_minutes")}
            </p>
          )}
        </div>
        <label className="check">
          <input type="checkbox" name="enabled" checked={rule.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
          {t("rule_enabled")}
        </label>
        <label className="check">
          <input type="checkbox" name="notify" checked={rule.notify} onChange={(e) => set({ notify: e.target.checked })} />
          {t("rule_notify")}
        </label>

        {error && !error.field && <p className="form-error">{t(error.message_key, error.params)}</p>}
        {error?.field && <p className="form-error" data-field={error.field}>{t(error.message_key, error.params)}</p>}
        {preview && (
          <div className="card" data-role="preview">
            {preview.status === "not_applicable" ? <p>{t("rule_preview_na")}</p>
              : <p>{t("rule_preview_result", { n: String(preview.would_fire) })}</p>}
            {preview.coverage_note && <p className="hint">{t(preview.coverage_note)}</p>}
          </div>
        )}
        <div className="actions spaced">
          {id !== "new" && (confirmDelete ? (
            <>
              <span>{t("rule_delete_confirm")}</span>
              <button type="button" className="btn-quiet" data-role="delete-confirm" onClick={() => void remove()}>{t("btn_confirm")}</button>
              <button type="button" className="btn-quiet" onClick={() => setConfirmDelete(false)}>{t("btn_cancel")}</button>
            </>
          ) : (
            <button type="button" className="btn-quiet" onClick={() => setConfirmDelete(true)}>{t("rule_delete")}</button>
          ))}
          <button type="button" className="btn-quiet" onClick={() => void runPreview()}>{t("rule_preview")}</button>
          <button type="submit" className="btn-primary" disabled={busy}>{t("btn_save")}</button>
        </div>
      </form>
    </section>
  );
}

function EventFields({ rule, set, fieldError }: {
  rule: EventRule; set: (patch: Partial<EventRule>) => void; fieldError: (name: string) => ReactElement | null;
}) {
  return (
    <>
      <label>
        {t("rule_event_types")}
        <input name="event_types" value={rule.event_types.join(", ")} placeholder="rule_set.create, sec_policy.create"
               onChange={(e) => set({ event_types: e.target.value.split(",").map((s) => s.trim()) as [string, ...string[]] })} />
        <span className="hint">{t("rule_event_types_hint")}</span>
        {fieldError("event_types")}
      </label>
      <div className="form-grid">
        <label>
          {t("rule_event_status")}
          <input name="status" value={rule.status} onChange={(e) => set({ status: e.target.value })} />
          {fieldError("status")}
        </label>
        <label>
          {t("rule_event_severity")}
          <input name="event_severity" value={rule.event_severity} onChange={(e) => set({ event_severity: e.target.value })} />
          {fieldError("event_severity")}
        </label>
      </div>
      <p className="sentence">
        <select name="threshold" value={rule.threshold} onChange={(e) => set({ threshold: e.target.value as ThresholdType })}>
          <option value="immediate">{t("rule_threshold_immediate")}</option>
          <option value="count">{t("rule_threshold_count")}</option>
        </select>{" "}
        {rule.threshold === "count" && (
          <>
            {t("rule_window_in")} <Num name="window_minutes" value={rule.window_minutes} onChange={(n) => set({ window_minutes: n })} />{" "}
            {t("rule_minutes_at_least")}{" "}
          </>
        )}
        <Num name="threshold_count" value={rule.threshold_count} onChange={(n) => set({ threshold_count: n })} /> {t("rule_unit_events")}
      </p>
    </>
  );
}

registerNav({ section: "main", path: "/alerts/rules/:id", labelKey: "rule_editor_title", order: 13, component: RuleEditor,
              hidden: true });
