// The filter of a flow report: the whole flow condition the alert rules use (labels, label groups, addresses, IP lists,
// either end, ports and services, decisions, processes, users, Windows services, transmission, exclusions), picked
// from what the inventory last read. One application's report also offers its app directly.
import { useEffect, useState } from "react";

import { call } from "../../api/client";
import type { ConditionChoices, EndpointFilter, FlowCondition, FlowRequest } from "../../api/generated";
import { ConditionEditor, NO_CHOICES } from "../../components/ConditionEditor";
import { t } from "../../i18n";
import { chips } from "../workbench/conditions";

let cached: Promise<ConditionChoices> | null = null;

/** Read the choices again on the next use: the reports page calls it as it opens, so choices read for another PCE
 * (switched since) are never offered; the forms and the schedule list then share one read. */
export function forgetChoices(): void {
  cached = null;
}

/** The condition choices and whether they have arrived. */
function useChoices(): [ConditionChoices, boolean] {
  const [choices, setChoices] = useState<ConditionChoices>(NO_CHOICES);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    cached ??= call("alert_rules.condition_choices").then((env) => {
      if (env.ok && env.data) return env.data;
      cached = null;  // a failed read is tried again by the next page, never kept as "nothing to choose"
      return NO_CHOICES;
    });
    let live = true;
    void cached.then((c) => { if (live) { setChoices(c); setLoaded(true); } });
    return () => { live = false; };
  }, []);
  return [choices, loaded];
}

const APP = "app";

/** Whether the filter names an application (an app label on either side): what one application's report needs. */
export function namesApp(cond: FlowCondition | null | undefined): boolean {
  return [cond?.src, cond?.dst].some((e) => (e?.labels ?? []).some((l) => l.key === APP && l.values.length > 0));
}

function empty(cond: FlowCondition): boolean {
  return !Object.values(cond).some((v) => v !== null && v !== undefined && v !== false && !(Array.isArray(v) && v.length === 0));
}

/** The filter as words, one per condition (the workbench's chips): what the schedule list shows. */
export function FilterSummary({ value }: { value: FlowCondition | null | undefined }) {
  const [choices] = useChoices();
  if (!value) return null;
  const names = Object.fromEntries([...choices.ip_lists, ...choices.label_groups, ...choices.services].map((o) => [o.href, o.name]));
  const words = chips({ mode: "flows", condition: value } as FlowRequest, names);
  if (words.length === 0) return null;
  return (
    <div className="hint" data-role="schedule-filter">
      {words.map((c) => (c.value ? `${t(c.labelKey)}: ${c.value}` : t(c.labelKey))).join("; ")}
    </div>
  );
}

export function ReportFilter({ value, onChange, requireApp, onValid }: {
  value: FlowCondition | null; onChange: (next: FlowCondition | null) => void; requireApp: boolean;
  /** Whether every condition typed parses: the form that holds the filter does not submit until it does. */
  onValid?: (ok: boolean) => void;
}) {
  const [choices, loaded] = useChoices();
  const [invalid, setInvalidField] = useState<string | null>(null);
  const setInvalid = (field: string | null) => { setInvalidField(field); onValid?.(field === null); };
  const cond = value ?? {};
  const set = (next: FlowCondition) => onChange(empty(next) ? null : next);
  const apps = choices.labels.find((c) => c.key === APP);
  const app = (cond.dst?.labels ?? []).find((l) => l.key === APP)?.values[0] ?? "";
  const pickApp = (v: string) => {
    const dst: EndpointFilter = { ...(cond.dst ?? {}) };
    const others = (dst.labels ?? []).filter((l) => l.key !== APP);
    dst.labels = v ? [{ key: APP, values: [v] }, ...others] : others;
    set({ ...cond, dst: dst.labels.length || dst.label_groups?.length || dst.ips?.length || dst.hrefs?.length
      || dst.ip_lists?.length || dst.public ? dst : null });
  };
  return (
    <div className="stack span-all" data-role="report-filter">
      <strong>{t("gui_reports_filter")}</strong>
      <span className="hint">{requireApp ? t("gui_reports_filter_app_required") : t("gui_reports_filter_hint")}</span>
      {requireApp && (
        <label>
          {t("gui_reports_filter_app")}
          <select name="filter_app" value={app} onChange={(e) => pickApp(e.target.value)}>
            <option value="">{t("gui_reports_filter_pick")}</option>
            {(apps?.values ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
          {!apps && <span className="hint">{t("gui_reports_filter_no_labels")}</span>}
          {apps?.truncated && <span className="hint">{t("gui_reports_filter_truncated")}</span>}
        </label>
      )}
      <details open={!requireApp || !empty({ ...cond, dst: null })}>
        <summary>{t(requireApp ? "gui_reports_filter_more" : "gui_reports_filter_conditions")}</summary>
        {/* mounted once the choices are in (its label pickers start from them), and remounted when the app is picked
            above, so its address and port fields show what the filter holds */}
        {loaded
          ? <ConditionEditor key={app} value={cond} choices={choices} onChange={set} onInvalid={setInvalid} />
          : <p className="hint">{t("loading")}</p>}
      </details>
      {invalid && <p className="form-error" data-field={invalid}>{t("rule_ports_invalid")}</p>}
    </div>
  );
}
