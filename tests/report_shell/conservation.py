"""old→new text-conservation check for the Phase 2B report-shell migration.

Transcribed from the design prototype ``design/v2/tools/reskin_report.py``
(``_norm`` / ``_conservation_text`` / ``_conservation_preserved`` /
``conservation_diff``). Behaviour is deliberately identical; the only interface
changes are that the allowlist is a per-call parameter instead of a module
constant, and that ``_conservation_preserved`` is exported under the public name
``label_value_preserved`` so migration tests can reuse the single-string
judgement directly.

Why this exists at all: the prototype's ``verify_no_truncation`` only ever
compared the *reskinned* HTML against its own PDF, so it could not see content
that was already gone before printing. On 2026-08-03 that is exactly what
happened — ``.report-hero-top`` was decomposed wholesale and both reports lost
their real titles, with no test failing. ``conservation_diff`` compares
old→new and is the only thing that catches that class of loss.

Direction matters: this checks that every piece of text in the OLD document
still appears in the NEW one. Text the new shell ADDS is unconstrained by
design — a layout affordance such as the wide-table hint paragraph is new
chrome, never a substitute for data, so it needs no exemption here. The
``allowlist`` parameter is for the reverse case: old-side markup that is screen
chrome rather than report content and legitimately has no successor (the
prototype's only entry was the ``.print-btn`` "列印 / PDF" control, which lives
outside ``main.report-main`` and is re-provided by the new shell itself).

Known blind spot, inherited from the prototype and deliberately kept: the test
is "is this string findable anywhere in the new document", so losing ONE of two
identical occurrences is invisible. A report title appears in ``<title>``, on
the cover and in the TOC simultaneously; dropping the TOC copy alone would not
be reported here. That is the right default — the reader still sees the text —
but it is why the baseline files also record ``table_count``/``chart_count``:
counts are what catch a whole duplicated block disappearing.
``tests/test_report_shell_conservation_unit.py`` pins this behaviour explicitly
so it cannot drift silently.
"""
from __future__ import annotations

import re
import unicodedata

from bs4 import (
    BeautifulSoup,
    CData,
    Comment,
    Declaration,
    Doctype,
    ProcessingInstruction,
)

__all__ = [
    "norm",
    "conservation_text",
    "conservation_diff",
    "label_value_preserved",
    "MIN_LEAF_CHARS",
]

# Strings shorter than this are skipped, not "considered verified": at three
# characters or fewer (numeric fragments, units, icon glyphs) a literal
# substring match finds look-alikes all over a report and drowns the real
# truncation signal in coincidental hits.
MIN_LEAF_CHARS = 4

_NON_CONTENT = (Comment, Doctype, ProcessingInstruction, CData, Declaration)


def norm(text: str) -> str:
    """NFKC → strip every whitespace character → casefold.

    Whitespace is removed rather than collapsed so that re-wrapping, re-indenting
    or splitting a run of text across elements cannot register as a loss.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def conservation_text(html: str) -> tuple[set[str], str]:
    """Return ``(leaf text set, flattened comparison string)`` for ``html``.

    ``script``/``style``/``svg`` subtrees are dropped: they carry no narrative
    text. Chart SVGs stay out of scope here on purpose — their content is
    covered by the table/chart count assertions in the baseline files instead.

    ``find_all(string=True)`` also matches ``NavigableString`` subclasses that
    are not content — a ``<!doctype html>`` node's text is literally ``html``.
    ``get_text()`` does not emit those, so leaving them in the leaf set while
    they are absent from the flattened string manufactures a false positive on
    every complete document. Hence the ``_NON_CONTENT`` filter.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "svg"]):
        tag.decompose()
    leaves = {
        norm(str(s)) for s in soup.find_all(string=True)
        if not isinstance(s, _NON_CONTENT) and len(norm(str(s))) >= MIN_LEAF_CHARS
    }
    flat = norm(soup.get_text(" "))
    return leaves, flat


def label_value_preserved(text: str, flat: str) -> bool:
    """Is ``text`` (already ``norm``-ed) findable in ``flat`` (already ``norm``-ed)?

    One structural rearrangement is tolerated: the old markup often glued an
    icon, a label, a colon and a value into a single text node (the audit
    cover's ``📅 資料範圍: 2026-07-16 – 2026-07-23``), while the new shell splits
    them into separate ``dt``/``dd`` nodes. Not one character is lost — the
    string simply is not contiguous any more.

    This is NOT relaxed to "any part matches": the label and the value must BOTH
    be found. If the value were replaced (``（無資料）``) the label alone would
    still match, and that must stay a failure.
    """
    if text in flat:
        return True
    core = re.sub(r"^[^\w一-鿿]+", "", text)
    if ":" in core:
        label, _, value = core.partition(":")
        if label and value and label in flat and value in flat:
            return True
    return False


def conservation_diff(old_html: str, new_html: str,
                      allowlist: frozenset[str] = frozenset()) -> list[str]:
    """Text nodes present in ``old_html`` that cannot be found in ``new_html``.

    An empty list means nothing was lost. Entries are truncated to 90 characters
    for readability of the failure message — the check itself uses the full
    string.

    ``allowlist`` entries must already be ``norm``-ed by the caller (write
    ``frozenset({norm("列印 / PDF")})``, not the raw literal); they are compared
    against the normalised leaf text.
    """
    old_leaves, _ = conservation_text(old_html)
    _, new_flat = conservation_text(new_html)
    return sorted(
        text[:90] for text in old_leaves
        if text not in allowlist and not label_value_preserved(text, new_flat)
    )
