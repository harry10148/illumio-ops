"""ApiClient 錯誤訊號與快取契約（2026-07-25 審查修復的守門測試）。

涵蓋：
- get_provision_state 不得把「PCE 不可達 / 401 / 5xx」講成 'draft'
- check_and_create_quarantine_labels 不得把「標籤查詢失敗」退化成空 dict
- ruleset_cache 必須有 TTL、且本 client 改動 policy 後失效
- async job 記錄不得寫進 Analyzer 全份覆寫的 state.json
- service 顯示字串的協定名不得把非 UDP 一律當 TCP
"""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient
from src.exceptions import APIError
from src.state_store import load_state_file, update_state_file


def _client(tmpdir):
    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                         "key": "k", "secret": "s", "verify_ssl": True}}
    c = ApiClient(cm)
    c._state_file = os.path.join(tmpdir, "state.json")
    return c


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.client = _client(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class TestProvisionState(_Base):
    HREF = "/orgs/1/sec_policy/active/rule_sets/1/sec_rules/9"

    def test_200_is_active(self):
        self.client._request = lambda url, **kw: (200, b"{}")
        self.assertEqual(self.client.get_provision_state(self.HREF), "active")

    def test_404_is_draft(self):
        self.client._request = lambda url, **kw: (404, b"")
        self.assertEqual(self.client.get_provision_state(self.HREF), "draft")

    def test_connection_failure_and_error_statuses_are_unknown(self):
        """status 0 是 _request 對連線層失敗的契約回傳（它不 raise）——
        全歸成 'draft' 會把「PCE 連不上/憑證失效」說成「規則未佈署」。"""
        for status in (0, 401, 403, 500, 503):
            with self.subTest(status=status):
                self.client._request = lambda url, _s=status, **kw: (_s, b"")
                self.assertEqual(
                    self.client.get_provision_state(self.HREF), "unknown")
                # fail-closed 方向不變：unknown 一樣不算已佈署
                self.assertFalse(self.client.is_provisioned(self.HREF))


class TestQuarantineLabelLookupFailure(_Base):
    def test_lookup_failure_raises_instead_of_empty_dict(self):
        """查詢失敗與「org 沒有 Quarantine 標籤」不得同形：後者會讓解除隔離
        流程把仍被隔離的 workload 全記成 not_quarantined 並回 ok:true。"""
        self.client._request = lambda url, **kw: (503, b"")
        with self.assertRaises(APIError):
            self.client.check_and_create_quarantine_labels()

    def test_existing_labels_are_returned(self):
        labels = [{"key": "Quarantine", "value": lv, "href": f"/orgs/1/labels/{i}"}
                  for i, lv in enumerate(("Mild", "Moderate", "Severe"))]

        def fake(url, **kw):
            return 200, json.dumps(labels).encode()

        self.client._request = fake
        out = self.client.check_and_create_quarantine_labels()
        self.assertEqual(set(out), {"Mild", "Moderate", "Severe"})

    def test_get_labels_default_still_returns_empty_on_error(self):
        """零行為變更釘：預設呼叫端（reports/cli）仍拿 []。"""
        self.client._request = lambda url, **kw: (503, b"")
        self.assertEqual(self.client.get_labels("app"), [])


class TestRulesetCacheTtl(_Base):
    RS = [{"href": "/orgs/1/sec_policy/draft/rule_sets/1", "rules": []}]

    def test_cache_expires(self):
        calls = []

        def fake_collection(path, *, timeout=15):
            calls.append(path)
            return 200, self.RS, None

        self.client._get_collection = fake_collection
        self.assertEqual(self.client.get_all_rulesets(), self.RS)
        self.assertEqual(self.client.get_all_rulesets(), self.RS)
        self.assertEqual(len(calls), 1)          # TTL 內共用快取
        self.client._ruleset_cache_at = time.time() - 10_000
        self.client.get_all_rulesets()
        self.assertEqual(len(calls), 2)          # 過期後重抓

    def test_policy_mutation_invalidates_cache(self):
        calls = []

        def fake_collection(path, *, timeout=15):
            calls.append(path)
            return 200, self.RS, None

        self.client._get_collection = fake_collection
        self.client.get_all_rulesets()
        self.client.has_draft_changes = lambda href: False
        self.client._api_put = lambda href, body: 204
        self.client.provision_changes = lambda href: True
        self.client.toggle_and_provision(
            "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/9", False)
        self.client.get_all_rulesets()
        self.assertEqual(len(calls), 2, "改動 policy 後仍供應改動前的 ruleset 快照")


class TestAsyncJobStateIsolation(_Base):
    JOB = "/orgs/1/traffic_flows/async_queries/42"

    def test_async_job_records_are_not_written_to_state_json(self):
        """state.json 由 Analyzer 以整份覆寫維護，任何 cycle 中途寫進去的 key
        都會被還原——async job 記錄必須住在自己的檔案。"""
        self.client._save_async_job_state(self.JOB, status="completed")
        self.assertNotIn("async_query_jobs", load_state_file(self.client._state_file))
        self.assertIn(self.JOB,
                      load_state_file(self.client._jobs._async_state_file())
                      .get("async_query_jobs", {}))

    def test_records_survive_a_full_state_json_rewrite(self):
        """模擬 Analyzer cycle：以 cycle 開頭的快照整份覆寫 state.json。"""
        snapshot = load_state_file(self.client._state_file)
        self.client._save_async_job_state(self.JOB, status="completed",
                                          query_signature="sig")
        update_state_file(self.client._state_file, lambda _cur: dict(snapshot))
        jobs = self.client._jobs._load_async_job_states()
        self.assertIn(self.JOB, jobs)
        self.assertEqual(jobs[self.JOB]["query_signature"], "sig")

    def test_legacy_entries_are_migrated_out_of_state_json(self):
        legacy = {"async_query_jobs": {self.JOB: {"job_href": self.JOB,
                                                  "status": "completed"}}}
        update_state_file(self.client._state_file, lambda _cur: dict(legacy))
        jobs = self.client._jobs._load_async_job_states()
        self.assertIn(self.JOB, jobs)
        self.assertNotIn("async_query_jobs", load_state_file(self.client._state_file))


class TestServiceProtocolNames(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.client = _client(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_resolve_service_str_uses_real_protocol_names(self):
        self.assertEqual(
            self.client.resolve_service_str([{"port": 8, "proto": 1}]), "ICMP/8")
        self.assertEqual(
            self.client.resolve_service_str([{"port": 128, "proto": 58}]), "ICMPv6/128")
        self.assertEqual(
            self.client.resolve_service_str([{"port": 443, "proto": 6}]), "TCP/443")
        self.assertEqual(
            self.client.resolve_service_str([{"port": 53, "proto": 17}]), "UDP/53")
        # 未知編號回編號本身，不冒充 TCP
        self.assertEqual(
            self.client.resolve_service_str([{"port": 1, "proto": 99}]), "99/1")
        # 缺 proto 維持既有 TCP 預設
        self.assertEqual(
            self.client.resolve_service_str([{"port": 80}]), "TCP/80")

    def test_label_cache_service_display_uses_real_protocol_names(self):
        svc = {"href": "/orgs/1/sec_policy/draft/services/5", "name": "Ping",
               "service_ports": [{"port": 8, "proto": 1}]}

        def fake_collection(path, **kw):
            if path.endswith("/services"):
                return 200, [svc], None
            return 200, [], None

        self.client._get_collection = fake_collection
        self.assertTrue(self.client.update_label_cache(silent=True))
        self.assertEqual(self.client.label_cache[svc["href"]], "Ping (ICMP/8)")


class TestLookupMissDoesNotRefetch(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.client = _client(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_miss_after_fresh_refresh_does_not_refetch_collections(self):
        """resolver 查無時會帶 force_refresh 再抓一次，但剛全量刷新成功過的話
        那次重抓拿到同一份資料、註定再 miss——不得白打四個集合 GET。"""
        calls = []

        def fake_collection(path, **kw):
            calls.append(path)
            return 200, [], None

        self.client._get_collection = fake_collection
        self.assertIsNone(self.client._resolve_actor_filter("Env=NoSuch"))
        self.assertEqual(len(calls), 4, f"多做了額外的全集合抓取: {calls}")

    def test_stale_cache_still_refreshes(self):
        calls = []

        def fake_collection(path, **kw):
            calls.append(path)
            return 200, [], None

        self.client._get_collection = fake_collection
        self.client._resolve_actor_filter("Env=NoSuch")
        # 讓上次刷新落在退避窗之外
        self.client._query_lookup_cache_refreshed_at = time.time() - 10_000
        self.client._resolve_actor_filter("Env=NoSuch")
        self.assertEqual(len(calls), 8)


class TestLabelFilterSeparator(unittest.TestCase):
    def test_value_containing_colon_keeps_the_key(self):
        """GUI 送的是 key=value；值本身含 ':' 時仍須切在第一個分隔符。"""
        from src.api.labels import LabelResolver
        self.assertEqual(
            LabelResolver._normalize_label_filter("Loc=TW:TPE"), "Loc:TW:TPE")
        self.assertEqual(
            LabelResolver._normalize_label_filter("Loc:TW:TPE"), "Loc:TW:TPE")
        self.assertEqual(
            LabelResolver._normalize_label_filter("role=web"), "role:web")
        self.assertEqual(LabelResolver._normalize_label_filter("nosep"), "")


if __name__ == "__main__":
    unittest.main()


class TestInvalidateLabelsForcesRefetch(unittest.TestCase):
    """invalidate_labels() 的契約是「下次查詢必打 PCE」——negative-lookup
    退避不得把它擋掉。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.client = _client(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_refetch_happens_immediately_after_invalidate(self):
        calls = []

        def fake_collection(path, **kw):
            calls.append(path)
            return 200, [], None

        self.client._get_collection = fake_collection
        self.client._resolve_actor_filter("Env=NoSuch")
        self.assertEqual(len(calls), 4)
        self.client.invalidate_labels()
        self.client._resolve_actor_filter("Env=NoSuch")
        self.assertEqual(len(calls), 8, "invalidate 後仍被退避擋住，未重新抓取")
