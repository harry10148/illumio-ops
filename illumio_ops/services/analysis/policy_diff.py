"""Policy diff (spec §6.5 policy_diff, P5c-3): what the Draft changes against the active policy, read live from the
PCE, each change attributed to the newest event in the store that names it. Events name the Draft href they changed
(resource_changes[].href, lab 2026-10-30); 5.x matched names, which a rename or a shared name defeats.

A failed read raises: an empty side would read as everything added or removed."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from illumio_ops.domain.policy_diff import (
    Change,
    diff_objects,
    diff_rule_sets,
    draft_href,
    grade,
    object_refs,
)
from illumio_ops.domain.segment import EventFilter, EventSegment
from illumio_ops.domain.values import SegmentView
from illumio_ops.pce.policy import (
    PendingItem,
    fetch_objects,
    fetch_pending,
    fetch_policy_names,
    fetch_rule_sets,
)
from illumio_ops.services.context import AppContext
from illumio_ops.services.eventsource import event_detail

DEADLINE_SECONDS = 600
EVENT_LIMIT = 1_000  # newest policy events read for attribution; more are disclosed
# (PCE collection, Change kind, compared fields) — the 5.x whitelist.
OBJECTS = (("ip_lists", "ip_list", ("ip_ranges", "fqdns", "description")),
           ("services", "service", ("service_ports", "windows_services", "description")),
           ("label_groups", "label_group", ("labels", "sub_groups", "description")))
COMPARED_PENDING = frozenset({"rule_sets", "ip_lists", "services", "label_groups"})
POLICY_EVENTS = tuple(f"{family}.{verb}" for family in ("rule_set", "sec_rule", "deny_rule", "ip_list", "service",
                                                          "label_group")
                      for verb in ("create", "update", "delete"))


class Attribution(BaseModel):
    actor: str
    at: datetime
    event_type: str


class PolicyDiff(BaseModel):
    changes: list[Change]
    pending: list[PendingItem]
    other_pending: list[PendingItem]  # pending kinds not compared here (firewall settings, virtual services, ...)
    attribution: dict[str, Attribution]  # Draft href (draft_href) -> newest event naming it
    attribution_limited: bool  # more policy events in the period than were read
    computed_at: datetime


def _names(ctx: AppContext, client: Any, deadline: float) -> dict[str, str]:
    names: dict[str, str] = {}
    for pversion in ("active", "draft"):
        pn = fetch_policy_names(client, pversion, deadline=deadline)
        names.update(pn.names)
        names.update({href: f"{k}:{v}" for href, (k, v) in pn.labels.items()})
    return names


def _attribution(ctx: AppContext, start: datetime, end: datetime, now: datetime,
                 wanted: set[str]) -> tuple[dict[str, Attribution], bool]:
    q = event_detail(ctx, EventSegment(filter=EventFilter(start=start, end=end, event_types=POLICY_EVENTS),
                                       view=SegmentView.DETAIL, limit=EVENT_LIMIT), now=now)
    out: dict[str, Attribution] = {}
    for row in q.rows:  # newest first: the first event naming a href is its latest
        for rc in row.raw.get("resource_changes") or []:
            href = rc.get("href") if isinstance(rc, dict) else None
            if href in wanted and href not in out:
                out[href] = Attribution(actor=row.created_by_name or row.created_by_kind or "—", at=row.timestamp,
                                        event_type=row.event_type)
    return out, q.limit_hit


def policy_diff(ctx: AppContext, *, start: datetime, end: datetime, now: datetime | None = None) -> PolicyDiff:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = time.monotonic() + DEADLINE_SECONDS
    with ctx.pce_client(ctx.settings.current().pce) as client:
        draft_sets = fetch_rule_sets(client, "draft", deadline=deadline)
        active_sets = fetch_rule_sets(client, "active", deadline=deadline)
        names = _names(ctx, client, deadline)
        changes = diff_rule_sets(draft_sets, active_sets, names)
        for collection, kind, fields in OBJECTS:
            changes += diff_objects(fetch_objects(client, "draft", collection, deadline=deadline),
                                    fetch_objects(client, "active", collection, deadline=deadline),
                                    kind=kind, fields=fields, names=names)  # type: ignore[arg-type]
        pending = fetch_pending(client, deadline=deadline)
    changes = grade(changes, object_refs(active_sets))
    attribution, limited = _attribution(ctx, start, end, at, {draft_href(c.href) for c in changes})
    return PolicyDiff(changes=changes, pending=pending,
                      other_pending=[p for p in pending if p.kind not in COMPARED_PENDING],
                      attribution=attribution, attribution_limited=limited, computed_at=at)
