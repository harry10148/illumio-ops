"""get_all_rulesets raise_on_error — enrichment 失敗訊號鏈（真 PCE 驗證 v1 項 6）。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


class TestGetAllRulesetsRaiseOnError(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")

    def tearDown(self):
        self._td.cleanup()

    def test_default_returns_empty_on_http_error(self):
        # 零行為變更釘：預設仍回 []（rule_scheduler/policy_diff 等呼叫端依賴）
        self.client._api_get = lambda ep, timeout=15: (403, None)
        self.assertEqual(self.client.get_all_rulesets(), [])

    def test_raise_on_error_raises_on_http_error(self):
        self.client._api_get = lambda ep, timeout=15: (403, None)
        with self.assertRaises(RuntimeError) as ctx:
            self.client.get_all_rulesets(raise_on_error=True)
        self.assertIn("403", str(ctx.exception))

    def test_raise_on_error_raises_on_connection_layer_failure(self):
        # _request 連線層失敗慣例：status 0（v1 報告附註的未驗證縫，一併涵蓋）
        self.client._api_get = lambda ep, timeout=15: (0, None)
        with self.assertRaises(RuntimeError):
            self.client.get_all_rulesets(raise_on_error=True)

    def test_raise_on_error_returns_data_on_200(self):
        rs = [{"href": "/orgs/1/sec_policy/draft/rule_sets/1", "rules": []}]
        self.client._api_get = lambda ep, timeout=15: (200, rs)
        self.assertEqual(self.client.get_all_rulesets(raise_on_error=True), rs)

    def test_raise_on_error_empty_200_is_legit_empty(self):
        # 200 且空 list = 合法空 org，不 raise
        self.client._api_get = lambda ep, timeout=15: (200, [])
        self.assertEqual(self.client.get_all_rulesets(raise_on_error=True), [])
