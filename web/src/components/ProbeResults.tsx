import type { ProbeItem } from "../api/generated";
import { t, useLang } from "../i18n";

const PROBE_LABEL_KEYS: Record<ProbeItem["name"], string> = {
  noop: "probe_name_noop",
  health: "probe_name_health",
  node_available: "probe_name_node_available",
};

export function formatTime(iso: string, lang: string): string {
  return new Date(iso).toLocaleString(lang === "zh_TW" ? "zh-TW" : "en");
}

interface Props {
  checkedAt: string | null;
  results: ProbeItem[];
  stale?: boolean;
}

/** One row per probe, in words; the run time above. */
export function ProbeResults({ checkedAt, results, stale = false }: Props) {
  const lang = useLang();
  if (!checkedAt) return <p className="muted">{t("home_pce_not_checked")}</p>;
  const time = formatTime(checkedAt, lang);
  return (
    <div className="probe-results">
      {stale ? (
        <p className="form-error" role="status">{t("home_pce_stale", { time })}</p>
      ) : (
        <p className="muted">{t("probe_last_check", { time })}</p>
      )}
      <ul className="probe-list">
        {results.map((r) => (
          <li key={r.name} data-tone={r.ok ? "ok" : "crit"} className="probe-row">
            <span className="probe-name">{t(PROBE_LABEL_KEYS[r.name])}</span>
            <span className="probe-detail">{t(r.detail_key, { status: r.category })}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
