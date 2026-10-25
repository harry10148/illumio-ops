"""Gate 2: no print() in the package (rescue.py is the one CLI surface allowed to)."""
from __future__ import annotations

import ast
from collections.abc import Iterable

from tests_v6.gates._scan import PKG_ROOT, Module, iter_modules

EXEMPT = {"illumio_ops.rescue"}


def find_prints(modules: Iterable[Module]) -> list[str]:
    out = []
    for name, tree, path in modules:
        if name in EXEMPT:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                out.append(f"{path}:{node.lineno}")
    return out


def test_no_print():
    assert find_prints(iter_modules(PKG_ROOT)) == []


def test_injected_print_is_caught(tmp_path):
    root = tmp_path / "illumio_ops"
    (root / "web").mkdir(parents=True)
    (root / "__init__.py").touch()
    (root / "web" / "bad.py").write_text('print("x")\n')
    (root / "rescue.py").write_text('print("allowed")\n')
    assert len(find_prints(iter_modules(root))) == 1
