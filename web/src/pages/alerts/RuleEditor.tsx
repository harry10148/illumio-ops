import { type FormEvent, type ReactElement, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type {
  CatalogCategory, ChannelsInput, ConditionChoices, DetectorKind, EventCatalog, EventRule, FlowCondition, PackRule,
  RulePreview, RuleWrite, Severity, SystemCheck, ThresholdType,
} from "../../api/generated";
import { ConditionEditor, NO_CHOICES, Side } from "../../components/ConditionEditor";
import { Disclosure, Purpose } from "../../components/ui";
import { t } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { CHANNEL_KEYS, CHECK_KEYS, CHECKS, DETECTOR_GROUPS, DETECTOR_KEYS, SEVERITY_KEYS, TYPE_KEYS, word } from "./common";
import { ScenarioList } from "./ScenarioList";
import { type Scenario, scenarioOf } from "./scenarios";

type Rule = RuleWrite["rule"];
type RuleType = Rule["type"];

const NEW_ID = "0".repeat(32);
const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];
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
               critical_assets_only: false, exclude: { public: true }, cooldown_minutes: 0 };
  }
}

/** The rule a scenario starts from: blank for its type, with the detector or the check it names chosen and named
 * after it; an event rule starts with no event ticked (its name is the category's, once the catalog is there). */
function fromScenario(s: Scenario): Rule {
  switch (s.group) {
    case "flow": return blank(s.id as RuleType);
    case "detector": return { ...blank("lateral"), name: t(s.labelKey), detectors: [s.id as DetectorKind] } as Rule;
    case "system": return { ...blank("system"), name: t(s.labelKey), check: s.id as SystemCheck } as Rule;
    default: return { ...blank("event"), event_types: [] as unknown as [string, ...string[]] } as Rule;
  }
}

// What the short form shows of each rule type; every other field of the rule is under Advanced.
const SHORT_FIELDS: Record<RuleType, string[]> = {
  event: ["name", "notify", "event_types", "threshold", "threshold_count", "window_minutes"],
  traffic: ["name", "notify", "condition", "threshold_connections", "window_minutes"],
  bandwidth: ["name", "notify", "condition", "threshold_mbps", "window_minutes"],
  volume: ["name", "notify", "condition", "threshold_mb", "window_minutes"],
  system: ["name", "notify"],
  lateral: ["name", "notify", "min_severity"],
};

/** Whether Advanced holds a value the short form does not show: a field outside SHORT_FIELDS that differs from the
 * rule the scenario started from, or an event type the checklist does not list. */
function advancedHolds(rule: Rule, start: Rule, listed: string[] | null): boolean {
  const now = rule as unknown as Record<string, unknown>, then = start as unknown as Record<string, unknown>;
  const shown = SHORT_FIELDS[rule.type];
  if (Object.keys(now).some((k) => !shown.includes(k) && !same(now[k], then[k]))) return true;
  return rule.type === "event" && listed !== null && rule.event_types.some((x) => x.trim() !== "" && !listed.includes(x.trim()));
}

// What a built-in event rule brings to a new rule that names exactly its events: all of these or none. Its name,
// whether it is on and whether it notifies are the operator's to choose; its pack key is not copied.
const PACK_FIELDS = ["status", "event_severity", "match_fields", "threshold", "threshold_count", "window_minutes", "severity",
                     "cooldown_minutes", "throttle"] as const;
type PackValues = Record<(typeof PACK_FIELDS)[number], unknown>;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const typeSet = (types: readonly string[]) => [...new Set(types.map((x) => x.trim()).filter((x) => x !== ""))].sort().join("\n");

/** The built-in event rule whose events are exactly these, if there is one. */
function packMatch(pack: PackRule[], types: readonly string[]): PackRule | null {
  const wanted = typeSet(types);
  if (wanted === "") return null;
  return pack.find((p) => p.rule.type === "event" && typeSet(p.rule.event_types) === wanted) ?? null;
}

function Num({ name, value, onChange }: { name: string; value: number; onChange: (n: number) => void }) {
  return <input name={name} inputMode="decimal" className="narrow" value={String(value)}
                onChange={(e) => onChange(Number(e.target.value))} />;
}

/** /alerts/rules/new is the list of scenarios; ?scenario=<group>:<id> is the form started from one of them and
 * ?form=full the form as it is; /alerts/rules/<id> edits that rule. */
export function RuleEditor() {
  const { id = "new" } = useParams();
  const [search] = useSearchParams();
  if (id !== "new") return <RuleForm key={id} id={id} scenario={null} />;
  const scenario = scenarioOf(search);
  if (scenario) return <RuleForm key={`${scenario.group}:${scenario.id}`} id={id} scenario={scenario} />;
  return search.get("form") === "full" ? <RuleForm key="full" id={id} scenario={null} /> : <ScenarioList />;
}

function RuleForm({ id, scenario }: { id: string; scenario: Scenario | null }) {
  const navigate = useNavigate();
  const [revision, setRevision] = useState<number | null>(null);
  // blank() runs once, when the form is mounted for its scenario: the condition editor's inputs are uncontrolled
  const [start] = useState<Rule | null>(() => id !== "new" ? null : scenario ? fromScenario(scenario) : blank("event"));
  const [rule, setRule] = useState<Rule | null>(start);
  const [choices, setChoices] = useState<ConditionChoices>(NO_CHOICES);
  const [catalog, setCatalog] = useState<EventCatalog | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [preview, setPreview] = useState<RulePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const ofCategory = scenario?.group === "event" ? scenario.id : null;
  const [pack, setPack] = useState<PackRule[] | null>(null);
  // the built-in rule whose settings the form now carries, and the values it brought (to tell a hand-made change)
  const [brought, setBrought] = useState<{ key: string; values: PackValues } | null>(null);
  const broughtNow = useRef(brought);
  const [fieldsSeq, setFieldsSeq] = useState(0);
  const [channels, setChannels] = useState<ChannelsInput | null>(null);

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
    void call("alert_rules.condition_choices").then((env) => {
      if (env.ok && env.data) setChoices(env.data);
    });
  }, [id]);
  useEffect(() => {
    if (ofCategory === null) return;
    void call("alert_rules.event_catalog").then((env) => {
      if (!env.ok || !env.data) { setError(env.error); return; }
      setCatalog(env.data);
      // the rule starts named after its category; a name typed while the catalog was on its way stays
      const found = env.data.categories.find((c) => c.id === ofCategory);
      if (found) setRule((r) => r && r.name === "" ? { ...r, name: t(found.label_key) } : r);
    });
  }, [ofCategory]);
  const group = scenario?.group ?? null;
  useEffect(() => {
    if (group === null) return;
    if (group === "event") {
      void call("alert_rules.pack_rules").then((env) => { if (env.ok && env.data) setPack(env.data.rules); });
    }
    void call("system.channels.get").then((env) => { if (env.ok && env.data) setChannels(env.data.channels); });
  }, [group]);
  // The ticked events are exactly a built-in rule's: its settings come in whole. They stop being so: each setting
  // goes back to what the scenario started with, unless it was changed by hand since it came in.
  const types = scenario && rule?.type === "event" ? typeSet(rule.event_types) : null;
  useEffect(() => {
    if (!pack || !start || !rule || rule.type !== "event" || types === null) return;
    const match = packMatch(pack, rule.event_types);
    const was = broughtNow.current;
    if ((match?.name_key ?? null) === (was?.key ?? null)) return;
    const next = { ...rule } as unknown as Record<string, unknown>;
    const from = start as unknown as Record<string, unknown>;
    if (was) for (const f of PACK_FIELDS) if (same(next[f], was.values[f])) next[f] = from[f];
    let now: { key: string; values: PackValues } | null = null;
    if (match) {
      const values = Object.fromEntries(PACK_FIELDS.map((f) => [f, (match.rule as unknown as Record<string, unknown>)[f]])) as PackValues;
      Object.assign(next, values);
      now = { key: match.name_key, values };
    }
    // the field matches are typed into a box that keeps its own text: it is drawn again only when they were replaced
    if (!same(next.match_fields, rule.match_fields)) setFieldsSeq((n) => n + 1);
    broughtNow.current = now;
    setBrought(now);
    setRule(next as unknown as Rule);
    setPreview(null);
  }, [types, pack]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!rule || revision === null) {
    return (
      <section className="page">
        <div className="page-title"><h1>{t("rule_editor_title")}</h1><Purpose>{t("purpose_rule_editor")}</Purpose></div>
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
  const category = ofCategory === null ? null : catalog?.categories.find((c) => c.id === ofCategory) ?? null;
  const listed = category ? category.events.map((e) => e.event_type) : null;
  // an event rule that names no event cannot be saved: the short form says so instead of sending it
  const needEvent = scenario !== null && rule.type === "event" && !rule.event_types.some((x) => x.trim() !== "");

  // The form's parts. The full form lays them out in one column; a scenario's form shows a few and keeps the rest
  // under Advanced. Either way each part is mounted once and stays where it is.
  const nameField = (
    <label>
      {t("rule_name")}
      <input name="name" value={rule.name} maxLength={120} onChange={(e) => set({ name: e.target.value })}
             placeholder={rule.pack_key ? t(rule.pack_key) : ""} />
      {fieldError("name")}
    </label>
  );
  const flowFields = flow && (
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
  );
  const checkField = rule.type === "system" && (
    <label>
      {t("rule_check")}
      <select name="check" value={rule.check} onChange={(e) => set({ check: e.target.value as SystemCheck })}>
        {CHECKS.map((c) => <option key={c} value={c}>{t(CHECK_KEYS[c] ?? c)}</option>)}
      </select>
    </label>
  );
  const detectorsField = rule.type === "lateral" && (
    <fieldset>
      <legend>{t("rule_detectors")}</legend>
      {DETECTOR_GROUPS.map((g) => (
        <div key={g.titleKey} className="stack">
          <p className="hint">{t(g.titleKey)}</p>
          <div className="form-grid">
            {g.kinds.map((d) => (
              <label key={d} className="check">
                <input type="checkbox" name={`detector_${d}`} checked={rule.detectors.includes(d)}
                       onChange={(e) => set({ detectors: (e.target.checked ? [...rule.detectors, d]
                         : rule.detectors.filter((x) => x !== d)) as [DetectorKind, ...DetectorKind[]] })} />
                {t(DETECTOR_KEYS[d] ?? d)}
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
        {SEVERITIES.map((s) => <option key={s} value={s}>{word(SEVERITY_KEYS, s)}</option>)}
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
        {(rule.type === "event" || rule.type === "lateral") && (
          <option value="">{t(rule.type === "event" ? "rule_severity_from_event" : "rule_severity_from_detection")}</option>
        )}
        {SEVERITIES.map((s) => <option key={s} value={s}>{word(SEVERITY_KEYS, s)}</option>)}
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
            onChange={(n) => set({ throttle: { ...rule.throttle!, count: n } })} /> {t("rule_throttle_per")}{" "}
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
  // where a notification goes is one setting for every rule: the short form says which channels are on now
  const channelsOn = channels ? (Object.keys(CHANNEL_KEYS) as (keyof ChannelsInput)[]).filter((k) => channels[k]?.enabled) : [];
  const channelsLine = channels && (
    <p className="hint" data-role="notify-channels">
      {channelsOn.length > 0 ? t("scn_channels_on", { channels: channelsOn.map((k) => word(CHANNEL_KEYS, k)).join(t("list_separator")) })
        : t("scn_channels_none")}{" "}
      <Link to="/alert-rules?tab=channels">{t("nav_system_channels")}</Link>
    </p>
  );
  // a system check cannot be tried on past data: its short form says so instead of offering the trial
  const noTrial = scenario !== null && rule.type === "system";

  return (
    <section className="page stack">
      <p>
        {scenario ? <Link to="/alerts/rules/new" data-role="scenario-back">{t("scn_back")}</Link>
          : <Link to="/alerts/rules">{t("rules_back")}</Link>}
      </p>
      <div className="page-title"><h1>{id === "new" ? t("rule_editor_new") : t("rule_editor_title")}</h1><Purpose>{t("purpose_rule_editor")}</Purpose></div>
      <form className="card stack" onSubmit={save} data-role="rule-editor">
        {scenario && start ? (
          <>
            <div className="stack" data-role="short-form">
              <p data-role="scenario">
                <strong>{category ? t(category.label_key) : t(scenario.labelKey)}</strong>{" — "}
                {scenario.descKey ? t(scenario.descKey) : t("scn_event_count", { n: String(category?.events.length ?? 0) })}
              </p>
              {nameField}
              {rule.type === "event" && (
                <>
                  {category && <EventChecklist category={category} rule={rule} set={set} />}
                  {catalog && !category && <p className="form-error">{t("err_not_found")}</p>}
                  {needEvent && <p className="hint" data-role="need-event">{t("scn_need_event")}</p>}
                  {brought && <p className="notice" data-role="pack-prefill">{t("scn_pack_prefill", { name: t(brought.key) })}</p>}
                  <ShortThreshold rule={rule} set={set} fieldError={fieldError} />
                </>
              )}
              {flowFields}
              {minSeverityField}
              {notifyField}
              {channelsLine}
              {noTrial && <p className="hint" data-role="preview-na">{t("rule_preview_na")}</p>}
            </div>
            <Disclosure role="advanced" summary={t("scn_advanced")}
                        open={advancedHolds(rule, start, listed) || Boolean(error?.field)}>
              <div className="stack">
                {rule.type === "event" && <EventFields rule={rule} set={set} fieldError={fieldError} threshold={false} fieldsSeq={fieldsSeq} />}
                {checkField}
                {detectorsField}
                {lateralRest}
                {severityField}
                {limits}
                {enabledField}
              </div>
            </Disclosure>
          </>
        ) : (
          <>
            {id === "new" && (
              <label>
                {t("rule_type")}
                <select name="type" value={rule.type} onChange={(e) => setRule(blank(e.target.value as RuleType))}>
                  {Object.keys(TYPE_KEYS).map((k) => <option key={k} value={k}>{word(TYPE_KEYS, k)}</option>)}
                </select>
              </label>
            )}
            {nameField}
            {rule.type === "event" && <EventFields rule={rule} set={set} fieldError={fieldError} threshold fieldsSeq={0} />}
            {flowFields}
            {checkField}
            {detectorsField}
            {minSeverityField}
            {lateralRest}
            {severityField}
            {limits}
            {enabledField}
            {notifyField}
          </>
        )}

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
              <button type="button" className="btn-danger" data-role="delete-confirm" onClick={() => void remove()}>{t("btn_confirm")}</button>
              <button type="button" className="btn-quiet" onClick={() => setConfirmDelete(false)}>{t("btn_cancel")}</button>
            </>
          ) : (
            <button type="button" className="btn-danger" onClick={() => setConfirmDelete(true)}>{t("rule_delete")}</button>
          ))}
          {!noTrial && <button type="button" className="btn-quiet" onClick={() => void runPreview()}>{t("rule_preview")}</button>}
          <button type="submit" className="btn-primary" disabled={busy || needEvent}>{t("btn_save")}</button>
        </div>
      </form>
    </section>
  );
}

/** A category's events to tick: each said as the catalog describes it. The ticked ones are the rule's event types in
 * the catalog's order; a type or pattern typed under Advanced that this category does not list stays after them. */
function EventChecklist({ category, rule, set }: {
  category: CatalogCategory; rule: EventRule; set: (patch: Partial<EventRule>) => void;
}) {
  const listed = category.events.map((e) => e.event_type);
  const toggle = (type: string, on: boolean) => {
    const others = rule.event_types.map((x) => x.trim()).filter((x) => x !== "" && !listed.includes(x));
    const ticked = listed.filter((x) => x === type ? on : rule.event_types.includes(x));
    set({ event_types: [...ticked, ...others] as unknown as [string, ...string[]] });
  };
  return (
    <fieldset data-role="event-checklist">
      <legend>{t("scn_events")}</legend>
      <div className="scn-checks">
        {category.events.map((e) => (
          <label key={e.event_type} className="check">
            <input type="checkbox" data-event-type={e.event_type} checked={rule.event_types.includes(e.event_type)}
                   onChange={(ev) => toggle(e.event_type, ev.target.checked)} />
            {t(e.description_key)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** The short form's threshold: each occurrence (one event), or a number of events within a number of minutes. A rule
 * that alerts each time on more than one event per subject can only come from elsewhere; its number is then shown. */
function ShortThreshold({ rule, set, fieldError }: {
  rule: EventRule; set: (patch: Partial<EventRule>) => void; fieldError: (name: string) => ReactElement | null;
}) {
  return (
    <p className="sentence" data-role="short-threshold">
      {t("scn_when")}{" "}
      <select name="threshold" value={rule.threshold}
              onChange={(e) => set(e.target.value === "count" ? { threshold: "count" } : { threshold: "immediate", threshold_count: 1 })}>
        <option value="immediate">{t("scn_threshold_each")}</option>
        <option value="count">{t("scn_threshold_count")}</option>
      </select>{" "}
      {rule.threshold === "count" && (
        <>
          {t("rule_window_in")} <Num name="window_minutes" value={rule.window_minutes} onChange={(n) => set({ window_minutes: n })} />{" "}
          {t("rule_minutes_at_least")}{" "}
        </>
      )}
      {(rule.threshold === "count" || rule.threshold_count !== 1) && (
        <><Num name="threshold_count" value={rule.threshold_count} onChange={(n) => set({ threshold_count: n })} /> {t("rule_unit_events")}</>
      )}
      {fieldError("window_minutes")}
    </p>
  );
}

// match_fields as text: one "path=pattern" per line (the pattern may itself hold "=").
function fieldsText(fields: Record<string, string> | undefined): string {
  return Object.entries(fields ?? {}).map(([k, v]) => `${k}=${v}`).join("\n");
}

function parseFields(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf("=");
    if (at > 0) out[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return out;
}

// A pattern (regular expression) rather than event type names: as domain/alertrules._looks_like_regex.
const isPattern = (p: string) => /^\^|\$$|[*+?[\](){}$\\]/.test(p);

/** The event catalog: a picker that adds to the typed list (which still takes types it does not list, or patterns),
 * and what each chosen type is. */
function EventPicker({ types, onAdd }: { types: string[]; onAdd: (type: string) => void }) {
  const [catalog, setCatalog] = useState<EventCatalog | null>(null);
  const [pick, setPick] = useState("");
  useEffect(() => {
    void call("alert_rules.event_catalog").then((env) => { if (env.ok && env.data) setCatalog(env.data); });
  }, []);
  if (!catalog) return null;
  const known = new Map(catalog.categories.flatMap((c) => c.events.map((e) => [e.event_type, e] as const)));
  const names = types.filter((p) => p && !isPattern(p)).flatMap((p) => p.split("|"));
  const chosen = names.filter((n) => known.has(n));
  return (
    <div className="stack" data-role="event-picker">
      <div className="row">
        <select name="event_pick" aria-label={t("rule_event_pick")} value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">{t("rule_event_pick")}</option>
          {catalog.categories.map((c) => (
            <optgroup key={c.id} label={t(c.label_key)}>
              {c.events.map((e) => <option key={e.event_type} value={e.event_type}>{`${e.event_type} — ${t(e.description_key)}`}</option>)}
            </optgroup>
          ))}
        </select>
        <button type="button" className="btn-quiet" disabled={!pick} onClick={() => { onAdd(pick); setPick(""); }}>
          {t("rule_event_add")}
        </button>
      </div>
      <p className="hint">{t("rule_event_catalog_hint")}</p>
      {names.length > 0 && (
        <ul className="stack" data-role="event-descriptions">
          {names.map((n) => {
            const e = known.get(n);
            return (
              <li key={n} data-event-type={n}>
                <span className="mono">{n}</span>{" — "}
                {e ? t(e.description_key) : <span className="hint">{t("rule_event_not_in_catalog")}</span>}
              </li>
            );
          })}
        </ul>
      )}
      {chosen.length > 0 && chosen.length === names.length && !chosen.some((n) => known.get(n)?.status_filter) && (
        <p className="hint" data-role="status-unmarked">{t("rule_event_status_unmarked")}</p>
      )}
    </div>
  );
}

function EventFields({ rule, set, fieldError, threshold, fieldsSeq }: {
  rule: EventRule; set: (patch: Partial<EventRule>) => void; fieldError: (name: string) => ReactElement | null;
  /** With the threshold sentence: the short form has its own. */ threshold: boolean;
  /** Counts the times the field matches were replaced from outside their box, which then shows the new ones. */ fieldsSeq: number;
}) {
  const add = (type: string) => {
    const kept = rule.event_types.map((p) => p.trim()).filter((p) => p !== "");
    if (!kept.includes(type)) set({ event_types: kept.concat([type]) as [string, ...string[]] });
  };
  return (
    <>
      <label>
        {t("rule_event_types")}
        <input name="event_types" value={rule.event_types.join(", ")} placeholder="rule_set.create, sec_policy.create"
               onChange={(e) => set({ event_types: e.target.value.split(",").map((s) => s.trim()) as [string, ...string[]] })} />
        <span className="hint">{t("rule_event_types_hint")}</span>
        {fieldError("event_types")}
      </label>
      <EventPicker types={rule.event_types} onAdd={add} />
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
      <details open={Object.keys(rule.match_fields ?? {}).length > 0}>
        <summary>{t("rule_match_fields")}</summary>
        <label>
          {t("rule_match_fields_label")}
          <textarea key={fieldsSeq} name="match_fields" rows={3} defaultValue={fieldsText(rule.match_fields)}
                    placeholder="created_by.user.username=admin@example.com&#10;notification_type=hard_limit.exceeded"
                    onBlur={(e) => set({ match_fields: parseFields(e.target.value) })} />
          <span className="hint">{t("rule_match_fields_hint")}</span>
          {fieldError("match_fields")}
        </label>
      </details>
      {threshold && <p className="sentence">
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
      </p>}
    </>
  );
}

registerNav({ section: "watch", path: "/alerts/rules/:id", labelKey: "rule_editor_title", order: 13, component: RuleEditor,
              hidden: true });
