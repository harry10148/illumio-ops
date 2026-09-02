"""A connection error's diagnosis lives at its END, not its start.

urllib3 renders an unreachable host as

    HTTPSConnectionPool(host='…', port=443): Max retries exceeded with url:
    /api/v2/orgs/NNNN/events?time_gte=…&time_lte=…&max_results=… (Caused by
    NewConnectionError(…: Failed to establish a new connection: [Errno 110]
    Connection timed out))

The host is at the front, the long query string is in the middle, and the only
part that says WHY — the `Caused by` clause — is at the very end. Cutting the
first N characters therefore keeps the least useful half: the watchdog alert
told operators "cannot reach the PCE" and stopped right before the reason.
"""
from __future__ import annotations

from src.events.stats import elide_error

LONG = (
    "HTTPSConnectionPool(host='pce.example.invalid', port=443): Max retries "
    "exceeded with url: /api/v2/orgs/1234567/events?time_gte=2026-09-01T00%3A00%3A00Z"
    "&time_lte=2026-09-02T00%3A00%3A00Z&max_results=10000&event_type=all "
    "(Caused by NewConnectionError('<urllib3.connection.HTTPSConnection object at "
    "0x7f0000000000>: Failed to establish a new connection: [Errno 110] "
    "Connection timed out'))"
)


def test_short_message_is_untouched():
    assert elide_error("boom", 120) == "boom"
    assert elide_error("x" * 120, 120) == "x" * 120


def test_long_message_keeps_the_cause_at_the_end():
    """What matters is the failure mode and errno, not the literal "Caused by".

    At 240 characters the tail holds the NewConnectionError text and the errno;
    the "(Caused by" preamble itself falls in the elided middle. That is the
    right trade — the words that tell an operator whether this is DNS, a
    firewall or TLS are the ones at the very end.
    """
    out = elide_error(LONG, 240)
    assert "Connection timed out" in out
    assert "[Errno 110]" in out


def test_long_message_keeps_the_host_at_the_start():
    out = elide_error(LONG, 240)
    assert "pce.example.invalid" in out


def test_result_never_exceeds_the_limit():
    for limit in (60, 120, 240, 400):
        assert len(elide_error(LONG, limit)) <= limit


def test_elision_is_marked_not_silent():
    """A silently cut string reads as a complete one — this project's rule."""
    out = elide_error(LONG, 240)
    assert "..." in out or "…" in out


def test_head_only_truncation_would_have_lost_the_cause():
    """Pins why this helper exists, so nobody 'simplifies' it back to a slice."""
    assert "Connection timed out" not in LONG[:120]
    assert "Connection timed out" in elide_error(LONG, 120)
