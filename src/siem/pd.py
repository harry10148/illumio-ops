"""Policy-decision vocabulary shared by the SIEM traffic filter.

The cache's ``action`` column holds whatever the PCE returned:
``flow.action or flow.policy_decision`` — the Explorer API's string names,
or the flat form's numeric codes (0/1/2). One normaliser so the per-destination
filter, the config validator and the GUI/CLI all agree on the four names.
"""
from __future__ import annotations

from typing import Any

PD_VALUES: tuple[str, ...] = ("allowed", "potentially_blocked", "blocked", "unknown")

_BY_CODE = {"0": "allowed", "1": "potentially_blocked", "2": "blocked"}


def normalise_pd(value: Any) -> str:
    """Map a stored ``action`` / ``policy_decision`` value to one of PD_VALUES.

    Anything unrecognised is ``unknown`` — the same bucket the ingestor uses
    when the PCE omitted the field — so a filter that lists ``unknown``
    catches every row it cannot classify, and one that does not never
    receives them.
    """
    if value is None:
        return "unknown"
    text = str(value).strip().lower()
    if text in PD_VALUES:
        return text
    return _BY_CODE.get(text, "unknown")


def pd_accepted(filters: set[str] | frozenset[str] | None, action: Any) -> bool:
    """True when a destination with ``filters`` should receive a row whose
    stored action is ``action``. An absent or empty filter set means every
    decision — the config default ``traffic_pd: []`` is "all", never "none"."""
    if not filters:
        return True
    return normalise_pd(action) in filters
