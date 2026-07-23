"""HTTP 200 from /api/v2/health does NOT mean healthy: parse body status."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.api_client import health_status_from_body


def test_parses_top_level_status_dict():
    assert health_status_from_body('{"status": "normal"}') == "normal"
    assert health_status_from_body('{"status": "WARNING"}') == "warning"


def test_parses_node_list_and_picks_worst():
    body = '[{"status": "normal"}, {"status": "critical"}, {"status": "warning"}]'
    assert health_status_from_body(body) == "critical"


def test_unparseable_body_returns_empty():
    assert health_status_from_body("not json") == ""
    assert health_status_from_body("") == ""
    assert health_status_from_body("[1, 2]") == ""


def test_degraded_200_fires_health_alert(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.analyzer import Analyzer
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = [{
        "id": 1, "name": "PCE Health", "type": "system",
        "filter_value": "pce_health", "threshold_count": 1, "threshold_type": "count",
    }]
    api = MagicMock()
    api.check_health.return_value = (200, '{"status": "warning"}')
    rep = MagicMock()
    ana = Analyzer(cm, api, rep)
    ana._run_health_check()
    rep.add_health_alert.assert_called_once()
    alert = rep.add_health_alert.call_args[0][0]
    assert "warning" in alert["details"].lower()


def _mk_health_analyzer(tmp_path, monkeypatch, api):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.analyzer import Analyzer
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = [{
        "id": 1, "name": "PCE Health", "type": "system",
        "filter_value": "pce_health", "threshold_count": 1, "threshold_type": "count",
    }]
    rep = MagicMock()
    return Analyzer(cm, api, rep), rep


def test_node_unavailable_fires_health_alert(tmp_path, monkeypatch):
    """/health 過但 /node_available 回 404（官方判準：節點不可服務）→ 告警。"""
    api = MagicMock()
    api.check_health.return_value = (200, '{"status": "normal"}')
    api.check_node_available.return_value = (404, "")
    ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, api)
    ana._run_health_check()
    rep.add_health_alert.assert_called_once()
    alert = rep.add_health_alert.call_args[0][0]
    assert "node_available" in alert["details"]


def test_node_available_200_and_202_both_healthy(tmp_path, monkeypatch):
    """lab 真機回 200（SLB 文件）、Supercluster 文件定義 202——皆健康。"""
    for code in (200, 202):
        api = MagicMock()
        api.check_health.return_value = (200, '{"status": "normal"}')
        api.check_node_available.return_value = (code, "")
        ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, api)
        ana._run_health_check()
        rep.add_health_alert.assert_not_called()


def test_api_without_node_available_probe_is_skipped(tmp_path, monkeypatch):
    """Protocol stub 沒有 check_node_available → 跳過探測，不炸不告警。"""
    class _Api:
        def check_health(self):
            return 200, '{"status": "normal"}'
    ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, _Api())
    ana._run_health_check()
    rep.add_health_alert.assert_not_called()
