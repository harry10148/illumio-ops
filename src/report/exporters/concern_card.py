"""Shared 'needs attention' concern card — severity + actor/IP/target + recommendation."""
from __future__ import annotations

import html

from src.report.analysis.audit.audit_risk import RISK_BG, RISK_COLOR
from src.report.exporters.report_i18n import STRINGS

# RISK_ORDER as a list for sort-key lookup (CRITICAL first)
_RISK_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


def _s(key: str, lang: str) -> str:
    entry = STRINGS[key]
    return entry.get(lang) or entry["en"]


def _risk_badge(risk: str) -> str:
    color = RISK_COLOR.get(risk, "#989A9B")
    bg = RISK_BG.get(risk, "#F9FAFB")
    return (
        f"<span class='risk-badge' style='background:{bg};color:{color};border-color:{color}'>"
        f"{risk}</span>"
    )


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
            f'<div class="concern-card audit-attn-item risk-{risk}">'
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
