import { type ReactElement, useEffect, useMemo, useState } from "react";

import { call } from "../../../api/client";
import type { CatalogEventView, EventCatalog, EventRule, RuleListItem } from "../../../api/generated";
import { t } from "../../../i18n";
import { isPattern, owners, readSeverity, readStatus, resourceOf, showSeverity, showStatus, splitTypes,
  verbOf, writeSeverity, writeStatus, type Picks, type SeverityPick, type StatusPick } from "./model";

const emptyCatalog: EventCatalog = { categories: [] };
const SEVERITIES: SeverityPick[] = ["info", "warning", "err"];
const STATUSES: StatusPick[] = ["success", "failure"];

function typesInOrder(previous: readonly string[], next: readonly string[]): string[] {
  const remaining = new Map<string, number>();
  for (const entry of next) remaining.set(entry, (remaining.get(entry) ?? 0) + 1);
  const kept = previous.filter((entry) => {
    const count = remaining.get(entry) ?? 0;
    if (count === 0) return false;
    remaining.set(entry, count - 1);
    return true;
  });
  const appended: string[] = [];
  for (const entry of next) {
    const count = remaining.get(entry) ?? 0;
    if (count > 0) {
      appended.push(entry);
      remaining.set(entry, count - 1);
    }
  }
  return [...kept, ...appended];
}

function EventTypesBox({ types, onChange }: { types: readonly string[]; onChange: (types: string[]) => void }) {
  const [text, setText] = useState(() => types.join("\n"));
  const held = types.map((value) => value.trim()).filter(Boolean);
  const heldKey = JSON.stringify(held);
  useEffect(() => {
    setText((current) => JSON.stringify(current.split("\n").map((line) => line.trim()).filter(Boolean)) === heldKey
      ? current : held.join("\n"));
  }, [heldKey]);
  return <textarea name="event_types" rows={Math.max(3, text.split("\n").length)} value={text} spellCheck={false}
    placeholder={t("rule_event_manual_placeholder")}
    onChange={(event) => {
      const next = event.target.value.split("\n").map((line) => line.trim()).filter(Boolean);
      setText(event.target.value);
      onChange(next.length ? next : [""]);
    }} />;
}

function selectedTypes(rule: EventRule, catalogTypes: ReadonlySet<string>): string[] {
  return splitTypes(rule.event_types, catalogTypes).listed;
}

function valueSummary(picks: Picks<SeverityPick> | Picks<StatusPick>, labels: Record<string, string>): string {
  if (picks.kind === "raw") return picks.text;
  return picks.values.map((value) => labels[value]).join(t("rule_condition_separator"));
}

export function EventCondition({ rule, set, fieldError, fieldsSeq, forceOpen, items, onOpenOwner }: {
  rule: EventRule;
  set: (patch: Partial<EventRule>) => void;
  fieldError: (name: string) => ReactElement | null;
  fieldsSeq: number;
  forceOpen?: boolean;
  items: RuleListItem[];
  onOpenOwner: (id: string) => void;
}) {
  const [catalog, setCatalog] = useState<EventCatalog>(emptyCatalog);
  const [category, setCategory] = useState("*");
  const [query, setQuery] = useState("");
  const [verb, setVerb] = useState("all");
  const [hideOwned, setHideOwned] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [emptySeverity, setEmptySeverity] = useState(false);
  useEffect(() => {
    let active = true;
    void call("alert_rules.event_catalog").then((env) => { if (active && env.ok && env.data) setCatalog(env.data); });
    const media = window.matchMedia("(max-width: 720px)");
    const update = () => setMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => { active = false; media.removeEventListener("change", update); };
  }, []);

  const events = useMemo(() => catalog.categories.flatMap((group) => group.events.map((event) => ({ ...event, category: group }))), [catalog]);
  const byType = useMemo(() => new Map(events.map((event) => [event.event_type, event])), [events]);
  const catalogTypes = useMemo(() => new Set(byType.keys()), [byType]);
  const split = splitTypes(rule.event_types, catalogTypes);
  const picked = selectedTypes(rule, catalogTypes).map((type) => byType.get(type)).filter(Boolean) as CatalogEventView[];
  const scopeAll = rule.event_types.length === 1 && rule.event_types[0] === "*";
  const ownerMap = useMemo(() => owners(items, rule.id), [items, rule.id]);
  const q = query.trim().toLocaleLowerCase();
  const visible = events.filter((event) => {
    const textMatches = !q || `${event.event_type} ${t(event.description_key)} ${t(event.category.label_key)}`.toLocaleLowerCase().includes(q);
    const categoryMatches = q !== "" || category === "*" || category === "@selected"
      ? true : event.category.id === category;
    const selectedMatches = category !== "@selected" || rule.event_types.includes(event.event_type);
    const verbMatches = verb === "all" || verbOf(event.event_type) === verb;
    const hasOwner = Boolean(ownerMap.get(event.event_type)?.length);
    return textMatches && categoryMatches && selectedMatches && verbMatches && (!hideOwned || !hasOwner || rule.event_types.includes(event.event_type));
  });
  const groups = new Map<string, typeof visible>();
  for (const event of visible) {
    const resource = resourceOf(event.event_type);
    groups.set(resource, [...(groups.get(resource) ?? []), event]);
  }

  function updateTypes(next: string[]) {
    set({ event_types: typesInOrder(rule.event_types, next) as [string, ...string[]] });
  }
  function toggleType(type: string, checked: boolean) {
    const next = rule.event_types.filter((entry) => entry !== "*" && entry !== "");
    updateTypes(checked ? [...next, type] : next.filter((entry) => entry !== type));
  }
  function toggleGroup(resource: string, checked: boolean) {
    const exact = groups.get(resource)?.map((event) => event.event_type) ?? [];
    const current = rule.event_types.filter((entry) => entry !== "*" && entry !== "");
    const next = checked ? [...current, ...exact.filter((type) => !current.includes(type))] : current.filter((type) => !exact.includes(type));
    updateTypes(next);
  }
  function removeChip(type: string) {
    updateTypes(rule.event_types.filter((entry) => entry !== type));
  }
  function changeSeverity(value: SeverityPick, checked: boolean) {
    const next = new Set(emptySeverity ? [] : severity.kind === "set" ? severity.values : []);
    if (checked) next.add(value); else next.delete(value);
    if (!next.size) {
      setEmptySeverity(true);
      return;
    }
    setEmptySeverity(false);
    set({ event_severity: writeSeverity({ kind: "set", values: [...next] }) });
  }
  const severity = readSeverity(rule.event_severity);
  const status = readStatus(rule.status);
  const severityVisible = showSeverity(scopeAll, picked, rule.event_severity);
  const statusVisible = showStatus(scopeAll, picked, rule.status);
  const matchFieldsText = Object.entries(rule.match_fields ?? {}).map(([path, pattern]) => `${path}=${pattern}`).join("\n");
  const hasMore = split.other.some((entry) => entry.trim() !== "") || Object.keys(rule.match_fields ?? {}).length > 0 || Boolean(forceOpen);
  const severityLabels = { info: t("severity_info"), warning: t("severity_warning"), err: t("severity_error") };
  const statusLabels = { success: t("rule_event_result_success"), failure: t("rule_event_result_failure") };
  const actionLabels = { all: t("rule_event_action_all"), create: t("rule_event_action_create"), update: t("rule_event_action_update"),
    delete: t("rule_event_action_delete"), other: t("rule_event_action_other") };

  return <div className="event-condition" onSubmitCapture={(event) => {
    if (emptySeverity) { event.preventDefault(); event.stopPropagation(); }
  }}>
    <fieldset className="event-scope">
      <legend>{t("rule_event_types")}</legend>
      <label className="check"><input type="radio" name="event_scope" value="all" checked={scopeAll}
        onChange={() => set({ event_types: ["*"] })} />{t("rule_event_scope_all")}</label>
      <label className="check"><input type="radio" name="event_scope" value="picked" checked={!scopeAll}
        onChange={() => { if (scopeAll) set({ event_types: [""] }); }} />{t("rule_event_scope_picked")}</label>
    </fieldset>
    {fieldError("event_types")}
    <div className="event-chips" aria-label={t("rule_event_types")}>
      {rule.event_types.filter(Boolean).map((type, index) => {
        const known = byType.has(type);
        const label = isPattern(type) || type.includes("|") || type === "*" ? t("rule_event_chip_pattern") : t("rule_event_chip_external");
        return <span className="event-chip" key={`${type}-${index}`}><code>{type}</code>{!known && <small>{label}</small>}
          <button type="button" aria-label={t("rule_event_remove", { type })} onClick={() => removeChip(type)}>×</button></span>;
      })}
    </div>
    {!scopeAll && <div className="event-picker" data-role="event-picker">
      {mobile ? <label className="event-category-mobile">{t("rule_event_category")}
        <select aria-label={t("rule_event_category")} value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="*">{t("rule_event_category_all")} ({events.length})</option><option value="@selected">{t("rule_event_category_selected")} ({selectedTypes(rule, catalogTypes).length})</option>
          {catalog.categories.map((item) => <option key={item.id} value={item.id}>{t(item.label_key)} ({item.events.filter((e) => rule.event_types.includes(e.event_type)).length}/{item.events.length})</option>)}
        </select></label> : <nav className="event-category-rail" aria-label={t("rule_event_category")}>
        <button type="button" data-category="*" aria-current={category === "*"} onClick={() => setCategory("*")}>{t("rule_event_category_all")}<i>{events.length}</i></button>
        <button type="button" data-category="@selected" aria-current={category === "@selected"} onClick={() => setCategory("@selected")}>{t("rule_event_category_selected")}<i>{selectedTypes(rule, catalogTypes).length}</i></button>
        <hr />
        {catalog.categories.map((item) => {
          const count = item.events.filter((event) => rule.event_types.includes(event.event_type)).length;
          return <button type="button" key={item.id} data-category={item.id} aria-current={category === item.id} onClick={() => setCategory(item.id)}>
            {t(item.label_key)}<i><b>{count}/</b>{item.events.length}</i></button>;
        })}
      </nav>}
      <div className="event-picker-main">
        <div className="event-picker-toolbar">
          <input type="search" name="event_search" aria-label={t("rule_event_search_label")} placeholder={t("rule_event_search_placeholder", { n: String(events.length) })}
            value={query} onChange={(event) => setQuery(event.target.value)} />
          <fieldset className="event-verb-filter"><legend>{t("rule_event_action")}</legend>
            {(["all", "create", "update", "delete", "other"] as const).map((value) => <label className="check" key={value}>
              <input type="radio" name="event_verb" value={value} checked={verb === value} onChange={() => setVerb(value)} />
              {actionLabels[value]}
            </label>)}
          </fieldset>
          <label className="check"><input type="checkbox" name="hide_owned" checked={hideOwned} onChange={(event) => setHideOwned(event.target.checked)} />{t("rule_event_hide_owned")}</label>
        </div>
        <div className="event-picker-list">
          {[...groups].map(([resource, group]) => <div className="event-picker-group" key={resource}>
            {group.length >= 2 && <div className="event-picker-group-head"><strong><code>{resource}</code> · {t("rule_event_group_count", { n: String(group.length) })}</strong>
              <label className="check"><input type="checkbox" data-group={resource} checked={group.every((event) => rule.event_types.includes(event.event_type))}
                onChange={(event) => toggleGroup(resource, event.target.checked)} />{t("rule_event_group_all")}</label></div>}
            {group.map((event) => {
              const typeOwners = ownerMap.get(event.event_type) ?? [];
              return <div className="event-picker-row" key={event.event_type}>
                <label><input type="checkbox" data-event-type={event.event_type} checked={rule.event_types.includes(event.event_type)}
                  onChange={(input) => toggleType(event.event_type, input.target.checked)} /><code>{event.event_type}</code>
                  <span>{t(event.description_key)}</span></label>
                {typeOwners.length > 0 && <span className="event-owner-hint" data-role="event-owner">{t("rule_event_owner_prefix")} {typeOwners.map((owner, index) => {
                  if (owner.rule.type !== "event") return null;
                  const ownerStatus = readStatus(owner.rule.status);
                  const result = ownerStatus.kind === "raw" ? ownerStatus.text : ownerStatus.values.length === STATUSES.length ? "" : valueSummary(ownerStatus, statusLabels);
                  return <span key={owner.rule.id}>{index > 0 ? ", " : ""}<button type="button" onClick={() => onOpenOwner(owner.rule.id)}>{owner.display_name}</button>
                    {result && <> {t("rule_event_owner_result", { result })}</>}{!owner.rule.enabled && <> {t("rule_event_owner_disabled")}</>}</span>;
                })}</span>}
              </div>;
            })}
          </div>)}
          {visible.length === 0 && <p className="event-picker-empty">{t("rule_event_no_matches")}</p>}
        </div>
      </div>
    </div>}

    <div className="event-filter-row">
      {severityVisible ? <fieldset><legend>{t("rule_event_severity")}</legend>{severity.kind === "raw"
        ? <input name="event_severity" value={rule.event_severity} onChange={(event) => set({ event_severity: event.target.value })} />
        : SEVERITIES.map((value) => <label className="check" key={value}><input type="checkbox" name={`event_severity_${value}`}
          checked={!emptySeverity && severity.values.includes(value)} onChange={(event) => changeSeverity(value, event.target.checked)} />{severityLabels[value]}</label>)}
        {emptySeverity && <span className="field-error">{t("rule_event_severity_empty")}</span>}
        {fieldError("event_severity")}</fieldset>
        : <p className="hint">{t("rule_event_filter_unmarked_severity")}</p>}
      {statusVisible ? <label>{t("rule_event_status")}{status.kind === "raw"
        ? <input name="status" value={rule.status} onChange={(event) => set({ status: event.target.value })} />
        : <select name="status" value={status.values.length === STATUSES.length ? "all" : status.values[0] ?? "all"}
          onChange={(event) => set({ status: event.target.value === "all" ? writeStatus({ kind: "set", values: STATUSES }) : event.target.value })}>
          <option value="all">{t("rule_event_status_all")}</option><option value="success">{t("rule_condition_success")}</option>
          <option value="failure">{t("rule_condition_failure")}</option></select>}{fieldError("status")}</label>
        : <p className="hint">{t("rule_event_filter_unmarked_status")}</p>}
    </div>

    <details className="event-more" open={hasMore}>
      <summary>{t("rule_event_more")}</summary>
      <div className="event-more-body">
        {!scopeAll && <label>{t("rule_event_manual_types")}
          <EventTypesBox types={split.other.filter((entry) => entry !== "")} onChange={(nextOther) => {
            const merged = [...split.listed, ...nextOther.filter(Boolean)];
            updateTypes(merged.length ? merged : [""]);
          }} />
          <span className="hint">{t("rule_event_types_hint")}</span>{fieldError("event_types")}</label>}
        <label>{t("rule_match_fields_label")}
          <textarea key={fieldsSeq} name="match_fields" rows={3} defaultValue={matchFieldsText}
            placeholder={t("rule_event_match_fields_placeholder")}
            onBlur={(event) => {
              const parsed: Record<string, string> = {};
              for (const line of event.target.value.split("\n")) { const at = line.indexOf("="); if (at > 0) parsed[line.slice(0, at).trim()] = line.slice(at + 1).trim(); }
              set({ match_fields: parsed });
            }} />
          <span className="hint">{t("rule_match_fields_hint")}</span>{fieldError("match_fields")}</label>
      </div>
    </details>
  </div>;
}
