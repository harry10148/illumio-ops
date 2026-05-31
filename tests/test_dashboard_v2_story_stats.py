"""Regression test: dashboard.js must populate the 6 Phase 3.1 story-stat
IDs and must NOT mutate story-card label/id pairs at runtime.

Bug context: ensureDashboardLayout() previously did `cards[1].value.id = 'd-cooldown'`
which (after Phase 3.1 story-card refactor) re-assigned the story-card 規則數
value element to id `d-cooldown`, breaking the rules-count display. The
v2 loadDashboard also only setCard'd 3 legacy IDs, leaving 5 new story-stat
IDs at the placeholder `-` forever.

dashboard_v2.js was retired in Phase 3.1 Task 9; all functionality lives in
dashboard.js. This test now guards dashboard.js directly.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src" / "static" / "js" / "dashboard.js"


def test_ensure_layout_does_not_reassign_card_ids():
    """dashboard.js must not change `cards[N].value.id` — index.html
    is now the source of truth for story-card IDs."""
    js = JS.read_text(encoding="utf-8")
    # The legacy bug pattern was: `value.id = 'd-cooldown'` / `value.id = 'd-pce-health'`
    assert "value.id = 'd-cooldown'" not in js, (
        "dashboard.js must not reassign value.id to 'd-cooldown' — "
        "this overwrites Phase 3.1 story-card markup"
    )
    assert "value.id = 'd-pce-health'" not in js, (
        "dashboard.js must not reassign value.id to 'd-pce-health'"
    )


def test_ensure_layout_does_not_hide_cards_by_index():
    """The legacy `cards.forEach((c, idx) => { if (idx > 2) c.style.display = 'none' })`
    incorrectly hid Phase 3.1 story-cards that share the .card class."""
    js = JS.read_text(encoding="utf-8")
    assert "if (idx > 2) card.style.display = 'none'" not in js


def test_load_dashboard_populates_six_story_stats():
    """loadDashboard() must populate all 6 story-stat IDs from real-time /api/status data."""
    js = JS.read_text(encoding="utf-8")
    required_ids = ['d-rules', 'd-health', 'd-event-poll',
                    'd-dispatch', 'd-unknown', 'd-suppressed']
    missing = [i for i in required_ids if f"'{i}'" not in js]
    assert not missing, (
        f"dashboard.js loadDashboard must reference these story-stat IDs: {missing}"
    )
