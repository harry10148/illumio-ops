"""Enablement detection + enable flow for the native Rule Hit Count feature."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.report.rule_hit_count_enablement import (
    EnablementError,
    EnablementStatus,
    RuleHitCountNotEnabled,
    check_enablement,
    enable_rule_hit_count,
)


def _api(tpl=(200, {"enabled": True}), fw=(200, {"rule_hit_count_enabled_scopes": [[]]})):
    api = MagicMock()
    api.api_cfg = {"org_id": 1}

    def _get(endpoint, timeout=15):
        if "report_templates" in endpoint:
            return tpl
        if "firewall_settings" in endpoint:
            return fw
        raise AssertionError(f"unexpected GET {endpoint}")

    api._api_get.side_effect = _get
    return api


class TestCheckEnablement(unittest.TestCase):
    def test_enabled_both_sides(self):
        st = check_enablement(_api())
        self.assertEqual(st.state, "enabled")
        self.assertTrue(st.pce_report_enabled)
        self.assertTrue(st.ven_scopes_enabled)

    def test_disabled_both_sides(self):
        st = check_enablement(_api(tpl=(200, {"enabled": False}),
                                   fw=(200, {"rule_hit_count_enabled_scopes": []})))
        self.assertEqual(st.state, "disabled")

    def test_partial_pce_only(self):
        st = check_enablement(_api(fw=(200, {"rule_hit_count_enabled_scopes": []})))
        self.assertEqual(st.state, "partial")
        self.assertTrue(st.pce_report_enabled)
        self.assertFalse(st.ven_scopes_enabled)

    def test_template_404_means_unsupported(self):
        st = check_enablement(_api(tpl=(404, None)))
        self.assertEqual(st.state, "unsupported")

    def test_connection_failure_raises(self):
        with self.assertRaises(ConnectionError):
            check_enablement(_api(tpl=(0, None)))


class TestEnable(unittest.TestCase):
    def _api_ok(self):
        api = MagicMock()
        api.api_cfg = {"org_id": 1}
        api._api_put.return_value = 204
        api._api_post.return_value = (201, {})
        return api

    def test_enable_all_vens_runs_three_steps_in_order(self):
        api = self._api_ok()
        steps = enable_rule_hit_count(api)
        self.assertEqual(steps, ["pce_report_template", "ven_firewall_settings_draft", "provisioned"])
        # PCE template first
        first = api._api_put.call_args_list[0]
        self.assertIn("report_templates/rule_hit_count_report", first.args[0])
        self.assertEqual(first.args[1], {"enabled": True})
        # VEN draft second — all VENs is [[]]
        second = api._api_put.call_args_list[1]
        self.assertIn("sec_policy/draft/firewall_settings", second.args[0])
        self.assertEqual(second.args[1], {"rule_hit_count_enabled_scopes": [[]]})
        # provision third
        prov = api._api_post.call_args
        self.assertIn("/sec_policy", prov.args[0])
        self.assertEqual(
            prov.args[1]["change_subset"],
            {"firewall_settings": [{"href": "/orgs/1/sec_policy/draft/firewall_settings"}]})
        self.assertEqual(prov.args[1]["update_description"], "Enable rule hit count (illumio-ops)")

    def test_enable_with_label_scopes(self):
        api = self._api_ok()
        scopes = [[{"label": {"href": "/orgs/1/labels/7"}}]]
        enable_rule_hit_count(api, scopes=scopes)
        second = api._api_put.call_args_list[1]
        self.assertEqual(second.args[1], {"rule_hit_count_enabled_scopes": scopes})

    def test_failure_mid_way_stops_and_reports_steps_done(self):
        api = self._api_ok()
        api._api_put.side_effect = [204, 500]   # PCE ok, VEN draft fails
        with self.assertRaises(EnablementError) as ctx:
            enable_rule_hit_count(api)
        self.assertEqual(ctx.exception.steps_done, ["pce_report_template"])
        api._api_post.assert_not_called()   # provision must NOT run after failure


class TestNotEnabledException(unittest.TestCase):
    def test_carries_status(self):
        st = EnablementStatus(state="disabled", pce_report_enabled=False,
                              ven_scopes_enabled=False, detail="x")
        exc = RuleHitCountNotEnabled(st)
        self.assertIs(exc.status, st)


if __name__ == "__main__":
    unittest.main()
