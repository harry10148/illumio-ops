import type {
  CatalogEventView, ConditionChoices, FlowCondition, PackRule, RuleListItem, RuleWrite,
} from "../../../api/generated";
import { t } from "../../../i18n";
import { conditionSummary, exclusionSummary, excluded, included } from "../ruleSummary";

export type Rule = RuleWrite["rule"];
export type Item = RuleListItem;
export type Table = "event" | "flow" | "special";
export type State = "off" | "rec" | "on";
export type Picks<T> = { kind: "set"; values: T[] } | { kind: "raw"; text: string };
export type SeverityPick = "info" | "warning" | "err";
export type StatusPick = "success" | "failure";
export type Verb = "create" | "update" | "delete" | "other";
export type FlowRule = Extract<Rule, { type: "traffic" | "bandwidth" | "volume" }>;

const NEW_ID = "0".repeat(32);
const ANY = new Set(["", "*", "any", "all"]);
const ALL_SEVERITIES: SeverityPick[] = ["info", "warning", "err"];
const ALL_STATUSES: StatusPick[] = ["success", "failure"];

export function tableOf(rule: Rule): Table {
  if (rule.type === "event") return "event";
  if (rule.type === "traffic" || rule.type === "bandwidth" || rule.type === "volume") return "flow";
  return "special";
}

export function order(items: Item[], pack: PackRule[]): Item[] {
  const positions = new Map<string, number>();
  pack.forEach((entry, index) => {
    if (!positions.has(entry.name_key)) positions.set(entry.name_key, index);
  });
  const builtIn = items.map((item, index) => ({ item, index, position: item.rule.pack_key === null
    ? undefined : positions.get(item.rule.pack_key) }));
  const found = builtIn.filter((entry) => entry.position !== undefined)
    .sort((a, b) => (a.position! - b.position!) || (a.index - b.index));
  const rest = builtIn.filter((entry) => entry.position === undefined).sort((a, b) => a.index - b.index);
  return [...found, ...rest].map((entry) => entry.item);
}

export function stateOf(rule: Rule): State {
  if (!rule.enabled) return "off";
  return rule.notify ? "on" : "rec";
}

export function withState(rule: Rule, state: State): Rule {
  if (state === "off") return { ...rule, enabled: false } as Rule;
  return { ...rule, enabled: true, notify: state === "on" } as Rule;
}

function anyValue(value: string): boolean {
  return ANY.has(value.trim().toLowerCase());
}

export function readSeverity(value: string): Picks<SeverityPick> {
  if (anyValue(value)) return { kind: "set", values: [...ALL_SEVERITIES] };
  const parts = value.split("|").map((part) => part.trim().toLowerCase());
  const aliases: Record<string, SeverityPick> = { info: "info", warning: "warning", err: "err", error: "err" };
  if (parts.length > 0 && parts.every((part) => part !== "" && aliases[part] !== undefined)) {
    const values = new Set(parts.map((part) => aliases[part]));
    return { kind: "set", values: ALL_SEVERITIES.filter((severity) => values.has(severity)) };
  }
  return { kind: "raw", text: value };
}

export function writeSeverity(picks: Picks<SeverityPick>): string {
  if (picks.kind === "raw") return picks.text;
  const values = new Set(picks.values);
  if (values.size === 0) throw new Error();
  if (ALL_SEVERITIES.every((severity) => values.has(severity))) return "all";
  return ALL_SEVERITIES.filter((severity) => values.has(severity)).join("|");
}

export function readStatus(value: string): Picks<StatusPick> {
  if (anyValue(value)) return { kind: "set", values: [...ALL_STATUSES] };
  const parts = value.split("|").map((part) => part.trim().toLowerCase());
  const allowed = new Set<string>(ALL_STATUSES);
  if (parts.length > 0 && parts.every((part) => allowed.has(part))) {
    const values = new Set(parts as StatusPick[]);
    return { kind: "set", values: ALL_STATUSES.filter((status) => values.has(status)) };
  }
  return { kind: "raw", text: value };
}

export function writeStatus(picks: Picks<StatusPick>): string {
  if (picks.kind === "raw") return picks.text;
  const values = new Set(picks.values);
  if (values.size === 0) throw new Error();
  if (ALL_STATUSES.every((status) => values.has(status))) return "all";
  return ALL_STATUSES.filter((status) => values.has(status)).join("|");
}

export function verbOf(eventType: string): Verb {
  const last = eventType.slice(eventType.lastIndexOf(".") + 1);
  return last === "create" || last === "update" || last === "delete" ? last : "other";
}

export function resourceOf(eventType: string): string {
  const firstDot = eventType.indexOf(".");
  return firstDot < 0 ? eventType : eventType.slice(0, firstDot);
}

// Kept in sync with RuleEditor.tsx's former helper and domain/alertrules._looks_like_regex.
export const isPattern = (pattern: string): boolean => /^\^|\$$|[*+?[\](){}$\\]/.test(pattern);

export function splitTypes(types: string[], catalog: ReadonlySet<string>): { listed: string[]; other: string[] } {
  const listed: string[] = [];
  const other: string[] = [];
  for (const type of types) {
    if (catalog.has(type) && !type.includes("|") && !isPattern(type)) listed.push(type);
    else other.push(type);
  }
  return { listed, other };
}

export function owners(items: Item[], exceptId: string | null): Map<string, Item[]> {
  const result = new Map<string, Item[]>();
  for (const item of items) {
    if (item.rule.type !== "event" || item.rule.id === exceptId) continue;
    const itemTypes = new Set<string>();
    for (const entry of item.rule.event_types) {
      if (isPattern(entry)) continue;
      for (const eventType of entry.split("|").map((part) => part.trim()).filter(Boolean)) {
        itemTypes.add(eventType);
      }
    }
    for (const eventType of itemTypes) {
      const current = result.get(eventType) ?? [];
      current.push(item);
      result.set(eventType, current);
    }
  }
  return result;
}

export function showSeverity(scopeAll: boolean, picked: CatalogEventView[], value: string): boolean {
  return scopeAll || picked.some((event) => event.severity_filter) || !anyValue(value);
}

export function showStatus(scopeAll: boolean, picked: CatalogEventView[], value: string): boolean {
  return scopeAll || picked.some((event) => event.status_filter) || !anyValue(value);
}

export const PACK_SKIP = ["id", "pack_key", "enabled", "notify", "name"] as const;

function comparable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((entry) => entry === undefined ? null : comparable(entry));
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(record).filter((key) => record[key] !== undefined).sort()
      .map((key) => [key, comparable(record[key])]));
  }
  if (typeof value === "number" && !Number.isFinite(value)) return null;
  return value;
}

function jsonEqual(left: unknown, right: unknown): boolean {
  return JSON.stringify(comparable(left)) === JSON.stringify(comparable(right));
}

function withoutPackSkip(rule: Rule): Record<string, unknown> {
  return Object.fromEntries(Object.entries(rule).filter(([key]) => !PACK_SKIP.includes(key as typeof PACK_SKIP[number])));
}

export function differsFromPack(rule: Rule, pack: PackRule[]): boolean {
  if (rule.pack_key === null) return false;
  const baseline = pack.find((entry) => entry.name_key === rule.pack_key);
  return baseline !== undefined && !jsonEqual(withoutPackSkip(rule), withoutPackSkip(baseline.rule));
}

export function fromTemplate(template: PackRule, name: string): Rule {
  return { ...template.rule, id: NEW_ID, pack_key: null, name, enabled: true, notify: true };
}

export function restored(rule: Rule, template: PackRule): Rule {
  return { ...template.rule, id: rule.id, pack_key: rule.pack_key, enabled: rule.enabled, notify: rule.notify, name: "" };
}

export function blank(type: Rule["type"]): Rule {
  const base = { id: NEW_ID, name: "", pack_key: null, enabled: true, notify: true, cooldown_minutes: 30, throttle: null };
  const condition: FlowCondition = {};
  switch (type) {
    case "event":
      return { ...base, type, severity: null, event_types: [""], status: "all", event_severity: "all", match_fields: {},
        threshold: "immediate", threshold_count: 1, window_minutes: 10 };
    case "traffic":
      return { ...base, type, severity: "medium", condition, threshold_connections: 25, window_minutes: 10 };
    case "bandwidth":
      return { ...base, type, severity: "medium", condition, threshold_mbps: 100, window_minutes: 60 };
    case "volume":
      return { ...base, type, severity: "medium", condition, threshold_mb: 1024, window_minutes: 60 };
    case "system":
      return { ...base, type, severity: "high", check: "pce_health", cooldown_minutes: 60 };
    default:
      return { ...base, type: "lateral", severity: null, detectors: ["fanout"], min_severity: "medium",
        critical_assets_only: false, exclude: { public: true }, cooldown_minutes: 0 };
  }
}

function metricThreshold(rule: FlowRule): number {
  switch (rule.type) {
    case "traffic": return rule.threshold_connections;
    case "bandwidth": return rule.threshold_mbps;
    case "volume": return rule.threshold_mb;
  }
}

export function switchMetric(rule: FlowRule, to: "traffic" | "bandwidth" | "volume",
                             touched: { window: boolean; threshold: boolean }): FlowRule {
  const defaults = blank(to) as FlowRule;
  const shared = {
    id: rule.id,
    name: rule.name,
    pack_key: rule.pack_key,
    enabled: rule.enabled,
    notify: rule.notify,
    cooldown_minutes: rule.cooldown_minutes,
    throttle: rule.throttle,
    severity: rule.severity,
    condition: rule.condition,
    window_minutes: touched.window ? rule.window_minutes : defaults.window_minutes,
  };
  const threshold = touched.threshold ? metricThreshold(rule) : metricThreshold(defaults);
  switch (to) {
    case "traffic": return { ...shared, type: "traffic", threshold_connections: threshold };
    case "bandwidth": return { ...shared, type: "bandwidth", threshold_mbps: threshold };
    case "volume": return { ...shared, type: "volume", threshold_mb: threshold };
  }
}

const SEP = "; ";
export function conditionText(rule: Rule, choices: ConditionChoices): { main: string; excluded: string } {
  if (rule.type === "event") {
    const parts = [rule.event_types.map((eventType) => eventType === "*" ? t("rsum_all_events") : eventType).join(t("rule_condition_separator"))];
    const severity = readSeverity(rule.event_severity);
    if (severity.kind === "raw") parts.push(`${t("rsum_event_severity")} ${severity.text}`);
    else if (severity.values.length !== ALL_SEVERITIES.length) {
      const words: Record<SeverityPick, string> = { info: t("severity_info"), warning: t("severity_warning"), err: t("severity_error") };
      parts.push(`${t("rule_condition_severity")} ${severity.values.map((value) => words[value]).join(t("rule_condition_separator"))}`);
    }
    const status = readStatus(rule.status);
    if (status.kind === "raw") parts.push(`${t("rsum_status")} ${status.text}`);
    else if (status.values.length !== ALL_STATUSES.length) {
      const words: Record<StatusPick, string> = { success: t("rule_condition_success"), failure: t("rule_condition_failure") };
      parts.push(`${t("rule_condition_status")} ${status.values.map((value) => words[value]).join(t("rule_condition_separator"))}`);
    }
    for (const [path, pattern] of Object.entries(rule.match_fields ?? {})) parts.push(`${path} = ${pattern}`);
    return { main: parts.join(SEP), excluded: "" };
  }
  if (rule.type === "traffic" || rule.type === "bandwidth" || rule.type === "volume") {
    return { main: included(rule.condition, choices).join(SEP), excluded: excluded(rule.condition, choices).join(SEP) };
  }
  return { main: conditionSummary(rule, choices), excluded: exclusionSummary(rule, choices) };
}

export function thresholdText(rule: Rule): string {
  switch (rule.type) {
    case "event":
      if (rule.threshold === "count") {
        return t("rule_threshold_event_count", { minutes: String(rule.window_minutes), n: String(rule.threshold_count) });
      }
      return rule.threshold_count > 1
        ? t("rule_threshold_immediate_count", { n: String(rule.threshold_count) })
        : t("rsum_event_each");
    case "traffic":
      return t("rule_threshold_traffic", { minutes: String(rule.window_minutes), n: String(rule.threshold_connections) });
    case "bandwidth":
      return t("rule_threshold_bandwidth", { minutes: String(rule.window_minutes), n: String(rule.threshold_mbps) });
    case "volume":
      return t("rule_threshold_volume", { minutes: String(rule.window_minutes), n: String(rule.threshold_mb) });
    default:
      return "";
  }
}
