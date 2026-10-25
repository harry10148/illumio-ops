"""Gate 7: nothing in the package depends on the process working directory."""
from __future__ import annotations

import ast
from collections.abc import Iterable

from tests_v6.gates._scan import PKG_ROOT, Module, iter_modules

CWD_CALLS = {("os", "getcwd"), ("os", "getcwdb"), ("os", "chdir"), ("Path", "cwd"), ("pathlib.Path", "cwd")}


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def find_cwd_uses(modules: Iterable[Module]) -> list[str]:
    out = []
    for _name, tree, path in modules:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and (_dotted(f.value), f.attr) in CWD_CALLS:
                out.append(f"{path}:{node.lineno}: {_dotted(f)}()")
            elif isinstance(f, ast.Name) and f.id in {"getcwd", "chdir"}:
                out.append(f"{path}:{node.lineno}: {f.id}()")
            elif (isinstance(f, ast.Name) and f.id == "open" and node.args
                  and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                  and not node.args[0].value.startswith("/")):
                out.append(f"{path}:{node.lineno}: open({node.args[0].value!r}) relative path")
    return out


def test_no_cwd_dependence():
    assert find_cwd_uses(iter_modules(PKG_ROOT)) == []


def test_injected_cwd_uses_are_caught(tmp_path):
    root = tmp_path / "illumio_ops"
    root.mkdir()
    (root / "__init__.py").touch()
    (root / "bad.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "os.getcwd()\nPath.cwd()\nopen('config/x.json')\nos.chdir('/')\n"
    )
    (root / "ok.py").write_text("open('/etc/hosts')\nopen(p)\n")
    assert len(find_cwd_uses(iter_modules(root))) == 4
