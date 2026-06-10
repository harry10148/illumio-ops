"""Posture score computation from traffic-report KPI snapshot.

This module is PURE (no I/O).  It maps whatever keys the snapshot actually
contains to three components, then produces a transparent breakdown that the
dashboard "How is this computed?" modal can render directly.

Snapshot key mapping
--------------------
The traffic snapshot written by ReportGenerator contains top-level keys from
`executive_summary()`:
  enforced_coverage_pct  → coverage_pct   (0-100 float, policy enforcement %)
  maturity_score         → readiness_pct  (0-100, microsegmentation maturity)
  maturity_dimensions.risk_port_control.ratio
                         → risk_control_ratio (fallback for penalty)

Risk penalty is derived from risk signals embedded in the snapshot:
  - ransomware_apps   : snapshot.get("risk_flows_total") or kpis dict
  - lateral_risk      : snapshot.get("lateral_movement_control") ratio from
                        maturity_dimensions (0-1; higher = better control)
  - uncovered_flows   : snapshot.get("true_gap_pct") or pb_uncovered_exposure

Risk penalty formula (bounded 0-100):
  ransomware_pts = min(40, ransomware_apps * 5)
      → each ransomware-exposed app costs 5 pts; cap at 40
  lateral_pts    = round((1 - lateral_control_ratio) * 30)
      → fully uncontrolled lateral movement costs 30 pts; 0 if fully controlled
  uncovered_pts  = min(30, uncovered_pct * 0.5)
      → true gap % scaled linearly; 60% gap = 30 pts

penalty = min(100, ransomware_pts + lateral_pts + uncovered_pts)
risk_health = max(0, 100 - penalty)

Final score
-----------
  score = round(coverage * 0.3 + readiness * 0.3 + risk_health * 0.4)

Missing components are excluded and weights renormalized.
If NO component is available: score=None, available=False.
"""
from __future__ import annotations

from typing import Optional


def _get_float(d: dict, *keys, default=None) -> Optional[float]:
    """Return first found key as float, or default."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return default


def compute_posture(kpis: dict) -> dict:
    """Compute posture score from a traffic snapshot KPI dict.

    Parameters
    ----------
    kpis:
        The snapshot dict (top-level, not the kpis list).  Pass the entire
        snapshot or at minimum the relevant sub-keys.

    Returns
    -------
    dict with keys:
        score         int | None
        available     bool
        formula       str
        components    list[dict]
    """
    if not isinstance(kpis, dict):
        return {"score": None, "available": False, "formula": "", "components": []}

    # ── Component 1: Policy Coverage % ─────────────────────────────────────────
    # Prefer enforced_coverage_pct from exec summary; fall back to
    # maturity_dimensions.policy_coverage.ratio (×100) or microsegmentation_maturity
    coverage_pct: Optional[float] = _get_float(kpis, "enforced_coverage_pct")
    if coverage_pct is None:
        dims = kpis.get("maturity_dimensions") or {}
        pc = (dims.get("policy_coverage") or dims.get("enforcement_coverage") or {})
        ratio = pc.get("ratio")
        if ratio is not None:
            try:
                coverage_pct = float(ratio) * 100.0
            except (TypeError, ValueError):
                pass
    if coverage_pct is None:
        # Last resort: microsegmentation_maturity dict-kpi (from analyze() path)
        flat_kpis = kpis.get("kpis") or {}
        if isinstance(flat_kpis, dict):
            v = flat_kpis.get("active_allow_coverage") or flat_kpis.get("microsegmentation_maturity")
            if v is not None:
                try:
                    f = float(v)
                    coverage_pct = f * 100.0 if f <= 1.0 else f
                except (TypeError, ValueError):
                    pass

    # ── Component 2: Enforcement Readiness % ───────────────────────────────────
    # maturity_score is already 0-100.  If absent, try enforcement_coverage ratio.
    readiness_pct: Optional[float] = _get_float(kpis, "maturity_score")
    if readiness_pct is None:
        dims = kpis.get("maturity_dimensions") or {}
        ec = (dims.get("enforcement_coverage") or {})
        ratio = ec.get("ratio")
        if ratio is not None:
            try:
                readiness_pct = float(ratio) * 100.0
            except (TypeError, ValueError):
                pass

    # ── Component 3: Risk signals → penalty → risk_health ──────────────────────
    # ransomware_apps: count of risk/ransomware-exposed flows (risk_flows_total)
    ransomware_apps = 0
    rft = _get_float(kpis, "risk_flows_total")
    if rft is None:
        flat_kpis = kpis.get("kpis") or {}
        if isinstance(flat_kpis, dict):
            rft = _get_float(flat_kpis, "high_risk_lateral_paths")
    if rft is not None:
        ransomware_apps = int(rft)

    # lateral_control_ratio: from maturity_dimensions (0=bad, 1=fully controlled)
    lateral_control_ratio: float = 1.0  # assume best if unknown
    dims = kpis.get("maturity_dimensions") or {}
    lm = dims.get("lateral_movement_control") or {}
    if lm.get("ratio") is not None:
        try:
            lateral_control_ratio = float(lm["ratio"])
        except (TypeError, ValueError):
            pass

    # uncovered_pct: true_gap_pct (% of flows with no policy) or pb_uncovered
    uncovered_pct: float = 0.0
    uncovered_avail = False
    tgp = _get_float(kpis, "true_gap_pct")
    if tgp is not None:
        uncovered_pct = float(tgp)
        uncovered_avail = True
    else:
        flat_kpis = kpis.get("kpis") or {}
        if isinstance(flat_kpis, dict):
            pb = _get_float(flat_kpis, "pb_uncovered_exposure")
            if pb is not None:
                # Convert raw flow count to an approximate percentage (capped at 100)
                total = _get_float(kpis, "total_flows") or 1.0
                uncovered_pct = min(100.0, float(pb) / float(total) * 100.0)
                uncovered_avail = True

    # Risk penalty (documented in module docstring)
    ransomware_pts = min(40, ransomware_apps * 5)
    lateral_pts = round((1.0 - min(1.0, max(0.0, lateral_control_ratio))) * 30)
    uncovered_pts = min(30, uncovered_pct * 0.5)
    penalty = min(100.0, ransomware_pts + lateral_pts + uncovered_pts)
    risk_health = max(0.0, 100.0 - penalty)

    # Determine whether risk component is "available" (at least one signal present)
    has_risk = (rft is not None or tgp is not None
                or lm.get("ratio") is not None)

    # ── Score computation with weight renormalization ──────────────────────────
    WEIGHTS = {
        "coverage":   (0.3, coverage_pct),
        "readiness":  (0.3, readiness_pct),
        "risk_health": (0.4, risk_health if has_risk else None),
    }
    total_weight = sum(w for w, v in WEIGHTS.values() if v is not None)
    score: Optional[int] = None
    if total_weight > 0:
        raw = sum(
            (w / total_weight) * v
            for w, v in WEIGHTS.values()
            if v is not None
        )
        score = max(0, min(100, round(raw)))

    available = score is not None

    # ── Build transparent breakdown ────────────────────────────────────────────
    components = []

    def _component(key, label_key, value, weight, effective_weight, note_key=""):
        if value is None:
            return None
        points = round((effective_weight) * value, 2)
        c = {
            "key": key,
            "label_key": label_key,
            "value": round(value, 1),
            "unit": "%",
            "weight": round(weight, 2),
            "effective_weight": round(effective_weight, 3),
            "points": points,
        }
        if note_key:
            c["note_key"] = note_key
        return c

    eff_cov = (0.3 / total_weight) if total_weight > 0 and coverage_pct is not None else 0.0
    eff_rdy = (0.3 / total_weight) if total_weight > 0 and readiness_pct is not None else 0.0
    eff_rsk = (0.4 / total_weight) if total_weight > 0 and has_risk else 0.0

    c = _component("coverage", "gui_posture_coverage", coverage_pct, 0.3, eff_cov,
                   note_key="gui_posture_coverage_note")
    if c:
        components.append(c)

    c = _component("readiness", "gui_posture_readiness", readiness_pct, 0.3, eff_rdy,
                   note_key="gui_posture_readiness_note")
    if c:
        components.append(c)

    if has_risk:
        rh_points = round(eff_rsk * risk_health, 2)
        risk_subscores = []
        if rft is not None:
            risk_subscores.append({
                "key": "ransomware_containment",
                "label_key": "gui_posture_sub_ransomware",
                "value": round(100.0 * (1.0 - ransomware_pts / 40.0)),
                "unit": "%",
                "penalty_points": round(ransomware_pts, 2),
                "max_penalty": 40,
            })
        if lm.get("ratio") is not None:
            risk_subscores.append({
                "key": "lateral_containment",
                "label_key": "gui_posture_sub_lateral",
                "value": round(100.0 * (1.0 - lateral_pts / 30.0)),
                "unit": "%",
                "penalty_points": round(lateral_pts, 2),
                "max_penalty": 30,
            })
        if uncovered_avail:
            risk_subscores.append({
                "key": "flow_coverage",
                "label_key": "gui_posture_sub_coverage",
                "value": round(100.0 * (1.0 - uncovered_pts / 30.0)),
                "unit": "%",
                "penalty_points": round(uncovered_pts, 2),
                "max_penalty": 30,
            })
        components.append({
            "key": "risk_health",
            "label_key": "gui_posture_risk_health",
            "value": round(risk_health, 1),
            "unit": "%",
            "weight": 0.4,
            "effective_weight": round(eff_rsk, 3),
            "points": rh_points,
            "note_key": "gui_posture_risk_health_note",
            "risk_subscores": risk_subscores,
            "detail": {
                "ransomware_apps": ransomware_apps,
                "lateral_control_ratio": round(lateral_control_ratio, 4),
                "uncovered_pct": round(uncovered_pct, 2),
                "penalty": round(penalty, 1),
            },
        })

    return {
        "score": score,
        "available": available,
        "formula": "coverage×0.3 + readiness×0.3 + risk_health×0.4",
        "components": components,
    }
