// Words for the alert value domains, shared by the alert pages.
import type { DeliveryView, DetectorKind, SystemCheck } from "../../api/generated";
import { t } from "../../i18n";

export const SEVERITY_KEYS: Record<string, string> = {
  low: "severity_low", medium: "severity_medium", high: "severity_high", critical: "severity_critical",
};
export const SEVERITY_TONES: Record<string, string> = { low: "neutral", medium: "info", high: "warn", critical: "danger" };
export const TYPE_KEYS: Record<string, string> = {
  event: "alert_type_event", traffic: "alert_type_traffic", bandwidth: "alert_type_bandwidth",
  volume: "alert_type_volume", system: "alert_type_system", lateral: "alert_type_lateral",
};
export const DELIVERY_KEYS: Record<string, string> = {
  pending: "delivery_pending", sent: "delivery_sent", failed: "delivery_failed",
  not_notified: "delivery_not_notified", grouped: "delivery_grouped", no_channel: "delivery_no_channel",
};
export const DELIVERY_TONES: Record<string, string> = {
  pending: "info", sent: "ok", failed: "danger", not_notified: "neutral", grouped: "neutral", no_channel: "warn",
};
export const CHANNEL_KEYS: Record<string, string> = {
  smtp: "channel_smtp", line: "channel_line", telegram: "channel_telegram", teams: "channel_teams",
  webhook: "channel_webhook", "-": "channel_none",
};
// Lateral-movement detectors, then the allowed-traffic anomaly detectors (spec §6.5.8), each group under its title:
// the order every page lists them in.
export const DETECTOR_GROUPS: { titleKey: string; kinds: DetectorKind[] }[] = [
  { titleKey: "lateral_detectors_lateral",
    kinds: ["fanout", "new_admin_connection", "pivot_chain", "blocked_surge", "non_admin_group", "cross_env",
            "account_fanout", "unexpected_initiator"] },
  { titleKey: "lateral_detectors_anomaly",
    kinds: ["peer_deviation", "volume_surge", "account_new_source", "suspicious_tool", "new_process", "auth_to_non_dc",
            "new_dc_client", "directory_surge", "direction_reversal", "new_pair_port", "quiet_host_wakes", "data_staging",
            "off_hours"] },
];
export const DETECTOR_KEYS: Record<string, string> = {
  fanout: "detector_name_fanout", new_admin_connection: "detector_name_new_admin_connection",
  pivot_chain: "detector_name_pivot_chain", blocked_surge: "detector_name_blocked_surge",
  non_admin_group: "detector_name_non_admin_group", cross_env: "detector_name_cross_env",
  account_fanout: "detector_name_account_fanout", unexpected_initiator: "detector_name_unexpected_initiator",
  peer_deviation: "detector_name_peer_deviation", volume_surge: "detector_name_volume_surge",
  account_new_source: "detector_name_account_new_source", suspicious_tool: "detector_name_suspicious_tool",
  new_process: "detector_name_new_process", auth_to_non_dc: "detector_name_auth_to_non_dc",
  new_dc_client: "detector_name_new_dc_client", directory_surge: "detector_name_directory_surge",
  direction_reversal: "detector_name_direction_reversal", new_pair_port: "detector_name_new_pair_port",
  quiet_host_wakes: "detector_name_quiet_host_wakes", data_staging: "detector_name_data_staging",
  off_hours: "detector_name_off_hours",
};
export const CHECKS: SystemCheck[] = ["pce_health", "collection_failing", "data_loss", "job_failing", "disk_low", "siem_backlog"];
export const CHECK_KEYS: Record<string, string> = {
  pce_health: "rule_system_pce_health", collection_failing: "rule_system_collection_failing",
  data_loss: "rule_system_data_loss", job_failing: "rule_system_job_failing", disk_low: "rule_system_disk_low",
  siem_backlog: "rule_system_siem_backlog",
};
export const STATUS_KEYS: Record<string, string> = {
  ok: "rule_status_ok", no_data: "rule_status_no_data", incomplete: "rule_status_incomplete",
  collection_off: "rule_status_collection_off",
};

export function word(keys: Record<string, string>, value: string): string {
  const key = keys[value];
  return key ? t(key) : value;
}

/** One badge per delivery: the channel and how it went. */
export function deliveryText(d: DeliveryView): string {
  const channel = d.channel === "-" ? "" : `${word(CHANNEL_KEYS, d.channel)}: `;
  return `${channel}${word(DELIVERY_KEYS, d.status)}`;
}
