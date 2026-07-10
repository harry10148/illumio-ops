"""Tests for the Rule Hit Count report generator (and the shared rule baseline)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.report.policy_usage_generator import build_rule_baseline


def _sample_rulesets():
    return [{
        "href": "/orgs/1/sec_policy/draft/rule_sets/10",
        "name": "RS-A",
        "scopes": [[{"label": {"href": "/orgs/1/labels/1"}}]],
        "rules": [
            {"href": "/orgs/1/sec_policy/draft/rule_sets/10/sec_rules/100",
             "enabled": True, "description": "allow web",
             "consumers": [{"actors": "ams"}],
             "providers": [{"label": {"href": "/orgs/1/labels/2"}}],
             "ingress_services": [{"port": 443, "proto": 6}]},
        ],
        "deny_rules": [
            {"href": "/orgs/1/sec_policy/draft/rule_sets/10/deny_rules/200",
             "enabled": True, "override": True},
        ],
    }]


class TestBuildRuleBaseline(unittest.TestCase):
    def test_flattens_and_annotates(self):
        flat_rules, ruleset_map = build_rule_baseline(_sample_rulesets())
        self.assertEqual(len(flat_rules), 2)
        self.assertEqual(ruleset_map["/orgs/1/sec_policy/draft/rule_sets/10"], "RS-A")
        allow, deny = flat_rules
        self.assertEqual(allow["_rule_type"], "Allow")
        self.assertEqual(allow["_ruleset_name"], "RS-A")
        self.assertEqual(allow["_rule_no"], 1)
        self.assertEqual(allow["_rule_id"], "100")
        self.assertEqual(deny["_rule_type"], "Override Deny")
        self.assertEqual(deny["_rule_no"], 2)


if __name__ == "__main__":
    unittest.main()
