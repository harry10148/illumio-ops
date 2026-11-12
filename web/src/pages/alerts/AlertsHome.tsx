// The home page: alerts first (UI redesign spec §4.1, sample 01) — the period's counts, the list filtered by kind,
// and the selected alert beside it with its timeline, what the vendor's tools cannot show, and what to do next.
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { AlertDetail, AlertItem, AlertList as AlertListData } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { DataTable, DetailPane, KpiStrip, PageHead, Segmented, SeverityTag, Tag, shortTime } from "../../components/ui";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { notifyShellStatus, useBasicMode } from "../../shell/status";
import { AlertBody, AlertHosts, categoryWord } from "./AlertBody";
import { deliveryText } from "./common";

const PERIODS = ["1", "7", "30"];
type Category = "" | "lateral" | "anomaly" | "traffic" | "event" | "system";
// Basic mode collects no traffic: lateral, anomaly and traffic alerts cannot happen there (spec §4.6).
const BASIC_CATEGORIES: Category[] = ["", "event", "system"];
const ALL_CATEGORIES: Category[] = ["", "lateral", "anomaly", "traffic", "event", "system"];
const DELIVERY_TONE: Record<string, "ok" | "crit" | "accum" | "muted" | "high"> = {
  sent: "ok", failed: "crit", pending: "accum", not_notified: "muted", grouped: "muted", no_channel: "high",
};

/** What the period's alerts come to, from the counts the list came with: only the levels that have any. */
function conclusion(data: AlertListData, days: string): string {
  const c = data.counts;
  const levels = ([["severity_critical", c.critical], ["severity_high", c.high], ["severity_medium", c.medium],
                   ["severity_low", c.low]] as [string, number][]).filter(([, n]) => n > 0);
  const total = levels.reduce((sum, [, n]) => sum + n, 0);
  if (total === 0) return t("alerts_conclusion_none", { days });
  const said = t("alerts_conclusion", { days, n: String(total), levels: levels
    .map(([key, n]) => t("alerts_level_count", { level: t(key), n: String(n) })).join(t("list_separator")) });
  return data.new > 0 ? `${said} ${t("alerts_conclusion_new", { k: String(data.new) })}` : said;
}

function Deliveries({ item }: { item: AlertItem }) {
  const sent = item.deliveries.filter((d) => d.status === "sent").length;
  const failed = item.deliveries.filter((d) => d.status === "failed");
  if (failed.length > 0) {
    return <span data-delivery="failed"><Tag tone="crit">{t("alerts_delivery_failed", { n: String(failed.length) })}</Tag></span>;
  }
  if (sent > 0) return <span data-delivery="sent"><Tag tone="ok">{t("alerts_delivery_sent", { n: String(sent) })}</Tag></span>;
  const [first] = item.deliveries;
  // recorded only is a setting, not an outcome: said in words, not as a tag
  if (first?.status === "not_notified") return <span className="hint" data-delivery="not_notified">{deliveryText(first)}</span>;
  return first
    ? <span data-delivery={first.status}><Tag tone={DELIVERY_TONE[first.status] ?? "muted"}>{deliveryText(first)}</Tag></span>
    : null;
}

function Side({ id }: { id: number }) {
  const [d, setD] = useState<AlertDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let live = true;  // an answer for an alert no longer selected must not replace this one (nor its quarantine target)
    setD(null);
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
  return <div className="alert-side" data-role="alert-side"><AlertBody d={d} full={false} /></div>;
}

export function AlertsHome() {
  const lang = useLang();
  const basic = useBasicMode();
  const [days, setDays] = useState("7");
  const [cat, setCat] = useState<Category>("");
  const [onlyNew, setOnlyNew] = useState(false);
  // ?device=<key>: only the alerts about one host (the host page's "and N more" leads here)
  const [params, setParams] = useSearchParams();
  const device = params.get("device");
  // "New" is measured against when this page was opened BEFORE this visit. Opening it marks everything seen for the
  // next visit and answers that earlier time, which is kept for as long as the page stays open: changing the page,
  // the period or the filter must not age the alerts being looked at.
  const [seenBefore, setSeenBefore] = useState<string | null>(null);
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    void call("alerts.mark_seen").then((env) => {
      setSeenBefore(env.ok && env.data ? env.data.previous : new Date().toISOString());  // unknown: nothing is called new
      notifyShellStatus();
    });
  }, []);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AlertListData | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (seenBefore === null) return;
    const query: Record<string, string> = { days, page: String(page), new_after: seenBefore };
    if (cat) query.category = cat;
    if (onlyNew) query.only_new = "true";
    if (device) query.device = device;
    void call("alerts.list", undefined, undefined, query).then((env) => {
      if (env.ok && env.data) {
        setData(env.data);
        setError(null);
        setSelected((s) => (s !== null && env.data!.items.some((i) => i.id === s) ? s : env.data!.items[0]?.id ?? null));
      } else setError(env.error);
    });
  }, [days, cat, onlyNew, page, seenBefore, device]);

  const c = data?.counts;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const categories = basic ? BASIC_CATEGORIES : ALL_CATEGORIES;
  return (
    <section className="page" data-role="alerts-home">
      <PageHead title={t("nav_alerts")} purpose={t("purpose_alerts")}>
        <label className="inline-label">
          {t("alerts_period")}
          <select name="days" value={days} onChange={(e) => { setDays(e.target.value); setPage(1); }}>
            {PERIODS.map((d) => <option key={d} value={d}>{t("alerts_period_days", { n: d })}</option>)}
          </select>
        </label>
      </PageHead>
      {data && <p className="page-conclusion" data-role="page-conclusion">{conclusion(data, days)}</p>}
      {basic && (
        <div className="needs-advanced" data-role="basic-mode-box">
          <p><Tag tone="muted">● {t("mode_basic")}</Tag> {t("home_basic_now")}</p>
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
      {device && (
        <p className="row" data-role="alert-device-filter">
          <span>{t("alerts_device_filter", { name: data?.items.flatMap((i) => i.devices).find((d) => d.key === device)?.name
            ?? device.replace(/^ip:/, "") })}</span>
          <button type="button" className="btn-text" onClick={() => { setParams({}); setPage(1); }}>{t("alerts_device_clear")}</button>
        </p>
      )}
      <div className="filter-bar" data-role="alert-filters">
        <div className="chips-row" role="group" aria-label={t("alerts_type")}>
          {categories.map((k) => (
            <button key={k || "all"} type="button" className="chip-btn" aria-pressed={cat === k}
                    data-category={k || "all"} onClick={() => { setCat(k); setPage(1); }}>
              {k ? categoryWord(k) : t("alerts_all")}
            </button>
          ))}
        </div>
        <Segmented label={t("alerts_seen_filter")} role="alert-seen" value={onlyNew ? "new" : "all"}
                   options={[{ value: "all", label: t("alerts_all") },
                             { value: "new", label: t("alerts_only_new"), count: data?.new || undefined }]}
                   onChange={(v) => { setOnlyNew(v === "new"); setPage(1); }} />
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
                empty={onlyNew ? t("alerts_none_new") : t("alerts_none")}
                columns={[
                  { key: "time", label: t("alerts_col_time"), kind: "time", render: (a) => (
                    <span title={formatTime(a.fired_at, lang)} data-new={a.is_new || undefined}>
                      {a.is_new && <span className="new-dot" role="img" aria-label={t("alerts_new_mark")} />}
                      {shortTime(a.fired_at)}
                    </span>) },
                  { key: "sev", label: t("alerts_col_severity"), render: (a) => <SeverityTag severity={a.severity} /> },
                  { key: "title", label: t("alerts_col_alert"), render: (a) => (
                    <div data-alert-id={a.id}>
                      <div>{a.summary}</div>
                      <div className="hint">{categoryWord(a.category)} · {a.rule_name}</div>
                    </div>
                  ) },
                  { key: "hosts", label: t("alerts_col_devices"), render: (a) => <AlertHosts a={a} /> },
                  { key: "delivery", label: t("alerts_col_delivery"), nowrap: true, render: (a) => <Deliveries item={a} /> },
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
              <Side key={selected} id={selected} />
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

registerNav({ section: "watch", path: "/", labelKey: "nav_alerts", order: 10, component: AlertsHome, badge: "new" });
registerNav({ section: "watch", path: "/alerts", labelKey: "nav_alerts", order: 10, component: AlertsRedirect, hidden: true });
