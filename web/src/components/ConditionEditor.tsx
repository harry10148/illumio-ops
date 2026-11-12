// A flow condition (FlowCondition) as a form: source and destination (or either end) by label, label group, address
// or IP list, and what each must not be; ports and named services, the reported decision, processes, users, Windows
// service names and transmission. Labels and the PCE objects come from what the inventory last read
// (alert_rules.condition_choices); one named that the PCE no longer has is shown as such, never dropped.
import { useState } from "react";

import type { ConditionChoices, EndpointFilter, FlowCondition, PolicyDecision, PortProto } from "../api/generated";
import { t } from "../i18n";
import { decisionWord } from "../terms";

export const NO_CHOICES: ConditionChoices = { labels: [], ip_lists: [], label_groups: [], services: [] };

const DECISIONS: PolicyDecision[] = ["allowed", "potentially_blocked", "blocked", "unknown"];
type Transmission = NonNullable<FlowCondition["transmissions"]>[number];
const TRANSMISSIONS: Transmission[] = ["unicast", "broadcast", "multicast"];
const TX_KEYS: Record<string, string> = { unicast: "cond_tx_unicast", broadcast: "cond_tx_broadcast", multicast: "cond_tx_multicast" };

const SIDE_KEYS: Record<string, string> = {
  src: "cond_src", dst: "cond_dst", src_exclude: "cond_src_exclude", dst_exclude: "cond_dst_exclude", exclude: "rule_exclude",
  either: "cond_either", either_exclude: "cond_either_exclude",
};
const HINT_KEYS: Record<string, string> = {
  src: "cond_side_hint", dst: "cond_side_hint", exclude: "rule_exclude_hint", either: "cond_either_hint",
};

const list = (text: string) => text.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
const names = (text: string) => text.split(",").map((s) => s.trim()).filter(Boolean);

function portsText(ports: PortProto[] | undefined): string {
  return (ports ?? []).map((p) => `${p.port ?? ""}${p.to_port != null ? `-${p.to_port}` : ""}${p.proto === 17 ? "/udp" : ""}`).join(", ");
}

function parsePorts(text: string): PortProto[] | null {
  const out: PortProto[] = [];
  for (const token of list(text)) {
    const m = /^(\d+)(?:-(\d+))?(?:\/(tcp|udp))?$/i.exec(token);
    if (!m) return null;
    out.push({ port: Number(m[1]), to_port: m[2] ? Number(m[2]) : null, proto: m[3]?.toLowerCase() === "udp" ? 17 : 6 });
  }
  return out;
}

/** PCE objects named by href: chips (a name the PCE no longer has says so) and a picker of the known ones. */
function HrefPicker({ name, kind, title, hint, picked, options, gone, addKey, onChange }: {
  name: string; kind: "ip-list" | "label-group" | "service"; title: string; hint?: string; picked: string[];
  options: { href: string; name: string }[]; gone: string; addKey: string; onChange: (next: string[]) => void;
}) {
  const [pick, setPick] = useState("");
  if (options.length === 0 && picked.length === 0) return null;
  const label = (href: string) => options.find((o) => o.href === href)?.name ?? gone;
  return (
    <div className="stack" data-role={name}>
      <span>{title}</span>
      {picked.length > 0 && (
        <ul className="chips">
          {picked.map((href) => (
            <li key={href} className="chip" {...{ [`data-${kind}`]: href }}>
              {label(href)}
              <button type="button" className="btn-quiet" aria-label={t("lateral_remove_label")}
                      onClick={() => onChange(picked.filter((x) => x !== href))}>×</button>
            </li>
          ))}
        </ul>
      )}
      {options.length > 0 && (
        <div className="row">
          <select name={name} aria-label={title} value={pick || options[0]?.href || ""} onChange={(e) => setPick(e.target.value)}>
            {options.map((o) => <option key={o.href} value={o.href}>{o.name}</option>)}
          </select>
          <button type="button" className="btn-quiet"
                  onClick={() => {
                    const href = pick || options[0]?.href;
                    if (href && !picked.includes(href)) onChange([...picked, href]);
                  }}>{t(addKey)}</button>
        </div>
      )}
      {hint && <p className="hint">{hint}</p>}
    </div>
  );
}

// One endpoint condition; the lateral alert rule's exclusion uses it alone (name "exclude").
export function Side({ name, value, choices, onChange }: {
  name: string; value: EndpointFilter | null | undefined; choices: ConditionChoices;
  onChange: (next: EndpointFilter | null) => void;
}) {
  const v = value ?? {};
  const labelChoices = choices.labels;
  const [key, setKey] = useState(labelChoices[0]?.key ?? "");
  const choice = labelChoices.find((c) => c.key === key);
  const [val, setVal] = useState("");
  const labels = v.labels ?? [];
  const set = (next: EndpointFilter) =>
    onChange((next.labels?.length || next.label_groups?.length || next.ips?.length || next.hrefs?.length
      || next.ip_lists?.length || next.public) ? next : null);
  const add = () => {
    const chosen = val || choice?.values[0] || "";
    if (!key || !chosen) return;
    const others = labels.filter((l) => l.key !== key);
    const same = labels.find((l) => l.key === key);
    const values = same ? [...new Set([...same.values, chosen])] : [chosen];
    set({ ...v, labels: [...others, { key, values: values as [string, ...string[]] }] });
  };
  const groups = choices.label_groups.map((g) => ({ href: g.href, name: `${g.name} (${g.key})` }));
  return (
    <fieldset className="stack" data-side={name}>
      <legend>{t(SIDE_KEYS[name] ?? name)}</legend>
      {labels.length > 0 && (
        <ul className="chips">
          {labels.map((l) => (
            <li key={l.key} className="chip">
              {`${l.key}=${l.values.join("|")}`}
              <button type="button" className="btn-quiet" aria-label={t("lateral_remove_label")}
                      onClick={() => set({ ...v, labels: labels.filter((x) => x !== l) })}>×</button>
            </li>
          ))}
        </ul>
      )}
      {labelChoices.length > 0 && (
        <div className="row">
          <select name={`${name}_label_key`} value={key} onChange={(e) => { setKey(e.target.value); setVal(""); }}>
            {labelChoices.map((c) => <option key={c.key} value={c.key}>{c.key}</option>)}
          </select>
          <select name={`${name}_label_value`} value={val || choice?.values[0] || ""} onChange={(e) => setVal(e.target.value)}>
            {(choice?.values ?? []).map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <button type="button" className="btn-quiet" onClick={add}>{t("cond_add_label")}</button>
        </div>
      )}
      {choice?.truncated && <p className="hint">{t("lateral_labels_truncated", { n: "500" })}</p>}
      <HrefPicker name={`${name}_label_group`} kind="label-group" title={t("cond_label_groups")} hint={t("cond_label_group_hint")}
                  picked={v.label_groups ?? []} options={groups} gone={t("cond_label_group_gone")}
                  addKey="cond_add_label_group" onChange={(label_groups) => set({ ...v, label_groups })} />
      <label>
        {t("cond_ips")}
        <input name={`${name}_ips`} defaultValue={(v.ips ?? []).join(", ")} placeholder="10.0.0.5, 10.1.0.0/16"
               onBlur={(e) => set({ ...v, ips: list(e.target.value) })} />
      </label>
      <HrefPicker name={`${name}_ip_list`} kind="ip-list" title={t("cond_ip_lists")} picked={v.ip_lists ?? []} options={choices.ip_lists}
                  gone={t("cond_ip_list_gone")} addKey="cond_add_ip_list" onChange={(ip_lists) => set({ ...v, ip_lists })} />
      <label className="check">
        <input type="checkbox" name={`${name}_public`} checked={v.public ?? false}
               onChange={(e) => set({ ...v, public: e.target.checked })} />
        <span>{t("cond_public")} <span className="hint">{t("cond_public_hint")}</span></span>
      </label>
      <p className="hint">{t(HINT_KEYS[name] ?? "cond_exclude_hint")}</p>
    </fieldset>
  );
}

function Transmissions({ name, legendKey, value, onChange }: {
  name: string; legendKey: string; value: Transmission[]; onChange: (next: Transmission[]) => void;
}) {
  return (
    <fieldset>
      <legend>{t(legendKey)}</legend>
      <div className="row">
        {TRANSMISSIONS.map((x) => (
          <label key={x} className="check">
            <input type="checkbox" name={`${name}_${x}`} checked={value.includes(x)}
                   onChange={(e) => onChange(e.target.checked ? [...value, x] : value.filter((y) => y !== x))} />
            {t(TX_KEYS[x] ?? x)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function ConditionEditor({ value, choices, onChange, onInvalid }: {
  value: FlowCondition; choices: ConditionChoices; onChange: (next: FlowCondition) => void;
  onInvalid: (field: string | null) => void;
}) {
  const decisions = value.decisions ?? [];
  const services = choices.services;
  const excluding = Boolean(value.src_exclude || value.dst_exclude || value.either_exclude || value.exclude_ports?.length
    || value.exclude_services?.length || value.exclude_processes?.length || value.exclude_windows_services?.length
    || value.exclude_transmissions?.length);
  const ports = (field: "ports" | "exclude_ports", text: string) => {
    const parsed = parsePorts(text);
    if (parsed === null) onInvalid(`condition.${field}`);
    else { onInvalid(null); onChange({ ...value, [field]: parsed }); }
  };
  return (
    <div className="stack" data-role="condition">
      <div className="form-grid">
        <Side name="src" value={value.src} choices={choices} onChange={(src) => onChange({ ...value, src })} />
        <Side name="dst" value={value.dst} choices={choices} onChange={(dst) => onChange({ ...value, dst })} />
      </div>
      <details open={Boolean(value.either)}>
        <summary>{t("cond_either")}</summary>
        <Side name="either" value={value.either} choices={choices} onChange={(either) => onChange({ ...value, either })} />
      </details>
      <label>
        {t("cond_ports")}
        <input name="ports" defaultValue={portsText(value.ports)} placeholder="22, 3389, 135-139, 53/udp"
               onBlur={(e) => ports("ports", e.target.value)} />
      </label>
      <HrefPicker name="service" kind="service" title={t("cond_services")} hint={t("cond_services_hint")} picked={value.services ?? []}
                  options={services} gone={t("cond_service_gone")} addKey="cond_add_service"
                  onChange={(next) => onChange({ ...value, services: next })} />
      <fieldset>
        <legend>{t("cond_decisions")}</legend>
        <div className="row">
          {DECISIONS.map((d) => (
            <label key={d} className="check">
              <input type="checkbox" name={`decision_${d}`} checked={decisions.includes(d)}
                     onChange={(e) => onChange({ ...value, decisions: e.target.checked ? [...decisions, d] : decisions.filter((x) => x !== d) })} />
              {decisionWord(d)}
            </label>
          ))}
        </div>
        <p className="hint">{t("cond_decisions_hint")}</p>
      </fieldset>
      <div className="form-grid">
        <label>
          {t("cond_initiator_process")}
          <input name="initiator_process" value={value.initiator_process ?? ""}
                 onChange={(e) => onChange({ ...value, initiator_process: e.target.value || null })} />
        </label>
        <label>
          {t("cond_initiator_user")}
          <input name="initiator_user" value={value.initiator_user ?? ""}
                 onChange={(e) => onChange({ ...value, initiator_user: e.target.value || null })} />
        </label>
        <label>
          {t("cond_windows_services")}
          <input name="windows_services" defaultValue={(value.windows_services ?? []).join(", ")} placeholder="wuauserv, Spooler"
                 onBlur={(e) => onChange({ ...value, windows_services: names(e.target.value) })} />
        </label>
      </div>
      <Transmissions name="transmission" legendKey="cond_transmissions" value={value.transmissions ?? []}
                     onChange={(transmissions) => onChange({ ...value, transmissions })} />
      <p className="hint">{t("cond_transmissions_hint")}</p>
      <label className="check">
        <input type="checkbox" name="exclude_system_accounts" checked={value.exclude_system_accounts ?? false}
               onChange={(e) => onChange({ ...value, exclude_system_accounts: e.target.checked })} />
        {t("cond_exclude_system")}
      </label>
      <details open={excluding}>
        <summary>{t("cond_exclusions")}</summary>
        <div className="stack">
          <div className="form-grid">
            <Side name="src_exclude" value={value.src_exclude} choices={choices}
                  onChange={(src_exclude) => onChange({ ...value, src_exclude })} />
            <Side name="dst_exclude" value={value.dst_exclude} choices={choices}
                  onChange={(dst_exclude) => onChange({ ...value, dst_exclude })} />
          </div>
          <Side name="either_exclude" value={value.either_exclude} choices={choices}
                onChange={(either_exclude) => onChange({ ...value, either_exclude })} />
          <label>
            {t("cond_exclude_ports")}
            <input name="exclude_ports" defaultValue={portsText(value.exclude_ports)} placeholder="53/udp, 123/udp"
                   onBlur={(e) => ports("exclude_ports", e.target.value)} />
          </label>
          <HrefPicker name="exclude_service" kind="service" title={t("cond_exclude_services")} picked={value.exclude_services ?? []}
                      options={services} gone={t("cond_service_gone")} addKey="cond_add_service"
                      onChange={(next) => onChange({ ...value, exclude_services: next })} />
          <div className="form-grid">
            <label>
              {t("cond_exclude_processes")}
              <input name="exclude_processes" defaultValue={(value.exclude_processes ?? []).join(", ")}
                     placeholder="svchost.exe, backup-agent"
                     onBlur={(e) => onChange({ ...value, exclude_processes: names(e.target.value) })} />
            </label>
            <label>
              {t("cond_exclude_windows_services")}
              <input name="exclude_windows_services" defaultValue={(value.exclude_windows_services ?? []).join(", ")}
                     onBlur={(e) => onChange({ ...value, exclude_windows_services: names(e.target.value) })} />
            </label>
          </div>
          <Transmissions name="exclude_transmission" legendKey="cond_exclude_transmissions"
                         value={value.exclude_transmissions ?? []}
                         onChange={(exclude_transmissions) => onChange({ ...value, exclude_transmissions })} />
          <p className="hint">{t("cond_exclude_hint")}</p>
        </div>
      </details>
    </div>
  );
}
