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


def test_networks_are_parsed_once_not_per_flow(monkeypatch):
    """設定的網段只在 __init__ 解析一次，passes() 不論被呼叫幾次都不再解析。

    這裡數的是 ip_network（解析「設定字串」的那一個），不是 ip_address：
    passes() 本來就必須解析**每筆 flow 自己的** src_ip（經 _parse_addr →
    ip_address），那是無法預先做的工作，不是本測試要禁止的事。

    早先的版本改用 inspect.getsource(passes) 斷言字面 token "ip_network" /
    "ip_address" 不出現——但 passes() 呼叫的 _parse_addr() 內部就有
    ip_address()，該不變量其實已經是假的；而且任何未來的 helper 只要多包一層
    就能同樣繞過。改成實際計數：不變量與「解析只做一次」逐字對應，且不因
    程式碼被搬進 helper 而失效。
    """
    import ipaddress as _ipaddress
    real = _ipaddress.ip_network
    calls = []

    def counting(*a, **kw):
        calls.append(a[0] if a else None)
        return real(*a, **kw)

    monkeypatch.setattr(_ipaddress, "ip_network", counting)

    f = TrafficFilter(exclude_src_ips=["10.0.0.0/24", "2001:db8::/32", "192.168.1.7"])
    assert len(calls) == 2, f"__init__ 應只解析兩個網段，實際 {calls}"

    flows = [
        {"src_ip": "10.0.0.99", "port": 1, "protocol": "TCP", "action": "allowed"},   # 命中網段
        {"src_ip": "192.168.1.7", "port": 1, "protocol": "TCP", "action": "allowed"},  # 命中精確 IP
        {"src_ip": "8.8.8.8", "port": 1, "protocol": "TCP", "action": "allowed"},      # 未命中
        {"src_ip": "2001:db8::1", "port": 1, "protocol": "TCP", "action": "allowed"},  # v6 命中
        {"src_ip": "", "port": 1, "protocol": "TCP", "action": "allowed"},             # 無法解析
    ]
    nets_before = f._excl_nets
    for _ in range(100):
        for flow in flows:
            f.passes(flow)

    assert len(calls) == 2, (
        f"passes() 不得再解析設定字串：多了 {len(calls) - 2} 次，前幾筆 {calls[2:5]}"
    )
    assert f._excl_nets is nets_before
