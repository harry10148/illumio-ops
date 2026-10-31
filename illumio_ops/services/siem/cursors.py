"""Where a destination starts (P7): when the SIEM page is saved, every enabled source of every enabled destination
gets its cursor at the newest record then — what is stored at that moment is history (spec §7), and nothing stored
after it is skipped, however long until the next run (Codex review: placing it at the first run skipped what came in
between). A source taken away, a destination turned off or removed, or SIEM turned off forgets its place."""
from __future__ import annotations

from illumio_ops.services.context import AppContext
from illumio_ops.services.siem.sources import cursor_sources, newest_id
from illumio_ops.store import siem as store


def place_new_cursors(ctx: AppContext) -> None:
    s = ctx.settings.current()
    pce = s.pce
    with ctx.db() as conn:
        have = store.cursors(conn)
    keep: dict[str, list[str]] = {}
    for d in s.siem.destinations:
        if not (s.siem.enabled and d.enabled):
            continue
        keep[d.id] = cursor_sources(d)
        for source in keep[d.id]:
            cur = have.get((d.id, source))
            if cur is None or (cur.pce_url, cur.org_id) != (pce.url, pce.org_id):
                last = newest_id(ctx, source)
                with ctx.db() as conn:
                    store.start_cursor(conn, d.id, source, pce_url=pce.url, org_id=pce.org_id, last_id=last)
    with ctx.db() as conn:
        for dest_id in {d for d, _ in have}:
            store.forget_destination(conn, dest_id, keep.get(dest_id, []))
