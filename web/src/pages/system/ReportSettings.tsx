import { type FormEvent, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { ReportSettingsView } from "../../api/generated";
import { t } from "../../i18n";
import { registerNav } from "../../shell/nav";
import { RhcSection } from "./RhcSection";

export function ReportSettings({ embedded = false }: { embedded?: boolean }) {
  const [view, setView] = useState<ReportSettingsView | null>(null);
  const [url, setUrl] = useState("");
  const [days, setDays] = useState(90);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void call("system.reports.get").then((env) => {
      if (env.ok && env.data) {
        setView(env.data);
        setUrl(env.data.gui_external_url);
        setDays(env.data.retention_days);
      } else setError(env.error);
    });
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!view) return;
    setBusy(true);
    const env = await call("system.reports.update", { revision: view.revision, gui_external_url: url, retention_days: days });
    setBusy(false);
    if (env.ok && env.data) {
      setView(env.data);
      setUrl(env.data.gui_external_url);
      setError(null);
      setSaved(true);
    } else {
      setError(env.error);
      setSaved(false);
    }
  }

  return (
    <section className="page stack" data-role="report-settings">
      {embedded ? <h2>{t("nav_system_reports")}</h2> : <h1>{t("nav_system_reports")}</h1>}
      {error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
      {view && (
        <form className="card form-grid" onSubmit={save}>
          <label className="span-all">
            {t("gui_reports_external_url")}
            <input name="gui_external_url" value={url} placeholder="https://illumio-ops.example.com:5443"
              onChange={(e) => { setUrl(e.target.value); setSaved(false); }} />
            <span className="hint">{t("gui_reports_external_url_hint")}</span>
          </label>
          <label>
            {t("gui_reports_retention")}
            <input name="retention_days" type="number" min={1} max={3650} value={days}
              onChange={(e) => { setDays(Number(e.target.value)); setSaved(false); }} />
            <span className="hint">{t("gui_reports_retention_hint")}</span>
          </label>
          <div className="actions span-all">
            <button type="submit" className="btn-primary" disabled={busy}>{t("btn_save")}</button>
            {saved && <span className="form-ok">{t("saved_ok")}</span>}
          </div>
        </form>
      )}
      <RhcSection />
    </section>
  );
}

/** Report settings (retention, the link address, Rule Hit Count) moved to Reports › Scheduled delivery (spec §4.7). */
function ReportSettingsRedirect() {
  return <Navigate to="/reports?tab=schedules" replace />;
}

registerNav({ section: "system", path: "/system/reports", labelKey: "nav_system_reports", order: 90,
              component: ReportSettingsRedirect, hidden: true });
