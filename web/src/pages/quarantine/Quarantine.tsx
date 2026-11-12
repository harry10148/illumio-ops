// Quarantine (purpose-led UI spec §6.4): which hosts carry the quarantine label now, who put it there and when, and
// how to take it off. The list is read from the inventory and this tool's own record (no write key needed, the PCE is
// not asked); lifting a quarantine is the same write the host page makes.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { QuarantineAction, QuarantineCurrent, QuarantineOutcome, QuarantinedHost } from "../../api/generated";
import { HostLink } from "../../components/HostLink";
import { formatTime } from "../../components/ProbeResults";
import { ActionNote, EmptyState, PageHead, Panel } from "../../components/ui";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { modeWord } from "../../terms";
import { word } from "../alerts/common";
import { DETAIL_KEYS, LEVEL_KEYS, Outcome, STATUS_KEYS, nonEmpty } from "./QuarantineDialog";

const HISTORY = 50;

export function Quarantine() {
  const lang = useLang();
  const [now, setNow] = useState<QuarantineCurrent | null>(null);
  const [history, setHistory] = useState<QuarantineAction[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [historyError, setHistoryError] = useState<ApiError | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<QuarantineOutcome | null>(null);

  const load = useCallback(() => {
    void call("quarantine.current").then((env) => {
      if (env.ok && env.data) { setNow(env.data); setError(null); } else setError(env.error);
    });
    void call("quarantine.history").then((env) => {
      // unread is said: a missing record reads as "nothing was done"
      if (env.ok && env.data) { setHistory(env.data.actions.slice(0, HISTORY)); setHistoryError(null); }
      else setHistoryError(env.error);
    });
  }, []);
  useEffect(() => { load(); }, [load]);

  async function release(host: QuarantinedHost) {
    setConfirming(null);
    const env = await call("quarantine.remove", { keys: nonEmpty([host.key]) });
    if (env.ok && env.data) { setOutcome(env.data); setError(null); } else setError(env.error);
    load();
  }

  const idle = now?.items.filter((h) => h.no_enforcement).length ?? 0;
  return (
    <section className="page" data-role="quarantine-page">
      <PageHead title={t("nav_quarantine")} purpose={t("purpose_quarantine")} />
      {now && now.items.length > 0 && (
        <p className="page-conclusion" data-role="page-conclusion">
          {t("q_page_conclusion", { n: String(now.items.length) })}
          {idle > 0 && <> {t("q_page_conclusion_idle", { m: String(idle) })}</>}
        </p>
      )}
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {now && !now.write_key && (
        <p className="notice" data-role="q-no-write-key">{t("q_no_write_key")} <Link to="/system/pce">{t("nav_system_pce")}</Link></p>
      )}
      {outcome && <Outcome outcome={outcome} />}
      {now && now.items.length === 0 && (
        <EmptyState text={t("q_page_none")}><Link to="/">{t("q_page_none_next")}</Link></EmptyState>
      )}
      {now && now.items.length > 0 && (
        <div className="table-wrap">
          <table className="table" data-role="quarantined">
            <thead>
              <tr>
                <th>{t("q_col_host")}</th><th>{t("q_page_col_level")}</th><th>{t("hosts_mode")}</th>
                <th>{t("q_page_col_applied")}</th>{now.write_key && <th />}
              </tr>
            </thead>
            <tbody>
              {now.items.map((h) => (
                <tr key={h.key} data-host={h.key}>
                  <td><HostLink hostKey={h.key} name={h.name} section="quarantine" /></td>
                  <td className="nowrap">{t(LEVEL_KEYS[h.level] ?? h.level)}</td>
                  <td>
                    {h.enforcement_mode ? modeWord(h.enforcement_mode) : "—"}
                    {h.no_enforcement && <ActionNote>{t("hosts_q_no_effect")}</ActionNote>}
                  </td>
                  <td>
                    {h.applied_at ? <><span className="num">{formatTime(h.applied_at, lang)}</span> · {h.applied_by}</>
                      : <span className="hint">{t("q_page_not_ours")}</span>}
                  </td>
                  {now.write_key && (
                    <td className="nowrap">
                      {confirming === h.key ? (
                        <>
                          <button type="button" className="btn-danger" data-role="q-release-confirm" onClick={() => void release(h)}>
                            {t("q_remove_confirm", { host: h.name })}
                          </button>
                          <button type="button" className="btn-quiet" onClick={() => setConfirming(null)}>{t("btn_cancel")}</button>
                        </>
                      ) : (
                        <button type="button" className="btn-danger" data-role="q-release" onClick={() => setConfirming(h.key)}>
                          {t("q_remove")}…
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Panel title={t("q_page_history")} role="q-page-history">
        {historyError && <p className="form-error">{t("q_history_unread")} {t(historyError.message_key, historyError.params)}</p>}
        {history && history.length === 0 && <p className="muted">{t("q_page_history_none")}</p>}
        {history && history.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("fleet_col_at")}</th><th>{t("q_col_host")}</th><th>{t("q_page_col_action")}</th>
                  <th>{t("q_page_col_by")}</th><th>{t("q_col_result")}</th>
                </tr>
              </thead>
              <tbody>
                {history.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap num">{formatTime(a.at, lang)}</td>
                    <td><HostLink hostKey={a.workload_href} name={a.hostname ?? a.workload_href} section="quarantine" /></td>
                    <td>{a.action === "apply" ? t("q_history_apply", { level: t(LEVEL_KEYS[a.level ?? ""] ?? a.level ?? "") })
                      : t("q_history_remove")}</td>
                    <td>{a.by}</td>
                    <td>{word(STATUS_KEYS, a.result)}{a.detail ? ` · ${word(DETAIL_KEYS, a.detail)}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </section>
  );
}

registerNav({ section: "devices", path: "/quarantine", labelKey: "nav_quarantine", order: 30, component: Quarantine });
