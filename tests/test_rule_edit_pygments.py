"""Tests for /api/rules/<idx>/highlight pygments endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_client():
    from src.gui import _create_app

    cm = MagicMock()
    cm.config = {
        "settings": {"language": "en"},
        "api": {"url": "https://pce.example.com:8443"},
        "rules": [
            {"type": "traffic", "name": "Test Rule", "threshold": 100},
        ],
        "report": {"output_dir": "/tmp/test-reports"},
        "web_gui": {"secret_key": "test"},
    }
    cm.load = MagicMock()
    app = _create_app(cm)
    app.config["TESTING"] = True
    return app.test_client(), app


class TestRuleHighlightEndpoint:
    def _authed(self, app):
        return patch("flask_login.utils._get_user", return_value=MagicMock(is_authenticated=True))

    def test_valid_index_returns_html(self):
        client, app = _make_client()
        with self._authed(app):
            resp = client.get("/api/rules/0/highlight")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "html" in data
        assert "Test Rule" in data["html"]

    def test_out_of_range_returns_404(self):
        client, app = _make_client()
        with self._authed(app):
            resp = client.get("/api/rules/99/highlight")
        assert resp.status_code == 404

    def test_pygments_css_served(self):
        client, app = _make_client()
        resp = client.get("/static/pygments.css")
        assert resp.status_code == 200
        assert b"highlight" in resp.data or b".hll" in resp.data or b"background" in resp.data

    def test_v2_renders_the_highlight_response_as_text_not_markup(self):
        """Task 11, a CHANGED consumer recorded rather than dropped.

        The legacy assertion was that src/templates/index.html links
        /static/pygments.css, because the legacy rule editor injected this
        endpoint's `html` field as markup. The v2 rules view
        (src/static/js/v2/areas/policy_rules.mjs, AL-06) assigns it to
        `code.textContent` instead — a deliberate consequence of the v2
        no-innerHTML rule (tests/test_csp_compliance.py) — so the operator
        sees the highlighter's tags as literal text and pygments.css is not
        loaded by any template. The endpoint and its stylesheet still work
        (the two tests above), the v2 consumer does not use them for
        styling. Logged in task-11-report.md as a product-bug backlog item.
        """
        from pathlib import Path
        alerting = Path("src/static/js/v2/areas/policy_rules.mjs").read_text(encoding="utf-8")
        assert "/highlight" in alerting, "AL-06 no longer calls the endpoint"
        assert "code.textContent = result.html" in alerting, (
            "AL-06's rendering changed — if it now renders the markup, this "
            "test's premise (and the missing pygments.css link) must be revisited"
        )
        templates = "".join(
            p.read_text(encoding="utf-8")
            for p in sorted(Path("src/templates").glob("*.html"))
        )
        assert "pygments.css" not in templates
