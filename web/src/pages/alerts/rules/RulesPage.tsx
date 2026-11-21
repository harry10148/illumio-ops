import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../../api/client";
import type { ConditionChoices, EvaluateRequested, PackRule, RuleListItem, RulesView } from "../../../api/generated";
import { formatTime } from "../../../components/ProbeResults";
import { Disclosure } from "../../../components/ui";
import { t, useLang } from "../../../i18n";
import { registerNav } from "../../../shell/nav";
import { SEVERITY_KEYS, STATUS_KEYS, word } from "../common";
import { conditionText, differsFromPack, order, stateOf, tableOf, thresholdText, withState, type State, type Table } from "./model";
import { scenariosOf } from "../scenarios";
import { RuleForm } from "./RuleForm";

type PackMode = "append_missing" | "replace";
type Row = RuleListItem & { rendered: string };
const TABLES: { id: Table }[] = [{ id: "event" }, { id: "flow" }, { id: "special" }];
const STATES: { value: State }[] = [
  { value: "off" }, { value: "rec" }, { value: "on" },
];

function tableLabel(id: Table): string {
  if (id === "event") return t("rules_table_event");
  if (id === "flow") return t("rules_table_flow");
  return t("rules_table_special");
}
function tableHint(id: Table): string {
  if (id === "event") return t("rules_table_event_hint");
  if (id === "flow") return t("rules_table_flow_hint");
  return t("rules_table_special_hint");
}
function stateLabel(value: State): string {
  if (value === "off") return t("rules_state_off");
  if (value === "rec") return t("rules_state_record");
  return t("rules_state_notify");
}

function confirmFormLeave(): boolean {
  const form = document.querySelector<HTMLFormElement>("[data-role=rule-form][data-dirty=true]");
  return !form || window.confirm(t("rule_form_unsaved_confirm"));
}

function ruleSeverity(item: RuleListItem): string {
  if (item.rule.severity) return word(SEVERITY_KEYS, item.rule.severity);
  return item.rule.type === "event" ? t("rules_severity_event") : t("rules_severity_detection");
}

function threshold(item: RuleListItem): string {
  const rule = item.rule;
  if (rule.type === "lateral") return t("rules_threshold_detected", { severity: word(SEVERITY_KEYS, rule.min_severity) });
  if (rule.type === "system") {
    const key = scenariosOf("system").find((s) => s.id === rule.check)?.descKey;
    return key ? t(key) : "";
  }
  return thresholdText(rule);
}

function pageRows(items: RuleListItem[], choices: ConditionChoices, pack: PackRule[], query: string): Record<Table, Row[]> {
  const result: Record<Table, Row[]> = { event: [], flow: [], special: [] };
  for (const item of order(items, pack)) {
    const parts = conditionText(item.rule, choices);
    const text = [item.display_name, parts.main, parts.excluded, threshold(item)].filter(Boolean).join(" ");
    if (query && !text.toLocaleLowerCase().includes(query.toLocaleLowerCase())) continue;
    result[tableOf(item.rule)].push({ ...item, rendered: text });
  }
  return result;
}

export function RulesPage({ embedded = false }: { embedded?: boolean }) {
  const [params] = useSearchParams();
  const formId = params.get("rule");
  const lang = useLang();
  const [view, setView] = useState<RulesView | null>(null);
  const [pack, setPack] = useState<PackRule[]>([]);
  const [choices, setChoices] = useState<ConditionChoices>({ ip_lists: [], label_groups: [], labels: [], services: [] });
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, setConfirm] = useState<PackMode | null>(null);
  const [resetting, setResetting] = useState<string | null>(null);
  const [evaluated, setEvaluated] = useState<EvaluateRequested | null>(null);
  const [keep, setKeep] = useState("");
  const [keepSaved, setKeepSaved] = useState(false);
  const [query, setQuery] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  // the state just picked shows at once; a save that fails puts the stored one back
  const [pending, setPending] = useState<{ id: string; state: State } | null>(null);
  const savedTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    void Promise.all([call("alert_rules.list"), call("alert_rules.pack_rules"), call("alert_rules.condition_choices")])
      .then(([rules, builtins, conditionChoices]) => {
        if (rules.ok && rules.data) { setView(rules.data); setKeep(String(rules.data.retention_days)); }
        else setError(rules.error);
        if (builtins.ok && builtins.data) setPack(builtins.data.rules);
        else setError(builtins.error);
        if (conditionChoices.ok && conditionChoices.data) setChoices(conditionChoices.data);
        else setError(conditionChoices.error);
      });
  }, []);
  useEffect(() => () => window.clearTimeout(savedTimer.current), []);

  async function saveState(item: RuleListItem, state: State) {
    if (!view || savingId) return;
    setSavingId(item.rule.id);
    setPending({ id: item.rule.id, state });
    setSavedId(null);
    setFailedId(null);
    const rule = withState(item.rule, state);
    const env = await call("alert_rules.update", { revision: view.revision, rule }, { rule_id: item.rule.id });
    setSavingId(null);
    setPending(null);
    if (env.ok && env.data) {
      setView(env.data);
      setError(null);
      setSavedId(item.rule.id);
      window.clearTimeout(savedTimer.current);
      savedTimer.current = window.setTimeout(() => setSavedId(null), 1500);
    }
    else { setError(env.error); setFailedId(item.rule.id); setView({ ...view }); }
  }

  async function reset(id: string) {
    const env = await call("alert_rules.reset_state", undefined, { rule_id: id });
    setResetting(null);
    if (env.ok && env.data) { setView(env.data); setError(null); } else setError(env.error);
  }
  async function evaluateNow() {
    const env = await call("alert_rules.evaluate_now");
    if (env.ok && env.data) { setEvaluated(env.data); setError(null); }
    else { setEvaluated(null); setError(env.error); }
  }
  async function saveKeep() {
    if (!view) return;
    const env = await call("alert_rules.retention", { revision: view.revision, retention_days: Number(keep) });
    if (env.ok && env.data) { setView(env.data); setError(null); setKeepSaved(true); }
    else { setError(env.error); setKeepSaved(false); }
  }
  async function applyPack(mode: PackMode) {
    if (!view) return;
    const env = await call("alert_rules.pack", { revision: view.revision, mode });
    setConfirm(null);
    if (env.ok && env.data) { setView(env.data); setError(null); }
    else setError(env.error);
  }

  const rows = useMemo(() => pageRows(view?.items ?? [], choices, pack, query.trim()), [view, choices, pack, query]);
  const counts = useMemo(() => {
    const all = view?.items ?? [];
    const byState = { on: 0, rec: 0, off: 0 };
    let recent = 0;
    for (const item of all) { byState[stateOf(item.rule)] += 1; recent += item.summary?.fired_7d ?? 0; }
    return { event: all.filter((i) => tableOf(i.rule) === "event").length,
      flow: all.filter((i) => tableOf(i.rule) === "flow").length,
      special: all.filter((i) => tableOf(i.rule) === "special").length, ...byState, recent };
  }, [view]);

  return (
    <section className="page stack rules-page">
      {!embedded && <p><Link to="/">{t("alert_back")}</Link></p>}
      <div className="page-head rules-page-head">
        <div>{!embedded && <h1>{t("rules_title")}</h1>}
          <p className="hint">{t("rules_page_intro")}</p>
        </div>
        <div className="rules-head-actions">
          <label className="rules-search"><span className="sr-only">{t("rules_search_label")}</span>
            <input type="search" value={query} placeholder={t("rules_search_placeholder")} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <Link className={formId ? "btn-quiet" : "btn-primary"} to="/alert-rules?rule=new"
            onClick={(event) => { if (!confirmFormLeave()) event.preventDefault(); }}>{t("rules_new")}</Link>
        </div>
      </div>
      {formId && <RuleForm key={formId} id={formId} view={view} pack={pack} onView={setView}
        onCreated={() => setQuery("")}
        stateSaving={savingId === formId}
        sharedState={pending?.id === formId ? pending.state : undefined}
        onStateChange={(id, state) => {
          const item = view?.items.find((entry) => entry.rule.id === id);
          if (item) void saveState(item, state);
        }} />}
      {view && <div className="rules-summary" data-role="rules-summary">
        <span>{t("rules_count_event", { n: String(counts.event) })}</span>
        <span>{t("rules_count_flow", { n: String(counts.flow) })}</span>
        <span>{t("rules_count_special", { n: String(counts.special) })}</span>
        <span>{t("rules_count_notify", { n: String(counts.on) })}</span>
        <span>{t("rules_count_record", { n: String(counts.rec) })}</span>
        <span>{t("rules_count_off", { n: String(counts.off) })}</span>
        <span>{t("rules_count_recent", { n: String(counts.recent) })}</span>
      </div>}
      <div className="row rules-actions" data-role="evaluate">
        <button type="button" className="btn-quiet" data-role="evaluate-now" title={t("rules_evaluate_hint")}
                disabled={!view} onClick={() => void evaluateNow()}>{t("rules_evaluate_now")}</button>
        {view && <Disclosure role="pack" summary={t("rules_pack_title")} open={view.pack_missing > 0 || confirm !== null}>
          <p className="hint">{t("rules_pack_hint")}</p>
          {view.pack_missing > 0 && <p className="notice">{t("rules_pack_missing", { n: String(view.pack_missing) })}</p>}
          {confirm ? <div className="row">
            <span>{t(confirm === "replace" ? "rules_pack_replace_confirm" : "rules_pack_append_confirm")}</span>
            <button type="button" className="btn-quiet" onClick={() => void applyPack(confirm)}>{t("btn_confirm")}</button>
            <button type="button" className="btn-quiet" onClick={() => setConfirm(null)}>{t("btn_cancel")}</button>
          </div> : <div className="row">
            <button type="button" className="btn-quiet" onClick={() => setConfirm("append_missing")}>{t("rules_pack_append")}</button>
            <button type="button" className="btn-quiet" onClick={() => setConfirm("replace")}>{t("rules_pack_replace")}</button>
          </div>}
        </Disclosure>}
      </div>
      {evaluated && <p className="notice" role="status" data-role="evaluate-requested">
        {t("rules_evaluate_requested", { time: formatTime(evaluated.requested_at, lang) })}
      </p>}
      {error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
      {view && TABLES.map(({ id }) => {
        return <section key={id} className="rules-block" data-role={`rules-${id}`}>
          <header className="rules-block-head"><div><h2>{tableLabel(id)} <span className="rules-block-count">{rows[id].length}</span></h2><p>{tableHint(id)}</p></div>
            {id === "special" && <div className="rules-special-links">
              <Link className="btn-quiet" to="/alerts/rules/new?only=special">{t("rules_new_special")}</Link>
              <Link className="btn-quiet" to="/alerts/rules/new?form=full">{t("scn_full_form")}</Link>
            </div>}
          </header>
          <div className="table-wrap rules-table-wrap">
            <table className="table rules-table">
              <thead><tr><th>{t("rules_col_name")}</th><th>{t("rules_col_condition")}</th><th>{t("rules_col_threshold")}</th>
                <th>{t("rules_col_severity")}</th><th>{t("rules_col_state")}</th><th>{t("rules_col_edit")}</th></tr></thead>
              <tbody>
                {rows[id].map((item) => {
                  const rule = item.rule;
                  const state = pending?.id === rule.id ? pending.state : stateOf(rule);
                  const condition = conditionText(rule, choices);
                  const heldCount = (item.summary?.suppressed_cooldown ?? 0) + (item.summary?.suppressed_throttle ?? 0);
                  const note = item.summary?.last_status && item.summary.last_status !== "ok" ? word(STATUS_KEYS, item.summary.last_status) : "";
                  const scenarios = rule.type === "lateral" ? scenariosOf("detector").filter((s) => rule.detectors.some((detector) => detector === s.id))
                    : rule.type === "system" ? scenariosOf("system").filter((s) => s.id === rule.check) : [];
                  const specialOpen = id === "special" && Boolean(item.held || note);
                  const stateResult = savingId === rule.id ? "saving" : savedId === rule.id ? "saved" : failedId === rule.id ? "failed" : undefined;
                  return <tr key={rule.id} data-rule-id={rule.id} data-rule-type={rule.type}>
                    <td className="rules-name-cell"><div className="rules-name"><span>{item.display_name}</span>
                      {rule.pack_key && <span className="rules-built-in-tag">{t("rules_builtin_tag")}</span>}
                      {differsFromPack(rule, pack) && <span className="rules-changed-tag">{t("rules_differs_tag")}</span>}
                    </div>
                    <div className="rules-activity">
                      <span>{item.summary?.last_fired_at ? formatTime(item.summary.last_fired_at, lang) : t("rules_no_fired")}</span>
                      <span data-role="fired-7d">{t("rules_activity_fired", { n: String(item.summary?.fired_7d ?? 0) })}</span>
                      {(item.summary?.known_7d ?? 0) > 0 && <span data-role="known-7d">{t("rules_activity_known", { n: String(item.summary?.known_7d) })}</span>}
                      {heldCount > 0 && <span data-role="held-count">{t("rules_held", { n: String(heldCount) })}</span>}
                      {note && <span data-role="rule-last-status">{note}</span>}
                    </div>
                    {item.held && <div className="hint" data-role="held">
                      {t(item.held.reason === "throttle" ? "rules_hold_throttle" : "rules_hold_cooldown",
                        { n: String(item.held.subjects), time: formatTime(item.held.until, lang) })}{" "}
                      {resetting === rule.id ? <>
                        <span>{t("rules_reset_confirm")}</span>{" "}
                        <button type="button" className="btn-quiet" data-role="reset-confirm" onClick={() => void reset(rule.id)}>{t("btn_confirm")}</button>{" "}
                        <button type="button" className="btn-quiet" onClick={() => setResetting(null)}>{t("btn_cancel")}</button>
                      </> : <button type="button" className="btn-quiet" data-role="reset" onClick={() => setResetting(rule.id)}>{t("rules_reset")}</button>}
                    </div>}</td>
                    <td className="rules-condition-cell" data-role="rule-condition"><span>{condition.main || t("rules_condition_any")}</span>
                      {condition.excluded && <span data-role="rule-exclusion">{`${t("rules_exclusion_prefix")} ${condition.excluded}`}</span>}
                      {id === "special" && <Disclosure role="rule-explanation" summary={t("rules_explanation")} open={Boolean(specialOpen)}>
                        {scenarios.map((scenario) => <div className="rules-explanation-item" key={scenario.id}>
                          <p>{scenario.descKey ? t(scenario.descKey) : ""}</p>
                          {scenario.notesKey && <p className="hint">{t(scenario.notesKey)}</p>}
                        </div>)}
                      </Disclosure>}</td>
                    <td data-role="rule-threshold">{threshold(item)}</td>
                    <td>{ruleSeverity(item)}</td>
                    <td><div className="rules-state" role="radiogroup" aria-label={t("rules_state_label", { name: item.display_name })}
                              data-role="rule-state" data-state={stateResult} aria-busy={savingId === rule.id || undefined}>
                      {STATES.map(({ value }) => <label key={value}>
                        <input type="radio" name={`rule_state_${rule.id}`} value={value} checked={state === value} disabled={savingId === rule.id}
                               onChange={() => void saveState(item, value)} />
                        <span>{stateLabel(value)}</span>
                      </label>)}
                    </div></td>
                    <td className="rules-edit-cell"><Link to={`/alert-rules?rule=${rule.id}`}
                      onClick={(event) => { if (!confirmFormLeave()) event.preventDefault(); }}>{t("rules_edit")}</Link></td>
                  </tr>;
                })}
                {rows[id].length === 0 && <tr><td colSpan={6} className="rules-empty">{t("rules_no_match")}</td></tr>}
              </tbody>
            </table>
          </div>
        </section>;
      })}
      {view && <div className="card row rules-retention" data-role="retention">
        <label>{t("rules_retention")} <input name="alert_retention_days" type="number" min={0} max={3650} className="narrow" value={keep}
          onChange={(e) => { setKeep(e.target.value); setKeepSaved(false); }} /></label>
        <span className="hint">{/^\d+$/.test(keep) && Number(keep) === 0 ? t("rules_retention_forever") : t("rules_retention_hint")}</span>
        <button type="button" className="btn-quiet" disabled={!/^\d+$/.test(keep)} onClick={() => void saveKeep()}>{t("btn_save")}</button>
        {keepSaved && <span className="form-ok" role="status">{t("saved_ok")}</span>}
      </div>}
    </section>
  );
}

function RulesRedirect() { return <Navigate to="/alert-rules" replace />; }
registerNav({ section: "watch", path: "/alerts/rules", labelKey: "nav_alert_rules", order: 12, component: RulesRedirect, hidden: true });
