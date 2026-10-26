// Words for the alert value domains, shared by the alert pages.
import type { DeliveryView } from "../../api/generated";
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
