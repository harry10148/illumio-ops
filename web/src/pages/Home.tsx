import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../api/client";
import type { HomeSummary } from "../api/generated";
import { ProbeResults } from "../components/ProbeResults";
import { t } from "../i18n";

export function Home() {
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void call("home.summary").then((env) => {
      if (env.ok && env.data) setSummary(env.data);
      else setError(env.error);
    });
  }, []);

  const pce = summary?.pce ?? null;
  return (
    <section className="page">
      <h1>{t("nav_home")}</h1>
      <div className="card">
        <h2>{t("home_pce_title")}</h2>
        {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
        {summary && (
          <>
            <ProbeResults checkedAt={pce?.checked_at ?? null} results={pce?.results ?? []} stale={pce?.stale ?? false} />
            {!pce && <Link to="/system/pce">{t("home_pce_setup_link")}</Link>}
          </>
        )}
      </div>
    </section>
  );
}
