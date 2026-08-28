"""CLI wizard weekly day_of_week validation (2026-08-28 backlog #1).

report_scheduler.py compares a weekly schedule's day_of_week against
strftime("%A").lower() — i.e. monday..sunday exactly. The wizard used to
accept any string via `_ask(..., cast=str)` with no choice set, so an
abbreviation like "mon" stored happily and the schedule never fired, with
no signal at all.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import i18n
import src.cli.menus.report_schedule as rs


@pytest.fixture(autouse=True)
def _english_ui():
    previous = i18n.get_language()
    i18n.set_language("en")
    try:
        yield
    finally:
        i18n.set_language(previous)


def _make_cm():
    saved = []
    cm = SimpleNamespace(config={"report": {"output_dir": "reports/"}})
    cm.add_report_schedule = lambda sched: saved.append(sched)
    return cm, saved


def _run_wizard(monkeypatch, answers, confirm_inputs=("", "")):
    """answers feeds rs.safe_input in call order; confirm_inputs feeds the
    plain builtins.input() calls used by _wizard_confirm + the final
    press-enter pause."""
    queue = iter(answers)
    monkeypatch.setattr(rs.os, "system", lambda *_a, **_k: None)
    monkeypatch.setattr(rs, "draw_panel", lambda *_a, **_k: None)
    monkeypatch.setattr(rs, "safe_input", lambda *_a, **_k: next(queue))
    confirms = iter(confirm_inputs)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(confirms))


def test_weekly_wizard_reasks_on_abbreviated_day(monkeypatch, capsys):
    """"mon" must be rejected and re-asked; "tuesday" is accepted and stored."""
    cm, saved = _make_cm()
    answers = [
        "x",          # name
        "",           # report_type -> default (traffic)
        "2",          # schedule_type -> weekly
        "mon",        # day_of_week: invalid, must be re-asked
        "tuesday",    # day_of_week: valid
        "",           # hour -> default
        "",           # minute -> default
        "",           # lookback_days -> default
        "",           # format -> default
        "",           # email -> default (N)
    ]
    _run_wizard(monkeypatch, answers)

    rs._add_report_schedule_wizard(cm)

    assert len(saved) == 1
    assert saved[0]["day_of_week"] == "tuesday"
    assert "Invalid selection" in capsys.readouterr().out


def test_weekly_wizard_accepts_full_lowercase_day_without_reask(monkeypatch):
    cm, saved = _make_cm()
    answers = [
        "x", "", "2", "friday", "", "", "", "", "",
    ]
    _run_wizard(monkeypatch, answers)

    rs._add_report_schedule_wizard(cm)

    assert len(saved) == 1
    assert saved[0]["day_of_week"] == "friday"
