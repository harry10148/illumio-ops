"""Test that Console respects TTY status and NO_COLOR."""
import os
import pytest

from src.cli import _render


def _reset_singleton():
    _render._CONSOLE_SINGLETON = None


@pytest.fixture(autouse=True)
def reset():
    _reset_singleton()
    saved = {k: os.environ.get(k) for k in ('NO_COLOR', 'TERM')}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _reset_singleton()


def test_console_no_color_when_NO_COLOR_env_set():
    os.environ['NO_COLOR'] = '1'
    c = _render._get_console()
    assert c.no_color is True or c.color_system is None


def test_console_no_color_when_term_dumb():
    os.environ.pop('NO_COLOR', None)
    os.environ['TERM'] = 'dumb'
    c = _render._get_console()
    assert c.no_color is True or c.color_system is None


def test_console_not_terminal_when_stdout_not_tty(monkeypatch):
    os.environ.pop('NO_COLOR', None)
    os.environ.pop('TERM', None)
    monkeypatch.setattr(_render, '_stdout_is_tty', lambda: False)
    c = _render._get_console()
    assert c.is_terminal is False
