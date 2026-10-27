// The label filter of a flow report: conditions "source/destination <label key> = <value>", picked from the
// inventory's labels. Conditions on one side must all hold; values of one key on one side are alternatives.
import type { EndpointFilter, FlowCondition, LabelChoice, LabelCond } from "../../api/generated";
import { t } from "../../i18n";

type Side = "src" | "dst";
export interface FilterRow { side: Side; key: string; value: string }

const SIDE_KEYS: Record<Side, string> = { src: "gui_reports_filter_source", dst: "gui_reports_filter_destination" };

export function rowsOf(cond: FlowCondition | null | undefined): FilterRow[] {
  const out: FilterRow[] = [];
  for (const side of ["dst", "src"] as Side[]) {
    for (const lc of cond?.[side]?.labels ?? []) for (const value of lc.values) out.push({ side, key: lc.key, value });
  }
  return out;
}

/** The picker's rows as a filter. `base` is the filter being edited: what the picker does not show (ports,
 * decisions, exclusions, individual hosts, users) is kept, and only its label conditions are replaced. */
export function conditionOf(rows: FilterRow[], base?: FlowCondition | null): FlowCondition | null {
  const done = rows.filter((r) => r.key !== "" && r.value !== "");
  const side = (s: Side): EndpointFilter | null => {
    const byKey = new Map<string, string[]>();
    for (const r of done.filter((x) => x.side === s)) byKey.set(r.key, [...new Set([...(byKey.get(r.key) ?? []), r.value])]);
    const kept = base?.[s];
    const labels = [...byKey].map(([key, values]) => ({ key, values: values as LabelCond["values"] }));
    if (labels.length === 0 && !kept?.hrefs?.length && !kept?.ips?.length) return null;
    return { ...(kept ?? {}), labels };
  };
  const out: FlowCondition = { ...(base ?? {}), src: side("src"), dst: side("dst") };
  const rest = Object.entries(out).some(([k, v]) =>
    k !== "src" && k !== "dst" && v !== null && v !== undefined && v !== false && !(Array.isArray(v) && v.length === 0));
  return out.src || out.dst || rest ? out : null;
}

export function namesApp(rows: FilterRow[]): boolean {
  return rows.some((r) => r.key === "app" && r.value !== "");
}

export function ReportFilter({ choices, rows, onChange, requireApp }: {
  choices: LabelChoice[]; rows: FilterRow[]; onChange: (rows: FilterRow[]) => void; requireApp: boolean;
}) {
  const set = (i: number, patch: Partial<FilterRow>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch, ...(patch.key !== undefined ? { value: "" } : {}) } : r)));
  const first = requireApp && choices.some((c) => c.key === "app") ? "app" : (choices[0]?.key ?? "");
  return (
    <div className="stack span-all" data-role="report-filter">
      <strong>{t("gui_reports_filter")}</strong>
      <span className="hint">{requireApp ? t("gui_reports_filter_app_required") : t("gui_reports_filter_hint")}</span>
      {choices.length === 0 && <span className="hint">{t("gui_reports_filter_no_labels")}</span>}
      {rows.map((r, i) => {
        const values = choices.find((c) => c.key === r.key);
        return (
          <div className="row" key={i} data-role="filter-row">
            <select name="filter_side" aria-label={t("gui_reports_filter_side")} value={r.side}
              onChange={(e) => set(i, { side: e.target.value as Side })}>
              {(Object.keys(SIDE_KEYS) as Side[]).map((s) => <option key={s} value={s}>{t(SIDE_KEYS[s])}</option>)}
            </select>
            <select name="filter_key" aria-label={t("gui_reports_filter_key")} value={r.key}
              onChange={(e) => set(i, { key: e.target.value })}>
              {choices.map((c) => <option key={c.key} value={c.key}>{c.key}</option>)}
            </select>
            <select name="filter_value" aria-label={t("gui_reports_filter_value")} value={r.value}
              onChange={(e) => set(i, { value: e.target.value })}>
              <option value="">{t("gui_reports_filter_pick")}</option>
              {(values?.values ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            <button type="button" className="btn-quiet" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              {t("gui_reports_filter_remove")}
            </button>
            {values?.truncated && <span className="hint">{t("gui_reports_filter_truncated")}</span>}
          </div>
        );
      })}
      {choices.length > 0 && (
        <div>
          <button type="button" className="btn-quiet" onClick={() => onChange([...rows, { side: "dst", key: first, value: "" }])}>
            {t("gui_reports_filter_add")}
          </button>
        </div>
      )}
    </div>
  );
}
