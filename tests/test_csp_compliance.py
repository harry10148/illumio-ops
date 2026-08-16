"""CSP-compliance regression tests.

These tests guard against re-introducing inline handlers and inline scripts,
which break under this app's strict ``script-src 'self'`` policy (no
'unsafe-inline', no nonce injection — see src/gui/__init__.py's `_csp`).

Phase 2A Task 11 retargeted this file. It used to check
src/templates/index.html and src/static/js/rule-scheduler.js, both of which
were deleted with the legacy frontend. The v2 frontend has exactly two
templates and one JS tree, and its rule is stricter than the legacy one:
every node goes through core/dom.mjs's el()/svg(), so there is no innerHTML
and no string-built markup anywhere for a handler to hide in. That is now
asserted directly, which also carries this task's own "no innerHTML"
constraint.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "src" / "templates"
V2_JS = REPO_ROOT / "src" / "static" / "js" / "v2"

EVENTS = (
    "click", "change", "input", "keydown", "keyup", "submit",
    "focus", "blur", "mouseover", "mouseout",
)
# HTML attribute form: on followed by a known event name, then `=`. The
# leading negative-lookbehind avoids matching identifiers like "function
# onClick" or text inside comments.
_INLINE_HANDLER_RE = re.compile(
    r"(?<![a-zA-Z_])on(?:" + "|".join(EVENTS) + r")\s*=", re.IGNORECASE
)


def _templates():
    paths = sorted(TEMPLATES.glob("*.html"))
    assert paths, f"no templates found under {TEMPLATES}"
    return [(p, p.read_text(encoding="utf-8")) for p in paths]


def _v2_sources():
    paths = sorted(V2_JS.rglob("*.mjs")) + sorted(V2_JS.rglob("*.js"))
    assert len(paths) >= 25, f"only {len(paths)} v2 sources found — wrong path?"
    return [(p, p.read_text(encoding="utf-8")) for p in paths]


def test_templates_have_no_inline_event_handlers():
    for path, text in _templates():
        hits = _INLINE_HANDLER_RE.findall(text)
        assert not hits, (
            f"Found {len(hits)} inline event-handler attribute(s) in "
            f"{path.name}: {hits[:5]}"
        )


def test_templates_have_no_inline_script_bodies():
    """<script> must be either `src=` or a non-executable data block.

    login.html embeds its i18n seed as `type="application/json"`, which the
    browser never executes and CSP therefore never blocks. Anything else with
    a body is executable inline script and would be blocked at runtime — i.e.
    it would ship broken.
    """
    for path, text in _templates():
        for m in re.finditer(r"<script([^>]*)>(.*?)</script>", text, flags=re.DOTALL):
            attrs, body = m.group(1), m.group(2).strip()
            if not body:
                continue
            assert 'type="application/json"' in attrs, (
                f"{path.name}: executable inline <script> body under a "
                f"script-src 'self' CSP:\n{body[:200]}"
            )


def test_v2_javascript_never_uses_innerhtml_or_string_built_markup():
    """No innerHTML/outerHTML/insertAdjacentHTML/document.write anywhere.

    This is the property that makes the inline-handler checks above
    sufficient: if no module can inject markup, no module can inject a
    handler attribute either — which is exactly how the legacy
    rule-scheduler.js check (`onclick=` concatenated into an HTML string)
    used to fail.
    """
    offenders = []
    for path, text in _v2_sources():
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        stripped = re.sub(r"^\s*//.*$", "", stripped, flags=re.MULTILINE)
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            if bad in stripped:
                offenders.append(f"{path.relative_to(V2_JS)}: {bad}")
    assert not offenders, (
        "v2 JavaScript must build DOM through core/dom.mjs's el()/svg():\n  "
        + "\n  ".join(offenders)
    )


# A handler attribute written into a markup string: lowercase, no space
# before `=` (attribute syntax, unlike JS's `api.onChange = fn`), on a line
# that is building markup (it contains an opening tag inside a string).
_STRING_MARKUP_RE = re.compile(r"""["'`]\s*<[a-zA-Z]""")
_ATTR_HANDLER_RE = re.compile(r"\son(?:" + "|".join(EVENTS) + r")=")


def test_v2_javascript_never_concatenates_an_event_attribute():
    """The specific legacy defect, kept as its own check: a handler attribute
    written into a string (`'<button onclick="' + ...`).

    Matched narrowly on purpose. A blanket ``on<event>=`` search over JS
    also hits ordinary property assignment — `api.onChange = fn` in
    components/filter-bar.mjs — which is not markup and not a CSP concern;
    flagging it would make this test noise that gets suppressed rather than
    a gate. So: lowercase attribute syntax, on a markup-building line.
    """
    offenders = []
    for path, text in _v2_sources():
        for lineno, line in enumerate(text.splitlines(), 1):
            if _STRING_MARKUP_RE.search(line) and _ATTR_HANDLER_RE.search(line):
                offenders.append(f"{path.relative_to(V2_JS)}:{lineno}: {line.strip()[:120]}")
    assert not offenders, offenders
