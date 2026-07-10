"""AL-8 overflow meta-alert gap fix: in pce_cache.enabled=true deployments the
legacy event-polling overflow path (event_overflow) never runs (Analyzer
takes the cache-subscriber branch), and the capacity-hardening Task 1
bisection floor in TrafficIngestor only ever logged a WARNING — no reporter
alert existed for it (see .superpowers/sdd/live-verification-report.md,
finding #7).

This module tests the fix:
1. TrafficIngestor exposes `last_run_overflow` when the 1-minute bisection
   floor is hit without resolving the cap (data in that window may be
   incomplete).
2. run_traffic_ingest (scheduler job) persists that into state.json under
   `traffic_overflow`, shaped like the legacy `event_overflow` key.
3. Analyzer._maybe_alert_overflow is generalized to check both
   `event_overflow` and `traffic_overflow`, each with its own cooldown key
   and distinct alert text, and is now called unconditionally every cycle
   (not only on the legacy no-cache-subscriber branch), so the cache-ingest
   path is actually covered.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest


# ─── 1. TrafficIngestor.last_run_overflow ──────────────────────────────────

@pytest.fixture
def session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


class AlwaysFullApi:
    def __init__(self):
        self.calls = 0

    def get_traffic_flows_async(self, max_results=200000, **kw):
        self.calls += 1
        return [{"src_ip": f"10.0.0.{i}", "dst_ip": "10.0.0.1", "port": 443,
                  "protocol": "tcp", "action": "blocked", "flow_count": 1,
                  "bytes_in": 1, "bytes_out": 1,
                  "first_detected": "2026-07-10T00:00:00+00:00",
                  "last_detected": "2026-07-10T00:00:01+00:00"}
                 for i in range(max_results)]


def test_traffic_ingestor_sets_last_run_overflow_on_floor_hit(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ing = TrafficIngestor(api=AlwaysFullApi(), session_factory=session_factory,
                          watermark=WatermarkStore(session_factory), max_results=2)
    ing.run_once()
    assert ing.last_run_overflow is not None
    assert ing.last_run_overflow["max_results"] == 2
    assert ing.last_run_overflow["raw_count"] > 0
    assert "query_since" in ing.last_run_overflow
    assert "query_until" in ing.last_run_overflow


def test_traffic_ingestor_last_run_overflow_none_when_no_cap_hit(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    class SmallApi:
        def get_traffic_flows_async(self, max_results=200000, **kw):
            return [{"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443,
                      "protocol": "tcp", "action": "blocked", "flow_count": 1,
                      "bytes_in": 1, "bytes_out": 1,
                      "first_detected": "2026-07-10T00:00:00+00:00",
                      "last_detected": "2026-07-10T00:00:01+00:00"}]

    ing = TrafficIngestor(api=SmallApi(), session_factory=session_factory,
                          watermark=WatermarkStore(session_factory), max_results=5)
    ing.run_once()
    assert ing.last_run_overflow is None


# ─── 2. run_traffic_ingest job persists traffic_overflow into state.json ──

def _cm(tmp_path):
    cm = MagicMock()
    cfg = cm.models.pce_cache
    cfg.db_path = str(tmp_path / "cache.sqlite")
    cfg.traffic_sampling.max_rows_per_batch = 200000
    cm.models.siem.enabled = False
    return cm


def _state_file(tmp_path):
    return str(tmp_path / "logs" / "state.json")


@pytest.fixture(autouse=True)
def _patch_state_file(tmp_path, monkeypatch):
    import src.scheduler.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "_resolve_state_file", lambda: _state_file(tmp_path))
    return tmp_path


def _load_state(tmp_path):
    from src.state_store import load_state_file
    return load_state_file(_state_file(tmp_path))


def test_run_traffic_ingest_writes_traffic_overflow_state(tmp_path):
    from src.scheduler.jobs import run_traffic_ingest

    cm = _cm(tmp_path)
    overflow = {"detected_at": "2026-07-10T00:00:00+00:00",
                "query_since": "2026-07-10T00:00:00+00:00",
                "query_until": "2026-07-10T00:01:00+00:00",
                "raw_count": 200000, "max_results": 200000, "window_count": 1}
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.scheduler.jobs.ApiClient") as mock_api, \
         patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
        mock_api.return_value.__enter__.return_value = MagicMock()
        wm = mock_wm_cls.return_value
        wm.get.return_value = MagicMock(last_status="ok", last_error=None)
        with patch("src.pce_cache.ingestor_traffic.TrafficIngestor") as mock_ing:
            mock_ing.return_value.run_once.return_value = 200000
            mock_ing.return_value.last_run_overflow = overflow
            run_traffic_ingest(cm)

    state = _load_state(tmp_path)
    assert state["traffic_overflow"] == overflow


def test_run_traffic_ingest_clears_traffic_overflow_when_resolved(tmp_path):
    from src.scheduler.jobs import run_traffic_ingest
    from src.state_store import update_state_file

    update_state_file(_state_file(tmp_path), lambda s: {
        **s, "traffic_overflow": {"raw_count": 5, "max_results": 5}
    })

    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.scheduler.jobs.ApiClient") as mock_api, \
         patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
        mock_api.return_value.__enter__.return_value = MagicMock()
        wm = mock_wm_cls.return_value
        wm.get.return_value = MagicMock(last_status="ok", last_error=None)
        with patch("src.pce_cache.ingestor_traffic.TrafficIngestor") as mock_ing:
            mock_ing.return_value.run_once.return_value = 3
            mock_ing.return_value.last_run_overflow = None
            run_traffic_ingest(cm)

    state = _load_state(tmp_path)
    assert state["traffic_overflow"] == {}


def test_run_traffic_ingest_does_not_clobber_overflow_on_fetch_failure(tmp_path):
    """A failed fetch tells us nothing new about overflow — must not silently
    clear a real, still-unresolved overflow episode just because this
    particular tick couldn't reach the PCE at all."""
    from src.scheduler.jobs import run_traffic_ingest
    from src.state_store import update_state_file

    stale_overflow = {"raw_count": 5, "max_results": 5}
    update_state_file(_state_file(tmp_path), lambda s: {
        **s, "traffic_overflow": stale_overflow
    })

    cm = _cm(tmp_path)
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.scheduler.jobs.ApiClient") as mock_api, \
         patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
        mock_api.return_value.__enter__.return_value = MagicMock()
        wm = mock_wm_cls.return_value
        wm.get.return_value = MagicMock(last_status="error", last_error="PCE down")
        with patch("src.pce_cache.ingestor_traffic.TrafficIngestor") as mock_ing:
            mock_ing.return_value.run_once.return_value = 0
            mock_ing.return_value.last_run_overflow = None
            run_traffic_ingest(cm)

    state = _load_state(tmp_path)
    assert state["traffic_overflow"] == stale_overflow


# ─── 3. Analyzer._maybe_alert_overflow generalized to both keys ───────────

@pytest.fixture
def ana(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", str(tmp_path / "state.json"))
    from src.analyzer import Analyzer
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["rules"] = []
    return Analyzer(cm, MagicMock(), MagicMock())


def test_maybe_alert_overflow_fires_for_traffic_overflow(ana):
    ana.state["event_overflow"] = {}
    ana.state["traffic_overflow"] = {
        "raw_count": 200000, "max_results": 200000,
        "query_since": "2026-07-10T00:00:00+00:00",
        "query_until": "2026-07-10T00:01:00+00:00",
    }
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_called_once()
    alert = ana.reporter.add_health_alert.call_args[0][0]
    assert "200000" in alert["details"]


def test_maybe_alert_overflow_fires_both_independently(ana):
    ana.state["event_overflow"] = {"raw_count": 5000, "max_results": 5000,
                                   "query_since": "a", "query_until": "b"}
    ana.state["traffic_overflow"] = {"raw_count": 200000, "max_results": 200000,
                                     "query_since": "c", "query_until": "d"}
    ana._maybe_alert_overflow()
    assert ana.reporter.add_health_alert.call_count == 2


def test_traffic_overflow_alert_has_independent_cooldown_from_event_overflow(ana):
    """A live event_overflow cooldown must not suppress a fresh
    traffic_overflow alert, and vice versa — they are different failure
    modes with different remediation."""
    now = datetime.datetime.now(datetime.timezone.utc)
    from src.events.poller import format_utc
    ana.state["overflow_last_alert_at"] = format_utc(now)  # event key on cooldown
    ana.state["event_overflow"] = {"raw_count": 5000, "max_results": 5000}
    ana.state["traffic_overflow"] = {"raw_count": 200000, "max_results": 200000}
    ana._maybe_alert_overflow()
    # event_overflow suppressed by its own cooldown, traffic_overflow fires
    ana.reporter.add_health_alert.assert_called_once()
    alert = ana.reporter.add_health_alert.call_args[0][0]
    assert "200000" in alert["details"]


def test_traffic_overflow_alert_respects_own_cooldown(ana):
    now = datetime.datetime.now(datetime.timezone.utc)
    from src.events.poller import format_utc
    ana.state["traffic_overflow_last_alert_at"] = format_utc(now)
    ana.state["traffic_overflow"] = {"raw_count": 200000, "max_results": 200000}
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_not_called()


def test_no_traffic_overflow_no_alert(ana):
    ana.state["event_overflow"] = {}
    ana.state["traffic_overflow"] = {}
    ana._maybe_alert_overflow()
    ana.reporter.add_health_alert.assert_not_called()


def test_run_analysis_checks_overflow_unconditionally_even_on_cache_path(ana, monkeypatch):
    """Regression for the exact gap found in live verification: when a cache
    subscriber is present (_sub_events is not None → cache branch taken),
    _maybe_alert_overflow must still run so traffic_overflow (written by the
    scheduler ingest job, not by this cycle) gets checked."""
    ana._sub_events = MagicMock()
    ana._sub_events.poll_new_rows.return_value = []
    monkeypatch.setattr(ana, "_run_health_check", lambda: True)
    monkeypatch.setattr(ana, "_fetch_traffic", lambda: (None, [], datetime.datetime.now(datetime.timezone.utc)))
    monkeypatch.setattr(ana, "save_state", lambda: None)
    ana.state["traffic_overflow"] = {"raw_count": 200000, "max_results": 200000}
    ana.run_analysis()
    ana.reporter.add_health_alert.assert_called_once()
