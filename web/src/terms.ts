// Enforcement mode names use the PCE's wording in both languages; a page does not coin its own wording.
import { t } from "./i18n";

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
