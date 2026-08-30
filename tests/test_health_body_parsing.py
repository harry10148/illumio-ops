"""HTTP 200 from /api/v2/health does NOT mean healthy: parse body status."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, call

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
    cm.config["api"]["deployment_type"] = "on_prem"
    cm.config["rules"] = [{
        "id": 1, "name": "PCE Health", "type": "system",
        "filter_value": "pce_health", "threshold_count": 1, "threshold_type": "count",
    }]
    api = MagicMock()
    api.check_connectivity.return_value = (200, "")
    api.check_health.return_value = (200, '{"status": "warning"}')
    rep = MagicMock()
    ana = Analyzer(cm, api, rep)
    ana._run_health_check()
    rep.add_health_alert.assert_called_once()
    assert api.method_calls[:2] == [call.check_connectivity(), call.check_health()]
    alert = rep.add_health_alert.call_args[0][0]
    assert "warning" in alert["details"].lower()


def _mk_health_analyzer(tmp_path, monkeypatch, api, *, deployment_type="on_prem"):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.analyzer import Analyzer
    from src.config import ConfigManager
    from src.i18n import set_language
    cm = ConfigManager()
    # These assertions exercise the English message contract.  Do not let the
    # developer machine's persisted UI language change their meaning.
    cm.config.setdefault("settings", {})["language"] = "en"
    set_language("en")
    cm.config["api"]["deployment_type"] = deployment_type
    cm.config["rules"] = [{
        "id": 1, "name": "PCE Health", "type": "system",
        "filter_value": "pce_health", "threshold_count": 1, "threshold_type": "count",
    }]
    rep = MagicMock()
    return Analyzer(cm, api, rep), rep


def test_saas_connectivity_success_skips_on_prem_health_probes(tmp_path, monkeypatch):
    """SaaS 只以 authenticated /noop 判定健康，不得呼叫 appliance-only probes。"""
    api = MagicMock()
    api.check_connectivity.return_value = (204, "")
    ana, rep = _mk_health_analyzer(
        tmp_path, monkeypatch, api, deployment_type="saas")

    ana._run_health_check()

    rep.add_health_alert.assert_not_called()
    api.check_health.assert_not_called()
    api.check_node_available.assert_not_called()
    assert ana.state["pce_stats"]["health_status"] == "ok"
    assert ana.state["pce_stats"]["health_probe"] == "noop"
    assert ana.state["pce_stats"]["deployment_type"] == "saas"
    assert ana.state["pce_stats"]["health_category"] == "ok"


def test_enabled_health_check_runs_without_an_alert_rule(tmp_path, monkeypatch):
    """Health telemetry must not depend on configuring an alert rule."""
    api = MagicMock()
    api.check_connectivity.return_value = (200, "")
    api.check_health.return_value = (200, '{"status": "normal"}')
    api.check_node_available.return_value = (200, "")
    ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, api)
    ana.cm.config["settings"]["enable_health_check"] = True
    ana.cm.config["rules"] = []

    ana._run_health_check()

    assert ana.state["pce_stats"]["health_status"] == "ok"
    assert ana.state["pce_stats"]["health_category"] == "ok"
    assert ana.state["pce_stats"]["health_probe"] == "health"
    rep.add_health_alert.assert_not_called()


def test_disabled_automatic_health_check_does_not_probe(tmp_path, monkeypatch):
    api = MagicMock()
    ana, _rep = _mk_health_analyzer(tmp_path, monkeypatch, api)
    ana.cm.config["settings"]["enable_health_check"] = False

    ana._run_health_check()

    api.check_connectivity.assert_not_called()


def test_automatic_health_check_skips_a_recent_probe(tmp_path, monkeypatch):
    from src.events.poller import format_utc

    api = MagicMock()
    ana, _rep = _mk_health_analyzer(tmp_path, monkeypatch, api)
    ana.state["pce_stats"]["last_health_check"] = format_utc(
        datetime.datetime.now(datetime.timezone.utc)
    )

    ana._run_health_check()

    api.check_connectivity.assert_not_called()


def test_forced_health_check_bypasses_disable_and_recent_probe(tmp_path, monkeypatch):
    from src.events.poller import format_utc

    api = MagicMock()
    api.check_connectivity.return_value = (200, "")
    api.check_health.return_value = (200, '{"status": "normal"}')
    api.check_node_available.return_value = (200, "")
    ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, api)
    ana.cm.config["settings"]["enable_health_check"] = False
    ana.state["pce_stats"]["last_health_check"] = format_utc(
        datetime.datetime.now(datetime.timezone.utc)
    )

    ana._run_health_check(force=True, dispatch_alerts=False)

    api.check_connectivity.assert_called_once()
    assert ana.state["pce_stats"]["health_status"] == "ok"
    rep.add_health_alert.assert_not_called()


def test_saas_auth_failure_is_reachable_and_classified(tmp_path, monkeypatch):
    api = MagicMock()
    api.check_connectivity.return_value = (401, "unauthorized")
    ana, rep = _mk_health_analyzer(
        tmp_path, monkeypatch, api, deployment_type="saas")

    ana._run_health_check()

    alert = rep.add_health_alert.call_args[0][0]
    assert "auth_failed" in alert["details"]
    assert "unreachable" not in alert["details"].lower()
    api.check_health.assert_not_called()
    api.check_node_available.assert_not_called()
    assert ana.state["pce_stats"]["health_category"] == "auth_failed"


def test_saas_rate_limit_is_classified(tmp_path, monkeypatch):
    api = MagicMock()
    api.check_connectivity.return_value = (429, "too many requests")
    ana, rep = _mk_health_analyzer(
        tmp_path, monkeypatch, api, deployment_type="saas")

    ana._run_health_check()

    alert = rep.add_health_alert.call_args[0][0]
    assert "rate_limited" in alert["details"]
    api.check_health.assert_not_called()
    api.check_node_available.assert_not_called()
    assert ana.state["pce_stats"]["health_category"] == "rate_limited"


def test_connectivity_transport_error_stops_probes_and_counts_watchdog_failure(
        tmp_path, monkeypatch):
    api = MagicMock()
    api.check_connectivity.return_value = (0, "connectivity/noop probe failed")
    ana, rep = _mk_health_analyzer(
        tmp_path, monkeypatch, api, deployment_type="saas")

    ana._run_health_check()

    rep.add_health_alert.assert_called_once()
    api.check_health.assert_not_called()
    api.check_node_available.assert_not_called()
    assert ana.state["pce_stats"]["consecutive_failures"] == 1
    assert ana.state["pce_stats"]["deployment_type"] == "saas"
    assert ana.state["pce_stats"]["health_category"] == "transport_error"


def test_health_unsupported_2xx_is_not_recorded_as_ok(tmp_path, monkeypatch):
    """`/health` 僅接受 200；其他 2xx 必須維持 failure category。"""
    api = MagicMock()
    api.check_connectivity.return_value = (200, "")
    api.check_health.return_value = (202, "accepted but not health")
    ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, api)

    ana._run_health_check()

    rep.add_health_alert.assert_called_once()
    alert = rep.add_health_alert.call_args[0][0]
    assert "category=http_error" in alert["details"]
    assert ana.state["pce_stats"]["health_status"] == "error"
    assert ana.state["pce_stats"]["health_category"] == "http_error"


def test_node_unsupported_2xx_is_not_recorded_as_ok(tmp_path, monkeypatch):
    """`/node_available` 僅接受 200/202；204 不得留下 health_category=ok。"""
    api = MagicMock()
    api.check_connectivity.return_value = (200, "")
    api.check_health.return_value = (200, '{"status": "normal"}')
    api.check_node_available.return_value = (204, "")
    ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, api)

    ana._run_health_check()

    rep.add_health_alert.assert_called_once()
    assert ana.state["pce_stats"]["health_status"] == "error"
    assert ana.state["pce_stats"]["health_category"] == "http_error"


def test_node_unavailable_fires_health_alert(tmp_path, monkeypatch):
    """/health 過但 /node_available 回 404（官方判準：節點不可服務）→ 告警。"""
    api = MagicMock()
    api.check_connectivity.return_value = (200, "")
    api.check_health.return_value = (200, '{"status": "normal"}')
    api.check_node_available.return_value = (404, "")
    ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, api)
    ana._run_health_check()
    assert api.method_calls[:3] == [
        call.check_connectivity(), call.check_health(), call.check_node_available()]
    rep.add_health_alert.assert_called_once()
    alert = rep.add_health_alert.call_args[0][0]
    assert "node_available" in alert["details"]


def test_node_available_200_and_202_both_healthy(tmp_path, monkeypatch):
    """lab 真機回 200（SLB 文件）、Supercluster 文件定義 202——皆健康。"""
    for code in (200, 202):
        api = MagicMock()
        api.check_connectivity.return_value = (200, "")
        api.check_health.return_value = (200, '{"status": "normal"}')
        api.check_node_available.return_value = (code, "")
        ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, api)
        ana._run_health_check()
        rep.add_health_alert.assert_not_called()


def test_api_without_node_available_probe_is_skipped(tmp_path, monkeypatch):
    """Protocol stub 沒有 check_node_available → 跳過探測，不炸不告警。"""
    class _Api:
        def check_connectivity(self):
            return 200, ""

        def check_health(self):
            return 200, '{"status": "normal"}'
    ana, rep = _mk_health_analyzer(tmp_path, monkeypatch, _Api())
    ana._run_health_check()
    rep.add_health_alert.assert_not_called()


def test_saas_system_rule_simulator_uses_connectivity_probe(tmp_path, monkeypatch, capsys):
    api = MagicMock()
    api.check_connectivity.return_value = (200, "")
    api.fetch_events.return_value = []
    api.execute_traffic_query_stream.return_value = []
    ana, _rep = _mk_health_analyzer(
        tmp_path, monkeypatch, api, deployment_type="saas")

    ana.run_debug_mode(mins=1, pd_sel=3, interactive=False)

    assert "PASS" in capsys.readouterr().out
    api.check_connectivity.assert_called_once()
    api.check_health.assert_not_called()


def test_on_prem_system_rule_simulator_checks_node_availability(
        tmp_path, monkeypatch, capsys):
    api = MagicMock()
    api.check_connectivity.return_value = (200, "")
    api.check_health.return_value = (200, '{"status": "normal"}')
    api.check_node_available.return_value = (404, "")
    api.fetch_events.return_value = []
    api.execute_traffic_query_stream.return_value = []
    ana, _rep = _mk_health_analyzer(tmp_path, monkeypatch, api)

    ana.run_debug_mode(mins=1, pd_sel=3, interactive=False)

    assert "WOULD TRIGGER" in capsys.readouterr().out
    assert api.method_calls[-3:] == [
        call.check_connectivity(), call.check_health(), call.check_node_available()]
