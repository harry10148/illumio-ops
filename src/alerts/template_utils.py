"""Small stdlib-based template rendering for alert outputs."""

from __future__ import annotations

import os
from string import Template


_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


def render_alert_template(template_name: str, **values) -> str:
    path = os.path.join(_TEMPLATE_DIR, template_name)
    with open(path, "r", encoding="utf-8") as handle:
        template = Template(handle.read())
    return template.safe_substitute(values)
