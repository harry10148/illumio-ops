"""Operations menu must contain Theme/Density rows + Logs/Stop items.
Stop item must be styled .danger.
The four controls must NOT exist outside of the menu panel."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "templates" / "index.html"


def _panel_body() -> str:
    html = INDEX.read_text(encoding="utf-8")
    # Capture from id="hdr-menu-panel" opening tag through its matching </div>.
    # The panel ends before either </div> </div> <div class="tabs" or end of header-right.
    m = re.search(
        r'id="hdr-menu-panel"[^>]*>(.*?)(?=</div>\s*</div>\s*<div class="tabs"|</div>\s*</header>)',
        html, flags=re.DOTALL,
    )
    assert m, "could not locate hdr-menu-panel body"
    return m.group(1)


def test_menu_contains_theme_and_density_selects() -> None:
    body = _panel_body()
    assert 'id="ui-theme-mode"' in body, "Theme select must be inside menu"
    assert 'id="ui-density"' in body, "Density select must be inside menu"


def test_menu_contains_logs_and_stop() -> None:
    body = _panel_body()
    assert 'data-action="mlOpen"' in body, "Logs item must be inside menu"
    assert 'data-action="stopGui"' in body, "Stop item must be inside menu"


def test_stop_item_has_danger_class() -> None:
    body = _panel_body()
    m = re.search(r'<button[^>]*data-action="stopGui"[^>]*>', body)
    assert m, "Stop button not found"
    assert "danger" in m.group(0)


def test_no_stray_controls_outside_menu() -> None:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(
        r'<div class="header-right">(.*?)<div[^>]*id="hdr-menu-panel"',
        html, flags=re.DOTALL,
    )
    assert m, "header-right not found before panel"
    pre = m.group(1)
    forbidden = ['id="ui-theme-mode"', 'id="ui-density"',
                 'data-action="mlOpen"', 'data-action="stopGui"']
    leaks = [f for f in forbidden if f in pre]
    assert not leaks, f"controls left outside menu: {leaks}"
