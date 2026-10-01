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


def pd_sql_predicate(column, filters: set[str] | frozenset[str] | None):
    """與 pd_accepted 等價的 SQL 條件（None＝不篩選）。

    安全網補登在候選掃描階段就要套用目的地的 pd 篩選：否則被篩掉的 flow
    （例如只收 blocked 的目的地遇上所有 allowed flow）每個 tick 都會成為候選，
    觸發大量 IN 查詢、把整個視窗的 id 載入記憶體。
    """
    from sqlalchemy import func, or_

    if not filters:
        return None
    norm = func.lower(func.trim(column))
    accepted: set[str] = set()
    for name in filters:
        if name == "unknown":
            continue
        accepted.add(name)
        accepted.update(code for code, n in _BY_CODE.items() if n == name)
    known = set(PD_VALUES) - {"unknown"} | set(_BY_CODE)
    clauses = []
    if accepted:
        clauses.append(norm.in_(sorted(accepted)))
    if "unknown" in filters:
        clauses.append(column.is_(None))
        clauses.append(norm.not_in(sorted(known)))
    return or_(*clauses)
