"""Static pin: 'alert_siem_backlog' sits in its alphabetically-correct spot
(after the alert_sev_* block, before alert_snap_*) in both locale files, kept
in sync (Hardening Follow-ups §F.4, 2026-07-10 sweep)."""
from pathlib import Path

_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")


def _assert_alphabetical_position(text: str) -> None:
    i_prev = text.index('"alert_sev_warning"')
    i_key = text.index('"alert_siem_backlog"')
    i_next = text.index('"alert_snap_col_connections"')
    assert i_prev < i_key < i_next


def test_alert_siem_backlog_alphabetical_position_en():
    _assert_alphabetical_position(_EN.read_text(encoding="utf-8"))


def test_alert_siem_backlog_alphabetical_position_zh():
    _assert_alphabetical_position(_ZH.read_text(encoding="utf-8"))
