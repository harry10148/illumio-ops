"""Records the BASELINE count of inline-styled hand-rolled UI patterns.

This file's threshold numbers are intentionally permissive on day 0.
Each Task N.B in the component abstraction plan tightens the threshold.
When all migrations are done, thresholds should approach 0 (a few stragglers
acceptable - they will be listed explicitly in Task 8 wrap-up).
"""
from __future__ import annotations

from tests._inline_scanner import (
    count_inline_empty_states,
    count_inline_fieldset_sections,
    count_inline_filter_bar_buttons,
    count_inline_kpi_cards,
    count_inline_status_pills,
    count_inline_styled_tables,
)


# Day-0 baseline values measured during recon (2026-05-15).
# Adjust the right-hand limit downward in each Task N.B step.
BASELINES: dict[str, int] = {
    "kpi_cards": 0,           # all migrated to .kpi-card (Task 1)
    "status_pills": 3,        # 2 of 5 migrated in Task 2; 3 remain (uncovered/bandwidth tables)
    "filter_bar_buttons": 0,  # all 4 migrated in Task 3 (traffic + workload toolbars)
    "empty_states": 41,       # 3 of 44 migrated in Task 4 (traffic + workload + events)
    "fieldset_sections": 5,   # fieldsets with style= attribute in index.html
    "styled_tables": 15,      # <table class="rule-table" style="..."> (measured)
}


def test_kpi_baseline_not_exceeded():
    assert count_inline_kpi_cards() <= BASELINES["kpi_cards"]


def test_status_pill_baseline_not_exceeded():
    assert count_inline_status_pills() <= BASELINES["status_pills"]


def test_filter_bar_baseline_not_exceeded():
    assert count_inline_filter_bar_buttons() <= BASELINES["filter_bar_buttons"]


def test_empty_state_baseline_not_exceeded():
    assert count_inline_empty_states() <= BASELINES["empty_states"]


def test_fieldset_baseline_not_exceeded():
    assert count_inline_fieldset_sections() <= BASELINES["fieldset_sections"]


def test_styled_table_baseline_not_exceeded():
    assert count_inline_styled_tables() <= BASELINES["styled_tables"]
