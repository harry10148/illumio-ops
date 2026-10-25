import { useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { JobView } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";

const JOB_LABEL_KEYS: Record<string, string> = {
  pce_probe: "job_name_pce_probe",
  tls_renew_check: "job_name_tls_renew_check",
  collect_traffic: "job_name_collect_traffic",
  collect_events: "job_name_collect_events",
  collect_inventory: "job_name_collect_inventory",
  collect_backfill: "job_name_collect_backfill",
  collect_backfill_manual: "job_name_collect_backfill_manual",
  collect_archive: "job_name_collect_archive",
  collect_retention: "job_name_collect_retention",
  flows_checkpoint: "job_name_flows_checkpoint",
};

function every(seconds: number | null): string {
  if (!seconds) return "";
  if (seconds % 3600 === 0) return t("jobs_every_hours", { n: String(seconds / 3600) });
  return t("jobs_every_minutes", { n: String(Math.round(seconds / 60)) });
}

function result(job: JobView): { tone: string; text: string } {
  const running = job.last_started_at && (!job.last_finished_at || job.last_started_at > job.last_finished_at);
  if (running) return { tone: "info", text: t("job_result_running") };
  if (job.last_ok === null) return { tone: "neutral", text: t("job_never_run") };
  return job.last_ok ? { tone: "ok", text: t("job_result_ok") } : { tone: "crit", text: t("job_result_failed") };
}

export function Jobs() {
  const lang = useLang();
  const [jobs, setJobs] = useState<JobView[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void call("system.jobs.list").then((env) => {
      if (env.ok && env.data) setJobs(env.data.jobs);
      else setError(env.error);
    });
  }, []);

  return (
    <section className="page">
      <h1>{t("nav_system_jobs")}</h1>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {jobs && (
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t("jobs_col_job")}</th>
                <th>{t("jobs_col_schedule")}</th>
                <th>{t("jobs_col_last_run")}</th>
                <th>{t("jobs_col_result")}</th>
                <th>{t("jobs_col_failures")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const r = result(job);
                const labelKey = JOB_LABEL_KEYS[job.job_id];
                return (
                  <tr key={job.job_id} data-job={job.job_id}>
                    <td>{labelKey ? t(labelKey) : job.job_id}</td>
                    <td>{every(job.interval_seconds)}</td>
                    <td>{job.last_started_at ? formatTime(job.last_started_at, lang) : t("job_never_run")}</td>
                    <td>
                      <span className="badge" data-tone={r.tone}>{r.text}</span>
                      {job.last_ok === false && job.last_error && <div className="hint wrap">{job.last_error}</div>}
                    </td>
                    <td>{t("jobs_failures_of_runs", { failures: String(job.failures), runs: String(job.runs) })}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

registerNav({ section: "system", path: "/system/jobs", labelKey: "nav_system_jobs", order: 20, component: Jobs });
