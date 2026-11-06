// Rule set browsing (5.x #/policy/rulesets; parity 2026-11-06): the PCE's active rule sets with their allow, deny and
// override deny rules, read-only. Reached from Rule scheduling; a schedule is made there.
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { RuleItem, RulesetBrowse } from "../../api/generated";
import { DataTable, PageHead, Panel, Tag } from "../../components/ui";
import { t } from "../../i18n";
import { registerNav } from "../../shell/nav";

const KIND_KEYS: Record<RuleItem["kind"], string> = {
  allow: "rsb_kind_allow", deny: "rsb_kind_deny", override_deny: "rsb_kind_override_deny",
};

function Flags({ pending, scheduled }: { pending: boolean; scheduled: boolean }) {
  return (
    <>
      {pending && <Tag tone="high">{t("rsb_draft_pending")}</Tag>}
      {scheduled && <Tag tone="adv">{t("rsb_scheduled")}</Tag>}
    </>
  );
}

export function Rulesets() {
  const [q, setQ] = useState("");
  const [view, setView] = useState<RulesetBrowse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  const load = useCallback(async (name: string) => {
    const mine = ++seq.current;
    setBusy(true);
    const env = await call("rule_schedules.rulesets", undefined, undefined, { q: name });
    if (mine !== seq.current) return;  // a newer search was sent
    setBusy(false);
    if (env.ok && env.data) {
      setView(env.data);
      setError(null);
    } else {
      setView(null);  // a failed read is never shown as an empty list
      setError(env.error);
    }
  }, []);
  useEffect(() => { void load(""); }, [load]);

  const search = (e: FormEvent) => {
    e.preventDefault();
    void load(q.trim());
  };

  return (
    <section className="page stack" data-role="rulesets">
      <PageHead title={t("rsb_title")} sub={t("rsb_sub")}>
        <Link to="/rule-schedules">{t("rsb_back")}</Link>
      </PageHead>
      <form className="row" onSubmit={search}>
        <label className="block">
          {t("rsb_search")}
          <input name="rsb_q" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)} />
        </label>
        <button type="submit" className="btn-quiet" disabled={busy}>{t("rs_search")}</button>
      </form>
      {busy && !view && <p className="muted">{t("loading")}</p>}
      {error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
      {view && (
        <>
          <p className="hint" data-role="rsb-count">
            {view.limited ? t("rsb_count_limited", { n: String(view.items.length), total: String(view.total) })
              : t("rsb_count", { n: String(view.total) })}
          </p>
          {view.items.length === 0 && <p className="muted">{t("rsb_none")}</p>}
          {view.items.map((rs) => (
            <Panel key={rs.href} role="rsb-ruleset" title={rs.name}
                   meta={<>
                     <Tag tone={rs.enabled ? "ok" : "muted"}>{rs.enabled ? t("rs_live_enabled") : t("rs_live_disabled")}</Tag>
                     <Flags pending={rs.draft_pending} scheduled={rs.scheduled} />
                   </>}>
              {rs.description && <p className="hint">{rs.description}</p>}
              <DataTable<RuleItem>
                rows={rs.rules}
                rowKey={(r) => r.href}
                empty={t("rsb_no_rules")}
                columns={[
                  { key: "rule", label: t("rsb_col_rule"), kind: "mono", render: (r) => r.label },
                  { key: "kind", label: t("rsb_col_kind"), render: (r) => (
                    <Tag tone={r.kind === "allow" ? "ok" : "crit"}>{t(KIND_KEYS[r.kind])}</Tag>) },
                  { key: "state", label: t("rsb_col_state"), render: (r) => (
                    <span>
                      <Tag tone={r.enabled ? "ok" : "muted"}>{r.enabled ? t("rs_live_enabled") : t("rs_live_disabled")}</Tag>
                      <Flags pending={r.draft_pending} scheduled={r.scheduled} />
                    </span>) },
                  { key: "what", label: t("rsb_col_what"), render: (r) => (
                    <div><div className="mono">{r.summary}</div>{r.description && <div className="hint">{r.description}</div>}</div>) },
                ]}
              />
            </Panel>
          ))}
        </>
      )}
    </section>
  );
}

registerNav({ section: "main", path: "/rule-schedules/rulesets", labelKey: "rsb_title", order: 19, component: Rulesets,
  hidden: true });
