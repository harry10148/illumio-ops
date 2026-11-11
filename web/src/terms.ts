// Illumio's words said plainly, the PCE's own word beside them (purpose-led UI spec §5.6). One table: a page does
// not coin its own wording. The plain word is for the reader who does not know Illumio; the term in brackets is for
// checking against the PCE console.
import { t } from "./i18n";

const MODE_TERMS: Record<string, string> = {
  idle: "term_mode_idle", visibility_only: "term_mode_visibility_only", selective: "term_mode_selective",
  full: "term_mode_full",
};

/** An enforcement mode as "plain words (PCE term)"; a mode this table does not know is shown as it is. */
export function modeWord(mode: string): string {
  const key = MODE_TERMS[mode];
  return key ? t(key) : mode;
}
