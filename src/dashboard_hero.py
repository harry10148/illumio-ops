"""Story-mode dashboard hero builder.

Pure helper used by /api/dashboard/snapshot to enrich the snapshot payload
with a one-sentence health summary + CTA metadata. Frontend consumes the
returned dict via dashboard.js:renderHero().
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_MATURITY_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*100\s*(?:\(([A-F])\))?")
_HIGH_RISK_SEVERITIES = {"HIGH", "CRITICAL"}


def _empty_hero() -> Dict[str, Any]:
    return {
        "sentence_key": "gui_hero_no_data",
        "sentence_params": {},
        "score": 0.0,
        "score_grade": "?",
        "high_risk_count": 0,
    }


def build_hero(snapshot: Optional[Dict[str, Any]], status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Synthesise hero payload from snapshot dict.

    Returns dict with keys:
      sentence_key   — i18n key to use (gui_hero_sentence or gui_hero_no_data)
      sentence_params — placeholder map ({score, grade, high_risk}) for client templating
      score          — numeric maturity score (0.0 when unknown)
      score_grade    — letter grade or "?"
      high_risk_count — count of HIGH+CRITICAL findings
    """
    if not snapshot or not isinstance(snapshot, dict):
        return _empty_hero()

    kpis = snapshot.get("kpis") or []
    score: float = 0.0
    grade: str = "?"
    for kpi in kpis:
        if not isinstance(kpi, dict):
            continue
        label = str(kpi.get("label", "")).lower()
        if "maturity" not in label:
            continue
        value = str(kpi.get("value", ""))
        m = _MATURITY_PATTERN.match(value)
        if m:
            try:
                score = float(m.group(1))
            except (TypeError, ValueError):
                score = 0.0
            grade = m.group(2) or "?"
        break

    findings = snapshot.get("key_findings") or []
    high_risk = 0
    for f in findings:
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "")).upper().strip()
        if sev in _HIGH_RISK_SEVERITIES:
            high_risk += 1

    if not kpis and not findings:
        return _empty_hero()

    return {
        "sentence_key": "gui_hero_sentence",
        "sentence_params": {
            "score": str(int(score)) if score else "0",
            "grade": grade,
            "high_risk": str(high_risk),
        },
        "score": score,
        "score_grade": grade,
        "high_risk_count": high_risk,
    }
