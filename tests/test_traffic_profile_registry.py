"""Phase 1: profile-aware module registry."""
from src.report.analysis import get_traffic_modules, PROFILES


def _ids(profile=None):
    return {mod_id for mod_id, _fn, _adapter in get_traffic_modules(profile)}


def test_profiles_constant():
    assert PROFILES == ("traffic", "security_risk", "network_inventory")


def test_traffic_profile_runs_only_lightweight_modules():
    assert _ids("traffic") == {"mod01", "mod02", "mod08", "mod09", "mod11"}


def test_security_risk_profile_unchanged_full_set():
    # Phase 1 keeps the existing behavior: security/inventory run everything.
    full = {"mod01", "mod02", "mod03", "mod04", "mod06", "mod07", "mod08",
            "mod09", "mod11", "mod13", "mod14", "mod15",
            "mod_draft_summary", "mod_ringfence"}
    assert _ids("security_risk") == full
    assert _ids("network_inventory") == full


def test_none_profile_returns_all_modules():
    assert _ids(None) == _ids("security_risk")


def test_unknown_profile_raises():
    import pytest
    with pytest.raises(ValueError):
        get_traffic_modules("bogus")
