"""Guard against reviewer-facing prose leaking into operator-facing i18n copy.

Phase 2A ported the Phase 1 mockup into the production GUI. The mockup's copy
was written for design *reviewers* and carries source citations ("rules.py:171"),
internal field/function names ("settings.settings", "buildDestModal"),
"the product does X, this mockup does Y" comparisons, and self-congratulatory
dev-retrospective asides ("正是上一次重構最常見的失誤"). None of that belongs
in front of an operator running the live GUI.

Task 12b removed the subset that cited *deleted* source files. Task 12c (this
guard) covers every live key — one referenced by quoted string literal in the
v2 production JS or templates — regardless of which file it cites, and widens
the pattern set past plain "<file>:<line>" citations after a first pass on
the test machine surfaced variants a narrower regex had missed: bare
filenames with no line number, orphaned "(:NNN-NNN)" line-only remnants, more
internal storage paths, and "the product ..." comparisons that don't use the
literal word "v2".

Detection is quote-anchored (mirrors scripts kept in the T12c working notes,
not a substring scan) so a key is only in scope when the live v2 source
actually references it — an occurrence of `gui_al_fn_desc_flow` must not
credit `gui_al_fn_desc`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
ZH = json.loads((ROOT / "src" / "i18n_zh_TW.json").read_text(encoding="utf-8"))


def _live_keys() -> set[str]:
    src_files: list[Path] = []
    for pattern in ("src/static/js/v2/**/*.mjs", "src/static/js/v2/*.js", "src/templates/**/*.html"):
        src_files.extend(ROOT.glob(pattern))
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in src_files)
    live = set(re.findall(r"""['"]([a-z][A-Za-z0-9_]+)['"]""", text))
    live |= set(re.findall(r'data-i18n="([^"]+)"', text))
    return live


LIVE_KEYS = _live_keys()

# 1. "<filename>.<ext>:<line>" citations of yaml/json/html (py/js/mjs are
#    covered unconditionally by BARE_SRC_FILENAME below, since a first pass
#    found citations with no trailing line number at all).
CITE_WITH_LINE = re.compile(r"[A-Za-z_][A-Za-z0-9_/.-]*\.(?:yaml|json|html)\s*:\s*\d")

# 2. A bare source filename, with or without a trailing line number — the
#    test-machine pass found "transcribed from integrations.js's forwarder
#    block" with no ":NNN" attached at all.
BARE_SRC_FILENAME = re.compile(r"\b[A-Za-z_][A-Za-z0-9_-]*\.(?:py|js|mjs)\b")

# 3. A citation reduced to just the line number, e.g. "(:1513-1515)" when a
#    sentence already named the file once and abbreviated the second cite.
BARE_LINE_CITE = re.compile(r"[（(]\s*:\s*\d{1,5}(?:\s*[-–]\s*\d{1,5})?\s*[）)]")

# 4. Anchor IDs from the mockup's design-doc numbering scheme.
ANCHOR_ID = re.compile(r"\b(?:OV|IN|AL|AU|RP|SY)-\d\d\b")

# 5. "the product does X" framing, comparing this GUI to some other
#    implementation. The word has no legitimate use in operator copy.
PRODUCT_WORD_EN = re.compile(r"\bproduct\b", re.IGNORECASE)
PRODUCT_WORD_ZH = re.compile(r"產品")

# 6. Internal storage paths / function names that leaked into prose instead
#    of staying implementation detail. `report_schedules` is excluded when
#    it's part of the background job name `tick_report_schedules`, which is
#    a legitimate, page-consistent thing to tell an operator to go look up.
FORBIDDEN_LITERAL = (
    "settings.settings",
    "settings.api",
    "dashboard_queries",
    "dashboard_overview.job_health",
    "buildCacheForm",
    "buildDestModal",
    "siemToggleCondFields",
    "status.alert_channels",
    "__set",
    "__length",
    "DESIGN-ADDED",
    "mockup",
)
REPORT_SCHEDULES_BARE = re.compile(r"(?<!tick_)report_schedules")

# 7. Dev-retrospective / self-congratulatory asides about our own past work.
DEV_RETROSPECTIVE = re.compile(r"重構|refactor", re.IGNORECASE)

# 8. HTTP plumbing narrated at the operator: "Calls GET /api/rules/<idx>/
#    highlight, which returns ...". Which endpoint the button hits is ours to
#    know, not theirs to read. Catches the method+path form; a bare /api/ path
#    is caught too, since gui_url_help's example URL is already allowlisted.
HTTP_PLUMBING = re.compile(r"(?:GET|POST|PUT|DELETE|PATCH)\s+/\S*|/api/")

# 9. The word "endpoint" in operator copy. Every legitimate use in the
#    dictionary today (network-endpoint event labels, report prose) sits on a
#    key the v2 GUI never reads, and this test only ever looks at live keys —
#    so a hit here means plumbing narration. A future live key that genuinely
#    means a network endpoint goes in ALLOWLIST.
ENDPOINT_WORD = re.compile(r"端點|\bendpoints?\b", re.IGNORECASE)

# 10. Mockup-era copy. "mockup" is already in FORBIDDEN_LITERAL; this is its
#     Chinese half, which shipped in five keys the port left behind.
MOCKUP_ZH = re.compile(r"設計稿")

# 11b. Which tier of our own architecture did the thing. An operator acts on
#     what the appliance does, not on which half of it did it; "the backend
#     answers 400" is a sentence about us, and it is usually covering for
#     behaviour that should have been fixed rather than described.
TIER_NARRATION = re.compile(r"後端|前端|\bthe (?:backend|frontend|server side)\b", re.IGNORECASE)

# 11c. HTTP status codes quoted at the operator.
STATUS_CODE = re.compile(r"回\s*[45]\d\d|\b(?:returns?|answers?|responds? with)\s+(?:an?\s+)?[45]\d\d\b", re.IGNORECASE)

# 11d. A request/response body pasted into the copy.
JSON_LITERAL = re.compile(r'\{\s*"')

# 11. Internal machinery named in prose: the state file behind a response, the
#     write lock a handler takes, ANSI stripping, and function-call syntax.
INTERNALS = re.compile(r"狀態檔|寫入鎖|ANSI|\b[a-z_]+\.[a-z_]+\(|\brun_debug_mode\b|\?[a-z]+=")

# 12. This app's own UI wiring, narrated at the operator: which of its fields
#     has a form control, how a save merges, which catalogue key a label came
#     from, what a previous redesign lost. The operator asked for the list of
#     these to be removed, and the reason it is a lint and not just a deletion
#     is that every one of them was written in good faith — the panel that
#     prompted this was titled "Stored, with no control in this form" and
#     existed to prove that five settings were not being dropped. Proving that
#     is the save path's job; saying it on screen only tells the operator about
#     our wiring. `.kv`-style storage vocabulary ("this key", "the settings
#     object") is the tell, not the intent.
UI_WIRING = re.compile(
    r"表單控制項|設定物件|覆蓋既有|沒有對應的[^，。]*控制項|唯一的控制項"
    r"|這個鍵|這些鍵|鍵名|i18n_key"
    r"|\bform control\b|\bsettings object\b|\bmerges over\b|\bthis key\b|\bthese keys\b",
    re.IGNORECASE,
)

# 13. Our own release history. "This changed in the last redesign" dates the
#     copy the moment it ships and means nothing to someone who never saw the
#     old screen.
OUR_HISTORY = re.compile(r"上一次改版|改版|\bprevious redesign\b|\bused to (?:be|show|live)\b", re.IGNORECASE)

# 14. A catalogue VALUE that is a bare storage identifier. Not prose about the
#     wiring — the wiring itself, shipped as a label: gui_siem_dispatch_tick's
#     en value was the literal string "dispatch_tick_seconds", so the English
#     GUI captioned a form field with its config key while the zh_TW side had
#     a real label all along. The roField lint in tests/test_gui_copy_lint.py
#     bans the read-only idiom that produces this; nothing looked at the
#     catalogue itself, where an EDITABLE field's label also comes from.
BARE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[_.][a-z0-9]+)+$")

# 15. Operator copy that names one of OUR OWN stored fields. Different from
#     rule 12: that one catches prose ABOUT the wiring, this one catches the
#     wiring's vocabulary leaking into an otherwise fine sentence — "clears
#     event_watermark", "timeline_24h is an empty array", "comes back in
#     note_clear_failed", "(gui_app_required)". Placeholders are stripped
#     first, because `{high_risk}` is a slot, not a field.
#
#     FIELD_NAME_OK is a per-key allowlist, and every entry is a name the
#     OPERATOR meets outside this app — a PCE href segment they read in the
#     target column, a value they type into a matcher, an option in a dropdown,
#     a background job named on the jobs page, or a stored value the message
#     exists to say is wrong. Those are the domain's vocabulary, not ours.
INTERNAL_FIELD = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?:\.[a-z][a-z0-9_]*)*\b")
PLACEHOLDER = re.compile(r"\{[^}]*\}")
FIELD_NAME_OK = {
    # report-type / schedule values the message exists to report as invalid
    "gui_au_dow_unknown", "gui_au_rep_type_unknown",
    # PCE href segments, which the operator reads in the target column
    "gui_au_kind_note", "gui_au_target_note_rule",
    # a background job named on the jobs page (already excluded by rule 6)
    "gui_au_rep_tick_note",
    # the two allowed values, in a validation error about them
    "gui_err_invalid_rule_sched_type",
    # a matcher path the operator types by hand
    "gui_ev_field_matchers_hint", "gui_ev_matchers_placeholder",
    # the PCE's own API object a destructive write touches — naming it is the
    # point of the warning
    "gui_rhc_needs_enable_confirm", "gui_rp_rhc_detail_missing_ven", "gui_rp_rhc_i_draft",
    # the literal option values in the format dropdown
    "gui_siem_format_help",
}
# Words that read as identifiers but are ordinary English or product terms.
FIELD_NAME_SKIP = {
    "event_type", "rule_set", "rule_sets", "sec_rules", "deny_rules", "user_login",
    "policy_usage", "rule_hit_count", "security_risk", "app_summary",
    "network_inventory", "policy_diff", "policy_resolver", "traffic_filter",
}

# Known-legitimate substrings that would otherwise false-positive; stripped
# before pattern matching (not string-replaced in the actual copy).
ALLOWLIST = {
    "gui_url_help": ("https://pce.example.com:8443/api/v2",),
    "cli_config_valid": ("config.json",),
}


def _scrub(key: str, value: str) -> str:
    scrubbed = value
    for allowed in ALLOWLIST.get(key, ()):
        scrubbed = scrubbed.replace(allowed, "")
    return scrubbed


def _violations(key: str, value: str) -> list[str]:
    text = _scrub(key, value)
    hits = []
    if CITE_WITH_LINE.search(text):
        hits.append("src-cite")
    if BARE_SRC_FILENAME.search(text):
        hits.append("bare-src-filename")
    if BARE_LINE_CITE.search(text):
        hits.append("bare-line-cite")
    if ANCHOR_ID.search(text):
        hits.append("anchor-id")
    if PRODUCT_WORD_EN.search(text) or PRODUCT_WORD_ZH.search(text):
        hits.append("product-comparison")
    for lit in FORBIDDEN_LITERAL:
        if lit in text:
            hits.append(f"internal-path:{lit}")
    if REPORT_SCHEDULES_BARE.search(text):
        hits.append("internal-path:report_schedules")
    if DEV_RETROSPECTIVE.search(text):
        hits.append("dev-retrospective")
    if BARE_IDENTIFIER.fullmatch(text.strip()):
        hits.append("value-is-a-config-key")
    if key not in FIELD_NAME_OK and len(text) >= 25:
        bare = PLACEHOLDER.sub(" ", text)
        named = [w for w in set(INTERNAL_FIELD.findall(bare)) if w not in FIELD_NAME_SKIP]
        if named:
            hits.append("names-internal-field:" + ",".join(sorted(named)))
    if UI_WIRING.search(text):
        hits.append("ui-wiring")
    if OUR_HISTORY.search(text):
        hits.append("our-history")
    if HTTP_PLUMBING.search(text):
        hits.append("http-plumbing")
    if ENDPOINT_WORD.search(text):
        hits.append("endpoint-word")
    if MOCKUP_ZH.search(text):
        hits.append("mockup-zh")
    if INTERNALS.search(text):
        hits.append("internals")
    if TIER_NARRATION.search(text):
        hits.append("tier-narration")
    if STATUS_CODE.search(text):
        hits.append("status-code")
    if JSON_LITERAL.search(text):
        hits.append("json-literal")
    return hits


def test_no_reviewer_copy_in_live_keys():
    offenders: dict[str, dict[str, list[str]]] = {}
    for key in sorted(LIVE_KEYS):
        for label, table in (("EN", EN), ("ZH", ZH)):
            value = table.get(key)
            if not isinstance(value, str):
                continue
            hits = _violations(key, value)
            if hits:
                offenders.setdefault(key, {})[label] = hits

    assert not offenders, (
        f"{len(offenders)} live i18n keys still carry reviewer-only source "
        "citations / internal paths / product-vs-mockup framing:\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(offenders.items()))
    )
