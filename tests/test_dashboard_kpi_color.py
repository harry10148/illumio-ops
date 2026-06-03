"""Dashboard story KPI cards should render in --color-success (green) when their
state is healthy, not --accent2 (orange).

Since the overview redesign (commit 5e67b0f), card colour is driven by
``_dashboardSetCard(id, value, state)`` during the data refresh rather than by a
default class applied in ``ensureDashboardLayout`` (which now only marks layout
ready). The health card must pass the 'ok' state when ``health_check`` is true.
"""
from __future__ import annotations

import re
from pathlib import Path


JS = Path(__file__).parent.parent / "src" / "static" / "js" / "dashboard.js"
CSS = Path(__file__).parent.parent / "src" / "static" / "css" / "app.css"


def test_health_card_renders_ok_state_when_healthy():
    """The health KPI card must use the 'ok' (green) state when health_check is
    true, via _dashboardSetCard during the dashboard refresh."""
    js = JS.read_text(encoding="utf-8")
    m = re.search(
        r"_dashboardSetCard\(\s*'d-health'.*?d\.health_check\s*\?\s*'ok'\s*:\s*'warn'",
        js, flags=re.DOTALL,
    )
    assert m, "d-health card should render 'ok' (green) when health_check is true"


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
