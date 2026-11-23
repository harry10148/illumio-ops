// Enforcement mode names use the PCE's wording in both languages; a page does not coin its own wording.
import { t } from "./i18n";

const PROTOCOL_NAMES: Record<number, string> = {
  6: "TCP", 17: "UDP", 1: "ICMP", 58: "ICMPv6", 47: "GRE", 50: "ESP",
};

/** A protocol name; unknown numbers stay numeric and null/-1 means any protocol. */
export function protocolWord(proto: number | null | undefined): string {
  if (proto == null || proto === -1) return t("proto_any");
  return PROTOCOL_NAMES[proto] ?? String(proto);
}

/** A displayed service, with its protocol name. Any-protocol filters show only the port. */
export function portWord(port: number | null | undefined, proto: number | null | undefined,
                         toPort?: number | null): string {
  if (proto == null || proto === -1) {
    if (port == null || port < 0) return "—";
    return toPort != null ? `${port}-${toPort}` : String(port);
  }
  const protocol = protocolWord(proto);
  if (port == null || port < 0) return protocol;
  return `${port}${toPort != null ? `-${toPort}` : ""}/${protocol}`;
}

/** A service grouping key stays numeric for identity; use this only for its visible label. */
export function serviceWord(key: string): string {
  const [rawPort, rawProto] = key.split("/");
  const port = Number(rawPort), proto = Number(rawProto);
  return Number.isFinite(port) && Number.isFinite(proto) ? portWord(port, proto) : key;
}

const MODE_TERMS: Record<string, string> = {
  idle: "term_mode_idle", visibility_only: "term_mode_visibility_only", selective: "term_mode_selective",
  full: "term_mode_full",
};

/** An enforcement mode name; a mode this table does not know is shown as it is. */
export function modeWord(mode: string): string {
  const key = MODE_TERMS[mode];
  return key ? t(key) : mode;
}

const DECISION_TERMS: Record<string, string> = {
  allowed: "term_decision_allowed", potentially_blocked: "term_decision_potentially_blocked",
  blocked: "term_decision_blocked", unknown: "decision_unknown",
};

/** A policy decision where it is a name (a table cell, a filter option, a state) as "plain words (PCE term)"; a
 *  decision this table does not know is shown as it is. A sentence keeps the PCE's own word. */
export function decisionWord(decision: string): string {
  const key = DECISION_TERMS[decision];
  return key ? t(key) : decision;
}
