"""Phase 2C Task 2 — the five-lamp health line the area menus carry.

Same sources as the GUI dashboard overview, so the CLI and the web UI cannot
disagree about whether the appliance is healthy. Every source is wrapped:
a missing flask, an unreadable state file or a broken helper turns its lamp
neutral and never propagates — the line is an auxiliary signal, and a menu that
refuses to draw because a health probe failed is worse than a grey lamp.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import i18n


@pytest.fixture(autouse=True)
def _english_ui():
    prev = i18n.get_language()
    i18n.set_language("en")
    yield
    i18n.set_language(prev)


def _cm():
    return SimpleNamespace(config={"settings": {"timezone": "UTC+8"}})


def test_all_sources_ok_renders_green_line(monkeypatch):
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [{"level": "ok"}] * 14)
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {
        "cache_lag": [{"source": "events", "lag_s": 174, "level": "ok"}],
        "siem_success_1h": 100.0, "dlq": 0, "verdict": "ok"})
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {
        "event_poll_status": "ok", "consecutive_failures": 0})
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [
        {"enabled": True, "configured": True, "last_status": "success"},
        {"enabled": True, "configured": True, "last_status": ""},
        {"enabled": False, "configured": False, "last_status": ""},
        {"enabled": False, "configured": False, "last_status": ""},
        {"enabled": False, "configured": False, "last_status": ""}])
    s = hl.build_health_summary(_cm())
    assert s["jobs"]["tone"] == "ok" and s["jobs"]["text"] == "Jobs 14/14"
    assert s["pce"]["tone"] == "ok"
    assert s["lag"]["text"] == "Lag 3m"
    assert s["siem"]["text"] == "SIEM 100%"
    assert s["chan"]["text"] == "Chan 2/5"
    assert "UTC+8" in hl.build_health_line(_cm())


def test_pce_consecutive_failures_escalates_to_crit(monkeypatch):
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {
        "event_poll_status": "ok", "consecutive_failures": 2})
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [])
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {"verdict": "ok"})
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [])
    assert hl.build_health_summary(_cm())["pce"]["tone"] == "crit"


def test_jobs_takes_the_worst_level(monkeypatch):
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [
        {"level": "ok"}, {"level": "warn"}, {"level": "error"}])
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {"verdict": "ok"})
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {})
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [])
    s = hl.build_health_summary(_cm())
    assert s["jobs"]["tone"] == "crit"
    assert s["jobs"]["text"] == "Jobs 1/3"


def test_siem_dlq_escalates_to_at_least_warn(monkeypatch):
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {
        "cache_lag": [], "siem_success_1h": 100.0, "dlq": 3, "verdict": "ok"})
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [])
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {})
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [])
    assert hl.build_health_summary(_cm())["siem"]["tone"] in ("warn", "crit")


def test_siem_below_95_percent_escalates(monkeypatch):
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {
        "cache_lag": [], "siem_success_1h": 94.0, "dlq": 0, "verdict": "ok"})
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [])
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {})
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [])
    assert hl.build_health_summary(_cm())["siem"]["tone"] in ("warn", "crit")


def test_channel_with_failed_last_status_is_crit(monkeypatch):
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [
        {"enabled": True, "configured": True, "last_status": "failed"}])
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [])
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {"verdict": "ok"})
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {})
    assert hl.build_health_summary(_cm())["chan"]["tone"] == "crit"


def test_no_live_channel_is_neutral_not_ok(monkeypatch):
    """Nothing configured is not the same as everything working."""
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [
        {"enabled": False, "configured": False, "last_status": ""}])
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [])
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {"verdict": "ok"})
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {})
    assert hl.build_health_summary(_cm())["chan"]["tone"] == "neutral"


@pytest.mark.parametrize(("seconds", "expected"), [
    (0, "0s"), (59, "59s"), (60, "1m"), (174, "3m"), (3599, "60m"),
    (3600, "1h"), (7300, "2h"),
])
def test_dur_rounding_matches_the_mockup(seconds, expected):
    import src.cli.health_line as hl
    assert hl._dur(seconds) == expected


def test_source_failure_degrades_to_neutral_not_raise(monkeypatch):
    import src.cli.health_line as hl

    def _boom(*a, **k):
        raise RuntimeError("flask missing")

    monkeypatch.setattr(hl, "_load_job_health_rows", _boom)
    monkeypatch.setattr(hl, "_load_pipeline", _boom)
    monkeypatch.setattr(hl, "_load_pce_stats", _boom)
    monkeypatch.setattr(hl, "_load_alert_channels", _boom)
    s = hl.build_health_summary(_cm())
    assert s["jobs"]["tone"] == "neutral"
    assert s["pce"]["tone"] == "neutral"
    assert s["siem"]["tone"] == "neutral"
    assert s["chan"]["tone"] == "neutral"
    assert isinstance(hl.build_health_line(_cm()), str)


def test_health_line_survives_a_broken_config(monkeypatch):
    """A menu must still draw when the clock helper cannot read the config."""
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [])
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {})
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {})
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [])
    assert isinstance(hl.build_health_line(object()), str)


def test_line_has_no_stray_escape_when_colours_are_off(monkeypatch):
    """Colors go empty off-TTY while ENDC stays a literal reset — pairing them
    unconditionally leaves "\\x1b[0m" scattered through piped output."""
    import src.cli.health_line as hl
    monkeypatch.setattr(hl.Colors, "GREEN", "", raising=False)
    monkeypatch.setattr(hl.Colors, "WARNING", "", raising=False)
    monkeypatch.setattr(hl.Colors, "FAIL", "", raising=False)
    monkeypatch.setattr(hl.Colors, "DARK_GRAY", "", raising=False)
    monkeypatch.setattr(hl, "_TONE_COLOR", {k: "" for k in ("ok", "warn", "crit", "neutral")})
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [{"level": "ok"}])
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {"verdict": "ok"})
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {"event_poll_status": "ok"})
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [])
    assert "\x1b" not in hl.build_health_line(_cm())


def test_pce_failure_count_is_readable_as_a_count(monkeypatch):
    """"PCE 410" reads as an HTTP status; it is a count of failed cycles."""
    import src.cli.health_line as hl
    monkeypatch.setattr(hl, "_load_pce_stats", lambda: {
        "event_poll_status": "error", "consecutive_failures": 410})
    monkeypatch.setattr(hl, "_load_job_health_rows", lambda: [])
    monkeypatch.setattr(hl, "_load_pipeline", lambda cm: {"verdict": "ok"})
    monkeypatch.setattr(hl, "_load_alert_channels", lambda cm: [])
    assert hl.build_health_summary(_cm())["pce"]["text"] == "PCE x410"
