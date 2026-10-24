from illumio_ops.settings.secrets import hash_password, verify_password

from .conftest import LOCAL, csrf, login, make_ctx, post

# Produced by 5.x src.config.hash_password (argon2id m=131072,t=4,p=4) for "legacy-pass-1234".
HASH_5X = "$argon2id$v=19$m=131072,t=4,p=4$zLAyG2eBFz4L39TOfsm/Hg$8TjLl9KrPlrdJi9fy3KFQ01oXs8KebivIJGPPdwqWFo"


def test_5x_argon2_hash_verifies():
    assert verify_password("legacy-pass-1234", HASH_5X)
    assert not verify_password("legacy-pass-1235", HASH_5X)


def test_hash_parameters_match_5x():
    assert hash_password("x").startswith("$argon2id$v=19$m=131072,t=4,p=4$")


def test_verify_password_rejects_empty_or_bad_hash():
    assert not verify_password("x", "") and not verify_password("x", "$argon2id$garbage")


def test_login_ok_returns_csrf_and_flag(client):
    r = login(client)
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True
    assert body["data"]["username"] == "illumio" and body["data"]["must_change_password"] is False
    assert body["data"]["csrf_token"]
    assert client.get("/api/auth/me", environ_overrides=LOCAL).get_json()["data"]["username"] == "illumio"


def test_wrong_user_and_wrong_password_look_identical(client):
    a = login(client, password="nope-nope-nope")
    b = login(client, username="root")
    assert a.status_code == b.status_code == 401
    assert a.get_json() == b.get_json()
    assert a.get_json()["error"]["code"] == "invalid_credentials"


def test_login_malformed_body_is_400_and_does_not_echo(client):
    r = client.post("/api/auth/login", json={"username": "illumio", "password": ["SECRETPART"]},
                    environ_overrides=LOCAL)
    assert r.status_code == 400 and b"SECRETPART" not in r.data


def test_logout_clears_session(client):
    token = login(client).get_json()["data"]["csrf_token"]
    assert post(client, "/api/auth/logout", token=token).status_code == 200
    assert client.get("/api/auth/me", environ_overrides=LOCAL).status_code == 401


def _change(client, **body):
    return post(client, "/api/auth/password", body)


def test_old_password_required_and_checked(client):
    login(client)
    r = _change(client, new_password="a-new-password-1", confirm_password="a-new-password-1")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "old_password_required"
    r = _change(client, old_password="wrong", new_password="a-new-password-1", confirm_password="a-new-password-1")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "old_password_incorrect"


def test_new_password_length_and_confirm(client):
    login(client)
    for new, confirm in (("short1234AB", "short1234AB"), ("x" * 513, "x" * 513), ("a-new-password-1", "different-pass-1")):
        r = _change(client, old_password="illumio", new_password=new, confirm_password=confirm)
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_new_password"
        assert r.get_json()["error"]["params"] == {"min": "12", "max": "512"}


def test_password_change_rotates_secret_and_keeps_caller_logged_in(app, ctx):
    a, b = app.test_client(), app.test_client()
    login(a)
    login(b)
    old_key = ctx.settings.current().web.secret_key
    r = _change(a, old_password="illumio", new_password="a-new-password-1", confirm_password="a-new-password-1")
    assert r.status_code == 200 and r.get_json()["data"]["csrf_token"]
    assert ctx.settings.current().web.secret_key != old_key
    assert verify_password("a-new-password-1", ctx.settings.current().web.password_hash)
    assert a.get("/api/auth/me", environ_overrides=LOCAL).status_code == 200
    assert b.get("/api/auth/me", environ_overrides=LOCAL).status_code == 401


def test_must_change_password_gate(tmp_path, static_dir):
    from illumio_ops.web.app import create_app

    app = create_app(make_ctx(tmp_path, must_change_password=True), use_https=False, static_dir=static_dir)
    app.testing = True
    c = app.test_client()
    assert login(c).get_json()["data"]["must_change_password"] is True
    assert c.get("/api/auth/me", environ_overrides=LOCAL).status_code == 200
    blocked = c.get("/api/does-not-exist", environ_overrides=LOCAL)
    assert blocked.status_code == 423 and blocked.get_json()["error"]["code"] == "password_change_required"
    r = post(c, "/api/auth/password", {"new_password": "completelynewpass12", "confirm_password": "completelynewpass12"})
    assert r.status_code == 200
    assert c.get("/api/auth/me", environ_overrides=LOCAL).get_json()["data"]["must_change_password"] is False


def test_csrf_endpoint_is_public(client):
    assert csrf(client)


def test_logout_revokes_a_copied_session_cookie(app):
    a, b = app.test_client(), app.test_client()
    token = login(a).get_json()["data"]["csrf_token"]
    b.set_cookie("session", a.get_cookie("session").value)
    assert b.get("/api/auth/me", environ_overrides=LOCAL).status_code == 200
    assert post(a, "/api/auth/logout", token=token).status_code == 200
    assert b.get("/api/auth/me", environ_overrides=LOCAL).status_code == 401


def test_login_issues_a_new_session_id(app):
    c = app.test_client()
    login(c)
    first = c.get_cookie("session").value
    login(c)
    assert c.get_cookie("session").value != first


def test_password_change_is_rate_limited(client):
    login(client)
    token = csrf(client)
    codes = [post(client, "/api/auth/password", {"old_password": "wrong", "new_password": "x",
                                                  "confirm_password": "x"}, token=token).status_code
             for _ in range(6)]
    assert codes[:5] == [400] * 5 and codes[5] == 429


def test_relogin_retires_the_previous_session(app):
    a, b = app.test_client(), app.test_client()
    login(a)
    b.set_cookie("session", a.get_cookie("session").value)
    assert b.get("/api/auth/me", environ_overrides=LOCAL).status_code == 200
    login(a)
    assert b.get("/api/auth/me", environ_overrides=LOCAL).status_code == 401
    assert a.get("/api/auth/me", environ_overrides=LOCAL).status_code == 200


def test_expired_session_ids_are_pruned(app, monkeypatch):
    from illumio_ops.web import auth

    c = app.test_client()
    login(c)
    sessions = app.extensions[auth._SESSIONS_KEY]
    assert len(sessions) == 1
    real = auth.time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + 28800 + 1)
    login(app.test_client())
    assert len(sessions) == 1
