def test_status_alerts_flags_error_status():
    from src.pce_cache.lag_monitor import status_alerts
    results = [
        {"source": "traffic", "level": "ok", "last_status": "error",
         "last_error": "HTTPSConnectionPool timeout"},
        {"source": "events", "level": "ok", "last_status": "ok", "last_error": None},
    ]
    msgs = status_alerts(results)
    assert len(msgs) == 1
    assert "traffic" in msgs[0]


def test_status_alerts_empty_when_all_ok():
    from src.pce_cache.lag_monitor import status_alerts
    assert status_alerts([{"source": "traffic", "last_status": "ok"}]) == []
