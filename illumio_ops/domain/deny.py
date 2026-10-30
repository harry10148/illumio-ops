"""Deny rule proposals, tried against collected traffic only (spec §6.5.1 防堵: suggestions and lists, never a
write to the PCE). A proposal names sources, destinations and services the way a deny rule does; what it
would block is every observed connection it matches that was not blocked already."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from illumio_ops.domain.exposure import Cut, EdgeIn
from illumio_ops.domain.filter import (
    EndpointFilter,
    FilterSpec,
    PortProto,
    endpoint_matches,
    port_matches,
)
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.values import PolicyDecision

# A connection already blocked is not one a new deny rule would block.
_WOULD_BLOCK = (PolicyDecision.ALLOWED, PolicyDecision.POTENTIALLY_BLOCKED, PolicyDecision.UNKNOWN)


class DenyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    src: EndpointFilter
    dst: EndpointFilter
    ports: tuple[PortProto, ...] = ()  # empty = all services

    @model_validator(mode="after")
    def _names_something(self) -> DenyProposal:
        if self.src.is_empty() and self.dst.is_empty() and not self.ports:
            raise ValueError("a deny rule names a source, a destination or a service")  # not "block everything"
        return self


def proposal_filter(p: DenyProposal, *, start: datetime, end: datetime) -> FilterSpec:
    return FilterSpec(start=start, end=end, src=None if p.src.is_empty() else p.src,
                      dst=None if p.dst.is_empty() else p.dst, ports=p.ports, decisions=_WOULD_BLOCK)


def edge_matches(p: DenyProposal, src: HostInfo, dst: HostInfo, *, src_ip: str, dst_ip: str, port: int,
                 proto: int) -> bool:
    return ((p.src.is_empty() or endpoint_matches(p.src, href=src.href, ip=src_ip, labels=src.labels))
            and (p.dst.is_empty() or endpoint_matches(p.dst, href=dst.href, ip=dst_ip, labels=dst.labels))
            and (not p.ports or any(port_matches(pp, port, proto) for pp in p.ports)))


def _ip_of(key: str) -> str:
    # A graph node is a workload href or ip:<address>; a workload's addresses are not on the graph, so
    # a proposal by address matches unmanaged ends only there (the traffic counts match every end).
    return key[3:] if key.startswith("ip:") else ""


def apply_deny(edges: Sequence[EdgeIn], p: DenyProposal, hosts: Callable[[str], HostInfo]) -> list[EdgeIn]:
    """The graph's edges a proposal leaves in place."""
    return [e for e in edges if not edge_matches(p, hosts(e.src), hosts(e.dst), src_ip=_ip_of(e.src),
                                                  dst_ip=_ip_of(e.dst), port=e.port, proto=e.proto)]


def _endpoint(key: str, hosts: Mapping[str, HostInfo]) -> EndpointFilter:
    h = hosts.get(key)
    if key.startswith("ip:"):
        return EndpointFilter(ips=(key[3:],))
    return EndpointFilter(hrefs=(h.href if h and h.href else key,))


def cut_to_proposal(cut: Cut, hosts: Mapping[str, HostInfo]) -> DenyProposal:
    """An edge cut becomes "deny <src> → <dst> on its ports"; a host cut becomes "deny everything into
    the host" — the same thing suggest_cuts counted, so the simulation repeats the cut's numbers."""
    if cut.kind == "edge" and cut.dst is not None:
        return DenyProposal(src=_endpoint(cut.src, hosts), dst=_endpoint(cut.dst, hosts),
                            ports=tuple(PortProto(port=port, proto=proto) for port, proto in cut.ports))
    return DenyProposal(src=EndpointFilter(), dst=_endpoint(cut.src, hosts))
