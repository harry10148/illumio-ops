"""The colours an email uses: the report shell's own tokens (email clients do not read CSS variables, so the values
are taken from report_shell.css, never a second palette). Shared by the report email and the alert email; a leaf
module so both can import it."""
from __future__ import annotations

import re
from functools import cache
from importlib import resources

from illumio_ops.domain.values import Severity

_TOKEN = re.compile(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\s*;")
_USED = ("text-1", "text-2", "text-3", "line", "surface-2", "accent-fg", "tone-crit-border", "tone-warn-border",
         "tone-info-border", "tone-neutral-border")


@cache
def _tokens() -> dict[str, str]:
    css = resources.files("illumio_ops.services.reports").joinpath("assets", "report_shell.css").read_text(encoding="utf-8")
    found = dict(_TOKEN.findall(css.split(":root", 1)[1].split("}", 1)[0]))
    return {k: found[k] for k in _USED}


TOKENS = _tokens()
SEVERITY_BORDER = {Severity.CRITICAL: "tone-crit-border", Severity.HIGH: "tone-crit-border",
                   Severity.MEDIUM: "tone-warn-border", Severity.LOW: "tone-info-border"}
