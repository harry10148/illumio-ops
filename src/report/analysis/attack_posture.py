"""Deterministic shared posture/attack data layer for traffic reporting."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.i18n import t

_UNLABELED = "unlabeled"

SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MEDIUM": 2,
    "LOW": 3,
    "INFO": 4,
}

CONFIDENCE_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}

ATTACK_STAGE_ORDER = {
    "initial_access": 0,
    "exposure": 1,
    "pivot": 2,
    "lateral_movement": 3,
    "blast_radius": 4,
    "control_plane": 5,
    "containment": 6,
}

FINDING_KIND_ORDER = {
    "boundary_breach": 0,
    "suspicious_pivot": 1,
    "blast_radius": 2,
    "blind_spot": 3,
    "enforcement_gap": 4,
}

# Action codes resolve to i18n keys (rpt_action_<lowercased code>); locale
# dispatch happens inside t() so zh_TW reports never fall back to English.
_ACTION_CODES: frozenset[str] = frozenset({
    "LOCK_BOUNDARY_PORTS",
    "MOVE_TO_ENFORCEMENT",
    "DEFINE_RINGFENCE_SCOPE",
    "REVIEW_REMOTE_ACCESS_ALLOWLIST",
    "TIGHTEN_LATERAL_POLICY",
    "RESTRICT_TRANSIT_NODE_ACCESS",
    "ONBOARD_UNMANAGED",
    "REVIEW_UNUSED_RULESETS",
    "RESOLVE_QUERY_FAILURES",
    "INVESTIGATE_HIGH_RISK_PORT_HITS",
    "REVIEW_HIGH_IMPACT_PROVISIONS",
    "HARDEN_AUTH_CHANNELS",
})

def _normalize_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text else _UNLABELED

def build_app_env_key(app: Any, env: Any) -> str:
    """Return normalized app_env identity key."""
    return f"{_normalize_label(app)}|{_normalize_label(env)}"

def build_app_display(app: Any, env: Any) -> str:
    """Return standardized display format for app/env identity."""
    return f"{_normalize_label(app)} ({_normalize_label(env)})"

def make_posture_item(
    *,
    scope: str,
    framework: str,
    app: Any,
    env: Any,
    finding_kind: str,
    attack_stage: str,
    confidence: str,
    recommended_action_code: str,
    severity: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable posture record with deterministic fields only."""
    return {
        "scope": scope,
        "framework": framework,
        "app_env_key": build_app_env_key(app, env),
        "app_display": build_app_display(app, env),
        "finding_kind": str(finding_kind or "").strip(),
        "attack_stage": str(attack_stage or "").strip(),
        "confidence": str(confidence or "medium").strip().lower(),
        "recommended_action_code": str(recommended_action_code or "").strip(),
        "severity": str(severity or "INFO").strip().upper(),
        "evidence": dict(evidence or {}),
    }

def rank_posture_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort posture findings with fixed severity/risk precedence."""
    return sorted(
        list(items or []),
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity", "")).upper(), 99),
            CONFIDENCE_ORDER.get(str(item.get("confidence", "")).lower(), 99),
            ATTACK_STAGE_ORDER.get(str(item.get("attack_stage", "")).lower(), 99),
            FINDING_KIND_ORDER.get(str(item.get("finding_kind", "")).lower(), 99),
            str(item.get("app_env_key", "")),
            str(item.get("recommended_action_code", "")),
        ),
    )

def resolve_recommendation(code: str, lang: str = "en") -> str:
    """Resolve recommendation text from i18n action-code keys."""
    norm = str(code or "").strip()
    if norm not in _ACTION_CODES:
        return t("rpt_action_default", lang=lang)
    return t(f"rpt_action_{norm.lower()}", lang=lang)

def _enrich_app_display(app_display: str, app_env_key: str, node_ips: dict[str, list[str]]) -> str:
    """Append IPs to display label. Unlabeled: IPs only. Labeled: label · IPs."""
    ips = node_ips.get(app_env_key, [])
    if not ips:
        return app_display
    shown = ips[:4]
    suffix = f" +{len(ips) - 4}" if len(ips) > 4 else ""
    ip_str = ", ".join(shown) + suffix
    if app_display == "unlabeled (unlabeled)":
        return ip_str
    return f"{app_display} · {ip_str}"

def summarize_attack_posture(items: list[dict[str, Any]], top_n: int = 5, lang: str = "en", node_ips: dict[str, list[str]] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Build attack-first summary blocks for report/email/snapshot."""
    ranked = rank_posture_items(items)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    finding_label_keys = {
        "boundary_breach": "rpt_finding_boundary_breach",
        "suspicious_pivot": "rpt_finding_suspicious_pivot",
        "blast_radius": "rpt_finding_blast_radius",
        "blind_spot": "rpt_finding_blind_spot",
        "enforcement_gap": "rpt_finding_enforcement_gap",
    }

    section_by_kind = {
        "boundary_breach": "boundary_breaches",
        "suspicious_pivot": "suspicious_pivot_behavior",
        "blast_radius": "blast_radius",
        "blind_spot": "blind_spots",
        "enforcement_gap": "blind_spots",
    }

    for item in ranked:
        section = section_by_kind.get(str(item.get("finding_kind", "")).lower())
        if section:
            kind = str(item.get("finding_kind", "")).lower()
            label = t(finding_label_keys.get(kind, "rpt_finding_blind_spot"), lang=lang)
            app_display = item.get("app_display", "unlabeled (unlabeled)")
            if node_ips:
                app_display = _enrich_app_display(app_display, item.get("app_env_key", ""), node_ips)
            grouped[section].append(
                {
                    "severity": item.get("severity", "INFO"),
                    "finding": f"{app_display}: {label}",
                    "action": resolve_recommendation(str(item.get("recommended_action_code", "")), lang),
                    "app_env_key": item.get("app_env_key", ""),
                    "action_code": item.get("recommended_action_code", ""),
                    "evidence": item.get("evidence", {}),
                }
            )

    action_counter: dict[str, int] = defaultdict(int)
    for item in ranked:
        code = str(item.get("recommended_action_code", "")).strip()
        if code:
            action_counter[code] += 1

    action_matrix = [
        {
            "action_code": code,
            "count": count,
            "action": resolve_recommendation(code, lang),
        }
        for code, count in sorted(action_counter.items(), key=lambda pair: (-pair[1], pair[0]))
    ][:top_n]

    return {
        "boundary_breaches": grouped.get("boundary_breaches", [])[:top_n],
        "suspicious_pivot_behavior": grouped.get("suspicious_pivot_behavior", [])[:top_n],
        "blast_radius": grouped.get("blast_radius", [])[:top_n],
        "blind_spots": grouped.get("blind_spots", [])[:top_n],
        "action_matrix": action_matrix,
    }
