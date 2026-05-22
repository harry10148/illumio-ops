import ast
from pathlib import Path

TARGETS = [
    "src/pce_cache/traffic_filter.py",
    "src/pce_cache/backfill.py",
    "src/pce_cache/ingestor_traffic.py",
    "src/events/poller.py",
]


def test_md5_sha1_marked_usedforsecurity_false():
    root = Path(__file__).resolve().parent.parent
    for rel in TARGETS:
        src = (root / rel).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else "")
                if name in ("md5", "sha1"):
                    kw_names = {kw.arg for kw in node.keywords}
                    assert "usedforsecurity" in kw_names, (
                        f"{rel} line {node.lineno}: {name}() must have usedforsecurity= kwarg"
                    )
