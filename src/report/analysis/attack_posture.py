"""Deterministic shared posture/attack data layer for traffic reporting."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

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

RECOMMENDATION_TEMPLATES: dict[str, dict[str, str]] = {
    "LOCK_BOUNDARY_PORTS": {
        "en": "Restrict cross-boundary ports to explicit allowlists and remove broad access.",
        "zh_TW": "將跨邊界通訊埠收斂為明確 allowlist，移除過寬存取範圍。",
    },
    "MOVE_TO_ENFORCEMENT": {
        "en": "Move scoped workloads from visibility/testing into selective or full enforcement.",
        "zh_TW": "將範圍內工作負載由 visibility/testing 推進到 selective 或 full enforcement。",
    },
    "DEFINE_RINGFENCE_SCOPE": {
        "en": "Tighten ringfence scope so only required app-to-app paths are permitted.",
        "zh_TW": "收斂 ringfence 範圍，只保留必要的 app-to-app 存取路徑。",
    },
    "REVIEW_REMOTE_ACCESS_ALLOWLIST": {
        "en": "Review remote-access flows and keep only approved source-to-destination pairs.",
        "zh_TW": "檢查遠端存取流量，只保留核准的來源到目的地組合。",
    },
    "TIGHTEN_LATERAL_POLICY": {
        "en": "Reduce traversable lateral paths and segment high-reachability nodes.",
        "zh_TW": "降低可橫向移動路徑，並優先分段高可達性的節點。",
    },
    "RESTRICT_TRANSIT_NODE_ACCESS": {
        "en": "This workload acts as a network hub (high reachability or articulation point). Apply stricter east-west policy boundaries to limit lateral movement.",
        "zh_TW": "此 workload 在流量圖中扮演網路樞紐角色（高可達性或 articulation point），請套用更嚴格的東西向政策邊界以限制橫向移動。",
    },
    "ONBOARD_UNMANAGED": {
        "en": "Onboard unmanaged assets or explicitly isolate their access paths.",
        "zh_TW": "將 unmanaged 資產納管，或明確隔離其存取路徑。",
    },
    "REVIEW_UNUSED_RULESETS": {
        "en": "Review high-unused rulesets and narrow policy scope to active dependencies.",
        "zh_TW": "檢視高比例未使用 ruleset，並將政策範圍收斂到實際依賴路徑。",
    },
    "RESOLVE_QUERY_FAILURES": {
        "en": "Resolve pending/failed usage queries before making policy retirement decisions.",
        "zh_TW": "先排除 pending/failed usage query，再進行政策下線判斷。",
    },
    "INVESTIGATE_HIGH_RISK_PORT_HITS": {
        "en": "Investigate concentration of high-risk port hits and validate least-privilege policy intent.",
        "zh_TW": "調查高風險通訊埠命中集中現象，並驗證最小權限政策是否符合預期。",
    },
    "REVIEW_HIGH_IMPACT_PROVISIONS": {
        "en": "Review high-impact provisions and confirm boundary-sensitive changes were authorized.",
        "zh_TW": "檢查高影響範圍 provision，確認邊界敏感變更皆經授權。",
    },
    "HARDEN_AUTH_CHANNELS": {
        "en": "Harden authentication channels and investigate repeated failed authentication behavior.",
        "zh_TW": "強化驗證通道並調查重複失敗的登入行為。",
    },
}

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
    """Resolve recommendation text from deterministic templates."""
    template = RECOMMENDATION_TEMPLATES.get(str(code or "").strip())
    if not template:
        return "Review attack posture evidence and apply least-privilege segmentation."
    if lang in template:
        return template[lang]
    return template.get("en", "")

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
    finding_labels = {
        "boundary_breach": ("Boundary control weakness detected", "偵測到邊界控制弱點"),
        "suspicious_pivot": ("Suspicious pivot behavior detected", "偵測到可疑橫向樞紐行為"),
        "blast_radius": ("High blast-radius posture detected", "偵測到高擴散半徑風險"),
        "blind_spot": ("Visibility/enforcement blind spot detected", "偵測到可視性或強制執行盲點"),
        "enforcement_gap": ("Enforcement gap detected", "偵測到強制執行落差"),
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
            label_en, label_zh = finding_labels.get(kind, (kind.replace("_", " "), kind.replace("_", " ")))
            label = label_zh if lang == "zh_TW" else label_en
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
