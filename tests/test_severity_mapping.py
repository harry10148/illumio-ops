"""All 8 official event severities (emerg/alert/crit/err/warning/notice/info/debug)
must map to a label and a canonical rank."""
from __future__ import annotations

from src.reporter import Reporter

OFFICIAL_SEVERITIES = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]


def test_every_official_severity_has_i18n_key():
    for sev in OFFICIAL_SEVERITIES:
        assert sev in Reporter._SEVERITY_I18N_KEYS, f"missing severity mapping: {sev}"


def test_highest_severity_ranks_all_official_values():
    assert Reporter._highest_severity([{"severity": "notice"}]) == "info"
    assert Reporter._highest_severity([{"severity": "debug"}]) == "info"
    assert Reporter._highest_severity([{"severity": "notice"}, {"severity": "crit"}]) == "critical"
