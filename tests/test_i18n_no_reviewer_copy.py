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
