import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { CollectionSettings, CollectionStatus, SourceStatus } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";

const SOURCE_KEYS: Record<string, string> = {
  traffic: "source_traffic",
  events: "source_events",
  inventory: "source_inventory",
  ransomware: "source_ransomware",
  backfill: "source_backfill",
};
const GAP_KIND_KEYS: Record<string, string> = { truncated: "gap_kind_truncated", failed: "gap_kind_failed" };
const REASON_KEYS: Record<string, string> = {
  another_pce: "reason_another_pce",
  rate_limit: "reason_rate_limit",
  timeout: "reason_timeout",
  unreachable: "reason_unreachable",
  tls: "reason_tls",
  auth: "reason_auth",
  pce_error: "reason_pce_error",
  other: "reason_other",
};
const CAP_KEYS: Record<string, string> = {
  ransomware_risk: "cap_ransomware_risk",
  ransomware_org_summary: "cap_ransomware_org_summary",
  visibility_level: "cap_visibility_level",
  tamper_signal: "cap_tamper_signal",
  draft_recompute: "cap_draft_recompute",
};
const CAP_STATE_KEYS: Record<string, string> = {
  supported: "cap_state_supported",
  unsupported: "cap_state_unsupported",
  unknown: "cap_state_unknown",
};

/** A label from a key table; an unknown value is shown as it is rather than guessed. */
function label(keys: Record<string, string>, value: string): string {
  const key = keys[value];
  return key ? t(key) : value;
}

function ago(seconds: number): string {
  if (seconds < 120) return t("ago_seconds", { n: String(seconds) });
  if (seconds < 7200) return t("ago_minutes", { n: String(Math.round(seconds / 60)) });
  return t("ago_hours", { n: String(Math.round(seconds / 3600)) });
}

function bytes(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function sourceLine(s: SourceStatus): { tone: string; text: string } {
  if (s.consecutive_failures > 0) {
    const reason = label(REASON_KEYS, s.last_error_reason ?? "other");
    return { tone: "crit", text: t("collection_failing", { n: String(s.consecutive_failures), reason }) };
  }
  if (s.last_ok_at === null) return { tone: "neutral", text: t("collection_never_run") };
  const lag = ago(s.lag_seconds ?? 0);
  return s.stale ? { tone: "warn", text: t("collection_stale", { ago: lag }) } : { tone: "ok", text: t("collection_ok_ago", { ago: lag }) };
}

interface Form {
  enabled: boolean;
  traffic_min: string;
  events_min: string;
  inventory_min: string;
  rate: string;
  backfill_days: string;
  disk_gb: string;
  flow_days: string;
  event_days: string;
  rollup_days: string;
  baseline_days: string;
  archive_enabled: boolean;
  archive_days: string;
}

function toForm(c: CollectionSettings): Form {
  return {
    enabled: c.enabled,
    traffic_min: String(c.traffic_interval_seconds / 60),
    events_min: String(c.events_interval_seconds / 60),
    inventory_min: String(c.inventory_interval_seconds / 60),
    rate: String(c.rate_limit_per_minute),
    backfill_days: String(c.backfill_days),
    disk_gb: String(c.disk_free_warn_gb),
    flow_days: String(c.retention.flow_days),
    event_days: String(c.retention.event_days),
    rollup_days: String(c.retention.rollup_days),
    baseline_days: String(c.retention.baseline_days),
    archive_enabled: c.archive.enabled,
    archive_days: String(c.archive.retention_days),
  };
}

function fromForm(f: Form): CollectionSettings {
  const n = (v: string) => Number(v.trim());
  return {
    enabled: f.enabled,
    traffic_interval_seconds: Math.round(n(f.traffic_min) * 60),
    events_interval_seconds: Math.round(n(f.events_min) * 60),
    inventory_interval_seconds: Math.round(n(f.inventory_min) * 60),
    rate_limit_per_minute: n(f.rate),
    backfill_days: n(f.backfill_days),
    disk_free_warn_gb: n(f.disk_gb),
    retention: { flow_days: n(f.flow_days), event_days: n(f.event_days), rollup_days: n(f.rollup_days), baseline_days: n(f.baseline_days) },
    archive: { enabled: f.archive_enabled, retention_days: n(f.archive_days) },
  };
}

/** The two rules that span several fields are explained in words, not as "some fields are not valid". */
function settingsError(e: ApiError): string {
  if (e.field === "settings.retention") return t("err_retention_order");
  if (e.field === "settings") return t("err_archive_retention_short");
  return t(e.message_key, e.params);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function Collection() {
  const lang = useLang();
  const [status, setStatus] = useState<CollectionStatus | null>(null);
  const [revision, setRevision] = useState<number | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [range, setRange] = useState({ start: today(), end: today() });
  const [backfillNote, setBackfillNote] = useState<string | null>(null);
  const [backfillError, setBackfillError] = useState<ApiError | null>(null);

  const refresh = useCallback(async () => {
    const env = await call("system.collection.status");
    if (env.ok && env.data) setStatus(env.data);
  }, []);

  useEffect(() => {
    void call("system.collection.get").then((env) => {
      if (env.ok && env.data) {
        setRevision(env.data.revision);
        setForm(toForm(env.data.settings));
      } else setError(env.error);
    });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    if (!form) return;
    setForm({ ...form, [key]: value });
    setSaved(false);
  };

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form || revision === null) return;
    setBusy(true);
    const env = await call("system.collection.update", { revision, settings: fromForm(form) });
    setBusy(false);
    if (env.ok && env.data) {
      setRevision(env.data.revision);
      setForm(toForm(env.data.settings));
      setError(null);
      setSaved(true);
    } else {
      setError(env.error);
      setSaved(false);
    }
  }

  async function startBackfill(e: FormEvent) {
    e.preventDefault();
    const env = await call("system.collection.backfill", { start: range.start, end: range.end });
    if (env.ok && env.data) {
      setBackfillError(null);
      setBackfillNote(t("backfill_started", { start: range.start, end: range.end }));
      void refresh();
    } else {
      setBackfillNote(null);
      setBackfillError(env.error);
    }
  }

  const num = (key: keyof Form, text: string) => (
    <label>
      {text}
      <input name={key} inputMode="numeric" value={String(form?.[key] ?? "")}
             onChange={(e) => set(key, e.target.value as Form[typeof key])} />
    </label>
  );

  return (
    <section className="page stack">
      <h1>{t("nav_system_collection")}</h1>
      {status && (
        <div className="card" data-role="collection-status">
          <h2>{t("collection_status_title")}</h2>
          {!status.enabled && <p className="notice">{t("collection_disabled")}</p>}
          {!status.pce_configured && <p className="notice">{t("collection_pce_missing")}</p>}
          {status.binding_host && <p className="hint">{t("collection_bound_to", { host: status.binding_host })}</p>}
          <ul className="status-list">
            {status.sources.map((s) => {
              const line = sourceLine(s);
              return (
                <li key={s.source} data-source={s.source}>
                  <span className="status-name">{label(SOURCE_KEYS, s.source)}</span>
                  <span className="badge" data-tone={line.tone}>{line.text}</span>
                  {s.last_ok_at && <span className="hint">{t("collection_last_ok", { at: formatTime(s.last_ok_at, lang) })}</span>}
                  {s.consecutive_failures > 0 && s.last_error && <span className="hint">{s.last_error}</span>}
                </li>
              );
            })}
          </ul>
          <p className="hint">
            {t("capacity_line", { db: bytes(status.db_bytes), free: bytes(status.disk_free_bytes) })}
            {status.disk_low && <span className="badge" data-tone="warn">{t("capacity_low")}</span>}
          </p>
        </div>
      )}
      {status && (
        <div className="card" data-role="collection-gaps">
          <h2>{t("collection_gaps_title")}</h2>
          {status.open_gaps.length === 0 ? (
            <p className="muted">{t("collection_gaps_none")}</p>
          ) : (
            <ul className="status-list">
              {status.open_gaps.map((g) => (
                <li key={`${g.source}-${g.window_start}`} data-kind={g.kind}>
                  {t("gap_line", {
                    source: label(SOURCE_KEYS, g.source),
                    start: formatTime(g.window_start, lang),
                    end: formatTime(g.window_end, lang),
                    kind: label(GAP_KIND_KEYS, g.kind),
                  })}
                </li>
              ))}
            </ul>
          )}
          {status.open_gaps_truncated && <p className="hint">{t("collection_gaps_more")}</p>}
        </div>
      )}
      {status && (
        <div className="card" data-role="visibility">
          <h2>{t("visibility_title")}</h2>
          <ul className="status-list">
            <li>{t("visibility_sees_allowed", { n: String(status.visibility.sees_allowed ?? 0) })}</li>
            {(status.visibility.blocked_only ?? 0) > 0 && (
              <li><span className="badge" data-tone="warn">{t("visibility_blocked_only", { n: String(status.visibility.blocked_only) })}</span></li>
            )}
            {(status.visibility.off ?? 0) > 0 && (
              <li><span className="badge" data-tone="warn">{t("visibility_off", { n: String(status.visibility.off) })}</span></li>
            )}
            {(status.visibility.unknown ?? 0) > 0 && <li>{t("visibility_unknown", { n: String(status.visibility.unknown) })}</li>}
          </ul>
          {(status.visibility.blocked_only ?? 0) + (status.visibility.off ?? 0) > 0 && (
            <p className="hint">{t("visibility_explain")}</p>
          )}
          <h2 className="block">{t("capabilities_title")}</h2>
          <ul className="status-list">
            {Object.keys(CAP_KEYS).map((name) => (
              <li key={name} data-capability={name}>
                {t("capability_line", {
                  name: label(CAP_KEYS, name),
                  state: label(CAP_STATE_KEYS, status.capabilities[name] ?? "unknown"),
                })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {form && (
        <form className="card form-grid" onSubmit={save} data-role="collection-settings">
          <h2 className="span-all">{t("collection_settings_title")}</h2>
          <label className="check">
            <input type="checkbox" name="enabled" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
            {t("collection_enabled")}
          </label>
          {num("traffic_min", t("collection_traffic_minutes"))}
          {num("events_min", t("collection_events_minutes"))}
          {num("inventory_min", t("collection_inventory_minutes"))}
          {num("rate", t("collection_rate_limit"))}
          {num("backfill_days", t("collection_backfill_days"))}
          {num("disk_gb", t("collection_disk_warn_gb"))}
          {num("flow_days", t("retention_flow_days"))}
          {num("event_days", t("retention_event_days"))}
          {num("rollup_days", t("retention_rollup_days"))}
          {num("baseline_days", t("retention_baseline_days"))}
          <label className="check">
            <input type="checkbox" name="archive_enabled" checked={form.archive_enabled}
                   onChange={(e) => set("archive_enabled", e.target.checked)} />
            {t("archive_enabled")}
          </label>
          {num("archive_days", t("archive_retention_days"))}
          {error && (
            <div className="form-error" role="alert">
              {settingsError(error)}
            </div>
          )}
          {saved && <p className="form-ok" role="status">{t("saved_ok")}</p>}
          <div className="actions">
            <button type="submit" className="btn-primary" disabled={busy}>{t("btn_save")}</button>
          </div>
        </form>
      )}
      <form className="card form-grid" onSubmit={startBackfill} data-role="backfill">
        <h2 className="span-all">{t("backfill_title")}</h2>
        <label>
          {t("backfill_start")}
          <input type="date" name="start" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} />
        </label>
        <label>
          {t("backfill_end")}
          <input type="date" name="end" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} />
        </label>
        {backfillError && <div className="form-error" role="alert">{t(backfillError.message_key, backfillError.params)}</div>}
        {backfillNote && <p className="form-ok" role="status">{backfillNote}</p>}
        <div className="actions">
          <button type="submit" className="btn-quiet">{t("btn_backfill")}</button>
        </div>
      </form>
    </section>
  );
}

registerNav({ section: "system", path: "/system/collection", labelKey: "nav_system_collection", order: 12, component: Collection });
