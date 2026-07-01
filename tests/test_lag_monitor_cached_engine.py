from unittest.mock import MagicMock, patch


def test_lag_monitor_uses_cached_engine_and_skips_per_tick_ddl(tmp_path):
    from src.pce_cache import lag_monitor
    cm = MagicMock()
    cm.models.pce_cache.db_path = str(tmp_path / "c.sqlite")
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600

    with patch("src.gui._helpers._get_cache_engine") as mock_ge, \
         patch("src.pce_cache.schema.init_schema") as mock_init, \
         patch("src.pce_cache.lag_monitor.check_cache_lag", return_value=[]) as mock_check:
        lag_monitor.run_cache_lag_monitor(cm)
        lag_monitor.run_cache_lag_monitor(cm)

    assert mock_ge.call_count == 2      # 每 tick 取快取 engine（cache hit，便宜）
    assert mock_init.call_count == 0    # lag_monitor 自己不再跑 init_schema DDL
    assert mock_check.call_count == 2
