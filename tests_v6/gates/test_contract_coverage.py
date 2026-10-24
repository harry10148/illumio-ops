"""Gate 3/4: every /api route has a contract, and every contract has a caller in web/src."""
from __future__ import annotations

import re
from pathlib import Path

from flask import Blueprint, Flask
from pydantic import BaseModel

from illumio_ops.web.contract import REGISTRY, Operation, api_route, op_id_for_endpoint
from tests_v6.gates._scan import REPO_ROOT

WEB_SRC = REPO_ROOT / "web" / "src"
GENERATED = WEB_SRC / "api" / "generated.ts"


def routes_without_contract(app: Flask, registry: dict[str, Operation]) -> list[str]:
    out = []
    routed = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        op_id = op_id_for_endpoint(rule.endpoint)
        if op_id is None or op_id not in registry:
            out.append(f"route {rule.rule} ({rule.endpoint}) has no contract")
        else:
            routed.add(op_id)
    out += [f"contract {op} is not routed" for op in sorted(set(registry) - routed)]
    return out


def ops_without_caller(web_src: Path, op_ids: list[str]) -> list[str]:
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(web_src.rglob("*.ts*"))
                     if p.resolve() != (web_src / "api" / "generated.ts").resolve())
    return [op for op in op_ids if not re.search(rf"""\bcall\(\s*["']{re.escape(op)}["']""", text)]


def _app(tmp_path):
    from illumio_ops.web.app import create_app
    from tests_v6.web.conftest import make_ctx

    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("x")
    return create_app(make_ctx(tmp_path), use_https=False, static_dir=static)


def test_every_api_rule_has_operation(tmp_path, monkeypatch):
    monkeypatch.setenv("ILLUMIO_OPS_RATELIMIT_URI", "memory://")
    assert routes_without_contract(_app(tmp_path), REGISTRY) == []


def test_injected_route_without_contract_is_caught(tmp_path, monkeypatch):
    monkeypatch.setenv("ILLUMIO_OPS_RATELIMIT_URI", "memory://")
    app = _app(tmp_path)
    app.add_url_rule("/api/rogue", "rogue", lambda: "x")
    assert any("/api/rogue" in v for v in routes_without_contract(app, REGISTRY))


def test_injected_unrouted_contract_is_caught(tmp_path, monkeypatch):
    monkeypatch.setenv("ILLUMIO_OPS_RATELIMIT_URI", "memory://")

    class R(BaseModel):
        x: int

    reg = dict(REGISTRY) | {"ghost.op": Operation("ghost.op", "GET", "/api/ghost", None, R)}
    assert "contract ghost.op is not routed" in routes_without_contract(_app(tmp_path), reg)


def test_every_operation_has_a_frontend_caller():
    assert ops_without_caller(WEB_SRC, sorted(REGISTRY)) == []


def test_generated_types_do_not_count_as_callers(tmp_path):
    src = tmp_path / "src"
    (src / "api").mkdir(parents=True)
    (src / "api" / "generated.ts").write_text('export type OpId = "a.b" | "c.d";\ncall("a.b")\n')
    (src / "page.tsx").write_text('await call("c.d", body)\n')
    assert ops_without_caller(src, ["a.b", "c.d"]) == ["a.b"]


def test_blueprint_binding_registers_endpoint(tmp_path):
    class R(BaseModel):
        x: int

    bp = Blueprint("probe_bp", __name__)
    api_route(bp, Operation("probe.op", "GET", "/api/probe", None, R))(lambda: R(x=1))
    app = Flask("t")
    app.register_blueprint(bp)
    assert op_id_for_endpoint("probe_bp.probe_op") == "probe.op"
