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


def test_dashboard_js_has_no_plotly_references():
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "static", "js", "dashboard.js"
    )
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Plotly" not in content
    assert "loadDashboardCharts" not in content
    assert "/api/dashboard/chart/" not in content


def test_index_html_has_no_dead_chart_divs():
    html_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "templates", "index.html"
    )
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "dashboard-charts" not in content
    assert "chart-traffic-timeline" not in content
