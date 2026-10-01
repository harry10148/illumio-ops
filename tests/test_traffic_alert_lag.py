"""settings.traffic_alert_lag_minutes：流量規則的評估視窗往前平移。

VEN 約每 10 分鐘才上報一次 flow；評估「最近 N 分鐘」時剛發生的短命 flow 多半
還沒進 PCE，等它進來時已落在之後所有視窗之外。
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock


def _ana(lag=None, interval=3600):
    from src.analyzer import Analyzer
    ana = Analyzer.__new__(Analyzer)
    ana.cm = MagicMock()
    ana.cm.config = {"settings": {} if lag is None else {"traffic_alert_lag_minutes": lag}}
    ana.cm.models.pce_cache.traffic_poll_interval_seconds = interval
    return ana


def test_default_lag_keeps_current_behaviour():
    now = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
    assert _ana()._evaluation_time(now) == now


def test_lag_shifts_evaluation_time():
    now = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
    assert _ana(lag=10)._evaluation_time(now) == now - dt.timedelta(minutes=10)


def test_lag_is_clamped():
    assert _ana(lag=999)._traffic_alert_lag() == 60
    assert _ana(lag="bad")._traffic_alert_lag() == 0


def test_warns_when_ingest_interval_exceeds_shortest_window(caplog):
    import logging
    ana = _ana(interval=3600)
    with caplog.at_level(logging.WARNING):
        ana._warn_if_ingest_slower_than_windows([{"threshold_window": 10}])
    assert any("traffic_poll_interval_seconds" in r.message for r in caplog.records)


def test_schema_accepts_lag_setting():
    from src.config_models import ConfigSchema
    m = ConfigSchema.model_validate({"settings": {"traffic_alert_lag_minutes": 10}})
    assert m.settings.traffic_alert_lag_minutes == 10
