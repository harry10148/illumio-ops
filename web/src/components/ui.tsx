// The console's building blocks (UI redesign spec §7, samples 01–11). Pages compose these; colours come only from
// tokens.css through data-tone.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { t } from "../i18n";

export type Tone = "crit" | "high" | "med" | "low" | "ok" | "accum" | "adv" | "muted";

const SEVERITY_TONE: Record<string, Tone> = { critical: "crit", high: "high", medium: "med", low: "low", info: "low" };
const SEVERITY_WORD: Record<string, string> = {
  critical: "severity_critical", high: "severity_high", medium: "severity_medium", low: "severity_low",
};

export function severityTone(severity: string): Tone {
  return SEVERITY_TONE[severity] ?? "muted";
}

export function Tag({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return <span className="tag" data-tone={tone} title={title}>{children}</span>;
}

export function SeverityTag({ severity }: { severity: string }) {
  const key = SEVERITY_WORD[severity];
  return <Tag tone={severityTone(severity)}>{key ? t(key) : severity}</Tag>;
}

/** ◆ for a feature that needs advanced mode, ● for one basic mode has; the word goes with the mark. */
export function ModeMark({ needs }: { needs: "advanced" | "basic" }) {
  return needs === "advanced"
    ? <Tag tone="adv">◆ {t("mode_advanced")}</Tag>
    : <Tag tone="ok">● {t("mode_basic")}</Tag>;
}

/** What basic mode leaves out, said where the missing thing would be — never an empty panel. */
export function NeedsAdvanced({ what }: { what: string }) {
  return (
    <div className="needs-advanced" data-role="needs-advanced">
      <p><Tag tone="adv">◆ {t("mode_advanced")}</Tag> {what}</p>
      <Link to="/system/collection">{t("needs_advanced_link")}</Link>
    </div>
  );
}

/** Why a number is not shown (accumulating, coverage, gap, basic mode); used instead of a 0. */
export function Reason({ text }: { text: string }) {
  return <span className="reason" data-reason="true">{text}</span>;
}

export interface KpiItem {
  key: string;
  label: string;
  value: string | number | null;
  /** Shown instead of the value when the value is null. */
  reason?: string;
  tone?: Tone;
  delta?: string;
}

export function KpiStrip({ items }: { items: KpiItem[] }) {
  return (
    <div className="kpi-strip" data-role="kpi-strip">
      {items.map((k) => (
        <div key={k.key} className="kpi" data-tone={k.tone ?? "muted"} data-kpi={k.key}>
          <div className="kpi-label">{k.label}</div>
          {k.value === null
            ? <div className="kpi-reason"><Reason text={k.reason ?? t("value_not_computed")} /></div>
            : <div className="kpi-value mono">{k.value}</div>}
          {k.delta && <div className="kpi-delta">{k.delta}</div>}
        </div>
      ))}
    </div>
  );
}

export interface Column<R> {
  key: string;
  label: string;
  /** Numbers and times line up right and use the monospace face. */
  kind?: "text" | "num" | "mono";
  render: (row: R) => ReactNode;
}

export function DataTable<R>({ columns, rows, rowKey, empty, onRowClick, selected }: {
  columns: Column<R>[];
  rows: R[];
  rowKey: (row: R) => string;
  /** Why there is nothing: every empty table says it. */
  empty: string;
  onRowClick?: (row: R) => void;
  selected?: string | null;
}) {
  return (
    <div className="table-wrap">
      <table className="table data-table">
        <thead>
          <tr>{columns.map((c) => <th key={c.key} data-kind={c.kind ?? "text"}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={columns.length} className="table-empty">{empty}</td></tr>
          ) : rows.map((r) => {
            const key = rowKey(r);
            return (
              <tr key={key} data-row={key} aria-selected={selected === key}
                  className={onRowClick ? "clickable" : undefined}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}>
                {columns.map((c) => <td key={c.key} data-kind={c.kind ?? "text"}>{c.render(r)}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The detail beside a list: on the right on a wide screen, under the list on a narrow one. */
export function DetailPane({ label, onClose, children }: { label: string; onClose?: () => void; children: ReactNode }) {
  return (
    <aside className="detail-pane" aria-label={label}>
      {onClose && (
        <button type="button" className="btn-quiet detail-close" onClick={onClose} aria-label={t("action_close")}>×</button>
      )}
      {children}
    </aside>
  );
}

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head console-head">
      <div>
        <h1>{title}</h1>
        {sub && <div className="page-sub">{sub}</div>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </header>
  );
}

export function Panel({ title, meta, children, role }: { title: string; meta?: ReactNode; children: ReactNode; role?: string }) {
  return (
    <section className="panel" data-role={role}>
      <div className="panel-head"><h2>{title}</h2>{meta && <span className="panel-meta">{meta}</span>}</div>
      <div className="panel-body">{children}</div>
    </section>
  );
}
