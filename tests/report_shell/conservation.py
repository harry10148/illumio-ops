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

WHAT A GREEN RESULT DOES AND DOES NOT PROVE — READ BEFORE RELYING ON IT
========================================================================
An empty result from ``conservation_diff(old_html, new_html)`` proves exactly
one thing:

    every text node of at least MIN_LEAF_CHARS (4) characters in the old
    document is findable SOMEWHERE in the new document's flattened text.

It is a set-level existence check (``old_leaves ⊆ new_flat``). Everything below
is outside that guarantee — green does not mean these did not happen:

* **Data correctness.** A value changed into another value is caught only if
  the old value was >= 4 characters AND unique in the document. Nothing else
  covers this; each type's own exporter tests do.
* **Pairing — the biggest hole.** Subset membership is invariant under every
  permutation, so swapped KPI values, exchanged table-row figures, or a value
  moved under the wrong label all pass silently. Nothing covers this. See
  ``test_transposed_values_are_a_known_blind_spot``.
* **Position and order.** Two sections whose entire contents are exchanged are
  not reported. If a migration moves content between chapters, assert that
  separately.
* **Structural integrity.** A whole column, row, or table can go missing and
  stay unreported if its text survives elsewhere in the document. The
  baselines' ``table_count`` catches a whole table vanishing; a lost column or
  row is covered only to the extent that the fixture's values are unique —
  which is why ``fixtures.py`` is written the way it is.
* **Chart content.** ``svg`` subtrees are removed wholesale, so chart titles,
  legends, axis labels and data labels are 100% out of scope. The baselines'
  ``chart_count`` counts figures, not what is inside them.
* **Short strings.** Values under 4 characters (``TCP``, ``443``, ``5``, a
  grade letter) never enter the comparison at all. This is a skip, not a pass.
* **Duplicated text.** Losing one of two identical occurrences is invisible —
  a report title lives in ``<title>``, on the cover and in the TOC at once.
  See ``test_duplicated_text_is_a_known_blind_spot``.
* **Exact matching.** ``flat`` has ALL whitespace stripped and matching is by
  substring, so ``alpha`` is satisfied by ``alphabetic``, and adjacent cells
  concatenate into strings that can satisfy a value that really did vanish.
  Short leaves are the dangerous ones.

The one thing it does prove is still worth having: it is the only check that
catches a whole block of narrative text disappearing during re-chaptering. On
2026-08-03 ``.report-hero-top`` was decomposed wholesale, both reports lost
their real titles, and not one test went red. Treat it as "the rearrangement
did not drop a block", never as "the migration is correct".

**Its strength is set by the fixtures, not by this module.** If sample data
repeats across tables or uses values under 4 characters, the holes above widen
at once: measured on the first version of ``fixtures.py``, deleting a column's
cell values went unreported for 116 of 137 columns. Before trusting a green
run on a new report type, look at what its fixture actually contains.

After a green run you still owe: the per-type ``table_count``/``chart_count``
comparison, that type's existing exporter tests, and T7's page-by-page check on
real output. Drop any of the three and a whole row above has nobody covering it.
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

    It is not relaxed to "any part matches" — both halves must be found — but do
    not read that as protecting the PAIRING. Each half is looked up
    independently, anywhere in the document; nothing checks that they are still
    attached to each other, or to each other's neighbours. The exemption only
    fails when a half is replaced by a string that appears NOWHERE in the new
    document (``（無資料）``). Swap two labels' values and both halves are still
    present, so this returns True and ``conservation_diff`` stays silent — see
    the pairing entry in the module docstring.
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
