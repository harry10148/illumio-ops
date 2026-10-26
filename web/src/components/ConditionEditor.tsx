// A flow condition (FlowCondition) as a form: source and destination by label or address, and what each must not
// be; ports, the reported decision, the initiating process or user. Labels come from the inventory the store holds.
import { useState } from "react";

import type { EndpointFilter, FlowCondition, LabelChoice, PolicyDecision, PortProto } from "../api/generated";
import { t } from "../i18n";

const DECISIONS: PolicyDecision[] = ["allowed", "potentially_blocked", "blocked", "unknown"];
const DECISION_KEYS: Record<string, string> = {
  allowed: "decision_allowed", potentially_blocked: "decision_potentially_blocked", blocked: "decision_blocked",
  unknown: "decision_unknown",
};

const SIDE_KEYS: Record<string, string> = {
  src: "cond_src", dst: "cond_dst", src_exclude: "cond_src_exclude", dst_exclude: "cond_dst_exclude",
};

const list = (text: string) => text.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);

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

function Side({ name, value, choices, onChange }: {
  name: string; value: EndpointFilter | null | undefined; choices: LabelChoice[];
  onChange: (next: EndpointFilter | null) => void;
}) {
  const v = value ?? {};
  const [key, setKey] = useState(choices[0]?.key ?? "");
  const choice = choices.find((c) => c.key === key);
  const [val, setVal] = useState("");
  const labels = v.labels ?? [];
  const set = (next: EndpointFilter) => onChange((next.labels?.length || next.ips?.length || next.hrefs?.length) ? next : null);
  const add = () => {
    const chosen = val || choice?.values[0] || "";
    if (!key || !chosen) return;
    const others = labels.filter((l) => l.key !== key);
    const same = labels.find((l) => l.key === key);
    const values = same ? [...new Set([...same.values, chosen])] : [chosen];
    set({ ...v, labels: [...others, { key, values: values as [string, ...string[]] }] });
  };
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
      {choices.length > 0 && (
        <div className="row">
          <select name={`${name}_label_key`} value={key} onChange={(e) => { setKey(e.target.value); setVal(""); }}>
            {choices.map((c) => <option key={c.key} value={c.key}>{c.key}</option>)}
          </select>
          <select name={`${name}_label_value`} value={val || choice?.values[0] || ""} onChange={(e) => setVal(e.target.value)}>
            {(choice?.values ?? []).map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <button type="button" className="btn-quiet" onClick={add}>{t("cond_add_label")}</button>
        </div>
      )}
      {choice?.truncated && <p className="hint">{t("lateral_labels_truncated", { n: "500" })}</p>}
      <label>
        {t("cond_ips")}
        <input name={`${name}_ips`} defaultValue={(v.ips ?? []).join(", ")} placeholder="10.0.0.5, 10.1.0.0/16"
               onBlur={(e) => set({ ...v, ips: list(e.target.value) })} />
      </label>
      <p className="hint">{t(name.endsWith("_exclude") ? "cond_exclude_hint" : "cond_side_hint")}</p>
    </fieldset>
  );
}

export function ConditionEditor({ value, choices, onChange, onInvalid }: {
  value: FlowCondition; choices: LabelChoice[]; onChange: (next: FlowCondition) => void;
  onInvalid: (field: string | null) => void;
}) {
  const decisions = value.decisions ?? [];
  return (
    <div className="stack" data-role="condition">
      <div className="form-grid">
        <Side name="src" value={value.src} choices={choices} onChange={(src) => onChange({ ...value, src })} />
        <Side name="dst" value={value.dst} choices={choices} onChange={(dst) => onChange({ ...value, dst })} />
      </div>
      <details open={Boolean(value.src_exclude || value.dst_exclude)}>
        <summary>{t("cond_exclusions")}</summary>
        <div className="form-grid">
          <Side name="src_exclude" value={value.src_exclude} choices={choices}
                onChange={(src_exclude) => onChange({ ...value, src_exclude })} />
          <Side name="dst_exclude" value={value.dst_exclude} choices={choices}
                onChange={(dst_exclude) => onChange({ ...value, dst_exclude })} />
        </div>
      </details>
      <label>
        {t("cond_ports")}
        <input name="ports" defaultValue={portsText(value.ports)} placeholder="22, 3389, 135-139, 53/udp"
               onBlur={(e) => {
                 const ports = parsePorts(e.target.value);
                 if (ports === null) onInvalid("condition.ports");
                 else { onInvalid(null); onChange({ ...value, ports }); }
               }} />
      </label>
      <fieldset>
        <legend>{t("cond_decisions")}</legend>
        <div className="row">
          {DECISIONS.map((d) => (
            <label key={d} className="check">
              <input type="checkbox" name={`decision_${d}`} checked={decisions.includes(d)}
                     onChange={(e) => onChange({ ...value, decisions: e.target.checked ? [...decisions, d] : decisions.filter((x) => x !== d) })} />
              {t(DECISION_KEYS[d] ?? d)}
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
      </div>
      <label className="check">
        <input type="checkbox" name="exclude_system_accounts" checked={value.exclude_system_accounts ?? false}
               onChange={(e) => onChange({ ...value, exclude_system_accounts: e.target.checked })} />
        {t("cond_exclude_system")}
      </label>
    </div>
  );
}
