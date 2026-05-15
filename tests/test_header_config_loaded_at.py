"""The header 'Loaded' timestamp must reflect the actual last config load,
not datetime.now() at template-render time (which always shows 'just now')."""
from __future__ import annotations

import re
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "src" / "gui" / "routes" / "auth.py"


def test_index_route_does_not_use_datetime_now_for_config_loaded_at() -> None:
    """auth.py index() must not assign config_loaded_at = datetime.now()."""
    src = AUTH.read_text(encoding="utf-8")
    m = re.search(r"def index\(\).*?(?=\n    @bp\.route|\n    def [a-z])",
                  src, flags=re.DOTALL)
    assert m, "could not locate index() in auth.py"
    body = m.group(0)
    assert "_dt.datetime.now()" not in body and "datetime.now()" not in body, (
        f"index() still uses datetime.now() for config_loaded_at:\n{body}"
    )
    # And must reference cm.last_loaded_at (the new property)
    assert "last_loaded_at" in body, (
        "index() should read cm.last_loaded_at (or equivalent) for header"
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
