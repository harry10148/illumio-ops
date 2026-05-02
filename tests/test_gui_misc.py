"""Residual GUI tests (split from test_gui_security.py for M9)."""
import json


def _csrf(login_response) -> str:
    """Extract CSRF token from login response JSON (new synchronizer token pattern)."""
    return (login_response.get_json() or {}).get('csrf_token', '')


def test_allowed_report_formats_constant_exists():
    """Phase 5 hardening: format allowlist constant must be defined in gui module."""
    from src import gui
    assert hasattr(gui, '_ALLOWED_REPORT_FORMATS'), (
        "_ALLOWED_REPORT_FORMATS not found; format allowlist must be defined as a module-level constant"
    )
    assert 'html' in gui._ALLOWED_REPORT_FORMATS
    assert 'csv' in gui._ALLOWED_REPORT_FORMATS
    assert 'pdf' in gui._ALLOWED_REPORT_FORMATS
    assert 'xlsx' in gui._ALLOWED_REPORT_FORMATS
    assert 'all' in gui._ALLOWED_REPORT_FORMATS


def test_save_settings_preserves_secret_when_value_is_redaction_placeholder(client, temp_config_file):
    """Bug fix: GET /api/settings redacts secrets to N asterisks. If GUI POSTs
    the unchanged response back, the masked value would overwrite the real
    secret. The save endpoint must drop fields whose value is purely 1-8
    asterisks for secret-named keys."""
    # Pre-populate api credentials
    with open(temp_config_file, "w") as f:
        json.dump({
            "api": {"url": "https://pce.test", "org_id": "1",
                    "key": "real-key-value", "secret": "real-secret-value"},
            "web_gui": {"username": "admin",
                        "password": __import__("src.config", fromlist=["hash_password"]).hash_password("testpass"),
                        "allowed_ips": ["127.0.0.1"], "secret_key": "k"},
            "rules": [],
        }, f)

    login = client.post("/api/login",
                        json={"username": "admin", "password": "testpass"},
                        environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    csrf = _csrf(login)

    # GET shows masked values (1-8 asterisks)
    r = client.get("/api/settings", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    payload = r.get_json()
    assert set(payload["api"]["key"]) == {"*"}
    assert set(payload["api"]["secret"]) == {"*"}

    # POST the masked payload back, untouched (simulating GUI Save without edit)
    r = client.post("/api/settings",
                    json=payload,
                    headers={"X-CSRF-Token": csrf},
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200, r.get_data(as_text=True)

    # Real values must still be there on disk
    with open(temp_config_file) as f:
        saved = json.load(f)
    assert saved["api"]["key"] == "real-key-value"
    assert saved["api"]["secret"] == "real-secret-value"


def test_save_settings_accepts_new_secret_value(client, temp_config_file):
    """When the user actually enters a new secret, it must be saved (not stripped)."""
    with open(temp_config_file, "w") as f:
        json.dump({
            "api": {"url": "https://pce.test", "org_id": "1",
                    "key": "old-key", "secret": "old-secret"},
            "web_gui": {"username": "admin",
                        "password": __import__("src.config", fromlist=["hash_password"]).hash_password("testpass"),
                        "allowed_ips": ["127.0.0.1"], "secret_key": "k"},
            "rules": [],
        }, f)

    login = client.post("/api/login",
                        json={"username": "admin", "password": "testpass"},
                        environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    csrf = _csrf(login)

    r = client.post("/api/settings",
                    json={"api": {"key": "new-real-key", "secret": "new-real-secret"}},
                    headers={"X-CSRF-Token": csrf},
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200

    with open(temp_config_file) as f:
        saved = json.load(f)
    assert saved["api"]["key"] == "new-real-key"
    assert saved["api"]["secret"] == "new-real-secret"
