"""What this PCE / VEN version offers, declared once (spec §6.5.1 version capability detection).

The detection rules are pure; the collectors record the outcome in the flow database, and every
page shows "this PCE / VEN version does not provide it" instead of an empty result.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from illumio_ops.domain.values import CapabilityState, TamperClassification


@dataclass(frozen=True)
class Capability:
    name: str
    label_key: str
    min_version_note: str


CAPABILITIES: dict[str, Capability] = {c.name: c for c in (
    Capability(name="ransomware_risk", label_key="cap_ransomware_risk", min_version_note="PCE 23.5"),
    Capability(name="ransomware_org_summary", label_key="cap_ransomware_org_summary", min_version_note="PCE 23.5"),
    Capability(name="visibility_level", label_key="cap_visibility_level", min_version_note=""),
    Capability(name="tamper_signal", label_key="cap_tamper_signal", min_version_note="VEN 26.2.20"),
    Capability(name="draft_recompute", label_key="cap_draft_recompute", min_version_note=""),
)}


def _field_state(rows: Sequence[Mapping[str, Any]], field: str) -> CapabilityState:
    if not rows:
        return CapabilityState.UNKNOWN
    return CapabilityState.SUPPORTED if any(field in r for r in rows) else CapabilityState.UNSUPPORTED


def detect_from_workloads(rows: Sequence[Mapping[str, Any]]) -> dict[str, CapabilityState]:
    """The field's presence is the signal (its value may be null on a given host)."""
    return {"ransomware_risk": _field_state(rows, "risk_summary"),
            "visibility_level": _field_state(rows, "visibility_level")}


def detect_tamper_signal(classifications: Iterable[str | None]) -> CapabilityState | None:
    """A signal-type event proves support; their absence proves nothing (None = no new knowledge)."""
    return CapabilityState.SUPPORTED if TamperClassification.SIGNAL in set(classifications) else None


def detect_from_status(status: int) -> CapabilityState:
    if 200 <= status < 300:
        return CapabilityState.SUPPORTED
    if status == 404:
        return CapabilityState.UNSUPPORTED
    return CapabilityState.UNKNOWN
