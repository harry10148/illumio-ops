"""VEN fleet rules: which enforcement-mode changes this tool makes, and what a change would block.

Progression only moves forward, from a white-list (5.x VALID_PROGRESSIONS): a mode the PCE adds later cannot be
progressed until it is named here, and moving back (or to Idle) is done in the PCE."""
from __future__ import annotations

from typing import Literal

MODES = ("idle", "visibility_only", "selective", "full")
TARGETS = ("visibility_only", "selective", "full")
VALID_PROGRESSIONS: dict[str, frozenset[str]] = {
    "idle": frozenset({"visibility_only", "selective", "full"}),
    "visibility_only": frozenset({"selective", "full"}),
    "selective": frozenset({"full"}),
}

Refusal = Literal["unmanaged", "not_in_inventory", "same_mode", "not_forward"]
# What the reported decisions say a target mode would block, for connections into the host:
#   connections — Full blocks what no rule allows: the connections reported Potentially Blocked
#   none        — Visibility Only blocks nothing
#   deny_rules  — Selective blocks only what a Deny Rule names; the reported decision does not say which rule
BlockBasis = Literal["connections", "none", "deny_rules"]


def refusal(current: str | None, target: str) -> Refusal | None:
    """Why a managed workload in the inventory cannot move from `current` to `target`; None when it can."""
    if current == target:
        return "same_mode"
    if target not in VALID_PROGRESSIONS.get(current or "", frozenset()):
        return "not_forward"
    return None


def block_basis(target: str) -> BlockBasis:
    if target == "full":
        return "connections"
    if target == "selective":
        return "deny_rules"
    return "none"
