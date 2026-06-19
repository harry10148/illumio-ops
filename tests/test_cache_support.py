from types import SimpleNamespace
from unittest.mock import patch

from src.report.cache_support import resolve_data_source, cache_available


# ── resolve_data_source ──────────────────────────────────────────────────────
def test_modes_when_cache_available():
    assert resolve_data_source("hybrid", True) == (True, False, None)
    assert resolve_data_source("live", True) == (False, False, None)
    assert resolve_data_source("cache-only", True) == (True, True, None)


def test_default_and_aliases():
    assert resolve_data_source(None, True) == (True, False, None)       # default hybrid
    assert resolve_data_source("", True) == (True, False, None)
    assert resolve_data_source("cache", True) == (True, False, None)    # alias -> hybrid
    assert resolve_data_source("no-cache", True) == (False, False, None)  # alias -> live
    assert resolve_data_source("api", True) == (False, False, None)     # alias -> live


def test_cache_unavailable_falls_back_with_warning():
    uc, clip, warn = resolve_data_source("hybrid", False)
    assert (uc, clip) == (False, False) and warn and "live" in warn.lower()
    uc, clip, warn = resolve_data_source("cache-only", False)
    assert (uc, clip) == (False, False) and warn and "cache-only" in warn.lower()
    # live never warns
    assert resolve_data_source("live", False) == (False, False, None)


def test_unknown_value_defaults_hybrid():
    assert resolve_data_source("bogus", True) == (True, False, None)


# ── cache_available ──────────────────────────────────────────────────────────
def _cm(enabled):
    return SimpleNamespace(models=SimpleNamespace(pce_cache=SimpleNamespace(enabled=enabled)))


def test_cache_unavailable_when_disabled():
    assert cache_available(_cm(False)) is False


def test_cache_unavailable_when_reader_none():
    with patch("src.main._make_cache_reader", return_value=None):
        assert cache_available(_cm(True)) is False


def test_cache_unavailable_when_empty():
    reader = SimpleNamespace(earliest_data_timestamp=lambda src: None)
    with patch("src.main._make_cache_reader", return_value=reader):
        assert cache_available(_cm(True)) is False


def test_cache_available_when_has_data():
    reader = SimpleNamespace(earliest_data_timestamp=lambda src: "2026-06-01T00:00:00Z")
    with patch("src.main._make_cache_reader", return_value=reader):
        assert cache_available(_cm(True)) is True
