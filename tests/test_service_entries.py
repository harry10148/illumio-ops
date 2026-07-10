"""service_ports_cache 完整條目擴充 + resolve_service_entries 行為契約。"""
from unittest.mock import MagicMock

from src.api.labels import LabelResolver


def _resolver_with_cache(cache):
    client = MagicMock()
    client.service_ports_cache = cache
    return LabelResolver(client)


def test_resolve_service_entries_hit():
    r = _resolver_with_cache({"/orgs/1/sec_policy/draft/services/9": [{"port": 80, "proto": 6}]})
    assert r.resolve_service_entries("/orgs/1/sec_policy/draft/services/9") == [{"port": 80, "proto": 6}]


def test_resolve_service_entries_miss_returns_none():
    r = _resolver_with_cache({})
    assert r.resolve_service_entries("/orgs/1/sec_policy/active/services/404") is None


def test_cache_build_includes_windows_and_protocol_only_entries():
    """update_label_cache 的 services 段落改用 _service_entry_defs 建條目：
    windows_services 與純 proto 條目都要進 service_ports_cache。"""
    svc = {
        "name": "Mixed",
        "href": "/orgs/1/sec_policy/draft/services/7",
        "service_ports": [
            {"port": 443, "proto": 6},
            {"proto": 1},  # ICMP：無 port
        ],
        "windows_services": [
            {"service_name": "wuauserv"},
            {"process_name": "svchost.exe"},
            {"port": 3389, "proto": 6, "service_name": "TermService"},
        ],
    }
    defs = LabelResolver._service_entry_defs(svc)
    assert {"port": 443, "proto": 6} in defs
    assert {"proto": 1} in defs
    assert {"windows_service_name": "wuauserv"} in defs
    assert {"process_name": "svchost.exe"} in defs
    # 名稱優先於 port（同一 windows 條目不重複展開）
    assert {"windows_service_name": "TermService"} in defs
    assert len(defs) == 5


def test_service_entry_defs_empty_service():
    assert LabelResolver._service_entry_defs({"name": "Empty", "href": "/x", "service_ports": []}) == []


def test_service_entry_defs_wildcard_for_negative_proto():
    """PCE 特殊物件「All Services」的 service_ports 條目是 {"proto": -1}
    （語意=所有協定、無服務限制），須正規化為 wildcard 標記條目，而非
    把 -1 當成一個真實 proto 值送進 query。"""
    svc = {
        "name": "All Services",
        "href": "/orgs/1/sec_policy/active/services/1",
        "service_ports": [{"proto": -1}],
    }
    defs = LabelResolver._service_entry_defs(svc)
    assert defs == [{"wildcard": True}]


def test_service_entry_defs_wildcard_for_negative_port():
    svc = {
        "name": "Weird",
        "href": "/orgs/1/sec_policy/active/services/2",
        "service_ports": [{"port": -1, "proto": 6}],
    }
    defs = LabelResolver._service_entry_defs(svc)
    assert defs == [{"wildcard": True}]
