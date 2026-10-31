"""Shared AST scanning for the v6 gate tests."""
from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = REPO_ROOT / "illumio_ops"

Module = tuple[str, ast.Module, Path]


def iter_modules(pkg_root: Path) -> Iterator[Module]:
    """Yield (dotted module name, parsed AST, path) for every .py under pkg_root."""
    base = pkg_root.parent
    for path in sorted(pkg_root.rglob("*.py")):
        rel = path.relative_to(base).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        yield ".".join(parts), ast.parse(path.read_text(encoding="utf-8"), filename=str(path)), path


def imported_modules(name: str, tree: ast.Module, is_package: bool) -> Iterator[tuple[str, int]]:
    """Absolute dotted names a module imports (relative imports resolved), with line numbers."""
    pkg = name if is_package else name.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = pkg.split(".")
                anchor = ".".join(parts[: len(parts) - (node.level - 1)])
                mod = f"{anchor}.{node.module}" if node.module else anchor
            else:
                mod = node.module or ""
            yield mod, node.lineno
            for a in node.names:  # `from illumio_ops import web` imports a subpackage
                yield f"{mod}.{a.name}", node.lineno


def subpackage(dotted: str) -> str | None:
    """'illumio_ops.web.app' -> 'web'; 'illumio_ops.paths' -> 'paths'; non-package -> None."""
    parts = dotted.split(".")
    if parts[0] != "illumio_ops" or len(parts) < 2:
        return None
    return parts[1]
