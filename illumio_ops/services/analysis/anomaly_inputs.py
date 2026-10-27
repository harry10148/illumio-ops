"""What the anomaly detectors need besides the run's connections (spec §6.5.8): peer groups, hourly activity, and
the account, process and directory baselines — looked up only for the keys this run's candidates name."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.anomaly import (
    ACTIVITY_DAYS,
    DIRECTORY,
    DIRECTORY_DETECTORS,
    DYNAMIC_PORTS,
    SURGE_WINDOW,
    group_of,
    is_public,
    target_signature,
)
from illumio_ops.domain.detectors import (
    Activity,
    AnomalyData,
    DetectorInput,
    Obs,
    evaluable,
    not_blocked,
)
from illumio_ops.domain.identity import account_key
from illumio_ops.domain.lateral import AdminPortSet, selector_matches
from illumio_ops.services import flowsource_anomaly as fa
from illumio_ops.services.analysis.context import LateralContext, host_for
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import LateralSettings
from illumio_ops.store.flowdb import analysis


def _candidates(inp: DetectorInput) -> list[Obs]:
    return [o for o in inp.traffic_obs if o.origin == "ingest" and evaluable(o, inp) and not_blocked(o)]


def _first_in_window(inp: DetectorInput, o: Obs) -> bool:
    lo, hi = inp.window
    first = inp.baseline_first_seen.get((o.src_key, o.dst_key, o.port if o.port is not None else -1, o.proto))
    return first is not None and lo < first <= hi


def _peers(ctx: AppContext, lc: LateralContext, inp: DetectorInput, rows: Sequence[Obs]) -> tuple[
        dict[str, int], dict[tuple[str, int, int], frozenset[str]]]:
    cfg = inp.config
    keys = cfg.peer_group_keys
    members: dict[str, list[str]] = {}
    for key, host in lc.hosts.items():
        group = group_of(host.labels, keys) if host.managed else None
        if group is not None:
            members.setdefault(group, []).append(key)
    sizes = {g: len(m) for g, m in members.items()}
    wanted: set[tuple[str, int, int]] = set()
    for o in rows:
        if o.port is None or o.port >= DYNAMIC_PORTS or cfg.admin_ports.matches(o.port, o.proto):
            continue
        src = lc.hosts.get(o.src_key)
        group = group_of(src.labels, keys) if src is not None and src.managed else None
        if group is not None and sizes.get(group, 0) >= cfg.peer_min_group and _first_in_window(inp, o):
            wanted.add((group, o.port, o.proto))
    found = fa.peer_seen(ctx, {w: members[w[0]] for w in wanted}, before=inp.window[0]) if wanted else {}
    seen: dict[tuple[str, int, int], frozenset[str]] = {}
    for asked, dsts in found.items():
        sigs = set()
        for dst in dsts:
            ip = dst[3:] if dst.startswith("ip:") else ""
            sig = target_signature(dst, ip, host_for(lc, dst, ip=ip, hostname=None), keys)
            if sig is not None:
                sigs.add(sig)
        seen[asked] = frozenset(sigs)
    return sizes, seen


def _activity(ctx: AppContext, inp: DetectorInput, at: datetime) -> tuple[
        dict[tuple[str, str], Activity], float, tuple[tuple[datetime, datetime, str], ...]]:
    cfg = inp.config
    covered = fa.activity_coverage(ctx)
    hour = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    days = (hour - covered) / timedelta(days=1) if covered is not None else 0.0
    if days < ACTIVITY_DAYS:
        return {}, max(days, 0.0), ()
    now = fa.activity_now(ctx, since=at - SURGE_WINDOW, until=at)
    floors = {"all": cfg.volume_min_connections, "directory": cfg.directory_min_connections}
    over = {k: v for k, v in now.items()
            if v[0] >= floors[k[1]] or (k[1] == "all" and v[1] is not None and v[1] >= cfg.volume_min_bytes)}
    history = fa.activity_history(ctx, sorted({src for src, _ in over}), start=hour - timedelta(days=ACTIVITY_DAYS),
                                  end=hour - timedelta(hours=1)) if over else {}
    gaps = tuple(fa.activity_gaps(ctx, start=hour - timedelta(days=ACTIVITY_DAYS), end=hour)) if over else ()
    return {k: Activity(v[0], v[1], *history.get(k, (0, None))) for k, v in over.items()}, days, gaps


@dataclass(frozen=True)
class DirectoryServers:
    """The directory servers (spec §6.5.8 E): inferred from traffic, declared by label, declared by address.
    The detectors and the lateral posture report read them through directory_servers()."""
    inferred: frozenset[str]
    declared: frozenset[str]
    ips: frozenset[str]
    sources: Mapping[str, int]  # destination -> distinct sources on directory ports since `since`
    ports: tuple[fa.PortSpec, ...]

    @property
    def servers(self) -> frozenset[str]:
        return self.inferred | self.declared


def directory_servers(ctx: AppContext, lc: LateralContext, admin_ports: AdminPortSet, *,
                      since: datetime) -> DirectoryServers:
    lat: LateralSettings = lc.settings
    ports = tuple(sorted({(e.port, e.proto) for e in admin_ports.entries if e.category in DIRECTORY}, key=str))
    ips = frozenset(lat.directory_server_ips)
    selectors = [(s.key, s.value) for s in lat.directory_servers]
    declared = frozenset(k for k, h in lc.hosts.items() if selectors and selector_matches(h.labels, selectors))
    if not ports:
        return DirectoryServers(frozenset(), declared, ips, {}, ports)

    def internal(key: str) -> bool:
        host = lc.hosts.get(key)
        return host.managed if host is not None else key.startswith("ip:") and not is_public(key[3:])

    counts = fa.directory_sources(ctx, ports, since=since)
    inferred = frozenset(k for k, n in counts.items() if n >= lat.detectors.directory_min_sources and internal(k))
    return DirectoryServers(inferred, declared, ips, counts, ports)


def _with_directory(ctx: AppContext, lc: LateralContext, inp: DetectorInput, rows: Sequence[Obs], at: datetime,
                    data: AnomalyData) -> AnomalyData:
    cfg = inp.config
    ds = directory_servers(ctx, lc, cfg.admin_ports, since=at - timedelta(days=lc.baseline_required))
    if not ds.ports:
        return data
    servers, ips, ports = ds.servers, ds.ips, ds.ports
    directory_rows = [o for o in rows if cfg.admin_ports.matches(o.port, o.proto, DIRECTORY)
                      and (o.dst_key in servers or o.dst_ip in ips)]
    candidates = {o.src_key for o in directory_rows if _first_in_window(inp, o)}
    # A server declared by address is ip:<address> in the baseline, or the managed host that holds it now.
    by_address = {f"ip:{ip}" for ip in ips} | {o.dst_key for o in directory_rows if o.dst_ip in ips}
    before = fa.directory_clients_before(ctx, candidates, servers | by_address, ports,
                                         before=inp.window[0]) if candidates else set()
    subjects = {o.src_key for o in [*inp.obs, *inp.traffic_obs]}
    with ctx.flows().connect() as conn:
        recent = analysis.detections_about(conn, subjects, since=inp.window[0] - cfg.directory_followup,
                                           detectors=[d.value for d in DIRECTORY_DETECTORS])
    return replace(data, directory_servers=frozenset(servers), directory_ips=ips, directory_inferred=len(ds.inferred),
                   directory_declared_missing=len(ds.declared - ds.inferred), directory_clients_before=frozenset(before),
                   recent_directory=[(r["subject_key"], r["detector"], datetime.fromisoformat(r["first_seen"]),
                                      datetime.fromisoformat(r["last_seen"])) for r in recent])


def load_anomaly_data(ctx: AppContext, lc: LateralContext, inp: DetectorInput, *, at: datetime,
                      live: bool) -> AnomalyData:
    """inp carries the run's window, traffic_obs and baseline_first_seen (for every candidate tuple)."""
    rows = _candidates(inp)
    sizes, peer_seen = _peers(ctx, lc, inp, rows)
    activity, days, gaps = _activity(ctx, inp, at) if live else ({}, 0.0, ())
    lo, hi = inp.window
    pairs = {(a, o.src_key) for o in rows if (a := account_key(o.initiator_user)) is not None}
    account_first = fa.account_first_seen(ctx, pairs) if pairs else {}
    accounts = {a for (a, _), first in account_first.items() if lo < first <= hi}
    procs = {(o.src_key, o.initiator_process) for o in rows if o.initiator_process}
    process_first = fa.process_first_seen(ctx, procs) if procs else {}
    hosts = {s for (s, _), first in process_first.items() if lo < first <= hi}
    data = AnomalyData(
        peer_seen=peer_seen, group_sizes=sizes, activity=activity, activity_days=days, activity_gaps=gaps, live=live,
        account_first=account_first,
        account_since=fa.account_since(ctx, accounts) if accounts else {},
        account_sources=fa.account_history(ctx, accounts, before=lo) if accounts else {},
        process_first=process_first, process_since=fa.process_since(ctx, hosts) if hosts else {})
    return _with_directory(ctx, lc, inp, rows, at, data)
