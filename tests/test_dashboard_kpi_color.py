"""Dashboard top 3 KPI cards: 健康摘要 / 事件查詢 should render in --color-success
(green) when their state is healthy, not --accent2 (orange)."""
from __future__ import annotations

import re
from pathlib import Path


JS = Path(__file__).parent.parent / "src" / "static" / "js" / "dashboard.js"
CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def test_ensure_layout_sets_ok_class_for_cooldown_and_pce_health():
    """ensureDashboardLayout must add 'value-ok' (or class 'ok') to cards[1]
    and cards[2] .value elements so they render green by default."""
    js = JS.read_text(encoding="utf-8")
    # Capture the ensureDashboardLayout body
    m = re.search(r"function ensureDashboardLayout\([^)]*\)\s*\{(.*?)\n\s*dashboard\.dataset\.layoutReady",
                  js, flags=re.DOTALL)
    assert m, "ensureDashboardLayout function body not found"
    body = m.group(1)
    # Expect at least 2 'classList.add' calls inside this function with 'ok'
    adds = re.findall(r"\.value[^;\n]*classList\.add\(\s*['\"]ok['\"]\s*\)", body)
    assert len(adds) >= 2, (
        f"Expected >=2 `.value.classList.add('ok')` inside ensureDashboardLayout, got {len(adds)}"
    )


def test_card_value_ok_uses_color_success_token():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.card\s+\.value\.ok\s*\{([^}]*)\}", css)
    assert m, ".card .value.ok rule not found"
    body = m.group(1)
    assert "var(--color-success)" in body, (
        f"`.card .value.ok` should use var(--color-success), got: {body!r}"
    )


def test_card_value_err_uses_color_danger_token():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.card\s+\.value\.err\s*\{([^}]*)\}", css)
    assert m, ".card .value.err rule not found"
    body = m.group(1)
    assert "var(--color-danger)" in body, (
        f"`.card .value.err` should use var(--color-danger), got: {body!r}"
    )
