import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { DetectorStatusView, KnownView, LabelChoice, LabelSelector, LateralSettings, LateralView, PortClass, PortEntry } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";

const DETECTOR_KEYS: Record<string, string> = {
  fanout: "detector_name_fanout",
  new_admin_connection: "detector_name_new_admin_connection",
  pivot_chain: "detector_name_pivot_chain",
  blocked_surge: "detector_name_blocked_surge",
  non_admin_group: "detector_name_non_admin_group",
  cross_env: "detector_name_cross_env",
  account_fanout: "detector_name_account_fanout",
  unexpected_initiator: "detector_name_unexpected_initiator",
  peer_deviation: "detector_name_peer_deviation",
  volume_surge: "detector_name_volume_surge",
  account_new_source: "detector_name_account_new_source",
  suspicious_tool: "detector_name_suspicious_tool",
  new_process: "detector_name_new_process",
  auth_to_non_dc: "detector_name_auth_to_non_dc",
  new_dc_client: "detector_name_new_dc_client",
  directory_surge: "detector_name_directory_surge",
};
// The allowed-traffic anomaly detectors (spec §6.5.8), listed apart from the lateral-movement ones.
const ANOMALY_DETECTORS = new Set(["peer_deviation", "volume_surge", "account_new_source", "suspicious_tool", "new_process",
                                   "auth_to_non_dc", "new_dc_client", "directory_surge"]);
const CLASS_KEYS: Record<string, string> = {
  remote: "port_class_remote", directory: "port_class_directory", database: "port_class_database",
};
const STATE_KEYS: Record<string, string> = {
  ok: "detector_state_ok",
  disabled: "detector_state_disabled",
  accumulating: "detector_state_accumulating",
  no_data: "detector_state_no_data",
  collection_off: "detector_state_collection_off",
  incomplete: "detector_state_incomplete",
};
const STATE_TONES: Record<string, string> = { ok: "ok", incomplete: "warn", no_data: "warn", accumulating: "info" };
const SOURCE_KEYS: Record<string, string> = { builtin: "port_source_builtin", pce: "port_source_pce", added: "port_source_added" };
const SETTING_KEYS: Record<string, string> = { critical_assets: "lateral_critical_title", admin_groups: "lateral_admin_title" };
// Detector thresholds and graph settings, shown as text while edited.
const NUMBERS: { key: string; labelKey: string }[] = [
  { key: "graph_hops", labelKey: "lateral_graph_hops" },
  { key: "observation_days", labelKey: "lateral_observation_days" },
  { key: "fanout_targets", labelKey: "det_fanout_targets" },
  { key: "fanout_window_minutes", labelKey: "det_fanout_window" },
  { key: "account_fanout_targets", labelKey: "det_account_targets" },
  { key: "account_fanout_window_minutes", labelKey: "det_account_window" },
  { key: "chain_window_minutes", labelKey: "det_chain_window" },
  { key: "blocked_targets", labelKey: "det_blocked_targets" },
  { key: "blocked_window_minutes", labelKey: "det_blocked_window" },
  { key: "blocked_surge_factor", labelKey: "det_blocked_factor" },
  { key: "precursor_hours", labelKey: "det_precursor_hours" },
  { key: "peer_min_group", labelKey: "det_peer_min_group" },
  { key: "volume_surge_factor", labelKey: "det_volume_factor" },
  { key: "volume_min_connections", labelKey: "det_volume_min_connections" },
  { key: "volume_min_mb", labelKey: "det_volume_min_mb" },
  { key: "directory_min_connections", labelKey: "det_directory_min_connections" },
  { key: "directory_min_sources", labelKey: "det_directory_min_sources" },
  { key: "directory_followup_minutes", labelKey: "det_directory_followup" },
  { key: "account_history_days", labelKey: "det_account_history" },
  { key: "process_history_days", labelKey: "det_process_history" },
];
const GRAPH_FIELDS = new Set(["graph_hops", "observation_days"]);

function label(keys: Record<string, string>, value: string): string {
  const key = keys[value];
  return key ? t(key) : value;
}

function proto(p: number | null): string {
  if (p === null) return t("proto_any");
  return p === 6 ? "TCP" : p === 17 ? "UDP" : String(p);
}

function portText(p: PortEntry): string {
  return `${p.port}/${proto(p.proto)}`;
}

function samePort(a: PortEntry, b: PortEntry): boolean {
  return a.port === b.port && a.proto === b.proto;
}

function asText(params: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]));
}

function toNumbers(s: LateralSettings): Record<string, string> {
  const d = s.detectors as unknown as Record<string, number>;
  return Object.fromEntries(NUMBERS.map(({ key }) => [key, String(GRAPH_FIELDS.has(key) ? (s as unknown as Record<string, number>)[key] : d[key])]));
}

function detectorLine(d: DetectorStatusView): string {
  return d.reason_key ? t(d.reason_key, asText(d.params)) : "";
}

function listText(items: readonly string[]): string {
  return items.join(", ");
}

function splitList(text: string): string[] {
  return text.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
}

function DetectorList({ items, titleKey }: { items: DetectorStatusView[]; titleKey: string }) {
  if (items.length === 0) return null;
  return (
    <>
      <h3>{t(titleKey)}</h3>
      <ul className="status-list">
        {items.map((d) => (
          <li key={d.detector} data-detector={d.detector}>
            <span className="status-name">{label(DETECTOR_KEYS, d.detector)}</span>
            <span className="badge" data-tone={STATE_TONES[d.state] ?? "neutral"}>{label(STATE_KEYS, d.state)}</span>
            {d.reason_key && <span className="hint">{detectorLine(d)}</span>}
          </li>
        ))}
      </ul>
    </>
  );
}

/** Detections marked known from an alert (spec §6.5.8): still recorded, grouped instead of sent. */
function KnownMarks() {
  const lang = useLang();
  const [items, setItems] = useState<KnownView[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    void call("system.lateral.known").then((env) => {
      if (env.ok && env.data) setItems(env.data.items);
      else setError(env.error);
    });
  }, []);
  async function remove(id: number) {
    const env = await call("system.lateral.known_delete", undefined, { mark_id: String(id) });
    if (env.ok && env.data) setItems(env.data.items);
    else setError(env.error);
  }
  return (
    <div className="card stack" data-role="known-detections">
      <h2>{t("lateral_known_title")}</h2>
      <p className="hint">{t("lateral_known_hint")}</p>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {items !== null && items.length === 0 && <p className="muted">{t("lateral_known_none")}</p>}
      {items !== null && items.length > 0 && (
        <ul className="stack">
          {items.map((m) => (
            <li key={m.id} data-known={m.id}>
              <strong>{label(DETECTOR_KEYS, m.detector)}</strong>{" "}
              {m.fingerprint ? m.subject_key : t("lateral_known_scope_all", { subject: m.subject_key })}
              <p>{m.reason}</p>
              <p className="hint">
                {t("alert_note_by", { who: m.created_by, at: formatTime(m.created_at, lang) })}{" "}
                <button type="button" className="btn-quiet" onClick={() => void remove(m.id)}>{t("lateral_known_remove")}</button>
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Pick key=value from the labels the current inventory carries. */
function LabelPicker({ name, choices, selected, onChange }: {
  name: string; choices: LabelChoice[]; selected: LabelSelector[]; onChange: (next: LabelSelector[]) => void;
}) {
  const [key, setKey] = useState(choices[0]?.key ?? "");
  const choice = choices.find((c) => c.key === key);
  const [value, setValue] = useState("");
  const add = () => {
    const v = value || choice?.values[0] || "";
    if (!key || !v || selected.some((s) => s.key === key && s.value === v)) return;
    onChange([...selected, { key, value: v }]);
  };
  return (
    <div className="stack" data-picker={name}>
      {selected.length === 0 ? <p className="muted">{t("lateral_none_set")}</p> : (
        <ul className="chips">
          {selected.map((s) => (
            <li key={`${s.key}=${s.value}`} className="chip">
              {`${s.key}=${s.value}`}
              <button type="button" className="btn-quiet" aria-label={t("lateral_remove_label")}
                      onClick={() => onChange(selected.filter((x) => x !== s))}>×</button>
            </li>
          ))}
        </ul>
      )}
      <div className="row">
        <label>
          {t("lateral_label_key")}
          <select name={`${name}_key`} value={key} onChange={(e) => { setKey(e.target.value); setValue(""); }}>
            {choices.map((c) => <option key={c.key} value={c.key}>{c.key}</option>)}
          </select>
        </label>
        <label>
          {t("lateral_label_value")}
          <select name={`${name}_value`} value={value || choice?.values[0] || ""} onChange={(e) => setValue(e.target.value)}>
            {(choice?.values ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <button type="button" className="btn-quiet" onClick={add}>{t("lateral_add_label")}</button>
      </div>
      {choice?.truncated && <p className="hint">{t("lateral_labels_truncated", { n: "500" })}</p>}
    </div>
  );
}

export function Lateral() {
  const lang = useLang();
  const [view, setView] = useState<LateralView | null>(null);
  const [settings, setSettings] = useState<LateralSettings | null>(null);
  const [numbers, setNumbers] = useState<Record<string, string>>({});
  const [processes, setProcesses] = useState<Record<string, string>>({});
  const [newPort, setNewPort] = useState<{ port: string; proto: string; category: PortClass }>({ port: "", proto: "6", category: "remote" });
  const [lists, setLists] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = (v: LateralView) => {
    setView(v);
    setSettings(v.settings);
    setNumbers(toNumbers(v.settings));
    setProcesses(Object.fromEntries(v.settings.expected_initiators.map((e) => [portText(e), e.processes.join(", ")])));
    setLists({ peer_group_keys: listText(v.settings.peer_group_keys), directory_server_ips: listText(v.settings.directory_server_ips),
               suspicious_tools: listText(v.settings.suspicious_tools) });
  };

  useEffect(() => {
    void call("system.lateral.get").then((env) => {
      if (env.ok && env.data) load(env.data);
      else setError(env.error);
    });
  }, []);

  const change = (next: LateralSettings) => {
    setSettings(next);
    setSaved(false);
  };

  function collect(s: LateralSettings): LateralSettings {
    const n = (k: string) => Number((numbers[k] ?? "").trim());
    const detectors = { ...s.detectors } as unknown as Record<string, number | boolean>;
    for (const { key } of NUMBERS) if (!GRAPH_FIELDS.has(key)) detectors[key] = n(key);
    return {
      ...s,
      graph_hops: n("graph_hops"),
      observation_days: n("observation_days"),
      detectors: detectors as unknown as LateralSettings["detectors"],
      peer_group_keys: splitList(lists.peer_group_keys ?? "") as LateralSettings["peer_group_keys"],
      directory_server_ips: splitList(lists.directory_server_ips ?? ""),
      suspicious_tools: splitList(lists.suspicious_tools ?? ""),
      expected_initiators: s.expected_initiators.map((e) => ({
        ...e,
        processes: (processes[portText(e)] ?? "").split(",").map((p) => p.trim()).filter(Boolean) as [string, ...string[]],
      })),
    };
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!settings || !view) return;
    setBusy(true);
    const env = await call("system.lateral.update", { revision: view.revision, settings: collect(settings) });
    setBusy(false);
    if (env.ok && env.data) {
      load(env.data);
      setError(null);
      setSaved(true);
    } else {
      setError(env.error);
      setSaved(false);
    }
  }

  if (!view || !settings) {
    return (
      <section className="page">
        <h1>{t("nav_system_lateral")}</h1>
        {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      </section>
    );
  }
  const st = view.status;
  const removed = settings.removed_admin_ports;
  const addPort = () => {
    const port = Number(newPort.port);
    if (!Number.isInteger(port) || port < 0 || port > 65535) return;
    const entry: PortEntry = { port, proto: newPort.proto === "" ? null : Number(newPort.proto), category: newPort.category };
    if (settings.extra_admin_ports.some((p) => samePort(p, entry))) return;
    change({ ...settings, extra_admin_ports: [...settings.extra_admin_ports, entry] });
    setNewPort({ port: "", proto: "6", category: "remote" });
  };
  return (
    <section className="page stack">
      <h1>{t("nav_system_lateral")}</h1>
      <div className="card" data-role="lateral-status">
        <h2>{t("lateral_status_title")}</h2>
        {!st.collected && (
          <p className="notice">
            {t("lateral_needs_traffic")} <Link to="/system/collection">{t("lateral_go_collection")}</Link>
          </p>
        )}
        <p data-role="baseline">
          {t("lateral_baseline", { days: String(st.baseline_days), required: String(st.baseline_required) })}
          {st.baseline_backfilling && <span className="hint"> {t("lateral_baseline_backfilling")}</span>}
        </p>
        <p className="hint">
          {st.detect_last_ok_at ? t("lateral_detect_last", { at: formatTime(st.detect_last_ok_at, lang) }) : t("lateral_detect_never")}
          {" · "}
          {st.exposure_last_ok_at ? t("lateral_exposure_last", { at: formatTime(st.exposure_last_ok_at, lang) }) : t("lateral_exposure_never")}
        </p>
        <DetectorList titleKey="lateral_detectors_lateral" items={st.detectors.filter((d) => !ANOMALY_DETECTORS.has(d.detector))} />
        <DetectorList titleKey="lateral_detectors_anomaly" items={st.detectors.filter((d) => ANOMALY_DETECTORS.has(d.detector))} />
        {st.stale_selectors.map((s) => (
          <p key={`${s.setting}-${s.key}-${s.value}`} className="badge" data-tone="warn">
            {t("lateral_stale_selector", { setting: label(SETTING_KEYS, s.setting), key: s.key, value: s.value })}
          </p>
        ))}
      </div>

      <form className="card stack" onSubmit={save} data-role="lateral-settings">
        <h2>{t("lateral_settings_title")}</h2>

        <div className="block">
        <h3>{t("lateral_ports_title")}</h3>
        <p className="hint">{t("lateral_ports_hint")}</p>
        <div className="table-wrap">
        <table className="table" data-role="admin-ports">
          <tbody>
            {view.effective_ports.map((p) => (
              <tr key={`${p.source}-${p.port}-${p.proto}`} data-port={p.port}>
                <td>{portText(p)}</td>
                <td>{p.name ?? ""}</td>
                <td><span className="badge" data-tone="info" data-class={p.category}>{label(CLASS_KEYS, p.category)}</span></td>
                <td><span className="badge" data-tone="neutral">{label(SOURCE_KEYS, p.source)}</span></td>
                <td>
                  <button type="button" className="btn-quiet" onClick={() => p.source === "added"
                    ? change({ ...settings, extra_admin_ports: settings.extra_admin_ports.filter((x) => !samePort(x, p)) })
                    : change({ ...settings, removed_admin_ports: [...removed, { port: p.port, proto: p.proto }] })}>
                    {t("lateral_port_remove")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        {removed.length > 0 && (
          <p className="hint">
            {t("lateral_removed_ports")}{" "}
            {removed.map((p) => (
              <button key={portText(p)} type="button" className="btn-quiet"
                      onClick={() => change({ ...settings, removed_admin_ports: removed.filter((x) => !samePort(x, p)) })}>
                {t("lateral_port_restore", { port: portText(p) })}
              </button>
            ))}
          </p>
        )}
        <div className="row">
          <label>
            {t("lateral_port")}
            <input name="new_port" inputMode="numeric" value={newPort.port} onChange={(e) => setNewPort({ ...newPort, port: e.target.value })} />
          </label>
          <label>
            {t("lateral_proto")}
            <select name="new_proto" value={newPort.proto} onChange={(e) => setNewPort({ ...newPort, proto: e.target.value })}>
              <option value="6">TCP</option>
              <option value="17">UDP</option>
              <option value="">{t("proto_any")}</option>
            </select>
          </label>
          <label>
            {t("lateral_port_class")}
            <select name="new_category" value={newPort.category} onChange={(e) => setNewPort({ ...newPort, category: e.target.value as PortClass })}>
              {Object.keys(CLASS_KEYS).map((c) => <option key={c} value={c}>{label(CLASS_KEYS, c)}</option>)}
            </select>
          </label>
          <button type="button" className="btn-quiet" onClick={addPort}>{t("lateral_add_port")}</button>
        </div>
        <label className="check">
          <input type="checkbox" name="include_pce_admin_services" checked={settings.include_pce_admin_services}
                 onChange={(e) => change({ ...settings, include_pce_admin_services: e.target.checked })} />
          {t("lateral_include_pce")}
        </label>
        </div>

        <div className="block">
        <h3>{t("lateral_critical_title")}</h3>
        <p className="hint">{t("lateral_critical_hint")}</p>
        <LabelPicker name="critical_assets" choices={view.label_choices} selected={settings.critical_assets}
                     onChange={(next) => change({ ...settings, critical_assets: next })} />
        </div>
        <div className="block">
        <h3>{t("lateral_admin_title")}</h3>
        <p className="hint">{t("lateral_admin_hint")}</p>
        <LabelPicker name="admin_groups" choices={view.label_choices} selected={settings.admin_groups}
                     onChange={(next) => change({ ...settings, admin_groups: next })} />
        </div>
        <label>
          {t("lateral_env_key")}
          <input name="environment_label_key" value={settings.environment_label_key}
                 onChange={(e) => change({ ...settings, environment_label_key: e.target.value })} />
        </label>

        <div className="block" data-role="anomaly-settings">
        <h3>{t("lateral_anomaly_title")}</h3>
        <p className="hint">{t("lateral_anomaly_hint")}</p>
        <label>
          {t("lateral_peer_keys")}
          <input name="peer_group_keys" value={lists.peer_group_keys ?? ""}
                 onChange={(e) => { setLists({ ...lists, peer_group_keys: e.target.value }); setSaved(false); }} />
        </label>
        <p className="hint">{t("lateral_directory_hint")}</p>
        <LabelPicker name="directory_servers" choices={view.label_choices} selected={settings.directory_servers}
                     onChange={(next) => change({ ...settings, directory_servers: next })} />
        <label>
          {t("lateral_directory_ips")}
          <input name="directory_server_ips" value={lists.directory_server_ips ?? ""}
                 onChange={(e) => { setLists({ ...lists, directory_server_ips: e.target.value }); setSaved(false); }} />
        </label>
        <label className="block">
          {t("lateral_tools")}
          <textarea name="suspicious_tools" rows={3} value={lists.suspicious_tools ?? ""}
                    onChange={(e) => { setLists({ ...lists, suspicious_tools: e.target.value }); setSaved(false); }} />
        </label>
        </div>

        <h3>{t("lateral_detectors_settings_title")}</h3>
        <div className="form-grid">
          {NUMBERS.map(({ key, labelKey }) => (
            <label key={key}>
              {t(labelKey)}
              <input name={key} inputMode="decimal" value={numbers[key] ?? ""}
                     onChange={(e) => { setNumbers({ ...numbers, [key]: e.target.value }); setSaved(false); }} />
              {key === "observation_days" && Number(numbers[key]) > st.observation_days_used && (
                <span className="hint">{t("lateral_observation_capped", { days: String(st.observation_days_used) })}</span>
              )}
            </label>
          ))}
          <label className="check">
            <input type="checkbox" name="exclude_system_accounts" checked={settings.detectors.exclude_system_accounts}
                   onChange={(e) => change({ ...settings, detectors: { ...settings.detectors, exclude_system_accounts: e.target.checked } })} />
            {t("det_exclude_system")}
          </label>
        </div>

        <h3>{t("lateral_expected_title")}</h3>
        <p className="hint">{t("lateral_expected_hint")}</p>
        <div className="form-grid">
          {settings.expected_initiators.map((e) => (
            <label key={portText(e)}>
              {portText(e)}
              <input name={`expected_${e.port}_${e.proto ?? "any"}`} value={processes[portText(e)] ?? ""}
                     onChange={(ev) => { setProcesses({ ...processes, [portText(e)]: ev.target.value }); setSaved(false); }} />
            </label>
          ))}
        </div>

        {error && <div className="form-error" role="alert" data-field={error.field ?? ""}>{t(error.message_key, error.params)}</div>}
        {saved && <p className="form-ok" role="status">{t("saved_ok")}</p>}
        <div className="actions">
          <button type="submit" className="btn-primary" disabled={busy}>{t("btn_save")}</button>
        </div>
      </form>
      <KnownMarks />
    </section>
  );
}

registerNav({ section: "system", path: "/system/lateral", labelKey: "nav_system_lateral", order: 14, component: Lateral });
