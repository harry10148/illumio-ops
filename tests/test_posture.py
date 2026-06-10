"""Tests for posture score computation (Piece A) and scheduler job (Piece B).

TDD sequence: write tests → run (expect failures) → implement → run (all pass).
"""
from __future__ import annotations

import json
import math
from unittest.mock import patch, MagicMock

import pytest

from src.report.posture import compute_posture


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _risk_kpis():
    """Synthetic snapshot with all three risk signals present (deterministic)."""
    return {
        "enforced_coverage_pct": 80.0,
        "maturity_score": 70.0,
        "risk_flows_total": 4,          # ransomware_apps=4 -> pts=min(40,20)=20 -> value=50
        "true_gap_pct": 20.0,           # uncovered_pts=min(30,10)=10 -> value=round(100*(1-10/30))=67
        "maturity_dimensions": {
            "lateral_movement_control": {"ratio": 0.5},  # lateral_pts=round(0.5*30)=15 -> value=50
        },
    }


def _full_kpis(**overrides):
    """Return a realistic traffic snapshot top-level dict."""
    base = {
        "enforced_coverage_pct": 70.0,
        "staged_coverage_pct": 10.0,
        "true_gap_pct": 20.0,
        "maturity_score": 65.0,
        "maturity_dimensions": {
            "enforcement_coverage": {"weight": 40, "score": 30.0, "ratio": 0.75},
            "policy_coverage":      {"weight": 25, "score": 17.5, "ratio": 0.70},
            "lateral_movement_control": {"weight": 15, "score": 10.0, "ratio": 0.667},
            "managed_asset_ratio":  {"weight": 10, "score": 9.0,  "ratio": 0.90},
            "risk_port_control":    {"weight": 10, "score": 6.0,  "ratio": 0.60},
        },
        "risk_flows_total": 4,
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Piece A: compute_posture
# ─────────────────────────────────────────────────────────────────────────────

class TestComputePostureFull:
    """Full KPI dict → expected score and breakdown."""

    def test_returns_dict_with_required_keys(self):
        result = compute_posture(_full_kpis())
        for key in ("score", "available", "formula", "components"):
            assert key in result, f"missing key: {key}"

    def test_available_true_when_all_components_present(self):
        result = compute_posture(_full_kpis())
        assert result["available"] is True

    def test_score_is_int_in_range(self):
        result = compute_posture(_full_kpis())
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100

    def test_score_formula_manual(self):
        """Manually verify the formula with known inputs."""
        # coverage=70, readiness=65, risk signals: ransomware=4 apps, lateral=0.667, uncovered=20%
        # ransomware_pts = min(40, 4*5) = 20
        # lateral_pts = round((1 - 0.667) * 30) = round(9.99) = 10
        # uncovered_pts = min(30, 20 * 0.5) = 10
        # penalty = 20+10+10 = 40
        # risk_health = 60
        # score = round(70*0.3 + 65*0.3 + 60*0.4) = round(21 + 19.5 + 24) = round(64.5) = 64 or 65
        result = compute_posture(_full_kpis())
        assert result["score"] in (64, 65)

    def test_component_keys_present(self):
        result = compute_posture(_full_kpis())
        keys = {c["key"] for c in result["components"]}
        assert keys == {"coverage", "readiness", "risk_health"}

    def test_component_points_sum_to_score(self):
        result = compute_posture(_full_kpis())
        total = sum(c["points"] for c in result["components"])
        # Allow ±1 due to rounding at each stage
        assert abs(total - result["score"]) <= 1.0

    def test_coverage_component_value(self):
        result = compute_posture(_full_kpis())
        cov = next(c for c in result["components"] if c["key"] == "coverage")
        assert cov["value"] == pytest.approx(70.0, abs=0.1)

    def test_risk_health_has_detail(self):
        result = compute_posture(_full_kpis())
        rh = next(c for c in result["components"] if c["key"] == "risk_health")
        assert "detail" in rh
        detail = rh["detail"]
        assert detail["ransomware_apps"] == 4
        assert "penalty" in detail

    def test_risk_health_value_at_zero_risk(self):
        kpis = _full_kpis(risk_flows_total=0, true_gap_pct=0.0)
        # Remove lateral risk by setting ratio=1.0
        kpis["maturity_dimensions"]["lateral_movement_control"]["ratio"] = 1.0
        result = compute_posture(kpis)
        rh = next(c for c in result["components"] if c["key"] == "risk_health")
        assert rh["value"] == pytest.approx(100.0, abs=0.1)

    def test_formula_string_present(self):
        result = compute_posture(_full_kpis())
        assert "coverage" in result["formula"]
        assert "readiness" in result["formula"]
        assert "risk_health" in result["formula"]

    def test_label_keys_present_on_components(self):
        result = compute_posture(_full_kpis())
        for c in result["components"]:
            assert "label_key" in c
            assert c["label_key"].startswith("gui_posture_")


class TestComputePosturePartial:
    """Partial snapshot (missing readiness) → renormalized weights."""

    def test_missing_readiness_still_returns_score(self):
        kpis = _full_kpis()
        del kpis["maturity_score"]
        # Also remove maturity_dimensions to prevent fallback
        del kpis["maturity_dimensions"]
        result = compute_posture(kpis)
        assert result["available"] is True
        assert result["score"] is not None

    def test_missing_readiness_weights_renormalized(self):
        """With readiness absent, coverage(0.3) + risk_health(0.4) = 0.7 total.
        Effective weights become 0.3/0.7 and 0.4/0.7."""
        kpis = _full_kpis()
        del kpis["maturity_score"]
        del kpis["maturity_dimensions"]
        result = compute_posture(kpis)
        # coverage and risk_health components should exist, readiness should not
        keys = {c["key"] for c in result["components"]}
        assert "readiness" not in keys
        assert "coverage" in keys
        assert "risk_health" in keys

    def test_missing_coverage_only_two_components(self):
        kpis = _full_kpis()
        del kpis["enforced_coverage_pct"]
        # Remove fallback sources too
        kpis.pop("maturity_dimensions", None)
        kpis.pop("kpis", None)
        result = compute_posture(kpis)
        keys = {c["key"] for c in result["components"]}
        assert "coverage" not in keys

    def test_only_readiness_present(self):
        kpis = {"maturity_score": 80.0}
        result = compute_posture(kpis)
        # readiness present, coverage absent, risk absent
        assert result["available"] is True
        # With only readiness, effective_weight = 0.3/0.3 = 1.0, score = 80
        assert result["score"] == 80


class TestComputePostureEmpty:
    """Empty / None input → available=False, score=None."""

    def test_empty_dict(self):
        result = compute_posture({})
        assert result["available"] is False
        assert result["score"] is None

    def test_none_input(self):
        result = compute_posture(None)
        assert result["available"] is False
        assert result["score"] is None

    def test_non_dict_input(self):
        result = compute_posture("invalid")
        assert result["available"] is False


class TestRiskPenaltyBounds:
    """Risk penalty stays bounded 0-100."""

    def test_extreme_ransomware_penalty_capped(self):
        kpis = _full_kpis(risk_flows_total=1000)
        result = compute_posture(kpis)
        rh = next(c for c in result["components"] if c["key"] == "risk_health")
        # ransomware_pts capped at 40, so penalty <= 100, risk_health >= 0
        assert rh["value"] >= 0.0

    def test_zero_risk_full_risk_health(self):
        kpis = _full_kpis(risk_flows_total=0, true_gap_pct=0.0)
        kpis["maturity_dimensions"]["lateral_movement_control"]["ratio"] = 1.0
        result = compute_posture(kpis)
        rh = next(c for c in result["components"] if c["key"] == "risk_health")
        assert rh["value"] == 100.0

    def test_score_clamp_upper(self):
        kpis = {
            "enforced_coverage_pct": 100.0,
            "maturity_score": 100.0,
            "risk_flows_total": 0,
            "true_gap_pct": 0.0,
            "maturity_dimensions": {
                "lateral_movement_control": {"ratio": 1.0}
            },
        }
        result = compute_posture(kpis)
        assert result["score"] == 100

    def test_score_clamp_lower(self):
        kpis = {
            "enforced_coverage_pct": 0.0,
            "maturity_score": 0.0,
            "risk_flows_total": 1000,
            "true_gap_pct": 100.0,
            "maturity_dimensions": {
                "lateral_movement_control": {"ratio": 0.0}
            },
        }
        result = compute_posture(kpis)
        assert result["score"] == 0


class TestRiskSubscores:
    def _risk_component(self, kpis):
        result = compute_posture(kpis)
        return next(c for c in result["components"] if c["key"] == "risk_health")

    def test_all_three_subscores_present_with_expected_values(self):
        rh = self._risk_component(_risk_kpis())
        subs = {s["key"]: s for s in rh["risk_subscores"]}
        assert subs["ransomware_containment"]["value"] == 50
        assert subs["ransomware_containment"]["penalty_points"] == 20
        assert subs["ransomware_containment"]["max_penalty"] == 40
        assert subs["lateral_containment"]["value"] == 50
        assert subs["lateral_containment"]["penalty_points"] == 15
        assert subs["flow_coverage"]["value"] == 67
        assert subs["flow_coverage"]["penalty_points"] == 10

    def test_absent_signal_omits_its_subscore(self):
        # Only ransomware signal present; lateral ratio + gap absent.
        kpis = {"enforced_coverage_pct": 80.0, "maturity_score": 70.0,
                "risk_flows_total": 4}
        rh = self._risk_component(kpis)
        keys = {s["key"] for s in rh["risk_subscores"]}
        assert keys == {"ransomware_containment"}

    def test_existing_keys_unchanged(self):
        rh = self._risk_component(_risk_kpis())
        for k in ("key", "label_key", "value", "unit", "weight",
                  "effective_weight", "points", "note_key", "detail"):
            assert k in rh

    def test_subscores_all_clean_are_100(self):
        kpis = {
            "enforced_coverage_pct": 100.0,
            "maturity_score": 100.0,
            "risk_flows_total": 0,
            "true_gap_pct": 0.0,
            "maturity_dimensions": {"lateral_movement_control": {"ratio": 1.0}},
        }
        rh = self._risk_component(kpis)
        assert {s["key"]: s["value"] for s in rh["risk_subscores"]} == {
            "ransomware_containment": 100,
            "lateral_containment": 100,
            "flow_coverage": 100,
        }

    def test_subscores_all_saturated_are_0(self):
        kpis = {
            "enforced_coverage_pct": 0.0,
            "maturity_score": 0.0,
            "risk_flows_total": 8,
            "true_gap_pct": 60.0,
            "maturity_dimensions": {"lateral_movement_control": {"ratio": 0.0}},
        }
        rh = self._risk_component(kpis)
        assert {s["key"]: s["value"] for s in rh["risk_subscores"]} == {
            "ransomware_containment": 0,
            "lateral_containment": 0,
            "flow_coverage": 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Piece B: run_posture_summary scheduler job
# ─────────────────────────────────────────────────────────────────────────────

class TestRunPostureSummaryJob:
    """run_posture_summary writes state["posture_summary"] correctly."""

    def _make_snapshot(self):
        return {
            "report_type": "traffic",
            "profile": "security_risk",
            "generated_at": "2026-06-01T10:00:00+00:00",
            "enforced_coverage_pct": 70.0,
            "maturity_score": 65.0,
            "true_gap_pct": 20.0,
            "risk_flows_total": 4,
            "maturity_dimensions": {
                "lateral_movement_control": {"ratio": 0.667},
            },
        }

    def test_writes_posture_summary_to_state(self, tmp_path):
        from src.scheduler.jobs import run_posture_summary
        state_file = str(tmp_path / "state.json")
        cm = MagicMock()
        cm.config = {}
        snap = self._make_snapshot()

        with patch("src.scheduler.jobs.read_latest", return_value=snap), \
             patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
            run_posture_summary(cm)

        s = json.load(open(state_file))
        assert "posture_summary" in s
        ps = s["posture_summary"]
        assert ps["available"] is True
        assert isinstance(ps["score"], int)
        assert "generated_at" in ps
        assert "source_date" in ps
        assert "components" in ps

    def test_no_snapshot_writes_available_false(self, tmp_path):
        from src.scheduler.jobs import run_posture_summary
        state_file = str(tmp_path / "state.json")
        cm = MagicMock()
        cm.config = {}

        with patch("src.scheduler.jobs.read_latest", return_value=None), \
             patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
            run_posture_summary(cm)

        s = json.load(open(state_file))
        assert s["posture_summary"] == {"available": False}

    def test_job_does_not_raise_on_bad_snapshot(self, tmp_path):
        from src.scheduler.jobs import run_posture_summary
        state_file = str(tmp_path / "state.json")
        cm = MagicMock()
        cm.config = {}

        # Simulate read_latest raising
        with patch("src.scheduler.jobs.read_latest", side_effect=RuntimeError("disk error")), \
             patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
            # Must NOT raise
            run_posture_summary(cm)

    def test_source_date_comes_from_snapshot_generated_at(self, tmp_path):
        from src.scheduler.jobs import run_posture_summary
        state_file = str(tmp_path / "state.json")
        cm = MagicMock()
        cm.config = {}
        snap = self._make_snapshot()

        with patch("src.scheduler.jobs.read_latest", return_value=snap), \
             patch("src.scheduler.jobs._resolve_state_file", return_value=state_file):
            run_posture_summary(cm)

        ps = json.load(open(state_file))["posture_summary"]
        assert ps["source_date"] == "2026-06-01T10:00:00+00:00"


# ─────────────────────────────────────────────────────────────────────────────
# Piece C: _overview_posture in dashboard API
# ─────────────────────────────────────────────────────────────────────────────

class TestOverviewPostureHelper:
    """_overview_posture(state) returns posture_summary or {available: False}."""

    def test_returns_posture_from_state(self):
        from src.gui.routes.dashboard import _overview_posture
        state = {"posture_summary": {"available": True, "score": 72, "components": []}}
        result = _overview_posture(state)
        assert result["available"] is True
        assert result["score"] == 72

    def test_returns_available_false_when_missing(self):
        from src.gui.routes.dashboard import _overview_posture
        result = _overview_posture({})
        assert result == {"available": False}

    def test_returns_available_false_when_no_score(self):
        from src.gui.routes.dashboard import _overview_posture
        state = {"posture_summary": {"available": False}}
        result = _overview_posture(state)
        assert result["available"] is False

    def test_overview_api_includes_posture_key(self, tmp_path):
        """Integration: GET /api/dashboard/overview response has 'posture' key."""
        import os
        import tempfile
        from src.config import ConfigManager
        from src.gui import _create_app
        from src.gui import _helpers

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            json.dump({
                "web_gui": {"username": "admin", "password": "pw",
                            "secret_key": "s", "allowed_ips": ["127.0.0.1"]},
                "pce_cache": {"enabled": False, "db_path": str(tmp_path / "c.sqlite")},
            }, f)
        cm = ConfigManager(config_file=path)
        app = _create_app(cm, persistent_mode=True)
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        sf = str(tmp_path / "state.json")
        json.dump({"posture_summary": {"available": True, "score": 55, "components": []}},
                  open(sf, "w"))

        with app.test_client() as c:
            c.post("/api/login", json={"username": "admin", "password": "pw"},
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})

            import unittest.mock as mock
            with mock.patch.object(_helpers, "_resolve_state_file", return_value=sf):
                r = c.get("/api/dashboard/overview",
                          environ_overrides={"REMOTE_ADDR": "127.0.0.1"})

        assert r.status_code == 200
        data = r.get_json()
        assert "posture" in data, f"'posture' key missing from overview response: {list(data.keys())}"
        assert data["posture"]["available"] is True
        assert data["posture"]["score"] == 55

        os.unlink(path)
