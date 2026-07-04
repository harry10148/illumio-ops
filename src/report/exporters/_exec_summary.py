"""Render a 200-word standalone executive summary block.

Phase 1 quick win for c1. All user-influenced values escape via html.escape.
"""
from __future__ import annotations

from html import escape

from src.i18n import t


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

    label = t('rpt_exec_summary_label', lang=lang, default='Executive Summary')
    heading = f'{escape(label)} — {escape(report_name)}' if report_name else escape(label)
    return (
        f'<section class="exec-summary" aria-labelledby="exec-summary-title">'
        f'<h2 id="exec-summary-title">{heading}</h2>'
        f'{verdict_html}{kpi_html}{summary_html}{notes_html}'
        f'</section>'
    )
