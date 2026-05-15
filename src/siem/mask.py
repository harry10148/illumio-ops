"""PII masking for PCE audit events before SIEM dispatch.

The PCE audit event schema (per Illumio REST API Public Schemas) carries
three fields a privacy-conscious deployment may want to redact before
forwarding to an external SIEM:

  1. `created_by.user.username` — typically the admin's email address.
  2. `action.src_ip` — the admin's source IP at the time of the action.
  3. `resource_changes[].changes[*].{before,after}` — free-text values
     such as rule descriptions and label assignments, which often carry
     internal project / customer names.

Masking is opt-in **per destination** (config: SiemDestinationSettings.mask_pii)
so an internal SOC and an external managed-SIEM can coexist with different
privacy levels in the same deployment.

The mask returns a *new* dict; the caller's event object is not mutated.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

REDACTED = "[REDACTED]"


def _mask_actor(event: dict[str, Any]) -> None:
    created_by = event.get("created_by")
    if isinstance(created_by, dict):
        user = created_by.get("user")
        if isinstance(user, dict):
            for key in ("username", "name", "email"):
                if user.get(key):
                    user[key] = REDACTED


def _mask_action(event: dict[str, Any]) -> None:
    action = event.get("action")
    if isinstance(action, dict):
        if action.get("src_ip"):
            action["src_ip"] = REDACTED


def _mask_changes(event: dict[str, Any]) -> None:
    """Redact before/after on every property of every resource_changes entry."""
    rc = event.get("resource_changes")
    if not isinstance(rc, list):
        return
    for entry in rc:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        # PCE schema variants: list of {name, before, after} OR dict keyed by attr name.
        if isinstance(changes, list):
            for ch in changes:
                if not isinstance(ch, dict):
                    continue
                for k in ("before", "after"):
                    if k in ch:
                        ch[k] = REDACTED
        elif isinstance(changes, dict):
            for attr_name, ch in changes.items():
                if isinstance(ch, dict):
                    for k in ("before", "after"):
                        if k in ch:
                            ch[k] = REDACTED


def _mask_top_level_actor(event: dict[str, Any]) -> None:
    """Normalized events expose flat `actor` / `source_ip` fields too.
    These are user-facing email/IP strings derived from the original payload,
    so redact them as well when present at top level."""
    if event.get("actor") and event.get("actor") != "System":
        event["actor"] = REDACTED
    if event.get("source_ip"):
        event["source_ip"] = REDACTED


def mask_event(event: dict[str, Any], *, mask_pii: bool = False) -> dict[str, Any]:
    """Return a possibly-masked copy of an event.

    When `mask_pii` is False (default), returns the event unchanged
    (zero-copy is fine — caller usually serializes immediately).
    When `mask_pii` is True, returns a deep copy with the three sensitive
    field families redacted in-place.
    """
    if not mask_pii:
        return event
    if not isinstance(event, dict):
        return event
    masked = deepcopy(event)
    _mask_actor(masked)
    _mask_top_level_actor(masked)
    _mask_action(masked)
    _mask_changes(masked)
    return masked


def mask_flow(flow: dict[str, Any], *, mask_pii: bool = False) -> dict[str, Any]:
    """Traffic flows are non-PII by nature (src/dst IPs + ports + labels are
    operational data, not personal). This is a placeholder that currently
    returns the flow unchanged but exists so callers don't need to special-case
    event-vs-flow when invoking masking. Future-proof for if PCE adds
    user-attribution fields to flows."""
    return flow
