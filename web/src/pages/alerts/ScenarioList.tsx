import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { RuleListItem } from "../../api/generated";
import { Purpose } from "../../components/ui";
import { t } from "../../i18n";
import { GROUPS, type Scenario, covering, scenarioKey, scenariosOf } from "./scenarios";

/** Where a new rule starts (purpose-led UI spec §10): every scenario a rule can be about, each with the rules already
 * filed under it. */
export function ScenarioList() {
  const [items, setItems] = useState<RuleListItem[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void call("alert_rules.list").then((env) => { if (env.ok && env.data) setItems(env.data.items); else setError(env.error); });
  }, []);

  const filed = new Map<string, RuleListItem[]>();
  if (items) {
    for (const item of items) {
      const found = covering(item.rule);
      for (const key of found.scenarios) filed.set(key, [...(filed.get(key) ?? []), item]);
    }
  }
  // the scenarios a rule is filed under come first; the rest keep the order they are defined in
  const ordered = (list: Scenario[]) => [...list.filter((s) => filed.has(scenarioKey(s))), ...list.filter((s) => !filed.has(scenarioKey(s)))];
  return (
    <section className="page stack" data-role="scenario-list">
      <p><Link to="/alert-rules">{t("rules_back")}</Link></p>
      <div className="page-title"><h1>{t("rule_editor_new")}</h1><Purpose>{t("purpose_scenario_list")}</Purpose></div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {items && GROUPS.map(({ group, labelKey }) => (
        <section key={group} className="card stack" data-scenario-group={group}>
          <h2>{t(labelKey)}</h2>
          <ul className="scn-list">
            {ordered(scenariosOf(group)).map((s) => (
              <li key={s.id} data-scenario={scenarioKey(s)}>
                <div className="scn-text">
                  <strong data-role="scenario-name">{t(s.labelKey)}</strong>
                  {s.descKey && <span data-role="scenario-desc">{t(s.descKey)}</span>}
                  {s.notesKey && <span className="hint" data-role="scenario-notes">{t(s.notesKey)}</span>}
                  {(filed.get(scenarioKey(s)) ?? []).map((item) => (
                    <Link key={item.rule.id} to={`/alerts/rules/${item.rule.id}`} data-role="covered-by">
                      {t("scn_covered_by", { name: item.display_name })}
                    </Link>
                  ))}
                </div>
                <Link to={`/alerts/rules/new?scenario=${scenarioKey(s)}`} data-role="scenario-new">{t("scn_new")}</Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <p><Link to="/alerts/rules/new?form=full" data-role="full-form">{t("scn_full_form")}</Link></p>
    </section>
  );
}
