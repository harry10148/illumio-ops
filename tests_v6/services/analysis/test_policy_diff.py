"""Policy diff from the PCE (P5c-3): Draft and active read live, each change attributed from the event store by the
href its events name (5.x matched names)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.pce.policy import PendingItem, PolicyNames
from illumio_ops.services.analysis import policy_diff
from tests_v6.domain.test_policy_diff import A, D, rs, rule
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_audit import _write, event

NOW = datetime(2026, 10, 30, 1, tzinfo=UTC)
START, END = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC)


class FakePolicy:
    def __init__(self):
        self.sets = {"draft": [rs(D, rules=[rule(D, 1), rule(D, 2)])], "active": [rs(A, rules=[rule(A, 1)])]}
        self.objects = {("draft", "ip_lists"): [{"href": f"{D}/ip_lists/1", "name": "L", "ip_ranges": [{"from_ip": "a"}]}],
                        ("active", "ip_lists"): []}
        self.pending = [PendingItem(kind="rule_sets", href=f"{D}/rule_sets/1", name="Web", update_type="update",
                                    updated_at=None),
                        PendingItem(kind="firewall_settings", href=f"{D}/firewall_settings", name=None,
                                    update_type="update", updated_at=None)]
        self.fail = None

    def install(self, monkeypatch):
        def rule_sets(client, pversion, *, deadline):
            if self.fail:
                raise self.fail
            return self.sets[pversion]
        monkeypatch.setattr(policy_diff, "fetch_rule_sets", rule_sets)
        monkeypatch.setattr(policy_diff, "fetch_objects",
                            lambda client, pversion, kind, *, deadline: self.objects.get((pversion, kind), []))
        monkeypatch.setattr(policy_diff, "fetch_policy_names",
                            lambda client, pversion, *, deadline: PolicyNames(labels={}, names={}))
        monkeypatch.setattr(policy_diff, "fetch_pending", lambda client, *, deadline: self.pending)
        return self


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


@pytest.fixture
def pce(monkeypatch):
    return FakePolicy().install(monkeypatch)


def _changed(href, at, user, etype="sec_rule.create"):
    return event(etype, at, user=user, extra={"resource_changes": [
        {"resource_type": etype.split(".")[0], "href": href, "change_type": "create", "changes": {}}]})


def test_changes_found(ctx, pce):
    d = policy_diff.policy_diff(ctx, start=START, end=END, now=NOW)
    assert [(c.kind, c.change, c.ref, c.field) for c in d.changes] == [
        ("rule_set", "modified", "1", "rule_count"), ("rule", "added", "sec_rules/2", "*"), ("ip_list", "added", "1", "*")]


def test_attribution_by_href(ctx, pce):
    _write(ctx, [_changed(f"{D}/rule_sets/1/sec_rules/2", datetime(2026, 10, 27, 8, tzinfo=UTC), "admin@lab"),
                 _changed(f"{D}/rule_sets/1/sec_rules/9", datetime(2026, 10, 28, tzinfo=UTC), "other")])
    d = policy_diff.policy_diff(ctx, start=START, end=END, now=NOW)
    a = d.attribution[f"{D}/rule_sets/1/sec_rules/2"]
    assert (a.actor, a.event_type) == ("admin@lab", "sec_rule.create")


def test_attribution_latest_wins(ctx, pce):
    href = f"{D}/rule_sets/1/sec_rules/2"
    _write(ctx, [_changed(href, datetime(2026, 10, 10, tzinfo=UTC), "first"),
                 _changed(href, datetime(2026, 10, 20, tzinfo=UTC), "second", "sec_rule.update")])
    assert policy_diff.policy_diff(ctx, start=START, end=END, now=NOW).attribution[href].actor == "second"


def test_no_event_left_blank(ctx, pce):
    assert policy_diff.policy_diff(ctx, start=START, end=END, now=NOW).attribution == {}


def test_other_pending_listed(ctx, pce):
    d = policy_diff.policy_diff(ctx, start=START, end=END, now=NOW)
    assert [p.kind for p in d.other_pending] == ["firewall_settings"]


def test_fetch_failure_raises(ctx, pce):
    """Review Focus 1: a failed read is never an empty side (that would read as everything removed)."""
    pce.fail = PceCollectionIncomplete("/sec_policy/active/rule_sets", 0, "HTTP 500")
    with pytest.raises(PceCollectionIncomplete):
        policy_diff.policy_diff(ctx, start=START, end=END, now=NOW)


def test_removed_rule_attributed(ctx, pce):
    """Final review #3: a deletion's event names the Draft href."""
    pce.sets = {"draft": [rs(D)], "active": [rs(A, rules=[rule(A, 4)])]}
    _write(ctx, [_changed(f"{D}/rule_sets/1/sec_rules/4", datetime(2026, 10, 27, tzinfo=UTC), "remover",
                          "sec_rule.delete")])
    d = policy_diff.policy_diff(ctx, start=START, end=END, now=NOW)
    assert d.attribution[f"{D}/rule_sets/1/sec_rules/4"].actor == "remover"
