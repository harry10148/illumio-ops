"""The lateral-movement exposure graph (spec §6.5.1 "可能性").

Nodes are hosts (managed workloads by href, unmanaged ends as ip:<address>); an edge is a management-port
connection actually observed in the observation period, by the reported decision of its newest
observation. "Now" holds every edge that was not blocked (allowed, potentially blocked, and unknown —
unknown is marked and counted, P3 ruling); "all enforced" keeps only allowed edges. The difference is
what enforcement buys. Edges come from observed traffic, not from policy.

Pure and bounded: reach counts use integer bitsets (k passes over the edges, no per-node BFS), the
articulation points an iterative Tarjan (5.x's recursive one gave up on deep graphs), paths a reverse
BFS in node-name order so they are the same on every run.
"""
from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.values import EdgeState

_STRENGTH = {EdgeState.UNKNOWN: 0, EdgeState.POTENTIALLY_BLOCKED: 1, EdgeState.ALLOWED: 2}
Port = tuple[int, int]  # (port, proto)


@dataclass(frozen=True)
class EdgeIn:
    src: str
    dst: str
    port: int
    proto: int
    state: EdgeState


def edge_state(decision: str | None) -> EdgeState | None:
    """The reported decision of an edge's newest observation; None = blocked, not in the graph."""
    if decision is None:
        return EdgeState.UNKNOWN
    d = decision.strip().lower()
    if d == "allowed":
        return EdgeState.ALLOWED
    if d == "potentially_blocked":
        return EdgeState.POTENTIALLY_BLOCKED
    if d.startswith("blocked"):
        return None
    return EdgeState.UNKNOWN


@dataclass(frozen=True)
class Graph:
    nodes: tuple[str, ...]
    index: Mapping[str, int]
    out: tuple[tuple[int, ...], ...]
    edge_info: Mapping[tuple[int, int], tuple[frozenset[Port], EdgeState]]


def build_graph(edges: Iterable[EdgeIn], *, enforced: bool) -> Graph:
    """One edge per host pair: its ports merged, its state the strongest of them."""
    merged: dict[tuple[str, str], tuple[set[Port], EdgeState]] = {}
    for e in edges:
        if e.src == e.dst or (enforced and e.state is not EdgeState.ALLOWED):
            continue
        ports, state = merged.setdefault((e.src, e.dst), (set(), e.state))
        ports.add((e.port, e.proto))
        if _STRENGTH[e.state] > _STRENGTH[state]:
            merged[(e.src, e.dst)] = (ports, e.state)
    nodes = tuple(sorted({n for pair in merged for n in pair}))
    index = {n: i for i, n in enumerate(nodes)}
    out: list[list[int]] = [[] for _ in nodes]
    info: dict[tuple[int, int], tuple[frozenset[Port], EdgeState]] = {}
    for (s, d), (ports, state) in sorted(merged.items()):
        out[index[s]].append(index[d])
        info[(index[s], index[d])] = (frozenset(ports), state)
    return Graph(nodes=nodes, index=index, out=tuple(tuple(sorted(o)) for o in out), edge_info=info)


def reach_counts(g: Graph, hops: int) -> list[int]:
    """How many hosts each host reaches in at most `hops` steps.

    R1[v] = v's neighbours as a bitset; R(i+1)[v] = R(i)[v] | OR of R(i)[u] over v's neighbours u.
    """
    direct = [0] * len(g.nodes)
    for v, outs in enumerate(g.out):
        for u in outs:
            direct[v] |= 1 << u
    reach = direct[:]
    for _ in range(hops - 1):
        nxt = reach[:]
        for v, outs in enumerate(g.out):
            acc = nxt[v]
            for u in outs:
                acc |= reach[u]
            nxt[v] = acc
        reach = nxt
    return [(r & ~(1 << v)).bit_count() for v, r in enumerate(reach)]


def _reverse(g: Graph) -> list[list[int]]:
    rev: list[list[int]] = [[] for _ in g.nodes]
    for v, outs in enumerate(g.out):
        for u in outs:
            rev[u].append(v)
    return rev  # in node-name order: g.nodes is sorted and v is visited in order


def _paths_to(g: Graph, rev: list[list[int]], target: int, hops: int, *, skip_edge: tuple[int, int] | None = None,
              skip_node: int | None = None) -> dict[int, int]:
    """Reverse BFS from target: source -> next hop on its shortest path (ties by node name)."""
    nxt: dict[int, int] = {}
    dist = {target: 0}
    q = deque([target])
    while q:
        node = q.popleft()
        if dist[node] == hops:
            continue
        for pred in rev[node]:
            if pred in dist or pred == skip_node or (pred, node) == skip_edge:
                continue
            dist[pred] = dist[node] + 1
            nxt[pred] = node
            q.append(pred)
    return nxt


def _path(nxt: dict[int, int], source: int, target: int) -> list[int]:
    path = [source]
    while path[-1] != target:
        path.append(nxt[path[-1]])
    return path


def paths_to(g: Graph, target: str, hops: int) -> dict[str, tuple[str, ...]]:
    """Every host that reaches `target` within `hops` steps -> its shortest path (target excluded)."""
    if target not in g.index:
        return {}
    t = g.index[target]
    nxt = _paths_to(g, _reverse(g), t, hops)
    return {g.nodes[s]: tuple(g.nodes[i] for i in _path(nxt, s, t)) for s in nxt}


def articulation_points(g: Graph) -> frozenset[str]:
    """Hosts whose removal splits the (undirected) graph — the pivots; iterative Tarjan."""
    n = len(g.nodes)
    adj: list[set[int]] = [set() for _ in range(n)]
    for v, outs in enumerate(g.out):
        for u in outs:
            adj[v].add(u)
            adj[u].add(v)
    neighbours = [sorted(a) for a in adj]
    disc = [-1] * n
    low = [0] * n
    points: set[int] = set()
    clock = 0
    for root in range(n):
        if disc[root] != -1:
            continue
        disc[root] = low[root] = clock
        clock += 1
        children = 0
        stack: list[tuple[int, int, int]] = [(root, -1, 0)]  # (node, parent, next neighbour index)
        while stack:
            v, parent, i = stack[-1]
            if i < len(neighbours[v]):
                stack[-1] = (v, parent, i + 1)
                u = neighbours[v][i]
                if u == parent:
                    continue
                if disc[u] == -1:
                    disc[u] = low[u] = clock
                    clock += 1
                    if v == root:
                        children += 1
                    stack.append((u, v, 0))
                else:
                    low[v] = min(low[v], disc[u])
            else:
                stack.pop()
                if parent != -1:
                    low[parent] = min(low[parent], low[v])
                    if parent != root and low[v] >= disc[parent]:
                        points.add(parent)
        if children > 1:
            points.add(root)
    return frozenset(g.nodes[p] for p in points)


class CrossEnvEdge(BaseModel):
    src: str
    dst: str
    src_env: str
    dst_env: str
    ports: list[Port]
    state: EdgeState


def cross_env(g: Graph, env_of: Mapping[str, str | None]) -> list[CrossEnvEdge]:
    """Management-port edges between two different known environments (5.x L010)."""
    out = []
    for (s, d), (ports, state) in g.edge_info.items():
        se, de = env_of.get(g.nodes[s]), env_of.get(g.nodes[d])
        if se and de and se != de:
            out.append(CrossEnvEdge(src=g.nodes[s], dst=g.nodes[d], src_env=se, dst_env=de, ports=sorted(ports),
                                    state=state))
    return out


class Foothold(BaseModel):
    """A host with an unprotected, listening high-risk service (spec §6.5.6): a place to land."""
    host: str
    name: str
    port: int
    proto: int
    severity: str | None


class GroupGraph(BaseModel):
    groups: list[str | None]  # None = hosts without the label
    edges: list[tuple[str | None, str | None, int, EdgeState]]  # (from, to, host edges, strongest state)


def collapse(g: Graph, group_of: Mapping[str, str | None]) -> GroupGraph:
    """The same graph by a label (app, env): host edges counted between groups."""
    agg: dict[tuple[str | None, str | None], tuple[int, EdgeState]] = {}
    for (s, d), (_, state) in g.edge_info.items():
        key = (group_of.get(g.nodes[s]), group_of.get(g.nodes[d]))
        n, best = agg.get(key, (0, EdgeState.UNKNOWN))
        agg[key] = (n + 1, state if _STRENGTH[state] > _STRENGTH[best] else best)
    groups = sorted({group_of.get(n) for n in g.nodes}, key=lambda x: (x is None, x or ""))
    return GroupGraph(groups=groups, edges=[(a, b, n, st) for (a, b), (n, st) in
                                            sorted(agg.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))])


class Cut(BaseModel):
    kind: Literal["edge", "node"]
    src: str
    dst: str | None
    ports: list[Port]
    before: int
    after: int


def suggest_cuts(g: Graph, target: str, hops: int, *, top: int = 3, max_candidates: int = 60) -> list[Cut]:
    """Greedy single cuts: of the edges and intermediate hosts on the shortest paths into `target`, the
    ones whose removal leaves the fewest hosts reaching it. Ties: an edge before a host, fewer ports
    first (the narrowest deny rule), then by name."""
    if target not in g.index:
        return []
    t = g.index[target]
    rev = _reverse(g)
    base = _paths_to(g, rev, t, hops)
    before = len(base)
    if not before:
        return []
    seen_edges: Counter[tuple[int, int]] = Counter()
    seen_nodes: Counter[int] = Counter()
    for s in base:
        path = _path(base, s, t)
        seen_edges.update(pairwise(path))
        seen_nodes.update(path[1:-1])
    # Candidates: the edges and hosts the most shortest paths go through.
    candidates: list[tuple[int, bool, str, str, int, int | None]] = [
        (-c, False, g.nodes[a], g.nodes[b], a, b) for (a, b), c in seen_edges.items()]
    candidates += [(-c, True, g.nodes[v], "", v, None) for v, c in seen_nodes.items()]
    cuts = []
    for *_, a, b in sorted(candidates)[:max_candidates]:
        if b is not None:
            after = len(_paths_to(g, rev, t, hops, skip_edge=(a, b)))
            ports = sorted(g.edge_info[(a, b)][0])
            cuts.append(Cut(kind="edge", src=g.nodes[a], dst=g.nodes[b], ports=ports, before=before, after=after))
        else:
            after = len(_paths_to(g, rev, t, hops, skip_node=a))
            cuts.append(Cut(kind="node", src=g.nodes[a], dst=None, ports=[], before=before, after=after))
    cuts.sort(key=lambda c: (c.after, c.kind != "edge", len(c.ports), c.src, c.dst or ""))
    return cuts[:top]


class HostExposure(BaseModel):
    key: str
    reach_now: int
    reach_enforced: int
    pivot_now: bool
    pivot_enforced: bool


class AssetExposure(BaseModel):
    key: str
    sources_now: int
    sources_enforced: int
    paths: list[list[str]]  # at most 5, shortest first
    cuts: list[Cut]


class ExposureResult(BaseModel):
    computed_at: datetime
    observation_from: datetime
    observation_to: datetime
    hops: int
    nodes: int
    edges_now: int
    edges_enforced: int
    unknown_edges: int
    hosts: list[HostExposure]
    assets: list[AssetExposure]
    cross_env: list[CrossEnvEdge]
    footholds: list[Foothold]
    limits_hit: list[str]


def compute_exposure(edges: Sequence[EdgeIn], hosts: Mapping[str, HostInfo], footholds: Sequence[Foothold], *,
                     hops: int, critical: frozenset[str], env_of: Mapping[str, str | None], computed_at: datetime,
                     observation_from: datetime, observation_to: datetime, max_assets: int = 50) -> ExposureResult:
    """Everything the lateral-movement page, the focus list and the posture report read. Critical assets
    beyond max_assets (the least reachable ones) are listed with their numbers only, and limits_hit says so."""
    now = build_graph(edges, enforced=False)
    enf = build_graph(edges, enforced=True)
    reach_now = dict(zip(now.nodes, reach_counts(now, hops), strict=True))
    reach_enf = dict(zip(enf.nodes, reach_counts(enf, hops), strict=True))
    pivots_now, pivots_enf = articulation_points(now), articulation_points(enf)
    host_rows = sorted(
        (HostExposure(key=n, reach_now=reach_now[n], reach_enforced=reach_enf.get(n, 0), pivot_now=n in pivots_now,
                      pivot_enforced=n in pivots_enf) for n in now.nodes),
        key=lambda h: (-h.reach_now, h.key))
    now_paths = {a: paths_to(now, a, hops) for a in critical}
    enf_sources = {a: len(paths_to(enf, a, hops)) for a in critical}
    order = sorted(critical, key=lambda a: (-len(now_paths[a]), a))
    assets = []
    for i, a in enumerate(order):
        detailed = i < max_assets
        paths = sorted(now_paths[a].values(), key=lambda p: (len(p), p))[:5] if detailed else []
        assets.append(AssetExposure(key=a, sources_now=len(now_paths[a]), sources_enforced=enf_sources[a],
                                    paths=[list(p) for p in paths],
                                    cuts=suggest_cuts(now, a, hops) if detailed else []))
    return ExposureResult(
        computed_at=computed_at, observation_from=observation_from, observation_to=observation_to, hops=hops,
        nodes=len(now.nodes), edges_now=len(now.edge_info), edges_enforced=len(enf.edge_info),
        unknown_edges=sum(1 for _, st in now.edge_info.values() if st is EdgeState.UNKNOWN),
        hosts=host_rows, assets=assets, cross_env=cross_env(now, env_of), footholds=list(footholds),
        limits_hit=["assets"] if len(order) > max_assets else [])
