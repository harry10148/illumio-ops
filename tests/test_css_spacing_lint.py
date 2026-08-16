"""Spacing lint: count magic-number margin/padding declarations in the v2
stylesheets. Threshold MUST NOT exceed 20.

Phase 2A Task 11 retargeted this file. It used to ratchet the LEGACY
src/static/css/app.css down from a baseline of 57 (threshold last raised to
80) plus an informational cap of 222 inline spacing values in
src/templates/index.html. Both files are gone. The v2 stylesheets were built
on --space-1..8 from the start, so the equivalent count is 14 at the time of
writing (9 in app.css + 5 in components.css) — the threshold below is set
just above that, not at the legacy number, so it is a real ratchet again
rather than a cap nothing could ever reach.

The inline-style half of the old file has no counterpart and is not
replaced: v2 builds every node through core/dom.mjs, which has no style=""
path at all, and tests/test_csp_compliance.py holds the "no inline anything"
line for the two templates that remain.
"""
from __future__ import annotations

import re
from pathlib import Path


CSS_DIR = Path(__file__).parent.parent / "src" / "static" / "css" / "v2"

# 14 = the count when the legacy stylesheet was deleted (Task 11). These are
# component-internal values that do not map onto a single --space-* step
# (1px hairlines, 12vh palette offset, and similar). Lower it if a future
# cleanup migrates more; raise it only with a reason.
MAGIC_THRESHOLD = 20

_MAGIC_RE = re.compile(r"^\s*(margin|padding)[a-zA-Z-]*\s*:\s*[0-9]", re.MULTILINE)


def _counts() -> dict[str, int]:
    return {
        p.name: len(_MAGIC_RE.findall(p.read_text(encoding="utf-8")))
        for p in sorted(CSS_DIR.glob("*.css"))
    }


def test_magic_number_margin_padding_count_below_threshold():
    counts = _counts()
    total = sum(counts.values())
    assert total <= MAGIC_THRESHOLD, (
        f"Found {total} magic-number margin/padding declarations in "
        f"css/v2 ({counts}); threshold is {MAGIC_THRESHOLD}. Migrate to "
        f"var(--space-*) or justify the addition by raising the threshold."
    )


def test_tokens_file_declares_no_spacing_of_its_own():
    """tokens.css defines --space-*; it must not also USE margin/padding.

    A rule in the token file would be invisible to anyone reading the
    component stylesheets, which is where layout is supposed to live.
    """
    counts = _counts()
    assert counts.get("tokens.css") == 0, counts


def test_the_space_scale_exists_and_is_what_consumers_use():
    """Sanity, so the threshold above is not satisfied by an empty ruleset:
    the scale really exists and the consumer stylesheets really call it."""
    tokens = (CSS_DIR / "tokens.css").read_text(encoding="utf-8")
    for step in range(1, 9):
        assert f"--space-{step}:" in tokens, step
    consumers = "".join(
        p.read_text(encoding="utf-8")
        for p in sorted(CSS_DIR.glob("*.css")) if p.name != "tokens.css"
    )
    assert consumers.count("var(--space-") >= 100, consumers.count("var(--space-")
