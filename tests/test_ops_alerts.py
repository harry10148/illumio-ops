"""lag 與容量警告除了寫 log，也要送到告警通道（舊版只寫 log）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_capacity_warnings_dispatched_and_throttled():
    import src.scheduler.jobs as jobs
    jobs._capacity_alerted_at.clear()
    with patch("src.reporter.send_ops_alert", return_value=True) as send:
        jobs._notify_capacity_warnings(MagicMock(), ["SIEM dispatch backlog: 60000 pending rows (threshold 50000)"])
        # 數字變了仍是同一類，6 小時內不重送
        jobs._notify_capacity_warnings(MagicMock(), ["SIEM dispatch backlog: 61000 pending rows (threshold 50000)"])
        assert send.call_count == 1
        # 恢復後再發生要立即送
        jobs._notify_capacity_warnings(MagicMock(), [])
        jobs._notify_capacity_warnings(MagicMock(), ["SIEM dispatch backlog: 70000 pending rows (threshold 50000)"])
        assert send.call_count == 2
    jobs._capacity_alerted_at.clear()


def test_send_ops_alert_uses_health_alert_and_never_raises():
    from src import reporter as reporter_mod
    with patch.object(reporter_mod, "Reporter") as rep_cls:
        assert reporter_mod.send_ops_alert(MagicMock(), "ops_alert_capacity_title", "disk low") is True
        alert = rep_cls.return_value.add_health_alert.call_args.args[0]
        assert alert["details"] == "disk low" and alert["status"] == "warning"
        rep_cls.return_value.send_alerts.side_effect = RuntimeError("smtp down")
        assert reporter_mod.send_ops_alert(MagicMock(), "ops_alert_capacity_title", "x") is False


def test_lag_monitor_notifies_on_error():
    import src.pce_cache.lag_monitor as lm
    lm._last_alert_at.clear()
    cm = MagicMock()
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    with patch.object(lm, "check_cache_lag", return_value=[
            {"source": "events", "level": "error", "lag_seconds": 99999, "last_status": "ok"}]), \
         patch("src.gui._helpers._get_cache_engine"), \
         patch("src.reporter.send_ops_alert") as send:
        lm.run_cache_lag_monitor(cm)
    send.assert_called_once()
    lm._last_alert_at.clear()
