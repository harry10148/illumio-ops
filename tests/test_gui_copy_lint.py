"""v3.1 §5.2 / §7 — the copy lint: what the GUI is not allowed to print.

Spec: docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md
§5.2 (文案與識別碼) and §7 (驗收). The 2026-09-04 source inventory behind it
counted the engineer-facing tells still on screen after 3B: 37 links whose
text was a route, 18 config keys printed as labels, 12 raw-JSON panes, 19
uppercase panel titles. Those numbers were an estimate over several patterns
at once; the per-rule counts this file measures are in each rule's comment,
and they are the ones being ratcheted down.

## Two kinds of rule in here, and the difference matters

**Live rules** fail today and are fixed by the task that owns them. **Ratchets**
already hold and exist so the pattern cannot come back. A ratchet is not
evidence of anything having been cleaned up, so each one says so rather than
being quietly counted as a passing check.

Rules whose subject belongs to a later task carry `xfail(strict=True)`: they
must fail now, and the day the work lands the strict marker turns the
unexpected pass into a failure, which is what forces the marker's removal.

## Where this file stops

A source lint sees idioms, not screens. It catches the one idiom that put
every route on screen after 3B, but it cannot promise that no OTHER expression
ever composes one. That promise is made against the rendered DOM instead, by
tests/test_v2_page_types_e2e.py::test_no_visible_text_is_a_route — which is
also what found four of the seven sites this file's first rule now names.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "src" / "static" / "js" / "v2"
CSS_DIR = ROOT / "src" / "static" / "css" / "v2"
CATALOGUES = [
    ROOT / "src" / "i18n_en.json",
    ROOT / "src" / "i18n_zh_TW.json",
    ROOT / "src" / "i18n" / "data" / "zh_explicit.json",
]


def _strip_comments(text: str) -> str:
    """Drop /* */ and // comments.

    Several modules quote the idioms below in their porting notes, and a
    module that DOCUMENTS a banned pattern is not committing it — the same
    distinction tests/test_color_token_lint.py draws for colour literals.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


def _sources() -> list[tuple[str, str]]:
    """Every module that renders operator-facing copy, as (relpath, code)."""
    paths = sorted((JS_DIR / "areas").glob("*.mjs"))
    paths += sorted((JS_DIR / "components").glob("*.mjs"))
    paths += [JS_DIR / "shell.mjs", JS_DIR / "app.mjs"]
    return [
        (str(p.relative_to(JS_DIR)), _strip_comments(p.read_text(encoding="utf-8")))
        for p in paths
    ]


def _hits(pattern: re.Pattern) -> dict[str, int]:
    out = {}
    for rel, text in _sources():
        n = len(pattern.findall(text))
        if n:
            out[rel] = n
    return out


# ── live rules ──────────────────────────────────────────────────────────────

def test_the_go_to_label_is_never_concatenated_with_anything():
    """§5.2: link text is a verb or an object name, never a route.

    Every route that reached the screen after 3B arrived the same way — the
    "Go to" label glued to a route variable: `t("gui_health_goto") + " " +
    route`, in the shared card helper, the home page, the traffic and event
    pages, the schedule board, the alert-ops panel and the health rail's
    popover. Seven sites, one idiom.

    The rule names the IDIOM rather than any one helper, because a helper is
    renameable and the idiom is the defect. The fix has no concatenation at
    all: `tf("gui_health_goto_named", {name})` with the destination resolved to
    the name the left-hand nav already gives it (components/page.mjs's
    goLabel), so the affordance survives and the address does not appear.
    """
    hits = _hits(re.compile(r'gui_health_goto"\)\s*\+'))
    assert hits == {}, (
        "the go-to label is being glued to a route (spec §5.2) — use "
        f"goLabel(route), which names the destination instead: {hits}"
    )


def test_no_hash_route_is_used_as_a_literal_piece_of_visible_text():
    """RATCHET (0 today): nothing may pass a route as an element's text.

    This has never fired; it exists so the deleted pattern cannot return as a
    literal. The runtime-composed form is the DOM gate's job — see the module
    docstring.
    """
    hits = _hits(re.compile(r"""text:\s*["']#/"""))
    assert hits == {}, hits


def test_no_catalogue_value_contains_a_hash_route():
    """RATCHET (0 today): a route inside a translated string is a route that
    cannot be localized, renamed, or checked by the router."""
    offenders = {}
    for path in CATALOGUES:
        data = json.loads(path.read_text(encoding="utf-8"))
        bad = {k: v for k, v in data.items() if isinstance(v, str) and "#/" in v}
        if bad:
            offenders[path.name] = bad
    assert offenders == {}, offenders


# ── rules whose subject belongs to a later task ─────────────────────────────

# Measured 2026-09-05: 18 call sites, all in areas/system.mjs. roField renders
# its first argument verbatim inside a <code> (system.mjs's roField), so every
# one of them prints a backend config key — `cache_read_max_rows`, `hec_token`,
# `old_password` — at an operator. Task 5 replaces the key with a human label.
_ROFIELD_RE = re.compile(r"""roField\(\s*["'][a-z][a-z0-9_]*["']""")


@pytest.mark.xfail(strict=True, reason="Task 5 rewrites system.mjs's roField labels")
def test_no_config_keys_are_printed_on_screen():
    """§5.2: `smtp.password` and friends are not words an operator knows."""
    hits = _hits(_ROFIELD_RE)
    assert hits == {}, (
        f"config keys rendered as field labels (spec §5.2): {hits}"
    )


# Measured 2026-09-05: 12 `.codepane` panes. Four are what §5.2 still allows —
# a log viewer or a debug console, where the raw line IS the content:
#
#   areas/system.mjs           2  the module-log drawer's message and raw line
#   areas/policy_scheduler.mjs 1  the schedule check's own log output
#   areas/policy_rules.mjs     1  the alert-ops output console (AL-13)
#
# The other eight are raw JSON or PEM dumped at an operator, and each has an
# owning task: system.mjs's DLQ error/payload and CSR output (Task 5),
# investigate.mjs's three event/flow JSON blocks (Tasks 3 and 6),
# policy_rules.mjs's rule-highlight JSON and policy_scheduler.mjs's PCE note
# preview (Task 6).
_CODEPANE_ALLOWED = {
    "areas/system.mjs": 2,
    "areas/policy_scheduler.mjs": 1,
    "areas/policy_rules.mjs": 1,
}


@pytest.mark.xfail(strict=True, reason="Tasks 5 and 6 remove the eight raw-JSON panes")
def test_raw_json_panes_are_confined_to_logs_and_debug_consoles():
    hits = _hits(re.compile(r'class:\s*"codepane'))
    assert hits == _CODEPANE_ALLOWED, (
        f"unexpected raw-output panes (spec §5.2): {hits} != {_CODEPANE_ALLOWED}"
    )


# §5.2/§7: uppercase is a device for eyebrows, table heads and chips. Anything
# else — panel titles, field labels, empty-state headings — is shouting.
_UPPERCASE_ALLOWED = {
    ".eyebrow",
    ".brand span",
    ".badge",
    "table.tbl th",
    ".side-card h4",
}
_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}", re.DOTALL)


def _uppercase_selectors() -> set[str]:
    found = set()
    for path in sorted(CSS_DIR.glob("*.css")):
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        for m in _RULE_RE.finditer(css):
            if "text-transform: uppercase" not in m.group(2):
                continue
            for sel in m.group(1).split(","):
                found.add(sel.strip())
    return found


@pytest.mark.xfail(strict=True, reason="Tasks 4-6 restyle the panel and field headings")
def test_uppercase_is_confined_to_eyebrows_table_heads_and_chips():
    extra = _uppercase_selectors() - _UPPERCASE_ALLOWED
    assert extra == set(), (
        f"selectors shouting in uppercase (spec §5.2): {sorted(extra)}"
    )


def test_the_uppercase_whitelist_is_not_a_dead_letter():
    """Guard the guard: the allowed selectors must really be in the stylesheets.

    Without this, renaming `.eyebrow` would leave a whitelist that permits
    nothing and a rule that looks stricter than it is.
    """
    found = _uppercase_selectors()
    assert _UPPERCASE_ALLOWED & found, (found, _UPPERCASE_ALLOWED)
