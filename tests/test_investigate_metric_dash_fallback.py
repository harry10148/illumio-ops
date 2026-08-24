"""Static guard: the traffic table's metric column must render "—" for an
unavailable bandwidth/volume figure, not a blank cell.

final-review LOW 6: item.formatted_bandwidth/formatted_volume are keys
that are ABSENT (not None, not "") on a row _shape_traffic_row could not
compute a rate/volume for -- `r.metric = item.formatted_bandwidth`
resolves to `undefined`, and `el("b", {text: undefined})` (core/dom.mjs)
silently skips setting textContent, leaving the cell blank. Honest (no
fabricated number) but inconsistent with spec's "—" convention for
unavailable, and with this same page's own `fmtBw` (used for the peak-
bandwidth KPI), which already renders null as "—".

Pytest cannot execute .mjs, so this reads the source as text -- the repo's
established pattern for frontend invariants a runtime test can't reach
(see tests/test_v2_teardown_registration.py).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVESTIGATE = ROOT / "src" / "static" / "js" / "v2" / "areas" / "investigate.mjs"


def _trafficrows_metric_lines() -> list[str]:
    text = INVESTIGATE.read_text(encoding="utf-8")
    m = re.search(r"function trafficRows\(rows, sort\) \{(.*?)\n\}", text, re.S)
    assert m, "trafficRows(rows, sort) not found in investigate.mjs -- has it moved/been renamed?"
    body = m.group(1)
    return [
        ln for ln in body.splitlines()
        if "r.metric = item.formatted_bandwidth" in ln or "r.metric = item.formatted_volume" in ln
    ]


def test_bandwidth_and_volume_metric_fall_back_to_a_dash_not_undefined():
    lines = _trafficrows_metric_lines()
    assert len(lines) == 2, f"expected exactly the bandwidth+volume assignments, found: {lines}"
    for line in lines:
        assert '|| "—"' in line or "|| '—'" in line, (
            f"metric column must fall back to the em dash for an absent "
            f"formatted_bandwidth/formatted_volume key, not render blank: {line!r}"
        )
