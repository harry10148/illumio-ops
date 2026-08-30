"""Shared 'needs attention' concern card — severity + actor/IP/target + recommendation."""
from __future__ import annotations

import html

from src.report.exporters.html_exporter import _sev_attrs
from src.report.exporters.report_i18n import STRINGS

# RISK_ORDER as a list for sort-key lookup (CRITICAL first)
_RISK_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def _s(key: str, lang: str) -> str:
    entry = STRINGS[key]
    return entry.get(lang) or entry["en"]


def _risk_badge(risk: str) -> str:
    """The v2 shell colours .risk-badge from data-tone/data-sev.

    This used to write RISK_COLOR/RISK_BG straight into a style attribute. The
    hexes are literals so nothing broke, but an inline colour beats the
    stylesheet: the same MEDIUM level rendered rgb(212,160,23) here and
    rgb(138,93,0) in the event tables, and a CRITICAL card was outlined while a
    CRITICAL table cell was solid — two looks for one severity in one document.
    """
    return f'<span class="risk-badge"{_sev_attrs(risk)}>{risk}</span>'


def render_concern_cards(items: list, lang: str = "en") -> str:
    """Render a list of concern-card dicts as HTML.

    Each item dict matches the audit attention-item schema:
      risk, event_type, count, summary, actors, targets, resources, src_ips, recommendation.

    Returns empty string when items is empty.
    Duplicate CSS classes (audit-attn-*) are kept for back-compat with existing audit styles.
    """
    if not items:
        return ""

    def _sort_key(x):
        r = x.get("risk", "INFO")
        try:
            return _RISK_ORDER.index(r)
        except ValueError:
            return 99

    rows = []
    for item in sorted(items, key=_sort_key):
        risk = item.get("risk", "INFO")
        badge = _risk_badge(risk)
        event_type = html.escape(str(item.get("event_type", "")))
        count = item.get("count", 0)
        summary = html.escape(str(item.get("summary", "")))
        rec = html.escape(str(item.get("recommendation", "")))
        actors_str = ", ".join(html.escape(str(a)) for a in item.get("actors", [])[:3]) or "N/A"
        targets_str = ", ".join(html.escape(str(a)) for a in item.get("targets", [])[:3])
        resources_str = ", ".join(html.escape(str(a)) for a in item.get("resources", [])[:3])
        src_ips_str = ", ".join(html.escape(str(ip)) for ip in item.get("src_ips", [])[:3])

        row = (
            f'<div class="concern-card audit-attn-item risk-{risk}"'
            f'{_sev_attrs(risk)}>'
            f'<div class="concern-header audit-attn-header">'
            f'{badge}'
            f'<code class="concern-event audit-attn-event-code">{event_type}</code>'
            f'<span class="concern-count audit-attn-count">x{count}</span>'
            f'</div>'
            f'<div class="concern-summary audit-attn-summary">{summary}</div>'
            f'<div class="concern-meta audit-attn-meta">'
            f'<strong>{_s("rpt_au_actor", lang)}</strong> {actors_str}'
            + (f' &nbsp;|&nbsp; <strong>IP:</strong> {src_ips_str}' if src_ips_str else '')
            + '</div>'
            + (
                f'<div class="concern-meta audit-attn-meta">'
                f'<strong>{_s("rpt_au_target", lang)}</strong> {targets_str}'
                + (f' &nbsp;|&nbsp; <strong>{_s("rpt_au_resource", lang)}</strong> {resources_str}' if resources_str else '')
                + '</div>'
                if targets_str or resources_str else ''
            )
            + f'<div class="concern-rec audit-attn-rec"><strong>{_s("rpt_au_rec", lang)}</strong> {rec}</div>'
            f'</div>'
        )
        rows.append(row)

    return "".join(rows)
