"""Locks in the removal of the dead /api/dashboard/chart/<id> plotly path.

The endpoint's JSON response was only ever fed to `Plotly.react()` behind a
`typeof Plotly !== 'undefined'` guard, and plotly.js was never loaded by the
frontend — so the branch was dead code. Task E1 removes the endpoint, its
plotly-only helpers, and the frontend caller together.
"""
import json, os, tempfile
import pytest
from src.config import ConfigManager


@pytest.fixture
def client(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    with open(path, "w") as f:
        json.dump({"web_gui": {"username": "admin", "password": "pw",
                               "secret_key": "s", "allowed_ips": ["127.0.0.1"]},
                   "pce_cache": {"enabled": True, "db_path": str(tmp_path / "c.sqlite")}}, f)
    cm = ConfigManager(config_file=path)
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True; app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        yield c
    os.unlink(path)


def test_chart_endpoint_no_longer_registered(client):
    r = client.get("/api/dashboard/chart/ven_status",
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 404


def test_helpers_module_imports_without_plotly_and_drops_chart_builders():
    import src.gui._helpers as helpers

    for name in (
        "_spec_to_plotly_figure", "_load_state_for_charts",
        "_build_traffic_timeline_spec", "_build_policy_decisions_spec",
        "_build_ven_status_spec", "_build_rule_hits_spec",
    ):
        assert not hasattr(helpers, name), f"{name} should have been removed"


def test_frontend_has_no_plotly_references():
    """Task 11: the two files this used to scan (src/static/js/dashboard.js,
    src/templates/index.html) were deleted with the legacy frontend, so the
    same scan runs over what replaced them — the whole v2 tree and both
    remaining templates. Broader than the original, not narrower."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    blob = "".join(
        p.read_text(encoding="utf-8")
        for p in sorted((root / "src" / "static" / "js" / "v2").rglob("*.mjs"))
        + sorted((root / "src" / "static" / "js" / "v2").rglob("*.js"))
        + sorted((root / "src" / "templates").glob("*.html"))
    )
    assert "Plotly" not in blob
    assert "loadDashboardCharts" not in blob
    assert "/api/dashboard/chart/" not in blob
    assert "dashboard-charts" not in blob
    assert "chart-traffic-timeline" not in blob
