"""The cross-checker must not use the code it checks (spec §2, the first anti-goal): every module under
illumio_ops/crosscheck imports only the standard library and the whitelist in the plan's Global Constraints."""
from __future__ import annotations

import sys
from pathlib import Path

from tests.gates._scan import PKG_ROOT, imported_modules, iter_modules

SCOPE = "illumio_ops.crosscheck"
# A target is allowed when it equals an entry or lies under it (`from x.client import PceClient` yields x.client.PceClient).
ALLOWED_PREFIXES = (
    SCOPE,
    "illumio_ops.pce.client",
    "illumio_ops.pce.async_query",
    "illumio_ops.pce.timefmt",
    "illumio_ops.pce.rate_limit",
    "illumio_ops.settings",
    "illumio_ops.paths",
    "illumio_ops.domain.event_catalog",
    "illumio_ops.domain.values",
)
# The root package only for its version string (the report header names the version); not a prefix.
ALLOWED_EXACT = frozenset({"illumio_ops", "illumio_ops.__version__"})


def _allowed(target: str) -> bool:
    top = target.split(".", 1)[0]
    if top != "illumio_ops":
        return top in sys.stdlib_module_names
    return target in ALLOWED_EXACT or any(target == p or target.startswith(p + ".") for p in ALLOWED_PREFIXES)


def scanned(pkg_root: Path) -> list[str]:
    return [name for name, _tree, _path in iter_modules(pkg_root) if name == SCOPE or name.startswith(SCOPE + ".")]


def find_violations(pkg_root: Path) -> list[str]:
    """pkg_root is an `illumio_ops` package directory; only its crosscheck sub-package is checked."""
    out = []
    for name, tree, path in iter_modules(pkg_root):
        if not (name == SCOPE or name.startswith(SCOPE + ".")):
            continue
        for target, line in imported_modules(name, tree, path.name == "__init__.py"):
            if not _allowed(target):
                out.append(f"{path}:{line}: imports {target}")
    return sorted(set(out))


def test_crosscheck_imports_only_the_whitelist():
    names = scanned(PKG_ROOT)
    # Not vacuous: the package is really there and scanned.
    assert {SCOPE, f"{SCOPE}.__main__", f"{SCOPE}.io", f"{SCOPE}.model"} <= set(names)
    assert find_violations(PKG_ROOT) == []


def _pkg(tmp_path: Path, src: str) -> Path:
    root = tmp_path / "illumio_ops"
    (root / "crosscheck").mkdir(parents=True)
    (root / "__init__.py").touch()
    (root / "crosscheck" / "__init__.py").touch()
    (root / "crosscheck" / "bad.py").write_text(src, encoding="utf-8")
    return root


def test_injected_eventsource_import_is_caught(tmp_path):
    root = _pkg(tmp_path, "from illumio_ops.services.eventsource import EventSource\n")
    v = find_violations(root)
    assert v and all("illumio_ops.services.eventsource" in s for s in v)


def test_injected_lazy_forms_are_caught(tmp_path):
    root = _pkg(tmp_path, "from illumio_ops import services\nfrom ..domain import alerts\nimport illumio_ops.pce.events\n"
                          "import requests\nfrom illumio_ops.store.db import connect\n")
    v = "\n".join(find_violations(root))
    for target in ("illumio_ops.services", "illumio_ops.domain.alerts", "illumio_ops.pce.events", "requests",
                   "illumio_ops.store.db"):
        assert f"imports {target}" in v, target


def test_whitelisted_imports_are_clean(tmp_path):
    root = _pkg(tmp_path, "from __future__ import annotations\nimport sqlite3, json\n"
                          "from illumio_ops import __version__\n"
                          "from illumio_ops.pce.client import PceClient\nfrom illumio_ops.pce.rate_limit import RateLimiter\n"
                          "from illumio_ops.settings.store import SettingsStore\nfrom illumio_ops.paths import resolve_paths\n"
                          "from illumio_ops.domain.event_catalog import catalog\nfrom . import model\n")
    assert find_violations(root) == []
