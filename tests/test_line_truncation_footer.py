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


_TRUNCATION_FOOTER = "[Message truncated - see mail or dashboard for full details]"


@pytest.fixture
def rep():
    from src.config import ConfigManager
    from src.i18n import set_language
    cm = ConfigManager()
    cm.config.setdefault("settings", {})["language"] = "en"
    set_language("en")
    return Reporter(cm)


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
    assert msg.endswith(_TRUNCATION_FOOTER)


@pytest.mark.parametrize("cap", [-10, 0])
def test_non_positive_cap_returns_empty_message(rep, cap):
    rep.add_health_alert(_mk_health_alert(0))

    assert rep._build_line_message("subj", lang="en", cap=cap) == ""


@pytest.mark.parametrize("cap", [1, 10, 30, 60])  # 60 == len(_TRUNCATION_FOOTER)
def test_cap_no_larger_than_footer_returns_footer_prefix(rep, cap):
    rep.add_health_alert(_mk_health_alert(0))

    msg = rep._build_line_message("subj", lang="en", cap=cap)

    assert msg == _TRUNCATION_FOOTER[:cap]
    assert len(msg) <= cap


def test_normal_length_message_unchanged_byte_for_byte(rep):
    # Pin: a normal-length digest must not be touched by the total-length cap.
    rep._now_str = lambda: "2026-08-30 03:30 (UTC+08)"
    rep.add_health_alert(_mk_health_alert(0))
    rep.add_health_alert(_mk_health_alert(1))
    msg = rep._build_line_message("subj", lang="en")
    uncapped = rep._build_line_message("subj", lang="en", cap=None)
    assert len(msg) <= 4500
    assert msg == uncapped
    assert not msg.endswith(_TRUNCATION_FOOTER)
    assert "rule-0" in msg and "rule-1" in msg


def test_long_event_description_preserves_complete_console_link(rep):
    rep.cm.config["api"] = {
        "url": "https://saas-api.example.invalid/api/v2",
        "deployment_type": "saas",
        "console_url": "",
    }
    rep.add_event_alert({
        "rule": "Suspicious",
        "desc": "d" * 4041,
        "severity": "info",
        "count": 1,
        "time": "t",
        "raw_data": [{
            "href": "/orgs/7/events/evt-normal",
            "event_type": "agent.tampering",
            "timestamp": "t",
        }],
    })

    msg = rep._build_line_message("Event alert", lang="en")

    assert len(msg) <= 4500
    assert msg.endswith(_TRUNCATION_FOOTER)
    assert "https://console.illum.io/#/events/evt-normal" in msg
    assert "PCE：https://console.illum.io/\n" not in msg


def test_line_event_link_drops_fake_userinfo_from_hostile_href(rep):
    rep.cm.config["api"] = {
        "url": "https://saas-api.example.invalid/api/v2",
        "deployment_type": "saas",
        "console_url": "",
    }
    rep.add_event_alert({
        "rule": "Suspicious",
        "desc": "d",
        "severity": "info",
        "count": 1,
        "time": "t",
        "raw_data": [{
            "href": "https://fake-user:fake-pass@evil.invalid/orgs/7/events/evt-line",
            "event_type": "agent.tampering",
            "timestamp": "t",
        }],
    })

    msg = rep._build_line_message("Event alert", lang="en")

    assert "https://console.illum.io/#/events/evt-line" in msg
    assert "fake-user" not in msg
