"""Guard: the autouse fixture in conftest keeps every test off the real logs/alerts.sqlite."""
from __future__ import annotations

import hashlib
import os
from unittest.mock import patch

import src.alerts.store as store_mod
from src.config import ROOT_DIR

REAL = os.path.join(ROOT_DIR, "logs", "alerts.sqlite")


def _fingerprint():
    if not os.path.exists(REAL):
        return None
    with open(REAL, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def test_default_path_is_redirected_during_tests(_isolate_alert_store):
    # via the module attribute: the fixture patches the name the store reads at call time
    assert store_mod.default_alerts_db_path() == _isolate_alert_store
    assert not store_mod.default_alerts_db_path().startswith(ROOT_DIR)


def test_real_dispatch_does_not_touch_the_product_database(monkeypatch, tmp_path):
    import src.reporter as reporter_mod
    from src.reporter import Reporter
    from src.config import ConfigManager
    monkeypatch.setattr(reporter_mod, "STATE_FILE", str(tmp_path / "state.json"))
    before = _fingerprint()
    cm = ConfigManager()
    cm.config["alerts"]["active"] = ["webhook"]
    cm.config["alerts"]["webhook_url"] = "https://hooks.example.com/x"
    r = Reporter(cm)
    r.add_health_alert({"time": "t", "rule": "ISOLATION-GUARD", "status": "503", "details": "d"})

    def _ok(self, reporter, subject, *, lang="en"):
        return {"channel": "webhook", "status": "success", "target": "https://hooks.example.com/...", "error": ""}

    with patch("src.alerts.plugins.WebhookAlertPlugin.send", _ok):
        r.send_alerts()
    assert _fingerprint() == before
    from src.alerts.store import AlertStore
    assert AlertStore().list()["total"] == 1     # it went to the tmp store instead
