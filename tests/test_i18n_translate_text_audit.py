"""Phase 2 invariant: _translate_text() must not run in the t() hot path."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "i18n" / "engine.py"


def test_translate_text_not_called_from_build_messages() -> None:
    """Walk engine.py AST: _build_messages must NOT invoke _translate_text."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_messages":
            calls = [
                n for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_translate_text"
            ]
            assert not calls, (
                f"_build_messages still invokes _translate_text at lines "
                f"{[c.lineno for c in calls]}; Phase 2 requires removing this."
            )
            return
    raise AssertionError("_build_messages function not found in engine.py")
