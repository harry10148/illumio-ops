"""PII masking for PCE audit events before SIEM dispatch.

The PCE audit event schema (per Illumio REST API Public Schemas) carries
three fields a privacy-conscious deployment may want to redact before
forwarding to an external SIEM:

  1. `created_by.user.username` — typically the admin's email address.
  2. `action.src_ip` — the admin's source IP at the time of the action.
  3. `resource_changes[].changes[*].{before,after}` — free-text values
     such as rule descriptions and label assignments, which often carry
     internal project / customer names.
  4. `notifications[].info.{user.username,user.name,user.email,src_ip}` —
     the same actor / client IP again, forwarded verbatim by `cef_pce` (cs4).

Masking is opt-in **per destination** (settings: siem.destinations[].mask_pii)
so an internal SOC and an external managed-SIEM can coexist with different
privacy levels in the same deployment.

The mask returns a *new* dict; the caller's event object is not mutated.
"""
from __future__ import annotations

import re
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
    if isinstance(action, dict) and action.get("src_ip"):
        action["src_ip"] = REDACTED


_USER_KEYS = ("username", "name", "full_name", "email")


def _redact_before_after(node: Any) -> None:
    """Every before/after at any depth (a label change nests them: changes.labels.added[].after)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("before", "after"):
                node[k] = REDACTED
            else:
                _redact_before_after(v)
    elif isinstance(node, list):
        for item in node:
            _redact_before_after(item)


def _redact_users(node: Any) -> None:
    """A user object anywhere (resource.user of a user's own event, a user in a change): its sign-in name, name
    and email."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "user" and isinstance(v, dict):
                for key in _USER_KEYS:
                    if v.get(key):
                        v[key] = REDACTED
            _redact_users(v)
    elif isinstance(node, list):
        for item in node:
            _redact_users(item)


def _mask_changes(event: dict[str, Any]) -> None:
    """Redact the free text of every change and the users the changed resources name."""
    rc = event.get("resource_changes")
    if not isinstance(rc, list):
        return
    for entry in rc:
        if isinstance(entry, dict):
            _redact_before_after(entry.get("changes"))
            _redact_users(entry)


def _mask_top_level_actor(event: dict[str, Any]) -> None:
    """Normalized events expose flat `actor` / `source_ip` fields too.
    These are user-facing email/IP strings derived from the original payload,
    so redact them as well when present at top level."""
    if event.get("actor") and event.get("actor") != "System":
        event["actor"] = REDACTED
    if event.get("source_ip"):
        event["source_ip"] = REDACTED


def _mask_notifications(event: dict[str, Any]) -> None:
    """cs4 (cef_pce) forwards notifications verbatim; the PCE puts the
    acting user's email and the client IP inside `info`, same PII as
    created_by / action."""
    notes = event.get("notifications")
    if not isinstance(notes, list):
        return
    for entry in notes:
        if not isinstance(entry, dict):
            continue
        info = entry.get("info")
        if not isinstance(info, dict):
            continue
        user = info.get("user")
        if isinstance(user, dict):
            for key in ("username", "name", "email"):
                if user.get(key):
                    user[key] = REDACTED
        if info.get("src_ip"):
            info["src_ip"] = REDACTED


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
    _mask_notifications(masked)
    return masked


# ── this product's own events (P7 security review) ───────────────────────────
# A masked destination gets no account, actor or email from an alert or a detection either: the subject of an account
# detection is a person's sign-in name, an event alert's facts name who did it. Hosts and addresses of workloads stay
# (operational data, as 5.x kept a flow's addresses).
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PERSON_KEYS = frozenset({"actor", "actors", "account", "accounts", "user", "users", "username", "user_name",
                          "created_by", "initiator_user", "email", "full_name", "sample_accounts"})


def _redact_people(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: (REDACTED if k in _PERSON_KEYS and v not in (None, "", [], {}) else _redact_people(v))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_redact_people(x) for x in node]
    if isinstance(node, str):
        return _EMAIL.sub(REDACTED, node)
    return node


def is_person(subject: str) -> bool:
    """A subject that names an account, not a workload (an href) or an address (ip:...)."""
    return bool(subject) and not subject.startswith(("/orgs/", "ip:"))


def mask_text(text: str, people: list[str]) -> str:
    for p in sorted({p for p in people if p}, key=len, reverse=True):
        text = text.replace(p, REDACTED)
    return _EMAIL.sub(REDACTED, text)


def mask_facts(facts: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = _redact_people(facts)
    return out


def people_in(node: Any) -> list[str]:
    """Every string a person key holds, at any depth (to take them out of a sentence too)."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _PERSON_KEYS:
                out += [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)]
                if isinstance(v, dict | list):
                    out += people_in(v)
            else:
                out += people_in(v)
    elif isinstance(node, list):
        for x in node:
            out += people_in(x)
    return out
