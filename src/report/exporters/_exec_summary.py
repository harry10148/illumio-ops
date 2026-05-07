"""Render a 200-word standalone executive summary block.

Phase 1 quick win for c1. All user-influenced values escape via html.escape.
"""
from __future__ import annotations

from html import escape

from .report_i18n import STRINGS


def _resolve_label(k: dict, lang: str) -> str:
    # Some generators (e.g. ven_status_generator) emit lang-agnostic 'i18n_key'
    # so the exporter can resolve at render time; others emit pre-resolved 'label'.
    if k.get('label'):
        return str(k['label'])
    key = k.get('i18n_key')
    if key and key in STRINGS:
        entry = STRINGS[key]
        return entry.get(lang) or entry.get('en') or ''
    return ''


def render_exec_summary_html(mod00: dict, report_name: str, lang: str = 'en') -> str:
    """Return a <section> HTML block for the report header.

    mod00 is the executive-summary dict produced by analysis.{report}_mod00.
    Output target: ≤200 words, standalone (no need to read further sections).
    All inserted values are escape()-ed.
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
        for k in kpis[:6]:
            label = escape(_resolve_label(k, lang))
            value = escape(str(k.get('value', '')))
            items.append(
                f'<div class="kpi"><span class="kpi-label">{label}</span>'
                f'<span class="kpi-value">{value}</span></div>'
            )
        kpi_html = f'<div class="kpi-strip">{"".join(items)}</div>'

    verdict_html = f'<p class="verdict">{escape(str(verdict))}</p>' if verdict else ''
    summary_html = f'<p class="summary-text">{escape(str(summary_text))}</p>' if summary_text else ''

    notes_html = ''
    if notes:
        items = ''.join(f'<li>{escape(str(n))}</li>' for n in notes[:2])
        notes_html = f'<ul class="notes">{items}</ul>'

    return (
        f'<section class="exec-summary" aria-labelledby="exec-summary-title">'
        f'<h2 id="exec-summary-title">Executive Summary — {escape(report_name)}</h2>'
        f'{verdict_html}{kpi_html}{summary_html}{notes_html}'
        f'</section>'
    )
