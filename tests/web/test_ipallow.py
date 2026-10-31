import ipaddress

import pytest

from illumio_ops.web.ipallow import (
    InvalidIpEntries,
    is_allowed,
    normalize_ip_token,
    validate_allowed_ips,
)


def test_ipv4_mapped_ipv6_is_normalised():
    assert normalize_ip_token("::ffff:192.168.1.1") == ipaddress.ip_address("192.168.1.1")
    assert normalize_ip_token("::ffff:10.0.0.0/104") == ipaddress.ip_network("10.0.0.0/8")


@pytest.mark.parametrize(("allowed", "remote", "ok"), [
    ([], "10.9.9.9", True),
    (["127.0.0.1", "192.168.1.0/24"], "192.168.1.50", True),
    (["127.0.0.1", "192.168.1.0/24"], "10.0.0.1", False),
    (["127.0.0.1"], "::ffff:127.0.0.1", True),
    (["192.168.1.99"], "::ffff:192.168.1.99", True),
    (["::1"], "127.0.0.1", True),  # loopback is loopback
    (["127.0.0.1"], "not-an-ip", False),
    (["garbage", "10.0.0.0/8"], "10.1.2.3", True),  # a bad stored entry never blocks the good ones
])
def test_is_allowed(allowed, remote, ok):
    assert is_allowed(allowed, remote) is ok


def test_validate_allowed_ips_normalises_and_skips_blank():
    assert validate_allowed_ips(["::ffff:192.168.1.1", "127.0.0.1/32", "::1", " "]) == [
        "192.168.1.1", "127.0.0.1/32", "::1"]


def test_validate_allowed_ips_reports_invalid_entries():
    with pytest.raises(InvalidIpEntries) as e:
        validate_allowed_ips(["10.0.0.1", "localhost", "300.1.1.1"])
    assert e.value.invalid == ["localhost", "300.1.1.1"]
