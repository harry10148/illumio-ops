"""Alert channels + plugin metadata tests (split from test_gui_security.py for M9)."""
import json
import os
import tempfile

from src.alerts.metadata import FieldMeta, PluginMeta
from src.config import ConfigManager
from src.gui import build_app as _create_app


def _csrf(login_response) -> str:
    """Extract CSRF token from login response JSON (new synchronizer token pattern)."""
    return (login_response.get_json() or {}).get('csrf_token', '')


def test_alert_plugins_endpoint_returns_metadata(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    response = client.get('/api/alert-plugins', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200
    assert response.json["plugins"]["mail"]["display_name"] == "Email (SMTP)"
    assert any(field["key"] == "sender" for field in response.json["plugins"]["mail"]["fields"])
    assert response.json["plugins"]["line"]["fields"][0]["secret"] is True
    assert any(field["key"] == "smtp.enable_tls" for field in response.json["plugins"]["mail"]["fields"])
    recipients = next(field for field in response.json["plugins"]["mail"]["fields"] if field["key"] == "recipients")
    assert recipients["input_type"] == "list"
    assert recipients["value_type"] == "string_list"
    smtp_port = next(field for field in response.json["plugins"]["mail"]["fields"] if field["key"] == "smtp.port")
    assert smtp_port["value_type"] == "integer"


def test_test_alert_endpoint_supports_single_channel(client, monkeypatch):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    def fake_send_alerts(self, force_test=False, channels=None):
        assert force_test is True
        assert channels == ["mail"]
        return [{"channel": "mail", "status": "success", "target": "ops@example.com"}]

    monkeypatch.setattr("src.reporter.Reporter.send_alerts", fake_send_alerts)

    response = client.post(
        '/api/actions/test-alert',
        json={"channel": "mail"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["results"][0]["channel"] == "mail"


def test_test_alert_endpoint_rejects_unknown_channel(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    response = client.post(
        '/api/actions/test-alert',
        json={"channel": "pagerduty"},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 400
    assert response.json["ok"] is False


def test_debug_endpoint_returns_captured_output(client, monkeypatch):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    csrf_token = _csrf(login)

    def fake_run_debug_mode(self, mins=None, pd_sel=None, interactive=None):
        assert interactive is False
        print("debug-output-line")

    monkeypatch.setattr("src.analyzer.Analyzer.run_debug_mode", fake_run_debug_mode)

    response = client.post(
        '/api/actions/debug',
        json={"mins": 30, "pd_sel": 3},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-CSRF-Token': csrf_token},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert "debug-output-line" in response.json["output"]


def test_status_includes_alert_channel_health(app_persistent):
    client = app_persistent.test_client()
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200

    response = client.get('/api/status', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 200
    channels = response.json["alert_channels"]
    line = next(item for item in channels if item["name"] == "line")
    assert line["configured"] is False
    assert "alerts.line_channel_access_token" in line["missing_required"]
    assert line["enabled"] is False


def test_settings_support_dynamic_plugin_roots(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                "api": {"url": "test", "key": "test", "secret": "test", "org_id": "1"},
                "rules": [],
                "web_gui": {
                    "username": "admin",
                    "password": "testpass",
                    "allowed_ips": ["127.0.0.1"],
                    "secret_key": "test-secret",
                },
            }, f)

        import src.gui as gui_module
        gui_module.PLUGIN_METADATA["dummy_settings_plugin"] = PluginMeta(
            name="dummy_settings_plugin",
            display_name="Dummy Plugin",
            description="Dynamic root config test.",
            fields={
                "dummy_plugin.token": FieldMeta(label="Token", required=True, secret=True),
                "dummy_plugin.retries": FieldMeta(label="Retries", required=True, input_type="number", value_type="integer"),
                "dummy_plugin.targets": FieldMeta(label="Targets", input_type="list", value_type="string_list"),
            },
        )

        cm = ConfigManager(config_file=path)
        cm.load()
        app = _create_app(cm, persistent_mode=True)
        app.config.update({"TESTING": True})
        client = app.test_client()

        login = client.post('/api/login', json={
            "username": "admin",
            "password": "testpass"
        }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert login.status_code == 200

        csrf_token = _csrf(login)

        save_response = client.post(
            '/api/settings',
            json={"dummy_plugin": {"token": "abc123", "retries": 0, "targets": ["ops", "soc"]}},
            environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
            headers={'X-CSRF-Token': csrf_token},
        )
        assert save_response.status_code == 200
        assert save_response.json["ok"] is True

        get_response = client.get('/api/settings', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert get_response.status_code == 200
        # "token" is a secret field — GET response redacts it; verify via __set sentinel
        assert get_response.json["dummy_plugin"]["token__set"] is True
        assert get_response.json["dummy_plugin"]["token"] != "abc123"
        assert get_response.json["dummy_plugin"]["retries"] == 0
        assert get_response.json["dummy_plugin"]["targets"] == ["ops", "soc"]

        status_response = client.get('/api/status', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        assert status_response.status_code == 200
        dummy = next(item for item in status_response.json["alert_channels"] if item["name"] == "dummy_settings_plugin")
        assert dummy["configured"] is True
        assert dummy["missing_required"] == []
    finally:
        import src.gui as gui_module
        gui_module.PLUGIN_METADATA.pop("dummy_settings_plugin", None)
        os.unlink(path)
