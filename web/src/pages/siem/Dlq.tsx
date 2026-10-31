// The SIEM DLQ (P7): what a destination would not take, the line as it was formatted. Resend sends the stored line
// to the destination as it is set up now; purge removes it; export downloads every line as JSON lines.
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { DlqPage, SiemSettingsView } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";

const PAGE = 50;
const SOURCE_KEYS: Record<string, string> = {
  audit: "siem_cursor_audit", alerts: "siem_cursor_alerts", detections: "siem_cursor_detections",
  new_connections: "siem_cursor_new_connections",
};

export function Dlq() {
  const lang = useLang();
  const [params, setParams] = useSearchParams();
  const dest = params.get("destination") ?? "";
  const [settings, setSettings] = useState<SiemSettingsView | null>(null);
  const [page, setPage] = useState<DlqPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [picked, setPicked] = useState<number[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"resend_all" | "purge_all" | "purge" | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    void call("siem.dlq.list", undefined, undefined,
              { destination_id: dest, limit: String(PAGE), offset: String(offset) }).then((env) => {
      if (env.ok && env.data) { setPage(env.data); setError(null); }
      else setError(env.error);
    });
  }, [dest, offset]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    void call("siem.settings.get").then((env) => { if (env.ok && env.data) setSettings(env.data); });
  }, []);

  async function act(kind: "resend" | "resend_all" | "purge" | "purge_all") {
    setBusy(true);
    setConfirm(null);
    const body = { ids: kind === "resend" || kind === "purge" ? picked : null, destination_id: dest || null };
    if (kind.startsWith("resend")) {
      const env = await call("siem.dlq.resend", body);
      if (env.ok && env.data) {
        setDone(t("siem_dlq_resent", { sent: String(env.data.sent), failed: String(env.data.failed), changed: String(env.data.changed),
                                       skipped: String(env.data.skipped), remaining: String(env.data.remaining) })
                + (env.data.error ? ` ${t("siem_dlq_last_error", { error: env.data.error })}` : ""));
      } else setError(env.error);
    } else {
      const env = await call("siem.dlq.purge", body);
      if (env.ok && env.data) setDone(t("siem_dlq_purged", { n: String(env.data.deleted) }));
      else setError(env.error);
    }
    setBusy(false);
    setPicked([]);
    load();
  }

  const items = page?.items ?? [];
  const exportHref = `/siem/dlq/export${dest ? `?destination_id=${dest}` : ""}`;
  return (
    <section className="page stack">
      <h1>{t("siem_dlq_title")}</h1>
      <p className="hint">{t("siem_dlq_intro")} <Link to="/siem">{t("nav_siem")}</Link></p>
      <div className="row">
        <label>{t("siem_col_destination")}
          <select name="dlq_destination" value={dest} onChange={(e) => { setOffset(0); setPicked([]); setParams(e.target.value ? { destination: e.target.value } : {}); }}>
            <option value="">{t("siem_dlq_all_destinations")}</option>
            {(settings?.siem.destinations ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
        <a className="btn-quiet" href={exportHref} data-role="dlq-export">{t("siem_dlq_export")}</a>
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {done && <p className="form-ok" role="status" data-role="dlq-done">{done}</p>}
      {page && page.total === 0 && <p className="muted" data-role="dlq-empty">{t("siem_dlq_empty")}</p>}
      {items.length > 0 && (
        <>
          <div className="row">
            <button type="button" className="btn-quiet" disabled={busy || picked.length === 0} onClick={() => void act("resend")} data-role="dlq-resend">{t("siem_dlq_resend", { n: String(picked.length) })}</button>
            <button type="button" className="btn-quiet" disabled={busy || picked.length === 0} onClick={() => setConfirm("purge")} data-role="dlq-purge">{t("siem_dlq_purge", { n: String(picked.length) })}</button>
            <button type="button" className="btn-quiet" disabled={busy} onClick={() => setConfirm("resend_all")} data-role="dlq-resend-all">{t("siem_dlq_resend_all")}</button>
            <button type="button" className="btn-quiet" disabled={busy} onClick={() => setConfirm("purge_all")} data-role="dlq-purge-all">{t("siem_dlq_purge_all")}</button>
          </div>
          {confirm && (
            <p className="notice" data-role="dlq-confirm">
              {t(confirm === "resend_all" ? "siem_dlq_confirm_resend_all" : confirm === "purge_all" ? "siem_dlq_confirm_purge_all" : "siem_dlq_confirm_purge",
                 { n: String(confirm === "purge" ? picked.length : page?.total ?? 0) })}{" "}
              <button type="button" className="btn-primary" onClick={() => void act(confirm)} data-role="dlq-confirm-yes">{t("siem_dlq_confirm_yes")}</button>{" "}
              <button type="button" className="btn-quiet" onClick={() => setConfirm(null)}>{t("q_close")}</button>
            </p>
          )}
          <div className="table-wrap">
            <table className="table" data-role="dlq-rows">
              <thead><tr><th><input type="checkbox" aria-label={t("siem_dlq_pick_all")} checked={picked.length === items.length}
                                    onChange={(e) => setPicked(e.target.checked ? items.map((x) => x.id) : [])} /></th>
                <th>{t("siem_dlq_col_when")}</th><th>{t("siem_col_destination")}</th><th>{t("siem_col_source")}</th>
                <th>{t("siem_dlq_col_record")}</th><th>{t("siem_col_error")}</th><th>{t("siem_dlq_col_attempts")}</th>
                <th>{t("siem_dlq_col_line")}</th></tr></thead>
              <tbody>
                {items.map((x) => (
                  <tr key={x.id} data-id={x.id}>
                    <td><input type="checkbox" checked={picked.includes(x.id)} aria-label={x.external_id}
                               onChange={(e) => setPicked(e.target.checked ? [...picked, x.id] : picked.filter((p) => p !== x.id))} /></td>
                    <td className="nowrap">{formatTime(x.quarantined_at, lang)}</td>
                    <td>{x.destination}</td>
                    <td>{t(SOURCE_KEYS[x.source] ?? x.source)}</td>
                    <td className="nowrap">{x.external_id}{x.event_time ? <div className="hint">{formatTime(x.event_time, lang)}</div> : null}</td>
                    <td className="wrap">{x.error}</td>
                    <td className="num">{x.attempts}</td>
                    <td className="wrap"><code>{x.preview}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row">
            <button type="button" className="btn-quiet" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>{t("siem_dlq_prev")}</button>
            <span className="hint">{t("siem_dlq_range", { from: String(offset + 1), to: String(offset + items.length), total: String(page?.total ?? 0) })}</span>
            <button type="button" className="btn-quiet" disabled={!page || offset + items.length >= page.total} onClick={() => setOffset(offset + PAGE)}>{t("siem_dlq_next")}</button>
          </div>
        </>
      )}
    </section>
  );
}

registerNav({ section: "main", path: "/siem/dlq", labelKey: "siem_dlq_title", order: 23, component: Dlq, hidden: true });
