"""mod15 可達性與 node_ips 的效能守門測試。

Audit bug 1: `_bfs_reachability` 無條件把每個鄰居入列，等於枚舉所有 simple
path（密集圖上數百萬條），而輸出只用得到「可達節點 + 一條最短路徑」。
Audit bug 2: node_ips 以 list membership 去重，未標記端點全擠在同一個 key，
成本是 rows × distinct-IP 的平方。
"""
from __future__ import annotations

import random
import time
from collections import deque

import pandas as pd

from src.report.analysis.mod15_lateral_movement import (
    _bfs_reachability,
    lateral_movement_risk,
)


def _reference_bfs(source, adjacency, max_depth):
    """獨立實作的 visited-set BFS，作為不變量對照。"""
    paths = {}
    q = deque([(source, [source])])
    while q:
        node, path = q.popleft()
        if len(path) - 1 >= max_depth:
            continue
        for nxt in sorted(adjacency.get(node, set())):
            if nxt == source or nxt in paths:
                continue
            paths[nxt] = path + [nxt]
            q.append((nxt, path + [nxt]))
    return paths


def _random_graph(n_nodes, out_degree, seed):
    rnd = random.Random(seed)
    nodes = [f"app{i}|prod" for i in range(n_nodes)]
    adjacency = {}
    for node in nodes:
        adjacency[node] = set(rnd.sample([n for n in nodes if n != node], out_degree))
    return nodes, adjacency


def test_bfs_matches_reference_visited_bfs():
    for seed in range(20):
        nodes, adjacency = _random_graph(12, 4, seed)
        for source in nodes[:3]:
            got = _bfs_reachability(source, adjacency, max_depth=4)
            expected = _reference_bfs(source, adjacency, max_depth=4)
            assert set(got) == set(expected), f"reachable set differs (seed={seed})"
            assert got == expected, f"recorded paths differ (seed={seed})"


def test_bfs_respects_max_depth():
    adjacency = {"a": {"b"}, "b": {"c"}, "c": {"d"}, "d": {"e"}}
    reached = _bfs_reachability("a", adjacency, max_depth=2)
    assert set(reached) == {"b", "c"}
    assert reached["c"] == ["a", "b", "c"]


def test_bfs_is_linear_on_a_dense_graph():
    """密集圖必須秒級完成；枚舉所有 simple path 的舊實作在此規模會爆量。"""
    nodes, adjacency = _random_graph(60, 25, seed=7)
    start = time.perf_counter()
    for node in nodes:
        _bfs_reachability(node, adjacency, max_depth=4)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"dense-graph reachability took {elapsed:.1f}s"


def _flow(src_app, src_ip, dst_app, dst_ip):
    return {
        "src_app": src_app, "src_env": "prod", "src_ip": src_ip,
        "dst_app": dst_app, "dst_env": "prod", "dst_ip": dst_ip,
        "port": 445, "policy_decision": "allowed", "num_connections": 1,
    }


def test_node_ips_dedupes_and_keeps_first_seen_order():
    df = pd.DataFrame([
        _flow("web", "10.0.0.1", "db", "10.0.1.1"),
        _flow("web", "10.0.0.2", "db", "10.0.1.1"),
        _flow("web", "10.0.0.1", "db", "10.0.1.2"),
    ])
    out = lateral_movement_risk(df)
    node_ips = out["node_ips"]
    assert node_ips["web|prod"] == ["10.0.0.1", "10.0.0.2"]
    assert node_ips["db|prod"] == ["10.0.1.1", "10.0.1.2"]
