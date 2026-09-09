"""Tests for src/events/shadow.py — diagnostic comparison tool.

shadow.py is retained because:
- It powers the /api/events/rule_test GUI endpoint (the alert-rule sandbox).
  /api/events/shadow_compare was retired 2026-09-09; the module stayed.
- matches_event_rule_legacy() implements the original analyzer algorithm (exact
  comma-separated type list, no regex/negation/pipe-alternation/nested fields).
  This intentionally different logic makes divergences from the current matcher
  visible to operators.

These tests guard against accidental regression of the legacy algorithm and the
compare_event_rules() diff logic.
"""

from __future__ import annotations

import pytest

from src.events.shadow import compare_event_rules, matches_event_rule_legacy


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def _event(event_type: str, status: str = "success", severity: str = "info", href: str | None = None) -> dict:
    base: dict = {"event_type": event_type, "status": status, "severity": severity}
    if href is not None:
        base["href"] = href
    return base


def _rule(filter_value: str, filter_status: str = "all", filter_severity: str = "all", rule_id: int = 1, name: str = "Rule 1") -> dict:
    return {
        "id": rule_id,
        "name": name,
        "type": "event",
        "filter_value": filter_value,
        "filter_status": filter_status,
        "filter_severity": filter_severity,
    }


# ---------------------------------------------------------------------------
# 1. matches_event_rule_legacy — basic contract
# ---------------------------------------------------------------------------

class TestMatchesEventRuleLegacy:
    """Unit tests for the legacy matching algorithm."""

    def test_exact_type_match(self):
        rule = _rule("rule_set.update")
        assert matches_event_rule_legacy(rule, _event("rule_set.update")) is True

    def test_type_mismatch(self):
        rule = _rule("rule_set.update")
        assert matches_event_rule_legacy(rule, _event("sec_policy.create")) is False

    def test_comma_separated_types_match_first(self):
        rule = _rule("rule_set.update, sec_policy.create")
        assert matches_event_rule_legacy(rule, _event("rule_set.update")) is True

    def test_comma_separated_types_match_second(self):
        rule = _rule("rule_set.update, sec_policy.create")
        assert matches_event_rule_legacy(rule, _event("sec_policy.create")) is True

    def test_comma_separated_types_no_match(self):
        rule = _rule("rule_set.update, sec_policy.create")
        assert matches_event_rule_legacy(rule, _event("user.create_session")) is False

    def test_status_filter_all_accepts_any(self):
        rule = _rule("rule_set.update", filter_status="all")
        assert matches_event_rule_legacy(rule, _event("rule_set.update", status="success")) is True
        assert matches_event_rule_legacy(rule, _event("rule_set.update", status="failure")) is True

    def test_status_filter_exact(self):
        rule = _rule("rule_set.update", filter_status="success")
        assert matches_event_rule_legacy(rule, _event("rule_set.update", status="success")) is True
        assert matches_event_rule_legacy(rule, _event("rule_set.update", status="failure")) is False

    def test_severity_filter_exact(self):
        rule = _rule("rule_set.update", filter_severity="err")
        assert matches_event_rule_legacy(rule, _event("rule_set.update", severity="err")) is True
        assert matches_event_rule_legacy(rule, _event("rule_set.update", severity="info")) is False

    def test_empty_filter_value_never_matches(self):
        rule = _rule("")
        assert matches_event_rule_legacy(rule, _event("rule_set.update")) is False

    def test_legacy_does_not_support_regex(self):
        """Legacy matcher treats patterns as literals, so regex chars don't expand."""
        rule = _rule("rule_set.*")
        # The literal string "rule_set.*" is not "rule_set.update", so no match.
        assert matches_event_rule_legacy(rule, _event("rule_set.update")) is False

    def test_legacy_does_not_support_pipe_alternation(self):
        """Legacy matcher does NOT split on '|', unlike the current matcher."""
        rule = _rule("rule_set.update|sec_policy.create")
        # The combined string is not a literal event_type, so both should miss.
        assert matches_event_rule_legacy(rule, _event("rule_set.update")) is False
        assert matches_event_rule_legacy(rule, _event("sec_policy.create")) is False

    def test_legacy_does_not_support_nested_field_matching(self):
        """match_fields keys in the rule are silently ignored by the legacy algorithm."""
        rule = {
            "id": 1,
            "name": "Nested",
            "type": "event",
            "filter_value": "rule_set.update",
            "filter_status": "all",
            "filter_severity": "all",
            "match_fields": {"created_by.user.username": "admin@lab.local"},
        }
        # Legacy ignores match_fields — it matches on type alone.
        assert matches_event_rule_legacy(rule, _event("rule_set.update")) is True


# ---------------------------------------------------------------------------
# 2. compare_event_rules — diff logic
# ---------------------------------------------------------------------------

class TestCompareEventRules:
    """Tests for the per-rule divergence comparison report."""

    def _make_events(self):
        """Return a small, deterministic event list with known hrefs."""
        return [
            {"href": "/orgs/1/events/e1", "event_type": "rule_set.update",   "status": "success", "severity": "info"},
            {"href": "/orgs/1/events/e2", "event_type": "sec_policy.create",  "status": "success", "severity": "info"},
            {"href": "/orgs/1/events/e3", "event_type": "user.create_session", "status": "success", "severity": "info"},
        ]

    def test_identical_matching_yields_same_status(self):
        """When both algorithms agree, status must be 'same'."""
        events = self._make_events()
        # A simple exact-type rule with no special syntax — both matchers agree.
        rules = [_rule("rule_set.update", rule_id=1)]
        result = compare_event_rules(rules, events)
        assert len(result) == 1
        item = result[0]
        assert item["status"] == "same"
        assert item["current_count"] == 1
        assert item["legacy_count"] == 1
        assert item["delta"] == 0
        assert item["only_current"] == []
        assert item["only_legacy"] == []

    def test_regex_pattern_current_more(self):
        """Current matcher supports regex; legacy does not.

        A regex pattern like 'rule_set\\..*' matches 'rule_set.update' in the
        current matcher but not in the legacy one, so current picks up extra
        events and status should be 'current_more'.
        """
        events = self._make_events()
        rules = [_rule("rule_set\\..*", rule_id=2, name="Regex rule")]
        result = compare_event_rules(rules, events)
        item = result[0]
        # Current matcher expands the regex, legacy sees it as a literal miss.
        assert item["status"] == "current_more"
        assert item["current_count"] == 1
        assert item["legacy_count"] == 0
        assert item["delta"] == 1
        assert len(item["only_current"]) == 1
        assert item["only_current"][0]["event_id"] == "/orgs/1/events/e1"

    def test_legacy_more_when_comma_list_used_and_regex_skips(self):
        """Comma-separated list matched by legacy but empty for current if pattern also looks like regex.

        We verify the 'legacy_more' branch by using a pattern that legacy accepts
        via comma-separation but that the current matcher rejects because of
        different whitespace normalisation edge-cases.  The simplest path: use
        legacy's comma-list of two types vs a rule that current won't match via
        pipe (since pipe IS supported by current but not legacy).
        We test the 'legacy_more' branch directly using a rule with no matches
        in current (empty filter_value) but that legacy somehow still won't match
        either — instead we synthesise the situation with pipe.
        """
        # Pipe-separated types: current matches both; legacy treats the combined
        # string as a literal (no match) — so current_more, not legacy_more.
        # To get legacy_more we need current to miss something legacy hits.
        # The only way that happens is if we give an exact literal that legacy
        # matches but current rejects due to regex parse error — that's fragile.
        # Instead, verify 'mixed' by giving a two-event list where one event only
        # current matches and another only legacy matches.

        e_regex  = {"href": "/orgs/1/events/regex-target",  "event_type": "rule_set.update",      "status": "success", "severity": "info"}
        e_literal = {"href": "/orgs/1/events/exact-target",  "event_type": "rule_set.update|extra", "status": "success", "severity": "info"}
        events = [e_regex, e_literal]

        # A rule whose filter_value is the pipe string.
        # - Current: treats "|" as alternation → matches e_regex ("rule_set.update") but not e_literal
        # - Legacy:  treats "rule_set.update|extra" as a literal → matches e_literal only
        rule = _rule("rule_set.update|extra", rule_id=3, name="Mixed")
        result = compare_event_rules([rule], events)
        item = result[0]
        assert item["status"] == "mixed"
        assert item["current_count"] == 1
        assert item["legacy_count"] == 1
        assert item["delta"] == 0
        # Each side should see exactly the event the other misses.
        current_ids = {e["event_id"] for e in item["only_current"]}
        legacy_ids  = {e["event_id"] for e in item["only_legacy"]}
        assert "/orgs/1/events/regex-target"  in current_ids
        assert "/orgs/1/events/exact-target"  in legacy_ids

    def test_no_events_yields_same_with_zero_counts(self):
        """With an empty event list both counters are 0 and status is 'same'."""
        rules = [_rule("rule_set.update", rule_id=4)]
        result = compare_event_rules(rules, [])
        item = result[0]
        assert item["status"] == "same"
        assert item["current_count"] == 0
        assert item["legacy_count"] == 0

    def test_only_legacy_list_capped_at_five(self):
        """only_legacy list must be capped at 5 even when there are more matches."""
        # The legacy matcher uses a literal match. Build 10 events that all have
        # the same literal event type that legacy will match but current won't
        # (we use a type string that looks like regex to current).
        event_type = "policy.update$"  # trailing '$' makes current treat it as regex anchor
        events = [
            {"href": f"/orgs/1/events/e{i}", "event_type": event_type, "status": "success", "severity": "info"}
            for i in range(10)
        ]
        rules = [_rule(event_type, rule_id=5)]
        result = compare_event_rules(rules, events)
        item = result[0]
        # Current uses regex "^policy.update$$" which fails → 0 current matches
        # Legacy uses exact string match "policy.update$" → 10 legacy matches
        assert item["legacy_count"] == 10
        assert item["current_count"] == 0
        assert len(item["only_legacy"]) == 5  # capped at 5
        assert item["only_current"] == []


def test_the_retired_route_is_gone_but_the_sandbox_still_answers():
    """`/api/events/shadow_compare` 退役（2026-09-09），`rule_test` 沒有。

    兩條路由共用 `src/events/shadow.py`，所以「刪檔案」與「退一條路由」是
    兩件事——退役時把模組一起拿掉會靜默打斷告警規則沙盒（GUI 的 AL-07）。
    這條測試盯的就是那個分野：路由不在了，而模組提供的兩個函式仍然匯得出來，
    因為 rule_test 兩個都用。
    """
    import src.gui.routes.events as events_module
    from src.events import compare_event_rules, matches_event_rule_legacy

    source = open(events_module.__file__, encoding="utf-8").read()
    assert "@bp.route('/api/events/shadow_compare')" not in source
    assert "@bp.route('/api/events/rule_test')" in source
    assert callable(compare_event_rules) and callable(matches_event_rule_legacy)
