"""Unit proof that the conservation harness itself works.

Task 3/4/5 each migrate a batch of exporters onto the v2 shell and use
``conservation_diff`` to prove the rearrangement dropped no text. A guard that
reports "nothing lost" because it is not looking at anything is worse than no
guard, so this file proves the mechanism in both directions:

  * it CATCHES a heading that really disappeared (both on a synthetic snippet
    and on a real report built by ``BUILDERS``);
  * it stays SILENT on the structural rearrangements that are legitimate
    (icon/label/value node splitting, sub-4-character fragments, script/style/
    svg subtrees, explicitly allowlisted screen chrome);
  * every ``BUILDERS`` entry actually renders — a builder that raises must fail
    loudly here, not be silently skipped by the later migration tests.

The first four cases mirror ``tests/design_v2/test_reskin_report.py`` (the
prototype's own conservation tests) so the transcribed implementation stays
behaviourally pinned to the prototype it came from.
"""
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from tests.report_shell.conservation import (
    MIN_LEAF_CHARS,
    conservation_diff,
    conservation_text,
    label_value_preserved,
    norm,
)
from tests.report_shell.fixtures import BUILDERS

OLD = ("<main><h2>Lateral movement</h2>"
       "<p>📅 資料範圍: 2026-01-01 – 2026-02-01</p><p>abc</p></main>")

REPORT_TYPES = {
    "traffic", "security_risk", "network_inventory", "audit", "ven_status",
    "policy_usage", "policy_diff", "app_summary", "rule_hit_count", "readiness",
}

# The five types whose minimal input renders at least one static chart.
TYPES_WITH_CHARTS = {"traffic", "network_inventory", "audit", "ven_status",
                     "policy_usage"}


def test_mechanism_catches_a_dropped_heading():
    assert conservation_diff(OLD, "<div><p>資料範圍: 2026-01-01 – 2026-02-01</p></div>") \
        == [norm("Lateral movement")]


def test_icon_label_value_split_is_tolerated_but_value_swap_is_not():
    ok = "<dl><dt>資料範圍</dt><dd>2026-01-01 – 2026-02-01</dd><p>lateral movement</p></dl>"
    assert conservation_diff(OLD, ok) == []
    swapped = "<dl><dt>資料範圍</dt><dd>（無資料）</dd><p>lateral movement</p></dl>"
    assert conservation_diff(OLD, swapped) != []


def test_short_strings_and_script_style_svg_are_out_of_scope():
    leaves, _ = conservation_text(
        "<p>abc</p><script>var x='longlonglong'</script>"
        "<svg><text>in-svg-text</text></svg>")
    assert leaves == set()   # abc <4 字元；script/svg 整棵剔除


def test_allowlist_exempts_exact_normalized_entry():
    old = "<button class='print-btn'>列印 / PDF</button><p>real content here</p>"
    assert conservation_diff(old, "<p>real content here</p>",
                             allowlist=frozenset({norm("列印 / PDF")})) == []


def test_doctype_node_is_not_mistaken_for_lost_content():
    """``find_all(string=True)`` also matches the Doctype declaration, whose node
    text is literally ``html`` — but ``get_text()`` never emits it. Without the
    non-content filter every full document would report ``html`` as lost."""
    doc = "<!doctype html><html><body><p>real content here</p></body></html>"
    leaves, _ = conservation_text(doc)
    assert "html" not in leaves
    assert conservation_diff(doc, doc) == []


def test_label_value_preserved_is_importable_and_requires_both_halves():
    flat = norm("資料範圍 2026-01-01 – 2026-02-01")
    assert label_value_preserved(norm("📅 資料範圍: 2026-01-01 – 2026-02-01"), flat)
    assert not label_value_preserved(norm("📅 資料範圍: 2026-03-03 – 2026-04-04"), flat)


# ------------------------------------------------------------- BUILDERS 契約 --
def test_builders_cover_exactly_the_ten_html_report_types():
    assert set(BUILDERS) == REPORT_TYPES


@pytest.mark.parametrize("report_type", sorted(REPORT_TYPES))
def test_every_builder_renders_a_document(report_type):
    """A builder that raises must fail loudly. No try/except, no skip."""
    html = BUILDERS[report_type]()
    assert isinstance(html, str)
    assert "<html" in html


def test_builders_render_enough_tables_and_charts_for_the_count_baselines():
    """The baseline files record ``table_count``/``chart_count``, so those
    counts must be non-zero — a fixture set that renders nothing but
    empty-state panels would let a migration drop every table and chart and
    still match its baseline. Per type: at least one real ``.report-table``
    (empty-state panels carry ``.report-table-panel--empty`` instead, so they do
    not count).

    The chart side pins the exact set rather than a total: with a total, one
    type's chart could disappear while another type's kept the sum positive.
    The five types that render none do so because their minimal input has no
    chart to draw, not because charts were dropped.
    """
    tables = {}
    charts = {}
    for report_type in sorted(REPORT_TYPES):
        soup = BeautifulSoup(BUILDERS[report_type](), "html.parser")
        tables[report_type] = len(soup.select(".report-table"))
        charts[report_type] = len(soup.select("figure.chart-static"))
    assert all(n > 0 for n in tables.values()), f"types with no real table: {tables}"
    assert {rt for rt, n in charts.items() if n > 0} == TYPES_WITH_CHARTS, \
        f"chart-bearing types changed: {charts}"


# Column-data deletions that conservation genuinely cannot see, each verified
# against the rendered document rather than assumed. These are NOT fixture
# defects — no choice of sample value fixes them:
#   * the value is an enum the exporter also prints outside the table
#     (``modified`` appears in policy_diff's own change counters);
#   * the value is a derived count or a grade letter and is therefore shorter
#     than MIN_LEAF_CHARS (``A``, ``1``);
#   * the exporter renders one frame in two places (readiness' Action/Affected
#     Apps rollup is built from the recommendations table below it).
_UNPROTECTED_COLUMNS = {
    ("policy_diff", "Change"),
    ("readiness", "Grade"),
    ("readiness", "Action"),
    ("readiness", "Affected Apps"),
    ("ven_status", "Count"),
}


def test_deleting_a_columns_data_is_caught_for_every_table_column():
    """The guard's real strength test, and the reason fixtures.py looks the way
    it does.

    Measured on the first version of these fixtures, this mutation went
    unreported for 116 of 137 columns — the harness was green because the
    sample data hid everything from it (values under four characters, and one
    DataFrame reused across a dozen tables). Sample values are now distinct and
    long enough; anything that regresses that will fail here rather than
    silently weakening every migration check in T3-T5.
    """
    missed = []
    for report_type in sorted(REPORT_TYPES):
        html = BUILDERS[report_type]()
        for ti, ncols in enumerate(_table_shapes(html)):
            for ci in range(ncols):
                name, mutated = _blank_column(html, ti, ci)
                if mutated is None:
                    continue
                if not conservation_diff(html, mutated):
                    missed.append((report_type, name))

    unexpected = [m for m in missed if m not in _UNPROTECTED_COLUMNS]
    assert not unexpected, (
        "conservation cannot see these column deletions; make the sample "
        f"values distinct and >= {MIN_LEAF_CHARS} characters: {unexpected}")

    stale = _UNPROTECTED_COLUMNS - set(missed)
    assert not stale, (
        f"these are now protected — drop them from _UNPROTECTED_COLUMNS: {stale}")


def _table_shapes(html: str) -> list[int]:
    soup = BeautifulSoup(html, "html.parser")
    return [len(t.select("thead th")) for t in _real_tables(soup)]


def _real_tables(soup):
    return [t for t in soup.select("table.report-table")
            if t.select("thead th") and t.select("tbody tr")]


def _blank_column(html: str, ti: int, ci: int):
    """Empty column ``ci`` of table ``ti``, keeping its header. Returns
    ``(column name, mutated html)``, or ``(name, None)`` if the column held no
    text to begin with."""
    soup = BeautifulSoup(html, "html.parser")
    table = _real_tables(soup)[ti]
    name = table.select("thead th")[ci].get_text(" ", strip=True)
    had_text = False
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) > ci:
            had_text = had_text or bool(cells[ci].get_text(" ", strip=True))
            cells[ci].clear()
    return name, (str(soup) if had_text else None)


@pytest.mark.parametrize("report_type", sorted(REPORT_TYPES))
def test_builders_are_deterministic_in_everything_the_baselines_record(report_type):
    """T3 captures a baseline from one call and compares a later call to it, so
    anything a baseline records must not vary between calls.

    Deliberately NOT a whole-document comparison: matplotlib mints a random
    ``clip-path`` id per SVG render, so ``ven_status`` differs by ~165 bytes
    between two calls. That is invisible to the baselines because ``svg``
    subtrees are stripped before text collection. Asserting byte equality here
    would fail for a reason that cannot affect a single migration check.
    """
    first, second = BUILDERS[report_type](), BUILDERS[report_type]()
    assert conservation_text(first)[0] == conservation_text(second)[0]
    for markup in (".report-table", "figure.chart-static"):
        assert len(BeautifulSoup(first, "html.parser").select(markup)) == \
               len(BeautifulSoup(second, "html.parser").select(markup))


@pytest.mark.parametrize("report_type", sorted(REPORT_TYPES))
def test_harness_is_identity_clean_on_a_real_report(report_type):
    html = BUILDERS[report_type]()
    assert conservation_diff(html, html) == []


@pytest.mark.parametrize("report_type", sorted(REPORT_TYPES))
def test_harness_catches_narrative_text_deleted_from_a_real_report(report_type):
    """Mutation proof, per report type.

    Deletes the longest text node that occurs exactly once in the document and
    requires the harness to name it. "Longest unique" is deterministic and lands
    on real narrative prose (a section's explanatory paragraph) rather than on
    shell chrome, which is what the migration tasks actually risk losing.
    """
    html = BUILDERS[report_type]()
    soup = BeautifulSoup(html, "html.parser")
    victim = _longest_unique_text_node(soup)
    assert victim is not None, f"{report_type}: no unique >=8-char text node to mutate"

    lost = norm(str(victim))
    victim.extract()
    diff = conservation_diff(html, str(soup))

    assert diff, f"{report_type}: harness reported nothing after deleting {lost[:60]!r}"
    assert lost[:90] in diff, \
        f"{report_type}: deleted {lost[:60]!r} but harness reported {diff}"


def test_transposed_values_are_a_known_blind_spot():
    """Documented limitation, pinned so it cannot change unnoticed — and the
    more dangerous of the two.

    ``conservation_diff`` asks whether ``old_leaves`` is a subset of the new
    document's flattened text. Subset membership is invariant under every
    permutation, so moving a value under the wrong label — two KPI values
    swapped, two table rows' figures exchanged, a timestamp attached to the
    wrong event — passes silently. The duplicate-text blind spot below is
    "something vanished and nobody noticed"; this one is "the report now states
    something false and nobody noticed", and a report's worth rests on its
    values being paired with the right labels.

    Nothing in this harness can close that. It needs per-type assertions in the
    exporters' own tests and T7's page-by-page check on real output.
    """
    old = ("<dl><dt>Hit rate percentage</dt><dd>41.73</dd>"
           "<dt>Unused rate percentage</dt><dd>58.27</dd></dl>")
    swapped = ("<dl><dt>Hit rate percentage</dt><dd>58.27</dd>"
               "<dt>Unused rate percentage</dt><dd>41.73</dd></dl>")
    assert conservation_diff(old, swapped) == []

    # Same at table-row level, on a real report: exchange two body rows' cells
    # and the check still reports nothing.
    html = BUILDERS["policy_usage"]()
    soup = BeautifulSoup(html, "html.parser")
    rows = _real_tables(soup)[0].select("tbody tr")
    a = rows[0].find_all("td", recursive=False)
    b = rows[1].find_all("td", recursive=False)
    for ca, cb in zip(a, b):
        ca.string, cb.string = cb.get_text(" ", strip=True), ca.get_text(" ", strip=True)
    assert conservation_diff(html, str(soup)) == []


def test_duplicated_text_is_a_known_blind_spot():
    """Documented limitation, pinned so it cannot change unnoticed.

    The check asks "is this string findable anywhere in the new document", so
    deleting ONE of two identical occurrences is invisible to it — a report
    title lives in ``<title>``, on the cover and in the TOC at once, and losing
    the TOC copy alone would not be reported. That is the prototype's semantics
    and it is the right default (the reader still sees the text somewhere), but
    it means table/chart COUNT assertions in the baseline files, not this
    function, are what defend against a whole duplicated block going missing.
    """
    old = "<p>duplicated narrative sentence</p><p>duplicated narrative sentence</p>"
    assert conservation_diff(old, "<p>duplicated narrative sentence</p>") == []


def _longest_unique_text_node(soup):
    _, flat = conservation_text(str(soup))
    best = None
    best_len = 0
    for node in soup.find_all(string=True):
        text = norm(str(node))
        if len(text) > best_len and len(text) >= 8 and flat.count(text) == 1:
            best, best_len = node, len(text)
    return best
