import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { EventCatalog, RuleListItem } from "../../api/generated";
import { Purpose } from "../../components/ui";
import { t } from "../../i18n";
import { conditionSummary } from "./ruleSummary";
import { GROUPS, type Scenario, covering, scenarioKey, scenariosOf } from "./scenarios";

/** Where a new rule starts (purpose-led UI spec §10): every scenario a rule can be about, each with the rules already
 * filed under it. A scenario without such a line says nothing about it: a rule matching by pattern may cover it, and
 * those are listed apart at the end. */
export function ScenarioList() {
  const [items, setItems] = useState<RuleListItem[] | null>(null);
  const [catalog, setCatalog] = useState<EventCatalog | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void call("alert_rules.list").then((env) => { if (env.ok && env.data) setItems(env.data.items); else setError(env.error); });
    void call("alert_rules.event_catalog").then((env) => { if (env.ok && env.data) setCatalog(env.data); else setError(env.error); });
  }, []);

  const filed = new Map<string, RuleListItem[]>();
  const byPattern: RuleListItem[] = [];
  if (items && catalog) {
    for (const item of items) {
      const found = covering(item.rule, catalog);
      for (const key of found.scenarios) filed.set(key, [...(filed.get(key) ?? []), item]);
      if (found.byPattern) byPattern.push(item);
    }
  }
  // the scenarios a rule is filed under come first; the rest keep the order they are defined in
  const ordered = (list: Scenario[]) => [...list.filter((s) => filed.has(scenarioKey(s))), ...list.filter((s) => !filed.has(scenarioKey(s)))];
  const eventCount = new Map((catalog?.categories ?? []).map((c) => [c.id, c.events.length] as const));

  return (
    <section className="page stack" data-role="scenario-list">
      <p><Link to="/alerts/rules">{t("rules_back")}</Link></p>
      <div className="page-title"><h1>{t("rule_editor_new")}</h1><Purpose>{t("purpose_scenario_list")}</Purpose></div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {items && catalog && GROUPS.map(({ group, labelKey }) => (
        <section key={group} className="card stack" data-scenario-group={group}>
          <h2>{t(labelKey)}</h2>
          <ul className="scn-list">
            {ordered(scenariosOf(group, catalog)).map((s) => (
              <li key={s.id} data-scenario={scenarioKey(s)}>
                <div className="scn-text">
                  <strong data-role="scenario-name">{t(s.labelKey)}</strong>
                  <span data-role="scenario-desc">
                    {s.descKey ? t(s.descKey) : t("scn_event_count", { n: String(eventCount.get(s.id) ?? 0) })}
                  </span>
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
      {byPattern.length > 0 && (
        <section className="card stack" data-role="pattern-rules">
          <h2>{t("scn_pattern_title")}</h2>
          <p className="hint">{t("scn_pattern_hint")}</p>
          <ul className="scn-list">
            {byPattern.map((item) => (
              <li key={item.rule.id} data-rule-id={item.rule.id}>
                <div className="scn-text">
                  <Link to={`/alerts/rules/${item.rule.id}`}>{item.display_name}</Link>
                  <span>{conditionSummary(item.rule)}</span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p><Link to="/alerts/rules/new?form=full" data-role="full-form">{t("scn_full_form")}</Link></p>
    </section>
  );
}
