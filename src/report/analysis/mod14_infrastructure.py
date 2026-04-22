"""Module 14: Deterministic infrastructure scoring by app(env)."""
from __future__ import annotations

from collections import defaultdict, deque

import pandas as pd

from .attack_posture import build_app_display, make_posture_item, rank_posture_items
from src.i18n import t, get_language

def _normalize_key_series(df: pd.DataFrame, app_col: str, env_col: str) -> pd.Series:
    app = df.get(app_col, pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.strip().str.lower()
    env = df.get(env_col, pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.strip().str.lower()
    app = app.where(app != "", "unlabeled")
    env = env.where(env != "", "unlabeled")
    return app + "|" + env

def _betweenness_centrality(nodes: list[str], adjacency: dict[str, set[str]]) -> dict[str, float]:
    # Brandes algorithm for unweighted directed graph.
    bc = {n: 0.0 for n in nodes}
    for source in nodes:
        stack: list[str] = []
        preds = {v: [] for v in nodes}
        sigma = {v: 0.0 for v in nodes}
        sigma[source] = 1.0
        dist = {v: -1 for v in nodes}
        dist[source] = 0
        q: deque[str] = deque([source])

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
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != source:
                bc[w] += delta[w]

    max_v = max(bc.values(), default=0.0)
    if max_v <= 0:
        return {k: 0.0 for k in bc}
    return {k: v / max_v for k, v in bc.items()}

# Critical asset port groups for automatic tier boosting
_DB_PORTS = {1433, 3306, 5432, 1521, 27017, 6379, 9200, 5984, 50000}
_IDENTITY_PORTS = {88, 389, 636, 3268, 3269, 464}

def _tier(score: float) -> str:
    if score >= 80:
        return "Tier-1 Critical"
    if score >= 60:
        return "Tier-2 Important"
    if score >= 40:
        return "Tier-3 Shared"
    return "Tier-4 Peripheral"

def _detect_critical_asset_keys(df: pd.DataFrame) -> dict[str, set[str]]:
    """Identify app(env) keys that serve as database or identity infrastructure.

    Nodes that are *destinations* for DB or Identity ports are inherently
    crown-jewel assets regardless of their topological position.
    """
    result: dict[str, set[str]] = {}
    if df.empty or "port" not in df.columns:
        return result

    port_col = pd.to_numeric(df.get("port", -1), errors="coerce").fillna(-1).astype(int)

    # Database providers: destinations receiving traffic on DB ports
    db_mask = port_col.isin(_DB_PORTS)
    if db_mask.any():
        dst_key_col = df.loc[db_mask].get("dst_key")
        if dst_key_col is not None:
            result["database"] = set(dst_key_col.dropna().unique())

    # Identity infrastructure: destinations receiving Kerberos/LDAP/GC traffic
    id_mask = port_col.isin(_IDENTITY_PORTS)
    if id_mask.any():
        dst_key_col = df.loc[id_mask].get("dst_key")
        if dst_key_col is not None:
            result["identity"] = set(dst_key_col.dropna().unique())

    return result

def infrastructure_scoring(df: pd.DataFrame, top_n: int = 20) -> dict:
    if df.empty:
        return {"error": "No data"}

    work = df.copy()
    work["src_key"] = _normalize_key_series(work, "src_app", "src_env")
    work["dst_key"] = _normalize_key_series(work, "dst_app", "dst_env")
    work["num_connections"] = pd.to_numeric(work.get("num_connections", 1), errors="coerce").fillna(1).astype(int)

    app_flows = work[work["src_key"] != work["dst_key"]].copy()
    if app_flows.empty:
        return {"error": "No app-env communication edges found"}

    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    adjacency: dict[str, set[str]] = defaultdict(set)
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    in_weight: dict[str, int] = defaultdict(int)
    out_weight: dict[str, int] = defaultdict(int)

    for _, row in app_flows.iterrows():
        src = str(row["src_key"])
        dst = str(row["dst_key"])
        w = int(row.get("num_connections", 1))
        edge_weights[(src, dst)] += w

    for (src, dst), w in edge_weights.items():
        adjacency[src].add(dst)
        out_degree[src] += 1
        in_degree[dst] += 1
        out_weight[src] += w
        in_weight[dst] += w

    all_nodes = sorted(set(in_degree) | set(out_degree))
    if not all_nodes:
        return {"error": "No graph nodes generated"}

    bc = _betweenness_centrality(all_nodes, adjacency)
    max_in_degree = max(in_degree.values(), default=1)
    max_out_degree = max(out_degree.values(), default=1)
    max_in_weight = max(in_weight.values(), default=1)
    max_out_weight = max(out_weight.values(), default=1)

    # C2: Detect critical asset keys (database / identity infrastructure)
    critical_assets = _detect_critical_asset_keys(app_flows)
    db_keys = critical_assets.get("database", set())
    id_keys = critical_assets.get("identity", set())

    rows: list[dict] = []
    attack_items: list[dict] = []

    for key in all_nodes:
        app, env = key.split("|", 1)
        node_flows = app_flows[(app_flows["src_key"] == key) | (app_flows["dst_key"] == key)]
        mixed_ratio = 0.0
        if not node_flows.empty and "src_managed" in node_flows.columns and "dst_managed" in node_flows.columns:
            managed_pair = node_flows["src_managed"].fillna(False).astype(bool) & node_flows["dst_managed"].fillna(False).astype(bool)
            mixed_ratio = 1.0 - float(managed_pair.mean())

        dampening_factor = max(0.7, 1.0 - 0.3 * mixed_ratio)
        non_prod_penalty = 1.0 if env in {"prod", "production", "prd"} else 0.85

        provider_score = (
            ((in_degree.get(key, 0) / max_in_degree) * 0.6 + (in_weight.get(key, 0) / max_in_weight) * 0.4) * 100.0
        )
        consumer_score = (
            ((out_degree.get(key, 0) / max_out_degree) * 0.6 + (out_weight.get(key, 0) / max_out_weight) * 0.4) * 100.0
        )
        betweenness_score = bc.get(key, 0.0) * 100.0

        base_score = provider_score * 0.45 + consumer_score * 0.35 + betweenness_score * 0.2

        # C2: Critical asset boost — crown jewels get a floor score
        is_db = key in db_keys
        is_identity = key in id_keys
        asset_type = ""
        if is_identity:
            asset_type = "Identity Infrastructure"
            base_score = max(base_score, 80.0)  # identity infra → at least Tier-1
        elif is_db:
            asset_type = "Database"
            base_score = max(base_score, 65.0)  # database → at least Tier-2

        infra_score = round(base_score * dampening_factor * non_prod_penalty, 1)

        if is_identity:
            role = "Identity"
        elif is_db:
            role = "Database"
        elif provider_score >= consumer_score * 1.3:
            role = "Provider"
        elif consumer_score >= provider_score * 1.3:
            role = "Consumer"
        elif betweenness_score >= 50:
            role = "Bridge"
        else:
            role = "Peer"

        rows.append(
            {
                "app_env_key": key,
                "app_display": build_app_display(app, env),
                "provider_score": round(provider_score, 1),
                "consumer_score": round(consumer_score, 1),
                "betweenness_score": round(betweenness_score, 1),
                "mixed_traffic_ratio": round(mixed_ratio, 4),
                "dampening_factor": round(dampening_factor, 4),
                "non_prod_penalty": round(non_prod_penalty, 4),
                "in_degree": in_degree.get(key, 0),
                "out_degree": out_degree.get(key, 0),
                "connections_in": in_weight.get(key, 0),
                "connections_out": out_weight.get(key, 0),
                "infrastructure_score": infra_score,
                "tier": _tier(infra_score),
                "role": role,
                "asset_type": asset_type,
            }
        )

        if betweenness_score >= 45 and infra_score >= 55:
            attack_items.append(
                make_posture_item(
                    scope="traffic_report",
                    framework="microseg_attack",
                    app=app,
                    env=env,
                    finding_kind="blast_radius",
                    attack_stage="blast_radius",
                    confidence="high",
                    recommended_action_code="RESTRICT_TRANSIT_NODE_ACCESS",
                    severity="HIGH" if betweenness_score < 70 else "CRITICAL",
                    evidence={
                        "betweenness_score": round(betweenness_score, 2),
                        "infrastructure_score": infra_score,
                        "mixed_traffic_ratio": round(mixed_ratio, 4),
                    },
                )
            )
        if mixed_ratio >= 0.35:
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
                    severity="HIGH" if mixed_ratio >= 0.55 else "MEDIUM",
                    evidence={"mixed_traffic_ratio": round(mixed_ratio, 4), "flow_count": int(len(node_flows))},
                )
            )

    scored = pd.DataFrame(rows).sort_values(
        by=["infrastructure_score", "app_env_key"], ascending=[False, True]
    ).reset_index(drop=True)

    top_apps = scored.head(top_n).copy()
    hub_apps = scored[scored["role"].isin(["Bridge", "Provider"])].head(min(top_n, 10)).copy()
    role_summary = scored.groupby("tier").size().reset_index(name="Count").rename(columns={"tier": "Tier"})

    edge_df = pd.DataFrame(
        [
            {
                "Source App (Env)": build_app_display(src.split("|", 1)[0], src.split("|", 1)[1]),
                "Source App Env Key": src,
                "Destination App (Env)": build_app_display(dst.split("|", 1)[0], dst.split("|", 1)[1]),
                "Destination App Env Key": dst,
                "Connections": weight,
            }
            for (src, dst), weight in edge_weights.items()
        ]
    ).sort_values(by=["Connections", "Source App Env Key", "Destination App Env Key"], ascending=[False, True, True]).head(top_n)

    if not role_summary.empty:
        tier_labels = role_summary['Tier'].tolist()
        tier_values = [int(v) for v in role_summary['Count'].tolist()]
    else:
        tier_labels, tier_values = [], []

    return {
        "total_apps": int(len(all_nodes)),
        "total_edges": int(len(edge_weights)),
        "top_apps": top_apps,
        "top_edges": edge_df.reset_index(drop=True),
        "role_summary": role_summary.reset_index(drop=True),
        "hub_apps": hub_apps.reset_index(drop=True),
        "attack_posture_items": rank_posture_items(attack_items)[: max(top_n, 10)],
        "chart_spec": {
            "type": "bar",
            "title": "Infrastructure Apps by Tier",
            "x_label": t("rpt_tier", default="Tier"),
            "y_label": t("rpt_app_count", default="App Count"),
            "data": {"labels": tier_labels, "values": tier_values},
            "i18n": {"lang": get_language()},
        },
    }

