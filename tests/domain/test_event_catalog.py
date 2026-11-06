"""The event catalog the alert rule editor offers (5.x parity 2026-11-06)."""
from illumio_ops.domain.alertpack import best_practice_rules
from illumio_ops.domain.alertrules import EventRule
from illumio_ops.domain.event_catalog import CATEGORY_KEYS, EVENT_DESC_KEYS, catalog
from illumio_ops.domain.events import PRECURSOR_EVENT_TYPES
from illumio_ops.domain.tamper import TIMELINE_EVENT_TYPES


def test_every_event_type_v6_names_is_in_the_catalog():
    """Checked against what this build itself reads: the pack's event rules, the tamper timeline, the precursors."""
    known = {e.event_type for e in catalog()}
    pack = {t for r in best_practice_rules(notify_new_defaults=True) if isinstance(r, EventRule) for t in r.event_types}
    assert pack - known == set()
    assert set(TIMELINE_EVENT_TYPES) - known == set()
    assert set(PRECURSOR_EVENT_TYPES) - known == set()


def test_each_type_once_with_a_category_and_a_description():
    events = catalog()
    assert len({e.event_type for e in events}) == len(events) > 250
    assert {e.category for e in events} <= set(CATEGORY_KEYS)
    assert set(EVENT_DESC_KEYS) == {e.event_type for e in events}


def test_the_pack_sets_a_status_only_on_types_marked_for_it():
    marked = {e.event_type for e in catalog() if e.status_filter}
    for r in best_practice_rules(notify_new_defaults=True):
        if isinstance(r, EventRule) and r.status not in ("all", "*", "any", ""):
            assert set(r.event_types) <= marked, r.pack_key
