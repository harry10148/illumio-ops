import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { Catalog, CustomReport, FlowCondition, ReportScheduleFields, SchedulesView, ScheduleItem } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { Switch } from "../../components/ui";
import { t, useLang } from "../../i18n";
import { STATUS_KEYS, STATUS_TONES, TYPE_KEYS, lookbackChoices, word } from "./common";
import { useUnsavedChanges } from "../../shell/unsaved";
import { FilterSummary, ReportFilter } from "./ReportFilter";

const WEEKDAY_KEYS = ["weekday_mon", "weekday_tue", "weekday_wed", "weekday_thu", "weekday_fri", "weekday_sat",
  "weekday_sun"];
const FREQUENCY_KEYS: Record<string, string> = {
  daily: "gui_reports_freq_daily", weekly: "gui_reports_freq_weekly", monthly: "gui_reports_freq_monthly",
};

const MONTH = "previous_month";  // the period choice that is not a number of days

function blank(type: string): ReportScheduleFields {
  return {
    name: "", enabled: true, report_type: type as ReportScheduleFields["report_type"], lookback_days: 7,
    frequency: "weekly", day_of_week: 0, day_of_month: null, hour: 8, minute: 0, formats: ["html", "xlsx"],
    email: false, recipients: [], lang: null, keep: 30, filter: null, period: "days",
  };
}

/** A lookback the type can read: kept when offered, else the longest one offered. */
function fitLookback(days: number, max: number | null | undefined): number {
  const choices = lookbackChoices(max);
  if (choices.length === 0 || choices.includes(String(days))) return days;
  return Number(choices[choices.length - 1]);
}

function when(s: ReportScheduleFields): string {
  const time = `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`;
  if (s.frequency === "weekly") return t("gui_reports_when_weekly", { day: t(WEEKDAY_KEYS[s.day_of_week ?? 0] ?? "weekday_mon"), time });
  if (s.frequency === "monthly") return t("gui_reports_when_monthly", { day: String(s.day_of_month ?? 1), time });
  return t("gui_reports_when_daily", { time });
}

/** Server fields that are shown by another field's control: their errors go there. */
const ERROR_SLOTS: Record<string, string> = { period: "lookback_days", hour: "time", minute: "time", email: "formats" };

function Editor({ initial, catalog, smtp, onSave, onCancel, error, busy }: {
  initial: ReportScheduleFields; catalog: Catalog; smtp: boolean; error: ApiError | null;
  busy: boolean;
  onSave: (s: ReportScheduleFields) => void; onCancel: () => void;
}) {
  const [s, setS] = useState<ReportScheduleFields>(() => ({
    ...initial,
    lookback_days: fitLookback(initial.lookback_days,
      catalog.entries.find((c) => c.report_type === initial.report_type)?.max_lookback),
  }));
  const [recipients, setRecipients] = useState(initial.recipients.join(", "));
  const [filter, setFilter] = useState<FlowCondition | null>(initial.filter ?? null);
  const [filterValid, setFilterValid] = useState(true);
  const baseline = { ...initial, lookback_days: fitLookback(initial.lookback_days,
    catalog.entries.find((c) => c.report_type === initial.report_type)?.max_lookback) };
  useUnsavedChanges(JSON.stringify(s) !== JSON.stringify(baseline) || recipients !== initial.recipients.join(", ") ||
    JSON.stringify(filter) !== JSON.stringify(initial.filter ?? null));
  const entry = catalog.entries.find((c) => c.report_type === s.report_type);
  const [customs, setCustoms] = useState<CustomReport[] | null>(null);
  // An error that names a field this form is showing goes next to that field. Any other error (none named, or one
  // with no place here, such as a recipient the server rejected: schedule.recipients.0) stays at the bottom, so no
  // error is ever dropped.
  const placed: Record<string, boolean> = {
    name: true, report_type: true, custom_id: s.report_type === "custom", lookback_days: true, frequency: true,
    day_of_week: s.frequency === "weekly", day_of_month: s.frequency === "monthly", time: true, lang: true,
    formats: true, recipients: s.email, filter: Boolean(entry?.accepts_filter), keep: true,
  };
  const errorField = error?.field?.startsWith("schedule.")
    ? (error.field.slice("schedule.".length).split(".")[0] ?? null) : null;
  const slot = errorField === null ? null : ERROR_SLOTS[errorField] ?? errorField;
  const inline = slot !== null && placed[slot] === true;
  const fieldError = (name: string) => error && inline && slot === name
    ? <span className="field-error" data-field={error.field} role="alert">{t(error.message_key, error.params)}</span> : null;
  useEffect(() => {
    if (s.report_type !== "custom" || customs) return;
    void call("custom_reports.list").then((env) => { if (env.ok && env.data) setCustoms(env.data.reports); });
  }, [s.report_type, customs]);
  const set = (patch: Partial<ReportScheduleFields>) => setS({ ...s, ...patch });
  const freq = (f: ReportScheduleFields["frequency"]) => set({
    frequency: f, day_of_week: f === "weekly" ? (s.day_of_week ?? 0) : null,
    day_of_month: f === "monthly" ? (s.day_of_month ?? 1) : null,
    period: f === "monthly" ? s.period : "days",  // the previous month is a monthly schedule's period
  });
  const toggleFormat = (f: ReportScheduleFields["formats"][number], on: boolean) =>
    // An empty list is sent as is: the server refuses it and names the field.
    set({ formats: (on ? [...new Set([...s.formats, f])] : s.formats.filter((x) => x !== f)) as ReportScheduleFields["formats"] });
  return (
    <div className="card form-grid" data-role="schedule-editor">
      <label>
        {t("gui_reports_sched_name")}
        <input name="name" value={s.name} maxLength={80} onChange={(e) => set({ name: e.target.value })} />
      </label>
      {fieldError("name")}
      <label>
        {t("gui_reports_col_report")}
        <select name="report_type" value={s.report_type}
          onChange={(e) => {
            const next = catalog.entries.find((c) => c.report_type === e.target.value);
            set({ report_type: e.target.value as ReportScheduleFields["report_type"],
                  // only a custom report names one: switching away must not send it (the server refuses it)
                  custom_id: e.target.value === "custom" ? s.custom_id : null,
                  lookback_days: fitLookback(s.lookback_days, next?.max_lookback),
                  // keep the chosen formats the new type also makes; none left: all it makes
                  formats: (s.formats.filter((f) => next?.formats.includes(f)).length
                    ? s.formats.filter((f) => next?.formats.includes(f)) : next?.formats ?? s.formats) as ReportScheduleFields["formats"] });
          }}>
          {/* a schedule of a type that is no longer made (Rule Hit Count): shown as what it is, to be changed */}
          {!catalog.entries.some((c) => c.report_type === s.report_type) && (
            <option value={s.report_type} disabled>{word(TYPE_KEYS, s.report_type)}</option>
          )}
          {catalog.entries.map((c) => (
            <option key={c.report_type} value={c.report_type} disabled={!c.available && c.report_type !== initial.report_type}>
              {word(TYPE_KEYS, c.report_type)}
            </option>
          ))}
        </select>
      </label>
      {fieldError("report_type")}
      {s.report_type === "custom" && (
        <label>
          {t("cust_which")}
          <select name="custom_id" value={s.custom_id ?? ""}
            onChange={(e) => set({ custom_id: e.target.value === "" ? null : Number(e.target.value) })}>
            <option value="">{t("cust_pick")}</option>
            {(customs ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      )}
      {s.report_type === "custom" && fieldError("custom_id")}
      <label>
        {t("gui_reports_lookback")}
        <select name="lookback_days" value={s.period === "previous_month" ? MONTH : String(s.lookback_days)}
          onChange={(e) => set(e.target.value === MONTH ? { period: "previous_month" }
            : { period: "days", lookback_days: Number(e.target.value) })}>
          {lookbackChoices(entry?.max_lookback).map((d) => <option key={d} value={d}>{t("gui_reports_days", { n: d })}</option>)}
          {s.frequency === "monthly" && <option value={MONTH}>{t("gui_reports_period_previous_month")}</option>}
        </select>
      </label>
      {fieldError("lookback_days")}
      <label>
        {t("gui_reports_frequency")}
        <select name="frequency" value={s.frequency} onChange={(e) => freq(e.target.value as ReportScheduleFields["frequency"])}>
          {Object.keys(FREQUENCY_KEYS).map((f) => <option key={f} value={f}>{word(FREQUENCY_KEYS, f)}</option>)}
        </select>
      </label>
      {fieldError("frequency")}
      {s.frequency === "weekly" && (
        <label>
          {t("gui_reports_day_of_week")}
          <select name="day_of_week" value={String(s.day_of_week ?? 0)} onChange={(e) => set({ day_of_week: Number(e.target.value) })}>
            {WEEKDAY_KEYS.map((k, i) => <option key={k} value={i}>{t(k)}</option>)}
          </select>
          {fieldError("day_of_week")}
        </label>
      )}
      {s.frequency === "monthly" && (
        <label>
          {t("gui_reports_day_of_month")}
          <input name="day_of_month" type="number" min={1} max={31} value={s.day_of_month ?? 1}
            onChange={(e) => set({ day_of_month: Number(e.target.value) })} />
          <span className="hint">{t("gui_reports_day_of_month_hint")}</span>
          {fieldError("day_of_month")}
        </label>
      )}
      <label>
        {t("gui_reports_time")}
        <input name="time" type="time" value={`${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`}
          onChange={(e) => { const [h, m] = e.target.value.split(":"); set({ hour: Number(h), minute: Number(m) }); }} />
        <span className="hint">{t("gui_reports_time_hint")}</span>
      </label>
      {fieldError("time")}
      <label>
        {t("gui_reports_language")}
        <select name="lang" value={s.lang ?? ""} onChange={(e) => set({ lang: e.target.value === "" ? null : (e.target.value as "en" | "zh_TW") })}>
          <option value="">{t("gui_reports_language_display")}</option>
          <option value="zh_TW">{t("gui_reports_language_zh")}</option>
          <option value="en">{t("gui_reports_language_en")}</option>
        </select>
      </label>
      {fieldError("lang")}
      <div className="row span-all">
        {(entry?.formats ?? ["html", "xlsx"]).map((f) => (
          <label key={f}><input type="checkbox" name={f} checked={s.formats.includes(f)}
            onChange={(e) => toggleFormat(f, e.target.checked)} /> {f.toUpperCase()}</label>
        ))}
        <label><input type="checkbox" name="email" checked={s.email} onChange={(e) => set({ email: e.target.checked })} /> {t("gui_reports_email")}</label>
        {fieldError("formats")}
        {s.email && !smtp && (
          <span className="hint">{t("gui_reports_email_needs_smtp")} <Link to="/system/channels">{t("gui_reports_channels_link")}</Link></span>
        )}
      </div>
      {s.email && (
        <label className="span-all">
          {t("gui_reports_recipients")}
          <input name="recipients" value={recipients} placeholder={t("gui_reports_recipients_hint")}
            onChange={(e) => setRecipients(e.target.value)} />
          {fieldError("recipients")}
        </label>
      )}
      {entry?.accepts_filter && (
        <ReportFilter value={filter} onChange={setFilter} requireApp={entry.requires_app} onValid={setFilterValid} />
      )}
      {entry?.accepts_filter && fieldError("filter")}
      <label>
        {t("gui_reports_keep")}
        <input name="keep" type="number" min={1} max={365} value={s.keep} onChange={(e) => set({ keep: Number(e.target.value) })} />
      </label>
      {fieldError("keep")}
      <label>
        <input type="checkbox" name="enabled" checked={s.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> {t("gui_reports_enabled")}
      </label>
      {error && !inline && <p className="form-error span-all" role="alert">{t(error.message_key, error.params)}</p>}
      <div className="actions span-all">
        <button type="button" className="btn-primary" disabled={!filterValid || busy} aria-busy={busy || undefined}
          onClick={() => onSave({ ...s, filter: entry?.accepts_filter ? filter : null,
                                  recipients: recipients.split(/[\s,;]+/).filter((r) => r !== "") })}>{t("btn_save")}</button>
        <button type="button" className="btn-quiet" onClick={onCancel}>{t("btn_cancel")}</button>
      </div>
    </div>
  );
}

export function Schedules({ catalog }: { catalog: Catalog }) {
  const lang = useLang();
  const navigate = useNavigate();
  const [view, setView] = useState<SchedulesView | null>(null);
  const [editing, setEditing] = useState<{ id: string | null; fields: ReportScheduleFields } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const env = await call("report_schedules.list");
    if (env.ok && env.data) setView(env.data);
    else setError(env.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function save(fields: ReportScheduleFields) {
    if (!view || !editing || busy) return;
    setBusy(true);
    const env = editing.id
      ? await call("report_schedules.update", { revision: view.revision, schedule: fields }, { schedule_id: editing.id })
      : await call("report_schedules.create", { revision: view.revision, schedule: fields });
    setBusy(false);
    if (env.ok && env.data) {
      setView(env.data);
      setEditing(null);
      setError(null);
    } else setError(env.error);
  }

  async function toggle(item: ScheduleItem): Promise<boolean> {
    if (!view || busy) return false;
    setBusy(true);
    const { id, ...fields } = item.schedule;
    const env = await call("report_schedules.update", { revision: view.revision, schedule: { ...fields, enabled: !fields.enabled } },
      { schedule_id: id });
    setBusy(false);
    if (env.ok && env.data) setView(env.data);
    else setError(env.error);
    return env.ok;
  }

  async function remove(id: string) {
    if (!view || busy) return;
    setBusy(true);
    const env = await call("report_schedules.delete", { revision: view.revision }, { schedule_id: id });
    setBusy(false);
    if (env.ok && env.data) { setView(env.data); setDeleting(null); }
    else setError(env.error);
  }

  async function runNow(id: string) {
    if (busy) return;
    setBusy(true);
    const env = await call("report_schedules.run_now", {}, { schedule_id: id });
    setBusy(false);
    if (env.ok && env.data) navigate(`/reports?id=${env.data.id}`);
    else setError(env.error);
  }

  if (!view) return error ? <p className="form-error" role="alert">{t(error.message_key, error.params)}</p> : null;
  const first = catalog.entries[0]?.report_type ?? "lateral_posture";
  return (
    <div className="stack" data-role="schedules">
      {!editing && (
        <div className="actions">
          <button type="button" className="btn-primary" disabled={busy} onClick={() => { setDeleting(null); setEditing({ id: null, fields: blank(first) }); }}>
            {t("gui_reports_sched_add")}
          </button>
        </div>
      )}
      {editing && (
        <Editor key={editing.id ?? "new"} initial={editing.fields} catalog={catalog} smtp={view.smtp_enabled} error={error} busy={busy}
          onSave={(f) => void save(f)} onCancel={() => { setEditing(null); setError(null); }} />
      )}
      {!editing && error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
      {view.items.length === 0 ? <p className="muted">{t("gui_reports_sched_none")}</p> : (
        <div className="table-wrap">
          <table className="table" data-role="schedule-list">
            <thead>
              <tr>
                <th>{t("gui_reports_sched_name")}</th><th>{t("gui_reports_col_report")}</th><th>{t("gui_reports_frequency")}</th>
                <th>{t("gui_reports_next_run")}</th><th>{t("gui_reports_last_result")}</th><th>{t("gui_reports_enabled")}</th><th />
              </tr>
            </thead>
            <tbody>
              {view.items.map((item) => {
                const s = item.schedule;
                return (
                  <tr key={s.id} data-schedule-id={s.id}>
                    <td>{s.name}</td>
                    <td>
                      {word(TYPE_KEYS, s.report_type)}
                      <div className="hint">{s.period === "previous_month" ? t("gui_reports_period_previous_month")
                        : t("gui_reports_days", { n: String(s.lookback_days) })}</div>
                      <FilterSummary value={s.filter} />
                    </td>
                    <td>{when(s)}{s.email && <div className="hint">{t("gui_reports_email")}</div>}</td>
                    <td>{item.next_run ? formatTime(item.next_run, lang) : t("gui_reports_disabled")}</td>
                    <td>
                      {item.last_status ? (
                        <Link to={`/reports?id=${item.last_report_id ?? ""}`}>
                          <span className="badge" data-tone={STATUS_TONES[item.last_status]}>{word(STATUS_KEYS, item.last_status)}</span>
                        </Link>
                      ) : t("gui_reports_never_run")}
                      {item.consecutive_failures > 1 && (
                        <div className="hint">{t("gui_reports_failures", { n: String(item.consecutive_failures) })}</div>
                      )}
                    </td>
                    <td><Switch label={t("gui_reports_enabled")} name="schedule_enabled" checked={s.enabled} disabled={editing !== null}
                      onChange={() => toggle(item)} /></td>
                    <td className="nowrap">
                      {deleting === s.id ? <>
                        <button type="button" className="btn-danger" data-role="schedule-delete-confirm" disabled={editing !== null || busy} aria-busy={busy || undefined}
                          onClick={() => void remove(s.id)}>{t("btn_confirm")}</button>
                        <button type="button" className="btn-quiet" onClick={() => setDeleting(null)}>{t("btn_cancel")}</button>
                      </> : <>
                        <button type="button" className="btn-quiet" disabled={editing !== null || busy} aria-busy={busy || undefined} onClick={() => void runNow(s.id)}>{t("gui_reports_run_now")}</button>
                        <button type="button" className="btn-quiet" disabled={editing !== null} onClick={() => { const { id, ...fields } = s; setDeleting(null); setEditing({ id, fields }); }}>{t("btn_edit")}</button>
                        <button type="button" className="btn-danger" disabled={editing !== null} onClick={() => setDeleting(s.id)}>{t("gui_reports_delete")}</button>
                      </>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
