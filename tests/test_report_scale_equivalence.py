"""The scale rewrites of mod13/mod14/mod15 must give the same answers.

Each rewrite replaced a per-key or per-pair loop that was quadratic at
thousands of app|env keys (measured 2026-10: 149 s → 19 s for the three
modules at 100k flows / ~4,000 keys). These tests pin the new code to the
old formulation on random data, so "faster" can never quietly mean
"different".
"""
from __future__ import annotations

import random
from collections import deque

import numpy as np
import pandas as pd
import pytest

from src.report.analysis._key_rows import rows_by_key
from src.report.analysis import mod13_readiness, mod14_infrastructure, mod15_lateral_movement


def _random_flows(seed: int, n: int = 400, apps: int = 12) -> pd.DataFrame:
    r = random.Random(seed)
    modes = ["full", "selective", "visibility_only", "idle", "", None]
    rows = []
    for _ in range(n):
        rows.append({
            "src_app": f"a{r.randrange(apps)}", "src_env": r.choice(["prod", "dev", ""]),
            "dst_app": f"a{r.randrange(apps)}", "dst_env": r.choice(["prod", "dev", ""]),
            "src_ip": f"10.0.0.{r.randrange(30)}", "dst_ip": f"10.0.1.{r.randrange(30)}",
            "src_enforcement": r.choice(modes), "dst_enforcement": r.choice(modes),
            "src_managed": r.random() < 0.7, "dst_managed": r.random() < 0.7,
            "port": r.choice([22, 3389, 445, 135, 5985, 443, 3306, 88]),
            "service": "svc", "num_connections": r.randrange(1, 50),
            "policy_decision": r.choice(["allowed", "potentially_blocked", "blocked"]),
        })
    df = pd.DataFrame(rows)
    df.index = df.index * 3 + 7  # a non-default index must survive the row lookups
    return df


@pytest.mark.parametrize("seed", range(5))
def test_rows_by_key_matches_the_boolean_mask(seed):
    df = _random_flows(seed)
    df["src_key"] = df["src_app"] + "|" + df["src_env"]
    df["dst_key"] = df["dst_app"] + "|" + df["dst_env"]
    rows = rows_by_key(df)
    keys = set(df["src_key"]) | set(df["dst_key"])
    assert set(rows) == keys
    for key in keys:
        expected = df[(df["src_key"] == key) | (df["dst_key"] == key)]
        pd.testing.assert_frame_equal(df.iloc[rows[key]], expected)


def _old_app_enforce_ratio(flows: pd.DataFrame, key: str):
    """The per-key formulation _enforce_ratio_by_key replaced."""
    parts = []
    for side in ("src", "dst"):
        mode_col, ip_col = f"{side}_enforcement", f"{side}_ip"
        if mode_col not in flows.columns:
            continue
        sel = flows[f"{side}_key"] == key
        parts.append(pd.DataFrame({
            "ip": flows.loc[sel, ip_col] if ip_col in flows.columns else flows.loc[sel].index,
            "mode": flows.loc[sel, mode_col],
        }))
    if not parts:
        return None
    wl = pd.concat(parts, ignore_index=True)
    wl["mode"] = wl["mode"].fillna("").astype(str).str.strip().str.lower()
    wl = wl[wl["mode"] != ""].drop_duplicates(subset=["ip"])
    if wl.empty:
        return None
    return float(wl["mode"].map(lambda m: mod13_readiness._ENFORCED.get(m, 0.0)).mean())


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("drop", [(), ("dst_enforcement",), ("src_ip", "dst_ip")])
def test_enforce_ratio_by_key_matches_the_per_key_version(seed, drop):
    df = _random_flows(seed).drop(columns=list(drop))
    df["src_key"] = df["src_app"] + "|" + df["src_env"]
    df["dst_key"] = df["dst_app"] + "|" + df["dst_env"]
    got = mod13_readiness._enforce_ratio_by_key(df)
    for key in set(df["src_key"]) | set(df["dst_key"]):
        flows = df[(df["src_key"] == key) | (df["dst_key"] == key)]
        assert got.get(key) == _old_app_enforce_ratio(flows, key), key


def test_enforce_ratio_by_key_without_modes_is_none():
    df = _random_flows(0).drop(columns=["src_enforcement", "dst_enforcement"])
    df["src_key"] = df["src_app"]
    df["dst_key"] = df["dst_app"]
    assert mod13_readiness._enforce_ratio_by_key(df) is None


def _old_betweenness(nodes, adjacency):
    bc = {n: 0.0 for n in nodes}
    for source in nodes:
        stack, preds = [], {v: [] for v in nodes}
        sigma = {v: 0.0 for v in nodes}
        dist = {v: -1 for v in nodes}
        sigma[source], dist[source] = 1.0, 0
        q = deque([source])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in adjacency.get(v, set()):
                if dist[w] < 0:
                    q.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    preds[w].append(v)
        delta = {v: 0.0 for v in nodes}
        while stack:
            w = stack.pop()
            for v in preds[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != source:
                bc[w] += delta[w]
    m = max(bc.values(), default=0.0)
    return {k: 0.0 for k in bc} if m <= 0 else {k: v / m for k, v in bc.items()}


@pytest.mark.parametrize("seed", range(20))
def test_betweenness_matches_brandes(seed):
    r = random.Random(seed)
    nodes = [f"n{i}" for i in range(r.randint(1, 50))]
    adj: dict[str, set[str]] = {}
    for _ in range(r.randint(0, len(nodes) * 3)):
        a, b = r.choice(nodes), r.choice(nodes)
        if a != b:
            adj.setdefault(a, set()).add(b)
    info: dict = {}
    got = mod14_infrastructure._betweenness_centrality(nodes, adj, info)
    want = _old_betweenness(nodes, adj)
    assert info == {}
    assert got.keys() == want.keys()
    assert all(abs(got[k] - want[k]) < 1e-9 for k in want)


def test_betweenness_samples_sources_on_huge_graphs(monkeypatch):
    monkeypatch.setattr(mod14_infrastructure, "BETWEENNESS_EXACT_MAX_SOURCES", 10)
    monkeypatch.setattr(mod14_infrastructure, "BETWEENNESS_SAMPLE_SOURCES", 5)
    nodes = [f"n{i}" for i in range(30)]
    adj = {nodes[i]: {nodes[i + 1]} for i in range(29)}  # a chain
    info: dict = {}
    got = mod14_infrastructure._betweenness_centrality(nodes, adj, info)
    assert info == {"betweenness_sampled_sources": 5}
    assert max(got.values()) == 1.0


def _old_attack_paths(result_nodes, adjacency, edge_weights, top_n, max_depth):
    from src.report.analysis.attack_posture import build_app_display
    rows = []
    for node in result_nodes:
        app, env = node.split("|", 1)
        for target, path in mod15_lateral_movement._bfs_reachability(node, adjacency, max_depth).items():
            if len(path) <= 2:
                continue
            ta, te = target.split("|", 1)
            rows.append({
                "Source App (Env)": build_app_display(app, env),
                "Source App Env Key": node,
                "Target App (Env)": build_app_display(ta, te),
                "Target App Env Key": target,
                "Path Depth": len(path) - 1,
                "Path": " → ".join(build_app_display(*h.split("|", 1)) for h in path),
                "Path Connection Weight": mod15_lateral_movement._path_weight(path, edge_weights),
            })
    if not rows:
        return pd.DataFrame()
    return (pd.DataFrame(rows)
            .sort_values(by=["Path Depth", "Path Connection Weight", "Source App Env Key"],
                         ascending=[False, False, True])
            .head(top_n).reset_index(drop=True))


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("top_n", [3, 20])
def test_attack_paths_keep_the_full_tables_top_n(seed, top_n):
    df = _random_flows(seed, n=600, apps=15)
    out = mod15_lateral_movement.lateral_movement_risk(df, top_n=top_n)

    # Rebuild the graph the way the module does and rank every path the old way.
    work = df.copy()
    work["policy_decision"] = work["policy_decision"].str.lower()
    work["src_key"] = mod15_lateral_movement._normalize_key_series(work, "src_app", "src_env")
    work["dst_key"] = mod15_lateral_movement._normalize_key_series(work, "dst_app", "dst_env")
    ports = mod15_lateral_movement._lateral_ports(None)
    trav = work[work["port"].isin(ports) & work["policy_decision"].isin(["allowed", "potentially_blocked"])]
    trav = trav[trav["src_key"] != trav["dst_key"]]
    weights: dict = {}
    adj: dict = {}
    for s, d, w in zip(trav["src_key"], trav["dst_key"], trav["num_connections"]):
        weights[(s, d)] = weights.get((s, d), 0) + int(w)
        adj.setdefault(s, set()).add(d)
    nodes = sorted(set(adj) | {d for v in adj.values() for d in v})
    want = _old_attack_paths(nodes, adj, weights, top_n, 4)
    pd.testing.assert_frame_equal(out["attack_paths"], want)


def test_reach_count_matches_bfs():
    r = random.Random(3)
    nodes = [f"n{i}" for i in range(40)]
    adj: dict = {}
    for _ in range(90):
        a, b = r.sample(nodes, 2)
        adj.setdefault(a, set()).add(b)
    sorted_adj = {k: sorted(v) for k, v in adj.items()}
    for n in nodes:
        for depth in (1, 2, 4):
            assert (mod15_lateral_movement._reach_count(n, sorted_adj, depth)
                    == len(mod15_lateral_movement._bfs_reachability(n, adj, depth)))
            assert (mod15_lateral_movement._bfs_reachability(n, sorted_adj, depth)
                    == mod15_lateral_movement._bfs_reachability(n, adj, depth))
