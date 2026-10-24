"""Gate 5: every settings field has a reader.

Matching a bare attribute name proves nothing (`.url`, `.level`, `.enabled` exist on
many objects), so each leaf path is registered with the module that reads it, and that
module must show both the attribute read and evidence of the owning model: the model
class name or the parent field (e.g. `.pce`, `.tls`).
"""
from __future__ import annotations

import ast
from pathlib import Path

from pydantic import BaseModel

from illumio_ops.settings.schema import Settings
from tests_v6.gates._scan import PKG_ROOT, iter_modules

SETTINGS_READERS: dict[str, str] = {
    "revision": "illumio_ops.settings.store",
    "pce.url": "illumio_ops.pce.client",
    "pce.org_id": "illumio_ops.pce.client",
    "pce.api_key": "illumio_ops.pce.client",
    "pce.api_secret": "illumio_ops.pce.client",
    "pce.verify_tls": "illumio_ops.pce.client",
    "pce.deployment_type": "illumio_ops.services.pce_health",
    "web.username": "illumio_ops.web.auth",
    "web.password_hash": "illumio_ops.web.auth",
    "web.must_change_password": "illumio_ops.web.auth",
    "web.secret_key": "illumio_ops.web.app",
    "web.allowed_ips": "illumio_ops.web.app",
    "web.session_lifetime_seconds": "illumio_ops.web.app",
}
# Fields whose reader arrives later: value = the task or phase that adds it.
PENDING_READERS: dict[str, str] = {
    "web.host": "P1-T11",
    "web.port": "P1-T11",
    **{f"web.tls.{f}": "P1-T11" for f in (
        "enabled", "mode", "cert_file", "key_file", "auto_renew", "auto_renew_days",
        "validity_days", "key_algorithm", "min_version", "ciphers")},
    "logging.level": "P1-T11",
    "display.language": "P1-T13",
    "pce.events_timeout_seconds": "P2",
    "pce.console_url": "P3",
    "display.timezone": "P3",
}
# Fields with no runtime reader by design.
STRUCTURAL: dict[str, str] = {
    "schema_version": "enforced by the schema's Literal type when the file is loaded",
}


def leaf_paths(model: type[BaseModel] = Settings, prefix: str = "") -> dict[str, tuple[str, str]]:
    """leaf path -> (owner model class name, parent field name)."""
    out: dict[str, tuple[str, str]] = {}
    parent = prefix.rstrip(".").rsplit(".", 1)[-1] if prefix else ""
    for name, field in model.model_fields.items():
        ann = field.annotation
        path = f"{prefix}{name}"
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            out |= leaf_paths(ann, f"{path}.")
        else:
            out[path] = (model.__name__, parent)
    return out


def _evidence(tree: ast.Module) -> tuple[set[str], set[str]]:
    attrs, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attrs.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit(".", 1)[-1])
    return attrs, names


def find_reader_violations(readers: dict[str, str], pending: dict[str, str], structural: dict[str, str],
                           leaves: dict[str, tuple[str, str]], pkg: Path = PKG_ROOT) -> list[str]:
    out = []
    registered = [*readers, *pending, *structural]
    dupes = {p for p in registered if registered.count(p) > 1}
    out += [f"{p} is registered more than once" for p in sorted(dupes)]
    out += [f"{p} has no registered reader" for p in sorted(set(leaves) - set(registered))]
    out += [f"{p} is registered but not a settings field" for p in sorted(set(registered) - set(leaves))]
    modules = {name: tree for name, tree, _ in iter_modules(pkg)}
    for path, module in sorted(readers.items()):
        if path not in leaves:
            continue
        tree = modules.get(module)
        if tree is None:
            out.append(f"{path}: reader module {module} does not exist")
            continue
        attrs, names = _evidence(tree)
        owner, parent = leaves[path]
        leaf = path.rsplit(".", 1)[-1]
        if leaf not in attrs:
            out.append(f"{path}: {module} never reads .{leaf}")
        elif owner not in names and (not parent or parent not in attrs):
            out.append(f"{path}: {module} reads .{leaf} but shows no sign of {owner}")
    return out


def test_every_settings_field_has_a_reader():
    assert find_reader_violations(SETTINGS_READERS, PENDING_READERS, STRUCTURAL, leaf_paths()) == []


def _pkg(tmp_path: Path, src: str) -> Path:
    root = tmp_path / "illumio_ops"
    root.mkdir()
    (root / "__init__.py").touch()
    (root / "r.py").write_text(src)
    return root


class _Log(BaseModel):
    level: str


class _Other(BaseModel):
    level: str


class _Root(BaseModel):
    logging: _Log
    other: _Other


def test_selftest_unregistered_leaf_is_red(tmp_path):
    v = find_reader_violations({}, {}, {}, leaf_paths(_Root), _pkg(tmp_path, "x = 1\n"))
    assert "logging.level has no registered reader" in v


def test_selftest_same_name_on_another_model_is_red(tmp_path):
    pkg = _pkg(tmp_path, "def f(o):\n    return o.other.level\n")
    v = find_reader_violations({"logging.level": "illumio_ops.r"}, {"other.level": "P9"}, {}, leaf_paths(_Root), pkg)
    assert v == ["logging.level: illumio_ops.r reads .level but shows no sign of _Log"]


def test_selftest_proper_reader_is_green(tmp_path):
    pkg = _pkg(tmp_path, "def f(s):\n    return s.logging.level\n")
    v = find_reader_violations({"logging.level": "illumio_ops.r"}, {"other.level": "P9"}, {}, leaf_paths(_Root), pkg)
    assert v == []
