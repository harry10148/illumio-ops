"""The CLI wizard's report-type table must cover every schedulable type.

`_generate_report` in src/report_scheduler.py is the authority on which report
types a schedule can produce; `VALID_REPORT_TYPES` is the frozenset that
dispatch chain is mirrored by. The CLI wizard used to hard-code three of the
eleven, so editing e.g. a `readiness` schedule fell through to the "1" default
and one Enter silently rewrote it to `traffic`.

This guard is deliberately a module-level assertion about a module-level
constant rather than a check inside the prompt flow, because
docs/superpowers/plans/2026-08-07-phase2c-cli.md Task 13 will restyle that
wizard — a restyling pass can drop a line inside a function without anything
noticing, but it cannot drop `type_map` without this test going red.
"""


def test_cli_type_map_covers_every_schedulable_type():
    from src.report_scheduler import VALID_REPORT_TYPES
    from src.cli.menus import report_schedule as rs
    assert set(rs.type_map.values()) == set(VALID_REPORT_TYPES), (
        "CLI 精靈的型別對照表與後端分派鏈不同步：編輯未涵蓋的型別會被靜默改掉"
    )
