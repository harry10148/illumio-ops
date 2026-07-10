import time
from unittest.mock import MagicMock

from cachetools import TTLCache

from src.gui import filter_object_cache
from src.gui.filter_object_cache import search_cached_objects, invalidate_object_cache


def _api():
    api = MagicMock()
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
    filter_object_cache._cache = TTLCache(maxsize=8, ttl=0.05)
    try:
        api_ok = _api()
        r1 = search_cached_objects(api_ok, "server", ["label"], 10)
        names1 = [i["name"] for i in r1["label"]["items"]]
        assert "Net=Server-172.16.15" in names1

        time.sleep(0.06)  # let TTL expire

        api_fail = MagicMock()
        api_fail.get_all_labels.return_value = []
        r2 = search_cached_objects(api_fail, "server", ["label"], 10)
        names2 = [i["name"] for i in r2["label"]["items"]]
        assert "Net=Server-172.16.15" in names2, "expected stale-serving of last-known-good data"

        invalidate_object_cache()
        r3 = search_cached_objects(api_fail, "server", ["label"], 10)
        assert r3["label"]["items"] == []
    finally:
        filter_object_cache._cache = orig_cache


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
