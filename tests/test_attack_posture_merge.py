"""攻擊態勢依主體合併與量化文字（spec B2）。"""
from src.report.analysis.attack_posture import make_posture_item, summarize_attack_posture


def _items():
    return [
        make_posture_item(scope="app", framework="readiness", app="web", env="prod",
                          finding_kind="blind_spot", attack_stage="exposure",
                          confidence="high", recommended_action_code="MOVE_TO_ENFORCEMENT",
                          severity="MEDIUM", evidence={"flow_count": 120, "allowed_ratio": 0.9}),
        make_posture_item(scope="app", framework="readiness", app="web", env="prod",
                          finding_kind="enforcement_gap", attack_stage="containment",
                          confidence="high", recommended_action_code="MOVE_TO_ENFORCEMENT",
                          severity="HIGH", evidence={"flow_count": 300}),
        make_posture_item(scope="app", framework="lateral", app="db", env="prod",
                          finding_kind="boundary_breach", attack_stage="initial_access",
                          confidence="high", recommended_action_code="LOCK_BOUNDARY_PORTS",
                          severity="HIGH", evidence={"reachability_count": 8}),
    ]


def test_same_app_merges_to_one_row():
    out = summarize_attack_posture(_items(), lang="en")
    blind = out["blind_spots"]
    # web(prod) 的 blind_spot + enforcement_gap 併成一列
    assert len(blind) == 1
    row = blind[0]
    assert row["severity"] == "HIGH"            # 取最高
    assert "web (prod)" in row["finding"]
    assert "300" in row["finding"]              # 數值 evidence 取大者且入文字


def test_findings_are_quantified():
    out = summarize_attack_posture(_items(), lang="en")
    bb = out["boundary_breaches"][0]
    assert "8" in bb["finding"]


def test_action_matrix_enriched():
    out = summarize_attack_posture(_items(), lang="en")
    am = {a["action_code"]: a for a in out["action_matrix"]}
    assert am["MOVE_TO_ENFORCEMENT"]["severity"] == "HIGH"
    assert am["MOVE_TO_ENFORCEMENT"]["count"] == 2
    assert "web (prod)" in am["MOVE_TO_ENFORCEMENT"]["apps"]
    assert am["MOVE_TO_ENFORCEMENT"]["flow_total"] == 420  # 120 + 300
