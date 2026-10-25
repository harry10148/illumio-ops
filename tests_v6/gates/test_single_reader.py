"""Gate: flows and events are read only through FlowSource / EventSource (and the collectors and the
collection status that own them). 5.x read the cache in four places with two meanings of "mixed"."""
from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from tests_v6.gates._scan import PKG_ROOT, Module, iter_modules

_READ = re.compile(r"\b(?:FROM|JOIN)\s+[\"`\[]?(flows|events)[\"`\]]?\b", re.IGNORECASE)
_SCOPES = ("illumio_ops.services", "illumio_ops.web")
ALLOWED = (
    "illumio_ops.services.flowsource",
    "illumio_ops.services.eventsource",
    "illumio_ops.services.collect",  # collectors, archive, status: they own the data they read
)


def find_direct_reads(modules: Iterable[Module]) -> list[str]:
    out = []
    for name, tree, path in modules:
        if not name.startswith(_SCOPES) or name.startswith(ALLOWED):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _READ.search(node.value):
                out.append(f"{path}:{node.lineno}: reads {_READ.search(node.value).group(1)} directly")
    return out


def test_no_direct_flow_reads_outside_sources():
    assert find_direct_reads(iter_modules(PKG_ROOT)) == []


def _tree(tmp_path: Path, rel: str, src: str) -> Path:
    root = tmp_path / "illumio_ops"
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").touch()
    f.write_text(src)
    return root


def test_injected_direct_read_is_caught(tmp_path):
    root = _tree(tmp_path, "web/routes/bad.py", 'SQL = "SELECT * FROM flows WHERE is_primary = 1"\n')
    assert len(find_direct_reads(iter_modules(root))) == 1
    root = _tree(tmp_path / "b", "services/report.py", 'SQL = "select x from x JOIN `events` e on 1"\n')
    assert len(find_direct_reads(iter_modules(root))) == 1


def test_owner_reads_are_allowed(tmp_path):
    root = _tree(tmp_path, "services/flowsource.py", 'SQL = "SELECT * FROM flows"\n')
    assert find_direct_reads(iter_modules(root)) == []
    assert ast  # module used
