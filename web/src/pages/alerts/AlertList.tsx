import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { AlertList as AlertListData } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { DELIVERY_TONES, SEVERITY_KEYS, SEVERITY_TONES, TYPE_KEYS, deliveryText, word } from "./common";

const PERIODS = ["1", "7", "30"];

export function AlertList() {
  const lang = useLang();
  const [days, setDays] = useState("7");
  const [type, setType] = useState("");
  const [severity, setSeverity] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AlertListData | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void call("alerts.list", undefined, undefined, { days, type, severity, page: String(page) }).then((env) => {
      if (env.ok && env.data) {
        setData(env.data);
        setError(null);
      } else setError(env.error);
    });
  }, [days, type, severity, page]);

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <section className="page stack">
      <div className="page-head">
        <h1>{t("nav_alerts")}</h1>
        <Link to="/alerts/rules" className="btn-quiet">{t("alerts_rules_link")}</Link>
      </div>
      <div className="row" data-role="alert-filters">
        <label>
          {t("alerts_period")}
          <select name="days" value={days} onChange={(e) => { setDays(e.target.value); setPage(1); }}>
            {PERIODS.map((d) => <option key={d} value={d}>{t("alerts_period_days", { n: d })}</option>)}
          </select>
        </label>
        <label>
          {t("alerts_type")}
          <select name="type" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
            <option value="">{t("alerts_all")}</option>
            {Object.keys(TYPE_KEYS).map((k) => <option key={k} value={k}>{word(TYPE_KEYS, k)}</option>)}
          </select>
        </label>
        <label>
          {t("alerts_severity")}
          <select name="severity" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }}>
            <option value="">{t("alerts_all")}</option>
            {Object.keys(SEVERITY_KEYS).map((k) => <option key={k} value={k}>{word(SEVERITY_KEYS, k)}</option>)}
          </select>
        </label>
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {data && (
        <>
          <p className="hint" data-role="alert-total">{t("alerts_total", { n: String(data.total) })}</p>
          {data.items.length === 0 ? <p className="muted">{t("alerts_none")}</p> : (
            <div className="table-wrap">
              <table className="table" data-role="alert-list">
                <thead>
                  <tr>
                    <th>{t("alerts_col_time")}</th><th>{t("alerts_col_severity")}</th><th>{t("alerts_col_rule")}</th>
                    <th>{t("alerts_col_summary")}</th><th>{t("alerts_col_delivery")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((a) => (
                    <tr key={a.id} data-alert-id={a.id}>
                      <td>{formatTime(a.fired_at, lang)}</td>
                      <td><span className="badge" data-tone={SEVERITY_TONES[a.severity]}>{word(SEVERITY_KEYS, a.severity)}</span></td>
                      <td><Link to={`/alerts/${a.id}`}>{a.rule_name}</Link></td>
                      <td>
                        {a.summary}
                        {a.caveats.map((c) => <span key={c} className="hint"> · {c}</span>)}
                      </td>
                      <td>
                        {a.deliveries.map((d) => (
                          <span key={d.channel} className="badge" data-delivery={d.status} data-tone={DELIVERY_TONES[d.status]}>
                            {deliveryText(d)}
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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

registerNav({ section: "main", path: "/alerts", labelKey: "nav_alerts", order: 10, component: AlertList });
