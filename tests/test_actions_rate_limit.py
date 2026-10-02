"""Rate-limit contract tests for heavy actions/dashboard endpoints (T2.5 / M-5).

These tests verify that per-endpoint @limiter.limit decorators actually trigger
429 responses after the configured threshold is crossed. They use an in-memory
limiter (storage_uri="memory://") so each fresh app instance starts clean.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def client(tmp_path):
    """Build a test Flask app and return an authenticated client + csrf_token."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {
            "username": "illumio",
            "password": "illumio",
            "secret_key": "",
            "allowed_ips": [],
        },
    }), encoding="utf-8")
    from src.config import ConfigManager
    from src.gui import build_app

    cm = ConfigManager(str(cfg))
    app = build_app(cm)
    app.config["TESTING"] = True

    c = app.test_client()
    r = c.post("/api/login", json={"username": "illumio", "password": "illumio"})
    assert r.status_code == 200, f"Login failed: {r.data!r}"
    csrf_token = (r.get_json() or {}).get("csrf_token", "")
    return c, csrf_token


def _exhaust(client, csrf_token, url, limit, body=None):
    """POST `url` up to `limit + 2` times; return the last status code seen."""
    headers = {"X-CSRFToken": csrf_token}
    last = None
    for _ in range(limit + 2):
        r = client.post(url, json=body or {}, headers=headers)
        last = r.status_code
        if last == 429:
            return last
    return last


def test_actions_run_rate_limit(client):
    """/api/actions/run should return 429 after 10 requests per hour."""
    c, tok = client
    # The endpoint calls real Analyzer/Reporter — it will fail with 500 (missing
    # PCE) but the limiter counter increments on every request regardless.
    last = _exhaust(c, tok, "/api/actions/run", limit=10)
    assert last == 429, f"Expected 429 after 10 calls, got {last}"


def test_dashboard_top10_rate_limit(client):
    """/api/dashboard/top10 should return 429 after 30 requests per hour."""
    c, tok = client
    last = _exhaust(c, tok, "/api/dashboard/top10", limit=30)
    assert last == 429, f"Expected 429 after 30 calls, got {last}"
