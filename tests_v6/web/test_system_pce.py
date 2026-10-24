import responses

from illumio_ops.settings.secrets import MASK

from .conftest import LOCAL, login

BASE = "https://pce.example.com:8443"


def _put(client, body):
    from .conftest import csrf
    return client.put("/api/system/pce", json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def _form(**kw):
    base = {"url": BASE, "org_id": "1", "api_key": "api_key_value", "api_secret": "SECRETVALUE",
            "deployment_type": "on_prem", "console_url": None, "verify_tls": True}
    return base | kw


def _save(client, **kw):
    rev = client.get("/api/system/pce", environ_overrides=LOCAL).get_json()["data"]["revision"]
    return _put(client, _form(**kw) | {"revision": rev})


def test_get_masks_secrets(client, ctx):
    login(client)
    assert _save(client).status_code == 200
    r = client.get("/api/system/pce", environ_overrides=LOCAL)
    data = r.get_json()["data"]
    assert data["api_key"] == MASK and data["api_secret"] == MASK
    assert b"SECRETVALUE" not in r.data and data["url"] == BASE
    assert data["revision"] == ctx.settings.current().revision


def test_put_masked_secret_keeps_existing(client, ctx):
    login(client)
    _save(client)
    assert _save(client, api_key=MASK, api_secret="", url=BASE + "/").status_code == 200
    pce = ctx.settings.current().pce
    assert pce.api_key == "api_key_value" and pce.api_secret == "SECRETVALUE"
    assert MASK not in ctx.paths.settings_file.read_text()


def test_put_stale_revision_returns_409(client, ctx):
    login(client)
    rev = client.get("/api/system/pce", environ_overrides=LOCAL).get_json()["data"]["revision"]
    assert _put(client, _form() | {"revision": rev}).status_code == 200
    r = _put(client, _form(org_id="2") | {"revision": rev})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "stale_revision"
    assert ctx.settings.current().pce.org_id == "1"


def test_put_invalid_url_returns_field_error(client, ctx):
    login(client)
    before = ctx.paths.settings_file.read_bytes()
    r = _save(client, url="pce.example.com")
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["code"] == "invalid_settings" and err["field"] == "pce.url"
    assert ctx.paths.settings_file.read_bytes() == before


def test_put_does_not_touch_events_timeout(client, ctx):
    login(client)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(events_timeout_seconds=90))
    _save(client)
    assert ctx.settings.current().pce.events_timeout_seconds == 90


def test_probe_unconfigured_returns_409(client):
    login(client)
    from .conftest import post
    r = post(client, "/api/system/pce/probe")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "pce_not_configured"


@responses.activate
def test_probe_writes_latest(client):
    responses.add_passthru("http://localhost")
    login(client)
    _save(client, deployment_type="saas")
    responses.add(responses.GET, f"{BASE}/api/v2/noop", status=401)
    from .conftest import post
    r = post(client, "/api/system/pce/probe")
    run = r.get_json()["data"]
    assert r.status_code == 200
    assert run["results"] == [{"name": "noop", "ok": False, "status": 401, "category": "auth_failed",
                               "detail_key": "probe_auth_failed"}]
    latest = client.get("/api/system/pce/latest", environ_overrides=LOCAL).get_json()["data"]
    assert latest["run"]["results"] == run["results"] and latest["run"]["checked_at"] == run["checked_at"]


def test_latest_is_empty_before_any_probe(client):
    login(client)
    assert client.get("/api/system/pce/latest", environ_overrides=LOCAL).get_json()["data"] == {"run": None}


def test_pce_endpoints_require_login(client):
    assert client.get("/api/system/pce", environ_overrides=LOCAL).status_code == 401


def test_changing_the_pce_address_requires_reentering_credentials(client, ctx):
    login(client)
    _save(client)
    r = _save(client, url="https://attacker.example.com:8443", api_key=MASK, api_secret=MASK)
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["code"] == "credentials_required" and err["field"] == "api_key"
    assert ctx.settings.current().pce.url == BASE
    ok = _save(client, url="https://new-pce.example.com:8443", api_key="k2", api_secret="s2")
    assert ok.status_code == 200 and ctx.settings.current().pce.api_secret == "s2"


def test_weakening_tls_check_requires_reentering_credentials(client, ctx):
    login(client)
    _save(client)
    r = _save(client, verify_tls=False, api_key=MASK, api_secret=MASK)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "credentials_required"
    assert ctx.settings.current().pce.verify_tls is True
    assert _save(client, verify_tls="/etc/pki/ca.pem", api_key=MASK, api_secret=MASK).status_code == 400


def test_other_edits_keep_saved_credentials(client, ctx):
    login(client)
    _save(client)
    assert _save(client, deployment_type="saas", api_key=MASK, api_secret=MASK).status_code == 200
    assert ctx.settings.current().pce.api_secret == "SECRETVALUE"
