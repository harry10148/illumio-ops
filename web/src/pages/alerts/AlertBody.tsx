// One alert, said one way (purpose-led UI spec §6.1): the side panel of the alerts page and the alert's own page show
// this same body — what happened, what to do, the hosts it is about, how it came about, and at the foot what can be
// done. The full page adds the evidence, the notifications and the notes under it.
import { useState } from "react";
import { Link } from "react-router-dom";

import type { AlertDetail, AlertDevice } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { HostLink, type HostSection } from "../../components/HostLink";
import { ActionNote, Disclosure, HostName, SeverityTag, Tag, shortTime } from "../../components/ui";
import { t, useLang } from "../../i18n";
import { modeWord } from "../../terms";
import { QuarantineDialog } from "../quarantine/QuarantineDialog";

const CATEGORY_KEYS: Record<string, string> = {
  lateral: "alert_cat_lateral", anomaly: "alert_cat_anomaly", traffic: "alert_cat_traffic",
  event: "alert_cat_event", system: "alert_cat_system",
};
const ROLE_KEYS: Record<string, string> = {
  source: "alert_role_source", destination: "alert_role_destination", subject: "alert_role_subject",
};
export const LIST_DEVICES = 3;

export function categoryWord(c: string): string {
  const key = CATEGORY_KEYS[c];
  return key ? t(key) : c;
}

/** The hosts of an alert in a list row: source → destination when it has both, else each host; at most LIST_DEVICES,
 * the rest as a count. An alert stored before hosts were kept shows the words it has; one about no host says so. */
export function AlertHosts({ a }: {
  a: { devices: AlertDevice[]; devices_more: number; src: string | null; dst: string | null; rule_type: string;
       host_section: HostSection | null };
}) {
  if (a.devices.length === 0) {
    if (a.src || a.dst) return <>{a.src ? <HostName name={a.src} /> : "—"} → {a.dst ? <HostName name={a.dst} /> : "—"}</>;
    return <span className="hint">{a.rule_type === "system" ? t("alerts_about_system_short") : "—"}</span>;
  }
  const section = a.host_section;
  const shown = a.devices.slice(0, LIST_DEVICES);
  const more = a.devices.length - shown.length + a.devices_more;
  const link = (d: AlertDevice) => <HostLink key={`${d.key}|${d.role}`} hostKey={d.key} name={d.name} section={section} />;
  const [first, second] = shown;
  const pair = shown.length === 2 && first?.role === "source" && second?.role === "destination";
  return (
    <span data-role="alert-hosts">
      {pair && first && second ? <>{link(first)} → {link(second)}</>
        : shown.map((d, i) => <span key={`${d.key}|${d.role}`}>{i > 0 && t("list_separator")}{link(d)}</span>)}
      {more > 0 && <span className="hint"> {t("alert_devices_more", { n: String(more) })}</span>}
    </span>
  );
}

function Devices({ d, section }: { d: AlertDetail; section: HostSection | null }) {
  if (d.devices.length === 0) {
    return (
      <p className="hint" data-role="alert-devices">
        {d.src || d.dst ? `${d.src ?? "—"} → ${d.dst ?? "—"}`
          : d.rule_type === "system" ? t("alert_about_system") : t("alert_about_no_host")}
      </p>
    );
  }
  return (
    <ul className="device-list" data-role="alert-devices">
      {d.devices.map((x) => {
        const facts = d.device_facts[x.key];
        const about = [
          t(ROLE_KEYS[x.role] ?? x.role),
          facts?.environment,
          facts && !facts.in_inventory ? t("alert_not_in_inventory") : null,
          facts?.enforcement_mode ? modeWord(facts.enforcement_mode) : null,
          !x.managed ? t("alert_unmanaged_address") : null,
        ].filter(Boolean).join(" · ");
        return (
          <li key={`${x.key}|${x.role}`}>
            <HostLink hostKey={x.key} name={x.name} section={section} />
            <span className="hint">{about}</span>
          </li>
        );
      })}
      {d.devices_more > 0 && <li className="hint">{t("alert_devices_more", { n: String(d.devices_more) })}</li>}
    </ul>
  );
}

export function AlertBody({ d, full }: { d: AlertDetail; full: boolean }) {
  const lang = useLang();
  const [isolating, setIsolating] = useState(false);
  const q = d.quarantine;
  const section = d.host_section;
  const [firstStep, ...moreSteps] = d.next_steps;
  return (
    <div className="stack alert-body" data-role="alert-body">
      <div className="row">
        <SeverityTag severity={d.severity} />
        <Tag tone="muted">{categoryWord(d.category)}</Tag>
        {d.category !== "event" && d.category !== "system" && <Tag tone="adv">◆ {t("mode_advanced")}</Tag>}
        {d.grouped && <Tag tone="muted">{t("alerts_grouped_tag")}</Tag>}
      </div>
      <h2 className="side-title" data-role="alert-summary">{d.summary}</h2>
      <p className="hint">{d.rule_name} · <span className="num">{formatTime(d.fired_at, lang)}</span></p>
      {d.caveats.map((c) => <p key={c} className="notice">{c}</p>)}
      {d.grouped && (
        <p className="hint" data-role="known-reason">
          {typeof d.params.known_reason === "string" ? t("alert_known_reason", { reason: d.params.known_reason })
            : t("alert_grouped_known_cause")}
        </p>
      )}
      {firstStep && (
        <div data-role="next-steps">
          <h3 className="side-h">{t("guide_title")}</h3>
          <p>{firstStep}</p>
          {moreSteps.length > 0 && (
            <Disclosure summary={t("alert_steps_all")}>{moreSteps.map((s) => <p key={s}>{s}</p>)}</Disclosure>
          )}
        </div>
      )}
      <div>
        <h3 className="side-h">{t("alert_devices_title")}</h3>
        <Devices d={d} section={section} />
      </div>
      <div>
        <h3 className="side-h">{t("alert_timeline_title")}</h3>
        <ol className="timeline" data-role="timeline">
          {d.timeline.map((e, i) => (
            <li key={i} data-kind={e.kind}>
              <span className="num" title={formatTime(e.at, lang)}>{full ? formatTime(e.at, lang) : shortTime(e.at)}</span> {e.text}
            </li>
          ))}
        </ol>
      </div>
      {d.beyond_vendor.length > 0 && (
        <div>
          <h3 className="side-h">{t("alert_beyond_title")}</h3>
          <ul className="plain-list" data-role="beyond">{d.beyond_vendor.map((s) => <li key={s}>{s}</li>)}</ul>
        </div>
      )}
      <div className="side-actions" data-role="alert-actions">
        {d.evidence_kind
          ? <Link className="btn-primary" to={`/investigate?alert=${d.id}`} data-role="open-workbench">{t("alert_start_investigation")}</Link>
          : <span className="hint">{t("alert_no_evidence_to_investigate")}</span>}
        {q.eligible && q.key ? (
          <button type="button" className="btn-quiet" data-role="quarantine" onClick={() => setIsolating(true)}>
            {t("alert_quarantine_host", { host: q.name ?? q.key })}
          </button>
        ) : (
          <span className="hint" data-role="quarantine-reason">{t(q.reason === "unmanaged" ? "alert_q_unmanaged"
            : q.reason === "not_in_inventory" ? "alert_q_not_in_inventory" : "alert_q_no_subject")}</span>
        )}
        {d.rule_type === "lateral" && !d.grouped && (
          full ? <a className="btn-text" href="#mark-known">{t("alert_known_mark")}</a>
            : <Link className="btn-text" to={`/alerts/${d.id}#mark-known`}>{t("alert_known_mark")}</Link>
        )}
        {d.console_link && (
          <a className="btn-text" href={d.console_link} target="_blank" rel="noopener noreferrer">{t("alert_open_console")}</a>
        )}
        {!full && <Link className="btn-text" to={`/alerts/${d.id}`} data-role="open-detail">{t("alert_full_detail")}</Link>}
        {q.eligible && q.key && q.no_enforcement && <ActionNote>{t("alert_quarantine_no_effect")}</ActionNote>}
      </div>
      {isolating && q.key && (
        <QuarantineDialog hosts={[{ key: q.key, name: q.name ?? q.key }]} onClose={() => setIsolating(false)} />
      )}
    </div>
  );
}
