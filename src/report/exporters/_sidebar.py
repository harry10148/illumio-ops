"""Render a sidebar with cross-report navigation.

Phase 1 quick win for c1. Static label set, no user input — but escape
report_name through html.escape as defense in depth.
"""
from __future__ import annotations

from html import escape


REPORTS = [
    ('audit', 'Audit Report', 'audit_report.html'),
    ('policy_usage', 'Policy Usage Report', 'policy_usage_report.html'),
    ('ven_status', 'VEN Status Report', 'ven_status_report.html'),
    ('traffic', 'Traffic Report', 'traffic_report.html'),
]


def render_sidebar_html(current: str) -> str:
    """Return an <aside> HTML block listing sibling reports."""
    items = []
    for key, label, href in REPORTS:
        label_html = escape(label)
        href_html = escape(href, quote=True)
        if key == current:
            items.append(f'<li class="current" aria-current="page">{label_html}</li>')
        else:
            items.append(f'<li><a href="{href_html}">{label_html}</a></li>')
    return (
        f'<aside class="report-sidebar" aria-label="Report navigation">'
        f'<h3>Reports</h3><ul>{"".join(items)}</ul></aside>'
    )
