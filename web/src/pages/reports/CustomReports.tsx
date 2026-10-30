// Custom reports (spec §6.5.5, P6e): reports made of sections saved from the workbench — each listed with its
// sections, made now, renamed, sections removed; a report a schedule still makes is not deleted.
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { CustomReport } from "../../api/generated";
import { t } from "../../i18n";

const VIEW_KEYS: Record<string, string> = { detail: "cust_view_detail", ranking: "cust_view_ranking" };
const MODE_KEYS: Record<string, string> = { flows: "cust_mode_flows", events: "cust_mode_events" };

function One({ rep, onChanged, generate }: {
  rep: CustomReport; onChanged: () => void; generate: (customId: number) => ReactNode;
}) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(rep.name);
  const [making, setMaking] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function act(p: Promise<{ ok: boolean; error: ApiError | null }>) {
    const env = await p;
    if (env.ok) {
      setError(null);
      onChanged();
    } else setError(env.error);
  }

  return (
    <div className="stack cust-report" data-role="custom-report" data-custom-id={rep.id}>
      <div className="row spaced">
        {renaming ? (
          <form className="row" onSubmit={(e) => { e.preventDefault(); setRenaming(false);
            void act(call("custom_reports.rename", { name }, { report_id: String(rep.id) })); }}>
            <input name="custom-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
            <button type="submit" className="btn-quiet">{t("cust_save")}</button>
          </form>
        ) : <strong>{rep.name}</strong>}
        <div className="row">
          <button type="button" className="btn-quiet" onClick={() => setRenaming(!renaming)}>{t("cust_rename")}</button>
          <button type="button" className="btn-quiet" data-role="custom-delete"
            onClick={() => void act(call("custom_reports.delete", undefined, { report_id: String(rep.id) }))}>{t("cust_delete")}</button>
          <button type="button" className="btn-quiet" data-role="custom-generate-open" onClick={() => setMaking(!making)}>
            {t("gui_reports_generate_open")}
          </button>
        </div>
      </div>
      {rep.schedules.length > 0 && <p className="hint">{t("cust_scheduled", { names: rep.schedules.join("、") })}</p>}
      <ol className="cust-sections" data-role="custom-sections">
        {rep.sections.map((s, i) => (
          <li key={`${i}|${s.title}`}>
            {s.title} <span className="hint">（{t(MODE_KEYS[s.segment.mode] ?? s.segment.mode)}・{t(VIEW_KEYS[s.segment.view] ?? s.segment.view)}）</span>{" "}
            {rep.sections.length > 1 && (
              <button type="button" className="btn-quiet" data-role="custom-section-remove"
                onClick={() => void act(call("custom_reports.remove_section", {}, { report_id: String(rep.id), index: String(i) }))}>
                {t("cust_remove_section")}
              </button>
            )}
          </li>
        ))}
      </ol>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {making && generate(rep.id)}
    </div>
  );
}

export function CustomReports({ generate }: { generate: (customId: number, done: () => void) => ReactNode }) {
  const [reports, setReports] = useState<CustomReport[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => {
    void call("custom_reports.list").then((env) => {
      if (env.ok && env.data) setReports(env.data.reports);
      else setError(env.error);
    });
  }, []);
  useEffect(load, [load]);

  if (error) return <p className="form-error">{t(error.message_key, error.params)}</p>;
  if (!reports) return <p className="muted">{t("loading")}</p>;
  return (
    <div className="stack" data-role="custom-reports">
      {reports.length === 0 && (
        <p className="muted" data-role="custom-none">{t("cust_none")} <Link to="/investigate">{t("nav_workbench")}</Link></p>
      )}
      {reports.map((r) => <One key={r.id} rep={r} onChanged={load} generate={(id) => generate(id, load)} />)}
    </div>
  );
}
