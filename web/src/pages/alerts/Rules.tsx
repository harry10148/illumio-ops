import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { EvaluateRequested, RuleListItem, RulesView } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { STATUS_KEYS, TYPE_KEYS, word } from "./common";

type Mode = "append_missing" | "replace";

export function Rules({ embedded = false }: { embedded?: boolean }) {
  const lang = useLang();
  const [view, setView] = useState<RulesView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, setConfirm] = useState<Mode | null>(null);
  const [resetting, setResetting] = useState<string | null>(null);
  const [evaluated, setEvaluated] = useState<EvaluateRequested | null>(null);
  const [keep, setKeep] = useState("");
  const [keepSaved, setKeepSaved] = useState(false);

  useEffect(() => {
    void call("alert_rules.list").then((env) => {
      if (env.ok && env.data) { setView(env.data); setKeep(String(env.data.retention_days)); }
      else setError(env.error);
    });
  }, []);

  async function reset(id: string) {
    const env = await call("alert_rules.reset_state", undefined, { rule_id: id });
    setResetting(null);
    if (env.ok && env.data) { setView(env.data); setError(null); } else setError(env.error);
  }

  async function evaluateNow() {
    const env = await call("alert_rules.evaluate_now");
    if (env.ok && env.data) { setEvaluated(env.data); setError(null); } else { setEvaluated(null); setError(env.error); }
  }

  async function saveKeep() {
    if (!view) return;
    const env = await call("alert_rules.retention", { revision: view.revision, retention_days: Number(keep) });
    if (env.ok && env.data) { setView(env.data); setError(null); setKeepSaved(true); }
    else { setError(env.error); setKeepSaved(false); }
  }

  async function toggle(item: RuleListItem, field: "enabled" | "notify") {
    if (!view) return;
    const rule = { ...item.rule, [field]: !item.rule[field] };
    const env = await call("alert_rules.update", { revision: view.revision, rule }, { rule_id: item.rule.id });
    if (env.ok && env.data) { setView(env.data); setError(null); } else setError(env.error);
  }

  async function applyPack(mode: Mode) {
    if (!view) return;
    const env = await call("alert_rules.pack", { revision: view.revision, mode });
    setConfirm(null);
    if (env.ok && env.data) { setView(env.data); setError(null); } else setError(env.error);
  }

  return (
    <section className="page stack">
      {!embedded && <p><Link to="/">{t("alert_back")}</Link></p>}
      <div className="page-head">
        {!embedded && <h1>{t("rules_title")}</h1>}
        <Link to="/alerts/rules/new" className="btn-primary">{t("rules_new")}</Link>
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {view && (
        <>
          <div className="card stack" data-role="pack">
            <p className="hint">{t("rules_pack_hint")}</p>
            {view.pack_missing > 0 && <p className="notice">{t("rules_pack_missing", { n: String(view.pack_missing) })}</p>}
            {confirm ? (
              <div className="row">
                <span>{t(confirm === "replace" ? "rules_pack_replace_confirm" : "rules_pack_append_confirm")}</span>
                <button type="button" className="btn-primary" onClick={() => void applyPack(confirm)}>{t("btn_confirm")}</button>
                <button type="button" className="btn-quiet" onClick={() => setConfirm(null)}>{t("btn_cancel")}</button>
              </div>
            ) : (
              <div className="row">
                <button type="button" className="btn-quiet" onClick={() => setConfirm("append_missing")}>{t("rules_pack_append")}</button>
                <button type="button" className="btn-quiet" onClick={() => setConfirm("replace")}>{t("rules_pack_replace")}</button>
              </div>
            )}
          </div>
          <div className="card stack" data-role="evaluate">
            <div className="row">
              <button type="button" className="btn-quiet" data-role="evaluate-now" onClick={() => void evaluateNow()}>
                {t("rules_evaluate_now")}
              </button>
              <span className="hint">{t("rules_evaluate_hint")}</span>
            </div>
            {evaluated && (
              <p className="notice" role="status" data-role="evaluate-requested">
                {t("rules_evaluate_requested", { time: formatTime(evaluated.requested_at, lang) })}
              </p>
            )}
          </div>
          <div className="table-wrap">
            <table className="table" data-role="rule-list">
              <thead>
                <tr>
                  <th>{t("rules_col_name")}</th><th>{t("rules_col_type")}</th><th>{t("rules_col_enabled")}</th>
                  <th>{t("rules_col_notify")}</th><th>{t("rules_col_last")}</th>
                  <th className="wb-num">{t("rules_col_7d")}</th><th className="wb-num">{t("rules_col_known")}</th>
                  <th>{t("rules_col_status")}</th>
                </tr>
              </thead>
              <tbody>
                {view.items.map((item) => {
                  const s = item.summary;
                  const held = (s?.suppressed_cooldown ?? 0) + (s?.suppressed_throttle ?? 0);
                  return (
                    <tr key={item.rule.id} data-rule-id={item.rule.id}>
                      <td><Link to={`/alerts/rules/${item.rule.id}`}>{item.display_name}</Link></td>
                      <td>{word(TYPE_KEYS, item.rule.type)}</td>
                      <td>
                        <input type="checkbox" aria-label={t("rules_col_enabled")} checked={item.rule.enabled}
                               onChange={() => void toggle(item, "enabled")} />
                      </td>
                      <td>
                        <input type="checkbox" aria-label={t("rules_col_notify")} checked={item.rule.notify}
                               onChange={() => void toggle(item, "notify")} />
                        {!item.rule.notify && <span className="hint"> {t("rules_record_only")}</span>}
                      </td>
                      <td>
                        {s?.last_fired_at ? formatTime(s.last_fired_at, lang) : t("rules_never")}
                        {held > 0 && <span className="hint"> · {t("rules_held", { n: String(held) })}</span>}
                        {item.held && (
                          <div className="hint" data-role="held">
                            {t(item.held.reason === "throttle" ? "rules_hold_throttle" : "rules_hold_cooldown",
                               { n: String(item.held.subjects), time: formatTime(item.held.until, lang) })}{" "}
                            {resetting === item.rule.id ? (
                              <>
                                <span>{t("rules_reset_confirm")}</span>{" "}
                                <button type="button" className="btn-quiet" data-role="reset-confirm"
                                        onClick={() => void reset(item.rule.id)}>{t("btn_confirm")}</button>
                                <button type="button" className="btn-quiet" onClick={() => setResetting(null)}>{t("btn_cancel")}</button>
                              </>
                            ) : (
                              <button type="button" className="btn-quiet" data-role="reset"
                                      onClick={() => setResetting(item.rule.id)}>{t("rules_reset")}</button>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="wb-num mono" data-role="fired-7d">{s?.fired_7d ?? 0}</td>
                      <td className="wb-num mono" data-role="known-7d">{s?.known_7d ?? 0}</td>
                      <td>{s?.last_status ? word(STATUS_KEYS, s.last_status) : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="card row" data-role="retention">
            <label>
              {t("rules_retention")}
              <input name="alert_retention_days" type="number" min={0} max={3650} className="narrow" value={keep}
                     onChange={(e) => { setKeep(e.target.value); setKeepSaved(false); }} />
            </label>
            <span className="hint">{Number(keep) === 0 ? t("rules_retention_forever") : t("rules_retention_hint")}</span>
            <button type="button" className="btn-quiet" onClick={() => void saveKeep()}>{t("btn_save")}</button>
            {keepSaved && <span className="form-ok" role="status">{t("saved_ok")}</span>}
          </div>
        </>
      )}
    </section>
  );
}

/** The rule list is the first tab of the alert rules page (UI redesign spec §4.9). */
function RulesRedirect() {
  return <Navigate to="/alert-rules" replace />;
}

registerNav({ section: "main", path: "/alerts/rules", labelKey: "nav_alert_rules", order: 12, component: RulesRedirect,
              hidden: true });
