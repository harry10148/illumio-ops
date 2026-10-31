// SIEM forwarding (spec §6.5 SIEM 轉送, P7): where each destination stands, then the destinations themselves. Three
// sources — PCE audit events, this product's detections and alerts, and (optional) new connections; never traffic
// records. In lightweight mode the traffic-made sources say they need alert mode instead of showing 0.
import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type {
  SiemDestinationInput, SiemSettingsInput, SiemSettingsView, SiemSourceStatus, SiemStatusView, SiemTestView,
} from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";

type Source = SiemDestinationInput["sources"][number];
type Decision = SiemDestinationInput["new_connection_decisions"][number];
const SOURCES: Source[] = ["audit", "findings", "new_connections"];
const SOURCE_KEYS: Record<Source, string> = {
  audit: "siem_src_audit", findings: "siem_src_findings", new_connections: "siem_src_new_connections",
};
const SOURCE_HINT_KEYS: Record<Source, string> = {
  audit: "siem_src_audit_hint", findings: "siem_src_findings_hint", new_connections: "siem_src_new_connections_hint",
};
const CURSOR_KEYS: Record<string, string> = {
  audit: "siem_cursor_audit", alerts: "siem_cursor_alerts", detections: "siem_cursor_detections",
  new_connections: "siem_cursor_new_connections",
};
const STATE_KEYS: Record<SiemSourceStatus["state"], string> = {
  ok: "siem_state_ok", behind: "siem_state_behind", failing: "siem_state_failing", dlq_full: "siem_state_dlq_full",
  waiting: "siem_state_waiting", needs_alert_mode: "siem_state_needs_alert_mode",
  baseline_building: "siem_state_baseline_building", off: "siem_state_off",
};
const STATE_TONES: Record<SiemSourceStatus["state"], string> = {
  ok: "ok", behind: "warn", failing: "bad", dlq_full: "bad", waiting: "info", needs_alert_mode: "warn",
  baseline_building: "info", off: "info",
};
const TRANSPORTS: SiemDestinationInput["transport"][] = ["udp", "tcp", "tls", "hec"];
const TRANSPORT_KEYS: Record<SiemDestinationInput["transport"], string> = {
  udp: "siem_transport_udp", tcp: "siem_transport_tcp", tls: "siem_transport_tls", hec: "siem_transport_hec",
};
const FORMATS: SiemDestinationInput["format"][] = ["cef_pce", "syslog_cef_pce", "cef", "syslog_cef", "json", "syslog_json"];
const FORMAT_KEYS: Record<SiemDestinationInput["format"], string> = {
  cef_pce: "siem_format_cef_pce", syslog_cef_pce: "siem_format_syslog_cef_pce", cef: "siem_format_cef",
  syslog_cef: "siem_format_syslog_cef", json: "siem_format_json", syslog_json: "siem_format_syslog_json",
};
const DECISIONS: Decision[] = ["allowed", "potentially_blocked", "blocked", "unknown"];
const DECISION_KEYS: Record<Decision, string> = {
  allowed: "decision_allowed", potentially_blocked: "decision_potentially_blocked", blocked: "decision_blocked",
  unknown: "decision_unknown",
};
const DEFAULT_PORTS: Record<string, number> = { udp: 514, tcp: 514, tls: 6514, hec: 8088 };

function newId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function blank(): SiemDestinationInput {
  return {
    id: newId(), name: "", enabled: true, transport: "tcp", format: "cef_pce", host: "", port: 514, framing: "lf",
    verify_tls: true, hec_token: "", batch_size: 100, max_retries: 10, sources: ["audit"], new_connection_decisions: [],
    mask_pii: false,
  };
}

function StatusTable({ status }: { status: SiemStatusView }) {
  const lang = useLang();
  if (status.destinations.length === 0) return <p className="muted">{t("siem_no_destinations")}</p>;
  return (
    <div className="table-wrap">
      <table className="table" data-role="siem-status">
        <thead><tr><th>{t("siem_col_destination")}</th><th>{t("siem_col_source")}</th><th>{t("siem_col_state")}</th>
          <th>{t("siem_col_pending")}</th><th>{t("siem_col_sent")}</th><th>{t("siem_col_last_sent")}</th>
          <th>{t("siem_col_dropped")}</th><th>{t("siem_col_error")}</th></tr></thead>
        <tbody>
          {status.destinations.flatMap((d) => d.sources.map((s, i) => (
            <tr key={`${d.id}-${s.source}`} data-dest={d.name} data-source={s.source} data-state={s.state}>
              {i === 0 && (
                <td rowSpan={d.sources.length}>
                  <strong>{d.name}</strong>
                  <div className="hint">{t(TRANSPORT_KEYS[d.transport])} · {d.host}:{d.port}</div>
                  <div className="hint">
                    <Link to={`/siem/dlq?destination=${d.id}`} data-role="siem-dlq-link">
                      {t("siem_dlq_count", { n: String(d.dlq), max: String(d.dlq_max) })}
                    </Link>
                  </div>
                </td>
              )}
              <td>{t(CURSOR_KEYS[s.source] ?? s.source)}</td>
              <td><span className="badge" data-tone={STATE_TONES[s.state]}>{t(STATE_KEYS[s.state])}</span>
                {s.state === "needs_alert_mode" && <div className="hint"><Link to="/system/collection">{t("siem_go_collection")}</Link></div>}
                {s.state === "baseline_building" && <div className="hint">{t("siem_baseline_hint", { days: String(status.baseline_days) })}</div>}
                {s.source === "alerts" && status.lightweight && <div className="hint">{t("siem_alerts_lightweight")}</div>}
              </td>
              <td className="num">{s.pending === null ? "—" : s.pending.toLocaleString()}</td>
              <td className="num">{s.sent.toLocaleString()}</td>
              <td className="nowrap">{s.last_sent_at ? formatTime(s.last_sent_at, lang) : "—"}</td>
              <td className="num">{s.dropped ? <span className="badge" data-tone="warn">{s.dropped.toLocaleString()}</span> : "0"}</td>
              <td>{s.head_attempts > 0 && <div className="hint" data-role="siem-stuck">{t("siem_stuck", { n: String(s.head_attempts) })}</div>}
                {s.last_error ? <span className="hint" data-role="siem-error">{s.last_error === "dlq_full" ? t("siem_state_dlq_full") : s.last_error}{s.last_error_at ? ` · ${formatTime(s.last_error_at, lang)}` : ""}</span> : "—"}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </div>
  );
}

function DestinationCard({ d, lightweight, onChange, onRemove }: {
  d: SiemDestinationInput; lightweight: boolean; onChange: (d: SiemDestinationInput) => void; onRemove: () => void;
}) {
  const [result, setResult] = useState<SiemTestView | ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof SiemDestinationInput>(k: K, v: SiemDestinationInput[K]) => onChange({ ...d, [k]: v });
  const toggle = <T,>(list: T[], v: T, on: boolean): T[] => (on ? [...list.filter((x) => x !== v), v] : list.filter((x) => x !== v));
  const stream = d.transport === "tcp" || d.transport === "tls";
  const tls = d.transport === "tls" || d.transport === "hec";
  const caPath = typeof d.verify_tls === "string" ? d.verify_tls : "";

  async function test() {
    setBusy(true);
    setResult(null);
    const env = await call("siem.destination.test", { destination: d });
    setBusy(false);
    setResult(env.ok && env.data ? env.data : (env.error as ApiError));
  }

  return (
    <div className="card stack" data-role="siem-destination" data-name={d.name}>
      <div className="row">
        <label className="check">
          <input type="checkbox" name="siem_dest_enabled" checked={d.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          {t("siem_dest_enabled")}
        </label>
        <button type="button" className="btn-quiet" onClick={onRemove} data-role="siem-remove">{t("siem_remove")}</button>
      </div>
      <div className="form-grid">
        <label>{t("siem_name")}
          <input name="siem_name" value={d.name} maxLength={64} required onChange={(e) => set("name", e.target.value)} />
        </label>
        <label>{t("siem_transport")}
          <select name="siem_transport" value={d.transport}
                  onChange={(e) => onChange({ ...d, transport: e.target.value as SiemDestinationInput["transport"],
                                              port: DEFAULT_PORTS[e.target.value] ?? d.port })}>
            {TRANSPORTS.map((x) => <option key={x} value={x}>{t(TRANSPORT_KEYS[x])}</option>)}
          </select>
        </label>
        <label>{t("siem_host")}
          <input name="siem_host" value={d.host} onChange={(e) => set("host", e.target.value.trim())} />
        </label>
        <label>{t("siem_port")}
          <input name="siem_port" type="number" min={1} max={65535} value={d.port} onChange={(e) => set("port", Number(e.target.value))} />
        </label>
        <label>{t("siem_format")}
          <select name="siem_format" value={d.format} onChange={(e) => set("format", e.target.value as SiemDestinationInput["format"])}>
            {FORMATS.map((x) => <option key={x} value={x}>{t(FORMAT_KEYS[x])}</option>)}
          </select>
          <span className="hint">{t("siem_format_hint")}</span>
        </label>
        {stream && (
          <label>{t("siem_framing")}
            <select name="siem_framing" value={d.framing} onChange={(e) => set("framing", e.target.value as SiemDestinationInput["framing"])}>
              <option value="lf">{t("siem_framing_lf")}</option>
              <option value="octet_counting">{t("siem_framing_octet")}</option>
            </select>
          </label>
        )}
        {tls && (
          <>
            <label className="check">
              <input type="checkbox" name="siem_verify_tls" checked={d.verify_tls !== false}
                     onChange={(e) => set("verify_tls", e.target.checked ? (caPath || true) : false)} />
              {t("siem_verify_tls")}
            </label>
            <label>{t("siem_ca_bundle")}
              <input name="siem_ca_bundle" value={caPath} placeholder="/etc/ssl/certs/siem-ca.pem" disabled={d.verify_tls === false}
                     onChange={(e) => set("verify_tls", e.target.value.trim() || true)} />
            </label>
          </>
        )}
        {d.transport === "hec" && (
          <label>{t("siem_hec_token")}
            <input name="siem_hec_token" type="password" autoComplete="off" value={d.hec_token}
                   onChange={(e) => set("hec_token", e.target.value)} />
            <span className="hint">{t("channel_secret_hint")}</span>
          </label>
        )}
      </div>
      <fieldset className="stack">
        <legend>{t("siem_sources")}</legend>
        {SOURCES.map((s) => (
          <label key={s} className="check">
            <input type="checkbox" name={`siem_source_${s}`} checked={d.sources.includes(s)}
                   onChange={(e) => set("sources", toggle(d.sources, s, e.target.checked))} />
            <span>{t(SOURCE_KEYS[s])} <span className="hint">{t(SOURCE_HINT_KEYS[s])}</span></span>
          </label>
        ))}
        {lightweight && (d.sources.includes("findings") || d.sources.includes("new_connections")) && (
          <p className="notice" data-role="siem-needs-alert-mode">
            {t("siem_needs_alert_mode")} <Link to="/system/collection">{t("siem_go_collection")}</Link>
          </p>
        )}
        {d.sources.includes("new_connections") && (
          <div className="row" data-role="siem-decisions">
            <span className="hint">{t("siem_decisions")}</span>
            {DECISIONS.map((x) => (
              <label key={x} className="check">
                <input type="checkbox" name={`siem_decision_${x}`} checked={d.new_connection_decisions.includes(x)}
                       onChange={(e) => set("new_connection_decisions", toggle(d.new_connection_decisions, x, e.target.checked))} />
                {t(DECISION_KEYS[x])}
              </label>
            ))}
          </div>
        )}
      </fieldset>
      <label className="check">
        <input type="checkbox" name="siem_mask_pii" checked={d.mask_pii} onChange={(e) => set("mask_pii", e.target.checked)} />
        <span>{t("siem_mask_pii")} <span className="hint">{t("siem_mask_pii_hint")}</span></span>
      </label>
      <div className="row">
        <button type="button" className="btn-quiet" disabled={busy} onClick={() => void test()} data-role="siem-test">{t("siem_test")}</button>
        {result && ("message_key" in result
          ? <span className="form-error" data-role="siem-test-result">{t(result.message_key, result.params)}</span>
          : <span className={result.ok ? "form-ok" : "form-error"} data-role="siem-test-result">
              {result.ok ? t("siem_test_ok") : t("siem_test_failed", { error: result.error ?? "" })}
            </span>)}
      </div>
    </div>
  );
}

export function Siem() {
  const [view, setView] = useState<SiemSettingsView | null>(null);
  const [siem, setSiem] = useState<SiemSettingsInput | null>(null);
  const [status, setStatus] = useState<SiemStatusView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  const loadStatus = () => void call("siem.status").then((env) => {
    if (env.ok && env.data) setStatus(env.data);
    else setError(env.error);
  });
  useEffect(() => {
    void call("siem.settings.get").then((env) => {
      if (env.ok && env.data) { setView(env.data); setSiem(env.data.siem); }
      else setError(env.error);
    });
    loadStatus();
  }, []);

  if (!view || !siem) {
    return (
      <section className="page">
        <h1>{t("nav_siem")}</h1>
        {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      </section>
    );
  }
  const change = (next: SiemSettingsInput) => { setSiem(next); setSaved(false); };
  const setDest = (i: number, d: SiemDestinationInput) => change({ ...siem, destinations: siem.destinations.map((x, j) => (j === i ? d : x)) });

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!view || !siem) return;
    const env = await call("siem.settings.update", { revision: view.revision, siem });
    if (env.ok && env.data) { setView(env.data); setSiem(env.data.siem); setError(null); setSaved(true); loadStatus(); }
    else { setError(env.error); setSaved(false); }
  }

  return (
    <section className="page stack">
      <h1>{t("nav_siem")}</h1>
      <p className="hint">{t("siem_intro")}</p>
      <div className="card stack">
        <div className="row">
          <h2>{t("siem_status_title")}</h2>
          <button type="button" className="btn-quiet" onClick={loadStatus}>{t("siem_refresh")}</button>
          <Link to="/siem/dlq">{t("siem_dlq_title")}</Link>
        </div>
        {status && !status.enabled && <p className="notice" data-role="siem-off">{t("siem_off")}</p>}
        {status && <StatusTable status={status} />}
      </div>
      <form className="stack" onSubmit={save} data-role="siem-settings">
        <label className="check">
          <input type="checkbox" name="siem_enabled" checked={siem.enabled} onChange={(e) => change({ ...siem, enabled: e.target.checked })} />
          {t("siem_enabled")}
        </label>
        {siem.destinations.map((d, i) => (
          <DestinationCard key={d.id} d={d} lightweight={status?.lightweight ?? false} onChange={(x) => setDest(i, x)}
                           onRemove={() => change({ ...siem, destinations: siem.destinations.filter((_, j) => j !== i) })} />
        ))}
        <div className="row">
          <button type="button" className="btn-quiet" disabled={siem.destinations.length >= 20} data-role="siem-add"
                  onClick={() => change({ ...siem, destinations: [...siem.destinations, blank()] })}>{t("siem_add")}</button>
        </div>
        <details className="card">
          <summary>{t("siem_advanced")}</summary>
          <div className="form-grid">
            <label>{t("siem_tick_seconds")}
              <input name="siem_tick_seconds" type="number" min={10} max={600} value={siem.tick_seconds}
                     onChange={(e) => change({ ...siem, tick_seconds: Number(e.target.value) })} />
            </label>
            <label>{t("siem_dlq_max")}
              <input name="siem_dlq_max" type="number" min={100} max={1000000} value={siem.dlq_max_per_dest}
                     onChange={(e) => change({ ...siem, dlq_max_per_dest: Number(e.target.value) })} />
            </label>
            <label>{t("siem_backlog_warn")}
              <input name="siem_backlog_warn" type="number" min={1000} max={10000000} value={siem.backlog_warn_rows}
                     onChange={(e) => change({ ...siem, backlog_warn_rows: Number(e.target.value) })} />
            </label>
          </div>
        </details>
        {error && <p className="form-error" data-field={error.field ?? ""}>{t(error.message_key, error.params)}</p>}
        {saved && <p className="form-ok" role="status">{t("saved_ok")}</p>}
        <div className="actions">
          <button type="submit" className="btn-primary">{t("btn_save")}</button>
        </div>
      </form>
    </section>
  );
}

registerNav({ section: "main", path: "/siem", labelKey: "nav_siem", order: 22, component: Siem });
