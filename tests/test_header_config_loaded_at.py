"""The header 'Loaded' timestamp must reflect the actual last config load,
not datetime.now() at template-render time (which always shows 'just now').

Phase 2A Task 11 note — a REMOVED feature, recorded rather than quietly
dropped: the v2 GUI's chrome (src/static/js/v2/shell.mjs: brand, six-area
nav, palette button, user menu, health rail) has no config-load timestamp
at all, so `/` no longer renders one. auth.py's index() therefore computes
no timestamp of any kind, which is a stronger form of the same guarantee —
the defect this file guards (a "Loaded" chip that is really a render clock)
cannot exist in a route that renders no clock. The first test below asserts
exactly that; the ConfigManager property test is unchanged and still passes
(note that `cm.last_loaded_at` now has no consumer in src/ — pre-existing
dead code this task did not create and did not remove).
"""
from __future__ import annotations

import re
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "src" / "gui" / "routes" / "auth.py"


def test_index_route_renders_no_render_time_clock() -> None:
    """auth.py index() must not compute any timestamp for the page it renders.

    Originally: "must not assign config_loaded_at = datetime.now(), must read
    cm.last_loaded_at instead". The v2 shell dropped the header chip that
    consumed it (see this module's docstring), so index() passes no timestamp
    at all — and a route that hands the template no clock cannot hand it a
    wrong one. A regression that re-introduces a server-rendered timestamp
    turns this red and has to re-answer the original question.
    """
    src = AUTH.read_text(encoding="utf-8")
    m = re.search(r"def index\(\).*?(?=\n    @bp\.route|\n    def [a-z])",
                  src, flags=re.DOTALL)
    assert m, "could not locate index() in auth.py"
    body = m.group(0)
    assert "datetime.now()" not in body, (
        f"index() still uses datetime.now() for a rendered timestamp:\n{body}"
    )
    assert "config_loaded_at" not in body, (
        "index() renders a config_loaded_at again — if the v2 chrome grew a "
        "'Loaded' chip, it must read cm.last_loaded_at, never render time:\n"
        f"{body}"
    )


def test_config_manager_exposes_last_loaded_at(tmp_path) -> None:
    """ConfigManager must expose a last_loaded_at attribute that updates on load()."""
    from src.config import ConfigManager
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"rules": [], "report_schedules": [], "settings": {}}',
                   encoding="utf-8")
    cm = ConfigManager(str(cfg))
    cm.load()
    t1 = cm.last_loaded_at
    assert t1 is not None
    time.sleep(0.05)
    cm.load()
    t2 = cm.last_loaded_at
    assert t2 >= t1, f"last_loaded_at must monotonically advance: {t1} -> {t2}"
