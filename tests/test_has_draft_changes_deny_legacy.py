"""has_draft_changes 父 RuleSet 檢查涵蓋 deny rules 與 legacy rules（backlog #7）。

修前只認 "/sec_rules/"：toggle_and_provision 對任何非 ruleset href 都會推出
父 ruleset 整個 provision（"/".join(draft_href.split("/")[:7])），但 deny
rules（可排程，見 gui/routes/rule_scheduler.py）與 legacy "/rules/" collection
（同檔 :158 仍接受）走的正是這條路——父 ruleset 有 pending draft 時卻不會被
擋下，等同繞過 sec_rules 才有的 fail-closed 保護。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


def _make_client():
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "key",
            "secret": "secret",
            "verify_ssl": False,
        }
    }
    return ApiClient(cm)


def _fake_get(item_href, parent_href):
    """回傳一個 _api_get side_effect：item 本身沒有 draft，父 ruleset 有。"""
    def _get(href):
        if href == item_href:
            return (200, {"update_type": None})
        if href == parent_href:
            return (200, {"update_type": "update"})
        raise AssertionError(f"unexpected href queried: {href}")
    return _get


class TestHasDraftChangesParentCollections(unittest.TestCase):
    def test_deny_rule_parent_ruleset_draft_is_detected(self):
        item = "/orgs/1/sec_policy/draft/rule_sets/1/deny_rules/5"
        parent = "/orgs/1/sec_policy/draft/rule_sets/1"
        client = _make_client()
        client._api_get = MagicMock(side_effect=_fake_get(item, parent))
        self.assertTrue(client.has_draft_changes(item))

    def test_legacy_rules_parent_ruleset_draft_is_detected(self):
        item = "/orgs/1/sec_policy/draft/rule_sets/1/rules/5"
        parent = "/orgs/1/sec_policy/draft/rule_sets/1"
        client = _make_client()
        client._api_get = MagicMock(side_effect=_fake_get(item, parent))
        self.assertTrue(client.has_draft_changes(item))

    def test_sec_rule_parent_ruleset_draft_still_detected(self):
        # 既有行為（回歸防護）：不能因為新增分支而弄壞原本的 sec_rules 檢查。
        item = "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/5"
        parent = "/orgs/1/sec_policy/draft/rule_sets/1"
        client = _make_client()
        client._api_get = MagicMock(side_effect=_fake_get(item, parent))
        self.assertTrue(client.has_draft_changes(item))

    def test_deny_rule_without_parent_draft_returns_false(self):
        item = "/orgs/1/sec_policy/draft/rule_sets/1/deny_rules/5"
        client = _make_client()
        client._api_get = MagicMock(return_value=(200, {"update_type": None}))
        self.assertFalse(client.has_draft_changes(item))


if __name__ == "__main__":
    unittest.main()
