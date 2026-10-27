import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { Catalog, ReportScheduleFields, SchedulesView, ScheduleItem } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { STATUS_KEYS, STATUS_TONES, TYPE_KEYS, lookbackChoices, word } from "./common";
import { type FilterRow, ReportFilter, conditionOf, namesApp, rowsOf } from "./ReportFilter";

const WEEKDAY_KEYS = ["weekday_mon", "weekday_tue", "weekday_wed", "weekday_thu", "weekday_fri", "weekday_sat",
  "weekday_sun"];
const FREQUENCY_KEYS: Record<string, string> = {
  daily: "gui_reports_freq_daily", weekly: "gui_reports_freq_weekly", monthly: "gui_reports_freq_monthly",
};

function blank(type: string): ReportScheduleFields {
  return {
    name: "", enabled: true, report_type: type as ReportScheduleFields["report_type"], lookback_days: 7,
    frequency: "weekly", day_of_week: 0, day_of_month: null, hour: 8, minute: 0, formats: ["html", "xlsx"],
    email: false, recipients: [], lang: null, keep: 30, filter: null,
  };
}

function when(s: ReportScheduleFields): string {
  const time = `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`;
  if (s.frequency === "weekly") return t("gui_reports_when_weekly", { day: t(WEEKDAY_KEYS[s.day_of_week ?? 0] ?? "weekday_mon"), time });
  if (s.frequency === "monthly") return t("gui_reports_when_monthly", { day: String(s.day_of_month ?? 1), time });
  return t("gui_reports_when_daily", { time });
}

function Editor({ initial, catalog, smtp, onSave, onCancel, error }: {
  initial: ReportScheduleFields; catalog: Catalog; smtp: boolean; error: ApiError | null;
  onSave: (s: ReportScheduleFields) => void; onCancel: () => void;
}) {
  const [s, setS] = useState<ReportScheduleFields>(initial);
  const [recipients, setRecipients] = useState(initial.recipients.join(", "));
  const [rows, setRows] = useState<FilterRow[]>(rowsOf(initial.filter));
  const entry = catalog.entries.find((c) => c.report_type === s.report_type);
  const set = (patch: Partial<ReportScheduleFields>) => setS({ ...s, ...patch });
  const freq = (f: ReportScheduleFields["frequency"]) => set({
    frequency: f, day_of_week: f === "weekly" ? (s.day_of_week ?? 0) : null,
    day_of_month: f === "monthly" ? (s.day_of_month ?? 1) : null,
  });
  const toggleFormat = (f: "html" | "xlsx", on: boolean) =>
    // An empty list is sent as is: the server refuses it and names the field.
    set({ formats: (on ? [...new Set([...s.formats, f])] : s.formats.filter((x) => x !== f)) as ReportScheduleFields["formats"] });
  return (
    <div className="card form-grid" data-role="schedule-editor">
      <label>
        {t("gui_reports_sched_name")}
        <input name="name" value={s.name} maxLength={80} onChange={(e) => set({ name: e.target.value })} />
      </label>
      <label>
        {t("gui_reports_col_report")}
        <select name="report_type" value={s.report_type}
          onChange={(e) => {
            const next = catalog.entries.find((c) => c.report_type === e.target.value);
            set({ report_type: e.target.value as ReportScheduleFields["report_type"] });
            if (next?.requires_app && !namesApp(rows)) setRows([...rows, { side: "dst", key: "app", value: "" }]);
          }}>
          {catalog.entries.map((c) => <option key={c.report_type} value={c.report_type}>{word(TYPE_KEYS, c.report_type)}</option>)}
        </select>
      </label>
      <label>
        {t("gui_reports_lookback")}
        <select name="lookback_days" value={String(s.lookback_days)} onChange={(e) => set({ lookback_days: Number(e.target.value) })}>
          {lookbackChoices(entry?.max_lookback).map((d) => <option key={d} value={d}>{t("gui_reports_days", { n: d })}</option>)}
        </select>
      </label>
      <label>
        {t("gui_reports_frequency")}
        <select name="frequency" value={s.frequency} onChange={(e) => freq(e.target.value as ReportScheduleFields["frequency"])}>
          {Object.keys(FREQUENCY_KEYS).map((f) => <option key={f} value={f}>{word(FREQUENCY_KEYS, f)}</option>)}
        </select>
      </label>
      {s.frequency === "weekly" && (
        <label>
          {t("gui_reports_day_of_week")}
          <select name="day_of_week" value={String(s.day_of_week ?? 0)} onChange={(e) => set({ day_of_week: Number(e.target.value) })}>
            {WEEKDAY_KEYS.map((k, i) => <option key={k} value={i}>{t(k)}</option>)}
          </select>
        </label>
      )}
      {s.frequency === "monthly" && (
        <label>
          {t("gui_reports_day_of_month")}
          <input name="day_of_month" type="number" min={1} max={31} value={s.day_of_month ?? 1}
            onChange={(e) => set({ day_of_month: Number(e.target.value) })} />
          <span className="hint">{t("gui_reports_day_of_month_hint")}</span>
        </label>
      )}
      <label>
        {t("gui_reports_time")}
        <input name="time" type="time" value={`${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`}
          onChange={(e) => { const [h, m] = e.target.value.split(":"); set({ hour: Number(h), minute: Number(m) }); }} />
        <span className="hint">{t("gui_reports_time_hint")}</span>
      </label>
      <label>
        {t("gui_reports_language")}
        <select name="lang" value={s.lang ?? ""} onChange={(e) => set({ lang: e.target.value === "" ? null : (e.target.value as "en" | "zh_TW") })}>
          <option value="">{t("gui_reports_language_display")}</option>
          <option value="zh_TW">{t("gui_reports_language_zh")}</option>
          <option value="en">{t("gui_reports_language_en")}</option>
        </select>
      </label>
      <div className="row span-all">
        <label><input type="checkbox" checked={s.formats.includes("html")} onChange={(e) => toggleFormat("html", e.target.checked)} /> HTML</label>
        <label><input type="checkbox" checked={s.formats.includes("xlsx")} onChange={(e) => toggleFormat("xlsx", e.target.checked)} /> XLSX</label>
        <label><input type="checkbox" name="email" checked={s.email} onChange={(e) => set({ email: e.target.checked })} /> {t("gui_reports_email")}</label>
        {s.email && !smtp && (
          <span className="hint">{t("gui_reports_email_needs_smtp")} <Link to="/system/channels">{t("gui_reports_channels_link")}</Link></span>
        )}
      </div>
      {s.email && (
        <label className="span-all">
          {t("gui_reports_recipients")}
          <input name="recipients" value={recipients} placeholder={t("gui_reports_recipients_hint")}
            onChange={(e) => setRecipients(e.target.value)} />
        </label>
      )}
      {entry?.accepts_filter && (
        <ReportFilter choices={catalog.label_choices} rows={rows} onChange={setRows} requireApp={entry.requires_app} />
      )}
      <label>
        {t("gui_reports_keep")}
        <input name="keep" type="number" min={1} max={365} value={s.keep} onChange={(e) => set({ keep: Number(e.target.value) })} />
      </label>
      <label>
        <input type="checkbox" name="enabled" checked={s.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> {t("gui_reports_enabled")}
      </label>
      {error && <p className="form-error span-all">{t(error.message_key, error.params)}{error.field ? ` (${error.field})` : ""}</p>}
      <div className="actions span-all">
        <button type="button" className="btn-primary"
          onClick={() => onSave({ ...s, filter: entry?.accepts_filter ? conditionOf(rows) : null,
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

  const load = useCallback(async () => {
    const env = await call("report_schedules.list");
    if (env.ok && env.data) setView(env.data);
    else setError(env.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function save(fields: ReportScheduleFields) {
    if (!view || !editing) return;
    const env = editing.id
      ? await call("report_schedules.update", { revision: view.revision, schedule: fields }, { schedule_id: editing.id })
      : await call("report_schedules.create", { revision: view.revision, schedule: fields });
    if (env.ok && env.data) {
      setView(env.data);
      setEditing(null);
      setError(null);
    } else setError(env.error);
  }

  async function toggle(item: ScheduleItem) {
    if (!view) return;
    const { id, ...fields } = item.schedule;
    const env = await call("report_schedules.update", { revision: view.revision, schedule: { ...fields, enabled: !fields.enabled } },
      { schedule_id: id });
    if (env.ok && env.data) setView(env.data);
    else setError(env.error);
  }

  async function remove(id: string) {
    if (!view) return;
    const env = await call("report_schedules.delete", { revision: view.revision }, { schedule_id: id });
    if (env.ok && env.data) setView(env.data);
    else setError(env.error);
  }

  async function runNow(id: string) {
    const env = await call("report_schedules.run_now", {}, { schedule_id: id });
    if (env.ok && env.data) navigate(`/reports?id=${env.data.id}`);
    else setError(env.error);
  }

  if (!view) return error ? <p className="form-error">{t(error.message_key, error.params)}</p> : null;
  const first = catalog.entries[0]?.report_type ?? "lateral_posture";
  return (
    <div className="stack" data-role="schedules">
      {!editing && (
        <div className="actions">
          <button type="button" className="btn-primary" onClick={() => setEditing({ id: null, fields: blank(first) })}>
            {t("gui_reports_sched_add")}
          </button>
        </div>
      )}
      {editing && (
        <Editor initial={editing.fields} catalog={catalog} smtp={view.smtp_enabled} error={error}
          onSave={(f) => void save(f)} onCancel={() => { setEditing(null); setError(null); }} />
      )}
      {!editing && error && <p className="form-error">{t(error.message_key, error.params)}</p>}
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
                      {word(TYPE_KEYS, s.report_type)}<div className="hint">{t("gui_reports_days", { n: String(s.lookback_days) })}</div>
                      {rowsOf(s.filter).length > 0 && (
                        <div className="hint" data-role="schedule-filter">
                          {rowsOf(s.filter).map((r) => `${r.key} = ${r.value}`).join(", ")}
                        </div>
                      )}
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
                    <td><input type="checkbox" aria-label={t("gui_reports_enabled")} checked={s.enabled} onChange={() => void toggle(item)} /></td>
                    <td className="nowrap">
                      <button type="button" className="btn-quiet" onClick={() => void runNow(s.id)}>{t("gui_reports_run_now")}</button>
                      <button type="button" className="btn-quiet" onClick={() => { const { id, ...fields } = s; setEditing({ id, fields }); }}>{t("btn_edit")}</button>
                      <button type="button" className="btn-quiet" onClick={() => void remove(s.id)}>{t("gui_reports_delete")}</button>
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
