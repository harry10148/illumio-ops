import { type FormEvent, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { ChannelsInput, ConditionChoices, DetectorKind, RulePreview, RuleWrite, Severity, SystemCheck } from "../../api/generated";
import { NO_CHOICES, Side } from "../../components/ConditionEditor";
import { Disclosure, Purpose } from "../../components/ui";
import { t } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { CHANNEL_KEYS, CHECK_KEYS, CHECKS, DETECTOR_GROUPS, DETECTOR_KEYS, SEVERITY_KEYS, word } from "./common";
import { blank } from "./rules/model";
import { ScenarioList } from "./ScenarioList";
import { type Scenario, scenarioOf } from "./scenarios";

type Rule = RuleWrite["rule"];
const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** A scenario starts from a blank rule with the detector or system check it names chosen and named after it. */
function fromScenario(s: Scenario): Rule {
  if (s.group === "detector") return { ...blank("lateral"), name: t(s.labelKey), detectors: [s.id as DetectorKind] } as Rule;
  return { ...blank("system"), name: t(s.labelKey), check: s.id as SystemCheck } as Rule;
}

function advancedHolds(rule: Rule, start: Rule): boolean {
  const now = rule as unknown as Record<string, unknown>;
  const then = start as unknown as Record<string, unknown>;
  const shown = rule.type === "lateral" ? ["name", "notify", "min_severity"] : ["name", "notify"];
  return Object.keys(now).some((key) => !shown.includes(key) && !same(now[key], then[key]));
}

export function Num({ name, value, onChange, ariaLabel }: { name: string; value: number; onChange: (n: number) => void; ariaLabel?: string }) {
  const labels: Record<string, string> = { cooldown_minutes: "rule_cooldown", throttle_count: "rule_throttle_at_most",
    throttle_period: "rule_throttle", threshold_count: "rule_form_event_accumulate", window_minutes: "rule_form_flow_lookback", threshold: "rule_form_flow_traffic_clause" };
  return <input name={name} aria-label={ariaLabel ?? t(labels[name] ?? "rule_form_flow_lookback")} inputMode="decimal" className="narrow" value={String(value)}
                onChange={(e) => onChange(Number(e.target.value))} />;
}

/** Legacy /alerts/rules routes remain for detection/system rules; event and traffic rules use the new page. */
export function RuleEditor() {
  const { id = "new" } = useParams();
  const [search] = useSearchParams();
  if (id === "new") {
    const scenarioParam = search.get("scenario") ?? "";
    if (scenarioParam.startsWith("event:") || scenarioParam.startsWith("flow:")) {
      return <Navigate to="/alert-rules?rule=new" replace />;
    }
    if (search.get("only") === "special") return <ScenarioList />;
    const scenario = scenarioOf(search);
    if (scenario) return <RuleForm key={`${scenario.group}:${scenario.id}`} id={id} scenario={scenario} />;
    if (search.get("form") === "full") return <RuleForm key="full" id={id} scenario={null} />;
    return <Navigate to="/alert-rules?rule=new" replace />;
  }
  return <ExistingRuleRoute key={id} id={id} />;
}

function ExistingRuleRoute({ id }: { id: string }) {
  const [redirect, setRedirect] = useState<boolean | null>(null);
  useEffect(() => {
    let active = true;
    void call("alert_rules.list").then((env) => {
      if (!active) return;
      const rule = env.ok && env.data?.items.find((item) => item.rule.id === id)?.rule;
      setRedirect(Boolean(rule && (rule.type === "event" || rule.type === "traffic" || rule.type === "bandwidth" || rule.type === "volume")));
    });
    return () => { active = false; };
  }, [id]);
  if (redirect === null) return <section className="page" />;
  if (redirect) return <Navigate to={`/alert-rules?rule=${id}`} replace />;
  return <RuleForm id={id} scenario={null} />;
}

function RuleForm({ id, scenario }: { id: string; scenario: Scenario | null }) {
  const navigate = useNavigate();
  const [revision, setRevision] = useState<number | null>(null);
  const [start] = useState<Rule | null>(() => id !== "new" ? null : scenario ? fromScenario(scenario) : blank("lateral"));
  const [rule, setRule] = useState<Rule | null>(start);
  const [choices, setChoices] = useState<ConditionChoices>(NO_CHOICES);
  const [error, setError] = useState<ApiError | null>(null);
  const [preview, setPreview] = useState<RulePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [channels, setChannels] = useState<ChannelsInput | null>(null);

  useEffect(() => {
    void call("alert_rules.list").then((env) => {
      if (!env.ok || !env.data) { setError(env.error); return; }
      setRevision(env.data.revision);
      if (id !== "new") {
        const found = env.data.items.find((item) => item.rule.id === id);
        if (found) setRule(found.rule);
        else setError({ code: "not_found", message_key: "err_not_found", params: {}, field: null });
      }
    });
    void call("alert_rules.condition_choices").then((env) => {
      if (env.ok && env.data) setChoices(env.data);
    });
    if (scenario) {
      void call("system.channels.get").then((env) => { if (env.ok && env.data) setChannels(env.data.channels); });
    }
  }, [id, scenario]);

  if (!rule || revision === null) {
    return (
      <section className="page">
        <div className="page-title"><h1>{t("rule_editor_title")}</h1><Purpose>{t("purpose_rule_editor")}</Purpose></div>
        {error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
      </section>
    );
  }
  const set = (patch: Partial<Rule>) => { setRule({ ...rule, ...patch } as Rule); setPreview(null); };
  const fieldError = (name: string) => error?.field && error.field.includes(name)
    ? <span className="form-error" data-field={error.field} role="alert">{t(error.message_key, error.params)}</span> : null;

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!rule || revision === null) return;
    setBusy(true);
    const env = id === "new"
      ? await call("alert_rules.create", { revision, rule })
      : await call("alert_rules.update", { revision, rule }, { rule_id: id });
    setBusy(false);
    if (env.ok && env.data) navigate("/alert-rules");
    else setError(env.error);
  }

  async function remove() {
    if (revision === null) return;
    const env = await call("alert_rules.delete", { revision }, { rule_id: id });
    if (env.ok) navigate("/alert-rules");
    else { setError(env.error); setConfirmDelete(false); }
  }

  async function runPreview() {
    if (!rule) return;
    const env = await call("alert_rules.preview", { rule, hours: 24 });
    if (env.ok && env.data) { setPreview(env.data); setError(null); } else setError(env.error);
  }

  const checkField = rule.type === "system" && (
    <label>
      {t("rule_check")}
      <select name="check" value={rule.check} onChange={(e) => set({ check: e.target.value as SystemCheck })}>
        {CHECKS.map((check) => <option key={check} value={check}>{t(CHECK_KEYS[check] ?? check)}</option>)}
      </select>
    </label>
  );
  const detectorsField = rule.type === "lateral" && (
    <fieldset>
      <legend>{t("rule_detectors")}</legend>
      {DETECTOR_GROUPS.map((group) => (
        <div key={group.titleKey} className="stack">
          <p className="hint">{t(group.titleKey)}</p>
          <div className="form-grid">
            {group.kinds.map((detector) => (
              <label key={detector} className="check">
                <input type="checkbox" name={`detector_${detector}`} checked={rule.detectors.includes(detector)}
                       onChange={(e) => set({ detectors: (e.target.checked ? [...rule.detectors, detector]
                         : rule.detectors.filter((value) => value !== detector)) as [DetectorKind, ...DetectorKind[]] })} />
                {t(DETECTOR_KEYS[detector] ?? detector)}
              </label>
            ))}
          </div>
        </div>
      ))}
      {fieldError("detectors")}
    </fieldset>
  );
  const minSeverityField = rule.type === "lateral" && (
    <label>
      {t("rule_min_severity")}
      <select name="min_severity" value={rule.min_severity} onChange={(e) => set({ min_severity: e.target.value as Severity })}>
        {SEVERITIES.map((severity) => <option key={severity} value={severity}>{word(SEVERITY_KEYS, severity)}</option>)}
      </select>
    </label>
  );
  const lateralRest = rule.type === "lateral" && (
    <>
      <label className="check">
        <input type="checkbox" name="critical_assets_only" checked={rule.critical_assets_only}
               onChange={(e) => set({ critical_assets_only: e.target.checked })} />
        {t("rule_critical_only")}
      </label>
      <Side name="exclude" value={rule.exclude} choices={choices} onChange={(exclude) => set({ exclude })} />
    </>
  );
  const severityField = (
    <label>
      {t("rule_severity")}
      <select name="severity" value={rule.severity ?? ""} onChange={(e) => set({ severity: (e.target.value || null) as Severity | null })}>
        {rule.type === "lateral" && <option value="">{t("rule_severity_from_detection")}</option>}
        {SEVERITIES.map((severity) => <option key={severity} value={severity}>{word(SEVERITY_KEYS, severity)}</option>)}
      </select>
      {fieldError("severity")}
    </label>
  );
  const limits = (
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
            onChange={(n) => set({ throttle: { ...rule.throttle!, count: n } })} /> {t("rule_throttle_per")} {" "}
          <Num name="throttle_period" value={rule.throttle.period_minutes}
               onChange={(n) => set({ throttle: { ...rule.throttle!, period_minutes: n } })} /> {t("rule_minutes")}
        </p>
      )}
    </div>
  );
  const enabledField = (
    <label className="check">
      <input type="checkbox" name="enabled" checked={rule.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
      {t("rule_enabled")}
    </label>
  );
  const notifyField = (
    <label className="check">
      <input type="checkbox" name="notify" checked={rule.notify} onChange={(e) => set({ notify: e.target.checked })} />
      {t("rule_notify")}
    </label>
  );
  const channelsOn = channels ? (Object.keys(CHANNEL_KEYS) as (keyof ChannelsInput)[]).filter((key) => channels[key]?.enabled) : [];
  const channelsLine = channels && (
    <p className="hint" data-role="notify-channels">
      {channelsOn.length > 0 ? t("scn_channels_on", { channels: channelsOn.map((key) => word(CHANNEL_KEYS, key)).join(t("list_separator")) })
        : t("scn_channels_none")} {" "}
      <Link to="/alert-rules?tab=channels">{t("nav_system_channels")}</Link>
    </p>
  );
  const noTrial = scenario?.group === "system";
  const startLink = scenario ? "/alerts/rules/new?only=special" : "/alert-rules";

  return (
    <section className="page stack">
      <p><Link to={startLink} data-role={scenario ? "scenario-back" : undefined}>{scenario ? t("scn_back") : t("rules_back")}</Link></p>
      <div className="page-title"><h1>{id === "new" ? t("rule_editor_new") : t("rule_editor_title")}</h1><Purpose>{t("purpose_rule_editor")}</Purpose></div>
      <form className="card stack" onSubmit={save} data-role="rule-editor">
        {scenario && start ? (
          <>
            <div className="stack" data-role="short-form">
              <div className="scn-text">
                <p data-role="scenario"><strong>{t(scenario.labelKey)}</strong>{" — "}{scenario.descKey && t(scenario.descKey)}</p>
                {scenario.notesKey && <p className="hint" data-role="scenario-notes">{t(scenario.notesKey)}</p>}
              </div>
              <label>{t("rule_name")}
                <input name="name" value={rule.name} maxLength={120} onChange={(e) => set({ name: e.target.value })}
                       placeholder={rule.pack_key ? t(rule.pack_key) : ""} />
                {fieldError("name")}
              </label>
              {minSeverityField}
              {notifyField}
              {channelsLine}
              {noTrial && <p className="hint" data-role="preview-na">{t("rule_preview_na")}</p>}
            </div>
            <Disclosure role="advanced" summary={t("scn_advanced")} open={advancedHolds(rule, start) || Boolean(error?.field)}>
              <div className="stack">
                {checkField}{detectorsField}{lateralRest}{severityField}{limits}{enabledField}
              </div>
            </Disclosure>
          </>
        ) : (
          <>
            {id === "new" && <label>{t("rule_type")}
              <select name="type" value={rule.type} onChange={(e) => setRule(blank(e.target.value as "lateral" | "system"))}>
                <option value="lateral">{t("alert_type_lateral")}</option>
                <option value="system">{t("alert_type_system")}</option>
              </select>
            </label>}
            <label>{t("rule_name")}
              <input name="name" value={rule.name} maxLength={120} onChange={(e) => set({ name: e.target.value })}
                     placeholder={rule.pack_key ? t(rule.pack_key) : ""} />
              {fieldError("name")}
            </label>
            {checkField}{detectorsField}{minSeverityField}{lateralRest}{severityField}{limits}{enabledField}{notifyField}
          </>
        )}

        {error && !error.field && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
        {error?.field && <p className="form-error" data-field={error.field} role="alert">{t(error.message_key, error.params)}</p>}
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
              <button type="button" className="btn-danger" data-role="delete-confirm" onClick={() => void remove()}>{t("btn_confirm")}</button>
              <button type="button" className="btn-quiet" onClick={() => setConfirmDelete(false)}>{t("btn_cancel")}</button>
            </>
          ) : <button type="button" className="btn-danger" onClick={() => setConfirmDelete(true)}>{t("rule_delete")}</button>)}
          {!noTrial && <button type="button" className="btn-quiet" onClick={() => void runPreview()}>{t("rule_preview")}</button>}
          <button type="submit" className="btn-primary" disabled={busy} aria-busy={busy || undefined}>{t("btn_save")}</button>
        </div>
      </form>
    </section>
  );
}

registerNav({ section: "watch", path: "/alerts/rules/:id", labelKey: "rule_editor_title", order: 13, component: RuleEditor,
              hidden: true });
