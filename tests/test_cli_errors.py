"""Test error formatting and did-you-mean."""
import pytest

from src.cli._errors import format_error, suggest_command


def test_format_error_basic():
    msg = format_error(
        cause="Failed to connect to PCE",
        recovery="Check PCE_HOST in config.json and confirm network reachability.",
    )
    assert "Failed to connect to PCE" in msg
    assert "Try:" in msg
    assert "Check PCE_HOST" in msg


def test_format_error_with_did_you_mean():
    msg = format_error(
        cause="Unknown command 'lst'",
        recovery="Run 'illumio-ops --help' to see available commands.",
        did_you_mean="list",
    )
    assert "Did you mean: list?" in msg


def test_suggest_command_close_match():
    suggestion = suggest_command('lst', ['list', 'show', 'create'])
    assert suggestion == 'list'


def test_suggest_command_no_match():
    suggestion = suggest_command('xyzzy', ['list', 'show', 'create'])
    assert suggestion is None
