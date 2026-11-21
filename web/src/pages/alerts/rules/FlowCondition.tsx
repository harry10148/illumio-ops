import type { ConditionChoices, FlowCondition as FlowConditionValue } from "../../../api/generated";
import { ConditionEditor } from "../../../components/ConditionEditor";
import { t } from "../../../i18n";

const COMMON_FIELDS = new Set(["src", "dst", "ports", "decisions"]);
const CONDITION_FIELDS = new Set([
  "decisions", "dst", "dst_exclude", "either", "either_exclude", "exclude_ports", "exclude_processes",
  "exclude_services", "exclude_system_accounts", "exclude_transmissions", "exclude_windows_services",
  "initiator_process", "initiator_processes", "initiator_user", "initiator_users", "ports", "service_process",
  "service_processes", "service_user", "service_users", "services", "src", "src_exclude", "text",
  "transmissions", "windows_services",
]);
const ENDPOINT_FIELDS = ["src", "dst", "either", "src_exclude", "dst_exclude", "either_exclude"] as const;

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined || value === false || value === "") return false;
  if (Array.isArray(value)) return value.some(hasValue);
  if (typeof value === "object") return Object.values(value as Record<string, unknown>).some(hasValue);
  return true;
}

function moreValues(condition: FlowConditionValue): boolean {
  return Object.entries(condition).some(([key, value]) => !COMMON_FIELDS.has(key) && hasValue(value));
}

function rawValues(condition: FlowConditionValue): Record<string, unknown> {
  const raw: Record<string, unknown> = {};
  const record = condition as Record<string, unknown>;
  for (const [key, value] of Object.entries(record)) {
    if (!CONDITION_FIELDS.has(key)) raw[key] = value;
  }
  for (const field of ENDPOINT_FIELDS) {
    const endpoint = record[field] as { match?: unknown; labels?: unknown[]; hrefs?: unknown[]; ips?: unknown[];
      ip_lists?: unknown[]; label_groups?: unknown[]; public?: boolean } | null | undefined;
    if (endpoint?.match !== undefined) {
      const hasLabels = Boolean(endpoint.labels?.length || endpoint.label_groups?.length);
      const hasHosts = Boolean(endpoint.hrefs?.length || endpoint.ips?.length || endpoint.ip_lists?.length || endpoint.public);
      if (!hasLabels || !hasHosts) raw[`${field}.match`] = endpoint.match;
    }
  }
  return raw;
}

export function FlowCondition({ condition, choices, onChange, onInvalid, forceMoreOpen = false,
  forceAdvancedOpen = false, forceExclusionsOpen = false }: {
  condition: FlowConditionValue;
  choices: ConditionChoices;
  onChange: (next: FlowConditionValue) => void;
  onInvalid: (field: string | null) => void;
  forceMoreOpen?: boolean;
  forceAdvancedOpen?: boolean;
  forceExclusionsOpen?: boolean;
}) {
  const raw = rawValues(condition);
  return <div className="stack" data-role="flow-condition">
    <ConditionEditor section="common" value={condition} choices={choices} onChange={onChange} onInvalid={onInvalid} full />
    <details data-role="flow-more" open={moreValues(condition) || forceMoreOpen}>
      <summary>{t("gui_reports_filter_more")}</summary>
      <ConditionEditor section="rest" value={condition} choices={choices} onChange={onChange} onInvalid={onInvalid} full
        forceAdvancedOpen={forceAdvancedOpen} forceExclusionsOpen={forceExclusionsOpen} />
      {Object.keys(raw).length > 0 && <div className="stack" data-role="flow-raw-values">
        <span>{t("rule_flow_raw_values")}</span>
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(raw, null, 2)}</pre>
      </div>}
    </details>
  </div>;
}
