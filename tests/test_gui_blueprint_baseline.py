"""Route-map snapshot test for the H5 Blueprint split.

Compares the Flask URL map against a baseline captured from the pre-split
__init__.py. Deleted in Task 12 once the split is complete.
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

_BASELINE_PATH = Path(__file__).parent / "_gui_route_baseline.json"


@pytest.fixture(scope="module")
def _app():
    from src.config import ConfigManager
    from src.gui import build_app
    cm = ConfigManager()
    return build_app(cm)


def _current_rules(app) -> list[dict]:
    return [
        {
            "url": r.rule,
            "endpoint": r.endpoint,
            "methods": sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS")),
        }
        for r in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, sorted(r.methods)))
    ]


def test_route_count_matches_baseline(_app):
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    current = _current_rules(_app)
    assert len(current) == len(baseline), (
        f"Route count changed: baseline={len(baseline)}, current={len(current)}\n"
        f"Added: {[r['url'] for r in current if r not in baseline]}\n"
        f"Removed: {[r['url'] for r in baseline if r not in current]}"
    )


def test_all_baseline_routes_present(_app):
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    current = _current_rules(_app)
    current_set = {(r["url"], tuple(r["methods"])) for r in current}
    missing = [
        r for r in baseline
        if (r["url"], tuple(r["methods"])) not in current_set
    ]
    assert not missing, f"Missing routes: {missing}"
