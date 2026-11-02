import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { RuleListItem, RulesView } from "../../api/generated";
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

  useEffect(() => {
    void call("alert_rules.list").then((env) => {
      if (env.ok && env.data) setView(env.data);
      else setError(env.error);
    });
  }, []);

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
