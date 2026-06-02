"""Small stdlib-based template rendering for alert outputs."""

from __future__ import annotations

import os
import re
from string import Template

from src.i18n import t
from src.events.reference import load_reference

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
_ALERT_TPL_KEY_RE = re.compile(r'\$(?:\{)?(alert_tpl_[a-zA-Z0-9_]+)')


def render_alert_template(template_name: str, **values) -> str:
    path = os.path.join(_TEMPLATE_DIR, template_name)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()

    # Auto-merge alert_tpl_* translations so callers don't need to pass them.
    for key in set(_ALERT_TPL_KEY_RE.findall(text)):
        values.setdefault(key, t(key))

    return Template(text).safe_substitute(values)


def enrich_event_context(event: dict) -> dict:
    """Return a copy of `event` enriched with description/severity/remediation/doc_url
    from the authoritative event reference. Unknown event_types pass through unchanged."""
    out = dict(event)
    ref = load_reference().get(event.get("event_type", ""))
    if ref:
        out.setdefault("description", ref.description)
        out.setdefault("severity", ref.severity)
        out.setdefault("remediation", ref.remediation)
        out.setdefault("doc_url", ref.doc_url)
    return out
