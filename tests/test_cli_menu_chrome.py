"""Phase 2C Task 1 — the shared chrome every area menu and wizard draws.

menu_screen is the frame (breadcrumb, optional health line, shortcuts);
confirm_box is the destructive-action gate; safe_input's hint can now say
"Current" instead of "Default"; and _wizard_step can redraw the frame above a
step label (DD-1) without changing what the un-migrated callers see.
"""
from __future__ import annotations

import pytest

from src import i18n


@pytest.fixture(autouse=True)
def _english_ui():
    prev = i18n.get_language()
    i18n.set_language("en")
    yield
    i18n.set_language(prev)


def test_menu_screen_draws_breadcrumb_and_shortcuts(monkeypatch):
    import src.cli.menu_chrome as chrome
    panels = []
    monkeypatch.setattr(chrome, "draw_panel",
                        lambda title, lines, **kw: panels.append((title, lines)))
    chrome.menu_screen("System > PCE Cache", ["1. View status"], health="HEALTH-LINE")
    assert len(panels) == 1
    _title, lines = panels[0]
    joined = "\n".join(str(x) for x in lines)
    assert "System > PCE Cache" in joined
    assert "HEALTH-LINE" in joined
    assert "-" in lines
    assert "1. View status" in joined


def test_menu_screen_without_health_omits_the_line(monkeypatch):
    """A menu with no health line must not leave a blank slot where it went."""
    import src.cli.menu_chrome as chrome
    panels = []
    monkeypatch.setattr(chrome, "draw_panel",
                        lambda title, lines, **kw: panels.append((title, lines)))
    chrome.menu_screen("System", ["1. Item"])
    _title, lines = panels[0]
    assert not any(str(x).strip() == "" for x in lines)


def test_menu_screen_with_no_lines_draws_no_separator(monkeypatch):
    """_wizard_step calls menu_screen(path, []) purely for the header."""
    import src.cli.menu_chrome as chrome
    panels = []
    monkeypatch.setattr(chrome, "draw_panel",
                        lambda title, lines, **kw: panels.append((title, lines)))
    chrome.menu_screen("Alerting > Add Event Rule", [])
    _title, lines = panels[0]
    assert "-" not in lines


def test_confirm_box_returns_true_only_on_yes(monkeypatch):
    import src.cli.menu_chrome as chrome
    monkeypatch.setattr(chrome, "draw_panel", lambda *a, **k: None)
    answers = iter(["y", "", "n"])
    monkeypatch.setattr(chrome, "safe_input", lambda *a, **k: next(answers))
    assert chrome.confirm_box("Confirm", ["- rule #3"], "Delete") is True
    assert chrome.confirm_box("Confirm", ["- rule #3"], "Delete") is False
    assert chrome.confirm_box("Confirm", ["- rule #3"], "Delete") is False


def test_confirm_box_none_means_cancel(monkeypatch):
    import src.cli.menu_chrome as chrome
    monkeypatch.setattr(chrome, "draw_panel", lambda *a, **k: None)
    monkeypatch.setattr(chrome, "safe_input", lambda *a, **k: None)
    assert chrome.confirm_box("Confirm", [], "Delete") is False


def test_confirm_box_shows_the_impact_lines(monkeypatch):
    """The point of the box is the consequences; they must reach the panel."""
    import src.cli.menu_chrome as chrome
    panels = []
    monkeypatch.setattr(chrome, "draw_panel",
                        lambda title, lines, **kw: panels.append((title, lines)))
    monkeypatch.setattr(chrome, "safe_input", lambda *a, **k: "n")
    chrome.confirm_box("Delete rule", ["- rule #3 stops firing", "- history is kept"], "Delete")
    _title, lines = panels[0]
    joined = "\n".join(str(x) for x in lines)
    assert "rule #3 stops firing" in joined
    assert "history is kept" in joined
    assert "Delete" in joined


def test_safe_input_hint_is_current_uses_current_prefix(monkeypatch, capsys):
    import builtins
    from src.cli import _render
    monkeypatch.setattr(builtins, "input", lambda prompt="": (print(prompt) or "42"))
    val = _render.safe_input("Time Window", int, hint="10", hint_is_current=True)
    out = capsys.readouterr().out
    assert val == 42
    assert "Current: 10" in out
    assert "Default: 10" not in out


def test_safe_input_default_prefix_unchanged(monkeypatch, capsys):
    import builtins
    from src.cli import _render
    monkeypatch.setattr(builtins, "input", lambda prompt="": (print(prompt) or "42"))
    _render.safe_input("Time Window", int, hint="10")
    assert "Default: 10" in capsys.readouterr().out


def test_wizard_step_with_path_redraws_header(monkeypatch, capsys):
    import src.cli.menus._helpers as helpers
    calls = []
    monkeypatch.setattr("src.cli.menu_chrome.menu_screen",
                        lambda path, lines, **kw: calls.append(path))
    helpers._wizard_step(2, 5, "Select Event Type", path="Alerting > Add Event Rule")
    assert calls == ["Alerting > Add Event Rule"]
    assert f"[{i18n.t('wiz_step')} 2/5] Select Event Type" in capsys.readouterr().out


def test_wizard_step_without_path_keeps_legacy_behavior(monkeypatch, capsys):
    import src.cli.menus._helpers as helpers
    monkeypatch.setattr("src.cli.menu_chrome.menu_screen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not redraw")))
    helpers._wizard_step(1, 4, "Basic Setup")
    assert f"[{i18n.t('wiz_step')} 1/4] Basic Setup" in capsys.readouterr().out


def test_confirm_box_accepts_the_localized_affirmative(monkeypatch):
    """zh operators type 是, not y — and the audit forbids that literal in source."""
    import src.cli.menu_chrome as chrome
    i18n.set_language("zh_TW")
    monkeypatch.setattr(chrome, "draw_panel", lambda *a, **k: None)
    monkeypatch.setattr(chrome, "safe_input", lambda *a, **k: "是")
    assert chrome.confirm_box("確認", ["- 規則 #3"], "刪除") is True


def test_confirm_box_still_accepts_plain_y_in_any_language(monkeypatch):
    import src.cli.menu_chrome as chrome
    i18n.set_language("zh_TW")
    monkeypatch.setattr(chrome, "draw_panel", lambda *a, **k: None)
    monkeypatch.setattr(chrome, "safe_input", lambda *a, **k: "Y")
    assert chrome.confirm_box("確認", [], "刪除") is True
