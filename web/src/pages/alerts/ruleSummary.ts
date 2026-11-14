// A rule's condition and exclusion as one line of words for the rule list (UI spec §4.9). Every part is read from
// the rule itself: values are shown as stored, objects known only by href (label groups, IP lists, services, hosts)
// are counted, never named from a guess.
import type { EndpointFilter, FlowCondition, PortProto, RuleListItem } from "../../api/generated";
import { t } from "../../i18n";
import { decisionWord } from "../../terms";
import { CHECK_KEYS, DETECTOR_KEYS, SEVERITY_KEYS, word } from "./common";

type AlertRule = RuleListItem["rule"];
const SEP = "; ";
const ANY = new Set(["", "*", "any", "all"]);

function ports(list: PortProto[] | undefined): string {
  return (list ?? []).map((p) => {
    const range = p.to_port != null ? `${p.port}-${p.to_port}` : p.port != null && p.port >= 0 ? String(p.port) : "";
    // no protocol on the rule: every protocol matches (domain/filter.py), so the port stands alone
    if (p.proto == null) return range;
    const proto = p.proto === 17 ? "udp" : p.proto === 6 ? "tcp" : t("rsum_proto", { n: String(p.proto) });
    return range ? `${range}/${proto}` : proto;
  }).join(", ");
}

function side(name: string, f: EndpointFilter | null | undefined): string[] {
  if (!f) return [];
  const out: string[] = [];
  for (const l of f.labels ?? []) out.push(`${name} ${l.key} = ${l.values.join(t("rsum_or"))}`);
  const counted: [number, string][] = [
    [(f.label_groups ?? []).length, "rsum_label_groups"], [(f.ip_lists ?? []).length, "rsum_ip_lists"],
    [(f.hrefs ?? []).length + (f.ips ?? []).length, "rsum_hosts"],
  ];
  for (const [n, key] of counted) if (n > 0) out.push(`${name} ${t(key, { n: String(n) })}`);
  if (f.public) out.push(`${name} ${t("rsum_public")}`);
  return out;
}

function included(c: FlowCondition): string[] {
  const out: string[] = [];
  if ((c.decisions ?? []).length) out.push((c.decisions ?? []).map(decisionWord).join(t("rsum_or")));
  out.push(...side(t("rsum_src"), c.src), ...side(t("rsum_dst"), c.dst), ...side(t("rsum_either"), c.either));
  if ((c.ports ?? []).length) out.push(`port ${ports(c.ports)}`);
  if ((c.services ?? []).length) out.push(t("rsum_services", { n: String((c.services ?? []).length) }));
  if ((c.windows_services ?? []).length) out.push(`${t("rsum_windows_services")} ${(c.windows_services ?? []).join(", ")}`);
  if ((c.transmissions ?? []).length) out.push(`${t("rsum_transmission")} ${(c.transmissions ?? []).join(", ")}`);
  const named: [string | null | undefined, string][] = [
    [c.initiator_process, "rsum_initiator_process"], [c.initiator_user, "rsum_initiator_user"],
    [c.service_process, "rsum_service_process"], [c.service_user, "rsum_service_user"], [c.text, "rsum_text"],
  ];
  for (const [v, key] of named) if (v) out.push(`${t(key)} ${v}`);
  return out;
}

function excluded(c: FlowCondition): string[] {
  const out = [...side(t("rsum_src"), c.src_exclude), ...side(t("rsum_dst"), c.dst_exclude),
    ...side(t("rsum_either"), c.either_exclude)];
  if ((c.exclude_ports ?? []).length) out.push(`port ${ports(c.exclude_ports)}`);
  if ((c.exclude_services ?? []).length) out.push(t("rsum_services", { n: String((c.exclude_services ?? []).length) }));
  if ((c.exclude_windows_services ?? []).length) out.push(`${t("rsum_windows_services")} ${(c.exclude_windows_services ?? []).join(", ")}`);
  if ((c.exclude_transmissions ?? []).length) out.push(`${t("rsum_transmission")} ${(c.exclude_transmissions ?? []).join(", ")}`);
  if ((c.exclude_processes ?? []).length) out.push(`${t("rsum_process")} ${(c.exclude_processes ?? []).join(", ")}`);
  if (c.exclude_system_accounts) out.push(t("rsum_system_accounts"));
  return out;
}

/** What makes the rule fire. */
export function conditionSummary(rule: AlertRule): string {
  switch (rule.type) {
    case "event": {
      const parts = [rule.event_types.join(", ")];
      // "", "*", "any" and "all" match every value (domain/alertrules.py _ANY): not a condition, so not printed
      if (!ANY.has(rule.status)) parts.push(`${t("rsum_status")} ${rule.status}`);
      if (!ANY.has(rule.event_severity)) parts.push(`${t("rsum_event_severity")} ${rule.event_severity}`);
      for (const [path, pattern] of Object.entries(rule.match_fields ?? {})) parts.push(`${path} = ${pattern}`);
      parts.push(rule.threshold === "count"
        ? t("rsum_event_count", { n: String(rule.threshold_count), minutes: String(rule.window_minutes) })
        : t("rsum_event_each"));
      return parts.join(SEP);
    }
    case "traffic":
      return [...included(rule.condition), t("rsum_connections", { n: rule.threshold_connections.toLocaleString(),
        minutes: String(rule.window_minutes) })].join(SEP);
    case "bandwidth":
      return [...included(rule.condition), t("rsum_mbps", { n: String(rule.threshold_mbps),
        minutes: String(rule.window_minutes) })].join(SEP);
    case "volume":
      return [...included(rule.condition), t("rsum_mb", { n: String(rule.threshold_mb),
        minutes: String(rule.window_minutes) })].join(SEP);
    case "system":
      return t(CHECK_KEYS[rule.check] ?? rule.check);
    case "lateral": {
      const parts = [rule.detectors.map((d: string) => t(DETECTOR_KEYS[d] ?? d)).join(", "),
        t("rsum_min_severity", { severity: word(SEVERITY_KEYS, rule.min_severity) })];
      if (rule.critical_assets_only) parts.push(t("rsum_critical_only"));
      return parts.join(SEP);
    }
    default:
      return "";
  }
}

/** What the rule leaves out; "" when nothing. */
export function exclusionSummary(rule: AlertRule): string {
  if (rule.type === "traffic" || rule.type === "bandwidth" || rule.type === "volume") return excluded(rule.condition).join(SEP);
  if (rule.type === "lateral") return side(t("rsum_host"), rule.exclude).join(SEP);
  return "";
}
