// What a dimension value adds to the conditions, and the conditions as removable chips (spec §6.5.3).
import type { AggRow, EndpointFilter, EventRequest, FlowCondition1, FlowRequest, SegmentDimension } from "../../api/generated";

export type Req = FlowRequest | EventRequest;

export interface Dim {
  dimension: SegmentDimension;
  labelKey?: string;
}

export const FLOW_DIMS: SegmentDimension[] = [
  "src_host", "dst_host", "service", "initiator_process", "initiator_user", "service_process", "service_user",
  "decision", "direction",
];
export const EVENT_DIMS: SegmentDimension[] = ["event_type", "event_host", "event_severity", "actor"];
export const OPEN_BY_DEFAULT: SegmentDimension[] = ["src_host", "dst_host", "service", "event_type", "event_host"];

export function dimId(d: Dim): string {
  return d.labelKey ? `${d.dimension}:${d.labelKey}` : d.dimension;
}

/** "443/6" → the port and protocol; "-1/1" is a protocol without a port. */
function service(key: string): { port: number | null; proto: number } {
  const [port = -1, proto = 0] = key.split("/").map(Number);
  return { port: port < 0 ? null : port, proto };
}

function endpoint(f: EndpointFilter | null | undefined, key: string, labelKey?: string): EndpointFilter {
  const e: EndpointFilter = { hrefs: [...(f?.hrefs ?? [])], ips: [...(f?.ips ?? [])], labels: [...(f?.labels ?? [])] };
  if (labelKey) {
    const found = (e.labels ?? []).find((l) => l.key === labelKey);
    if (!found) e.labels = [...(e.labels ?? []), { key: labelKey, values: [key] }];
    else if (!found.values.includes(key)) {
      e.labels = (e.labels ?? []).map((l) => (l === found ? { key: labelKey, values: [...found.values, key] } : l));
    }
  } else if (key.startsWith("ip:")) {
    if (!e.ips!.includes(key.slice(3))) e.ips = [...e.ips!, key.slice(3)];
  } else if (!e.hrefs!.includes(key)) e.hrefs = [...e.hrefs!, key];
  // only what is set, so a value already chosen gives back the same conditions (chosen())
  return Object.fromEntries(Object.entries(e).filter(([, v]) => (v as unknown[]).length)) as EndpointFilter;
}

/** The request with one more value of a dimension: the same dimension ORs, others AND (the filter's own rules).
 * Direction has no condition (it is shown, not filtered). */
export function addValue(req: Req, d: Dim, row: AggRow): Req | null {
  const key = String(row.keys[0] ?? "");
  if (req.mode === "events") {
    const r = { ...req };
    if (d.dimension === "event_type") r.event_types = [...new Set([...(r.event_types ?? []), key])];
    else if (d.dimension === "event_host") r.host_hrefs = [...new Set([...(r.host_hrefs ?? []), key])];
    else if (d.dimension === "event_severity") r.severities = [...new Set([...(r.severities ?? []), key])];
    else if (d.dimension === "actor") r.actor = key;
    else return null;
    return r;
  }
  const c: FlowCondition1 = { ...(req.condition ?? {}) };
  switch (d.dimension) {
    case "src_host": case "src_label": c.src = endpoint(c.src, key, d.labelKey); break;
    case "dst_host": case "dst_label": c.dst = endpoint(c.dst, key, d.labelKey); break;
    case "service": {
      const s = service(key);
      if (!(c.ports ?? []).some((p) => p.port === s.port && p.proto === s.proto)) c.ports = [...(c.ports ?? []), s];
      break;
    }
    case "initiator_process": c.initiator_process = key; break;
    case "initiator_user": c.initiator_user = key; break;
    case "service_process": c.service_process = key; break;
    case "service_user": c.service_user = key; break;
    case "decision":
      c.decisions = [...new Set([...(c.decisions ?? []), key as NonNullable<FlowCondition1["decisions"]>[number]])];
      break;
    default: return null;
  }
  return { ...req, condition: c };
}

export interface Chip {
  id: string;
  /** i18n key of the condition's name and the value to show */
  labelKey: string;
  value: string;
  remove: (req: Req) => Req;
}

function shown(names: Record<string, string>, v: string): string {
  return names[v] ?? (v.startsWith("ip:") ? v.slice(3) : v.split("/").slice(-2).join("/"));
}

/** Every atomic condition, each removable on its own. `names`: href → hostname seen in the panel. */
export function chips(req: Req, names: Record<string, string>): Chip[] {
  const out: Chip[] = [];
  if (req.mode === "events") {
    const lists: [keyof EventRequest, string][] = [["event_types", "wb_cond_event_type"], ["host_hrefs", "wb_cond_event_host"],
      ["severities", "wb_cond_severity"]];
    for (const [field, labelKey] of lists) {
      for (const v of (req[field] as string[] | undefined) ?? []) {
        out.push({ id: `${field}:${v}`, labelKey, value: shown(names, v),
          remove: (r) => ({ ...r, [field]: ((r as EventRequest)[field] as string[]).filter((x) => x !== v) }) as Req });
      }
    }
    if (req.actor) out.push({ id: "actor", labelKey: "wb_cond_actor", value: req.actor, remove: (r) => ({ ...r, actor: null }) as Req });
    return out;
  }
  const c = req.condition ?? {};
  const side = (k: "src" | "dst" | "src_exclude" | "dst_exclude", labelKey: string) => {
    const e = c[k];
    if (!e) return;
    const without = (r: Req, patch: Partial<EndpointFilter>): Req => {
      const cond = { ...((r as FlowRequest).condition ?? {}) };
      const next = { ...(cond[k] ?? {}), ...patch };
      cond[k] = (next.hrefs?.length || next.ips?.length || next.labels?.length) ? next : null;
      return { ...r, condition: cond } as Req;
    };
    for (const h of e.hrefs ?? []) out.push({ id: `${k}:h:${h}`, labelKey, value: shown(names, h),
      remove: (r) => without(r, { hrefs: ((r as FlowRequest).condition?.[k]?.hrefs ?? []).filter((x) => x !== h) }) });
    for (const ip of e.ips ?? []) out.push({ id: `${k}:i:${ip}`, labelKey, value: ip,
      remove: (r) => without(r, { ips: ((r as FlowRequest).condition?.[k]?.ips ?? []).filter((x) => x !== ip) }) });
    for (const l of e.labels ?? []) out.push({ id: `${k}:l:${l.key}`, labelKey, value: `${l.key}=${l.values.join(", ")}`,
      remove: (r) => without(r, { labels: ((r as FlowRequest).condition?.[k]?.labels ?? []).filter((x) => x.key !== l.key) }) });
  };
  side("src", "wb_cond_src");
  side("dst", "wb_cond_dst");
  side("src_exclude", "wb_cond_src_not");
  side("dst_exclude", "wb_cond_dst_not");
  const cond = (r: Req) => ({ ...((r as FlowRequest).condition ?? {}) });
  for (const p of c.ports ?? []) out.push({ id: `port:${p.port}/${p.proto}`, labelKey: "wb_cond_port",
    value: `${p.port ?? "*"}${p.to_port ? `-${p.to_port}` : ""}/${p.proto ?? "*"}`,
    remove: (r) => ({ ...r, condition: { ...cond(r), ports: (cond(r).ports ?? []).filter((x) => x !== p) } }) as Req });
  for (const p of c.exclude_ports ?? []) out.push({ id: `xport:${p.port}/${p.proto}`, labelKey: "wb_cond_port_not",
    value: `${p.port ?? "*"}/${p.proto ?? "*"}`,
    remove: (r) => ({ ...r, condition: { ...cond(r), exclude_ports: (cond(r).exclude_ports ?? []).filter((x) => x !== p) } }) as Req });
  for (const d of c.decisions ?? []) out.push({ id: `decision:${d}`, labelKey: "wb_cond_decision", value: d,
    remove: (r) => ({ ...r, condition: { ...cond(r), decisions: (cond(r).decisions ?? []).filter((x) => x !== d) } }) as Req });
  const single: [keyof FlowCondition1, string][] = [["initiator_process", "wb_cond_initiator_process"],
    ["initiator_user", "wb_cond_initiator_user"], ["service_process", "wb_cond_service_process"],
    ["service_user", "wb_cond_service_user"], ["text", "wb_cond_text"]];
  for (const [field, labelKey] of single) {
    const v = c[field];
    if (typeof v === "string" && v) out.push({ id: field, labelKey, value: v,
      remove: (r) => ({ ...r, condition: { ...cond(r), [field]: null } }) as Req });
  }
  if (c.exclude_system_accounts) out.push({ id: "nosys", labelKey: "wb_cond_no_system", value: "",
    remove: (r) => ({ ...r, condition: { ...cond(r), exclude_system_accounts: false } }) as Req });
  return out;
}

/** Whether a panel value is already in the conditions (shown as chosen). */
export function chosen(req: Req, d: Dim, key: string): boolean {
  const probe = addValue(req, d, { keys: [key], display: [null], value: 0, bytes_known: null });
  return probe !== null && JSON.stringify(probe) === JSON.stringify(req);
}
