"""Render a 200-word standalone executive summary block.

Phase 1 quick win for c1. All user-influenced values escape via html.escape.
"""
from __future__ import annotations

from html import escape

from src.i18n import t


# How much of the executive summary fits its ≤200-word, standalone brief.
#
# These caps have a history worth reading before touching them. The KPI cap was
# 6, and on 2026-07-23 a visual check found it silently dropping traffic's
# potentially_blocked and unknown decision buckets; the fix at the time was to
# raise the cap to 8. The producers then grew past 8 as well. Counted by walking
# their AST (an earlier hand count of these same numbers was wrong — brace
# counting trips over the f-strings inside the elements):
#
#   mod12_executive_summary._traffic_flows_summary   10, fixed
#   mod12_executive_summary.executive_summary        12 literal
#     (security risk / network inventory)            + 1 UNCONDITIONAL insert
#                                                    + 1 per enforcement mode
#                                                    = 13-17
#   audit_mod00_executive                            8 literal + up to 4  = 8-12
#   pu_mod00_executive                               8 KPIs; notes 0-5
#
# So the same defect came back on the new threshold, and the surplus KPIs left
# the document entirely — the traffic exporter's other KPI renderer,
# `kpi_cards`, is assigned and never read, so this strip is their only outlet.
#
# Raising the cap a second time would only move the cliff again. CLAUDE.md's
# report rule allows eliding — it forbids doing it SILENTLY — so the caps stay
# and what they drop is now stated on the page. Do not raise them; if the brief
# changes, change the brief.
KPI_LIMIT = 8
NOTE_LIMIT = 2


def _elision_note(i18n_key: str, total: int, limit: int, lang: str) -> str:
    """Disclose that the cap dropped items, or '' when it did not.

    Phrased as "showing X of Y" rather than "N more are hidden" so it reads
    correctly at N=1 and so the reader learns the real total, which is the
    number they need in order to know what they are missing.
    """
    if total <= limit:
        return ''
    return (f'<p class="note exec-elided">'
            f'{escape(t(i18n_key, lang=lang, shown=limit, total=total))}</p>')


def _resolve_label(k: dict, lang: str) -> str:
    # Prefer resolving the i18n key ('label_key' or 'i18n_key') at render time
    # so reports render in `lang` even when the generator baked in an English
    # 'label' (e.g. audit_mod00_executive.py). A key "resolves" when t()
    # returns something other than the raw key and not a [MISSING:...]
    # placeholder; otherwise fall back to the pre-resolved 'label'.
    key = k.get('label_key') or k.get('i18n_key')
    if key:
        resolved = t(key, lang=lang)
        if resolved and resolved != key and not resolved.startswith('[MISSING:'):
            return resolved
    if k.get('label'):
        return str(k['label'])
    return key or ''


def kpi_tone_attr(kpi: dict, raw_value: str) -> str:
    """Tone attribute for a KPI, or "" for one that should stay body ink.

    Only the grade gets it. The cover already tones its grade chip; without this
    the executive summary — the page written to be skimmed — is the one page
    that repeats an F without saying it is bad.

    Counts are left alone deliberately: colouring a number implies a judgement
    the number itself does not carry.
    """
    if not str(kpi.get('i18n_key', '')).endswith('_grade'):
        return ''
    from src.report.exporters.grade_colors import grade_tone
    tone = grade_tone(raw_value.strip())
    return '' if tone in ('', 'neutral') else f' data-tone="{tone}"'


def render_exec_summary_html(mod00: dict, report_name: str, lang: str = 'en',
                             include_heading: bool = True) -> str:
    """Return a <section> HTML block for the report header.

    mod00 is the executive-summary dict produced by analysis.{report}_mod00.
    Output target: ≤200 words, standalone (no need to read further sections).
    All inserted values are escape()-ed.

    ``include_heading=False`` omits the block's own ``<h2>``: the v2 report
    shell prints the section heading itself, and leaving this one in would print
    the same title twice. The caller is then responsible for carrying the
    heading text (``rpt_exec_summary_label`` + report name) into the shell.
    """
    if not mod00:
        return ''
    kpis = mod00.get('kpis', []) or []
    verdict = mod00.get('verdict') or mod00.get('overall_status') or ''
    summary_text = mod00.get('summary_text') or mod00.get('exec_summary') or ''
    notes = mod00.get('execution_notes', []) or []

    kpi_html = ''
    if kpis:
        items = []
        for k in kpis[:KPI_LIMIT]:
            label = escape(_resolve_label(k, lang))
            raw = str(k.get('value', ''))
            value = escape(raw)
            items.append(
                f'<div class="kpi"{kpi_tone_attr(k, raw)}>'
                f'<span class="kpi-label">{label}</span>'
                f'<span class="kpi-value">{value}</span></div>'
            )
        kpi_html = (f'<div class="kpi-strip">{"".join(items)}</div>'
                    + _elision_note('rpt_exec_kpi_elided', len(kpis), KPI_LIMIT, lang))

    verdict_html = f'<p class="verdict">{escape(str(verdict))}</p>' if verdict else ''
    summary_html = f'<p class="summary-text">{escape(str(summary_text))}</p>' if summary_text else ''

    notes_html = ''
    if notes:
        items = ''.join(f'<li>{escape(str(n))}</li>' for n in notes[:NOTE_LIMIT])
        notes_html = (f'<ul class="notes">{items}</ul>'
                      + _elision_note('rpt_exec_note_elided', len(notes),
                                      NOTE_LIMIT, lang))

    if not include_heading:
        # No heading means no element for aria-labelledby to point at; a
        # dangling reference is worse than none.
        return (f'<section class="exec-summary">'
                f'{verdict_html}{kpi_html}{summary_html}{notes_html}'
                f'</section>')

    label = t('rpt_exec_summary_label', lang=lang, default='Executive Summary')
    heading = f'{escape(label)} — {escape(report_name)}' if report_name else escape(label)
    return (
        f'<section class="exec-summary" aria-labelledby="exec-summary-title">'
        f'<h2 id="exec-summary-title">{heading}</h2>'
        f'{verdict_html}{kpi_html}{summary_html}{notes_html}'
        f'</section>'
    )
