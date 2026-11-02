"""What an alert can say that the vendor's filter and traffic map cannot (UI redesign spec §4.1 「原廠查不到的」):
fixed sentences, each tied to a field a detector put in its summary. A field the summary lacks gives no sentence —
nothing here is inferred."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from illumio_ops.domain.values import PrecursorKind


@dataclass(frozen=True)
class Fact:
    text_key: str
    params: dict[str, str]


PRECURSOR_KEYS: Mapping[str, str] = {
    PrecursorKind.TAMPER.value: "beyond_precursor_tamper",
    PrecursorKind.SUSPEND.value: "beyond_precursor_suspend",
    PrecursorKind.OFFLINE.value: "beyond_precursor_offline",
}


def _s(value: Any) -> str:
    return str(value)


def beyond_vendor(summary: Mapping[str, Any]) -> list[Fact]:
    out: list[Fact] = []
    # peer deviation (spec §6.5.8 A): no member of the host's group had used this destination and port
    if "group" in summary and "group_size" in summary:
        out.append(Fact("beyond_peer_never", {"group": _s(summary["group"]), "group_size": _s(summary["group_size"]),
                                              "starters": _s(summary.get("starters", 1))}))
    # the host's own history of bytes (volume surge, data staging)
    if "previous_max_mb" in summary and "mb" in summary:
        out.append(Fact("beyond_volume", {"mb": _s(summary["mb"]), "previous_max_mb": _s(summary["previous_max_mb"])}))
    # the account's sources before this one
    if "known_sources" in summary and "user" in summary:
        out.append(Fact("beyond_account_sources", {"user": _s(summary["user"]), "source": _s(summary.get("source", "")),
                                                   "known_sources": _s(summary["known_sources"])}))
    if summary.get("process"):
        out.append(Fact("beyond_process", {"process": _s(summary["process"])}))
    if summary.get("new_listener") is True:
        out.append(Fact("beyond_new_listener", {"target": _s(summary.get("target", ""))}))
    if summary.get("via"):
        out.append(Fact("beyond_via", {"via": _s(summary["via"]), "target": _s(summary.get("target", ""))}))
    for p in summary.get("precursors") or ():
        key = PRECURSOR_KEYS.get(str(p.get("kind"))) if isinstance(p, Mapping) else None
        if key:
            out.append(Fact(key, {"at": _s(p.get("at", ""))}))
    return out
