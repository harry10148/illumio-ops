"""Regression tests for rule scheduler CLI input handling."""
from unittest.mock import MagicMock


def test_schedule_management_blank_enter_does_not_exit(monkeypatch):
    from src.rule_scheduler_cli import _RuleSchedulerCLI

    cli = _RuleSchedulerCLI(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    list_calls = []
    answers = iter(["", "q"])

    monkeypatch.setattr(cli, "_list_grouped", lambda: list_calls.append("listed"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    cli.schedule_management_ui()

    assert len(list_calls) == 2


# ── Phase 2C Task 10: chrome + a status row ─────────────────────────────────

def test_scheduler_menu_renders_inside_panel_with_status(monkeypatch):
    """§3.3.4b: the menu shows whether the scheduler is on and how many
    schedules exist, so an operator does not have to open Settings to find out."""
    from types import SimpleNamespace
    import src.rule_scheduler_cli as rsc
    screens = []
    monkeypatch.setattr(rsc, "menu_screen",
                        lambda path, lines, **kw: screens.append((path, lines)))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "0")
    cli = rsc._RuleSchedulerCLI.__new__(rsc._RuleSchedulerCLI)
    cli.db = SimpleNamespace(db={"s1": {}, "s2": {}})
    cli.api = None
    cli.engine = None
    cli.cm = SimpleNamespace(config={"rule_scheduler": {"enabled": True,
                                                       "check_interval_seconds": 300}})
    cli.run()
    path, lines = screens[0]
    joined = "\n".join(str(x) for x in lines)
    assert "Rule Scheduler" in path or "rule" in path.lower()
    assert "ON" in joined
    assert "2" in joined            # schedule count


def test_scheduler_menu_survives_unreadable_status(monkeypatch):
    from types import SimpleNamespace
    import src.rule_scheduler_cli as rsc
    screens = []
    monkeypatch.setattr(rsc, "menu_screen",
                        lambda path, lines, **kw: screens.append(lines))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "0")
    cli = rsc._RuleSchedulerCLI.__new__(rsc._RuleSchedulerCLI)
    cli.db = None                       # no schedule store at all
    cli.api = None
    cli.engine = None
    cli.cm = SimpleNamespace(config={})
    cli.run()
    assert screens
