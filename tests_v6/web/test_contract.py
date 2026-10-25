import json
import subprocess
import sys
from pathlib import Path

import pytest
from flask import Blueprint
from pydantic import BaseModel

from illumio_ops.pce.client import PceNotConfigured, PceTransportError
from illumio_ops.settings.store import SettingsConflict, SettingsInvalid
from illumio_ops.web.app import create_app
from illumio_ops.web.contract import (
    REGISTRY,
    ApiFailure,
    Operation,
    api_route,
    op_id_for_endpoint,
    operation,
)

from .conftest import LOCAL, login, post

REPO = Path(__file__).resolve().parents[2]


class _Req(BaseModel):
    name: str
    count: int


class _Res(BaseModel):
    echo: str


def _app_with(tmp_path, static_dir, ctx, handler, *, method="POST", request=_Req):
    bp = Blueprint("t", __name__)
    op = Operation("t.op", method, "/api/t/op", request, _Res)
    api_route(bp, op)(handler)
    app = create_app(ctx, use_https=False, static_dir=static_dir)
    app.register_blueprint(bp)
    app.testing = True
    c = app.test_client()
    login(c)
    return c


def test_invalid_body_returns_field_error(tmp_path, static_dir, ctx):
    c = _app_with(tmp_path, static_dir, ctx, lambda body: _Res(echo=body.name))
    r = post(c, "/api/t/op", {"name": "x", "count": "SECRETNOTINT"})
    body = r.get_json()
    assert r.status_code == 400 and body["error"]["code"] == "invalid_input"
    assert body["error"]["field"] == "count" and b"SECRETNOTINT" not in r.data
    ok = post(c, "/api/t/op", {"name": "x", "count": 1}).get_json()
    assert ok == {"ok": True, "data": {"echo": "x"}, "error": None,
                  "meta": {"partial": False, "truncated": False, "notes": []}}


@pytest.mark.parametrize(("exc", "status", "code", "params"), [
    (SettingsInvalid([("web.port", "bad")]), 400, "invalid_settings", {}),
    (SettingsConflict(3, 4), 409, "stale_revision", {"expected": "3", "actual": "4"}),
    (PceNotConfigured(), 409, "pce_not_configured", {}),
    (PceTransportError("/noop", "dns"), 502, "pce_unreachable", {"kind": "dns"}),
    (ApiFailure(422, "custom", "err_custom", field="f", params={"a": "b"}), 422, "custom", {"a": "b"}),
])
def test_exceptions_map_to_envelopes(tmp_path, static_dir, ctx, exc, status, code, params):
    def boom(body):
        raise exc

    r = post(_app_with(tmp_path, static_dir, ctx, boom), "/api/t/op", {"name": "x", "count": 1})
    assert r.status_code == status
    err = r.get_json()["error"]
    assert err["code"] == code and err["params"] == params
    if isinstance(exc, SettingsInvalid):
        assert err["field"] == "web.port"


def test_unhandled_exception_hides_message(tmp_path, static_dir, ctx):
    def boom(body):
        raise RuntimeError("SECRET internal detail")

    r = post(_app_with(tmp_path, static_dir, ctx, boom), "/api/t/op", {"name": "x", "count": 1})
    assert r.status_code == 500 and r.get_json()["error"]["code"] == "internal_error"
    assert b"SECRET" not in r.data


def test_get_operation_without_body(tmp_path, static_dir, ctx):
    c = _app_with(tmp_path, static_dir, ctx, lambda: _Res(echo="hi"), method="GET", request=None)
    assert c.get("/api/t/op", environ_overrides=LOCAL).get_json()["data"] == {"echo": "hi"}


def test_duplicate_op_id_rejected():
    reg: dict[str, Operation] = {}
    operation("x.y", "GET", "/api/x", None, _Res, registry=reg)
    with pytest.raises(ValueError):
        operation("x.y", "GET", "/api/x2", None, _Res, registry=reg)


def test_auth_ops_registered_and_public_ones_mapped(app):
    assert {"auth.login", "auth.csrf", "auth.logout", "auth.me", "auth.password"} <= set(REGISTRY)
    with app.test_request_context("/api/auth/login", method="POST"):
        from flask import request
        assert op_id_for_endpoint(request.url_rule.endpoint) == "auth.login"


def _export(out: Path) -> bytes:
    subprocess.run([sys.executable, str(REPO / "scripts/v6/export_contracts.py"), "--out", str(out)],
                   check=True, cwd=REPO, timeout=120)
    return out.read_bytes()


def test_export_is_stable(tmp_path):
    a = _export(tmp_path / "a.json")
    b = _export(tmp_path / "b.json")
    assert a == b
    data = json.loads(a)
    assert data["operations"]["auth.login"]["method"] == "POST"
    assert data["operations"]["auth.login"]["path"] == "/api/auth/login"
    assert "properties" in data["operations"]["auth.login"]["request_schema"]
    assert data["operations"]["auth.me"]["request_schema"] is None
    assert data["values"]["PolicyDecision"] == ["allowed", "blocked", "potentially_blocked", "unknown"]
