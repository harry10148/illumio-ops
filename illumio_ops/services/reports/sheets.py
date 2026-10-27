"""Worksheet names for a report's tables: the HTML says which sheet holds a capped table's rows, so both
renderers name sheets the same way."""
from __future__ import annotations

import re
from collections.abc import Sequence

_ILLEGAL = re.compile(r"[\[\]:*?/\\]")
MAX_LEN = 31  # Excel's limit
RESERVED = ("Summary", "摘要")  # the summary sheet's names (render_xlsx)


def sheet_names(titles: Sequence[str]) -> list[str]:
    """Illegal characters removed, at most 31 characters, unique (case-insensitive, as Excel compares)."""
    used = {r.lower() for r in RESERVED}
    out = []
    for title in titles:
        base = _ILLEGAL.sub(" ", title).strip().strip("'") or "Sheet"
        name = base[:MAX_LEN]
        n = 2
        while name.lower() in used:
            suffix = f" ({n})"
            name = base[:MAX_LEN - len(suffix)] + suffix
            n += 1
        used.add(name.lower())
        out.append(name)
    return out
