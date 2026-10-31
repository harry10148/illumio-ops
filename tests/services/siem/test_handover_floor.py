"""P8: a destination carried over from 5.x starts where 5.x stopped — events 5.x already sent (at or before the floor)
are passed over once, everything after is sent; the floor then goes, so a late event is never lost."""
import json
from datetime import timedelta

from illumio_ops.services.siem.dispatch import run_siem
from illumio_ops.store import siem as store

from .conftest import DEST, NOW, FakeTransport, add_events, configure


def _ids(t):
    return [json.loads(x)["pce_event_id"].rsplit("e", 1)[1] for x in t.lines]


def _with_floor(ctx, floor):
    configure(ctx)
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        store.start_cursor(conn, DEST, "audit", pce_url=pce.url, org_id=pce.org_id, last_id=0)
        store.set_floor(conn, DEST, "audit", floor)


def test_events_5x_sent_are_passed_over_and_the_rest_sent(ctx):
    _with_floor(ctx, NOW + timedelta(seconds=2))
    add_events(ctx, [4, 1, 3, 2])  # stored in any order: the first cycle after an upgrade reads hours at once
    t = FakeTransport()
    run_siem(ctx, now=NOW, transport_factory=lambda d: t)
    assert sorted(_ids(t)) == ["3", "4"]
    with ctx.db() as conn:
        assert store.get_cursor(conn, DEST, "audit").sent == 2


def test_the_floor_goes_once_caught_up_so_a_late_event_is_sent(ctx):
    _with_floor(ctx, NOW + timedelta(seconds=2))
    add_events(ctx, [1, 3])
    run_siem(ctx, now=NOW, transport_factory=lambda d: FakeTransport())
    run_siem(ctx, now=NOW, transport_factory=lambda d: FakeTransport())  # caught up: the floor goes
    with ctx.db() as conn:
        assert store.get_cursor(conn, DEST, "audit").floor_time is None
    add_events(ctx, [0])  # a VEN reconnecting sends an old event late
    t = FakeTransport()
    run_siem(ctx, now=NOW, transport_factory=lambda d: t)
    assert _ids(t) == ["0"]


def test_the_floor_stays_until_the_first_events_are_stored(ctx):
    _with_floor(ctx, NOW + timedelta(seconds=2))
    run_siem(ctx, now=NOW, transport_factory=lambda d: FakeTransport())  # before the first events cycle
    with ctx.db() as conn:
        assert store.get_cursor(conn, DEST, "audit").floor_time == NOW + timedelta(seconds=2)
