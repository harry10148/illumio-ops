"""Module 15: Deterministic graph-centric lateral movement risk."""
from __future__ import annotations

from collections import defaultdict, deque

import pandas as pd

from .attack_posture import build_app_display, make_posture_item, rank_posture_items
from src.i18n import t, get_language


_LATERAL_PORTS = {
    445: "SMB",
    135: "RPC",
    139: "NetBIOS",
    3389: "RDP",
    22: "SSH",
    5985: "WinRM-HTTP",
    5986: "WinRM-HTTPS",
    23: "Telnet",
    2049: "NFS",
    111: "RPC Portmapper",
    389: "LDAP",
    636: "LDAPS",
    88: "Kerberos",
    1433: "MSSQL",
    3306: "MySQL",
    5432: "PostgreSQL",
}


def _normalize_key_series(df: pd.DataFrame, app_col: str, env_col: str) -> pd.Series:
    app = df.get(app_col, pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.strip().str.lower()
    env = df.get(env_col, pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.strip().str.lower()
    app = app.where(app != "", "unlabeled")
    env = env.where(env != "", "unlabeled")
    return app + "|" + env


def _articulation_points(nodes: list[str], graph: dict[str, set[str]]) -> set[str]:
    # Tarjan articulation point algorithm on undirected graph.
    if not nodes:
        return set()
    ids: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    out_edges: dict[str, int] = defaultdict(int)
    points: set[str] = set()
    current_id = 0

    def dfs(at: str):
        nonlocal current_id
        current_id += 1
        ids[at] = current_id
        low[at] = current_id

        for to in graph.get(at, set()):
            if to == parent.get(at):
                continue
            if to not in ids:
                parent[to] = at
                out_edges[at] += 1
                dfs(to)
                low[at] = min(low[at], low[to])
                if parent.get(at) is not None and ids[at] <= low[to]:
                    points.add(at)
            else:
                low[at] = min(low[at], ids[to])

    for node in nodes:
        if node not in ids:
            parent[node] = None
            dfs(node)
            if out_edges[node] > 1:
                points.add(node)
    return points


def _bfs_reachability(source: str, adjacency: dict[str, set[str]], max_depth: int) -> dict[str, list[str]]:
    paths: dict[str, list[str]] = {}
    q: deque[tuple[str, list[str]]] = deque([(source, [source])])
    while q:
        node, path = q.popleft()
        if len(path) - 1 >= max_depth:
            continue
        for nxt in sorted(adjacency.get(node, set())):
            if nxt in path:
                continue
            new_path = path + [nxt]
            if nxt not in paths:
                paths[nxt] = new_path
            q.append((nxt, new_path))
    return paths


def _path_weight(path: list[str], edge_weights: dict[tuple[str, str], int]) -> int:
    total = 0
    for i in range(len(path) - 1):
        total += int(edge_weights.get((path[i], path[i + 1]), 0))
    return total


def lateral_movement_risk(df: pd.DataFrame, top_n: int = 20, max_depth: int = 4) -> dict:
    if df.empty:
        return {"error": "No data"}

    work = df.copy()
    work["port"] = pd.to_numeric(work.get("port", -1), errors="coerce").fillna(-1).astype(int)
    work["policy_decision"] = work.get("policy_decision", "").fillna("").astype(str).str.lower()
    work["num_connections"] = pd.to_numeric(work.get("num_connections", 1), errors="coerce").fillna(1).astype(int)
    work["src_key"] = _normalize_key_series(work, "src_app", "src_env")
    work["dst_key"] = _normalize_key_series(work, "dst_app", "dst_env")

    lateral = work[work["port"].isin(_LATERAL_PORTS)].copy()
    lateral["service"] = lateral["port"].map(_LATERAL_PORTS)
    if lateral.empty:
        return {
            "total_lateral_flows": 0,
            "unique_lateral_src": 0,
            "unique_lateral_dst": 0,
            "lateral_pct": 0.0,
            "service_summary": pd.DataFrame(),
            "ip_top_talkers": pd.DataFrame(),
            "ip_top_pairs": pd.DataFrame(),
            "fan_out_sources": pd.DataFrame(),
            "app_chains": pd.DataFrame(),
            "bridge_nodes": pd.DataFrame(),
            "top_reachable_nodes": pd.DataFrame(),
            "attack_paths": pd.DataFrame(),
            "allowed_lateral_flows": pd.DataFrame(),
            "source_risk_scores": pd.DataFrame(),
            "attack_posture_items": [],
        }

    lateral_pct = round(len(lateral) / max(1, len(work)) * 100, 1)
    service_summary = (
        lateral.groupby(["port", "service", "policy_decision"])
        .agg(
            connections=("num_connections", "sum"),
            unique_src=("src_key", "nunique"),
            unique_dst=("dst_key", "nunique"),
        )
        .reset_index()
        .rename(
            columns={
                "port": "Port",
                "service": "Service",
                "policy_decision": "Decision",
                "connections": "Connections",
                "unique_src": "Unique Sources",
                "unique_dst": "Unique Destinations",
            }
        )
        .sort_values(by=["Connections", "Port"], ascending=[False, True])
        .head(top_n)
        .reset_index(drop=True)
    )

    # IP-level analysis (consolidated from former mod05)
    _has_hostname = "src_hostname" in lateral.columns
    if _has_hostname:
        ip_top_talkers = (
            lateral.groupby(["src_ip", "src_hostname"])["dst_ip"]
            .nunique()
            .reset_index()
            .nlargest(top_n, "dst_ip")
            .rename(columns={"src_ip": "Source IP", "src_hostname": "Hostname", "dst_ip": "Unique Destinations"})
            .reset_index(drop=True)
        )
    else:
        ip_top_talkers = (
            lateral.groupby("src_ip")["dst_ip"]
            .nunique()
            .reset_index()
            .nlargest(top_n, "dst_ip")
            .rename(columns={"src_ip": "Source IP", "dst_ip": "Unique Destinations"})
            .reset_index(drop=True)
        )

    lateral_with_pair = lateral.copy()
    lateral_with_pair["pair"] = lateral_with_pair["src_ip"].astype(str) + " \u2192 " + lateral_with_pair["dst_ip"].astype(str)
    ip_top_pairs = (
        lateral_with_pair.groupby(["pair", "service"])["num_connections"]
        .sum()
        .reset_index()
        .nlargest(top_n, "num_connections")
        .rename(columns={"pair": "Host Pair", "service": "Service", "num_connections": "Connections"})
        .reset_index(drop=True)
    )

    traversable = lateral[lateral["policy_decision"].isin(["allowed", "potentially_blocked"])].copy()
    traversable = traversable[traversable["src_key"] != traversable["dst_key"]]

    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    adjacency: dict[str, set[str]] = defaultdict(set)
    undirected: dict[str, set[str]] = defaultdict(set)
    for _, row in traversable.iterrows():
        src = str(row["src_key"])
        dst = str(row["dst_key"])
        edge_weights[(src, dst)] += int(row["num_connections"])
    for (src, dst), _w in edge_weights.items():
        adjacency[src].add(dst)
        undirected[src].add(dst)
        undirected[dst].add(src)

    nodes = sorted(set(undirected.keys()) | {n for neigh in undirected.values() for n in neigh})
    articulation = _articulation_points(nodes, undirected)

    reach_rows: list[dict] = []
    path_rows: list[dict] = []
    bridge_rows: list[dict] = []
    attack_items: list[dict] = []

    max_reach = 1
    reach_cache: dict[str, dict[str, list[str]]] = {}
    for node in nodes:
        reached = _bfs_reachability(node, adjacency, max_depth=max_depth)
        reach_cache[node] = reached
        max_reach = max(max_reach, len(reached))

    for node in nodes:
        app, env = node.split("|", 1)
        reached = reach_cache.get(node, {})
        reach_count = len(reached)
        reach_score = round((reach_count / max_reach) * 100.0, 1) if max_reach else 0.0
        bridge_score = round((60.0 if node in articulation else 0.0) + (reach_score * 0.4), 1)

        reach_rows.append(
            {
                "Source App (Env)": build_app_display(app, env),
                "app_env_key": node,
                "Reachable App Count": reach_count,
                "Max Depth Used": max_depth,
                "Reachability Score": reach_score,
            }
        )
        bridge_rows.append(
            {
                "App (Env)": build_app_display(app, env),
                "app_env_key": node,
                "Articulation Point": "Yes" if node in articulation else "No",
                "Reachable App Count": reach_count,
                "Bridge Score": bridge_score,
            }
        )

        if node in articulation and reach_count >= 2:
            attack_items.append(
                make_posture_item(
                    scope="traffic_report",
                    framework="microseg_attack",
                    app=app,
                    env=env,
                    finding_kind="suspicious_pivot",
                    attack_stage="pivot",
                    confidence="high",
                    recommended_action_code="RESTRICT_TRANSIT_NODE_ACCESS",
                    severity="CRITICAL" if reach_count >= 6 else "HIGH",
                    evidence={"reachability_count": reach_count, "bridge_score": bridge_score},
                )
            )
        if reach_count >= 4:
            attack_items.append(
                make_posture_item(
                    scope="traffic_report",
                    framework="microseg_attack",
                    app=app,
                    env=env,
                    finding_kind="blast_radius",
                    attack_stage="blast_radius",
                    confidence="medium",
                    recommended_action_code="TIGHTEN_LATERAL_POLICY",
                    severity="HIGH",
                    evidence={"reachability_count": reach_count, "max_depth": max_depth},
                )
            )

        for target, path in reached.items():
            if len(path) <= 2:
                continue
            tgt_app, tgt_env = target.split("|", 1)
            path_rows.append(
                {
                    "Source App (Env)": build_app_display(app, env),
                    "Source App Env Key": node,
                    "Target App (Env)": build_app_display(tgt_app, tgt_env),
                    "Target App Env Key": target,
                    "Path Depth": len(path) - 1,
                    "Path": " -> ".join(build_app_display(*hop.split("|", 1)) for hop in path),
                    "Path Connection Weight": _path_weight(path, edge_weights),
                }
            )

    top_reachable_nodes = (
        pd.DataFrame(reach_rows)
        .sort_values(by=["Reachable App Count", "app_env_key"], ascending=[False, True])
        .head(top_n)
        .reset_index(drop=True)
        if reach_rows
        else pd.DataFrame()
    )
    bridge_nodes = (
        pd.DataFrame(bridge_rows)
        .sort_values(by=["Bridge Score", "app_env_key"], ascending=[False, True])
        .head(top_n)
        .reset_index(drop=True)
        if bridge_rows
        else pd.DataFrame()
    )
    attack_paths = (
        pd.DataFrame(path_rows)
        .sort_values(by=["Path Depth", "Path Connection Weight", "Source App Env Key"], ascending=[False, False, True])
        .head(top_n)
        .reset_index(drop=True)
        if path_rows
        else pd.DataFrame()
    )
    app_chains = top_reachable_nodes.copy() if not top_reachable_nodes.empty else pd.DataFrame()

    allowed_lateral_flows = (
        lateral[lateral["policy_decision"] == "allowed"]
        .groupby(["src_key", "dst_key", "port", "service"])
        .agg(connections=("num_connections", "sum"))
        .reset_index()
        .rename(
            columns={
                "src_key": "Source App Env Key",
                "dst_key": "Destination App Env Key",
                "port": "Port",
                "service": "Service",
                "connections": "Connections",
            }
        )
        .sort_values(by=["Connections", "Source App Env Key"], ascending=[False, True])
        .head(top_n)
        .reset_index(drop=True)
    )
    if not allowed_lateral_flows.empty:
        allowed_lateral_flows["Source App (Env)"] = allowed_lateral_flows["Source App Env Key"].apply(
            lambda v: build_app_display(*str(v).split("|", 1))
        )
        allowed_lateral_flows["Destination App (Env)"] = allowed_lateral_flows["Destination App Env Key"].apply(
            lambda v: build_app_display(*str(v).split("|", 1))
        )

    fan_out_sources = (
        traversable.groupby("src_key")
        .agg(
            unique_dst=("dst_key", "nunique"),
            unique_ports=("port", "nunique"),
            connections=("num_connections", "sum"),
        )
        .reset_index()
        .rename(
            columns={
                "src_key": "Source App Env Key",
                "unique_dst": "Unique Destinations",
                "unique_ports": "Lateral Ports",
                "connections": "Connections",
            }
        )
        .sort_values(by=["Unique Destinations", "Source App Env Key"], ascending=[False, True])
        .head(top_n)
        .reset_index(drop=True)
        if not traversable.empty
        else pd.DataFrame()
    )
    if not fan_out_sources.empty:
        fan_out_sources["Source App (Env)"] = fan_out_sources["Source App Env Key"].apply(
            lambda v: build_app_display(*str(v).split("|", 1))
        )

    source_risk_scores = (
        bridge_nodes[["App (Env)", "app_env_key", "Bridge Score", "Reachable App Count"]]
        .rename(columns={"Bridge Score": "Risk Score"})
        .copy()
    )
    if not source_risk_scores.empty:
        source_risk_scores["Risk Level"] = source_risk_scores["Risk Score"].apply(
            lambda s: "Critical" if s >= 85 else ("High" if s >= 60 else ("Medium" if s >= 35 else "Low"))
        )

    if "src_managed" in traversable.columns and "dst_managed" in traversable.columns:
        unmanaged_reach = traversable[
            (~traversable["src_managed"].fillna(False).astype(bool))
            | (~traversable["dst_managed"].fillna(False).astype(bool))
        ]
        for key, group in unmanaged_reach.groupby("src_key"):
            app, env = str(key).split("|", 1)
            attack_items.append(
                make_posture_item(
                    scope="traffic_report",
                    framework="microseg_attack",
                    app=app,
                    env=env,
                    finding_kind="blind_spot",
                    attack_stage="exposure",
                    confidence="medium",
                    recommended_action_code="ONBOARD_UNMANAGED",
                    severity="HIGH" if len(group) >= 3 else "MEDIUM",
                    evidence={"unmanaged_traversable_flows": int(len(group))},
                )
            )

    # Phase 5: network chart_spec from top reachable nodes + edges
    _chart_nodes = []
    _chart_edges = []
    if nodes:
        # Use top 10 reachable nodes as network graph vertices
        top_node_keys = (
            pd.DataFrame(reach_rows)
            .sort_values("Reachable App Count", ascending=False)
            .head(10)["app_env_key"]
            .tolist()
            if reach_rows else nodes[:10]
        )
        for nk in top_node_keys:
            app, env = str(nk).split("|", 1)
            _chart_nodes.append({"id": nk, "label": build_app_display(app, env)})
        top_node_set = set(top_node_keys)
        for (src, dst) in list(edge_weights.keys())[:30]:
            if src in top_node_set and dst in top_node_set:
                _chart_edges.append((src, dst))

    _network_chart_spec = {
        "type": "network",
        "title": t("rpt_lm_chart_title", default="Lateral Movement Graph"),
        "data": {
            "nodes": _chart_nodes,
            "edges": _chart_edges,
        },
        "i18n": {"lang": get_language()},
    }

    return {
        "total_lateral_flows": int(len(lateral)),
        "unique_lateral_src": int(lateral["src_ip"].nunique()) if "src_ip" in lateral.columns else 0,
        "unique_lateral_dst": int(lateral["dst_ip"].nunique()) if "dst_ip" in lateral.columns else 0,
        "lateral_pct": lateral_pct,
        "service_summary": service_summary,
        "ip_top_talkers": ip_top_talkers,
        "ip_top_pairs": ip_top_pairs,
        "fan_out_sources": fan_out_sources,
        "app_chains": app_chains,
        "bridge_nodes": bridge_nodes,
        "top_reachable_nodes": top_reachable_nodes,
        "attack_paths": attack_paths,
        "articulation_proxies": bridge_nodes,
        "source_risk_scores": source_risk_scores,
        "allowed_lateral_flows": allowed_lateral_flows,
        "attack_posture_items": rank_posture_items(attack_items)[: max(top_n, 10)],
        "chart_spec": _network_chart_spec,
    }

