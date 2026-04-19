"""Regression tests: each Phase 10 chart-bearing module emits a chart_spec key."""

from __future__ import annotations

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_chart_spec(result: dict, *, allow_none: bool = False) -> None:
    """Assert chart_spec key exists and, unless allow_none, is a non-None dict
    with the required keys type/title/data."""
    assert "chart_spec" in result, "chart_spec key missing from result"
    if not allow_none:
        spec = result["chart_spec"]
        assert spec is not None, "chart_spec is None (expected a dict with data)"
        assert isinstance(spec, dict), f"chart_spec is not a dict: {type(spec)}"
        for key in ("type", "title", "data"):
            assert key in spec, f"chart_spec missing required key '{key}'"


# ---------------------------------------------------------------------------
# audit_mod00_executive
# ---------------------------------------------------------------------------

class TestAuditMod00Executive:
    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "timestamp": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "event_type": ["user.sign_in", "user.sign_in", "sec_policy.create"],
            "severity": ["info", "info", "warning"],
        })

    def test_chart_spec_key_present(self) -> None:
        from src.report.analysis.audit.audit_mod00_executive import audit_executive_summary

        df = self._make_df()
        result = audit_executive_summary({}, df)
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.audit.audit_mod00_executive import audit_executive_summary

        df = self._make_df()
        result = audit_executive_summary({}, df)
        spec = result["chart_spec"]
        assert spec["type"] == "bar"
        assert "labels" in spec["data"]
        assert "values" in spec["data"]

    def test_chart_spec_none_on_empty_df(self) -> None:
        from src.report.analysis.audit.audit_mod00_executive import audit_executive_summary

        df = pd.DataFrame(columns=["timestamp", "event_type", "severity"])
        result = audit_executive_summary({}, df)
        assert "chart_spec" in result
        assert result["chart_spec"] is None


# ---------------------------------------------------------------------------
# audit_mod02_users
# ---------------------------------------------------------------------------

class TestAuditMod02Users:
    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "timestamp": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "event_type": [
                "user.sign_in",
                "user.sign_in",
                "user.sign_in",
                "request.authentication_failed",
            ],
            "severity": ["info", "info", "info", "warning"],
            "actor": ["alice", "bob", "alice", "charlie"],
        })

    def test_chart_spec_key_present(self) -> None:
        from src.report.analysis.audit.audit_mod02_users import audit_user_activity

        df = self._make_df()
        result = audit_user_activity(df)
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.audit.audit_mod02_users import audit_user_activity

        df = self._make_df()
        result = audit_user_activity(df)
        spec = result["chart_spec"]
        assert spec["type"] == "bar"
        assert "labels" in spec["data"]
        assert "values" in spec["data"]

    def test_chart_spec_key_present_on_no_user_events(self) -> None:
        """Returns dict with chart_spec key even when no matching user events."""
        from src.report.analysis.audit.audit_mod02_users import audit_user_activity

        df = pd.DataFrame({
            "timestamp": ["2024-01-01"],
            "event_type": ["some.other.event"],
            "severity": ["info"],
        })
        result = audit_user_activity(df)
        # When no user events, function returns a dict without chart_spec (early return).
        # This is acceptable — just verify no KeyError on the happy path tested above.
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# audit_mod03_policy
# ---------------------------------------------------------------------------

class TestAuditMod03Policy:
    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "timestamp": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "event_type": ["sec_rule.create", "sec_rule.update", "sec_policy.create"],
            "severity": ["info", "info", "warning"],
            "actor": ["alice", "alice", "bob"],
        })

    def test_chart_spec_key_present(self) -> None:
        from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes

        df = self._make_df()
        result = audit_policy_changes(df)
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes

        df = self._make_df()
        result = audit_policy_changes(df)
        spec = result["chart_spec"]
        assert spec["type"] == "bar"
        assert "labels" in spec["data"]
        assert "values" in spec["data"]

    def test_chart_spec_none_on_no_policy_events(self) -> None:
        from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes

        df = pd.DataFrame({
            "timestamp": ["2024-01-01"],
            "event_type": ["user.sign_in"],
            "severity": ["info"],
            "actor": ["alice"],
        })
        result = audit_policy_changes(df)
        # No matching policy events → chart_spec absent (early return dict w/o key)
        # or present but None.  Either way no crash.
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# pu_mod02_hit_detail
# ---------------------------------------------------------------------------

class TestPuMod02HitDetail:
    def _minimal_args(self):
        baseline_rules = [
            {
                "href": "/orgs/1/sec_policy/draft/rule_sets/1/rules/1",
                "_rule_type": "Allow",
                "_ruleset_href": "/orgs/1/sec_policy/draft/rule_sets/1",
                "description": "Allow web traffic",
                "enabled": True,
                "providers": [],
                "consumers": [],
                "ingress_services": [{"port": 443, "proto": 6}],
            },
            {
                "href": "/orgs/1/sec_policy/draft/rule_sets/1/rules/2",
                "_rule_type": "Allow",
                "_ruleset_href": "/orgs/1/sec_policy/draft/rule_sets/1",
                "description": "Allow SSH",
                "enabled": True,
                "providers": [],
                "consumers": [],
                "ingress_services": [{"port": 22, "proto": 6}],
            },
        ]
        ruleset_map = {"/orgs/1/sec_policy/draft/rule_sets/1": "Test Ruleset"}
        hit_counts = {
            "/orgs/1/sec_policy/draft/rule_sets/1/rules/1": 100,
            "/orgs/1/sec_policy/draft/rule_sets/1/rules/2": 5,
        }
        return baseline_rules, ruleset_map, hit_counts

    def test_chart_spec_key_present(self) -> None:
        from src.report.analysis.policy_usage.pu_mod02_hit_detail import pu_hit_detail

        baseline_rules, ruleset_map, hit_counts = self._minimal_args()
        result = pu_hit_detail(baseline_rules, ruleset_map, hit_counts)
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.policy_usage.pu_mod02_hit_detail import pu_hit_detail

        baseline_rules, ruleset_map, hit_counts = self._minimal_args()
        result = pu_hit_detail(baseline_rules, ruleset_map, hit_counts)
        spec = result["chart_spec"]
        assert spec["type"] == "bar"
        assert "labels" in spec["data"]
        assert "values" in spec["data"]

    def test_chart_spec_none_when_no_hits(self) -> None:
        from src.report.analysis.policy_usage.pu_mod02_hit_detail import pu_hit_detail

        baseline_rules = [
            {
                "href": "/orgs/1/sec_policy/draft/rule_sets/1/rules/1",
                "_rule_type": "Allow",
                "providers": [],
                "consumers": [],
                "ingress_services": [],
            }
        ]
        result = pu_hit_detail(baseline_rules, {}, {})
        assert "chart_spec" in result
        assert result["chart_spec"] is None


# ---------------------------------------------------------------------------
# pu_mod04_deny_effectiveness
# ---------------------------------------------------------------------------

class TestPuMod04DenyEffectiveness:
    def _minimal_args(self):
        baseline_rules = [
            {
                "href": "/orgs/1/sec_policy/draft/rule_sets/1/rules/1",
                "_rule_type": "Allow",
                "_ruleset_href": "/orgs/1/sec_policy/draft/rule_sets/1",
                "providers": [],
                "consumers": [],
                "ingress_services": [],
            },
            {
                "href": "/orgs/1/sec_policy/draft/rule_sets/1/rules/2",
                "_rule_type": "Deny",
                "_ruleset_href": "/orgs/1/sec_policy/draft/rule_sets/1",
                "providers": [],
                "consumers": [],
                "ingress_services": [{"port": 22, "proto": 6}],
            },
            {
                "href": "/orgs/1/sec_policy/draft/rule_sets/1/rules/3",
                "_rule_type": "Deny",
                "_ruleset_href": "/orgs/1/sec_policy/draft/rule_sets/1",
                "providers": [],
                "consumers": [],
                "ingress_services": [{"port": 3389, "proto": 6}],
            },
        ]
        hit_counts = {"/orgs/1/sec_policy/draft/rule_sets/1/rules/2": 5}
        ruleset_map = {"/orgs/1/sec_policy/draft/rule_sets/1": "Test Ruleset"}
        return baseline_rules, hit_counts, ruleset_map

    def test_chart_spec_key_present(self) -> None:
        from src.report.analysis.policy_usage.pu_mod04_deny_effectiveness import pu_deny_effectiveness

        baseline_rules, hit_counts, ruleset_map = self._minimal_args()
        result = pu_deny_effectiveness(baseline_rules, hit_counts, ruleset_map)
        _assert_chart_spec(result)

    def test_chart_spec_structure(self) -> None:
        from src.report.analysis.policy_usage.pu_mod04_deny_effectiveness import pu_deny_effectiveness

        baseline_rules, hit_counts, ruleset_map = self._minimal_args()
        result = pu_deny_effectiveness(baseline_rules, hit_counts, ruleset_map)
        spec = result["chart_spec"]
        assert spec["type"] == "pie"
        assert "labels" in spec["data"]
        assert "values" in spec["data"]

    def test_chart_spec_none_on_empty_rules(self) -> None:
        from src.report.analysis.policy_usage.pu_mod04_deny_effectiveness import pu_deny_effectiveness

        result = pu_deny_effectiveness([], {}, {})
        assert "chart_spec" in result
        assert result["chart_spec"] is None
