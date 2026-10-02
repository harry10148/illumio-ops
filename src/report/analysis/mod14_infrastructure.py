"""Module 14: Deterministic infrastructure scoring by app(env)."""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from ._key_rows import rows_by_key
from .attack_posture import build_app_display, make_posture_item, rank_posture_items
from src.i18n import t, get_language

def _normalize_key_series(df: pd.DataFrame, app_col: str, env_col: str) -> pd.Series:
    app = df.get(app_col, pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.strip().str.lower()
    env = df.get(env_col, pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.strip().str.lower()
    app = app.where(app != "", "unlabeled")
    env = env.where(env != "", "unlabeled")
    return app + "|" + env

# Above this many path sources, betweenness is estimated from an evenly spaced
# sample of them (Brandes & Pich pivot sampling) instead of computed from all:
# exact cost is O(V·E) in Python — about 18 s for 4,000 app|env keys and 30k
# edges — and the score is only used relative to its maximum.
BETWEENNESS_EXACT_MAX_SOURCES = 1500
BETWEENNESS_SAMPLE_SOURCES = 500


def _betweenness_centrality(nodes: list[str], adjacency: dict[str, set[str]],
                            info: dict | None = None) -> dict[str, float]:
    # Brandes algorithm for unweighted directed graph, normalised to the max.
    #
    # Same algorithm as before on integer node ids: the old version allocated
    # four dicts of every node per source (V² dict entries, ~48 s at 4,000
    # app|env keys) and kept a predecessor list per node. Predecessors of w are
    # exactly its in-neighbours one BFS level closer, so they are read from
    # the reverse adjacency instead of being stored.
    n = len(nodes)
    index = {name: i for i, name in enumerate(nodes)}
    succ: list[list[int]] = [[] for _ in range(n)]
    pred_all: list[list[int]] = [[] for _ in range(n)]
    for name, targets in adjacency.items():
        u = index.get(name)
        if u is None:
            continue
        for target in targets:
            v = index.get(target)
            if v is not None:
                succ[u].append(v)
                pred_all[v].append(u)

    # A node with no out-edges is no path's source.
    sources = [i for i in range(n) if succ[i]]
    if len(sources) > BETWEENNESS_EXACT_MAX_SOURCES:
        step = len(sources) / BETWEENNESS_SAMPLE_SOURCES
        sources = [sources[int(k * step)] for k in range(BETWEENNESS_SAMPLE_SOURCES)]
        if info is not None:
            info["betweenness_sampled_sources"] = len(sources)
    bc = [0.0] * n
    for s in sources:
        sigma = [0.0] * n
        dist = [-1] * n
        sigma[s] = 1.0
        dist[s] = 0
        order = [s]
        head = 0
        while head < len(order):
            v = order[head]
            head += 1
            dv1 = dist[v] + 1
            sv = sigma[v]
            for w in succ[v]:
                if dist[w] < 0:
                    dist[w] = dv1
                    order.append(w)
                if dist[w] == dv1:
                    sigma[w] += sv
        delta = [0.0] * n
        for w in reversed(order[1:]):
            dw1 = dist[w] - 1
            coeff = (1.0 + delta[w]) / sigma[w]
            for v in pred_all[w]:
                if dist[v] == dw1:
                    delta[v] += sigma[v] * coeff
            bc[w] += delta[w]

    max_v = max(bc, default=0.0)
    if max_v <= 0:
        return {k: 0.0 for k in nodes}
    return {k: bc[i] / max_v for i, k in enumerate(nodes)}

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

def infrastructure_scoring(df: pd.DataFrame, top_n: int = 20, *, lang: str = "en") -> dict:
    if df.empty:
        return {"error": t("rpt_mod_err_no_data", lang=lang)}

    work = df.copy()
    work["src_key"] = _normalize_key_series(work, "src_app", "src_env")
    work["dst_key"] = _normalize_key_series(work, "dst_app", "dst_env")
    work["num_connections"] = pd.to_numeric(work.get("num_connections", 1), errors="coerce").fillna(1).astype(int)

    app_flows = work[work["src_key"] != work["dst_key"]].copy()
    if app_flows.empty:
        return {"error": t("rpt_mod14_err_no_edges", lang=lang)}

    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    adjacency: dict[str, set[str]] = defaultdict(set)
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    in_weight: dict[str, int] = defaultdict(int)
    out_weight: dict[str, int] = defaultdict(int)

    # One groupby instead of iterrows over every cross-app flow.
    grouped = app_flows.groupby(["src_key", "dst_key"], sort=False)["num_connections"].sum()
    for (src, dst), w in grouped.items():
        edge_weights[(str(src), str(dst))] += int(w)

    for (src, dst), w in edge_weights.items():
        adjacency[src].add(dst)
        out_degree[src] += 1
        in_degree[dst] += 1
        out_weight[src] += w
        in_weight[dst] += w

    all_nodes = sorted(set(in_degree) | set(out_degree))
    if not all_nodes:
        return {"error": t("rpt_mod14_err_no_nodes", lang=lang)}

    bc_info: dict = {}
    bc = _betweenness_centrality(all_nodes, adjacency, bc_info)
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

    key_rows = rows_by_key(app_flows)
    for key in all_nodes:
        app, env = key.split("|", 1)
        node_flows = app_flows.iloc[key_rows[key]]
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
        # Set when betweenness was estimated from a sample of path sources
        # (very large graphs); absent when it is exact.
        **bc_info,
        "top_apps": top_apps,
        "top_edges": edge_df.reset_index(drop=True),
        "role_summary": role_summary.reset_index(drop=True),
        "hub_apps": hub_apps.reset_index(drop=True),
        "attack_posture_items": rank_posture_items(attack_items)[: max(top_n, 10)],
        "chart_spec": {
            "type": "bar",
            "title": "Infrastructure Apps by Tier",
            "title_key": "rpt_chart_infrastructure_apps_by_tier",
            "x_label": t("rpt_tier", default="Tier", lang=lang),
            "x_label_key": "rpt_chart_axis_tier",
            "y_label": t("rpt_app_count", default="App Count", lang=lang),
            "y_label_key": "rpt_chart_axis_app_count",
            "data": {"labels": tier_labels, "values": tier_values},
            "i18n": {"lang": get_language()},
        },
    }

