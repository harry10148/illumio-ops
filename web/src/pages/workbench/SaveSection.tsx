// Save the workbench's analysis segment as a section of a custom report (spec §6.5.3 存成排程報表, P6e): its
// conditions, view and grouping without the period — the report gives the period each time it is made.
import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { CustomReport, CustomSectionAdd } from "../../api/generated";
import { t } from "../../i18n";
import type { Req } from "./conditions";

const NEW = "new";

export function SaveSection({ req }: { req: Req }) {
  const [open, setOpen] = useState(false);
  const [reports, setReports] = useState<CustomReport[] | null>(null);
  const [target, setTarget] = useState(NEW);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [saved, setSaved] = useState<CustomReport | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (!open || reports) return;
    void call("custom_reports.list").then((env) => {
      if (env.ok && env.data) setReports(env.data.reports);
      else setError(env.error);
    });
  }, [open, reports]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const env = await call("custom_reports.add_section", {
      report_id: target === NEW ? null : Number(target), name: target === NEW ? name : null, title,
      request: req as CustomSectionAdd["request"],
    });
    if (env.ok && env.data) {
      setSaved(env.data);
      setReports(null);
      setTitle("");
    } else setError(env.error);
  }

  if (!open) {
    return (
      <button type="button" className="btn-quiet" data-role="save-section" onClick={() => { setOpen(true); setSaved(null); }}>
        {t("cust_save_section")}
      </button>
    );
  }
  return (
    <form className="card stack" data-role="save-section-form" onSubmit={(e) => void save(e)}>
      <p className="hint">{t("cust_save_hint")}</p>
      <div className="row">
        <label>
          {t("cust_into")}
          <select name="custom-target" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value={NEW}>{t("cust_new_report")}</option>
            {(reports ?? []).map((r) => <option key={r.id} value={String(r.id)}>{r.name}</option>)}
          </select>
        </label>
        {target === NEW && (
          <label>
            {t("cust_name")}
            <input name="custom-name" value={name} maxLength={120} required onChange={(e) => setName(e.target.value)} />
          </label>
        )}
        <label>
          {t("cust_section_title")}
          <input name="section-title" value={title} maxLength={120} required onChange={(e) => setTitle(e.target.value)} />
        </label>
      </div>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {saved && (
        <p className="hint" data-role="save-section-done">
          {t("cust_saved", { name: saved.name, n: String(saved.sections.length) })} <Link to="/reports">{t("nav_reports")}</Link>
        </p>
      )}
      <div className="row">
        <button type="submit" className="btn-primary">{t("cust_save")}</button>
        <button type="button" className="btn-quiet" onClick={() => setOpen(false)}>{t("q_close")}</button>
      </div>
    </form>
  );
}
