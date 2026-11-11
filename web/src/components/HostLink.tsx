// Wherever a host or an address is named, it leads to that host's page (purpose-led UI spec §6.3), landing on the
// section the place it was named in is about.
import { Link } from "react-router-dom";

import { HostName } from "./ui";

export type HostSection =
  | "status" | "alerts" | "different" | "usual" | "connections" | "would-block" | "ransomware" | "tamper" | "quarantine";

export function hostPath(hostKey: string, section?: HostSection): string {
  return `/hosts?${new URLSearchParams({ key: hostKey }).toString()}${section ? `#${section}` : ""}`;
}

export function HostLink({ hostKey, name, section }: { hostKey: string; name: string; section?: HostSection }) {
  return (
    <Link to={hostPath(hostKey, section)} data-role="host-link" onClick={(e) => e.stopPropagation()}>
      <HostName name={name} />
    </Link>
  );
}

const STATUS_RULES = new Set(["rule_agent_offline", "rule_agent_heartbeat", "rule_agent_suspend"]);
const STATUS_EVENTS = ["system_task.agent_offline_check", "system_task.agent_missed_heartbeats_check", "agent.suspend"];

/** Where on the host page an alert's hosts should land: its VEN state for an offline, heartbeat or suspend alert,
 * the tampering record for a tampering alert, its connections for a detection or a traffic alert. */
export function sectionForAlert(a: {
  rule_type: string; pack_key?: string | null; params?: Record<string, unknown>;
}): HostSection | undefined {
  if (a.rule_type === "event") {
    const types = Array.isArray(a.params?.event_types) ? (a.params.event_types as unknown[]).map(String) : [];
    if (a.pack_key === "rule_agent_tampering" || types.includes("agent.tampering")) return "tamper";
    if ((a.pack_key && STATUS_RULES.has(a.pack_key)) || types.some((x) => STATUS_EVENTS.includes(x))) return "status";
    return undefined;
  }
  if (a.rule_type === "system") return undefined;
  return "connections";
}
