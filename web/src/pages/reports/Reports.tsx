import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { BulkDeleted, Catalog, CatalogEntry, FlowCondition, ReportItem, ReportPage } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { ModeMark, PageHead, Tag } from "../../components/ui";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import {
  EMAIL_KEYS,
  lookbackChoices,
  STATUS_KEYS,
  STATUS_TONES,
  TYPE_DESC_KEYS,
  TYPE_KEYS,
  periodText,
  word,
} from "./common";
import { ReportFilter, forgetChoices, namesApp } from "./ReportFilter";
import { CustomReports } from "./CustomReports";
import { Schedules } from "./Schedules";
import { ReportSettings } from "../system/ReportSettings";

const POLL_MS = 5000;
type Tab = "templates" | "schedules" | "produced";

function GenerateForm({ entry, catalog, onDone, customId }: {
  entry: CatalogEntry; catalog: Catalog; onDone: () => void; customId?: number;
}) {
  const choices = lookbackChoices(entry.max_lookback);
  // A named period: whole days from the first the data reaches (the archive's, when it goes further back) to yesterday.
  const datesOffered = entry.earliest_day != null && (entry.max_lookback == null || entry.max_lookback > 1);
  const [days, setDays] = useState(choices.includes("7") ? "7" : (choices[choices.length - 1] ?? "1"));
  const [from, setFrom] = useState("");
  const [to, setTo] = useState(entry.latest_day);
  const [filter, setFilter] = useState<FlowCondition | null>(null);
  const [filterValid, setFilterValid] = useState(true);
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
      ...(days === "custom" ? { period_from: from, period_to: to } : { lookback_days: Number(days) }),
      filter: entry.accepts_filter ? filter : null,
      lang: lang === "" ? null : (lang as "en" | "zh_TW"),
      formats,
      email,
      recipients: recipients.split(/[\s,;]+/).filter((r) => r !== ""),
      custom_id: customId ?? null,
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
            {datesOffered && <option value="custom">{t("gui_reports_custom_period")}</option>}
          </select>
        </label>
        {days === "custom" && (
          <>
            <label>
              {t("gui_reports_period_from")}
              <input type="date" name="period_from" value={from} min={entry.earliest_day ?? undefined}
                     max={to || entry.latest_day} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label>
              {t("gui_reports_period_to")}
              <input type="date" name="period_to" value={to} min={from || entry.earliest_day || undefined}
                     max={entry.latest_day} onChange={(e) => setTo(e.target.value)} />
            </label>
          </>
        )}
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
      {days === "custom" && (
        <p className="hint" data-role="period-hint">
          {t("gui_reports_period_hint", { first: entry.earliest_day ?? "", last: entry.latest_day })}
        </p>
      )}
      {entry.accepts_filter && (
        <ReportFilter value={filter} onChange={setFilter} requireApp={entry.requires_app} onValid={setFilterValid} />
      )}
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      <div className="actions">
        <button type="button" className="btn-primary"
          disabled={busy || formats.length === 0 || !filterValid || (entry.requires_app && !namesApp(filter))
            || (days === "custom" && (from === "" || to === ""))} onClick={() => void submit()}>
          {t("gui_reports_generate")}
        </button>
      </div>
    </div>
  );
}

const UI_GROUPS = ["assessment", "traffic", "policy", "operations"] as const;
const UI_GROUP_KEYS: Record<string, string> = {
  assessment: "rpt_group_assessment", traffic: "rpt_group_traffic", policy: "rpt_group_policy",
  operations: "rpt_group_operations",
};

/** Templates by the four columns of sample 07: each card says what basic mode means for it (§5), how many schedules
 * make it and how many copies are kept. */
function CatalogView({ catalog, onGenerated }: { catalog: Catalog; onGenerated: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="rpt-columns" data-role="report-catalog">
      {UI_GROUPS.filter((g) => catalog.entries.some((e) => e.ui_group === g)).map((g) => (
        <div key={g} className="stack rpt-column">
          <h2>{word(UI_GROUP_KEYS, g)}</h2>
          {catalog.entries.filter((e) => e.ui_group === g).map((e) => (
            <div key={e.report_type} className="card stack rpt-card" data-report-type={e.report_type}
                 data-available={String(e.available)}>
              <div>
                <strong>{word(TYPE_KEYS, e.report_type)}</strong>
                <div className="hint">{word(TYPE_DESC_KEYS, e.report_type)}</div>
              </div>
              <div className="row">
                {e.mode === "on_demand"
                  ? <Tag tone="muted" title={t("rpt_mode_on_demand_hint")}>● {t("rpt_mode_on_demand")}</Tag>
                  : <ModeMark needs="basic" />}
                <span className="hint" data-role="rpt-counts">
                  {t("rpt_card_counts", { schedules: String(e.schedules), copies: String(e.copies) })}
                </span>
              </div>
              {!e.available && e.reason_key && (
                <div className="notice" data-role="unavailable">
                  {t(e.reason_key)}{" "}
                  {e.report_type === "rule_hit_count"
                    ? <Link to="/reports?tab=schedules">{t("nav_system_reports")}</Link>
                    : <Link to="/system/collection">{t("gui_reports_collection_link")}</Link>}
                </div>
              )}
              {e.report_type !== "custom" && (
                <div className="row">
                  <button type="button" className="btn-quiet" disabled={!e.available}
                    onClick={() => setOpen(open === e.report_type ? null : e.report_type)}>
                    {t("gui_reports_generate_open")}
                  </button>
                  <Link to="/reports?tab=schedules" className="btn-quiet">{t("rpt_schedule_link")}</Link>
                </div>
              )}
              {e.report_type === "custom" && (
                <CustomReports generate={(customId, done) => (
                  <GenerateForm entry={e} catalog={catalog} customId={customId} onDone={() => { done(); onGenerated(); }} />
                )} />
              )}
              {open === e.report_type && e.report_type !== "custom" && (
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
  // Several reports deleted at once (5.x bulk delete): picked on this page, confirmed, then what happened to each said.
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [outcome, setOutcome] = useState<BulkDeleted | null>(null);
  useEffect(() => {
    marked.current?.scrollIntoView({ block: "center" });
  }, [highlight, data]);
  // a report that left the list (deleted, another page) is no longer picked
  useEffect(() => {
    setPicked((now) => new Set([...now].filter((id) => data.items.some((r) => r.id === id && r.status !== "running"))));
  }, [data]);

  async function remove(id: number) {
    const env = await call("reports.delete", undefined, { report_id: String(id) });
    if (env.ok) {
      setError(null);
      onChanged();
    } else setError(env.error);
  }

  async function removePicked() {
    setConfirming(false);
    const [first, ...rest] = [...picked];
    if (first === undefined) return;
    const env = await call("reports.bulk_delete", { ids: [first, ...rest] });
    if (env.ok && env.data) {
      setError(null);
      setOutcome(env.data);
      setPicked(new Set());
      onChanged();
    } else setError(env.error);
  }

  const pickable = data.items.filter((r) => r.status !== "running");
  const toggle = (id: number, on: boolean) => {
    const next = new Set(picked);
    if (on) next.add(id); else next.delete(id);
    setPicked(next);
    setConfirming(false);
  };

  if (data.items.length === 0) return <p className="muted">{t("gui_reports_none")}</p>;
  return (
    <>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      <div className="row" data-role="bulk-actions">
        {confirming ? (
          <>
            <span>{t("gui_reports_delete_confirm", { n: String(picked.size) })}</span>
            <button type="button" className="btn-danger" data-role="bulk-delete-confirm" onClick={() => void removePicked()}>
              {t("gui_reports_delete")}
            </button>
            <button type="button" className="btn-quiet" onClick={() => setConfirming(false)}>{t("btn_cancel")}</button>
          </>
        ) : (
          <button type="button" className="btn-quiet" data-role="bulk-delete" disabled={picked.size === 0}
            onClick={() => { setOutcome(null); setConfirming(true); }}>
            {t("gui_reports_delete_selected", { n: String(picked.size) })}
          </button>
        )}
        {outcome && (
          <span className="hint" data-role="bulk-outcome">{t("gui_reports_bulk_result", {
            removed: String(outcome.removed.length), running: String(outcome.running.length),
            missing: String(outcome.missing.length) })}</span>
        )}
      </div>
      <div className="table-wrap">
        <table className="table" data-role="report-list">
          <thead>
            <tr>
              <th>
                <input type="checkbox" name="pick-all" aria-label={t("gui_reports_select_all")}
                  checked={pickable.length > 0 && pickable.every((r) => picked.has(r.id))} disabled={pickable.length === 0}
                  onChange={(e) => { setPicked(new Set(e.target.checked ? pickable.map((r) => r.id) : [])); setConfirming(false); }} />
              </th>
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
                  <input type="checkbox" name={`pick-${r.id}`} aria-label={t("gui_reports_select_one")}
                    checked={picked.has(r.id)} disabled={r.status === "running"}
                    onChange={(e) => toggle(r.id, e.target.checked)} />
                </td>
                <td>
                  <div data-role="report-conclusion">{r.conclusion || `${word(TYPE_KEYS, r.report_type)}${r.custom_name ? `：${r.custom_name}` : ""}`}</div>
                  <div className="hint">{word(TYPE_KEYS, r.report_type)}{r.custom_name ? `：${r.custom_name}` : ""} · {r.pce_label}</div>
                </td>
                <td className="nowrap">{periodText(r.period_start, r.period_end, lang)}</td>
                <td>
                  {r.trigger === "schedule" ? (r.schedule_name ?? t("gui_reports_schedule_deleted")) : t("gui_reports_trigger_manual")}
                  <div className="hint">{formatTime(r.created_at, lang)}</div>
                </td>
                <td>
                  <span className="badge" data-tone={STATUS_TONES[r.status]}>{word(STATUS_KEYS, r.status)}</span>
                  {r.error_key && <div className="hint">{t(r.error_key)}</div>}
                  {r.error_detail && <div className="hint">{r.error_detail}</div>}
                </td>
                <td>
                  {r.files.map((f) => (
                    <div key={f}>
                      <a href={`/reports/files/${r.id}/${encodeURIComponent(f)}`} download>{f.split(".").pop()?.toUpperCase()}</a>
                      {f.toLowerCase().endsWith(".html") && (
                        <>
                          {" · "}
                          <a href={`/reports/view/${r.id}/${encodeURIComponent(f)}`} target="_blank" rel="noopener noreferrer"
                            data-role="report-open" title={t("gui_reports_open_hint")}>{t("gui_reports_open")}</a>
                        </>
                      )}
                    </div>
                  ))}
                </td>
                <td>
                  {r.email_status ? word(EMAIL_KEYS, r.email_status) : ""}
                  {r.email_detail && <div className="hint">{r.email_detail}</div>}
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
  // The PCE may have been switched since this page was last open: read the choices again. In the first render (a
  // lazy state initializer), before the forms' own effects read them.
  useState(() => { forgetChoices(); return null; });
  const highlight = params.get("id") ? Number(params.get("id")) : null;
  const raw = params.get("tab");
  // An email link names a report (?id=): it opens on the produced list
  const tab: Tab = raw === "schedules" ? "schedules" : raw === "produced" || params.get("id") ? "produced" : "templates";
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
  const list = data && (
    <>
      <History data={linked ? { ...data, items: [linked, ...data.items] } : data} highlight={highlight}
        onChanged={() => void load()} />
      {pages > 1 && (
        <div className="row">
          <button type="button" className="btn-quiet" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("page_prev")}</button>
          <span className="hint">{t("page_of", { page: String(page), pages: String(pages) })}</span>
          <button type="button" className="btn-quiet" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("page_next")}</button>
        </div>
      )}
    </>
  );
  const tabButton = (id: Tab, key: string) => (
    <button type="button" role="tab" aria-selected={tab === id} aria-pressed={tab === id} className="chip-btn" data-tab={id}
      onClick={() => setParams(id === "templates" ? {} : { tab: id })}>{t(key)}</button>
  );
  return (
    <section className="page stack" data-role="reports-page">
      <PageHead title={t("nav_reports")} sub={t("rpt_page_sub")} />
      <div className="chips-row tabs" role="tablist">
        {tabButton("templates", "rpt_tab_templates")}
        {tabButton("schedules", "gui_reports_tab_schedules")}
        {tabButton("produced", "rpt_tab_produced")}
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {tab === "schedules" && (
        <>
          {catalog && <Schedules catalog={catalog} />}
          <ReportSettings embedded />
        </>
      )}
      {tab === "templates" && (
        <>
          {catalog && <CatalogView catalog={catalog} onGenerated={() => { setPage(1); void load(); }} />}
          <h2>{t("rpt_recent")}</h2>
          {list}
        </>
      )}
      {tab === "produced" && list}
    </section>
  );
}

registerNav({ section: "output", path: "/reports", labelKey: "nav_reports", order: 20, component: Reports });
