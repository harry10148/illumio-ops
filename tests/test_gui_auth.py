"""Login/logout/CSRF/redirect tests (split from test_gui_security.py for M9)."""
import json


def test_redirect_unauthenticated(client):
    response = client.get('/')
    assert response.status_code == 302
    assert response.location.endswith('/login')

def test_login_success(client):
    response = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    })
    assert response.status_code == 200
    assert response.json.get("ok") is True

    # Should now be able to access root
    response = client.get('/')
    assert response.status_code == 200

def test_login_fail(client):
    response = client.post('/api/login', json={
        "username": "admin",
        "password": "wrongpassword"
    })
    assert response.status_code == 401
    assert response.json.get("ok") is False

def test_api_csrf_failure_returns_refreshable_json(client):
    login = client.post('/api/login', json={
        "username": "admin",
        "password": "testpass"
    })
    assert login.status_code == 200

    response = client.post(
        "/api/report-schedules/123/run",
        headers={"X-CSRF-Token": "expired-token"},
    )

    assert response.status_code == 400
    assert response.is_json
    body = response.get_json()
    assert body["ok"] is False
    assert body["code"] == "csrf_error"
    assert body["csrf_token"]

def test_frontend_api_helper_refreshes_expired_csrf_token():
    with open("src/static/js/utils.js", encoding="utf-8") as f:
        js = f.read()

    assert "csrf_error" in js
    assert "/api/csrf-token" in js
    assert "_setCsrfToken" in js


def test_login_default_install_does_not_force_change():
    """Forced first-login password change is DISABLED (operator request): a
    default install logs in with illumio/illumio and /api/login reports
    must_change_password=False (no inline change-password gate)."""
    import json, tempfile, os
    from src.config import ConfigManager
    from src.gui import build_app as _create_app
    d = tempfile.mkdtemp()
    cfg = os.path.join(d, "config.json")
    with open(cfg, "w") as f:
        json.dump({"api": {"url": "https://x", "org_id": "1", "key": "k", "secret": "s"}}, f)
    cm = ConfigManager(cfg, alerts_file=os.path.join(d, "alerts.json"))
    app = _create_app(cm)
    app.config["TESTING"] = True
    c = app.test_client()
    r = c.post("/api/login", json={"username": "illumio", "password": "illumio"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["must_change_password"] is False
    assert "csrf_token" in body


def test_login_then_change_password_flow_clears_must_change(temp_config_file):
    """End-to-end gate flow with an EXPLICITLY-armed must_change gate (first-boot
    auto-arming is disabled by operator request, so the admin arms it manually):
    login with illumio/illumio → POST /api/security with new_password →
    must_change_password and _initial_password are cleared and dashboard calls work."""
    import os
    from src.config import ConfigManager, hash_password
    from src.gui import build_app as _create_app
    # Explicitly arm the must-change gate (no longer auto-armed on first boot).
    with open(temp_config_file, "w") as f:
        json.dump({
            "api": {"url": "https://x", "org_id": "1", "key": "k", "secret": "s"},
            "rules": [],
            "web_gui": {
                "username": "illumio",
                "password": hash_password("illumio"),
                "_initial_password": "illumio",
                "must_change_password": True,
            },
        }, f)
    cm = ConfigManager(temp_config_file, alerts_file=temp_config_file + ".alerts")
    assert cm.config["web_gui"]["_initial_password"] == "illumio"
    assert cm.config["web_gui"]["must_change_password"] is True

    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True
    c = app.test_client()

    # Step 1: login
    r = c.post("/api/login",
               json={"username": "illumio", "password": "illumio"},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["must_change_password"] is True
    csrf = body["csrf_token"]

    # Step 2: a protected endpoint should be 423 BEFORE password change
    r2 = c.get("/api/status", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r2.status_code == 423
    assert r2.get_json().get("error") == "must_change_password"

    # Step 3: change password via /api/security
    r3 = c.post("/api/security",
                json={"old_password": "illumio",
                      "new_password": "n3w-stronger-pw",
                      "confirm_password": "n3w-stronger-pw"},
                headers={"X-CSRF-Token": csrf},
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r3.status_code == 200, r3.get_data(as_text=True)
    assert r3.get_json().get("ok") is True

    # Step 4: must_change flags are cleared
    assert "must_change_password" not in cm.config["web_gui"]
    assert "_initial_password" not in cm.config["web_gui"]

    # Step 5: protected endpoints now succeed (no 423)
    r4 = c.get("/api/status", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r4.status_code == 200
