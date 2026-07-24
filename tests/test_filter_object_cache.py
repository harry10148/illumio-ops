import time
from unittest.mock import MagicMock

import pytest
from cachetools import TTLCache

from src.gui import filter_object_cache
from src.gui.filter_object_cache import search_cached_objects, invalidate_object_cache

# 快取 key 帶 PCE 身分（api.base_url）；同一測試裡的替身須固定同值，
# 否則每個 MagicMock 的自動屬性都是獨一 repr、彼此不共享快取。
_BASE_URL = "https://pce:8443/api/v2/orgs/1"


def _api():
    api = MagicMock()
    api.base_url = _BASE_URL
    api.get_all_labels.return_value = [
        {"key": "Net", "value": "Server-172.16.15", "href": "/orgs/1/labels/1"},
        {"key": "Net", "value": "MGMT-192.168.10", "href": "/orgs/1/labels/2"},
        {"key": "env", "value": "Production", "href": "/orgs/1/labels/3"},
    ]
    api.get_ip_lists.return_value = [
        {"name": "Prod-Subnets", "href": "/orgs/1/sec_policy/active/ip_lists/7",
         "ip_ranges": [{"from_ip": "10.10.0.0/16"}, {"from_ip": "10.11.0.0/16"}]},
        {"name": "Corp-VPN", "href": "/orgs/1/sec_policy/active/ip_lists/8",
         "ip_ranges": [{"from_ip": "172.16.8.0/22"}]},
    ]
    api.get_label_groups.return_value = [
        {"name": "PG-Prod-Apps", "href": "/orgs/1/sec_policy/active/label_groups/5"},
    ]
    api.get_services.return_value = [
        {"name": "Web-Ports", "href": "/s/1",
         "service_ports": [{"port": 80, "proto": 6}, {"port": 443, "proto": 6}]},
        {"name": "RDP", "href": "/s/2",
         "service_ports": [{"port": 3389, "proto": 6}],
         "windows_services": [{"service_name": "TermService"}]},
    ]
    return api


def setup_function():
    invalidate_object_cache()


def test_label_substring_across_dimensions():
    r = search_cached_objects(_api(), "server", ["label"], 10)
    names = [i["name"] for i in r["label"]["items"]]
    assert "Net=Server-172.16.15" in names
    assert r["label"]["items"][0]["key"] == "Net"


def test_label_case_insensitive():
    r = search_cached_objects(_api(), "PROD", ["label"], 10)
    assert any(i["value"] == "Production" for i in r["label"]["items"])


def test_iplist_has_summary():
    r = search_cached_objects(_api(), "prod", ["iplist"], 10)
    item = r["iplist"]["items"][0]
    assert item["name"] == "Prod-Subnets"
    assert item["href"].endswith("/ip_lists/7")
    assert "10.10.0.0/16" in item["summary"]


def test_label_group_name_match():
    r = search_cached_objects(_api(), "prod-apps", ["label_group"], 10)
    assert r["label_group"]["items"][0]["name"] == "PG-Prod-Apps"


def test_truncated_flag():
    r = search_cached_objects(_api(), "net", ["label"], 1)
    # "net" 比對到兩個 Net= label，limit=1 → truncated
    assert len(r["label"]["items"]) == 1
    assert r["label"]["truncated"] is True


def test_cache_reused_no_second_fetch():
    api = _api()
    search_cached_objects(api, "a", ["label"], 10)
    search_cached_objects(api, "b", ["label"], 10)
    assert api.get_all_labels.call_count == 1  # TTL 內只抓一次


def test_types_filter_only_requested():
    r = search_cached_objects(_api(), "prod", ["iplist"], 10)
    assert "iplist" in r and "label" not in r


def test_stale_served_on_refetch_failure_after_expiry():
    orig_cache = filter_object_cache._cache
    filter_object_cache._cache = TTLCache(maxsize=32, ttl=0.05)
    try:
        api_ok = _api()
        r1 = search_cached_objects(api_ok, "server", ["label"], 10)
        names1 = [i["name"] for i in r1["label"]["items"]]
        assert "Net=Server-172.16.15" in names1

        time.sleep(0.06)  # let TTL expire

        # 失敗＝fetcher raise（raise_on_error=True 的 APIError 路徑），
        # 不再是回空集合——空集合是合法真值，見下一個測試。
        api_fail = MagicMock()
        api_fail.base_url = _BASE_URL
        api_fail.get_all_labels.side_effect = RuntimeError("pce down")
        r2 = search_cached_objects(api_fail, "server", ["label"], 10)
        names2 = [i["name"] for i in r2["label"]["items"]]
        assert "Net=Server-172.16.15" in names2, "expected stale-serving of last-known-good data"

        # 無舊值時失敗必須 re-raise（端點據此回 pce_unreachable），
        # 不得無聲回空集合。
        invalidate_object_cache()
        with pytest.raises(RuntimeError):
            search_cached_objects(api_fail, "server", ["label"], 10)
    finally:
        filter_object_cache._cache = orig_cache


def test_empty_refetch_supersedes_last_good_and_is_cached():
    """合法空集合是真值：全刪後不得再供舊物件（_last_good 被空集合取代），
    且空集合要進 TTL 快取——空 org 不必每個 keystroke 都打 PCE。"""
    orig_cache = filter_object_cache._cache
    filter_object_cache._cache = TTLCache(maxsize=32, ttl=0.05)
    try:
        api_ok = _api()
        search_cached_objects(api_ok, "server", ["label"], 10)

        time.sleep(0.06)  # let TTL expire

        api_empty = MagicMock()
        api_empty.base_url = _BASE_URL
        api_empty.get_all_labels.return_value = []
        r = search_cached_objects(api_empty, "server", ["label"], 10)
        assert r["label"]["items"] == [], "deleted objects must not be stale-served"

        search_cached_objects(api_empty, "anything", ["label"], 10)
        assert api_empty.get_all_labels.call_count == 1, "empty result must be TTL-cached"
    finally:
        filter_object_cache._cache = orig_cache


def test_cache_scoped_by_pce_identity():
    """切換 active PCE profile 後不得吃到前一個 PCE 的物件/href。"""
    api_a = _api()
    search_cached_objects(api_a, "server", ["label"], 10)

    api_b = MagicMock()
    api_b.base_url = "https://pce-b:8443/api/v2/orgs/7"
    api_b.get_all_labels.return_value = [
        {"key": "env", "value": "B-only", "href": "/orgs/7/labels/9"}]
    r = search_cached_objects(api_b, "b-only", ["label"], 10)
    assert [i["value"] for i in r["label"]["items"]] == ["B-only"]
    assert api_b.get_all_labels.call_count == 1, "PCE B must not reuse PCE A's cache"

    # PCE A 的快取仍在，且不含 B 的物件
    r_a = search_cached_objects(api_a, "b-only", ["label"], 10)
    assert r_a["label"]["items"] == []
    assert api_a.get_all_labels.call_count == 1


def test_search_service_with_summary():
    api = MagicMock()
    api.get_services.return_value = [
        {"name": "Web-Ports", "href": "/s/1",
         "service_ports": [{"port": 80, "proto": 6}, {"port": 443, "proto": 6}]},
        {"name": "RDP", "href": "/s/2",
         "service_ports": [{"port": 3389, "proto": 6}],
         "windows_services": [{"service_name": "TermService"}]},
    ]
    invalidate_object_cache()
    out = search_cached_objects(api, "web", ["service"], 10)
    assert out["service"]["items"] == [
        {"name": "Web-Ports", "href": "/s/1", "summary": "tcp/80, tcp/443"}]


def test_service_summary_truncates_with_ellipsis():
    from src.gui.filter_object_cache import _service_summary
    svc = {"service_ports": [{"port": p, "proto": 6} for p in (1, 2, 3, 4, 5)]}
    s = _service_summary(svc)
    assert s.endswith(", …") and s.count(",") == 3  # 3 segments + ellipsis


def test_service_summary_all_services_wildcard():
    """PCE 特殊物件「All Services」的 service_ports 是 {"proto": -1}
    （語意=所有協定、無服務限制），摘要須顯示 "all"，不可印出 "-1"。"""
    from src.gui.filter_object_cache import _service_summary
    svc = {"service_ports": [{"proto": -1}]}
    assert _service_summary(svc) == "all"
