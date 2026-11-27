import { type FormEvent, type ReactElement, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../../api/client";
import type { ChannelsInput, ConditionChoices, EventRule, PackRule, RulePreview, RuleWrite, RulesView, Severity, ThresholdType } from "../../../api/generated";
import { NO_CHOICES } from "../../../components/ConditionEditor";
import { Disclosure } from "../../../components/ui";
import { t } from "../../../i18n";
import { CHANNEL_KEYS, SEVERITY_KEYS, TYPE_KEYS, word } from "../common";
import { useUnsavedChanges } from "../../../shell/unsaved";
import { Num } from "../RuleEditor";
import { blank, differsFromPack, fromTemplate, restored, stateOf, switchMetric, withState, type FlowRule, type State } from "./model";
import { EventCondition } from "./EventCondition";
import { FlowCondition } from "./FlowCondition";

type Rule = RuleWrite["rule"];
type FlowType = FlowRule["type"];
const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];
const WHY_KEYS: Record<string, string> = {
  rule_agent_tampering: "rule_why_agent_tampering",
  rule_agent_suspend: "rule_why_agent_suspend",
  rule_agent_clone: "rule_why_agent_clone",
  rule_agent_heartbeat: "rule_why_agent_heartbeat",
  rule_agent_offline: "rule_why_agent_offline",
  rule_lost_agent: "rule_why_lost_agent",
  rule_login_failed: "rule_why_login_failed",
  rule_api_auth_failed: "rule_why_api_auth_failed",
  rule_api_authz_failed: "rule_why_api_authz_failed",
  rule_policy_fail: "rule_why_policy_fail",
  rule_ruleset_change: "rule_why_ruleset_change",
  rule_sec_rule_change: "rule_why_sec_rule_change",
  rule_policy_provision: "rule_why_policy_provision",
  rule_api_key_change: "rule_why_api_key_change",
  rule_bulk_unpair: "rule_why_bulk_unpair",
  rule_auth_settings_change: "rule_why_auth_settings_change",
  rule_high_blocked: "rule_why_high_blocked",
};

function same(left: unknown, right: unknown): boolean {
  const normalize = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(normalize);
    if (value && typeof value === "object") {
      const record = value as Record<string, unknown>;
      return Object.fromEntries(Object.keys(record).sort().map((key) => [key, normalize(record[key])]));
    }
    return value;
  };
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right));
}

function comparableRule(rule: Rule): Record<string, unknown> {
  const { enabled: _enabled, notify: _notify, ...rest } = rule;
  return rest;
}

function Step({ number, label, children, kind }: { number: number; label: string; children: ReactNode; kind?: string }) {
  return <section className="rule-form-step" data-step={number} data-kind={kind}>
    <div className="rule-form-step-label">{number} {label}</div>
    <div className="rule-form-step-body">{children}</div>
  </section>;
}

function flowClause(type: FlowType): string {
  if (type === "traffic") return t("rule_form_flow_traffic_clause");
  if (type === "bandwidth") return t("rule_form_flow_bandwidth_clause");
  return t("rule_form_flow_volume_clause");
}

function flowUnit(type: FlowType): string {
  if (type === "traffic") return t("rule_form_unit_connections");
  if (type === "bandwidth") return t("rule_form_unit_mbps");
  return t("rule_unit_mb");
}

function flowHint(type: FlowType): string {
  return type === "traffic" ? t("rule_traffic_hint") : t("rule_bytes_hint");
}

function stateLabel(state: State): string {
  if (state === "off") return t("rules_state_off");
  if (state === "rec") return t("rules_state_record");
  return t("rules_state_notify");
}

export function RuleForm({ id, view, pack, onView, onStateChange, onCreated, stateSaving = false, sharedState }: {
  id: string; view: RulesView | null; pack: PackRule[];
  onView: (next: RulesView) => void; onStateChange: (id: string, state: State) => void; stateSaving?: boolean;
  onCreated?: () => void;
  sharedState?: State;
}) {
  const [params, setParams] = useSearchParams();
  const isNew = id === "new";
  const [rule, setRule] = useState<Rule | null>(() => isNew ? blank(params.get("kind") === "flow" ? "traffic" : "event") : null);
  const [baseline, setBaseline] = useState<Rule | null>(() => isNew ? blank(params.get("kind") === "flow" ? "traffic" : "event") : null);
  const [revision, setRevision] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [preview, setPreview] = useState<RulePreview | null>(null);
  const [channels, setChannels] = useState<ChannelsInput | null>(null);
  const [choices, setChoices] = useState<ConditionChoices>(NO_CHOICES);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [fieldsSeq, setFieldsSeq] = useState(0);
  const [touched, setTouched] = useState({ window: false, threshold: false });
  const initialTemplateApplied = useRef(false);
  const templateParam = params.get("template");
  useEffect(() => {
    if (!isNew && view) {
      const found = view.items.find((item) => item.rule.id === id)?.rule;
      if (found && !baseline) {
        setRule(found);
        setBaseline(found);
        setRevision(view.revision);
      }
    } else if (isNew && !revision && view) setRevision(view.revision);
  }, [id, isNew, view, baseline, revision]);

  useEffect(() => {
    if (!isNew || initialTemplateApplied.current || pack.length === 0) return;
    if (templateParam) {
      const template = pack.find((entry) => entry.name_key === templateParam &&
        (entry.rule.type === "event" || entry.rule.type === "traffic" || entry.rule.type === "bandwidth" || entry.rule.type === "volume"));
      if (template) {
        setRule(fromTemplate(template, `${t(template.name_key)}${t("rule_template_copy_suffix")}`));
        setFieldsSeq((sequence) => sequence + 1);
      }
    }
    initialTemplateApplied.current = true;
  }, [isNew, pack, templateParam]);

  useEffect(() => {
    let active = true;
    void call("system.channels.get").then((env) => { if (active && env.ok && env.data) setChannels(env.data.channels); });
    void call("alert_rules.condition_choices").then((env) => { if (active && env.ok && env.data) setChoices(env.data); });
    return () => { active = false; };
  }, []);

  // The row saves state immediately. Reflect that shared value without replacing other form edits.
  useEffect(() => {
    if (isNew || !rule) return;
    if (sharedState) {
      setRule((value) => value ? withState(value, sharedState) : value);
      return;
    }
    const current = view?.items.find((item) => item.rule.id === id)?.rule;
    if (!current) return;
    setRule((value) => value ? { ...value, enabled: current.enabled, notify: current.notify } as Rule : value);
  }, [view, id, isNew, sharedState]);

  const dirty = Boolean(rule && baseline && (isNew ? !same(rule, baseline) : !same(comparableRule(rule), comparableRule(baseline))));
  useUnsavedChanges(dirty);
  const flow = rule?.type === "traffic" || rule?.type === "bandwidth" || rule?.type === "volume";
  const reference = useMemo(() => {
    if (!rule) return null;
    if (rule.pack_key) return pack.find((item) => item.name_key === rule.pack_key)?.rule ?? null;
    return blank(rule.type);
  }, [rule?.type, rule?.pack_key, pack]);
  const advancedDiffers = Boolean(rule && reference &&
    (!same(rule.cooldown_minutes, reference.cooldown_minutes) || !same(rule.throttle, reference.throttle)));
  const set = (patch: Partial<Rule>) => { setRule((current) => current ? { ...current, ...patch } as Rule : current); setPreview(null); };
  const fieldError = (name: string): ReactElement | null => error?.field && error.field.includes(name)
    ? <span className="field-error" data-field={error.field} role="alert">{t(error.message_key, error.params)}</span> : null;

  function close() {
    if (dirty && !window.confirm(t("rule_form_unsaved_confirm"))) return;
    setParams({}, { replace: false });
  }

  function chooseKind(next: "event" | "flow") {
    if (!isNew || !rule) return;
    // the whole rule is replaced, not merged: a rule refuses the other kind's fields
    const keep = { id: rule.id, name: rule.name, enabled: rule.enabled, notify: rule.notify };
    if (next === "event" && rule.type !== "event") setRule({ ...blank("event"), ...keep } as Rule);
    else if (next === "flow" && !flow) setRule({ ...blank("traffic"), ...keep } as Rule);
    else return;
    setPreview(null);
  }

  function chooseMetric(next: FlowType) {
    if (!flow || rule.type === next) return;
    setRule(switchMetric(rule, next, touched));
    setPreview(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!rule || revision === null || busy || localError) return;
    setBusy(true);
    setError(null);
    const latest = await call("alert_rules.list");
    if (!latest.ok || !latest.data) {
      setBusy(false);
      setError(latest.error);
      return;
    }
    const current = latest.data.items.find((item) => item.rule.id === id)?.rule;
    if (!isNew && (!current || !baseline || !same(comparableRule(current), comparableRule(baseline)))) {
      setBusy(false);
      setRevision(latest.data.revision);
      onView(latest.data);
      setError({ code: "rule_conflict", message_key: "rule_form_conflict", params: {}, field: null });
      return;
    }
    const before = new Set(latest.data.items.map((item) => item.rule.id));
    const result = isNew
      ? await call("alert_rules.create", { revision: latest.data.revision, rule })
      : await call("alert_rules.update", { revision: latest.data.revision, rule }, { rule_id: id });
    setBusy(false);
    if (!result.ok || !result.data) { setError(result.error); return; }
    onView(result.data);
    // saved: the form closes and the rule's row is shown and marked for a moment (new and edited alike)
    const target = isNew ? result.data.items.find((item) => !before.has(item.rule.id))?.rule.id : id;
    if (isNew) onCreated?.();
    setParams({}, { replace: true });
    if (target) window.setTimeout(() => {
      const row = document.querySelector<HTMLElement>(`[data-rule-id="${target}"]`);
      row?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
      row?.classList.add("rule-form-flash");
      window.setTimeout(() => row?.classList.remove("rule-form-flash"), 1600);
    }, 80);
  }

  async function reloadConflict() {
    const fresh = await call("alert_rules.list");
    if (!fresh.ok || !fresh.data) { setError(fresh.error); return; }
    const current = fresh.data.items.find((item) => item.rule.id === id)?.rule;
    if (!current) { setParams({}, { replace: true }); onView(fresh.data); return; }
    setRule(current);
    setBaseline(current);
    setRevision(fresh.data.revision);
    setError(null);
    onView(fresh.data);
    setFieldsSeq((sequence) => sequence + 1);
  }

  async function remove() {
    if (isNew) return;
    const fresh = await call("alert_rules.list");
    if (!fresh.ok || !fresh.data) { setError(fresh.error); setConfirmDelete(false); return; }
    const result = await call("alert_rules.delete", { revision: fresh.data.revision }, { rule_id: id });
    if (result.ok && result.data) { onView(result.data); setParams({}, { replace: true }); }
    else { setError(result.error); setConfirmDelete(false); }
  }

  async function runPreview() {
    if (!rule) return;
    const result = await call("alert_rules.preview", { rule, hours: 24 });
    if (result.ok && result.data) { setPreview(result.data); setError(null); }
    else setError(result.error);
  }

  function setStatus(state: State) {
    if (!rule) return;
    set(withState(rule, state));
    if (!isNew) onStateChange(id, state);
  }

  if (!rule || revision === null) return <section className="card rule-form-loading" data-role="rule-form-loading">{t("loading")}</section>;

  const eventRule = rule.type === "event" ? rule : null;
  const flowRule = flow ? rule : null;
  const customNameRequired = rule.pack_key === null;
  const templates = pack.filter((entry) => entry.rule.type === "event" || entry.rule.type === "traffic" ||
    entry.rule.type === "bandwidth" || entry.rule.type === "volume");
  const selectedTemplate = templates.find((entry) => entry.name_key === templateParam);
  const whyKey = rule.pack_key ? WHY_KEYS[rule.pack_key] : undefined;
  const restoreTemplate = rule.pack_key ? pack.find((entry) => entry.name_key === rule.pack_key) : undefined;
  const canRestore = Boolean(!isNew && restoreTemplate && differsFromPack(rule, pack));
  const headingName = view?.items.find((item) => item.rule.id === id)?.display_name || baseline?.name || rule.name;
  const channelsOn = channels ? Object.keys(CHANNEL_KEYS).filter((key) => key !== "-")
    .filter((key) => channels[key as keyof ChannelsInput].enabled) as (keyof ChannelsInput)[] : [];
  const hasNameError = Boolean(error?.field?.includes("name"));
  const state = stateOf(rule);

  function chooseTemplate(key: string) {
    if (!rule) return;
    if (dirty && !window.confirm(t("rule_template_replace_confirm"))) {
      return;
    }
    if (!key) {
      setRule(blank(rule.type));
      setFieldsSeq((sequence) => sequence + 1);
      setPreview(null);
      setParams((current) => { current.delete("template"); return current; }, { replace: true });
      return;
    }
    const template = templates.find((entry) => entry.name_key === key);
    if (!template) return;
    setRule(fromTemplate(template, `${t(template.name_key)}${t("rule_template_copy_suffix")}`));
    setFieldsSeq((sequence) => sequence + 1);
    setPreview(null);
    setParams((current) => { current.set("template", key); return current; }, { replace: true });
  }

  function restoreDefault() {
    if (!rule || !restoreTemplate || !window.confirm(t("rule_restore_confirm"))) return;
    setRule(restored(rule, restoreTemplate));
    setFieldsSeq((sequence) => sequence + 1);
    setPreview(null);
  }

  return <form className="card stack rule-form" data-role="rule-form" data-dirty={dirty} onSubmit={(event) => void save(event)}>
    <header className="rule-form-head">
      <div><h2>{isNew ? t("rule_form_new_title") : t("rule_form_edit_title", { name: headingName })}</h2>
        {!isNew && whyKey && <p className="hint">{t(whyKey)}</p>}
      </div>
      <button type="button" className="btn-text" onClick={close}>{t("rule_form_close")}</button>
    </header>
    {isNew && <div className="rule-template-picker">
      <label>{t("rule_template_label")}
        <select name="template" value={selectedTemplate?.name_key ?? ""} onChange={(event) => chooseTemplate(event.target.value)}>
          <option value="">{t("rule_template_blank")}</option>
          <optgroup label={t("rule_template_event_group")}>
            {templates.filter((entry) => entry.rule.type === "event").map((entry) =>
              <option key={entry.name_key} value={entry.name_key}>{t(entry.name_key)}</option>)}
          </optgroup>
          <optgroup label={t("rule_template_flow_group")}>
            {templates.filter((entry) => entry.rule.type !== "event").map((entry) =>
              <option key={entry.name_key} value={entry.name_key}>{t(entry.name_key)}</option>)}
          </optgroup>
        </select>
      </label>
      {selectedTemplate && WHY_KEYS[selectedTemplate.name_key] && <p className="hint">{t(WHY_KEYS[selectedTemplate.name_key]!)}</p>}
    </div>}
    <Step number={1} label={t("rule_form_step_watch")}>
      {isNew ? <div className="rule-form-segments" role="radiogroup" aria-label={t("rule_form_step_watch")}>
        {(["event", "flow"] as const).map((kind) => <label className="check" key={kind}>
          <input type="radio" name="rule_kind" value={kind} checked={kind === "event" ? rule.type === "event" : flow}
                 onChange={() => chooseKind(kind)} />{t(kind === "event" ? "alert_type_event" : "alert_type_traffic")}
        </label>)}
      </div> : <strong>{t(rule.type === "event" ? "alert_type_event" : "alert_type_traffic")}</strong>}
    </Step>
    <Step number={2} label={t("rule_form_step_condition")} kind={rule.type}>
      {eventRule && <EventCondition rule={eventRule as EventRule} set={(patch) => set(patch)} fieldError={fieldError} fieldsSeq={fieldsSeq}
        forceOpen={Boolean(error?.field?.includes("match_fields") || error?.field?.includes("event_types"))}
        items={view?.items ?? []} onOpenOwner={(ownerId) => {
          if (dirty && !window.confirm(t("rule_form_unsaved_confirm"))) return;
          setParams({ rule: ownerId });
        }} />}
      {flowRule && <FlowCondition key={`flow-condition-${fieldsSeq}`} condition={flowRule.condition} choices={choices}
        onChange={(condition) => set({ condition })} onInvalid={setLocalError}
        forceMoreOpen={Boolean(error?.field?.includes("condition."))}
        forceAdvancedOpen={Boolean(error?.field?.includes("condition."))}
        forceExclusionsOpen={Boolean(error?.field?.includes("exclude"))} />}
      {localError && <p className="field-error" data-field={localError} role="alert">{t(localError === "event_severity_empty" ? "rule_event_severity_empty" : "rule_ports_invalid")}</p>}
      {fieldError("condition")}
    </Step>
    <Step number={3} label={t("rule_form_step_threshold")}>
      {eventRule ? <div className="rule-form-threshold">
        <div className="rule-form-segments" role="radiogroup" aria-label={t("rule_form_step_threshold")}>
          {(["immediate", "count"] as ThresholdType[]).map((threshold) => <label className="check" key={threshold}>
            <input type="radio" name="threshold" value={threshold} checked={eventRule.threshold === threshold}
              onChange={() => set({ threshold, ...(threshold === "immediate" ? { threshold_count: 1 } : {}) })} />
            {threshold === "immediate" ? t("rule_form_event_every") : t("rule_form_event_accumulate")}
          </label>)}
        </div>
        {eventRule.threshold === "immediate" ? <p className="sentence">{t("rule_form_event_same_check")}{" "}
          <Num name="threshold_count" ariaLabel={t("rule_form_event_accumulate")} value={eventRule.threshold_count} onChange={(n) => set({ threshold_count: n })} /> {t("rule_unit_events")}</p>
          : <p className="sentence">{t("rule_window_in")}{" "}
            <Num name="window_minutes" ariaLabel={t("rule_minutes_at_least")} value={eventRule.window_minutes} onChange={(n) => set({ window_minutes: n })} /> {t("rule_minutes_at_least")}{" "}
            <Num name="threshold_count" ariaLabel={t("rule_form_event_accumulate")} value={eventRule.threshold_count} onChange={(n) => set({ threshold_count: n })} /> {t("rule_unit_events")}</p>}
        {fieldError("threshold_count")}{eventRule.threshold === "count" && fieldError("window_minutes")}
      </div> : flowRule && <div className="rule-form-threshold">
        <div className="rule-form-segments" role="radiogroup" aria-label={t("rule_form_step_threshold")}>
          {(["traffic", "bandwidth", "volume"] as FlowType[]).map((metric) => <label className="check" key={metric}>
            <input type="radio" name="flow_metric" value={metric} checked={flowRule.type === metric} onChange={() => chooseMetric(metric)} />
            {word(TYPE_KEYS, metric)}
          </label>)}
        </div>
        <p className="sentence">{t("rule_form_flow_lookback")}{" "}
          <Num name="window_minutes" ariaLabel={t("rule_form_flow_lookback")} value={flowRule.window_minutes} onChange={(n) => {
            setTouched((value) => ({ ...value, window: true })); set({ window_minutes: n });
          }} />{" "}
          {flowClause(flowRule.type)}{" "}
          <Num name="threshold" ariaLabel={t(flowRule.type === "traffic" ? "rule_form_flow_traffic_clause" : flowRule.type === "bandwidth" ? "rule_form_flow_bandwidth_clause" : "rule_form_flow_volume_clause")} value={flowRule.type === "traffic" ? flowRule.threshold_connections : flowRule.type === "bandwidth" ? flowRule.threshold_mbps : flowRule.threshold_mb}
            onChange={(n) => {
              setTouched((value) => ({ ...value, threshold: true }));
              if (flowRule.type === "traffic") set({ threshold_connections: n });
              else if (flowRule.type === "bandwidth") set({ threshold_mbps: n });
              else set({ threshold_mb: n });
            }} />{" "}
          {flowUnit(flowRule.type)}
        </p>
        <p className="hint">{flowHint(flowRule.type)}</p>
        {flowRule.type === "bandwidth" && <p className="hint">{t("scn_flow_bandwidth_notes")}</p>}
        {flowRule.type === "volume" && <p className="hint">{t("scn_flow_volume_notes")}</p>}
        {fieldError("window_minutes")}{fieldError("threshold")}
      </div>}
    </Step>
    <Step number={4} label={t("rule_form_step_alert")}>
      <div className="form-grid rule-form-alert-fields">
        <label className="rule-form-name">{t("rule_name")}
          <input name="name" required={customNameRequired} maxLength={120} value={rule.name} placeholder={rule.pack_key ? t(rule.pack_key) : ""}
            onChange={(event) => set({ name: event.target.value })} />
          {hasNameError && fieldError("name")}
        </label>
        <label>{t("rule_severity")}
          <select name="severity" required={flow} value={rule.severity ?? ""}
            onChange={(event) => set({ severity: (event.target.value || null) as Severity | null })}>
            {rule.type === "event" && <option value="">{t("rule_severity_from_event")}</option>}
            {SEVERITIES.map((severity) => <option key={severity} value={severity}>{word(SEVERITY_KEYS, severity)}</option>)}
          </select>{fieldError("severity")}
        </label>
      </div>
      <div className="rule-form-segments rules-state" role="radiogroup" aria-label={t("rules_state_label", { name: rule.name || t("alert_type_event") })} data-role="form-rule-state">
        {(["off", "rec", "on"] as State[]).map((value) => <label key={value}>
          <input type="radio" name="form_rule_state" value={value} checked={state === value} disabled={stateSaving}
            onChange={() => setStatus(value)} />
          <span>{stateLabel(value)}</span>
        </label>)}
      </div>
      <Disclosure role="rule-form-advanced" summary={t("scn_advanced")}
        open={advancedDiffers || Boolean(error?.field && (error.field.includes("cooldown") || error.field.includes("throttle")))}>
        <div className="form-grid">
          <label>{t("rule_cooldown")}
            <Num name="cooldown_minutes" value={rule.cooldown_minutes} onChange={(n) => set({ cooldown_minutes: n })} />
            <span className="hint">{t("rule_cooldown_hint")}</span>{fieldError("cooldown_minutes")}
          </label>
          <label className="check"><input type="checkbox" name="throttle_on" checked={rule.throttle !== null}
            onChange={(event) => set({ throttle: event.target.checked ? { count: 1, period_minutes: 15 } : null })} />{t("rule_throttle")}</label>
          {rule.throttle && <p className="sentence">{t("rule_throttle_at_most")}{" "}
            <Num name="throttle_count" value={rule.throttle.count} onChange={(n) => set({ throttle: { ...rule.throttle!, count: n } })} /> {t("rule_throttle_per")}{" "}
            <Num name="throttle_period" value={rule.throttle.period_minutes} onChange={(n) => set({ throttle: { ...rule.throttle!, period_minutes: n } })} /> {t("rule_minutes")}
          </p>}
          {fieldError("throttle")}
        </div>
      </Disclosure>
      <p className="hint" data-role="notify-channels">
        {channelsOn.length ? t("scn_channels_on", { channels: channelsOn.map((key) => word(CHANNEL_KEYS, key)).join(t("list_separator")) }) : t("scn_channels_none")} {" "}
        <Link to="/alert-rules?tab=channels" onClick={(event) => {
          if (dirty && !window.confirm(t("rule_form_unsaved_confirm"))) event.preventDefault();
        }}>{t("nav_system_channels")}</Link>
      </p>
    </Step>
    {error && !error.field && <p className="form-error" role="alert" data-role="rule-form-error">
      {t(error.message_key, error.params)}
      {error.code === "rule_conflict" && <button type="button" className="btn-quiet" onClick={() => void reloadConflict()}>{t("btn_reload")}</button>}
    </p>}
    {preview && <div className="card" data-role="preview">
      {preview.status === "not_applicable" ? <p>{t("rule_preview_na")}</p> : <p>{t("rule_preview_result", { n: String(preview.would_fire) })}</p>}
      {preview.coverage_note && <p className="hint">{t(preview.coverage_note)}</p>}
    </div>}
    <footer className="rule-form-actions">
      {canRestore && <button type="button" className="btn-quiet" onClick={restoreDefault}>{t("rule_restore_default")}</button>}
      {!isNew && (confirmDelete ? <>
        <span>{t("rule_delete_confirm")}</span>
        <button type="button" className="btn-danger" data-role="delete-confirm" onClick={() => void remove()}>{t("btn_confirm")}</button>
        <button type="button" className="btn-quiet" onClick={() => setConfirmDelete(false)}>{t("btn_cancel")}</button>
      </> : <button type="button" className="btn-danger" onClick={() => setConfirmDelete(true)}>{t("rule_delete")}</button>)}
      <button type="button" className="btn-quiet" onClick={() => void runPreview()}>{t("rule_preview")}</button>
      <button type="submit" className="btn-primary" disabled={busy || stateSaving || (customNameRequired && rule.name.trim() === "")} aria-busy={busy || undefined}>{isNew ? t("rule_form_create") : t("btn_save")}</button>
    </footer>
  </form>;
}
