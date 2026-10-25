"""The exposure graph (spec §6.5.1 "可能性"): observed management-port edges, now vs all enforced."""
import random
import time
from collections import deque
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.exposure import (
    EdgeIn,
    Foothold,
    articulation_points,
    build_graph,
    collapse,
    compute_exposure,
    cross_env,
    edge_state,
    paths_to,
    reach_counts,
    suggest_cuts,
)
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.values import EdgeState

A, P, U = EdgeState.ALLOWED, EdgeState.POTENTIALLY_BLOCKED, EdgeState.UNKNOWN
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


def e(src, dst, state=P, port=22, proto=6):
    return EdgeIn(src, dst, port, proto, state)


def _bfs_reach(g, v, hops):
    seen, q = {v}, deque([(v, 0)])
    while q:
        node, d = q.popleft()
        if d == hops:
            continue
        for u in g.out[node]:
            if u not in seen:
                seen.add(u)
                q.append((u, d + 1))
    return len(seen) - 1


def test_edge_state_mapping():
    assert edge_state("allowed") is A and edge_state("potentially_blocked") is P
    assert edge_state("blocked") is None and edge_state("blocked_by_boundary") is None
    assert edge_state("unknown") is U and edge_state(None) is U


def test_reach_counts_match_bfs_on_random_graphs():
    rnd = random.Random(7)
    for _ in range(200):
        n = rnd.randint(2, 25)
        edges = [e(f"h{rnd.randrange(n)}", f"h{rnd.randrange(n)}") for _ in range(rnd.randint(1, 60))]
        g = build_graph(edges, enforced=False)
        hops = rnd.randint(1, 4)
        assert reach_counts(g, hops) == [_bfs_reach(g, i, hops) for i in range(len(g.nodes))]


def test_enforced_graph_keeps_only_allowed():
    g = build_graph([e("a", "b", A), e("b", "c", P), e("c", "d", U)], enforced=True)
    assert g.nodes == ("a", "b") and len(g.edge_info) == 1


def test_unknown_edges_in_now_marked():
    g = build_graph([e("a", "b", U), e("a", "b", U, port=445), e("b", "c", P)], enforced=False)
    states = {(g.nodes[a], g.nodes[b]): info[1] for (a, b), info in g.edge_info.items()}
    assert states == {("a", "b"): U, ("b", "c"): P}
    ports = next(info[0] for (a, b), info in g.edge_info.items() if g.nodes[a] == "a")
    assert ports == frozenset({(22, 6), (445, 6)})
    # the strongest state of parallel ports wins
    g2 = build_graph([e("a", "b", U), e("a", "b", A, port=3389)], enforced=False)
    assert next(iter(g2.edge_info.values()))[1] is A


def test_blocked_edges_excluded():
    # blocked observations never reach build_graph (edge_state returns None); self-loops are dropped
    g = build_graph([e("a", "a"), e("a", "b")], enforced=False)
    assert g.nodes == ("a", "b") and reach_counts(g, 3) == [1, 0]


def test_articulation_points_on_deep_chain():
    chain = [e(f"n{i:05d}", f"n{i + 1:05d}") for i in range(10_000)]
    pts = articulation_points(build_graph(chain, enforced=False))
    assert len(pts) == 9_999 and "n00000" not in pts and "n10000" not in pts
    star = build_graph([e("hub", x) for x in "abc"], enforced=False)
    assert articulation_points(star) == frozenset({"hub"})


def test_paths_shortest_and_deterministic():
    g = build_graph([e("a", "b"), e("b", "t"), e("a", "c"), e("c", "t"), e("d", "a")], enforced=False)
    p = paths_to(g, "t", 3)
    assert p["a"] == ("a", "b", "t")  # b before c by name: the same path every run
    assert p["d"] == ("d", "a", "b", "t") and "t" not in p
    assert "d" not in paths_to(g, "t", 2)


def test_cross_env_requires_both_envs():
    g = build_graph([e("a", "b"), e("a", "c"), e("b", "c")], enforced=False)
    out = cross_env(g, {"a": "Dev", "b": "Prod", "c": None})
    assert [(x.src, x.dst, x.src_env, x.dst_env) for x in out] == [("a", "b", "Dev", "Prod")]


def test_collapse_by_label():
    g = build_graph([e("a1", "b1"), e("a2", "b1", A), e("a1", "a2"), e("x", "b1")], enforced=False)
    gg = collapse(g, {"a1": "app-a", "a2": "app-a", "b1": "app-b"})
    edges = {(s, d): (n, st) for s, d, n, st in gg.edges}
    assert edges[("app-a", "app-b")] == (2, A) and edges[("app-a", "app-a")] == (1, P)
    assert edges[(None, "app-b")] == (1, P) and set(gg.groups) == {"app-a", "app-b", None}


def test_cut_suggestion_reduces_reach():
    # seven sources reach fin-db through bak-01 → fin-db; two have their own way in
    edges = [e(f"s{i}", "bak-01") for i in range(5)] + [e("bak-01", "fin-db", port=3389)]
    edges += [e("x1", "y1"), e("y1", "fin-db"), e("x1", "bak-01")]
    g = build_graph(edges, enforced=False)
    before = len(paths_to(g, "fin-db", 3))
    cuts = suggest_cuts(g, "fin-db", 3)
    best = cuts[0]
    assert (best.kind, best.src, best.dst, best.before) == ("edge", "bak-01", "fin-db", before)
    assert best.ports == [(3389, 6)] and best.after == 2  # y1 and x1 still get in


def _host(key, critical=False):
    return HostInfo(key=key, href=key, hostname=key, managed=True, labels={}, enforcement_mode=None,
                    visibility_level=None, os_id=None, ven_href=None, critical=critical, admin_group=False)


def test_compute_exposure_shape_and_asset_limit():
    edges = [e("a", "b", A), e("b", "c"), e("c", "d", U), e("x", "c")]
    hosts = {k: _host(k, critical=k in ("c", "d")) for k in "abcdx"}
    r = compute_exposure(edges, hosts, [Foothold(host="c", name="RDP", port=3389, proto=6, severity="critical")],
                         hops=3, critical=frozenset({"c", "d"}), env_of={}, computed_at=NOW,
                         observation_from=NOW - timedelta(days=30), observation_to=NOW, max_assets=1)
    assert (r.nodes, r.edges_now, r.edges_enforced, r.unknown_edges) == (5, 4, 1, 1)
    by_key = {h.key: h for h in r.hosts}
    assert (by_key["a"].reach_now, by_key["a"].reach_enforced) == (3, 1)
    assert r.hosts[0].key == "a"
    first, second = r.assets
    assert first.key == "d" and first.sources_now == 4 and first.paths and first.cuts  # most reachable first
    assert second.key == "c" and second.paths == [] and second.cuts == [] and "assets" in r.limits_hit
    assert r.footholds[0].host == "c"


def test_compute_exposure_performance():
    rnd = random.Random(11)
    n = 2_000
    edges = [e(f"h{rnd.randrange(n):04d}", f"h{rnd.randrange(n):04d}", rnd.choice([A, P, P, U]))
             for _ in range(60_000)]
    hosts = {f"h{i:04d}": _host(f"h{i:04d}", critical=i < 20) for i in range(n)}
    start = time.monotonic()
    r = compute_exposure(edges, hosts, [], hops=3, critical=frozenset(f"h{i:04d}" for i in range(20)), env_of={},
                         computed_at=NOW, observation_from=NOW - timedelta(days=30), observation_to=NOW)
    assert time.monotonic() - start < 120
    assert r.nodes == n and len(r.assets) == 20
