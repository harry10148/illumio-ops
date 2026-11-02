// The home page: alerts first (UI redesign spec §4.1, sample 01) — the period's counts, the list filtered by kind,
// and the selected alert beside it with its timeline, what the vendor's tools cannot show, and what to do next.
import { useEffect, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { AlertDetail, AlertItem, AlertList as AlertListData } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { DataTable, DetailPane, KpiStrip, PageHead, SeverityTag, Tag, shortTime } from "../../components/ui";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { useBasicMode } from "../../shell/status";
import { QuarantineDialog } from "../quarantine/QuarantineDialog";
import { deliveryText } from "./common";

const PERIODS = ["1", "7", "30"];
type Category = "" | "lateral" | "anomaly" | "traffic" | "event" | "system";
const CATEGORY_KEYS: Record<Exclude<Category, "">, string> = {
  lateral: "alert_cat_lateral", anomaly: "alert_cat_anomaly", traffic: "alert_cat_traffic",
  event: "alert_cat_event", system: "alert_cat_system",
};
// Basic mode collects no traffic: lateral, anomaly and traffic alerts cannot happen there (spec §4.6).
const BASIC_CATEGORIES: Category[] = ["", "event", "system"];
const ALL_CATEGORIES: Category[] = ["", "lateral", "anomaly", "traffic", "event", "system"];
const DELIVERY_TONE: Record<string, "ok" | "crit" | "accum" | "muted" | "high"> = {
  sent: "ok", failed: "crit", pending: "accum", not_notified: "muted", grouped: "muted", no_channel: "high",
};

function categoryWord(c: string): string {
  const key = CATEGORY_KEYS[c as Exclude<Category, "">];
  return key ? t(key) : c;
}

function Deliveries({ item }: { item: AlertItem }) {
  const sent = item.deliveries.filter((d) => d.status === "sent").length;
  const failed = item.deliveries.filter((d) => d.status === "failed");
  if (failed.length > 0) {
    return <span data-delivery="failed"><Tag tone="crit">{t("alerts_delivery_failed", { n: String(failed.length) })}</Tag></span>;
  }
  if (sent > 0) return <span data-delivery="sent"><Tag tone="ok">{t("alerts_delivery_sent", { n: String(sent) })}</Tag></span>;
  const [first] = item.deliveries;
  return first
    ? <span data-delivery={first.status}><Tag tone={DELIVERY_TONE[first.status] ?? "muted"}>{deliveryText(first)}</Tag></span>
    : null;
}

function Side({ id, onKnown }: { id: number; onKnown: () => void }) {
  const lang = useLang();
  const [d, setD] = useState<AlertDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [isolating, setIsolating] = useState(false);

  useEffect(() => {
    let live = true;  // an answer for an alert no longer selected must not replace this one (nor its quarantine target)
    setD(null);
    setIsolating(false);
    void call("alerts.get", undefined, { alert_id: String(id) }).then((env) => {
      if (!live) return;
      if (env.ok && env.data) {
        setD(env.data);
        setError(null);
      } else setError(env.error);
    });
    return () => { live = false; };
  }, [id]);

  if (error) return <p className="form-error">{t(error.message_key, error.params)}</p>;
  if (!d) return <p className="muted">{t("loading")}</p>;
  const q = d.quarantine;
  return (
    <div className="stack alert-side" data-role="alert-side">
      <div className="row">
        <SeverityTag severity={d.severity} />
        <Tag tone="muted">{categoryWord(d.category)}</Tag>
        {d.category !== "event" && d.category !== "system" && <Tag tone="adv">◆ {t("mode_advanced")}</Tag>}
        {d.grouped && <Tag tone="muted">{t("alerts_grouped_tag")}</Tag>}
      </div>
      <h2 className="side-title" data-role="alert-summary">{d.summary}</h2>
      <p className="hint">{d.rule_name} · <span className="mono">{formatTime(d.fired_at, lang)}</span></p>
      {d.caveats.map((c) => <p key={c} className="notice">{c}</p>)}
      <div>
        <h3 className="side-h">{t("alert_timeline_title")}</h3>
        <ol className="timeline" data-role="timeline">
          {d.timeline.map((e, i) => (
            <li key={i} data-kind={e.kind}><span className="mono" title={formatTime(e.at, lang)}>{shortTime(e.at)}</span> {e.text}</li>
          ))}
        </ol>
      </div>
      <div>
        <h3 className="side-h">{t("alert_beyond_title")}</h3>
        {d.beyond_vendor.length === 0
          ? <p className="muted" data-role="beyond-none">{t("alert_beyond_none")}</p>
          : <ul className="plain-list" data-role="beyond">{d.beyond_vendor.map((s) => <li key={s}>{s}</li>)}</ul>}
      </div>
      <div>
        <h3 className="side-h">{t("alert_delivery_title")}</h3>
        <p className="row">{d.deliveries.map((x) => (
          <Tag key={x.channel} tone={DELIVERY_TONE[x.status] ?? "muted"}>{deliveryText(x)}</Tag>
        ))}</p>
      </div>
      <div className="side-actions">
        {d.evidence_kind
          ? <Link className="btn-primary" to={`/investigate?alert=${d.id}`} data-role="open-workbench">{t("alert_start_investigation")}</Link>
          : <span className="hint">{t("alert_no_evidence_to_investigate")}</span>}
        {q.eligible && q.key ? (
          <button type="button" className="btn-quiet" data-role="quarantine" onClick={() => setIsolating(true)}>
            {t("alert_quarantine")}{q.no_enforcement ? ` · ${t("alert_quarantine_no_effect")}` : ""}
          </button>
        ) : (
          <span className="hint" data-role="quarantine-reason">{t(q.reason === "unmanaged" ? "alert_q_unmanaged"
            : q.reason === "not_in_inventory" ? "alert_q_not_in_inventory" : "alert_q_no_subject")}</span>
        )}
        {d.rule_type === "lateral" && !d.grouped && (
          <Link className="btn-quiet" to={`/alerts/${d.id}#mark-known`} onClick={onKnown}>{t("alert_known_mark")}</Link>
        )}
        <Link to={`/alerts/${d.id}`} data-role="open-detail">{t("alert_full_detail")}</Link>
      </div>
      {isolating && q.key && (
        <QuarantineDialog hosts={[{ key: q.key, name: q.name ?? q.key }]} onClose={() => setIsolating(false)} />
      )}
    </div>
  );
}

export function AlertsHome() {
  const lang = useLang();
  const basic = useBasicMode();
  const [days, setDays] = useState("7");
  const [cat, setCat] = useState<Category>("");
  const [unprocessed, setUnprocessed] = useState(true);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AlertListData | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    const query: Record<string, string> = { days, page: String(page) };
    if (cat) query.category = cat;
    if (unprocessed) query.unprocessed = "true";
    void call("alerts.list", undefined, undefined, query).then((env) => {
      if (env.ok && env.data) {
        setData(env.data);
        setError(null);
        setSelected((s) => (s !== null && env.data!.items.some((i) => i.id === s) ? s : env.data!.items[0]?.id ?? null));
      } else setError(env.error);
    });
  }, [days, cat, unprocessed, page]);

  const c = data?.counts;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const categories = basic ? BASIC_CATEGORIES : ALL_CATEGORIES;
  return (
    <section className="page" data-role="alerts-home">
      <PageHead title={t("nav_alerts")} sub={t("alerts_home_sub", { n: days })}>
        <label className="inline-label">
          {t("alerts_period")}
          <select name="days" value={days} onChange={(e) => { setDays(e.target.value); setPage(1); }}>
            {PERIODS.map((d) => <option key={d} value={d}>{t("alerts_period_days", { n: d })}</option>)}
          </select>
        </label>
      </PageHead>
      {basic && (
        <div className="needs-advanced" data-role="basic-mode-box">
          <p><Tag tone="ok">● {t("mode_basic")}</Tag> {t("home_basic_now")}</p>
          <p><Tag tone="adv">◆ {t("mode_advanced")}</Tag> {t("home_basic_advanced_adds")}</p>
          <p className="hint">{t("home_basic_investigate")}</p>
          <Link to="/system/collection">{t("needs_advanced_link")}</Link>
        </div>
      )}
      <KpiStrip items={[
        { key: "critical", label: t("severity_critical"), value: c ? c.critical : null, tone: "crit" },
        { key: "high", label: t("severity_high"), value: c ? c.high : null, tone: "high" },
        { key: "medium", label: t("severity_medium"), value: c ? c.medium : null, tone: "med" },
        { key: "low", label: t("severity_low"), value: c ? c.low : null },
        { key: "grouped", label: t("alerts_kpi_grouped"), value: c ? c.grouped : null },
      ]} />
      <div className="filter-bar" data-role="alert-filters">
        <div className="chips-row" role="group" aria-label={t("alerts_type")}>
          {categories.map((k) => (
            <button key={k || "all"} type="button" className="chip-btn" aria-pressed={cat === k}
                    data-category={k || "all"} onClick={() => { setCat(k); setPage(1); }}>
              {k ? categoryWord(k) : t("alerts_all")}
            </button>
          ))}
        </div>
        <label className="check">
          <input type="checkbox" name="unprocessed" checked={unprocessed}
                 onChange={(e) => { setUnprocessed(e.target.checked); setPage(1); }} />
          {t("alerts_only_unprocessed")}
        </label>
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {data && (
        <div className="split">
          <div className="stack">
            <p className="hint" data-role="alert-total">{t("alerts_total", { n: String(data.total) })}</p>
            <div data-role="alert-list">
              <DataTable<AlertItem>
                rows={data.items}
                rowKey={(a) => String(a.id)}
                selected={selected === null ? null : String(selected)}
                onRowClick={(a) => setSelected(a.id)}
                empty={unprocessed ? t("alerts_none_unprocessed") : t("alerts_none")}
                columns={[
                  { key: "time", label: t("alerts_col_time"), kind: "mono", render: (a) => <span title={formatTime(a.fired_at, lang)}>{shortTime(a.fired_at)}</span> },
                  { key: "sev", label: t("alerts_col_severity"), render: (a) => <SeverityTag severity={a.severity} /> },
                  { key: "title", label: t("alerts_col_alert"), render: (a) => (
                    <div data-alert-id={a.id}>
                      <div>{a.summary}</div>
                      <div className="hint">{categoryWord(a.category)} · {a.rule_name}</div>
                    </div>
                  ) },
                  { key: "ends", label: t("alerts_col_ends"), kind: "mono",
                    render: (a) => (a.src || a.dst ? `${a.src ?? "—"} → ${a.dst ?? "—"}` : "—") },
                  { key: "delivery", label: t("alerts_col_delivery"), render: (a) => <Deliveries item={a} /> },
                ]}
              />
            </div>
            {pages > 1 && (
              <div className="row">
                <button type="button" className="btn-quiet" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("page_prev")}</button>
                <span className="hint">{t("page_of", { page: String(page), pages: String(pages) })}</span>
                <button type="button" className="btn-quiet" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("page_next")}</button>
              </div>
            )}
          </div>
          {selected !== null && (
            <DetailPane label={t("alert_detail_title")}>
              <Side key={selected} id={selected} onKnown={() => undefined} />
            </DetailPane>
          )}
        </div>
      )}
    </section>
  );
}

/** Bookmarks of the old list page land on the home page with their filters. */
function AlertsRedirect() {
  const { search } = useLocation();
  return <Navigate to={`/${search}`} replace />;
}

registerNav({ section: "main", path: "/", labelKey: "nav_alerts", order: 10, component: AlertsHome, badge: "unprocessed" });
registerNav({ section: "main", path: "/alerts", labelKey: "nav_alerts", order: 10, component: AlertsRedirect, hidden: true });
