"""Gate 6: every SQLite table has exactly one writing module (illumio_ops.store.ownership)."""
from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from illumio_ops.store.ownership import TABLE_OWNERS
from tests_v6.gates._scan import PKG_ROOT, Module, iter_modules

_T = r"""["`\[]?(\w+)["`\]]?"""
_WRITES = [
    re.compile(rf"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+{_T}", re.IGNORECASE),
    re.compile(rf"\bREPLACE\s+INTO\s+{_T}", re.IGNORECASE),
    re.compile(rf"\bUPDATE\s+(?:OR\s+\w+\s+)?{_T}\s+SET\b", re.IGNORECASE),
    re.compile(rf"\bDELETE\s+FROM\s+{_T}", re.IGNORECASE),
]
_UPSERT_TAIL = re.compile(r"\bDO\s+UPDATE\s+SET\b", re.IGNORECASE)


def _strings(tree: ast.Module) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value, node.lineno
        elif isinstance(node, ast.JoinedStr):
            parts = [v.value if isinstance(v, ast.Constant) else " x " for v in node.values]
            yield "".join(str(p) for p in parts), node.lineno


def written_tables(sql: str) -> set[str]:
    sql = _UPSERT_TAIL.sub(" ", sql)  # an upsert's DO UPDATE SET has no table name
    return {m.group(1).lower() for rx in _WRITES for m in rx.finditer(sql)}


def find_foreign_writers(modules: Iterable[Module], owners: dict[str, str] = TABLE_OWNERS) -> list[str]:
    out = []
    for name, tree, path in modules:
        for text, line in _strings(tree):
            for table in written_tables(text):
                owner = owners.get(table)
                if owner is None:
                    out.append(f"{path}:{line}: writes unregistered table {table}")
                elif owner != name:
                    out.append(f"{path}:{line}: writes {table} owned by {owner}")
    return out


def test_no_foreign_writers():
    assert find_foreign_writers(iter_modules(PKG_ROOT)) == []


def _tree(tmp_path: Path, rel: str, src: str) -> Path:
    root = tmp_path / "illumio_ops"
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").touch()
    f.write_text(src)
    return root


def test_injected_foreign_write_is_caught(tmp_path):
    root = _tree(tmp_path, "web/bad.py", 'SQL = "INSERT INTO job_health (job_id) VALUES (?)"\n')
    assert len(find_foreign_writers(iter_modules(root))) == 1


def test_injected_foreign_replace_is_caught(tmp_path):
    root = _tree(tmp_path, "web/bad.py", 'SQL = "REPLACE INTO job_health (job_id) VALUES (?)"\n')
    assert len(find_foreign_writers(iter_modules(root))) == 1


def test_injected_update_and_delete_are_caught(tmp_path):
    root = _tree(tmp_path, "web/bad.py",
                 'A = "UPDATE job_health SET runs = 0"\nB = "delete from `pce_probe`"\n')
    assert len(find_foreign_writers(iter_modules(root))) == 2


def test_unregistered_table_write_is_caught(tmp_path):
    root = _tree(tmp_path, "jobs/health.py", 'SQL = "INSERT INTO mystery (x) VALUES (1)"\n')
    assert "unregistered" in find_foreign_writers(iter_modules(root))[0]


def test_owner_upsert_is_clean(tmp_path):
    root = _tree(tmp_path, "jobs/health.py",
                 'SQL = ("INSERT INTO job_health (job_id) VALUES (?) "\n'
                 '       "ON CONFLICT(job_id) DO UPDATE SET runs = runs + 1")\n')
    assert find_foreign_writers(iter_modules(root)) == []


def test_foreign_write_to_flowdb_table_is_caught(tmp_path):
    root = _tree(tmp_path, "web/bad.py", 'SQL = "DELETE FROM flows WHERE id = ?"\n')
    [violation] = find_foreign_writers(iter_modules(root))
    assert "owned by illumio_ops.store.flowdb.flows" in violation
