import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../api/client";
import type { FocusEntry, FocusView, HomeSummary } from "../api/generated";
import { ProbeResults, formatTime } from "../components/ProbeResults";
import { t, useLang } from "../i18n";
import { SEVERITY_KEYS, SEVERITY_TONES, word } from "./alerts/common";

// Literal maps: i18n keys are never built from data.
const SOURCE_KEYS: Record<string, string> = {
  exposure: "home_focus_src_exposure", ransomware: "home_focus_src_ransomware", tamper: "home_focus_src_tamper",
  detections: "home_focus_src_detections", traffic: "home_focus_src_traffic",
};
const STATUS_KEYS: Record<string, string> = {
  missing: "home_focus_status_missing", stale: "home_focus_status_stale", error: "home_focus_status_error",
};
const TOP = 10;  // the ranked list's head first: a lab estate had 117 items, 102 of them detections
const PATTERN_KEYS: Record<string, string> = {
  regular_cycle: "tamper_pattern_regular_cycle", burst: "tamper_pattern_burst", sporadic: "tamper_pattern_sporadic",
  too_few: "tamper_pattern_too_few",
};

/** The item's parameters as a reader sees them: an unmanaged host's key is its address, a pattern is words. */
function shownParams(params: FocusEntry["params"]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v === null || typeof v === "object") continue;
    const s = String(v);
    out[k] = k === "pattern" ? word(PATTERN_KEYS, s) : s.startsWith("ip:") ? s.slice(3) : s;
  }
  return out;
}

function FocusItem({ item }: { item: FocusEntry }) {
  const p = shownParams(item.params);
  const query = item.link?.query ?? {};
  const href = item.link ? `${item.link.route}${Object.keys(query).length ? `?${new URLSearchParams(query).toString()}` : ""}` : null;
  return (
    <li className="focus-item" data-kind={item.kind}>
      <div className="row">
        <span className="badge" data-tone={SEVERITY_TONES[item.severity]}>{word(SEVERITY_KEYS, item.severity)}</span>
        <span className="badge">{item.new_this_week ? t("home_focus_new")
          : t("home_focus_weeks", { n: String(item.weeks_persisting) })}</span>
        <strong>{t(item.title_key, p)}</strong>
      </div>
      <p className="hint">{t(item.why_key, p)}</p>
      {href && <Link to={href} data-role="focus-link">{t("home_focus_open")}</Link>}
    </li>
  );
}

function Focus() {
  const lang = useLang();
  const [view, setView] = useState<FocusView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [all, setAll] = useState(false);

  useEffect(() => {
    void call("home.focus").then((env) => {
      if (env.ok && env.data) setView(env.data);
      else setError(env.error);
    });
  }, []);

  const problems = Object.entries(view?.sources_status ?? {}).filter(([, s]) => s !== "ok");
  return (
    <div className="card stack" data-role="focus">
      <h2>{t("home_focus_title")}</h2>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {!view && !error && <p className="muted">{t("loading")}</p>}
      {view && view.computed_at === null && <p className="notice" data-role="focus-not-computed">{t("home_focus_not_computed")}</p>}
      {view?.computed_at && (
        <p className={view.stale ? "notice" : "hint"}>
          {t(view.stale ? "home_focus_stale" : "home_focus_computed", { time: formatTime(view.computed_at, lang) })}
        </p>
      )}
      {problems.length > 0 && (
        <ul className="notice" data-role="focus-sources">
          {problems.map(([src, status]) => (
            <li key={src}>{word(SOURCE_KEYS, src)}：{word(STATUS_KEYS, status.startsWith("error") ? "error" : status)}</li>
          ))}
        </ul>
      )}
      {view?.computed_at && view.items.length === 0 && problems.length === 0 && <p className="muted">{t("home_focus_empty")}</p>}
      {view && view.items.length > 0 && (
        <ol className="focus-list">{(all ? view.items : view.items.slice(0, TOP)).map((it) => <FocusItem key={it.fingerprint} item={it} />)}</ol>
      )}
      {view && !all && view.items.length > TOP && (
        <button type="button" className="btn-quiet" data-role="focus-more" onClick={() => setAll(true)}>
          {t("home_focus_more", { shown: String(TOP), total: String(view.items.length) })}
        </button>
      )}
    </div>
  );
}

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
      <Focus />
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
