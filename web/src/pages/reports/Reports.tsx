import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { Catalog, CatalogEntry, ReportItem, ReportPage } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import {
  EMAIL_KEYS,
  GROUP_KEYS,
  GROUP_ORDER,
  lookbackChoices,
  STATUS_KEYS,
  STATUS_TONES,
  TYPE_DESC_KEYS,
  TYPE_KEYS,
  periodText,
  word,
} from "./common";
import { type FilterRow, ReportFilter, conditionOf, namesApp } from "./ReportFilter";
import { Schedules } from "./Schedules";

const POLL_MS = 5000;

function GenerateForm({ entry, catalog, onDone }: { entry: CatalogEntry; catalog: Catalog; onDone: () => void }) {
  const choices = lookbackChoices(entry.max_lookback);
  const [days, setDays] = useState(choices.includes("7") ? "7" : (choices[choices.length - 1] ?? "1"));
  const [rows, setRows] = useState<FilterRow[]>(entry.requires_app ? [{ side: "dst", key: "app", value: "" }] : []);
  const [lang, setLang] = useState("");
  // The formats this type makes, all on by default (policy_resolver: JSON and CSV only).
  const [formats, setFormats] = useState<CatalogEntry["formats"]>(entry.formats);
  const [email, setEmail] = useState(false);
  const [recipients, setRecipients] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    const env = await call("reports.generate", {
      report_type: entry.report_type,
      lookback_days: Number(days),
      filter: entry.accepts_filter ? conditionOf(rows) : null,
      lang: lang === "" ? null : (lang as "en" | "zh_TW"),
      formats,
      email,
      recipients: recipients.split(/[\s,;]+/).filter((r) => r !== ""),
    });
    setBusy(false);
    if (env.ok) {
      setError(null);
      onDone();
    } else setError(env.error);
  }

  return (
    <div className="stack" data-role="generate-form">
      <div className="row">
        <label>
          {t("gui_reports_lookback")}
          <select name="lookback_days" value={days} onChange={(e) => setDays(e.target.value)}>
            {choices.map((d) => <option key={d} value={d}>{t("gui_reports_days", { n: d })}</option>)}
          </select>
        </label>
        <label>
          {t("gui_reports_language")}
          <select name="lang" value={lang} onChange={(e) => setLang(e.target.value)}>
            <option value="">{t("gui_reports_language_display")}</option>
            <option value="zh_TW">{t("gui_reports_language_zh")}</option>
            <option value="en">{t("gui_reports_language_en")}</option>
          </select>
        </label>
        {entry.formats.map((f) => (
          <label key={f}>
            <input type="checkbox" name={f} checked={formats.includes(f)}
              onChange={(e) => setFormats(e.target.checked ? entry.formats.filter((x) => x === f || formats.includes(x))
                : formats.filter((x) => x !== f))} /> {f.toUpperCase()}
          </label>
        ))}
      </div>
      <div className="row">
        <label>
          <input type="checkbox" name="email" checked={email} disabled={!catalog.smtp_enabled}
            onChange={(e) => setEmail(e.target.checked)} /> {t("gui_reports_email")}
        </label>
        {!catalog.smtp_enabled && (
          <span className="hint">{t("gui_reports_email_needs_smtp")} <Link to="/system/channels">{t("gui_reports_channels_link")}</Link></span>
        )}
        {email && (
          <label>
            {t("gui_reports_recipients")}
            <input name="recipients" value={recipients} placeholder={t("gui_reports_recipients_hint")}
              onChange={(e) => setRecipients(e.target.value)} />
          </label>
        )}
      </div>
      {entry.accepts_filter && (
        <ReportFilter choices={catalog.label_choices} rows={rows} onChange={setRows} requireApp={entry.requires_app} />
      )}
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      <div className="actions">
        <button type="button" className="btn-primary"
          disabled={busy || formats.length === 0 || (entry.requires_app && !namesApp(rows))} onClick={() => void submit()}>
          {t("gui_reports_generate")}
        </button>
      </div>
    </div>
  );
}

function CatalogView({ catalog, onGenerated }: { catalog: Catalog; onGenerated: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const groups = GROUP_ORDER.filter((g) => catalog.entries.some((e) => e.group === g));
  return (
    <div className="stack" data-role="report-catalog">
      {groups.map((g) => (
        <div key={g} className="card stack">
          <h2>{word(GROUP_KEYS, g)}</h2>
          {catalog.entries.filter((e) => e.group === g).map((e) => (
            <div key={e.report_type} className="stack" data-report-type={e.report_type} data-available={String(e.available)}>
              <div className="row spaced">
                <div>
                  <strong>{word(TYPE_KEYS, e.report_type)}</strong>
                  <div className="hint">{word(TYPE_DESC_KEYS, e.report_type)}</div>
                  {!e.available && e.reason_key && (
                    <div className="notice" data-role="unavailable">
                      {t(e.reason_key)}{" "}
                      {e.report_type === "rule_hit_count"
                        ? <Link to="/system/reports">{t("nav_system_reports")}</Link>
                        : <Link to="/system/collection">{t("gui_reports_collection_link")}</Link>}
                    </div>
                  )}
                </div>
                <button type="button" className="btn-quiet" disabled={!e.available}
                  onClick={() => setOpen(open === e.report_type ? null : e.report_type)}>
                  {t("gui_reports_generate_open")}
                </button>
              </div>
              {open === e.report_type && (
                <GenerateForm entry={e} catalog={catalog} onDone={() => { setOpen(null); onGenerated(); }} />
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function History({ data, highlight, onChanged }: { data: ReportPage; highlight: number | null; onChanged: () => void }) {
  const lang = useLang();
  const marked = useRef<HTMLTableRowElement | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    marked.current?.scrollIntoView({ block: "center" });
  }, [highlight, data]);

  async function remove(id: number) {
    const env = await call("reports.delete", undefined, { report_id: String(id) });
    if (env.ok) {
      setError(null);
      onChanged();
    } else setError(env.error);
  }

  if (data.items.length === 0) return <p className="muted">{t("gui_reports_none")}</p>;
  return (
    <>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      <div className="table-wrap">
        <table className="table" data-role="report-list">
          <thead>
            <tr>
              <th>{t("gui_reports_col_report")}</th><th>{t("gui_reports_col_period")}</th>
              <th>{t("gui_reports_col_trigger")}</th><th>{t("gui_reports_col_status")}</th>
              <th>{t("gui_reports_col_files")}</th><th>{t("gui_reports_col_email")}</th><th />
            </tr>
          </thead>
          <tbody>
            {data.items.map((r: ReportItem) => (
              <tr key={r.id} data-report-id={r.id} data-status={r.status} data-highlight={r.id === highlight ? "true" : undefined}
                ref={r.id === highlight ? marked : undefined} className={r.id === highlight ? "notice" : undefined}>
                <td>
                  {word(TYPE_KEYS, r.report_type)}
                  <div className="hint">{r.pce_label}</div>
                </td>
                <td className="nowrap">{periodText(r.period_start, r.period_end, lang)}</td>
                <td>
                  {r.trigger === "schedule" ? (r.schedule_name ?? t("gui_reports_schedule_deleted")) : t("gui_reports_trigger_manual")}
                  <div className="hint">{formatTime(r.created_at, lang)}</div>
                </td>
                <td>
                  <span className="badge" data-tone={STATUS_TONES[r.status]}>{word(STATUS_KEYS, r.status)}</span>
                  {r.error_key && <div className="hint">{t(r.error_key)}</div>}
                  {r.error_detail && <div className="hint mono">{r.error_detail}</div>}
                </td>
                <td>
                  {r.files.map((f) => (
                    <div key={f}><a href={`/reports/files/${r.id}/${encodeURIComponent(f)}`} download>{f.split(".").pop()?.toUpperCase()}</a></div>
                  ))}
                </td>
                <td>
                  {r.email_status ? word(EMAIL_KEYS, r.email_status) : ""}
                  {r.email_detail && <div className="hint mono">{r.email_detail}</div>}
                </td>
                <td>
                  <button type="button" className="btn-quiet" disabled={r.status === "running"}
                    onClick={() => void remove(r.id)}>{t("gui_reports_delete")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function Reports() {
  const [params, setParams] = useSearchParams();
  const highlight = params.get("id") ? Number(params.get("id")) : null;
  const tab = params.get("tab") === "schedules" ? "schedules" : "reports";
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ReportPage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [linked, setLinked] = useState<ReportItem | null>(null);

  const load = useCallback(async () => {
    const [cat, list] = await Promise.all([call("reports.catalog"), call("reports.list", undefined, undefined, { page: String(page) })]);
    if (cat.ok && cat.data) setCatalog(cat.data);
    if (list.ok && list.data) {
      setData(list.data);
      setError(null);
    } else setError(list.error ?? cat.error);
  }, [page]);

  useEffect(() => { void load(); }, [load]);
  // An email link names one report: show it even when it is not on this page of the list.
  useEffect(() => {
    if (highlight === null || !data || data.items.some((r) => r.id === highlight)) {
      setLinked(null);
      return;
    }
    void call("reports.get", undefined, { report_id: String(highlight) }).then((env) => {
      if (env.ok && env.data) setLinked(env.data);
      else setError(env.error);
    });
  }, [highlight, data]);
  const busy = data?.items.some((r) => r.status === "queued" || r.status === "running" || r.email_status === "sending") ?? false;
  useEffect(() => {
    if (!busy) return undefined;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, load]);

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <section className="page stack">
      <div className="page-head">
        <h1>{t("nav_reports")}</h1>
      </div>
      <div className="row" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "reports"} className={tab === "reports" ? "btn-primary" : "btn-quiet"}
          onClick={() => setParams({})}>{t("gui_reports_tab_reports")}</button>
        <button type="button" role="tab" aria-selected={tab === "schedules"} className={tab === "schedules" ? "btn-primary" : "btn-quiet"}
          onClick={() => setParams({ tab: "schedules" })}>{t("gui_reports_tab_schedules")}</button>
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {tab === "schedules" ? (
        catalog && <Schedules catalog={catalog} />
      ) : (
        <>
          {catalog && <CatalogView catalog={catalog} onGenerated={() => { setPage(1); void load(); }} />}
          <h2>{t("gui_reports_history")}</h2>
          {data && (
            <History data={linked ? { ...data, items: [linked, ...data.items] } : data} highlight={highlight}
              onChanged={() => void load()} />
          )}
          {pages > 1 && (
            <div className="row">
              <button type="button" className="btn-quiet" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("page_prev")}</button>
              <span className="hint">{t("page_of", { page: String(page), pages: String(pages) })}</span>
              <button type="button" className="btn-quiet" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("page_next")}</button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

registerNav({ section: "main", path: "/reports", labelKey: "nav_reports", order: 20, component: Reports });
