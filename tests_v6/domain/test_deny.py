"""Deny rule proposals (spec §6.5.1 防堵, read-only): which observed connections and graph edges they cut."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.deny import (
    DenyProposal,
    apply_deny,
    cut_to_proposal,
    edge_matches,
    proposal_filter,
)
from illumio_ops.domain.exposure import Cut, EdgeIn
from illumio_ops.domain.filter import EndpointFilter, LabelCond, PortProto
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.values import EdgeState, PolicyDecision

END = datetime(2026, 10, 25, 12, tzinfo=UTC)


def host(key, labels=None, managed=True):
    return HostInfo(key=key, href=None if key.startswith("ip:") else key, hostname=key, managed=managed,
                    labels=labels or {}, enforcement_mode=None, visibility_level=None, os_id=None, ven_href=None,
                    critical=False, admin_group=False)


DEV_TO_FIN_RDP = DenyProposal(src=EndpointFilter(labels=(LabelCond(key="env", values=("Dev",)),)),
                              dst=EndpointFilter(hrefs=("/w/fin",)), ports=(PortProto(port=3389, proto=6),))


def test_proposal_filter_excludes_already_blocked():
    spec = proposal_filter(DEV_TO_FIN_RDP, start=END - timedelta(days=30), end=END)
    assert set(spec.decisions) == {PolicyDecision.ALLOWED, PolicyDecision.POTENTIALLY_BLOCKED, PolicyDecision.UNKNOWN}
    assert spec.dst.hrefs == ("/w/fin",) and spec.ports == (PortProto(port=3389, proto=6),)
    anything = proposal_filter(DenyProposal(src=EndpointFilter(), dst=EndpointFilter()), start=spec.start, end=END)
    assert anything.src is None and anything.dst is None and anything.ports == ()


def test_edge_matches_by_labels_href_ip_and_ports():
    dev, fin = host("/w/dev", {"env": "Dev"}), host("/w/fin")
    assert edge_matches(DEV_TO_FIN_RDP, dev, fin, src_ip="", dst_ip="", port=3389, proto=6)
    assert not edge_matches(DEV_TO_FIN_RDP, dev, fin, src_ip="", dst_ip="", port=22, proto=6)
    assert not edge_matches(DEV_TO_FIN_RDP, host("/w/prod", {"env": "Prod"}), fin, src_ip="", dst_ip="", port=3389,
                            proto=6)
    by_ip = DenyProposal(src=EndpointFilter(ips=("10.0.0.0/8",)), dst=EndpointFilter())
    assert edge_matches(by_ip, host("ip:10.1.1.1", managed=False), fin, src_ip="10.1.1.1", dst_ip="", port=1, proto=6)


def test_apply_deny_drops_matching_edges():
    hosts = {"/w/dev": host("/w/dev", {"env": "Dev"}), "/w/fin": host("/w/fin"), "/w/x": host("/w/x")}
    edges = [EdgeIn("/w/dev", "/w/fin", 3389, 6, EdgeState.ALLOWED), EdgeIn("/w/dev", "/w/fin", 22, 6, EdgeState.ALLOWED),
             EdgeIn("/w/x", "/w/fin", 3389, 6, EdgeState.ALLOWED)]
    kept = apply_deny(edges, DEV_TO_FIN_RDP, hosts.__getitem__)
    assert [(k.src, k.port) for k in kept] == [("/w/dev", 22), ("/w/x", 3389)]


def test_cut_converts_to_proposal():
    hosts = {"/w/bak": host("/w/bak"), "/w/fin": host("/w/fin")}
    edge = cut_to_proposal(Cut(kind="edge", src="/w/bak", dst="/w/fin", ports=[(3389, 6)], before=9, after=2), hosts)
    assert edge.src.hrefs == ("/w/bak",) and edge.dst.hrefs == ("/w/fin",)
    assert edge.ports == (PortProto(port=3389, proto=6),)
    unmanaged = cut_to_proposal(Cut(kind="edge", src="ip:10.9.9.9", dst="/w/fin", ports=[(22, 6)], before=3, after=1),
                                hosts)
    assert unmanaged.src.ips == ("10.9.9.9",)
    node = cut_to_proposal(Cut(kind="node", src="/w/bak", dst=None, ports=[], before=9, after=2), hosts)
    assert node.src.is_empty() and node.dst.hrefs == ("/w/bak",) and node.ports == ()
