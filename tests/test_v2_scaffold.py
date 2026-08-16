"""The v2 shell is the app's only GUI (Phase 2A Task 11 switchover).

Task 1 created these tests against a flag-gated `/v2` preview route. Task 11
removed the flag, the route and src/gui/routes/v2.py: `/` now renders the v2
shell and `/login` the v2 login page. The assertions here changed target
accordingly — what each one *proves* is unchanged or stronger:

  - "the shell is reachable and login-gated" now tests `/` instead of `/v2`;
  - "the preview is absent unless the flag is on" became "the preview route
    is gone for good" — an authenticated GET /v2 must 404, from the DEFAULT
    config, with no flag able to bring it back;
  - "the shell HTML is really the v2 one" gained a check that the legacy
    bundle is not being served alongside it.

`client` (built on `app_persistent`) comes from tests/conftest.py.
"""
import pytest

from src.config import ConfigManager, hash_password
from src.gui import build_app as _create_app


@pytest.fixture
def client_legacy_flag(temp_config_file):
    """A client whose config still carries the retired enable_v2_preview flag.

    Mirrors tests/conftest.py's app_persistent construction. Real installs
    that ran the preview have `enable_v2_preview: true` sitting in their
    config.json; WebGuiSettings is extra="allow", so the key survives
    validation. This fixture exists to prove the leftover key neither
    resurrects /v2 nor breaks the app.
    """
    cm = ConfigManager(config_file=temp_config_file)
    cm.load()
    cm.config["web_gui"] = {
        "username": "admin",
        "password": hash_password("testpass"),
        "allowed_ips": ["127.0.0.1", "192.168.1.0/24"],
        "secret_key": "x" * 64,
        "enable_v2_preview": True,
    }
    cm.save()

    app = _create_app(cm, persistent_mode=True)
    app.config.update({"TESTING": True})
    return app.test_client()


def _login(client):
    resp = client.post("/api/login", json={"username": "admin", "password": "testpass"})
    assert resp.status_code == 200, resp.data
    return resp


def test_preview_route_is_gone(client):
    """/v2 must not exist any more — the shell moved to `/`.

    Logs in first: unauthenticated requests to *any* unmatched path are
    redirected to /login by the app-wide `security_check` before_request
    hook (src/gui/__init__.py) before Flask ever raises a 404 for the
    missing route, so an unauthenticated probe can't distinguish "route
    absent" from "route present but requires login".
    """
    _login(client)

    assert client.get("/v2").status_code == 404


def test_preview_route_stays_gone_with_the_retired_flag_still_in_config(client_legacy_flag):
    """A leftover `enable_v2_preview: true` must not bring /v2 back.

    The flag is deleted from src/config_models.py, not merely defaulted off;
    this is what proves no code still reads it.
    """
    _login(client_legacy_flag)

    assert client_legacy_flag.get("/v2").status_code == 404
    # ...and the leftover key does not break the real GUI either.
    assert client_legacy_flag.get("/").status_code == 200


def test_root_requires_login(client):
    resp = client.get("/")
    assert resp.status_code in (302, 401)
    assert resp.status_code != 404


def test_root_serves_the_v2_shell_and_not_the_legacy_bundle(client):
    _login(client)

    resp = client.get("/")
    assert resp.status_code == 200
    assert b"css/v2/tokens.css" in resp.data
    assert b"js/v2/app.mjs" in resp.data
    assert b'id="shell"' in resp.data
    # The legacy frontend must not be served alongside it. These are the two
    # entry points src/templates/index.html loaded (its own bundle root and
    # the dashboard module); either one appearing here means `/` is still
    # rendering, or mixing in, the old GUI.
    assert b"js/_init_bootstrap.js" not in resp.data
    assert b"js/dashboard.js" not in resp.data
    assert b"css/app.css" not in resp.data


def test_login_page_serves_the_v2_login(client):
    """GET /login is the v2 login page, reachable without a session."""
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b'id="login-root"' in resp.data
    assert b"js/v2/areas/login.mjs" in resp.data
    # The server-rendered catalogue seed login.mjs boots from (auth.py's
    # login_page); without it every string on the page falls back to English.
    assert b'id="login-i18n-seed"' in resp.data
    assert b"gui_login_btn" in resp.data


def test_pre_auth_bypass_list_is_exact_and_grants_nothing_broader(client):
    """security_check's bypass is an exact-match list, not a prefix match.

    /login is reachable logged out; a path that merely *starts with* /login
    is not. A regression to `request.path.startswith(...)` turns this red.
    """
    assert client.get("/login").status_code == 200
    # Unmatched paths under the same prefix must still be pushed to /login,
    # never served.
    for path in ("/login/extra", "/loginx", "/api/login/extra"):
        resp = client.get(path)
        assert resp.status_code in (302, 401), (path, resp.status_code)
        if resp.status_code == 302:
            assert resp.headers["Location"].endswith("/login")
