"""exclude_src_ips accepts CIDR networks as well as exact IPs (task 11 / #6).

The mixed semantics are pinned: a string containing "/" is a network parsed
with strict=False, anything else is an exact address. Exact entries stay in the
O(1) set so existing configs behave byte-identically; only networks are scanned.
"""
import pytest
from src.pce_cache.traffic_filter import TrafficFilter
from src.config_models import TrafficFilterSettings


@pytest.mark.parametrize("entry, ip, excluded", [
    ("10.0.0.5",        "10.0.0.5",      True),   # 精確 v4，行為不得改變
    ("10.0.0.5",        "10.0.0.6",      False),
    ("10.0.0.0/24",     "10.0.0.99",     True),   # v4 CIDR
    ("10.0.0.0/24",     "10.0.1.1",      False),
    ("10.0.0.7/24",     "10.0.0.1",      True),   # 非網路位址 → strict=False
    ("2001:db8::/32",   "2001:db8::1",   True),   # v6 CIDR
    ("2001:db8::/32",   "2001:dba::1",   False),
    ("10.0.0.0/24",     "2001:db8::1",   False),  # 跨版本不匹配且不拋例外
    ("2001:db8::/32",   "10.0.0.1",      False),
])
def test_exclude_matches_exact_and_cidr(entry, ip, excluded):
    f = TrafficFilter(exclude_src_ips=[entry])
    assert f.passes({"src_ip": ip, "port": 1, "protocol": "TCP", "action": "allowed"}) is not excluded


def test_empty_src_ip_does_not_raise():
    f = TrafficFilter(exclude_src_ips=["10.0.0.0/24"])
    assert f.passes({"src_ip": "", "port": 1, "protocol": "TCP", "action": "allowed"}) is True


@pytest.mark.parametrize("good", ["10.0.0.1", "10.0.0.0/24", "2001:db8::1", "2001:db8::/32"])
def test_settings_accepts_ip_and_cidr(good):
    assert TrafficFilterSettings(exclude_src_ips=[good]).exclude_src_ips == [good]


@pytest.mark.parametrize("bad", ["not-an-ip", "10.0.0", "10.0.0.0/33", "::::", "10.0.0.0/", "/24"])
def test_settings_rejects_malformed(bad):
    with pytest.raises(ValueError):
        TrafficFilterSettings(exclude_src_ips=[bad])


def test_networks_are_parsed_once_not_per_flow():
    """passes() 每筆 flow 都會被呼叫；解析必須在 __init__ 完成。"""
    import inspect
    src = inspect.getsource(TrafficFilter.passes)
    for forbidden in ("ip_network", "ip_address"):
        assert forbidden not in src, f"passes() 不得在每筆 flow 解析字串（發現 {forbidden}）"
