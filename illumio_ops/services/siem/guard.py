"""Retention never waits for a SIEM destination (a dead one would freeze the store), but what it deletes before a
destination sent it is counted on that destination's cursor and shown on the status page (P7)."""
from __future__ import annotations

from collections.abc import Callable

from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import SiemDestination
from illumio_ops.store import siem as store

# Eligible records about to be deleted with an id above the given one, for that destination (its own filter, e.g. the
# new-connection decisions it takes).
CountAfter = Callable[[int, SiemDestination], int]


def expiring(ctx: AppContext, source: str, count_after: CountAfter) -> dict[tuple[str, str], int]:
    """Per cursor of this source (of the configured PCE): how many records about to be deleted it has not sent.
    Called just before the delete, inside the same hold of the store's write lock."""
    settings = ctx.settings.current()
    pce = settings.pce
    dests = {d.id: d for d in settings.siem.destinations}
    with ctx.db() as conn:
        cursors = [c for (_, s), c in store.cursors(conn).items()
                   if s == source and (c.pce_url, c.org_id) == (pce.url, pce.org_id) and c.destination_id in dests]
    return {(c.destination_id, source): n for c in cursors if (n := count_after(c.last_id, dests[c.destination_id]))}


def record_dropped(ctx: AppContext, counts: dict[tuple[str, str], int]) -> None:
    if counts:
        with ctx.db() as conn:
            store.add_dropped(conn, counts)
