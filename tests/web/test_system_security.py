from .conftest import LOCAL, csrf, login


def _put(client, url, body):
    return client.put(url, json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def _security(client):
    return client.get("/api/system/security", environ_overrides=LOCAL).get_json()["data"]


def test_get_shows_requester_address(client):
    login(client)
    s = _security(client)
    assert s["username"] == "illumio" and s["allowed_ips"] == [] and s["requester_ip"] == "127.0.0.1"


def test_allowlist_excluding_requester_is_refused(client, ctx):
    login(client)
    rev = _security(client)["revision"]
    r = _put(client, "/api/system/security", {"revision": rev, "allowed_ips": ["10.0.0.0/8"], "confirm_lockout": False})
    body = r.get_json()
    assert r.status_code == 409 and body["error"]["code"] == "would_lock_out"
    assert body["error"]["params"] == {"ip": "127.0.0.1"}
    assert ctx.settings.current().web.allowed_ips == ()


def test_allowlist_with_confirm_is_saved(client, ctx):
    login(client)
    rev = _security(client)["revision"]
    r = _put(client, "/api/system/security", {"revision": rev, "allowed_ips": ["10.0.0.0/8"], "confirm_lockout": True})
    assert r.status_code == 200 and ctx.settings.current().web.allowed_ips == ("10.0.0.0/8",)


def test_allowlist_including_requester_needs_no_confirm(client, ctx):
    login(client)
    rev = _security(client)["revision"]
    r = _put(client, "/api/system/security",
             {"revision": rev, "allowed_ips": ["::ffff:127.0.0.1", " ", "192.168.1.0/24"], "confirm_lockout": False})
    assert r.status_code == 200
    assert ctx.settings.current().web.allowed_ips == ("127.0.0.1", "192.168.1.0/24")


def test_empty_allowlist_allows_everyone(client, ctx):
    login(client)
    rev = _security(client)["revision"]
    assert _put(client, "/api/system/security", {"revision": rev, "allowed_ips": [], "confirm_lockout": False}).status_code == 200


def test_invalid_ip_reports_field(client, ctx):
    login(client)
    rev = _security(client)["revision"]
    r = _put(client, "/api/system/security",
             {"revision": rev, "allowed_ips": ["127.0.0.1", "localhost", "300.1.1.1"], "confirm_lockout": True})
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["field"] == "allowed_ips" and err["params"] == {"entries": "localhost, 300.1.1.1"}


def test_language_change_reflected_in_me(client, ctx):
    login(client)
    assert client.get("/api/auth/me", environ_overrides=LOCAL).get_json()["data"]["language"] == "en"
    rev = client.get("/api/system/display", environ_overrides=LOCAL).get_json()["data"]["revision"]
    r = _put(client, "/api/system/display", {"revision": rev, "language": "zh_TW"})
    assert r.status_code == 200 and r.get_json()["data"]["language"] == "zh_TW"
    assert client.get("/api/auth/me", environ_overrides=LOCAL).get_json()["data"]["language"] == "zh_TW"


def test_unknown_language_is_rejected(client):
    login(client)
    rev = client.get("/api/system/display", environ_overrides=LOCAL).get_json()["data"]["revision"]
    r = _put(client, "/api/system/display", {"revision": rev, "language": "fr"})
    assert r.status_code == 400 and r.get_json()["error"]["field"] == "language"


def test_default_password_flag(client):
    login(client)
    assert client.get("/api/auth/me", environ_overrides=LOCAL).get_json()["data"]["default_password_in_use"] is True
    from .conftest import post
    r = post(client, "/api/auth/password", {"old_password": "illumio", "new_password": "a-new-password-1",
                                            "confirm_password": "a-new-password-1"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", environ_overrides=LOCAL).get_json()["data"]["default_password_in_use"] is False
