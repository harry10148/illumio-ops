import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { LogLines, LogQuery } from "../../api/generated";
import { t } from "../../i18n";
import { registerNav } from "../../shell/nav";

const LIMIT = 200;
const LEVEL_TONES: Record<string, string> = { ERROR: "crit", CRITICAL: "crit", WARNING: "warn" };

export function Logs() {
  const [level, setLevel] = useState<NonNullable<LogQuery["level"]> | "">("");
  const [module, setModule] = useState("");
  const [contains, setContains] = useState("");
  const [result, setResult] = useState<LogLines | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const search = useCallback(async () => {
    const env = await call("system.logs.query", {
      level: level || null,
      module: module.trim() || null,
      contains: contains.trim() || null,
      limit: LIMIT,
    });
    if (env.ok && env.data) {
      setResult(env.data);
      setError(null);
    } else setError(env.error);
  }, [level, module, contains]);

  useEffect(() => {
    void search();
    // first load only; later searches are explicit
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submit(e: FormEvent) {
    e.preventDefault();
    void search();
  }

  return (
    <section className="page stack">
      <h1>{t("nav_system_logs")}</h1>
      <form className="card form-grid" onSubmit={submit}>
        <label>
          {t("logs_level")}
          <select name="level" value={level} onChange={(e) => setLevel(e.target.value as typeof level)}>
            <option value="">{t("logs_level_any")}</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </label>
        <label>
          {t("logs_module")}
          <input name="module" value={module} onChange={(e) => setModule(e.target.value)} placeholder="illumio_ops.services.collect" />
        </label>
        <label>
          {t("logs_contains")}
          <input name="contains" value={contains} onChange={(e) => setContains(e.target.value)} />
        </label>
        <div className="actions">
          <button type="submit" className="btn-primary">{t("btn_search")}</button>
        </div>
      </form>
      {error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
      {result && result.lines.length === 0 && <p className="muted">{t("logs_empty")}</p>}
      {result && result.lines.length > 0 && (
        <div className="card table-wrap">
          {result.truncated && <p className="hint">{t("logs_truncated", { n: String(LIMIT) })}</p>}
          <table className="table" data-role="log-lines">
            <thead>
              <tr>
                <th>{t("logs_col_time")}</th>
                <th>{t("logs_col_level")}</th>
                <th>{t("logs_col_module")}</th>
                <th>{t("logs_col_message")}</th>
              </tr>
            </thead>
            <tbody>
              {result.lines.map((line, i) => (
                <tr key={`${line.ts}-${i}`}>
                  <td className="nowrap">{line.ts}</td>
                  <td><span className="badge" data-tone={LEVEL_TONES[line.level] ?? "neutral"}>{line.level}</span></td>
                  <td>{line.module}</td>
                  <td className="log-message">{line.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

registerNav({ section: "system", path: "/system/logs", labelKey: "nav_system_logs", order: 25, component: Logs });
