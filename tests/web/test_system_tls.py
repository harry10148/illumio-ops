from illumio_ops.web import tls

from .conftest import LOCAL, csrf, login, post
from .test_tls import _sign_with_own_ca


def _status(client):
    return client.get("/api/system/tls", environ_overrides=LOCAL).get_json()["data"]


def test_status_reports_self_signed_cert(client, ctx):
    tls.ensure_self_signed(ctx.paths.tls_dir, ctx.settings.current().web.tls)
    login(client)
    s = _status(client)
    assert s["enabled"] is True and s["mode"] == "self_signed"
    assert s["cert"]["subject_cn"] == "localhost" and 396 <= s["cert"]["days_remaining"] <= 397
    assert s["restart_required"] is False


def test_renew_uses_configured_days_and_algorithm(client, ctx):
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["web"]["tls"].update(validity_days=100, key_algorithm="rsa-2048"))
    login(client)
    r = post(client, "/api/system/tls/renew")
    assert r.status_code == 200
    assert 99 <= r.get_json()["data"]["cert"]["days_remaining"] <= 100


def test_renew_refused_for_provided_certificate(client, ctx):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["web"]["tls"].update(mode="provided"))
    login(client)
    r = post(client, "/api/system/tls/renew")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "renew_self_signed_only"


def test_csr_then_import_switches_to_provided(client, ctx):
    login(client)
    r = post(client, "/api/system/tls/csr", {"cn": "ops.example.com", "o": "", "ou": "", "c": "TW",
                                              "san_dns": ["ops.example.com"], "san_ip": [],
                                              "key_algorithm": "rsa-2048"})
    assert r.status_code == 200 and "BEGIN CERTIFICATE REQUEST" in r.get_json()["data"]["csr_pem"]
    pem = _sign_with_own_ca(ctx.paths.tls_dir / tls.CSR_KEY, cn="ops.example.com")
    r = post(client, "/api/system/tls/import", {"cert_pem": pem})
    data = r.get_json()["data"]
    assert r.status_code == 200 and data["mode"] == "provided" and data["cert"]["subject_cn"] == "ops.example.com"
    t = ctx.settings.current().web.tls
    assert t.cert_file == str(ctx.paths.tls_dir / tls.CA_SIGNED_CERT) and t.key_file == str(ctx.paths.tls_dir / tls.CA_SIGNED_KEY)


def test_import_mismatched_cert_is_refused_and_settings_unchanged(client, ctx):
    login(client)
    post(client, "/api/system/tls/csr", {"cn": "a", "o": "", "ou": "", "c": "", "san_dns": [], "san_ip": [],
                                         "key_algorithm": "rsa-2048"})
    other = ctx.paths.tls_dir / "other.pem"
    other.write_bytes((ctx.paths.tls_dir / tls.CSR_KEY).read_bytes())
    post(client, "/api/system/tls/csr", {"cn": "b", "o": "", "ou": "", "c": "", "san_dns": [], "san_ip": [],
                                         "key_algorithm": "rsa-2048"})
    r = post(client, "/api/system/tls/import", {"cert_pem": _sign_with_own_ca(other)})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "certificate_rejected"
    assert ctx.settings.current().web.tls.mode == "self_signed"


def test_update_provided_requires_existing_files(client, ctx):
    login(client)
    s = _status(client)
    body = {k: s[k] for k in ("revision", "enabled", "auto_renew", "auto_renew_days", "validity_days",
                              "key_algorithm", "min_version")}
    body |= {"mode": "provided", "cert_file": "/nonexistent/c.pem", "key_file": "/nonexistent/k.pem"}
    r = client.put("/api/system/tls", json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})
    assert r.status_code == 400 and r.get_json()["error"]["field"] == "cert_file"


def test_update_marks_restart_required(client, ctx):
    ctx.served_tls = ctx.settings.current().web.tls
    login(client)
    s = _status(client)
    body = {k: s[k] for k in ("revision", "enabled", "mode", "cert_file", "key_file", "auto_renew",
                              "validity_days", "key_algorithm", "min_version")} | {"auto_renew_days": 45}
    r = client.put("/api/system/tls", json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})
    assert r.status_code == 200 and r.get_json()["data"]["restart_required"] is True
    assert ctx.settings.current().web.tls.auto_renew_days == 45


def test_a_new_csr_does_not_replace_the_key_in_use(client, ctx):
    import ssl

    login(client)
    body = {"cn": "ops.example.com", "o": "", "ou": "", "c": "", "san_dns": [], "san_ip": [], "key_algorithm": "rsa-2048"}
    post(client, "/api/system/tls/csr", body)
    pending = sorted(p.name for p in ctx.paths.tls_dir.iterdir())
    key_for_ca = next(ctx.paths.tls_dir / n for n in pending if "key" in n)
    assert post(client, "/api/system/tls/import", {"cert_pem": _sign_with_own_ca(key_for_ca)}).status_code == 200
    t = ctx.settings.current().web.tls
    post(client, "/api/system/tls/csr", body | {"cn": "renewal.example.com"})  # e.g. preparing a renewal
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(t.cert_file, t.key_file)  # still a pair
