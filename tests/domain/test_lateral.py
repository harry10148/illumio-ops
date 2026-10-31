"""The shared lateral-movement context: management ports, critical assets and admin groups (spec §6.5.1)."""
from illumio_ops.domain.filter import PortProto
from illumio_ops.domain.lateral import (
    effective_admin_ports,
    selector_matches,
    stale_selectors,
)
from illumio_ops.domain.values import PortClass

BUILTIN = ((445, "SMB", PortClass.REMOTE), (22, "SSH", PortClass.REMOTE))
PCE = ((3389, 6, "RDP"), (3389, 17, "RDP"))


def _entries(ps):
    return {(e.port, e.proto, e.source) for e in ps.entries}


def test_effective_ports_union_and_removal():
    ps = effective_admin_ports(BUILTIN, PCE, extra=((8080, 6, PortClass.REMOTE),), removed=((22, None),), include_pce=True)
    assert _entries(ps) == {(445, 6, "builtin"), (3389, 6, "pce"), (3389, 17, "pce"), (8080, 6, "added")}
    assert next(e for e in ps.entries if e.port == 445).name == "SMB"
    assert next(e for e in ps.entries if e.port == 8080).name is None


def test_pce_admin_services_toggle():
    ps = effective_admin_ports(BUILTIN, PCE, extra=(), removed=(), include_pce=False)
    assert {e.source for e in ps.entries} == {"builtin"}


def test_any_protocol_entry_matches_both():
    # A port added without a protocol matches both (built-ins carry their own protocols since 2026-10-27).
    ps = effective_admin_ports(BUILTIN, PCE, extra=((4444, None, PortClass.REMOTE),), removed=(), include_pce=True)
    assert ps.matches(4444, 6) and ps.matches(4444, 17)
    assert ps.matches(445, 6) and not ps.matches(445, 17)
    assert ps.matches(3389, 6) and not ps.matches(8080, 6) and not ps.matches(None, 6)
    only_tcp = effective_admin_ports((), ((3389, 6, "RDP"),), extra=(), removed=(), include_pce=True)
    assert only_tcp.matches(3389, 6) and not only_tcp.matches(3389, 17)
    assert set(ps.port_filters()) >= {PortProto(port=4444), PortProto(port=445, proto=6), PortProto(port=3389, proto=6)}


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


def test_admin_port_set_class_of():
    from illumio_ops.domain.values import LATERAL_PORTS_DEFAULT
    s = effective_admin_ports(LATERAL_PORTS_DEFAULT, PCE, extra=(), removed=(), include_pce=True)
    assert s.class_of(389, 6) is PortClass.DIRECTORY and s.class_of(88, 17) is PortClass.DIRECTORY
    assert s.class_of(1433, 6) is PortClass.DATABASE and s.class_of(445, 6) is PortClass.REMOTE
    assert s.class_of(3389, 17) is PortClass.REMOTE and s.class_of(8080, 6) is None and s.class_of(None, 6) is None
    assert s.matches(389, 6) and not s.matches(389, 6, {PortClass.REMOTE, PortClass.DATABASE})
    ldap = {PortProto(port=389, proto=6), PortProto(port=389, proto=17)}
    assert not ldap & set(s.port_filters({PortClass.REMOTE}))
    assert ldap <= set(s.port_filters()) and ldap <= set(s.port_filters({PortClass.DIRECTORY}))
    assert {e.port for e in s.entries if e.category is PortClass.DIRECTORY} == {88, 389, 636, 464, 3268, 3269, 9389}


def test_added_port_keeps_its_category():
    s = effective_admin_ports(BUILTIN, (), extra=((1521, 6, PortClass.DATABASE),), removed=(), include_pce=False)
    assert s.class_of(1521, 6) is PortClass.DATABASE


def test_builtin_ports_carry_their_protocols():
    """A UDP reply landing on an ephemeral port numbered 1433 or 5985 is not a management connection (lab: 8.8.8.8
    "1433/UDP into 8 hosts"; dc → MacBook "UDP 5985"); UDP counts only where the service itself uses UDP."""
    from illumio_ops.domain.values import LATERAL_PORTS_DEFAULT
    s = effective_admin_ports(LATERAL_PORTS_DEFAULT, (), extra=(), removed=(), include_pce=False)
    assert s.matches(1433, 6) and not s.matches(1433, 17)
    assert s.matches(5985, 6) and not s.matches(5985, 17)
    assert s.matches(3269, 6) and not s.matches(3269, 17)
    for port in (88, 464, 389, 3389, 2049, 111, 5938):
        assert s.matches(port, 17), port
    assert all(e.proto in (6, 17) for e in s.entries if e.source == "builtin")


def test_removing_a_builtin_without_protocol_removes_both():
    from illumio_ops.domain.values import LATERAL_PORTS_DEFAULT
    s = effective_admin_ports(LATERAL_PORTS_DEFAULT, (), extra=(), removed=((389, None),), include_pce=False)
    assert not s.matches(389, 6) and not s.matches(389, 17)
