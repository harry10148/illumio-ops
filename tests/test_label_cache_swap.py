"""Task 7: label cache build-then-swap——消除 clear-before-fetch 空窗與
rollback lost-update 競態。update_label_cache 應先在區域 dict 組好全部資料，
四個集合全部成功後才在 _cache_lock 內一次 swap 進共享快取。"""
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


def _fake_collections(fail_suffix=None, fail_status=503):
    """產生 _get_collection 的 side_effect：四集合各一筆正常資料，
    fail_suffix 指定的集合回傳 fail_status。"""

    def fake(path, *, timeout=15):
        if fail_suffix and path.endswith(fail_suffix):
            return fail_status, None, None
        if path.endswith("/labels"):
            return 200, [{"href": "/orgs/1/labels/1", "key": "role", "value": "web"}], None
        if path.endswith("/label_groups"):
            return 200, [{"href": "/orgs/1/sec_policy/draft/label_groups/1", "name": "G1"}], None
        if path.endswith("/ip_lists"):
            return 200, [{"href": "/orgs/1/sec_policy/draft/ip_lists/1", "name": "IPL1"}], None
        if path.endswith("/services"):
            return 200, [{
                "href": "/orgs/1/sec_policy/draft/services/1",
                "name": "S1",
                "service_ports": [{"port": 443, "proto": 6}],
            }], None
        return 200, [], None

    return fake


class TestSwapOnlyAfterAllFetchesSucceed(unittest.TestCase):
    def test_swap_only_after_all_fetches_succeed(self):
        """第三個集合（ip_lists）回 503 → 共享快取內容原封不動、
        refreshed_at 不變、回傳 False（現況：其餘集合照寫且 refreshed_at 更新）。"""
        client = _make_client()
        client.label_cache["/orgs/1/labels/old"] = "role:old"
        client._label_href_cache["role:old"] = "/orgs/1/labels/old"
        old_ts = 12345.0
        client._query_lookup_cache_refreshed_at = old_ts

        client._get_collection = MagicMock(side_effect=_fake_collections(fail_suffix="/ip_lists"))
        result = client.update_label_cache(silent=True)

        self.assertFalse(result)
        self.assertEqual(dict(client.label_cache), {"/orgs/1/labels/old": "role:old"})
        self.assertEqual(dict(client._label_href_cache), {"role:old": "/orgs/1/labels/old"})
        self.assertEqual(client._query_lookup_cache_refreshed_at, old_ts)

    def test_successful_update_replaces_stale_entries(self):
        """全部成功時 swap 為全新內容：PCE 端已刪除的舊條目不得殘留。"""
        client = _make_client()
        client.label_cache["/orgs/1/labels/deleted"] = "role:deleted"

        client._get_collection = MagicMock(side_effect=_fake_collections())
        result = client.update_label_cache(silent=True)

        self.assertTrue(result)
        self.assertNotIn("/orgs/1/labels/deleted", client.label_cache)
        self.assertEqual(client.label_cache.get("/orgs/1/labels/1"), "role:web")
        self.assertEqual(client.label_cache.get("/orgs/1/sec_policy/draft/ip_lists/1"), "[IPList] IPL1")


class TestNoInvalidateBeforeFetch(unittest.TestCase):
    def test_no_invalidate_before_fetch(self):
        """swap 模式天然不需要 clear-before-fetch：update_label_cache 全程
        不得呼叫 invalidate_query_lookup_cache（現況 force_refresh=True 會先清空，
        期間讀者看到空快取）。"""
        client = _make_client()
        client._labels.invalidate_query_lookup_cache = MagicMock()
        client._get_collection = MagicMock(side_effect=_fake_collections())

        client.update_label_cache(silent=True, force_refresh=True)

        client._labels.invalidate_query_lookup_cache.assert_not_called()


class TestSwapPreservesDictIdentity(unittest.TestCase):
    def test_swap_preserves_dict_identity(self):
        """swap 採 clear+update 而非替換引用：既有別名引用不得失效。"""
        client = _make_client()
        cache_ids = {
            "label_cache": id(client.label_cache),
            "service_ports_cache": id(client.service_ports_cache),
            "_label_href_cache": id(client._label_href_cache),
            "_label_group_href_cache": id(client._label_group_href_cache),
            "_iplist_href_cache": id(client._iplist_href_cache),
        }
        client._get_collection = MagicMock(side_effect=_fake_collections())

        client.update_label_cache(silent=True)

        self.assertEqual(id(client.label_cache), cache_ids["label_cache"])
        self.assertEqual(id(client.service_ports_cache), cache_ids["service_ports_cache"])
        self.assertEqual(id(client._label_href_cache), cache_ids["_label_href_cache"])
        self.assertEqual(id(client._label_group_href_cache), cache_ids["_label_group_href_cache"])
        self.assertEqual(id(client._iplist_href_cache), cache_ids["_iplist_href_cache"])
        self.assertEqual(client.label_cache.get("/orgs/1/labels/1"), "role:web")


if __name__ == "__main__":
    unittest.main()
