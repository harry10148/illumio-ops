from unittest.mock import MagicMock


def _make_cm():
    cm = MagicMock()
    cm.config = {}                       # 真 dict，讓 .get(...) 走預設
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.events_poll_interval_seconds = 300
    cm.models.pce_cache.traffic_poll_interval_seconds = 3600
    cm.models.siem.enabled = False       # 跳過 siem 註冊，聚焦 cache 區塊
    return cm


def test_event_ingest_isolated_from_cache_batch_writers():
    from src.scheduler import build_scheduler
    sched = build_scheduler(_make_cm())
    sched.start(paused=True)             # flush pending jobs 到 jobstore，不實際跑
    try:
        assert sched.get_job("pce_cache_ingest_events").executor == "event_reader"
        for jid in ("pce_cache_ingest_traffic", "pce_cache_aggregate",
                    "pce_cache_retention"):
            assert sched.get_job(jid).executor == "cache_writer", jid
        for jid in ("cache_lag_monitor", "monitor_cycle"):
            assert sched.get_job(jid).executor == "default", jid
        assert "event_reader" in sched._executors
        assert sched._executors["event_reader"]._pool._max_workers == 1
        assert "cache_writer" in sched._executors
        assert sched._executors["cache_writer"]._pool._max_workers == 1
    finally:
        sched.shutdown(wait=False)
