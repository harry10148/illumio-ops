"""
src/report/exporters/report_shell.py
design/v3 report shell — the shared skeleton every HTML report renders into.

SHELL_CSS below is a port of ``design/v3/reports/shell.css``. That file stays
the design authority for the report shell. It is a copy of
``design/v2/reports/shell.css`` with the palette tokens moved to v3 and nothing
else touched; v2 stays where it is as the historical baseline, because it is
what the prototype renderer (``design/v2/tools/reskin_report.py``) loads and
what the reviewed PDFs in ``design/v2/reports/reskinned/`` were produced from —
those artefacts still describe the file they actually came from. Any change made
on the product side must be annotated back into ``design/v3/reports/shell.css``
so the two do not silently drift apart.

Deliberate deltas from the design file (everything else is a verbatim port).
``tests/test_report_shell_renderer.py`` rebuilds SHELL_CSS from the design file
by applying exactly this list and asserts equality, so the list below and that
test are the drift guard — prose alone is not:
  * a provenance header carrying ``SHELL_CSS_PORT_MARKER``;
  * the "hide the old print cover" rule is dropped — the product no longer
    emits a second cover, so there is nothing to defend against. The screen
    half of the ``.print-only`` / ``.screen-only`` pair is kept;
  * ``.print-btn`` is added (screen-only; hidden in the print block);
  * ``.score-num`` gains ``color: var(--ink)`` so the maturity score picks up
    the grade tone from the ``data-tone`` on its wrapper;
  * ``.mat-fill.warn`` / ``.progress-fill.warn`` is restored from the old
    product shell (``report_css.py:529``). The design file never had it, but
    the old shell did; without it the 40-70% band falls back to the info blue
    and the three-level semantic colour collapses to two. A gap the design file
    shares is still a regression against the shipped output;
  * the empty-table-panel state and the sort-indicator rules are restored from
    the old product shell (``report_css.py:161-163,178,205-207``). Both style
    elements that ``table_renderer.py`` / ``TABLE_JS`` still emit for all ten
    report types; the design file never covered the JS-driven affordances, so
    without them "no data" looks identical to a rendered table and the sort
    arrow becomes loose text beside the column name. Three parts of that port
    are deliberate decisions rather than oversights, recorded here so the next
    reader can tell them apart from omissions:
      - the sorted-column HIGHLIGHT (``report_css.py:177``, a background
        gradient on ``th.is-sorted-asc/desc``) is NOT ported. The shell's table
        header already carries a surface fill and a hairline; a second gradient
        on top of it is the "shadow theatre" the design brief rules out. The
        sorted column still reads from the indicator's full opacity and accent
        colour, so the signal survives in a quieter form;
      - the indicator's accent colour replaces the old ``--gold``: this is an
        interaction state, and the shell's tone-* colours are reserved for
        severity;
      - the print block hides the indicator outright and gives the reserved
        right padding back. Paper cannot be sorted, and ``th`` becomes
        ``position: static`` in print, which detaches the absolutely positioned
        arrow from its column and scatters it down the chapter's right edge
        (measured: 20 stray "↕" in one audit PDF).
  * the ``@page`` blocks gain a ``@bottom-right`` margin box printing
    ``counter(page) " / " counter(pages)``, restored from the old product shell
    (``report_css.py:288-295``). The design file never had it, but every one of
    the ten report types printed it before the migration — measured on
    ``620f7a52``: the still-unmigrated policy_diff and readiness numbered every
    page, the already-migrated traffic / audit / policy_usage numbered none, and
    nobody noticed for two batches. An 8-10 page PDF with no page numbers cannot
    be cited or re-collated once the sheets separate. Only the DEFAULT page
    declares it — measured, not assumed: the named ``wide`` page inherits the
    margin box (removing a second copy from ``@page wide`` leaves rule hit
    count's mixed portrait/landscape document with all 8 pages numbered). The
    font, size and colour are the old shell's literals because the point is to
    reproduce the shipped footer, not because a token would fail: a margin box
    does resolve ``:root``'s custom properties (a ``var()`` build and a
    same-colour literal build rasterise to identical footer pixels);
  * the print block gains the wide-table release rules carried over from the
    old product shell (``report_css.py``) plus ``!important`` on the four
    column-width floors that must survive them — see the comment on the
    release block itself for why both halves are required.

``src`` must never import from ``design/`` — the design tree is not shipped in
the offline bundle — so the severity/tone tables below are copies of
``reskin_report.py``'s, not imports of them.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from typing import Sequence

from src.i18n import t

from .grade_colors import grade_tone

def _read_asset(name: str) -> str:
    import os
    path = os.path.join(os.path.dirname(__file__), "assets", name)
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


__all__ = [
    "SHELL_CSS",
    "TABLE_JS",
    "ShellCover",
    "ShellSection",
    "build_shell_document",
    "wide_table_attrs",
]

# The shell stylesheet is a file next to this module (assets/report_shell.css),
# not a 1,400-line Python string. Read once at import; byte-identical to the
# old literal, so the design-drift guard still compares like for like.
SHELL_CSS = _read_asset("report_shell.css")


# Tone vocabulary of the shell. Anything outside this set degrades to
# "neutral" rather than emitting an attribute the CSS has no rule for.
TONES: tuple[str, ...] = ("ok", "warn", "crit", "info", "neutral")


def _parse_root_tokens(css: str) -> dict[str, str]:
    """Custom properties declared in SHELL_CSS's ``:root`` block.

    Parsed rather than retyped on purpose. Everything that cannot go through
    ``var()`` — matplotlib takes RGB values, not CSS — still has to use the
    shell's colours, and a second hand-written table is exactly the thing that
    falls behind on the next palette move. There is only one such table now,
    and it is generated from the stylesheet that ships.

    Only the first ``:root`` block is read; that is where the palette lives.
    Values are returned verbatim (including non-colour tokens like sizes), so
    callers name the token they want and get whatever the shell says it is.
    """
    start = css.index(":root {")
    end = css.index("}", start)
    out: dict[str, str] = {}
    for line in css[start:end].splitlines():
        line = line.split("/*")[0].strip()
        if not line.startswith("--") or ":" not in line:
            continue
        name, _, value = line.partition(":")
        out[name.strip().lstrip("-")] = value.strip().rstrip(";").strip()
    return out


#: Every custom property the shell's ``:root`` declares, by name without the
#: leading dashes (``tone-crit-border``, ``text-2``, ``space-4``, ...).
SHELL_TOKENS: dict[str, str] = _parse_root_tokens(SHELL_CSS)

#: tone -> the LED colour (``--tone-<t>-border``). This is the colour a chart
#: should use for a solid mark of that tone.
def _relative_luminance(hex_colour: str) -> float:
    """WCAG 相對亮度。給 ink_on() 決定字要壓白的還是黑的。"""
    raw = hex_colour.lstrip("#")
    parts = [int(raw[k:k + 2], 16) / 255 for k in (0, 2, 4)]
    lin = [(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4) for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ink_on(fill_hex: str) -> str:
    """壓在 `fill_hex` 上的字色（CSS 變數名）。

    這件事本來是一句「整條 bar 都用白字」。在深綠、深紅、深青上白字沒問題，
    但同一條 bar 上還有 warn 的橘與 neutral 的灰——白字壓上去只有 2.0 與 2.6:1，
    看得到但讀不了，而**看得到**正是它一直沒被發現的原因。改成逐段依底色亮度
    決定：亮底配印刷黑（warn 9.0:1、neutral 7.1:1），暗底配紙白（ok 7.0:1、
    crit 6.3:1、info 10.2:1），全部過 AA。

    門檻 0.3 落在 crit(0.116) 與 neutral(0.358) 之間，離兩邊都有餘裕；日後改
    色票不會剛好卡在界線上。
    """
    return "var(--text-1)" if _relative_luminance(fill_hex) >= 0.3 else "var(--paper)"


TONE_HEX: dict[str, str] = {t: SHELL_TOKENS[f"tone-{t}-border"] for t in TONES}

#: tone -> the pale fill (``--tone-<t>-bg``) and the ink (``--tone-<t>-fg``).
#: The fill exists so a chart can reproduce the badge's solid-vs-outlined
#: distinction: CRITICAL and HIGH share a tone, and on paper the only thing
#: keeping them apart is that HIGH is outlined rather than filled.
TONE_FILL_HEX: dict[str, str] = {t: SHELL_TOKENS[f"tone-{t}-bg"] for t in TONES}
TONE_INK_HEX: dict[str, str] = {t: SHELL_TOKENS[f"tone-{t}-fg"] for t in TONES}

# Report severity vocabulary -> the shell's five tones. Copied from
# design/v2/tools/reskin_report.py (src must not import from design/).
# CRITICAL and HIGH share a tone; the solid-vs-outlined badge rule in
# SHELL_CSS is what keeps the two levels apart.
SEVERITY_TONE: dict[str, str] = {
    "CRITICAL": "crit",
    "HIGH": "crit",
    "MEDIUM": "warn",
    "LOW": "info",
    "INFO": "neutral",
    "OK": "ok",
    "GOOD": "ok",
    "PASS": "ok",
}
SEVERITY_RANK: tuple[str, ...] = (
    "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "PASS", "GOOD", "OK",
)

# Column count at which a table stops fitting an A4 portrait page and gets its
# own landscape named page. See the wide table policy in SHELL_CSS section 12.
#
# 2026-09-02: was 10, on the assumption that 8-9 columns still read fine
# portrait. Regenerating the audit report against live data disproved it — its
# nine-column user-activity table needs 729px against a 674px portrait panel,
# and squeezing it to fit breaks words in both the headers and the values
# ("NOTIFICATI/ON_DETAIL", "principal_unreso/lved"). The same table on a
# landscape page keeps every value on one line. The portrait cap in SHELL_CSS
# stays as the safety net for eight columns and fewer.
WIDE_TABLE_LANDSCAPE_COLS = 9

_KIND_LABEL_KEY: dict[str, str] = {
    "exec": "rpt_shell_kind_exec",
    "finding": "rpt_shell_kind_finding",
    "detail": "rpt_shell_kind_detail",
}

# Section kinds the shell knows. Anything else degrades to "detail".
KINDS: tuple[str, ...] = tuple(_KIND_LABEL_KEY)


# ---------------------------------------------------------------------------
# TABLE_JS — moved here verbatim from the deleted report_css.py (Task 6). It is
# the only part of the old shell that survived it: the sort / auto-fit / wide-
# scroll behaviour of ``table_renderer.py``'s tables, which all ten report
# types still render. The CSS it depends on (``.sort-indicator``,
# ``.report-table--interactive``, ``.report-table-panel--empty``, and the
# print-time width release) lives in SHELL_CSS above as declared deltas; the
# two halves must move together.
# ---------------------------------------------------------------------------
# The table behaviour script lives in assets/report_table.js.
TABLE_JS = "\n<script>\n" + _read_asset("report_table.js") + "</script>\n"

# Marker token embedded in SHELL_CSS (assets/report_shell.css) identifying the
# v3 port; tests/test_report_shell_renderer.py asserts it is still there.
SHELL_CSS_PORT_MARKER = "shell-css-port-v3"

# The section id the appendix element carries (see _render_appendix). A
# ShellSection must not reuse it or the in-page anchors collide.
APPENDIX_SECTION_ID = "appendix"


def _esc(value: object) -> str:
    """Escape an untrusted scalar for HTML text or attribute context."""
    return _html.escape("" if value is None else str(value), quote=True)


def _tone(value: str) -> str:
    return value if value in TONES else "neutral"


def _kind(value: str) -> str:
    """Whitelist a section kind the way ``_tone()`` whitelists a tone.

    Without this a typo would emit an unknown ``data-shell`` value and an
    empty ``.chapter-eyebrow`` — the kind label would silently disappear
    instead of failing loudly.
    """
    return value if value in KINDS else "detail"


def _kind_label(kind: str, lang: str) -> str:
    key = _KIND_LABEL_KEY.get(kind)
    return t(key, lang=lang) if key else ""


@dataclass(frozen=True)
class ShellCover:
    """Cover data. Every field is a PCE-sourced value and gets escaped here."""

    title: str
    doc_title: str
    type_label: str
    eyebrow: str = ""
    kicker: str = ""
    grade: str = ""
    score: str = ""
    badges: tuple[tuple[str, str], ...] = ()
    meta: dict[str, str] = field(default_factory=dict)


def cover_meta(lang: str, *, pce_url: object = "", org_name: object = "",
               date_range: object = None, generated_at: object = "",
               extra: Sequence[tuple[str, object]] = ()) -> dict[str, str]:
    """The cover's label → value rows, in the one order every report uses.

    PCE, org, data period, generated-at, then ``extra`` (already-translated
    labels). Empty values are left out rather than printed as blank rows.
    ``date_range`` may be a string or a (start, end) pair, joined with " – ".
    Values are raw: build_shell_document escapes them.
    """
    if isinstance(date_range, (tuple, list)):
        date_range = " – ".join(str(d) for d in date_range if d)
    rows: list[tuple[str, object]] = [
        (t("rpt_cover_pce", lang=lang), pce_url),
        (t("rpt_cover_org", lang=lang), org_name),
        (t("rpt_cover_date_range", lang=lang), date_range),
        (t("rpt_cover_generated", lang=lang), generated_at),
        *extra,
    ]
    return {label: str(value) for label, value in rows if value}


@dataclass(frozen=True)
class ShellSection:
    """One chapter. ``html`` is already-rendered, already-escaped markup."""

    id: str
    title: str
    html: str
    kind: str = "detail"
    tone: str = "neutral"
    marks: dict[str, int] = field(default_factory=dict)


def wide_table_attrs(n_cols: int, lang: str) -> tuple[str, str]:
    """Extra panel class + hint paragraph for a table with ``n_cols`` columns.

    Returns ``("", "")`` below the landscape threshold so callers can splice
    the result in unconditionally.

    This returns ``--landscape`` ONLY. It is not self-sufficient: every print
    column-width guarantee in SHELL_CSS (the long-text column's share, the
    readable floor for meta columns, the timestamp floor, the reduced font)
    hangs off ``--wide``, and ``--landscape`` on its own gets ``page: wide`` and
    ``table-layout: fixed`` with none of those floors. The prototype never
    emits ``--landscape`` without ``--wide``
    (``design/v2/tools/reskin_report.py:323``), and today
    ``table_renderer.py``'s threshold of 8 means every >=10 column table is
    already ``--wide``. Callers must keep it that way.
    """
    if n_cols < WIDE_TABLE_LANDSCAPE_COLS:
        return ("", "")
    hint = t("rpt_shell_table_hint_wide", lang=lang, cols=n_cols)
    return (" report-table-panel--landscape",
            f'<p class="table-hint">{_esc(hint)}</p>')


def _mark_chips(marks: dict[str, int]) -> str:
    """Every mark with a non-zero count gets a chip — no cap, no silent drop.

    ``.chapter-marks`` is flex-wrap, so there is no layout reason to truncate,
    and ``chips[:3]`` silently lost the lower severities in the prototype.
    Ranked severities come first in severity order; anything the rank list does
    not know about is appended rather than dropped.

    Zero counts are deliberately NOT rendered: ``{"CRITICAL": 0}`` means "no
    CRITICAL marks in this chapter", and a chip reading "CRITICAL 0" would read
    as a finding rather than the absence of one. This is a decision, not the
    truncation bug above — the number of chips varies with what is present, but
    nothing that is present is ever dropped.
    """
    if not marks:
        return ""
    chips: list[str] = []
    for sev in SEVERITY_RANK:
        count = marks.get(sev)
        if count:
            chips.append(_mark_chip(sev, count))
    for sev, count in marks.items():
        if sev in SEVERITY_RANK or not count:
            continue
        chips.append(_mark_chip(sev, count))
    return "".join(chips)


def _mark_chip(sev: str, count: int) -> str:
    tone = SEVERITY_TONE.get(str(sev).upper(), "neutral")
    return (f'<span class="mark-chip" data-tone="{tone}">'
            f"{_esc(sev)} {_esc(count)}</span>")


def _render_cover(cover: ShellCover, doc_tone: str) -> str:
    badges = "".join(
        f'<span class="badge" data-tone="{_tone(tone)}">{_esc(text)}</span>'
        for text, tone in cover.badges
    )
    if cover.grade:
        # A1: the chip carries data-tone and no inline colour; the grade -> tone
        # mapping is grade_colors.grade_tone(). The score rides along inside the
        # chip the way the original cover printed "F (25.8/100)".
        # .grade-chip is inline-flex, which collapses whitespace *between* its
        # children — a plain space here renders as "D52.4/100". The separator
        # has to live inside the span.
        score = (f'<span class="score-denom">&#160;{_esc(cover.score)}</span>'
                 if cover.score else "")
        badges += (
            f'<span class="grade-chip" data-tone="{grade_tone(cover.grade)}">'
            f"{_esc(cover.grade)}{score}</span>"
        )
    elif cover.score:
        # A score with no grade still has to reach the page. Nesting it inside
        # the `if cover.grade:` branch dropped it from the document entirely —
        # no chip, no text, no warning (the silent-truncation class this repo
        # keeps re-hitting). No chip is drawn because there is no grade to
        # colour it by, so the tone is neutral.
        badges += (f'<span class="score-denom" data-tone="neutral">'
                   f"{_esc(cover.score)}</span>")
    # Each label/value pair is wrapped so the grid lays out the PAIR, not its two
    # halves independently. `.cover-meta` is display:grid, and a bare
    # <dt><dd><dt><dd> is four separate grid items: at three columns the flow put
    # 資料範圍 / its value / 產生時間 on row one and left 產生時間's value alone on
    # row two, directly beneath 資料範圍's label. The reader cannot tell which
    # value belongs to which label — the misfiling failure conservation provably
    # cannot see, because every string is still present and only its position
    # moved. Found by reading a real 17-page PDF, not by any test.
    #
    # The appendix builds the same pairs into a plain <dl> with no grid, so it
    # was never affected and is deliberately left alone.
    meta = "".join(f'<div class="cover-meta-pair"><dt>{_esc(k)}</dt>'
                   f"<dd>{_esc(v)}</dd></div>"
                   for k, v in cover.meta.items())
    return (
        f'<header class="cover" data-shell="cover" data-tone="{_tone(doc_tone)}">'
        + (f'<p class="cover-eyebrow">{_esc(cover.eyebrow)}</p>'
           if cover.eyebrow else "")
        + f"<h1>{_esc(cover.title)}</h1>"
        + (f'<p class="cover-kicker">{_esc(cover.kicker)}</p>'
           if cover.kicker else "")
        + (f'<div class="cover-badges">{badges}</div>' if badges else "")
        + (f'<dl class="cover-meta">{meta}</dl>' if meta else "")
        + "</header>"
    )


def _render_toc(entries: Sequence[ShellSection], lang: str) -> str:
    title = t("rpt_shell_toc_title", lang=lang)
    items = "".join(
        f'<li data-tone="{_tone(section.tone)}">'
        f'<a href="#{_esc(section.id)}">'
        f'<span class="toc-num">{index:02d}</span>'
        f'<span class="toc-label">{_esc(section.title)}</span>'
        f'<span class="toc-dot"></span></a></li>'
        for index, section in enumerate(entries)
    )
    return (
        f'<nav class="toc" data-shell="toc" aria-label="{_esc(title)}">'
        f'<button class="print-btn" onclick="window.print()">'
        f'{_esc(t("rpt_nav_print_pdf", lang=lang))}</button>'
        f"<h2>{_esc(title)}</h2><ol>{items}</ol></nav>"
    )


def _render_appendix(*, lang: str, cover: ShellCover,
                     numbered: Sequence[ShellSection],
                     rule_index: Sequence[tuple[str, str, str]],
                     appendix_html: str) -> str:
    meta = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>"
                   for k, v in cover.meta.items())
    # Same sequence and same numbers as the TOC — the index covers every
    # section (brief: "章節索引(自 sections)"), exec chapters included.
    chapter_dl = "".join(
        f"<dt>{index:02d}</dt><dd>{_esc(section.title)}</dd>"
        for index, section in enumerate(numbered)
    )
    rules = ""
    if rule_index:
        items = "".join(
            f'<li data-tone="{SEVERITY_TONE.get(str(sev).upper(), "neutral")}">'
            f"<code>{_esc(code)}</code><span>{_esc(name)}</span>"
            f'<span class="rule-sev">{_esc(sev)}</span></li>'
            for code, name, sev in rule_index
        )
        rules = (f'<h3>{_esc(t("rpt_shell_appendix_rules", lang=lang))}</h3>'
                 f'<ol class="rule-index">{items}</ol>')
    return (
        f'<section class="appendix" data-shell="appendix"'
        f' id="{APPENDIX_SECTION_ID}">'
        f'<h2>{_esc(t("rpt_shell_appendix_title", lang=lang))}</h2>'
        '<div class="appendix-grid">'
        f'<div><h3>{_esc(t("rpt_shell_appendix_params", lang=lang))}</h3>'
        f"<dl>{meta}</dl></div>"
        f'<div><h3>{_esc(t("rpt_shell_appendix_chapters", lang=lang))}</h3>'
        f"<dl>{chapter_dl}</dl></div>"
        "</div>"
        + rules
        + (f'<div class="colophon">{appendix_html}</div>' if appendix_html else "")
        + "</section>"
    )


def build_shell_document(*, lang: str, cover: ShellCover,
                         sections: Sequence[ShellSection],
                         appendix_html: str = "",
                         rule_index: Sequence[tuple[str, str, str]] = (),
                         extra_head: str = "",
                         include_table_js: bool = True) -> str:
    """Render a complete, offline-openable v2 report document.

    Section order is the caller's order — the shell never re-sorts chapters.
    ``ShellSection.html`` and ``appendix_html``/``extra_head`` are trusted as
    already-escaped rendered markup; every scalar on ``ShellCover`` and
    ``ShellSection`` is escaped here.

    Numbering: there is exactly one sequence — ``exec`` sections first, then
    the chapters, both in caller order — and all three places a number is
    shown read from it. The TOC prints ``{i:02d}`` from 00 (brief), the chapter
    header prints the same digits with an ``S`` prefix, and the appendix index
    lists every section under the same digits. Numbering each of the three
    independently only looks consistent when there is exactly one exec section.

    ``id="appendix"`` is reserved for the appendix element; a ``ShellSection``
    must not use it or the in-page anchors collide.
    """
    ordered = list(sections)
    execs = [s for s in ordered if _kind(s.kind) == "exec"]
    chapters = [s for s in ordered if _kind(s.kind) != "exec"]
    # The single numbering sequence. Chapters start at len(execs).
    numbered = execs + chapters

    # Document tone — read from the FINDING chapters only, never from every
    # chapter (G1). The cover's tone is a claim about what the report found, and
    # a detail chapter's tint is not that claim: while this looked at all
    # chapters, a single CRITICAL cell in an unrelated table (unmanaged hosts,
    # vulnerability exposure, infrastructure scoring) tinted its chapter and,
    # because critical wins outright, dyed the cover of a report with zero
    # findings. Restricting the source decouples the two: a chapter is free to
    # colour itself from its own content without speaking for the document.
    #
    # No finding chapter at all -> neutral, not "the first chapter's tone". A
    # report that never looks for findings (traffic, network inventory) has made
    # no finding to report, and neutral says exactly that; borrowing chapter 1's
    # tint would make the cover assert a severity nothing measured.
    finding_chapters = [s for s in chapters if _kind(s.kind) == "finding"]
    doc_tone = next(
        (_tone(s.tone) for s in finding_chapters if _tone(s.tone) == "crit"),
        _tone(finding_chapters[0].tone) if finding_chapters else "neutral",
    )

    parts = [_render_cover(cover, doc_tone)]
    for section in execs:
        parts.append(
            f'<section class="exec" id="{_esc(section.id)}" data-shell="exec"'
            f' data-tone="{_tone(section.tone)}">'
            f"<h2>{_esc(section.title)}</h2>{section.html}</section>"
        )
    parts.append(_render_toc(numbered, lang))

    chapter_html = "".join(
        f'<section class="chapter" id="{_esc(section.id)}"'
        f' data-shell="{_kind(section.kind)}" data-tone="{_tone(section.tone)}">'
        '<div class="chapter-head">'
        # ASCII chapter number: CJK gets split and re-spaced in the PDF text
        # layer, so the two-pass page-number probe anchors on S00/S01/...
        f'<span class="chapter-index">S{len(execs) + offset:02d}</span>'
        f'<span class="chapter-eyebrow">'
        f'{_esc(_kind_label(_kind(section.kind), lang))}</span>'
        f'<h2 class="chapter-title">{_esc(section.title)}</h2>'
        f'<span class="chapter-marks">{_mark_chips(section.marks)}</span>'
        f"</div>{section.html}</section>"
        for offset, section in enumerate(chapters)
    )
    parts.append(f'<div class="chapters">{chapter_html}</div>')
    parts.append(_render_appendix(lang=lang, cover=cover, numbered=numbered,
                                  rule_index=rule_index,
                                  appendix_html=appendix_html))

    lang_attr = "zh-TW" if lang == "zh_TW" else "en"
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{lang_attr}"><head>\n'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{_esc(cover.doc_title)}</title>\n"
        f"<style>\n{SHELL_CSS}</style>\n"
        + extra_head
        + "</head>\n"
        + f'<body data-report-title="{_esc(cover.type_label)}">'
        + '<div class="sheet"><div class="doc">'
        + "".join(parts)
        + "</div></div>"
        + (TABLE_JS if include_table_js else "")
        + "</body></html>"
    )
