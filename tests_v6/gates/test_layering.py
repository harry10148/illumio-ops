"""Gate 1: dependency direction between v6 layers."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from tests_v6.gates._scan import (
    PKG_ROOT,
    Module,
    imported_modules,
    iter_modules,
    subpackage,
)

ANY = "*"
# layer -> sub-packages (or top-level modules) it must not import; ANY = everything else in illumio_ops
LAYER_RULES: dict[str, frozenset[str]] = {
    "domain": frozenset({ANY}),
    "store": frozenset({"services", "web", "jobs"}),
    "pce": frozenset({"services", "web", "jobs"}),
    "settings": frozenset({"services", "web", "jobs"}),
    "services": frozenset({"web"}),
}


def find_layer_violations(modules: Iterable[Module]) -> list[str]:
    out = []
    for name, tree, path in modules:
        layer = subpackage(name)
        forbidden = LAYER_RULES.get(layer or "")
        if not forbidden:
            continue
        for target, line in imported_modules(name, tree, path.name == "__init__.py"):
            tgt = subpackage(target)
            if tgt is None or tgt == layer:
                continue
            if ANY in forbidden or tgt in forbidden:
                out.append(f"{path}:{line}: {layer} imports {target}")
    return sorted(set(out))


def test_no_layer_violations():
    assert find_layer_violations(iter_modules(PKG_ROOT)) == []


def _pkg(tmp_path: Path, rel: str, src: str) -> Path:
    root = tmp_path / "illumio_ops"
    for d in ("", "domain", "store", "services", "web"):
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "__init__.py").touch()
    (root / rel).write_text(src, encoding="utf-8")
    return root


def test_injected_domain_import_is_caught(tmp_path):
    root = _pkg(tmp_path, "domain/bad.py", "import illumio_ops.web\n")
    assert len(find_layer_violations(iter_modules(root))) == 1


def test_injected_relative_and_from_imports_are_caught(tmp_path):
    root = _pkg(tmp_path, "store/bad.py", "from ..services import x\nfrom illumio_ops import web\n")
    v = find_layer_violations(iter_modules(root))
    assert any("illumio_ops.services" in s for s in v) and any("illumio_ops.web" in s for s in v)


def test_allowed_direction_is_clean(tmp_path):
    root = _pkg(tmp_path, "web/ok.py", "from illumio_ops.services import x\nfrom illumio_ops.domain import y\n")
    assert find_layer_violations(iter_modules(root)) == []
