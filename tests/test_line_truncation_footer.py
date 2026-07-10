"""LINE digest sections cap entries; the cut must be announced, not silent.

Uses health_alerts (cap [:2], no pre-existing footer) rather than event_alerts:
the event section already caps at [:3] and already appends a non-silent
"alert_field_remaining_events" footer of its own (added in an earlier commit),
so it is already compliant with the "no silent truncation" rule and is left
untouched here. health/traffic/metric sections shared the same [:2] cap with
no footer at all before this change.
"""
from __future__ import annotations

import pytest

from src.reporter import Reporter


@pytest.fixture
def rep():
    from src.config import ConfigManager
    return Reporter(ConfigManager())


def _mk_health_alert(i):
    return {"time": "2026-07-04 12:00", "rule": f"rule-{i}", "status": "warning",
            "details": "detail"}


def test_footer_present_when_section_truncated(rep):
    for i in range(5):
        rep.add_health_alert(_mk_health_alert(i))
    msg = rep._build_line_message("subj", lang="en")
    assert "3 more" in msg  # 5 alerts, 2 shown, 3 truncated


def test_no_footer_when_section_fits(rep):
    rep.add_health_alert(_mk_health_alert(0))
    msg = rep._build_line_message("subj", lang="en")
    assert "more" not in msg.split("rule-0")[-1][:40]


def test_total_length_capped_with_truncation_footer(rep):
    # Two health alerts (only the first 2 are rendered) with long details each,
    # so the assembled digest exceeds the 4500-char total-length cap even
    # though the per-section [:2] cap keeps entry count low.
    for i in range(2):
        alert = _mk_health_alert(i)
        alert["details"] = "x" * 3000
        rep.add_health_alert(alert)
    msg = rep._build_line_message("subj", lang="en")
    assert len(msg) <= 4500
    assert msg.endswith("[Message truncated - see mail or dashboard for full details]")


def test_normal_length_message_unchanged_byte_for_byte(rep):
    # Pin: a normal-length digest must not be touched by the total-length cap.
    rep.add_health_alert(_mk_health_alert(0))
    rep.add_health_alert(_mk_health_alert(1))
    msg = rep._build_line_message("subj", lang="en")
    assert len(msg) <= 4500
    assert not msg.endswith("[Message truncated - see mail or dashboard for full details]")
    assert "rule-0" in msg and "rule-1" in msg
