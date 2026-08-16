"""Guard against `src` imports creeping back into conftest.py's module scope.

Why this matters: CI runs the bare `pytest` console script (see
.github/workflows/ci.yml), which does NOT add the repository root to
sys.path. `python -m pytest` (used for local verification throughout this
project) DOES add it, via runpy's sys.path[0] handling. A module-level
`from src... import ...` (or `import src...`) in tests/conftest.py is
therefore invisible locally but fails collection in CI with
`ModuleNotFoundError: No module named 'src'` — see
tests/conftest.py's fixture functions, which import `src` internally for
exactly this reason.

This test parses conftest.py's AST (rather than importing it, which would
just re-trigger the same failure under the console script and require the
repo root already be on sys.path to even collect) and fails if any
top-level Import/ImportFrom statement names the `src` package. Imports of
`src` inside function bodies (executed lazily, once collection has already
put the repo root on sys.path) are fine and are not flagged.
"""

import ast
import os


def _module_level_src_imports(tree: ast.Module) -> list[str]:
    """Return descriptions of any top-level (not nested in a def/class) import of `src`."""
    offenders = []
    for node in tree.body:  # tree.body is only *top-level* statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "src" or alias.name.startswith("src."):
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "src" or node.module.startswith("src.")):
                offenders.append(f"line {node.lineno}: from {node.module} import ...")
    return offenders


def test_conftest_has_no_module_level_src_import():
    """conftest.py must not import `src` at module scope.

    Regression guard for the CI break where `tests/conftest.py:15` had a
    module-level `from src.loguru_config import _StdLibInterceptHandler`:
    it collected fine under `python -m pytest` (used for every local
    verification in this project) but raised
    `ModuleNotFoundError: No module named 'src'` under the bare `pytest`
    console script CI actually runs, failing collection for the entire
    suite before a single test executed.

    This assertion fails if a module-level `src` import is reintroduced
    (proven by running it against the pre-fix conftest.py, where it was
    red) and passes once the import is moved inside the fixture/function
    that needs it, matching every other `src` import already in this file.
    """
    conftest_path = os.path.join(os.path.dirname(__file__), "conftest.py")
    with open(conftest_path, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=conftest_path)
    offenders = _module_level_src_imports(tree)

    assert not offenders, (
        "tests/conftest.py imports `src` at module scope, which breaks "
        "collection under CI's bare `pytest` console script (no repo root "
        "on sys.path) even though it passes locally under `python -m "
        "pytest`. Move the import(s) inside the function/fixture that "
        f"needs them instead:\n" + "\n".join(offenders)
    )
