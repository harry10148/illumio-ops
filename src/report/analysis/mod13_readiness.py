"""Module 13: Deterministic enforcement readiness by app(env)."""
from __future__ import annotations

import pandas as pd
from src.i18n import t, get_language

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

def _build_recommendations(attack_items: list[dict], top_n: int) -> pd.DataFrame:
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
                "Issue": item.get("finding_kind", "").replace("_", " ").title(),
                "Action": resolve_recommendation(item.get("recommended_action_code", ""), "en"),
                "Action Code": item.get("recommended_action_code", ""),
                "Severity": item.get("severity", "INFO"),
            }
        )
    return pd.DataFrame(rows)

def enforcement_readiness(df: pd.DataFrame, workloads: list | None = None, top_n: int = 20) -> dict:
    if df.empty:
        return {"error": "No data"}

    work = df.copy()
    work["src_key"] = _normalize_key_series(work, "src_app", "src_env")
    work["dst_key"] = _normalize_key_series(work, "dst_app", "dst_env")
    work["num_connections"] = pd.to_numeric(work.get("num_connections", 1), errors="coerce").fillna(1).astype(int)
    work["policy_decision"] = work.get("policy_decision", "").fillna("").astype(str).str.lower()
    work["port"] = pd.to_numeric(work.get("port", -1), errors="coerce").fillna(-1).astype(int)

    all_keys = sorted(set(work["src_key"].tolist()) | set(work["dst_key"].tolist()))
    app_rows: list[dict] = []
    attack_items: list[dict] = []

    global_workload_ratio = 0.5
    if workloads:
        enforced = sum(1 for w in workloads if str(w.get("enforcement_mode", "")).lower() in {"full", "selective"})
        global_workload_ratio = enforced / max(1, len(workloads))

    for key in all_keys:
        app, env = key.split("|", 1)
        flows = work[(work["src_key"] == key) | (work["dst_key"] == key)]
        if flows.empty:
            continue

        total = len(flows)
        allowed_ratio = float((flows["policy_decision"] == "allowed").mean())
        ringfence_ratio = float((flows["src_key"] == flows["dst_key"]).mean()) if total else 0.0

        src_flags = (
            flows.loc[flows["src_key"] == key, "src_managed"].fillna(False).astype(bool).tolist()
            if "src_managed" in flows.columns
            else []
        )
        dst_flags = (
            flows.loc[flows["dst_key"] == key, "dst_managed"].fillna(False).astype(bool).tolist()
            if "dst_managed" in flows.columns
            else []
        )
        managed_flags = src_flags + dst_flags
        enforce_ratio = float(sum(managed_flags) / len(managed_flags)) if managed_flags else global_workload_ratio

        # Staged readiness: potentially_blocked means rules exist but not yet enforced.
        # This is a positive signal (rules are ready) — reward it instead of penalizing.
        pb_ratio = float((flows["policy_decision"] == "potentially_blocked").mean())
        blocked_ratio = float((flows["policy_decision"] == "blocked").mean())
        # staged_ratio combines allowed (already enforced) + potentially_blocked (ready to enforce)
        staged_ratio = min(1.0, allowed_ratio + pb_ratio)

        remote = flows[flows["port"].isin(_REMOTE_PORTS)]
        if remote.empty:
            remote_coverage = 1.0
        else:
            remote_coverage = float((remote["policy_decision"] == "allowed").mean())

        policy_score = round(_WEIGHTS["policy_coverage"] * allowed_ratio, 1)
        ringfence_score = round(_WEIGHTS["ringfence_maturity"] * ringfence_ratio, 1)
        enforce_score = round(_WEIGHTS["enforcement_mode"] * enforce_ratio, 1)
        staged_score = round(_WEIGHTS["staged_readiness"] * staged_ratio, 1)
        remote_score = round(_WEIGHTS["remote_app_coverage"] * remote_coverage, 1)
        readiness_score = round(policy_score + ringfence_score + enforce_score + staged_score + remote_score, 1)

        app_rows.append(
            {
                "app_env_key": key,
                "app_display": build_app_display(app, env),
                "readiness_score": readiness_score,
                "policy_coverage_ratio": round(allowed_ratio, 4),
                "ringfence_maturity_ratio": round(ringfence_ratio, 4),
                "enforcement_mode_ratio": round(enforce_ratio, 4),
                "staged_readiness_ratio": round(staged_ratio, 4),
                "potentially_blocked_ratio": round(pb_ratio, 4),
                "remote_app_coverage_ratio": round(remote_coverage, 4),
                "policy_coverage_score": policy_score,
                "ringfence_maturity_score": ringfence_score,
                "enforcement_mode_score": enforce_score,
                "staged_readiness_score": staged_score,
                "remote_app_coverage_score": remote_score,
                "flow_count": total,
                "connection_count": int(flows["num_connections"].sum()),
                "blocked_or_pb_flow_count": int(flows["policy_decision"].isin(["blocked", "potentially_blocked"]).sum()),
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
        if not remote.empty and remote_coverage < 0.85:
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
        return {"error": "No app/env records derived from traffic"}

    app_env_scores = pd.DataFrame(app_rows).sort_values(
        by=["readiness_score", "app_env_key"], ascending=[True, True]
    ).reset_index(drop=True)

    avg_policy = float(app_env_scores["policy_coverage_ratio"].mean())
    avg_ringfence = float(app_env_scores["ringfence_maturity_ratio"].mean())
    avg_enforce = float(app_env_scores["enforcement_mode_ratio"].mean())
    avg_staged = float(app_env_scores["staged_readiness_ratio"].mean())
    avg_remote = float(app_env_scores["remote_app_coverage_ratio"].mean())

    factor_scores = {
        "policy_coverage": round(_WEIGHTS["policy_coverage"] * avg_policy, 1),
        "ringfence_maturity": round(_WEIGHTS["ringfence_maturity"] * avg_ringfence, 1),
        "enforcement_mode": round(_WEIGHTS["enforcement_mode"] * avg_enforce, 1),
        "staged_readiness": round(_WEIGHTS["staged_readiness"] * avg_staged, 1),
        "remote_app_coverage": round(_WEIGHTS["remote_app_coverage"] * avg_remote, 1),
    }

    total_score = round(sum(factor_scores.values()), 1)
    factor_table = pd.DataFrame(
        [
            {"Factor": "Policy Coverage", "Weight": _WEIGHTS["policy_coverage"], "Score": factor_scores["policy_coverage"], "Ratio %": round(avg_policy * 100, 1)},
            {"Factor": "Ringfence Maturity", "Weight": _WEIGHTS["ringfence_maturity"], "Score": factor_scores["ringfence_maturity"], "Ratio %": round(avg_ringfence * 100, 1)},
            {"Factor": "Enforcement Mode", "Weight": _WEIGHTS["enforcement_mode"], "Score": factor_scores["enforcement_mode"], "Ratio %": round(avg_enforce * 100, 1)},
            {"Factor": "Staged Readiness", "Weight": _WEIGHTS["staged_readiness"], "Score": factor_scores["staged_readiness"], "Ratio %": round(avg_staged * 100, 1)},
            {"Factor": "Remote-App Coverage", "Weight": _WEIGHTS["remote_app_coverage"], "Score": factor_scores["remote_app_coverage"], "Ratio %": round(avg_remote * 100, 1)},
        ]
    )

    # Enforcement mode distribution from workloads (if available)
    enforcement_mode_distribution: dict[str, int] = {}
    if workloads:
        for w in workloads:
            mode = str(w.get("enforcement_mode", "unknown")).lower().strip()
            enforcement_mode_distribution[mode] = enforcement_mode_distribution.get(mode, 0) + 1

    ranked_items = rank_posture_items(attack_items)
    recommendations = _build_recommendations(ranked_items, top_n=top_n)

    factor_chart_labels = [
        'Policy Coverage',
        'Ringfence Maturity',
        'Enforcement Mode',
        'Staged Readiness',
        'Remote App Coverage',
    ]
    factor_chart_values = [
        factor_scores['policy_coverage'],
        factor_scores['ringfence_maturity'],
        factor_scores['enforcement_mode'],
        factor_scores['staged_readiness'],
        factor_scores['remote_app_coverage'],
    ]

    return {
        "total_score": total_score,
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
            "x_label": t("rpt_dimension", default="Factor"),
            "y_label": t("rpt_score", default="Score"),
            "data": {"labels": factor_chart_labels, "values": factor_chart_values},
            "i18n": {"lang": get_language()},
        },
    }

