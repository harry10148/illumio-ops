"""The windows traffic is asked of the PCE in (services/collect/windows.py): none crosses a UTC midnight, and one
that ends at a midnight is asked to the second before — the PCE keeps traffic by UTC day and answers a window that
touches two days with both days' counts in one record (lab 26.2 and SaaS 26.30, 2026-11-14)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise

from illumio_ops.services.collect.windows import SLICE, asked_end, day_end, slices

T = datetime(2026, 11, 3, 22, 40, tzinfo=UTC)
MIDNIGHT = datetime(2026, 11, 4, tzinfo=UTC)


def test_slices_stop_at_utc_midnight():
    got = slices(T, MIDNIGHT + timedelta(minutes=40))
    assert got == [(T, T + SLICE), (T + SLICE, MIDNIGHT), (MIDNIGHT, MIDNIGHT + timedelta(minutes=40))]
    assert all(a.date() == (b - timedelta(microseconds=1)).date() for a, b in got)


def test_slices_cover_the_span_without_a_hole():
    end = T + timedelta(days=2, hours=3)
    got = slices(T, end)
    assert got[0][0] == T and got[-1][1] == end
    assert all(a[1] == b[0] for a, b in pairwise(got))
    assert all(b - a <= SLICE for a, b in got)


def test_one_piece_when_short_and_within_a_day():
    assert slices(T, T + timedelta(minutes=30)) == [(T, T + timedelta(minutes=30))]


def test_day_end_is_the_next_utc_midnight_whatever_the_zone():
    taipei = timezone(timedelta(hours=8))
    assert day_end(T) == MIDNIGHT
    assert day_end(datetime(2026, 11, 4, 6, 40, tzinfo=taipei)) == MIDNIGHT  # 22:40 UTC the day before
    assert day_end(MIDNIGHT) == MIDNIGHT + timedelta(days=1)


def test_a_window_ending_at_midnight_is_asked_to_the_second_before():
    assert asked_end(T, MIDNIGHT) == MIDNIGHT - timedelta(seconds=1)
    assert asked_end(T, T + SLICE) == T + SLICE  # not a midnight: as it is
    # a midnight in another zone is not the PCE's
    local = datetime(2026, 11, 4, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert asked_end(local - SLICE, local) == local
    # never before its own start
    assert asked_end(MIDNIGHT - timedelta(seconds=1), MIDNIGHT) == MIDNIGHT
