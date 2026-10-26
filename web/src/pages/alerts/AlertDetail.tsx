import { type FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { AlertDetail as Detail, AlertEvidence, PolicyExplanation, RuleRef } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { DELIVERY_TONES, SEVERITY_KEYS, SEVERITY_TONES, deliveryText, word } from "./common";

type Row = Record<string, unknown>;

const FLOW_COLUMNS = ["src_hostname", "dst_hostname", "port", "policy_decision", "num_connections", "last_detected"];
const EVENT_COLUMNS = ["timestamp", "event_type", "status", "severity", "created_by_name"];
const COLUMN_KEYS: Record<string, string> = {
  src_hostname: "evidence_col_src", dst_hostname: "evidence_col_dst", port: "evidence_col_port",
  policy_decision: "evidence_col_decision", num_connections: "evidence_col_connections",
  last_detected: "evidence_col_last", timestamp: "evidence_col_time", event_type: "evidence_col_event_type",
  status: "evidence_col_status", severity: "evidence_col_severity", created_by_name: "evidence_col_actor",
};

function cell(row: Row, column: string, lang: string): string {
  const v = row[column];
  if (v === null || v === undefined) {
    if (column === "src_hostname") return String(row.src_ip ?? "");
    if (column === "dst_hostname") return String(row.dst_ip ?? "");
    return "";
  }
  if (column === "last_detected" || column === "timestamp") return formatTime(String(v), lang);
  return String(v);
}

function Rules({ titleKey, rules }: { titleKey: string; rules: RuleRef[] }) {
  if (rules.length === 0) return null;
  return (
    <p>
      <strong>{t(titleKey)}</strong>{" "}
      {rules.map((r) => r.ruleset_name).join(", ")}
    </p>
  );
}

function Explanation({ e }: { e: PolicyExplanation }) {
  if (e.pce_error) return <p className="form-error">{t("explain_failed", { error: e.pce_error })}</p>;
  if (e.source === "none") return <p className="hint">{t("explain_unplaced")}</p>;
  const none = e.allow.length + e.deny.length + e.override_deny.length === 0;
  return (
    <div className="hint" data-role="explanation">
      {none && <p>{t("explain_no_rule")}</p>}
      <Rules titleKey="explain_allow" rules={e.allow} />
      <Rules titleKey="explain_deny" rules={e.deny} />
      <Rules titleKey="explain_override_deny" rules={e.override_deny} />
      {e.partial && <p>{t("explain_partial", { ends: e.unresolved.join(", ") })}</p>}
    </div>
  );
}

function Evidence({ alertId, kind }: { alertId: string; kind: string | null }) {
  const lang = useLang();
  const [ev, setEv] = useState<AlertEvidence | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [explained, setExplained] = useState<Record<number, PolicyExplanation | ApiError>>({});

  useEffect(() => {
    void call("alerts.evidence", undefined, { alert_id: alertId }).then((env) => {
      if (env.ok && env.data) setEv(env.data);
      else setError(env.error);
    });
  }, [alertId]);

  async function explain(i: number, row: Row) {
    const env = await call("alerts.explain", {
      src_href: (row.src_href as string | null) ?? null, src_ip: String(row.src_ip ?? ""),
      dst_href: (row.dst_href as string | null) ?? null, dst_ip: String(row.dst_ip ?? ""),
      port: Number(row.port ?? 0), proto: Number(row.proto ?? 6),
    }, { alert_id: alertId });
    setExplained({ ...explained, [i]: env.ok && env.data ? env.data : (env.error as ApiError) });
  }

  if (!kind) return <p className="muted">{t("evidence_none")}</p>;
  if (error) return <p className="form-error">{t(error.message_key, error.params)}</p>;
  if (!ev) return <p className="muted">{t("loading")}</p>;
  const columns = ev.kind === "flow" ? FLOW_COLUMNS : EVENT_COLUMNS;
  const gaps = ev.coverage?.gaps ?? [];
  return (
    <div data-role="evidence">
      {gaps.length > 0 && <p className="notice">{t("evidence_gaps", { n: String(gaps.length) })}</p>}
      {ev.limit_hit && <p className="hint">{t("evidence_limit", { n: String(ev.rows.length) })}</p>}
      {ev.rows.length === 0 ? <p className="muted">{t("evidence_empty")}</p> : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                {columns.map((c) => <th key={c}>{t(COLUMN_KEYS[c] ?? c)}</th>)}
                {ev.kind === "flow" && <th />}
              </tr>
            </thead>
            <tbody>
              {ev.rows.map((row, i) => {
                const result = explained[i];
                return [
                  <tr key={`r${i}`}>
                    {columns.map((c) => <td key={c}>{cell(row, c, lang)}</td>)}
                    {ev.kind === "flow" && (
                      <td><button type="button" className="btn-quiet" onClick={() => void explain(i, row)}>{t("explain_button")}</button></td>
                    )}
                  </tr>,
                  result && (
                    <tr key={`e${i}`}>
                      <td colSpan={columns.length + 1}>
                        {"message_key" in result
                          ? <p className="form-error">{t(result.message_key, result.params)}</p>
                          : <Explanation e={result} />}
                      </td>
                    </tr>
                  ),
                ];
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function AlertDetail() {
  const lang = useLang();
  const { id = "" } = useParams();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<ApiError | null>(null);

  useEffect(() => {
    void call("alerts.get", undefined, { alert_id: id }).then((env) => {
      if (env.ok && env.data) setD(env.data);
      else setError(env.error);
    });
  }, [id]);

  async function addNote(e: FormEvent) {
    e.preventDefault();
    const env = await call("alerts.note_add", { body: note }, { alert_id: id });
    if (env.ok && env.data) {
      setD(env.data);
      setNote("");
      setNoteError(null);
    } else setNoteError(env.error);
  }

  if (!d) {
    return (
      <section className="page">
        <h1>{t("alert_detail_title")}</h1>
        {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      </section>
    );
  }
  return (
    <section className="page stack" data-role="alert-detail">
      <p><Link to="/alerts">{t("alert_back")}</Link></p>
      <div className="page-head">
        <h1>{d.rule_name}</h1>
        {d.console_link && (
          <a className="btn-quiet" href={d.console_link} target="_blank" rel="noopener noreferrer">{t("alert_open_console")}</a>
        )}
      </div>
      <div className="card stack">
        <p>
          <span className="badge" data-tone={SEVERITY_TONES[d.severity]}>{word(SEVERITY_KEYS, d.severity)}</span>{" "}
          <strong data-role="alert-summary">{d.summary}</strong>
        </p>
        <p className="hint">{t("alert_fired_at", { at: formatTime(d.fired_at, lang) })}</p>
        {d.caveats.map((c) => <p key={c} className="notice">{c}</p>)}
        {d.grouped && <p className="hint">{t("alert_grouped_known_cause")}</p>}
      </div>
      <div className="card stack">
        <h2>{t("alert_evidence_title")}</h2>
        <p className="hint">{t("alert_evidence_hint")}</p>
        <Evidence alertId={id} kind={d.evidence_kind} />
      </div>
      <div className="card stack" data-role="deliveries">
        <h2>{t("alert_delivery_title")}</h2>
        <ul className="status-list">
          {d.deliveries.map((x) => (
            <li key={x.channel} data-delivery={x.status}>
              <span className="badge" data-tone={DELIVERY_TONES[x.status]}>{deliveryText(x)}</span>
              {x.attempts > 0 && <span className="hint"> {t("delivery_attempts", { n: String(x.attempts) })}</span>}
              {x.last_error && <span className="hint" data-role="delivery-error"> {x.last_error}</span>}
            </li>
          ))}
        </ul>
      </div>
      <form className="card stack" onSubmit={addNote} data-role="notes">
        <h2>{t("alert_notes_title")}</h2>
        {d.notes.length === 0 ? <p className="muted">{t("alert_notes_none")}</p> : (
          <ul className="stack">
            {d.notes.map((n) => (
              <li key={n.id}>
                <p>{n.body}</p>
                <p className="hint">{t("alert_note_by", { who: n.created_by, at: formatTime(n.created_at, lang) })}</p>
              </li>
            ))}
          </ul>
        )}
        <label className="block">
          {t("alert_note_add_label")}
          <textarea name="note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={4000} />
        </label>
        {noteError && <p className="form-error">{t(noteError.message_key, noteError.params)}</p>}
        <div className="actions">
          <button type="submit" className="btn-primary" disabled={!note.trim()}>{t("alert_note_add")}</button>
        </div>
      </form>
    </section>
  );
}

registerNav({ section: "main", path: "/alerts/:id", labelKey: "alert_detail_title", order: 11, component: AlertDetail,
              hidden: true });
