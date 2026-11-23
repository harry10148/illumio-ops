from illumio_ops.domain.protocols import PROTOCOLS
from illumio_ops.services.reports.common import port_text, ports_text


def test_port_text_names_known_protocols_and_preserves_unknown_numbers():
    assert port_text(443, 6) == "443/TCP"
    assert port_text(53, 17) == "53/UDP"
    assert port_text(1400, 6, 1500) == "1400-1500/TCP"
    assert port_text(123, 58) == "123/ICMPv6"
    assert port_text(47, 47) == "47/GRE"
    assert port_text(50, 50) == "50/ESP"
    assert port_text(12, 132) == "12/132"
    assert PROTOCOLS == {6: "TCP", 17: "UDP", 1: "ICMP", 58: "ICMPv6", 47: "GRE", 50: "ESP"}


def test_port_text_handles_protocol_only_and_any_protocol():
    assert port_text(None, 1) == "ICMP"
    assert port_text(-1, 58) == "ICMPv6"
    assert port_text(443, None) == "443"
    assert port_text(443, -1) == "443"
    assert port_text(1400, None, 1500) == "1400-1500"


def test_ports_text_uses_the_same_display_rules_for_tuples_and_mappings():
    assert ports_text([(443, 6), {"port": 53, "proto": 17}, {"port": 443, "proto": None}]) == \
        "443/TCP, 53/UDP, 443"


def test_a_service_with_no_port_and_any_protocol_reads_as_all():
    from illumio_ops.domain.protocols import service_label
    assert service_label(None, -1) == "*" and service_label(None, None) == "*"
