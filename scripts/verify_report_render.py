#!/usr/bin/env python3
"""Mechanical render verification for one already-generated report HTML file.

Usage::

    scripts/verify_report_render.py <report.html> [--out-dir tmp/phase2b-shots]

Exit codes
----------
``0``  every check passed.
``1``  at least one check found a real problem in the report.
``2``  the tool itself broke (missing binary, browser crash, unreadable input).

The 1-vs-2 split is deliberate: a broken measurement must never be reported as
a clean report, and the caller must be able to tell "the report is bad" from
"the tool is bad" without reading the log.

The five checks
---------------
1. **screenshots** — full-page PNGs at 1280 and 800 CSS px, quantised to 256
   colours (report pages use ~100 colours; quantising costs nothing visible and
   saves 2-3x the bytes).  Asserts the files exist and decode to a non-zero
   raster.
2. **pdf** — ``page.pdf()`` under print emulation; asserts the file exists and
   that ``pdftotext`` can parse at least one page out of it.
3. **no-truncation** (forward, DOM ⊆ PDF) — every print-visible DOM text run
   of >= 4 characters must be findable in the ``pdftotext -raw`` text layer.
   Catches content that is silently dropped or clipped away by print CSS.
4. **no-stray-glyph** (reverse, PDF ⊆ static DOM) — every whitespace-separated
   token in the PDF text layer must be findable in the *static* HTML text.
   Catches the opposite failure: glyphs that appear in print but correspond to
   nothing in the document.
5. **print-clipping** — under print emulation, no table may be wider than the
   panel that holds it, measured at 695 CSS px (A4 portrait content width) and
   1035 CSS px (A4 landscape content width).

Why checks 3 and 4 use *different* corpora — this is load-bearing
----------------------------------------------------------------
Check 3's needles come from the **live browser DOM under print emulation**, so
JS-injected content counts and print-hidden content does not.  Check 4's
haystack comes from the **static HTML parsed by BeautifulSoup**, ignoring
visibility and ignoring JS.

Making them symmetric would defeat check 4.  The motivating bug (task 4 of this
phase) was 20 stray ``↕`` sort indicators printed at one x-coordinate; those
indicators are created by ``TABLE_JS`` at runtime.  Had check 4's haystack been
the live DOM, the arrows would have been in the haystack and would have
explained themselves.  Against the static HTML they are unexplained, and the
check fires.  For the same reason ``<script>`` and ``<style>`` subtrees are
stripped from the haystack: the injector's own source text must not vouch for
the thing it injects.

Two measurement traps this phase has already paid for
-----------------------------------------------------
1. **Never measure a layout the browser has not re-flowed.**  Changing viewport
   or media and reading straight away gives stale numbers — the same document
   measured 2764px one way and 2479px the other.  Every viewport change, media
   change and load here is followed by a double-``requestAnimationFrame``
   settle before anything is read.

   The obvious cure — emulate print *before* ``goto``, so nothing ever changes
   after load — is wrong here, and measurably so.  ``TABLE_JS`` pins
   screen-measured column widths into inline styles on load, and inline styles
   do not respond to media; the screen-then-print order is the collision the
   shell's ``!important`` width release exists to survive.  See ``_print_state``
   for the two measurements that decided it.
2. **``pdftotext -layout`` reflows columns**, so a needle missing from its
   output is not proof of truncation.  Everything here uses ``-raw``, then
   NFKC-normalises, strips *all* whitespace and casefolds both sides.  A
   first-pass script in this phase reported 17 strings "missing from the PDF
   text layer" that were all present, and another reported 78 truncations that
   were 0.

Counting basis (state it, never blur it)
----------------------------------------
Check 3 counts **DOM text runs** (consecutive text nodes of one element, see
``_PRINT_TEXT_JS``).  Check 4 counts **pdftotext words**.  These
are not the same unit and do not convert: the 20 stray arrows above were 20 DOM
elements and extracted as 3 words.  Every output line names its unit.

Known blind spots, stated rather than hidden
--------------------------------------------
* Chart SVGs are excluded from both directions.  matplotlib emits glyphs as
  vector paths (measured: 0 ``<text>`` elements in the ven_status fixture), so
  chart labels reach neither the DOM text nor the PDF text layer.  Chart
  legibility is a human-inspection item, not a mechanical one.
* Check 4 matches each token as a substring of the whitespace-stripped static
  corpus.  That corpus is one long string, so short tokens are found easily and
  the check is far more sensitive to *foreign* glyphs than to *displaced
  familiar* ones.  This is the "specific rather than fully general" option the
  task explicitly allows: it catches unexpected glyphs by content, not every
  possible displacement by position.  A ``pdftotext -bbox`` pile-up probe was
  considered and left out: the motivating defect is already caught by content,
  and a positional heuristic that has never seen a true positive would be one
  more guard nobody can calibrate.  A glyph that is displaced but still spelled
  correctly remains a human-inspection item.
* CSS ``letter-spacing`` makes ``pdftotext`` emit headings one character per
  token (``R U L E``).  Those single-character tokens are trivially found, so
  check 4 carries little signal on letter-spaced headings.
* The ``@bottom-right`` page counter ("3 / 8") is content-stream text with no
  DOM origin.  It is stripped per page before either direction runs; without
  that, it both fails check 4 outright and breaks check 3 for any text node
  that straddles a page boundary.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

# A4 portrait: 210mm - 26mm margins = 184mm ~= 695px at 96dpi.
# A4 landscape: 297mm - 23mm margins ~= 1035px.  Both mirror the shell's
# `@page` / `@page wide` margin declarations in report_shell.py.
PRINT_WIDTH_PORTRAIT = 695
PRINT_WIDTH_LANDSCAPE = 1035

SCREENSHOT_WIDTHS = (1280, 800)

# Minimum needle length for check 3.  Shorter strings (unit suffixes, single
# digits, symbols) collide across cells everywhere in a flattened text layer,
# so comparing them produces coincidental hits and layout-difference misses in
# roughly equal measure and carries almost no signal.  They are *excluded from
# the denominator*, not treated as verified; the output line names the real
# denominator.
MIN_NEEDLE_CHARS = 4

_PAGE_FOOTER_RE_TEMPLATE = r"^[ \t]*{page}[ \t]*/[ \t]*\d+[ \t]*$"


class ToolError(RuntimeError):
    """The measurement itself failed; never report this as a report defect."""


# --------------------------------------------------------------- normalising --
def norm(text: str) -> str:
    """NFKC, drop every whitespace character, casefold.

    Print CSS uppercases labels, re-wraps lines at different places from the
    screen, and `overflow-wrap: anywhere` splits words mid-token; none of that
    is a content difference.  Dropping whitespace also re-joins a word that
    `pdftotext` emitted across two lines.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


# ------------------------------------------------------------------ pdftotext --
def pdf_pages_raw(pdf_path: Path) -> list[str]:
    """Per-page text via ``pdftotext -raw`` (never ``-layout``; see docstring)."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-raw", str(pdf_path), "-"],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError as exc:  # poppler-utils absent
        raise ToolError("pdftotext not found; install poppler-utils") from exc
    except subprocess.CalledProcessError as exc:
        raise ToolError(f"pdftotext failed on {pdf_path}: {exc.stderr!r}") from exc
    pages = proc.stdout.split("\f")
    # pdftotext terminates the final page with \f, producing a trailing empty
    # chunk.  Drop it, but only if it really is empty.
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def strip_page_footers(pages: list[str]) -> tuple[str, int]:
    """Remove the ``@bottom-right`` "<n> / <total>" counter from each page.

    Anchored on the page's *own* number and removed at most once per page, so a
    genuine cell value such as ``8 / 10`` (`.mat-val` renders exactly that) on
    page 3 cannot be mistaken for page 3's footer.  Returns the joined text and
    how many footers were removed, so a caller can notice if the count stops
    matching the page count.
    """
    cleaned: list[str] = []
    removed = 0
    for index, page in enumerate(pages, 1):
        pattern = re.compile(_PAGE_FOOTER_RE_TEMPLATE.format(page=index), re.MULTILINE)
        page, hits = pattern.subn("", page, count=1)
        removed += hits
        cleaned.append(page)
    return "\n".join(cleaned), removed


# ---------------------------------------------------------------- static HTML --
def static_corpus(html: str) -> str:
    """Flattened text of the static document, visibility ignored, JS ignored.

    Haystack for check 4 only.  Over-inclusion here is safe (it can only make
    check 4 less sensitive), but `script`/`style` must go: TABLE_JS's own source
    would otherwise vouch for the elements TABLE_JS injects.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "svg", "template"]):
        tag.decompose()
    return norm(soup.get_text(" "))


# ------------------------------------------------------------------ browser JS --
# Every text node whose parent is visible under the current (print) emulation.
# `checkVisibility` is what makes `.sort-indicator`, `.table-hint` and the
# collapsed `<details>` summary drop out without naming any of them here.
#
# Text nodes are joined into *runs*: consecutive text children of one element,
# separated only by elements that contribute no text of their own.  The
# exporters pepper long identifiers with `<wbr>` break opportunities
# (`sec_<wbr>policy.<wbr>create.<wbr>evtzulu`), which splits one cell value into
# four text nodes; comparing those separately never notices content lost
# *between* them.  A child element that does carry text flushes the run, so
# `Foo <b>bar</b> baz` stays two needles and never fabricates `Foo baz`.
_PRINT_TEXT_JS = """
(excusedSelector) => {
  const out = [];
  const describe = (el) => {
    let where = el.tagName.toLowerCase();
    const cls = (el.getAttribute('class') || '').trim();
    if (cls) where += '.' + cls.split(/\\s+/).join('.');
    return where;
  };
  const walk = (el) => {
    if (el.closest('svg, script, style, template')) return;
    const visible = el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
    const excused = el.closest(excusedSelector) !== null;
    let run = '';
    const flush = () => {
      if (run.trim()) out.push([run, describe(el), visible, excused]);
      run = '';
    };
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) { run += child.data; continue; }
      if (child.nodeType !== Node.ELEMENT_NODE) continue;
      if ((child.textContent || '').trim() === '') continue;  // <wbr>, <br>, empty spans
      flush();
      walk(child);
    }
    flush();
  };
  walk(document.body);
  return out;
}
"""

# Text that legitimately does not reach paper.  Derived from the `display: none`
# and `content-visibility` declarations inside the shell's own `@media print`
# block (report_shell.py), not invented here — re-derive it if that block
# changes.  Everything else that turns out invisible under print emulation is a
# *finding*, not an exemption: collecting only print-visible text would make the
# check structurally blind to "print CSS hides content that must print", which
# is exactly the 2026-08-03 defect (`.cell-long::details-content` losing
# `content-visibility: visible` silently dropped 15 full change_detail bodies
# from the text layer).
PRINT_EXCUSED_SELECTOR = ", ".join((
    ".sort-indicator",      # JS-injected sort affordance; paper cannot sort
    ".table-hint",          # "scroll for more" screen hint
    ".cell-long > summary",  # the elided head; the full <pre> prints instead
    ".print-btn",           # the print control itself
    ".screen-only",         # declared screen-only by the shell
))

# Tables wider than the panel that holds them.  The prototype skipped panels
# whose computed `overflow-x` was `visible`; the v2 shell sets
# `.report-table-panel { overflow: visible }` for print, so that skip would
# skip every panel and the check would measure nothing.  It is deliberately
# gone: with `overflow: visible` the excess is not clipped by the panel, it
# runs off the edge of the paper, which is the same defect and is what we are
# looking for.  The landscape/portrait pairing stays — a landscape panel is
# meaningless at the portrait width and vice versa.
_CLIP_JS = """(portrait) => {
  const bad = [];
  for (const panel of document.querySelectorAll('.report-table-panel')) {
    const isLandscape = panel.classList.contains('report-table-panel--landscape');
    if (isLandscape === portrait) continue;
    const table = panel.querySelector('table');
    if (!table) continue;
    const width = Math.max(table.scrollWidth,
                           Math.ceil(table.getBoundingClientRect().width));
    if (width > panel.clientWidth + 1) {
      const section = panel.closest('section');
      bad.push([section ? section.id : '(no section)', width, panel.clientWidth]);
    }
  }
  return bad;
}"""


# TABLE_JS measures column widths inside a `requestAnimationFrame` callback and
# writes the result back as inline styles.  `load` fires before that callback
# runs, so measuring straight after `goto` can read the pre-autofit layout —
# which is exactly the layout the print-clipping check exists to catch.  Two
# nested frames guarantee the first frame's callbacks have completed.
_SETTLE_JS = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"


def _load(page, uri: str) -> None:
    page.goto(uri, wait_until="load")
    page.evaluate(_SETTLE_JS)


def _shrink_png(path: Path) -> None:
    """Full-page shots run to megabytes; report pages hold ~100 colours."""
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
    rgb.quantize(colors=256, method=Image.MEDIANCUT).save(path, optimize=True)


# ------------------------------------------------------------------- pipeline --
class Render:
    """Everything one browser session produces for one document."""

    def __init__(self) -> None:
        self.shots: list[Path] = []
        self.pdf: Path | None = None
        self.print_text: list[tuple[str, str]] = []
        self.clipped: list[tuple[str, str, int, int]] = []


SCREEN_WIDTH = 1280


def _print_state(browser, uri, width: int):
    """A page in the state a real "print this report" produces.

    Order matters and is measured, not assumed.  TABLE_JS's `autoFitColumns`
    measures each table on load and writes the result back as `table.style.width`
    / `col` / `th` inline styles, which do not respond to media.  A real reader
    loads the report on screen — so those widths are *screen*-derived — and only
    then prints, which is the collision the shell's `!important` width-release
    block exists to survive.

    Emulating print before `goto` (the prototype's order) makes TABLE_JS measure
    the print layout instead, and the collision never happens.  Measured on
    `rule_hit_count` with that release block deleted: print-first wrote a 1014px
    inline width at the A4 landscape width and the 11-column table reported
    1014px against a 1014px panel — clean, wrongly.  Screen-first wrote 1166px
    and the same table reported 1166px against 1014px — the defect, visible.

    Both changes are followed by a settle so nothing here reads a stale layout:
    that trap is real (the same document has measured 2764px and 2479px), it is
    just not solved by reloading under print.
    """
    page = browser.new_page(viewport={"width": SCREEN_WIDTH, "height": 1000})
    _load(page, uri)            # screen media: TABLE_JS pins screen-derived widths
    page.emulate_media(media="print")
    page.set_viewport_size({"width": width, "height": 1000})
    page.evaluate(_SETTLE_JS)   # flush the relayout before anything is measured
    return page


def render(html_path: Path, out_dir: Path) -> Render:
    """Screenshots, PDF, print text and clipping, in one browser session."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ToolError("playwright is not installed in this interpreter") from exc

    uri = html_path.resolve().as_uri()
    stem = html_path.stem
    result = Render()
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            # 1. screen media, both widths.
            for width in SCREENSHOT_WIDTHS:
                page = browser.new_page(viewport={"width": width, "height": 1000})
                _load(page, uri)
                shot = out_dir / f"{stem}-{width}.png"
                page.screenshot(path=str(shot), full_page=True)
                _shrink_png(shot)
                result.shots.append(shot)
                page.close()

            # 2. print media, PDF.  `prefer_css_page_size` is required, not
            # optional: the shell declares `@page wide { size: A4 landscape }`
            # for >=10-column tables, and forcing `format="A4"` alone would lay
            # those pages out portrait and clip them.  `format` stays as the
            # fallback for a document that declares no page size.
            page = _print_state(browser, uri, PRINT_WIDTH_PORTRAIT)
            pdf_path = out_dir / f"{stem}.pdf"
            page.pdf(path=str(pdf_path), format="A4",
                     print_background=True, prefer_css_page_size=True)
            result.pdf = pdf_path

            # 3. text and its print visibility, from that same print state.
            result.print_text = [tuple(row) for row in
                                 page.evaluate(_PRINT_TEXT_JS, PRINT_EXCUSED_SELECTOR)]
            page.close()

            # 4. clipping, one print state per print width.
            for width, portrait in ((PRINT_WIDTH_PORTRAIT, True),
                                    (PRINT_WIDTH_LANDSCAPE, False)):
                page = _print_state(browser, uri, width)
                orientation = "portrait" if portrait else "landscape"
                result.clipped += [(orientation, *row)
                                   for row in page.evaluate(_CLIP_JS, portrait)]
                page.close()
        finally:
            browser.close()
    return result


# -------------------------------------------------------------------- checks --
class Check:
    def __init__(self, name: str, ok: bool, summary: str, details: list[str] | None = None):
        self.name = name
        self.ok = ok
        self.summary = summary
        self.details = details or []


def check_screenshots(result: Render) -> Check:
    from PIL import Image

    problems = []
    sizes = []
    for shot in result.shots:
        if not shot.exists() or shot.stat().st_size == 0:
            problems.append(f"{shot.name}: missing or empty")
            continue
        try:
            with Image.open(shot) as image:
                width, height = image.size
        except Exception as exc:  # noqa: BLE001 - a corrupt PNG is a report defect
            problems.append(f"{shot.name}: undecodable ({exc})")
            continue
        if width == 0 or height == 0:
            problems.append(f"{shot.name}: zero-sized raster")
        sizes.append(f"{shot.name} {width}x{height} {shot.stat().st_size // 1024}KB")
    if len(result.shots) != len(SCREENSHOT_WIDTHS):
        problems.append(f"expected {len(SCREENSHOT_WIDTHS)} shots, got {len(result.shots)}")
    return Check("screenshots", not problems,
                 f"{len(result.shots)} PNG: " + ", ".join(sizes), problems)


def check_pdf(result: Render, pages: list[str]) -> Check:
    problems = []
    if result.pdf is None or not result.pdf.exists() or result.pdf.stat().st_size == 0:
        problems.append("PDF missing or empty")
    if not pages:
        problems.append("pdftotext extracted no pages")
    size = result.pdf.stat().st_size // 1024 if result.pdf and result.pdf.exists() else 0
    return Check("pdf", not problems, f"{len(pages)} pages, {size}KB", problems)


def check_no_truncation(result: Render, flat_pdf: str) -> Check:
    """Forward direction: every DOM text run reaches the PDF text layer.

    Runs that print emulation reports invisible are *still required*, unless
    they match ``PRINT_EXCUSED_SELECTOR``.  Excusing everything invisible would
    make the check unable to see print CSS hiding content it should not.
    """
    missing = []
    checked = 0
    excused = 0
    for text, where, visible, is_excused in result.print_text:
        needle = norm(text)
        if len(needle) < MIN_NEEDLE_CHARS:
            continue
        if is_excused and not visible:
            excused += 1
            continue
        checked += 1
        if needle not in flat_pdf:
            state = "print-visible" if visible else "hidden by print CSS"
            missing.append(f"{where} [{state}]: {text.strip()[:90]!r}")
    return Check(
        "no-truncation", not missing,
        f"{checked} DOM text runs compared (>= {MIN_NEEDLE_CHARS} chars, "
        f"{len(result.print_text)} collected, {excused} excused as screen-only), "
        f"{len(missing)} missing from the PDF text layer",
        missing[:40],
    )


def check_no_stray_glyph(flat_pdf_tokens: list[str], corpus: str) -> Check:
    """Reverse direction: every PDF word is explained by the static HTML."""
    unexplained = []
    checked = 0
    for token in flat_pdf_tokens:
        needle = norm(token)
        if not needle:
            continue
        checked += 1
        if needle not in corpus:
            unexplained.append(token)
    # Report distinct offenders; 20 copies of one stray glyph is one defect.
    distinct = sorted(set(unexplained))
    return Check(
        "no-stray-glyph", not unexplained,
        f"{checked} pdftotext words compared, {len(unexplained)} unexplained "
        f"({len(distinct)} distinct)",
        [f"{token!r} x{unexplained.count(token)}" for token in distinct[:40]],
    )


def check_print_clipping(result: Render) -> Check:
    details = [f"{orientation} {section}: table {table}px > panel {panel}px"
               for orientation, section, table, panel in result.clipped]
    return Check("print-clipping", not result.clipped,
                 f"{len(result.clipped)} table(s) wider than their panel at "
                 f"{PRINT_WIDTH_PORTRAIT}px/{PRINT_WIDTH_LANDSCAPE}px",
                 details)


# ---------------------------------------------------------------------- main --
def verify(html_path: Path, out_dir: Path) -> tuple[list[Check], list[str]]:
    html = html_path.read_text(encoding="utf-8")
    result = render(html_path, out_dir)

    pages = pdf_pages_raw(result.pdf) if result.pdf and result.pdf.exists() else []
    text, footers_removed = strip_page_footers(pages)
    notes = []
    if pages and footers_removed != len(pages):
        notes.append(f"note: stripped {footers_removed} page-number footers from "
                     f"{len(pages)} pages (expected one per page)")
    flat_pdf = norm(text)
    tokens = text.split()

    checks = [
        check_screenshots(result),
        check_pdf(result, pages),
        check_no_truncation(result, flat_pdf),
        check_no_stray_glyph(tokens, static_corpus(html)),
        check_print_clipping(result),
    ]
    return checks, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("html", type=Path, help="a generated report HTML file")
    parser.add_argument("--out-dir", type=Path, default=Path("tmp/phase2b-shots"),
                        help="where screenshots and the PDF go (default tmp/phase2b-shots)")
    args = parser.parse_args(argv)

    if not args.html.is_file():
        print(f"[tool-error] not a file: {args.html}", file=sys.stderr)
        return 2

    try:
        checks, notes = verify(args.html, args.out_dir)
    except ToolError as exc:
        print(f"[tool-error] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - anything unexpected is a tool fault
        print(f"[tool-error] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"== {args.html.name}")
    for note in notes:
        print(f"   {note}")
    for check in checks:
        print(f"  [{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.summary}")
        for line in check.details:
            print(f"         - {line}")
    failed = [check.name for check in checks if not check.ok]
    print(f"   result: {'OK' if not failed else 'FAILED ' + ', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
