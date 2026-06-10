"""Score-impact remediation advisor.

PURE derivation over compute_posture() output (no I/O). Turns the posture
breakdown into a ranked "fix this -> +N points" list. Each item's
``recoverable_points`` is how much the overall (weight-renormalized) posture
score would rise if that axis were brought to 100, reusing the
``effective_weight`` already computed by compute_posture().

Returns i18n KEYS, not rendered text -- the presentation layer renders them.
"""
from __future__ import annotations

# Risk sub-score key -> recommendation i18n key
_RISK_REC = {
    "ransomware_containment": "gui_posture_rmd_ransomware",
    "lateral_containment": "gui_posture_rmd_lateral",
    "flow_coverage": "gui_posture_rmd_coverage",
}
# Top-level component key -> recommendation i18n key
_COMPONENT_REC = {
    "coverage": "gui_posture_rmd_policy_coverage",
    "readiness": "gui_posture_rmd_readiness",
}


def build_remediation(posture: dict) -> list[dict]:
    """Return remediation items sorted by recoverable_points (desc)."""
    if not posture or not posture.get("available"):
        return []

    items: list[dict] = []
    for comp in posture.get("components") or []:
        key = comp.get("key")
        eff = comp.get("effective_weight") or 0.0

        if key in ("coverage", "readiness"):
            value = comp.get("value")
            if value is None:
                continue
            recoverable = eff * (100.0 - value)
            if recoverable <= 0:
                continue
            items.append({
                "key": key,
                "label_key": comp.get("label_key"),
                "recoverable_points": round(recoverable, 1),
                "current": round(value, 1),
                "target": 100,
                "recommendation_key": _COMPONENT_REC.get(key, ""),
            })

        elif key == "risk_health":
            for sub in comp.get("risk_subscores") or []:
                pts = sub.get("penalty_points") or 0.0
                recoverable = eff * pts
                if recoverable <= 0:
                    continue
                items.append({
                    "key": sub.get("key"),
                    "label_key": sub.get("label_key"),
                    "recoverable_points": round(recoverable, 1),
                    "current": sub.get("value"),
                    "target": 100,
                    "recommendation_key": _RISK_REC.get(sub.get("key"), ""),
                })

    items.sort(key=lambda x: x["recoverable_points"], reverse=True)
    return items
