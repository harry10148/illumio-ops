"""Change Impact: compare current report's KPIs to the previous snapshot."""
from __future__ import annotations

from typing import Optional

# 方向名單對齊快照實際 key（原名單 key 全庫零生產者，屬過期殘留）。
# staged_coverage_pct 語意雙向（staged→enforced 轉換使其下降是好事、
# 新缺口使其上升是壞事）——刻意不列入任一名單，維持 neutral。
LOWER_BETTER = ("true_gap_pct", "risk_flows_total")
HIGHER_BETTER = ("enforced_coverage_pct", "maturity_score")

_POSTURE_KEYS = ('enforced_coverage_pct', 'staged_coverage_pct', 'true_gap_pct',
                 'maturity_score', 'maturity_grade', 'maturity_dimensions',
                 'enforcement_mode_distribution')


def collect_current_kpis(module_results: dict) -> dict:
    """自 module_results 收集 Change Impact／快照共用的 posture KPI dict。

    mod12 的顯示用 'kpis' 是 list；可比較的 posture 值住在 mod12 頂層 key。
    此函式是快照寫入端（report_generator）與章節渲染端（html_exporter）的
    單一事實來源——兩端 key 集合由此保持一致。
    """
    mod12 = module_results.get('mod12', {}) or {}
    kpis = {k: mod12[k] for k in _POSTURE_KEYS if k in mod12}
    for mid in ('mod04', 'mod15', 'mod12'):
        m = module_results.get(mid, {})
        if isinstance(m, dict) and 'risk_flows_total' in m and 'risk_flows_total' not in kpis:
            kpis['risk_flows_total'] = m['risk_flows_total']
    return kpis


def compare(*, current_kpis: dict, previous: Optional[dict]) -> dict:
    if previous is None:
        return {"skipped": True, "reason": "no_previous_snapshot"}
    prev_kpis = previous.get("kpis", {})
    deltas = {}
    improved_count = 0
    regressed_count = 0
    for k, current in current_kpis.items():
        if not isinstance(current, (int, float)):
            continue
        prev = prev_kpis.get(k)
        if not isinstance(prev, (int, float)):
            continue
        delta = current - prev
        direction = _direction(k, delta)
        if direction == "improved":
            improved_count += 1
        elif direction == "regressed":
            regressed_count += 1
        deltas[k] = {"current": current, "previous": prev, "delta": delta, "direction": direction}
    verdict = _verdict(improved_count, regressed_count)
    return {
        "deltas": deltas,
        "improved_count": improved_count,
        "regressed_count": regressed_count,
        "overall_verdict": verdict,
        "previous_snapshot_at": previous.get("generated_at"),
    }


def _direction(kpi: str, delta: float) -> str:
    if delta == 0:
        return "unchanged"
    if kpi in LOWER_BETTER:
        return "improved" if delta < 0 else "regressed"
    if kpi in HIGHER_BETTER:
        return "improved" if delta > 0 else "regressed"
    return "neutral"


def _verdict(improved, regressed):
    if improved > 0 and regressed == 0:
        return "improved"
    if regressed > 0 and improved == 0:
        return "regressed"
    if improved > 0 and regressed > 0:
        return "mixed"
    return "unchanged"  # pragma: no cover
