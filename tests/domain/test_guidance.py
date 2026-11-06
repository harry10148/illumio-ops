"""What to do next, per alert (parity audit 2026-11-06 A3): 5.x mailed a remediation per event type; v6 said what
happened and stopped. The steps are keyed by what fired — the PCE event type, the system check, the detector — so a
rule an operator wrote about the same event gets them too."""
import pytest

from illumio_ops.domain.alerting import (
    EVENT_MESSAGE_KEYS,
    EVENT_SUBJECT_KEYS,
    LATERAL_MESSAGE_KEYS,
    SYSTEM_MESSAGE_KEYS,
)
from illumio_ops.domain.alertpack import _EVENTS, HIGH_BLOCKED
from illumio_ops.domain.guidance import guide_keys
from illumio_ops.domain.values import DetectorKind, Language, SystemCheck
from illumio_ops.i18n import dictionary


def _all_keys():
    out = set()
    for _key, types, *_ in _EVENTS:
        for t in types.split(","):
            keys = guide_keys(EVENT_MESSAGE_KEYS[next(iter(EVENT_MESSAGE_KEYS))], {"event_types": [t]}, None)
            assert keys, t  # every event type the pack alerts on has a next step
            out |= set(keys)
    for check in SystemCheck:
        keys = guide_keys(SYSTEM_MESSAGE_KEYS[check], {}, None)
        assert keys, check
        out |= set(keys)
    for kind in DetectorKind:
        keys = guide_keys(LATERAL_MESSAGE_KEYS[kind], {}, None)
        assert keys, kind
        out |= set(keys)
    keys = guide_keys("alert_traffic", {}, HIGH_BLOCKED)
    assert keys
    return out | set(keys)


@pytest.mark.parametrize("lang", list(Language))
def test_every_step_is_written_in_both_languages(lang):
    words = dictionary(lang)
    assert all(k in words and words[k].strip() for k in _all_keys())


def test_event_alert_steps_follow_its_event_types_once_each():
    keys = guide_keys(EVENT_SUBJECT_KEYS["actor"], {"event_types": ["rule_set.update", "sec_rule.create",
                                                                     "agent.tampering"]}, None)
    assert len(keys) == len(set(keys)) == 2  # rule set and rule changes share one step


def test_an_event_type_without_a_step_gets_none_rather_than_filler():
    assert guide_keys("alert_event_count", {"event_types": ["container_cluster.update"]}, None) == ()
    assert guide_keys("alert_volume", {}, "some_custom_pack") == ()  # an operator's own flow rule: they know why
