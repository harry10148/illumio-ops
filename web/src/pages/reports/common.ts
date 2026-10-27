// Words for the report value domains, shared by the report pages.
import { t } from "../../i18n";

export const TYPE_KEYS: Record<string, string> = {
  lateral_posture: "rpt_title_lateral_posture",
  new_connections: "rpt_title_new_connections",
  unmanaged_endpoints: "rpt_title_unmanaged",
};
export const TYPE_DESC_KEYS: Record<string, string> = {
  lateral_posture: "gui_reports_desc_lateral_posture",
  new_connections: "gui_reports_desc_new_connections",
  unmanaged_endpoints: "gui_reports_desc_unmanaged",
};
export const GROUP_KEYS: Record<string, string> = {
  lateral: "gui_reports_group_lateral", inventory: "gui_reports_group_inventory",
  analysis: "gui_reports_group_analysis", assessment: "gui_reports_group_assessment",
  operations: "gui_reports_group_operations",
};
export const GROUP_ORDER = ["lateral", "inventory", "analysis", "assessment", "operations"];
export const STATUS_KEYS: Record<string, string> = {
  queued: "gui_reports_status_queued", running: "gui_reports_status_running",
  done: "gui_reports_status_done", failed: "gui_reports_status_failed",
};
export const STATUS_TONES: Record<string, string> = { queued: "info", running: "info", done: "ok", failed: "danger" };
export const EMAIL_KEYS: Record<string, string> = {
  sending: "gui_reports_email_sending", sent: "gui_reports_email_sent", failed: "gui_reports_email_failed",
  skipped_no_smtp: "gui_reports_email_skipped",
};
export const LOOKBACK_CHOICES = ["1", "7", "14", "30", "90"];

export function word(keys: Record<string, string>, value: string): string {
  const key = keys[value];
  return key ? t(key) : value;
}

/** "2026-10-20 – 2026-10-26": the period's end is exclusive. */
export function periodText(start: string, end: string, lang: string): string {
  const fmt = (d: Date) => d.toLocaleDateString(lang === "zh_TW" ? "zh-TW" : "en");
  const last = new Date(new Date(end).getTime() - 1);
  return `${fmt(new Date(start))} – ${fmt(last)}`;
}
