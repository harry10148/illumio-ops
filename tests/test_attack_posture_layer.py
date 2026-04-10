import pandas as pd

from src.report.analysis.attack_posture import (
    build_app_display,
    build_app_env_key,
    make_posture_item,
    rank_posture_items,
    resolve_recommendation,
)


def test_app_env_key_normalization_edge_cases():
    assert build_app_env_key("ordering", "prod") == "ordering|prod"
    assert build_app_env_key("ordering", None) == "ordering|unlabeled"
    assert build_app_env_key("", "prod") == "unlabeled|prod"
    assert build_app_env_key(None, None) == "unlabeled|unlabeled"
    assert build_app_display("ordering", "prod") == "ordering (prod)"
    assert build_app_display(None, None) == "unlabeled (unlabeled)"


def test_posture_item_schema_contract():
    item = make_posture_item(
        scope="traffic_report",
        framework="microseg_attack",
        app="ordering",
        env="prod",
        finding_kind="boundary_breach",
        attack_stage="pivot",
        confidence="high",
        recommended_action_code="LOCK_BOUNDARY_PORTS",
        severity="HIGH",
        evidence={"connections": 42},
    )
    required = {
        "scope",
        "framework",
        "app_env_key",
        "app_display",
        "finding_kind",
        "attack_stage",
        "confidence",
        "recommended_action_code",
        "severity",
        "evidence",
    }
    assert required.issubset(item.keys())
    assert item["app_env_key"] == "ordering|prod"


def test_posture_item_ranking_is_deterministic():
    items = [
        make_posture_item(
            scope="traffic_report",
            framework="microseg_attack",
            app="a",
            env="prod",
            finding_kind="blind_spot",
            attack_stage="exposure",
            confidence="medium",
            recommended_action_code="ONBOARD_UNMANAGED",
            severity="MEDIUM",
            evidence={"connections": 50},
        ),
        make_posture_item(
            scope="traffic_report",
            framework="microseg_attack",
            app="b",
            env="prod",
            finding_kind="boundary_breach",
            attack_stage="pivot",
            confidence="high",
            recommended_action_code="LOCK_BOUNDARY_PORTS",
            severity="CRITICAL",
            evidence={"connections": 10},
        ),
        make_posture_item(
            scope="traffic_report",
            framework="microseg_attack",
            app="c",
            env="prod",
            finding_kind="enforcement_gap",
            attack_stage="control_plane",
            confidence="high",
            recommended_action_code="MOVE_TO_ENFORCEMENT",
            severity="HIGH",
            evidence={"connections": 100},
        ),
    ]
    ranked_once = rank_posture_items(items)
    ranked_twice = rank_posture_items(items)
    assert [x["app_env_key"] for x in ranked_once] == [x["app_env_key"] for x in ranked_twice]
    assert ranked_once[0]["severity"] == "CRITICAL"


def test_recommendation_template_resolution():
    txt = resolve_recommendation("LOCK_BOUNDARY_PORTS")
    assert isinstance(txt, str)
    assert txt
    assert resolve_recommendation("UNKNOWN_CODE").startswith("Review")

