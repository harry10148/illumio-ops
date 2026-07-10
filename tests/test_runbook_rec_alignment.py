"""Keep the two parallel advice systems (reporter _REC_I18N_KEYS and
events.runbooks) aligned with each other and with the catalog."""
from __future__ import annotations

from src.events.catalog import KNOWN_EVENT_TYPES
from src.events.runbooks import RUNBOOK_CATEGORIES, runbook_for
from src.reporter import Reporter


def _all_runbook_patterns() -> set[str]:
    return {p for cat in RUNBOOK_CATEGORIES.values() for p in cat["patterns"]}


def test_every_rec_key_is_a_known_event_type():
    unknown = set(Reporter._REC_I18N_KEYS) - set(KNOWN_EVENT_TYPES)
    assert not unknown, f"_REC_I18N_KEYS references unknown event types: {sorted(unknown)}"


def test_every_rec_key_has_a_runbook():
    missing = set(Reporter._REC_I18N_KEYS) - _all_runbook_patterns()
    assert not missing, f"_REC_I18N_KEYS entries without runbook coverage: {sorted(missing)}"


def test_every_runbook_pattern_is_a_known_event_type():
    unknown = _all_runbook_patterns() - set(KNOWN_EVENT_TYPES)
    assert not unknown, f"runbook patterns reference unknown event types: {sorted(unknown)}"


def test_capacity_category_exists_with_valid_severity():
    cat = RUNBOOK_CATEGORIES["pce-capacity"]
    assert cat["severity_hint"] == "critical"
    assert "database.temp_table_autocleanup_started" in cat["patterns"]


def test_prune_response_mentions_limit_semantics():
    rb = runbook_for("system_task.prune_old_log_events")
    assert rb is not None
    assert "hard limit" in rb["response"].lower()
