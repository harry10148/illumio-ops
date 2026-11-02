// Alert rules and notifications on one page (UI redesign spec §4.9, sample 10): the rules with their week's
// triggers, a rule test against a recent detection or event, and the notification channels.
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { Candidate, RuleTestResult } from "../../api/generated";
import { DataTable, PageHead, Panel, Tag, shortTime } from "../../components/ui";
import { t } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { Channels } from "../system/Channels";
import { CHANNEL_KEYS, word } from "./common";
import { Rules } from "./Rules";

type Tab = "rules" | "channels";

function RuleTest() {
  const [cands, setCands] = useState<Candidate[] | null>(null);
  const [picked, setPicked] = useState("");
  const [result, setResult] = useState<RuleTestResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void call("alert_rules.test_candidates").then((env) => {
      if (env.ok && env.data) setCands(env.data.items);
      else setError(env.error);
    });
  }, []);

  async function run(value: string) {
    setPicked(value);
    setResult(null);
    if (!value) return;
    const [source, id] = value.split(":");
    const env = await call("alert_rules.test", { source: source as "detection" | "event", id: Number(id) });
    if (env.ok && env.data) {
      setResult(env.data);
      setError(null);
    } else setError(env.error);
  }

  return (
    <Panel title={t("rule_test_title")} role="rule-test" meta={t("rule_test_meta")}>
      {cands && cands.length === 0 ? <p className="muted">{t("rule_test_no_candidates")}</p> : (
        <label className="block">
          {t("rule_test_pick")}
          <select name="rule_test_record" value={picked} onChange={(e) => void run(e.target.value)}>
            <option value="">{t("rule_test_choose")}</option>
            {(cands ?? []).map((c) => (
              <option key={`${c.source}:${c.record_id}`} value={`${c.source}:${c.record_id}`}>
                {shortTime(c.at)} · {c.source === "detection" ? t("rule_test_detection") : t("rule_test_event")} · {c.title}
              </option>
            ))}
          </select>
        </label>
      )}
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {result && (
        <DataTable
          rows={result.items}
          rowKey={(m) => m.rule_id}
          empty={t("rule_test_no_rules")}
          columns={[
            { key: "rule", label: t("rules_col_name"), render: (m) => m.rule_name },
            { key: "verdict", label: t("rule_test_col_verdict"), render: (m) => (
              <span data-role="verdict" data-alert={m.would_alert}>
                <Tag tone={m.would_alert ? "high" : "muted"}>{m.would_alert ? t("rule_test_alerts") : t("rule_test_no_alert")}</Tag>
                {m.reason_key && <span className="hint"> {t(m.reason_key, m.params)}</span>}
              </span>
            ) },
            { key: "channels", label: t("rule_test_col_channels"), render: (m) => (
              m.channels.length ? m.channels.map((c) => word(CHANNEL_KEYS, c)).join("、") : "—"
            ) },
          ]}
        />
      )}
    </Panel>
  );
}

export function RulesAndChannels() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "channels" ? "channels" : "rules";
  const pick = (next: Tab) => setParams(next === "rules" ? {} : { tab: next }, { replace: true });
  return (
    <section className="page" data-role="rules-and-channels">
      <PageHead title={t("nav_alert_rules")} sub={t("rules_page_sub")} />
      <div className="chips-row tabs" role="tablist">
        <button type="button" role="tab" className="chip-btn" aria-pressed={tab === "rules"} aria-selected={tab === "rules"}
                onClick={() => pick("rules")} data-tab="rules">{t("rules_tab_rules")}</button>
        <button type="button" role="tab" className="chip-btn" aria-pressed={tab === "channels"}
                aria-selected={tab === "channels"} onClick={() => pick("channels")} data-tab="channels">{t("rules_tab_channels")}</button>
      </div>
      {tab === "rules" ? (
        <div className="stack">
          <Rules embedded />
          <RuleTest />
        </div>
      ) : <Channels embedded />}
    </section>
  );
}

registerNav({ section: "bottom", path: "/alert-rules", labelKey: "nav_alert_rules", order: 10, component: RulesAndChannels });
