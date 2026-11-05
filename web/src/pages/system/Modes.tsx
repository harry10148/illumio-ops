// System › Modes and data sources, top half (UI redesign spec §4.10, sample 11): the two modes side by side with
// what each does and needs, the current one marked; then how far collection has read and what it takes on disk.
import { useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { DataStatus } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { Panel, Reason, Tag } from "../../components/ui";
import { t, useLang } from "../../i18n";

const DISK_KEYS: Record<string, string> = {
  flows: "modes_disk_flows", archive: "modes_disk_archive", app: "modes_disk_app", reports: "modes_disk_reports",
};

function size(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

function ModeCard({ mode, current }: { mode: "basic" | "advanced"; current: boolean }) {
  const basic = mode === "basic";
  return (
    <div className="mode-card" data-mode={mode} data-current={current || undefined}>
      <div className="row">
        <Tag tone={basic ? "muted" : "adv"}>{basic ? `● ${t("mode_basic")}` : `◆ ${t("mode_advanced")}`}</Tag>
        {current && <Tag tone="accum">{t("modes_current")}</Tag>}
      </div>
      <p>{t(basic ? "modes_basic_does" : "modes_advanced_does")}</p>
      <p className="hint">{t(basic ? "modes_basic_needs" : "modes_advanced_needs")}</p>
    </div>
  );
}

export function Modes() {
  const lang = useLang();
  const [d, setD] = useState<DataStatus | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    void call("system.collection.data").then((env) => {
      if (env.ok && env.data) setD(env.data);
      else setError(env.error);
    });
  }, []);
  if (error) return <p className="form-error">{t(error.message_key, error.params)}</p>;
  if (!d) return <p className="muted">{t("loading")}</p>;
  const basicWhy = t("modes_basic_no_traffic");
  return (
    <div className="stack" data-role="modes">
      <div className="mode-cards">
        <ModeCard mode="basic" current={d.mode === "basic"} />
        <ModeCard mode="advanced" current={d.mode === "advanced"} />
      </div>
      <p className="hint">{t("modes_switch_below")}</p>
      <Panel title={t("modes_data_title")} role="data-status">
        <dl className="kv-list">
          <dt>{t("modes_events_latest")}</dt>
          <dd className="mono">{d.events_latest ? formatTime(d.events_latest, lang) : <Reason text={t("shell_collection_not_started")} />}</dd>
          <dt>{t("modes_flows_latest")}</dt>
          <dd className="mono">{d.flows_latest ? formatTime(d.flows_latest, lang)
            : <Reason text={d.mode === "basic" ? basicWhy : t("shell_collection_not_started")} />}</dd>
          <dt>{t("modes_baseline")}</dt>
          <dd>{d.baseline_days === null ? <Reason text={basicWhy} />
            : t("modes_baseline_days", { have: String(d.baseline_days), want: String(d.baseline_target_days) })}</dd>
          <dt>{t("modes_live_hours")}</dt>
          <dd>{d.live_hours_days === null ? <Reason text={basicWhy} />
            : t("modes_live_hours_days", { n: String(d.live_hours_days) })}</dd>
          <dt>{t("modes_gaps")}</dt>
          <dd data-role="gaps">{d.gaps.length === 0 ? t("modes_gaps_none") : (
            <ul className="plain-list">
              {d.gaps.map((g, i) => (
                <li key={i} className="mono">{g.source} · {g.kind} · {formatTime(g.start, lang)} – {formatTime(g.end, lang)}</li>
              ))}
            </ul>
          )}</dd>
        </dl>
      </Panel>
      <Panel title={t("modes_disk_title")} role="disk">
        <dl className="kv-list">
          {d.disk.map((p) => (
            <div key={p.name} style={{ display: "contents" }}>
              <dt>{t(DISK_KEYS[p.name] ?? p.name)}</dt><dd className="mono" data-disk={p.name}>{size(p.bytes)}</dd>
            </div>
          ))}
        </dl>
      </Panel>
    </div>
  );
}
