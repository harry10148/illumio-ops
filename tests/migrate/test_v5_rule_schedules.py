"""5.x rule schedules (config/rule_schedules.json) → v6 paused schedules (UI redesign spec §4.5): the operator turns
each on; nothing is checked against the PCE at upgrade time; what cannot be read is reported, not guessed."""
import json
from datetime import UTC, datetime

from illumio_ops.domain.rule_schedule import Expiry, Weekly
from illumio_ops.migrate.v5_rule_schedules import convert

RULE = "/orgs/1/sec_policy/active/rule_sets/5/sec_rules/9"
RS = "/orgs/1/sec_policy/active/rule_sets/6"


def _one(entry, href=RULE, zone="Asia/Taipei"):
    done, items = convert({href: entry}, local_zone=zone)
    return done, items


def test_recurring_becomes_paused_weekly():
    done, items = _one({"type": "recurring", "name": "r9", "detail_name": "Vendor access", "is_ruleset": False,
                        "action": "allow", "days": ["Monday", "wed", "FRI"], "start": "09:00", "end": "18:00",
                        "timezone": "Asia/Taipei", "detail_rs": "Vendor", "detail_src": "Vendor-VPN",
                        "detail_dst": "jump-02", "detail_svc": "3389"})
    [s] = done
    assert s.href == RULE and s.name == "Vendor access" and s.ruleset_name == "Vendor"
    assert s.summary == "Vendor-VPN → jump-02: 3389" and not s.is_ruleset
    assert s.plan == Weekly(days=("mon", "wed", "fri"), start="09:00", end="18:00", timezone="Asia/Taipei",
                            action="enable_in_window")
    assert [(i.action, i.reason_key) for i in items] == [("rewritten", "migrate_rule_schedule_paused")]


def test_one_time_naive_expiry_in_item_timezone():
    [s], _ = _one({"type": "one_time", "name": "tmp", "is_ruleset": True, "expire_at": "2026-12-01T00:00",
                   "timezone": "Asia/Taipei"}, href=RS)
    assert s.is_ruleset and s.plan == Expiry(expire_at=datetime(2026, 11, 30, 16, tzinfo=UTC), timezone="Asia/Taipei")


def test_local_timezone_resolved_or_reported():
    [s], _ = _one({"type": "recurring", "name": "r", "action": "allow", "days": ["mon"], "start": "08:00",
                   "end": "09:00", "timezone": "local"}, zone="Europe/Berlin")
    assert s.plan.timezone == "Europe/Berlin"
    [u], items = _one({"type": "recurring", "name": "r", "action": "allow", "days": ["mon"], "start": "08:00",
                       "end": "09:00"}, zone=None)
    assert u.plan.timezone == "UTC" and items[0].reason_key == "migrate_rule_schedule_paused_utc"


def test_utc_offset_zone():
    [s], _ = _one({"type": "recurring", "name": "r", "action": "allow", "days": ["mon"], "start": "08:00",
                   "end": "09:00", "timezone": "UTC+8"})
    assert s.plan.timezone == "Etc/GMT-8"


def test_action_mapping():
    for action, want in (("allow", "enable_in_window"), ("block", "disable_in_window"),
                         ("disable", "disable_in_window")):
        [s], _ = _one({"type": "recurring", "name": "r", "action": action, "days": ["sun"], "start": "22:00",
                       "end": "06:00", "timezone": "Asia/Taipei"})
        assert s.plan.action == want


def test_invalid_entries_reported_not_migrated():
    bad = {"/orgs/1/sec_policy/active/rule_sets/1": {"type": "recurring", "name": "a", "action": "allow",
                                                     "days": ["mon"], "start": "8", "end": "09:00"},
           "/orgs/1/sec_policy/active/rule_sets/2": {"type": "recurring", "name": "b", "action": "allow",
                                                     "days": ["mon"], "start": "09:00", "end": "09:00"},
           "/orgs/1/sec_policy/active/rule_sets/3": {"type": "one_time", "name": "c", "expire_at": "soon"},
           "/orgs/1/workloads/x": {"type": "recurring", "name": "d"},
           "/orgs/1/sec_policy/active/rule_sets/4": {"type": "weird", "name": "e"}}
    done, items = convert(bad, local_zone="UTC")
    assert done == [] and len(items) == 5
    assert all(i.action == "dropped" and i.reason_key == "migrate_rule_schedule_unreadable" for i in items)


def test_nothing_to_migrate():
    done, items = convert(None, local_zone="UTC")
    assert done == [] and [i.reason_key for i in items] == ["migrate_rule_schedule_none"]


def test_entries_serialise():
    [s], _ = _one({"type": "recurring", "name": "r", "action": "allow", "days": ["mon"], "start": "08:00",
                   "end": "09:00", "timezone": "Asia/Taipei"})
    assert json.loads(s.plan.model_dump_json())["kind"] == "weekly"
