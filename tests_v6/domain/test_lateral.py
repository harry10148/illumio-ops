"""The shared lateral-movement context: management ports, critical assets and admin groups (spec §6.5.1)."""
from illumio_ops.domain.filter import PortProto
from illumio_ops.domain.lateral import (
    effective_admin_ports,
    selector_matches,
    stale_selectors,
)

BUILTIN = ((445, "SMB"), (22, "SSH"))
PCE = ((3389, 6, "RDP"), (3389, 17, "RDP"))


def _entries(ps):
    return {(e.port, e.proto, e.source) for e in ps.entries}


def test_effective_ports_union_and_removal():
    ps = effective_admin_ports(BUILTIN, PCE, extra=((8080, 6),), removed=((22, None),), include_pce=True)
    assert _entries(ps) == {(445, None, "builtin"), (3389, 6, "pce"), (3389, 17, "pce"), (8080, 6, "added")}
    assert next(e for e in ps.entries if e.port == 445).name == "SMB"
    assert next(e for e in ps.entries if e.port == 8080).name is None


def test_pce_admin_services_toggle():
    ps = effective_admin_ports(BUILTIN, PCE, extra=(), removed=(), include_pce=False)
    assert {e.source for e in ps.entries} == {"builtin"}


def test_any_protocol_entry_matches_both():
    ps = effective_admin_ports(BUILTIN, PCE, extra=(), removed=(), include_pce=True)
    assert ps.matches(445, 6) and ps.matches(445, 17)
    assert ps.matches(3389, 6) and not ps.matches(8080, 6) and not ps.matches(None, 6)
    only_tcp = effective_admin_ports((), ((3389, 6, "RDP"),), extra=(), removed=(), include_pce=True)
    assert only_tcp.matches(3389, 6) and not only_tcp.matches(3389, 17)
    assert set(ps.port_filters()) >= {PortProto(port=445), PortProto(port=3389, proto=6)}


def test_removed_without_proto_removes_all_protocols():
    all_gone = effective_admin_ports(BUILTIN, PCE, extra=(), removed=((3389, None),), include_pce=True)
    assert not any(e.port == 3389 for e in all_gone.entries)
    udp_gone = effective_admin_ports(BUILTIN, PCE, extra=(), removed=((3389, 17),), include_pce=True)
    assert {(e.port, e.proto) for e in udp_gone.entries if e.port == 3389} == {(3389, 6)}


def test_selector_union_semantics():
    labels = {"app": "Finance", "env": "Prod"}
    assert selector_matches(labels, [("app", "Finance"), ("role", "DB")])
    assert not selector_matches(labels, [("role", "DB")])
    assert not selector_matches(labels, [])


def test_stale_selector_detected():
    assert stale_selectors([("app", "Finance"), ("app", "Gone")], {("app", "Finance")}) == [("app", "Gone")]


def test_builtin_covers_remote_control_without_the_pce():
    """VNC and TeamViewer are in the PCE's admin category; the built-in list carries them too, so a PCE that does
    not report ransomware-protection services still counts them (P4: cover as much as the vendor list)."""
    from illumio_ops.domain.values import LATERAL_PORTS_DEFAULT
    s = effective_admin_ports(LATERAL_PORTS_DEFAULT, (), extra=(), removed=(), include_pce=False)
    assert s.matches(5900, 6) and s.matches(5938, 6)
