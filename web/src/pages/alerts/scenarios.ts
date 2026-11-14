// What a new alert rule can be about (purpose-led UI spec §10): the event catalog's categories, the three traffic
// thresholds, every detector and every system check. A scenario's sentence says only what makes a rule of it fire,
// each written from the function that decides it (domain/alerting.py, domain/detectors.py, domain/anomaly.py).
import type { DetectorKind, EventCatalog, RuleWrite, SystemCheck } from "../../api/generated";
import { CHECK_KEYS, CHECKS, DETECTOR_GROUPS, DETECTOR_KEYS, TYPE_KEYS } from "./common";

type Rule = RuleWrite["rule"];

export type ScenarioGroup = "event" | "flow" | "detector" | "system";
// event: id = the catalog category id, labelKey = its label_key, descKey = null (the line under it is computed: how
//        many event types the category holds)
// flow: "traffic" | "bandwidth" | "volume";  detector: a DetectorKind;  system: a SystemCheck
// descKey says what makes it fire, in one sentence; notesKey what is left out of the count and what it needs before
// it is judged (null: nothing to add).
export type Scenario = { group: ScenarioGroup; id: string; labelKey: string; descKey: string | null; notesKey: string | null };

export const GROUPS: { group: ScenarioGroup; labelKey: string }[] = [
  { group: "event", labelKey: "scn_group_event" }, { group: "flow", labelKey: "scn_group_flow" },
  { group: "detector", labelKey: "scn_group_detector" }, { group: "system", labelKey: "scn_group_system" },
];

const FLOW_DESC: Record<string, string> = {
  traffic: "scn_flow_traffic", bandwidth: "scn_flow_bandwidth", volume: "scn_flow_volume",
};
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

const FLOW_NOTES: Record<string, string> = { bandwidth: "scn_flow_bandwidth_notes", volume: "scn_flow_volume_notes" };
const DETECTOR_NOTES: Partial<Record<DetectorKind, string>> = {
  new_admin_connection: "scn_det_new_admin_connection_notes", blocked_surge: "scn_det_blocked_surge_notes",
  non_admin_group: "scn_det_non_admin_group_notes", account_fanout: "scn_det_account_fanout_notes",
  unexpected_initiator: "scn_det_unexpected_initiator_notes", peer_deviation: "scn_det_peer_deviation_notes",
  volume_surge: "scn_det_volume_surge_notes", account_new_source: "scn_det_account_new_source_notes",
  suspicious_tool: "scn_det_suspicious_tool_notes", new_process: "scn_det_new_process_notes",
  new_dc_client: "scn_det_new_dc_client_notes", directory_surge: "scn_det_directory_surge_notes",
  direction_reversal: "scn_det_direction_reversal_notes", new_pair_port: "scn_det_new_pair_port_notes",
  quiet_host_wakes: "scn_det_quiet_host_wakes_notes", data_staging: "scn_det_data_staging_notes",
  off_hours: "scn_det_off_hours_notes",
};

const FLOW: Scenario[] = Object.keys(FLOW_DESC).map((id) => (
  { group: "flow", id, labelKey: TYPE_KEYS[id] ?? id, descKey: FLOW_DESC[id] ?? null, notesKey: FLOW_NOTES[id] ?? null }));
const DETECTORS: Scenario[] = DETECTOR_GROUPS.flatMap((g) => g.kinds).map((id) => (
  { group: "detector", id, labelKey: DETECTOR_KEYS[id] ?? id, descKey: DETECTOR_DESC[id], notesKey: DETECTOR_NOTES[id] ?? null }));
const SYSTEM: Scenario[] = CHECKS.map((id) => (
  { group: "system", id, labelKey: CHECK_KEYS[id] ?? id, descKey: CHECK_DESC[id], notesKey: null }));

/** A group's scenarios in the order they are defined; the event group is the catalog's categories, so it is empty
 * until the catalog is there. */
export function scenariosOf(group: ScenarioGroup, catalog: EventCatalog | null): Scenario[] {
  switch (group) {
    case "event":
      return (catalog?.categories ?? []).map((c) => ({ group, id: c.id, labelKey: c.label_key, descKey: null, notesKey: null }));
    case "flow": return FLOW;
    case "detector": return DETECTORS;
    default: return SYSTEM;
  }
}

export const scenarioKey = (s: Pick<Scenario, "group" | "id">) => `${s.group}:${s.id}`;

/** "?scenario=detector:fanout" → that scenario; null when there is none or it names nothing known. An event category
 * is known only by the catalog: without one its name is the rule type's, with one an id it does not hold is null. */
export function scenarioOf(search: URLSearchParams, catalog: EventCatalog | null = null): Scenario | null {
  const [group, id] = (search.get("scenario") ?? "").split(":");
  if (!group || !id) return null;
  if (group === "event") {
    if (!catalog) return { group, id, labelKey: TYPE_KEYS.event ?? group, descKey: null, notesKey: null };
    return scenariosOf(group, catalog).find((s) => s.id === id) ?? null;
  }
  if (group !== "flow" && group !== "detector" && group !== "system") return null;
  return scenariosOf(group, null).find((s) => s.id === id) ?? null;
}

/** The scenarios a rule is filed under, as "group:id". An event rule is filed by each event type it names exactly as
 * the catalog lists it; "*", a|b, a regular expression and a type the catalog does not list are patterns
 * (byPattern), filed under no category — what such a pattern covers is not worked out here. */
export function covering(rule: Rule, catalog: EventCatalog): { scenarios: string[]; byPattern: boolean } {
  switch (rule.type) {
    case "event": {
      const category = new Map(catalog.categories.flatMap((c) => c.events.map((e) => [e.event_type, c.id] as const)));
      const found = new Set<string>();
      let byPattern = false;
      for (const type of rule.event_types) {
        const id = category.get(type);
        if (id === undefined) byPattern = true;
        else found.add(`event:${id}`);
      }
      return { scenarios: [...found], byPattern };
    }
    case "traffic": case "bandwidth": case "volume":
      return { scenarios: [`flow:${rule.type}`], byPattern: false };
    case "system":
      return { scenarios: [`system:${rule.check}`], byPattern: false };
    default:
      return { scenarios: rule.detectors.map((d) => `detector:${d}`), byPattern: false };
  }
}
