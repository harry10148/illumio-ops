"""The investigation table's peer precedent (UI redesign spec §5.1): for a row naming a source host and a destination,
how many other members of the source's peer group (the lateral settings' peer group labels, at least peer_min_group
managed hosts) had connected, before the period began, to a destination of the same kind — the destination's own
peer group when it is a managed host in one, else that host — on the request's ports (any port when it names none).
The same baseline and signature the peer-deviation detector reads (spec §6.5.8 A)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from illumio_ops.domain.anomaly import group_of, target_signature
from illumio_ops.domain.values import CollectionMode, SegmentDimension
from illumio_ops.services.analysis.context import (
    LateralContext,
    host_for,
    load_lateral_context,
)
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import AggRow
from illumio_ops.services.flowsource_anomaly import peer_destinations
from illumio_ops.services.workbench import (
    FlowRequest,
    PeerPrecedent,
    PeerRowReason,
    PeerState,
)


def _ip(key: str) -> str:
    return key[3:] if key.startswith("ip:") else ""


def _signature(lc: LateralContext, key: str, keys: Sequence[str]) -> str | None:
    return target_signature(key, _ip(key), host_for(lc, key, ip=_ip(key), hostname=None), keys)


def peer_precedent(ctx: AppContext, req: FlowRequest, rows: Sequence[AggRow], *,
                   now: datetime | None = None) -> PeerPrecedent:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    ports = list(req.condition.ports)
    port_words = [("" if p.port is None else f"{p.port}" + (f"-{p.to_port}" if p.to_port is not None else ""))
                  + ("" if p.proto is None else f"/{p.proto}") for p in ports]
    dims = [g.dimension for g in req.group_by]

    def blank(state: PeerState) -> PeerPrecedent:
        return PeerPrecedent(state=state, values=[None] * len(rows), reasons=[None] * len(rows), ports=port_words)

    if ctx.settings.current().collection.mode is CollectionMode.LIGHTWEIGHT:
        return blank("basic_mode")  # no baseline is kept
    if SegmentDimension.SRC_HOST not in dims:
        return blank("no_source_dimension")
    if SegmentDimension.DST_HOST not in dims:
        return blank("needs_destination")
    si, di = dims.index(SegmentDimension.SRC_HOST), dims.index(SegmentDimension.DST_HOST)
    lat = ctx.settings.current().lateral
    keys = lat.peer_group_keys
    lc = load_lateral_context(ctx, now=at)
    members: dict[str, list[str]] = {}
    for key, host in lc.hosts.items():
        group = group_of(host.labels, keys) if host.managed else None
        if group is not None:
            members.setdefault(group, []).append(key)

    groups: list[str | None] = []
    reasons: list[PeerRowReason | None] = []
    for r in rows:
        src = lc.hosts.get(str(r.keys[si]))
        group = group_of(src.labels, keys) if src is not None and src.managed else None
        if group is None:
            groups.append(None)
            reasons.append("no_group")
        elif len(members[group]) < lat.detectors.peer_min_group:
            groups.append(None)
            reasons.append("group_too_small")
        else:
            groups.append(group)
            reasons.append(None)
    wanted = {m for g in groups if g is not None for m in members[g]}
    pairs = peer_destinations(ctx, wanted, ports=ports, before=req.start) if wanted else set()
    sig_cache: dict[str, str | None] = {}

    def sig(key: str) -> str | None:
        if key not in sig_cache:
            sig_cache[key] = _signature(lc, key, keys)
        return sig_cache[key]

    values: list[int | None] = []
    for r, group in zip(rows, groups, strict=True):
        if group is None:
            values.append(None)
            continue
        src_key, dst_sig = str(r.keys[si]), sig(str(r.keys[di]))
        peers = set(members[group]) - {src_key}
        values.append(len({s for s, d in pairs if s in peers and dst_sig is not None and sig(d) == dst_sig}))
    return PeerPrecedent(state="ok", values=values, reasons=reasons, ports=port_words)
