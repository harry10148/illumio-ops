"""Module 13: Deterministic enforcement readiness by app(env)."""
from __future__ import annotations

import pandas as pd
from src.i18n import t

from .attack_posture import (
    build_app_display,
    make_posture_item,
    rank_posture_items,
    resolve_recommendation,
)

_WEIGHTS = {
    "policy_coverage": 35,
    "ringfence_maturity": 20,
    "enforcement_mode": 20,
    "staged_readiness": 15,
    "remote_app_coverage": 10,
}

_REMOTE_PORTS = {22, 3389, 5900, 5901, 5938, 3283}

def _normalize_key_series(df: pd.DataFrame, app_col: str, env_col: str) -> pd.Series:
    app = df.get(app_col, pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.strip().str.lower()
    env = df.get(env_col, pd.Series(index=df.index, dtype=object)).fillna("").astype(str).str.strip().str.lower()
    app = app.where(app != "", "unlabeled")
    env = env.where(env != "", "unlabeled")
    return app + "|" + env

def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"

def _severity_from_ratio(ratio: float) -> str:
    if ratio >= 0.75:
        return "CRITICAL"
    if ratio >= 0.45:
        return "HIGH"
    return "MEDIUM"

def _build_recommendations(attack_items: list[dict], top_n: int, lang: str = "en") -> pd.DataFrame:
    if not attack_items:
        return pd.DataFrame(
            columns=["Priority", "App (Env)", "App Env Key", "Issue", "Action", "Action Code", "Severity"]
        )
    priority = {"CRITICAL": "P1", "HIGH": "P2", "MEDIUM": "P3", "LOW": "P4", "INFO": "P5"}
    rows = []
    for item in rank_posture_items(attack_items)[:top_n]:
        rows.append(
            {
                "Priority": priority.get(item.get("severity", "INFO"), "P5"),
                "App (Env)": item.get("app_display"),
                "App Env Key": item.get("app_env_key"),
                "Issue": t(f"rpt_finding_{item.get('finding_kind', '')}",
                           default=item.get("finding_kind", "").replace("_", " ").title(),
                           lang=lang),
                "Action": resolve_recommendation(item.get("recommended_action_code", ""), lang),
                "Action Code": item.get("recommended_action_code", ""),
                "Severity": item.get("severity", "INFO"),
            }
        )
    return pd.DataFrame(rows)

_ENFORCED = {"full": 1.0, "selective": 0.5}


def _app_enforce_ratio(flows: pd.DataFrame, key: str):
    """(full + 0.5×selective) / workloads with a known mode, for this app(env).

    Uses the workloads' own enforcement mode carried on the flows. The old
    factor was the share of flow endpoints that were MANAGED — every app with
    a VEN read 100% "Enforcement Mode" even when nothing was enforced.
    Returns None when the data carries no mode (CSV import).
    """
    parts = []
    for side in ("src", "dst"):
        mode_col, ip_col = f"{side}_enforcement", f"{side}_ip"
        if mode_col not in flows.columns:
            continue
        sel = flows[f"{side}_key"] == key
        sub = pd.DataFrame({
            "ip": flows.loc[sel, ip_col] if ip_col in flows.columns else flows.loc[sel].index,
            "mode": flows.loc[sel, mode_col],
        })
        parts.append(sub)
    if not parts:
        return None
    wl = pd.concat(parts, ignore_index=True)
    wl["mode"] = wl["mode"].fillna("").astype(str).str.strip().str.lower()
    wl = wl[wl["mode"] != ""].drop_duplicates(subset=["ip"])
    if wl.empty:
        return None
    return float(wl["mode"].map(lambda m: _ENFORCED.get(m, 0.0)).mean())


def _weighted(parts: dict) -> float:
    """Weighted 0-100 score over the factors that are available (ratio not None)."""
    avail = {k: r for k, r in parts.items() if r is not None}
    weight = sum(_WEIGHTS[k] for k in avail)
    if not weight:
        return 0.0
    return round(sum(_WEIGHTS[k] * r for k, r in avail.items()) / weight * 100, 1)


def enforcement_readiness(df: pd.DataFrame, workloads: list | None = None, top_n: int = 20, *, lang: str = "en") -> dict:
    if df.empty:
        return {"error": t("rpt_mod_err_no_data", lang=lang)}

    work = df.copy()
    work["src_key"] = _normalize_key_series(work, "src_app", "src_env")
    work["dst_key"] = _normalize_key_series(work, "dst_app", "dst_env")
    work["num_connections"] = pd.to_numeric(work.get("num_connections", 1), errors="coerce").fillna(1).astype(int)
    work["policy_decision"] = work.get("policy_decision", "").fillna("").astype(str).str.lower()
    work["port"] = pd.to_numeric(work.get("port", -1), errors="coerce").fillna(-1).astype(int)

    all_keys = sorted(set(work["src_key"].tolist()) | set(work["dst_key"].tolist()))
    app_rows: list[dict] = []
    attack_items: list[dict] = []

    # Per-app modes from the workload inventory (the standalone Readiness
    # report passes it); the flows' own enforcement columns win when present.
    workload_ratio_by_key: dict[str, float] = {}
    global_workload_ratio = None
    if workloads:
        buckets: dict[str, list[float]] = {}
        for w in workloads:
            app = env = ""
            for lbl in (w.get("labels") or []):
                if lbl.get("key") == "app":
                    app = str(lbl.get("value") or "")
                elif lbl.get("key") == "env":
                    env = str(lbl.get("value") or "")
            wkey = f"{app.strip().lower() or 'unlabeled'}|{env.strip().lower() or 'unlabeled'}"
            buckets.setdefault(wkey, []).append(
                _ENFORCED.get(str(w.get("enforcement_mode", "")).lower(), 0.0))
        workload_ratio_by_key = {k: sum(v) / len(v) for k, v in buckets.items()}
        all_vals = [x for v in buckets.values() for x in v]
        global_workload_ratio = sum(all_vals) / len(all_vals) if all_vals else None

    for key in all_keys:
        app, env = key.split("|", 1)
        flows = work[(work["src_key"] == key) | (work["dst_key"] == key)]
        if flows.empty:
            continue

        total = len(flows)
        allowed_ratio = float((flows["policy_decision"] == "allowed").mean())
        ringfence_ratio = float((flows["src_key"] == flows["dst_key"]).mean()) if total else 0.0

        enforce_ratio = _app_enforce_ratio(flows, key)
        if enforce_ratio is None:
            enforce_ratio = workload_ratio_by_key.get(key, global_workload_ratio)

        # PB flows are uncovered exposure (no enforcement yet). Only allowed flows count as ready.
        pb_ratio = float((flows["policy_decision"] == "potentially_blocked").mean())
        blocked_ratio = float((flows["policy_decision"] == "blocked").mean())
        pb_uncovered_count = int((flows["policy_decision"] == "potentially_blocked").sum())
        # "Staged readiness" was the allowed share again — the same number as
        # policy coverage, so 50% of the weight sat on one metric. It is now
        # the share of flows that keep working once enforced: everything but
        # Potentially Blocked (blocked flows are already being dropped).
        staged_ratio = 1.0 - pb_ratio

        remote = flows[flows["port"].isin(_REMOTE_PORTS)]
        # No remote-access flows: the factor does not apply (it used to score
        # as 100% covered).
        remote_coverage = None if remote.empty else float((remote["policy_decision"] == "allowed").mean())

        def _pts(k, r):
            return None if r is None else round(_WEIGHTS[k] * r, 1)
        policy_score = _pts("policy_coverage", allowed_ratio)
        ringfence_score = _pts("ringfence_maturity", ringfence_ratio)
        enforce_score = _pts("enforcement_mode", enforce_ratio)
        staged_score = _pts("staged_readiness", staged_ratio)
        remote_score = _pts("remote_app_coverage", remote_coverage)
        readiness_score = _weighted({
            "policy_coverage": allowed_ratio, "ringfence_maturity": ringfence_ratio,
            "enforcement_mode": enforce_ratio, "staged_readiness": staged_ratio,
            "remote_app_coverage": remote_coverage,
        })

        app_rows.append(
            {
                "app_env_key": key,
                "app_display": build_app_display(app, env),
                "readiness_score": readiness_score,
                "policy_coverage_ratio": round(allowed_ratio, 4),
                "ringfence_maturity_ratio": round(ringfence_ratio, 4),
                "enforcement_mode_ratio": None if enforce_ratio is None else round(enforce_ratio, 4),
                "staged_readiness_ratio": round(staged_ratio, 4),
                "potentially_blocked_ratio": round(pb_ratio, 4),
                "remote_app_coverage_ratio": None if remote_coverage is None else round(remote_coverage, 4),
                "policy_coverage_score": policy_score,
                "ringfence_maturity_score": ringfence_score,
                "enforcement_mode_score": enforce_score,
                "staged_readiness_score": staged_score,
                "remote_app_coverage_score": remote_score,
                "flow_count": total,
                "connection_count": int(flows["num_connections"].sum()),
                "blocked_or_pb_flow_count": int(flows["policy_decision"].isin(["blocked", "potentially_blocked"]).sum()),
                "pb_uncovered_count": pb_uncovered_count,
            }
        )

        confidence = "high" if total >= 6 else "medium"
        if allowed_ratio < 0.75:
            attack_items.append(
                make_posture_item(
                    scope="traffic_report",
                    framework="microseg_attack",
                    app=app,
                    env=env,
                    finding_kind="enforcement_gap",
                    attack_stage="control_plane",
                    confidence=confidence,
                    recommended_action_code="MOVE_TO_ENFORCEMENT",
                    severity=_severity_from_ratio(1 - allowed_ratio),
                    evidence={
                        "flow_count": total,
                        "allowed_ratio": round(allowed_ratio, 4),
                        "blocked_or_pb_flow_count": int(flows["policy_decision"].isin(["blocked", "potentially_blocked"]).sum()),
                    },
                )
            )
        if ringfence_ratio < 0.5:
            attack_items.append(
                make_posture_item(
                    scope="traffic_report",
                    framework="microseg_attack",
                    app=app,
                    env=env,
                    finding_kind="boundary_breach",
                    attack_stage="pivot",
                    confidence=confidence,
                    recommended_action_code="DEFINE_RINGFENCE_SCOPE",
                    severity="HIGH" if ringfence_ratio < 0.25 else "MEDIUM",
                    evidence={"flow_count": total, "ringfence_ratio": round(ringfence_ratio, 4)},
                )
            )
        if blocked_ratio > 0.2:
            attack_items.append(
                make_posture_item(
                    scope="traffic_report",
                    framework="microseg_attack",
                    app=app,
                    env=env,
                    finding_kind="suspicious_pivot",
                    attack_stage="pivot",
                    confidence=confidence,
                    recommended_action_code="REVIEW_REMOTE_ACCESS_ALLOWLIST",
                    severity=_severity_from_ratio(blocked_ratio),
                    evidence={"flow_count": total, "blocked_ratio": round(blocked_ratio, 4)},
                )
            )
        if remote_coverage is not None and remote_coverage < 0.85:
            attack_items.append(
                make_posture_item(
                    scope="traffic_report",
                    framework="microseg_attack",
                    app=app,
                    env=env,
                    finding_kind="boundary_breach",
                    attack_stage="pivot",
                    confidence=confidence,
                    recommended_action_code="LOCK_BOUNDARY_PORTS",
                    severity="HIGH",
                    evidence={
                        "remote_flow_count": int(len(remote)),
                        "remote_allowed_ratio": round(remote_coverage, 4),
                    },
                )
            )

    if not app_rows:
        return {"error": t("rpt_mod13_err_no_app_env", lang=lang)}

    app_env_scores = pd.DataFrame(app_rows).sort_values(
        by=["readiness_score", "app_env_key"], ascending=[True, True]
    ).reset_index(drop=True)

    def _avg(col):
        v = pd.to_numeric(app_env_scores[col], errors="coerce").dropna()
        return None if v.empty else float(v.mean())

    avg_policy = _avg("policy_coverage_ratio") or 0.0
    avg_ringfence = _avg("ringfence_maturity_ratio")
    avg_enforce = _avg("enforcement_mode_ratio")
    avg_staged = _avg("staged_readiness_ratio")
    avg_remote = _avg("remote_app_coverage_ratio")
    averages = {"policy_coverage": avg_policy, "ringfence_maturity": avg_ringfence,
                "enforcement_mode": avg_enforce, "staged_readiness": avg_staged,
                "remote_app_coverage": avg_remote}

    # A factor with no data (no enforcement mode in the source, no remote
    # flows) is shown as N/A and left out of the total, which is rescaled
    # over the factors that do apply.
    factor_scores = {k: (None if r is None else round(_WEIGHTS[k] * r, 1)) for k, r in averages.items()}
    total_score = _weighted(averages)
    _labels = {
        "policy_coverage": t("rpt_factor_policy_coverage", default="Policy Coverage", lang=lang),
        "ringfence_maturity": t("rpt_factor_ringfence_maturity", default="Ringfence Maturity", lang=lang),
        "enforcement_mode": t("rpt_factor_enforcement_mode", default="Enforcement Mode", lang=lang),
        "staged_readiness": t("rpt_factor_staged_readiness", default="Staged Readiness", lang=lang),
        "remote_app_coverage": t("rpt_factor_remote_app_coverage", default="Remote-App Coverage", lang=lang),
    }
    na = t("rpt_mat_na", lang=lang)
    factor_table = pd.DataFrame([
        {"Factor": _labels[k], "Weight": _WEIGHTS[k],
         "Score": na if factor_scores[k] is None else factor_scores[k],
         "Ratio %": na if averages[k] is None else round(averages[k] * 100, 1)}
        for k in _WEIGHTS
    ])

    # Enforcement mode distribution from workloads (if available)
    enforcement_mode_distribution: dict[str, int] = {}
    if workloads:
        for w in workloads:
            mode = str(w.get("enforcement_mode", "unknown")).lower().strip()
            enforcement_mode_distribution[mode] = enforcement_mode_distribution.get(mode, 0) + 1

    ranked_items = rank_posture_items(attack_items)
    recommendations = _build_recommendations(ranked_items, top_n=top_n, lang=lang)

    factor_chart_labels = [
        t("rpt_factor_policy_coverage", default="Policy Coverage", lang=lang),
        t("rpt_factor_ringfence_maturity", default="Ringfence Maturity", lang=lang),
        t("rpt_factor_enforcement_mode", default="Enforcement Mode", lang=lang),
        t("rpt_factor_staged_readiness", default="Staged Readiness", lang=lang),
        t("rpt_factor_remote_app_coverage", default="Remote-App Coverage", lang=lang),
    ]
    factor_chart_values = [
        factor_scores['policy_coverage'] or 0,
        factor_scores['ringfence_maturity'] or 0,
        factor_scores['enforcement_mode'] or 0,
        factor_scores['staged_readiness'] or 0,
        factor_scores['remote_app_coverage'] or 0,
    ]

    # Estate-wide PB total must come from the deduped flow frame: summing the
    # per-app column double-counts every cross-app flow (each such flow lands in
    # both its src_key and dst_key group). Count each flow row exactly once.
    total_pb_uncovered = int((work["policy_decision"] == "potentially_blocked").sum())

    result = {
        "total_score": total_score,
        "ready_to_enforce_share": round(avg_policy, 4),
        "pb_uncovered_count": total_pb_uncovered,
        "grade": _score_to_grade(total_score),
        "factor_scores": factor_scores,
        "factor_table": factor_table,
        "recommendations": recommendations,
        "app_env_scores": app_env_scores.head(top_n),
        "enforcement_mode_distribution": enforcement_mode_distribution,
        "attack_posture_items": ranked_items[: max(top_n, 10)],
        "chart_spec": {
            "type": "bar",
            "title": "Enforcement Readiness Factor Scores",
            "title_key": "rpt_chart_readiness_factor_scores",
            "x_label": t("rpt_dimension", default="Factor", lang=lang),
            "x_label_key": "rpt_chart_axis_factor",
            "y_label": t("rpt_score", default="Score", lang=lang),
            "y_label_key": "rpt_chart_axis_score",
            "data": {"labels": factor_chart_labels, "values": factor_chart_values},
            "i18n": {"lang": lang},
        },
    }

    if "draft_policy_decision" in df.columns:
        result["draft_enforcement_gap"] = int(
            df["draft_policy_decision"].str.startswith("blocked_", na=False).sum()
        )

    return result


def analyze(flows_df: pd.DataFrame, query_context: dict | None = None, *, lang: str = "en") -> dict:
    """Public alias matching the standard module interface."""
    df = flows_df.copy()
    if "num_connections" not in df.columns:
        df["num_connections"] = 1
    return enforcement_readiness(df, lang=lang)

