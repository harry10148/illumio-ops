// What a new alert rule can be about (purpose-led UI spec §10): the event catalog's categories, the three traffic
// thresholds, every detector and every system check. A scenario's sentence says only what makes a rule of it fire,
// each written from the function that decides it (domain/alerting.py, domain/detectors.py, domain/anomaly.py).
import type { DetectorKind, RuleWrite, SystemCheck } from "../../api/generated";
import { CHECK_KEYS, CHECKS, DETECTOR_GROUPS, DETECTOR_KEYS } from "./common";

type Rule = RuleWrite["rule"];

export type ScenarioGroup = "detector" | "system";
// detector: a DetectorKind; system: a SystemCheck
// descKey says what makes it fire, in one sentence; notesKey what is left out of the count and what it needs before
// it is judged (null: nothing to add).
export type Scenario = { group: ScenarioGroup; id: string; labelKey: string; descKey: string | null; notesKey: string | null };

export const GROUPS: { group: ScenarioGroup; labelKey: string }[] = [
  { group: "detector", labelKey: "scn_group_detector" }, { group: "system", labelKey: "scn_group_system" },
];

const DETECTOR_DESC: Record<DetectorKind, string> = {
  fanout: "scn_det_fanout", new_admin_connection: "scn_det_new_admin_connection", pivot_chain: "scn_det_pivot_chain",
  blocked_surge: "scn_det_blocked_surge", non_admin_group: "scn_det_non_admin_group", cross_env: "scn_det_cross_env",
  account_fanout: "scn_det_account_fanout", unexpected_initiator: "scn_det_unexpected_initiator",
  peer_deviation: "scn_det_peer_deviation", volume_surge: "scn_det_volume_surge",
  account_new_source: "scn_det_account_new_source", suspicious_tool: "scn_det_suspicious_tool",
  new_process: "scn_det_new_process", auth_to_non_dc: "scn_det_auth_to_non_dc", new_dc_client: "scn_det_new_dc_client",
  directory_surge: "scn_det_directory_surge", direction_reversal: "scn_det_direction_reversal",
  new_pair_port: "scn_det_new_pair_port", quiet_host_wakes: "scn_det_quiet_host_wakes",
  data_staging: "scn_det_data_staging", off_hours: "scn_det_off_hours",
};
const CHECK_DESC: Record<SystemCheck, string> = {
  pce_health: "scn_sys_pce_health", collection_failing: "scn_sys_collection_failing", data_loss: "scn_sys_data_loss",
  job_failing: "scn_sys_job_failing", disk_low: "scn_sys_disk_low", siem_backlog: "scn_sys_siem_backlog",
};

const DETECTOR_NOTES: Partial<Record<DetectorKind, string>> = {
  new_admin_connection: "scn_det_new_admin_connection_notes", pivot_chain: "scn_det_pivot_chain_notes",
  blocked_surge: "scn_det_blocked_surge_notes", auth_to_non_dc: "scn_det_auth_to_non_dc_notes",
  non_admin_group: "scn_det_non_admin_group_notes", account_fanout: "scn_det_account_fanout_notes",
  unexpected_initiator: "scn_det_unexpected_initiator_notes", peer_deviation: "scn_det_peer_deviation_notes",
  volume_surge: "scn_det_volume_surge_notes", account_new_source: "scn_det_account_new_source_notes",
  suspicious_tool: "scn_det_suspicious_tool_notes", new_process: "scn_det_new_process_notes",
  new_dc_client: "scn_det_new_dc_client_notes", directory_surge: "scn_det_directory_surge_notes",
  direction_reversal: "scn_det_direction_reversal_notes", new_pair_port: "scn_det_new_pair_port_notes",
  quiet_host_wakes: "scn_det_quiet_host_wakes_notes", data_staging: "scn_det_data_staging_notes",
  off_hours: "scn_det_off_hours_notes",
};

const DETECTORS: Scenario[] = DETECTOR_GROUPS.flatMap((g) => g.kinds).map((id) => (
  { group: "detector", id, labelKey: DETECTOR_KEYS[id] ?? id, descKey: DETECTOR_DESC[id], notesKey: DETECTOR_NOTES[id] ?? null }));
const SYSTEM: Scenario[] = CHECKS.map((id) => (
  { group: "system", id, labelKey: CHECK_KEYS[id] ?? id, descKey: CHECK_DESC[id], notesKey: null }));

/** A group's scenarios in the order they are defined. */
export function scenariosOf(group: ScenarioGroup): Scenario[] {
  switch (group) {
    case "detector": return DETECTORS;
    default: return SYSTEM;
  }
}

export const scenarioKey = (s: Pick<Scenario, "group" | "id">) => `${s.group}:${s.id}`;

/** "?scenario=detector:fanout" → that scenario; null when there is none or it names nothing known. */
export function scenarioOf(search: URLSearchParams): Scenario | null {
  const [group, id] = (search.get("scenario") ?? "").split(":");
  if (!group || !id) return null;
  if (group !== "detector" && group !== "system") return null;
  return scenariosOf(group).find((s) => s.id === id) ?? null;
}

/** The detection and system scenarios covered by a rule, as "group:id". */
export function covering(rule: Rule): { scenarios: string[]; byPattern: boolean } {
  switch (rule.type) {
    case "system":
      return { scenarios: [`system:${rule.check}`], byPattern: false };
    case "lateral":
      return { scenarios: rule.detectors.map((d) => `detector:${d}`), byPattern: false };
    default:
      return { scenarios: [], byPattern: false };
  }
}
