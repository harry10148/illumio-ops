"""Task 5 (2f1): an explicit data_source preference must override the
automatic cache/API decision in Analyzer._fetch_query_flows, and the path
actually used must be reported back through Analyzer.last_query_stats
(and from there, the /api/quarantine/search response) as 'actual_source'.

Covered invariants:
  1. data_source='live' bypasses the cache entirely — cover_state and
     read_flows_raw are never called — even when coverage is 'full'.
     actual_source == 'api'.
  2. data_source='hybrid' (and unspecified, the default) leave today's
     automatic behaviour untouched: full coverage → cache, actual_source
     == 'cache'.
  3. Partial coverage + hybrid, with the API gap contributing rows, still
     produces actual_source == 'mixed' (both sides genuinely contributed).
  4. query_flows() forwards params['data_source'] into _fetch_query_flows
     and surfaces the resulting source as last_query_stats['actual_source'].
"""
import datetime
import unittest
from unittest.mock import MagicMock

from src.analyzer import Analyzer


def _make_analyzer():
    """Build an Analyzer with minimal mocks; no state file I/O."""
    mock_cm = MagicMock()
    mock_cm.config = {"rules": []}
    az = Analyzer(mock_cm, MagicMock(), MagicMock())
    az.load_state = MagicMock()
    az.save_state = MagicMock()
    return az


def _make_cache_reader(cover_state="full", cache_start=None, flows=None):
    cr = MagicMock()
    cr.cover_state.return_value = cover_state
    cr.earliest_data_timestamp.return_value = cache_start
    cr.read_flows_raw.return_value = flows if flows is not None else [{"policy_decision": "allowed"}]
    return cr


_START = "2026-01-01T00:00:00Z"
_END = "2026-01-08T00:00:00Z"
_CACHE_START = datetime.datetime(2026, 1, 4, tzinfo=datetime.timezone.utc)  # middle of window


class TestExplicitLiveBypassesCache(unittest.TestCase):

    def test_live_with_full_coverage_never_touches_cache(self):
        """Even when cover_state would say 'full', data_source='live' must
        skip cover_state entirely and go straight to the API."""
        az = _make_analyzer()
        cr = _make_cache_reader(cover_state="full")
        az._cache_reader = cr
        az.api.execute_traffic_query_stream.return_value = iter([{"policy_decision": "blocked"}])

        flows, source = az._fetch_query_flows(
            _START, _END, ["allowed"], MagicMock(), False,
            data_source="live",
        )

        cr.cover_state.assert_not_called()
        cr.read_flows_raw.assert_not_called()
        self.assertEqual(source, "api")
        az.api.execute_traffic_query_stream.assert_called_once()

    def test_live_alias_no_cache_also_bypasses(self):
        """resolve_data_source's back-compat alias ('no-cache' -> 'live')
        must behave identically — same single source of truth as the
        report path."""
        az = _make_analyzer()
        cr = _make_cache_reader(cover_state="full")
        az._cache_reader = cr
        az.api.execute_traffic_query_stream.return_value = iter([])

        _, source = az._fetch_query_flows(
            _START, _END, ["allowed"], MagicMock(), False,
            data_source="no-cache",
        )

        cr.read_flows_raw.assert_not_called()
        self.assertEqual(source, "api")


class TestHybridDefaultUnchanged(unittest.TestCase):

    def test_hybrid_full_coverage_reads_cache(self):
        az = _make_analyzer()
        cr = _make_cache_reader(cover_state="full")
        az._cache_reader = cr

        flows, source = az._fetch_query_flows(
            _START, _END, ["allowed"], MagicMock(), False,
            data_source="hybrid",
        )

        cr.read_flows_raw.assert_called_once()
        az.api.execute_traffic_query_stream.assert_not_called()
        self.assertEqual(source, "cache")
        self.assertGreater(len(flows), 0)

    def test_unspecified_full_coverage_reads_cache(self):
        """No data_source at all (None) must behave exactly like today —
        the default automatic path, not the live bypass."""
        az = _make_analyzer()
        cr = _make_cache_reader(cover_state="full")
        az._cache_reader = cr

        flows, source = az._fetch_query_flows(
            _START, _END, ["allowed"], MagicMock(), False,
        )

        cr.read_flows_raw.assert_called_once()
        az.api.execute_traffic_query_stream.assert_not_called()
        self.assertEqual(source, "cache")

    def test_partial_hybrid_with_gap_contribution_is_mixed(self):
        """Partial coverage where the API gap query actually returns rows
        (both sides contribute) must be tagged 'mixed', not 'cache'."""
        az = _make_analyzer()
        cr = _make_cache_reader(cover_state="partial", cache_start=_CACHE_START,
                                 flows=[{"policy_decision": "allowed"}])
        az._cache_reader = cr
        az.api.execute_traffic_query_stream.return_value = iter(
            [{"policy_decision": "blocked", "first_detected": "x", "last_detected": "y"}]
        )

        flows, source = az._fetch_query_flows(
            _START, _END, ["allowed"], MagicMock(), False,
            data_source="hybrid",
        )

        self.assertEqual(source, "mixed")
        cr.read_flows_raw.assert_called_once()
        az.api.execute_traffic_query_stream.assert_called_once()

    def test_partial_with_empty_gap_is_still_cache_not_mixed(self):
        """Partial coverage where the gap query comes back empty must stay
        'cache' — labelling an effectively pure-cache result 'mixed' would
        be misleading."""
        az = _make_analyzer()
        cr = _make_cache_reader(cover_state="partial", cache_start=_CACHE_START)
        az._cache_reader = cr
        az.api.execute_traffic_query_stream.return_value = iter([])

        _, source = az._fetch_query_flows(
            _START, _END, ["allowed"], MagicMock(), False,
            data_source="hybrid",
        )

        self.assertEqual(source, "cache")


class TestQueryFlowsSurfacesActualSource(unittest.TestCase):
    """query_flows() must forward params['data_source'] and report the
    resulting path via last_query_stats['actual_source']."""

    def _params(self, **extra):
        p = {"start_time": _START, "end_time": _END}
        p.update(extra)
        return p

    def test_actual_source_api_surfaces_in_last_query_stats(self):
        az = _make_analyzer()
        az.api.last_fetch_error = None
        captured = {}

        def _fake_fetch(*args, **kwargs):
            captured["data_source"] = kwargs.get("data_source")
            return iter([]), "api"

        az._fetch_query_flows = _fake_fetch
        az.query_flows(self._params(data_source="live"))

        self.assertEqual(captured["data_source"], "live")
        self.assertEqual(az.last_query_stats["actual_source"], "api")

    def test_actual_source_cache_surfaces_in_last_query_stats(self):
        az = _make_analyzer()
        az.api.last_fetch_error = None
        az._fetch_query_flows = lambda *a, **kw: (iter([{"policy_decision": "allowed"}]), "cache")

        az.query_flows(self._params())

        self.assertEqual(az.last_query_stats["actual_source"], "cache")

    def test_actual_source_mixed_surfaces_in_last_query_stats(self):
        az = _make_analyzer()
        az.api.last_fetch_error = None
        az._fetch_query_flows = lambda *a, **kw: (iter([{"policy_decision": "allowed"}]), "mixed")

        az.query_flows(self._params())

        self.assertEqual(az.last_query_stats["actual_source"], "mixed")


class TestQuarantineSearchDataSourceValidation:
    """/api/quarantine/search's live branch (fix round 1): 'cache-only' is
    not implemented by this path (analyzer has no clip-to-cache behaviour),
    so it must be rejected at the endpoint rather than silently downgraded
    to hybrid by resolve_data_source. Uses the same app_persistent +
    Analyzer.query_flows monkeypatch pattern as tests/test_gui_quarantine.py.
    """

    def _login(self, app_persistent):
        from tests._helpers import _csrf
        c = app_persistent.test_client()
        login = c.post('/api/login', json={"username": "admin", "password": "testpass"},
                       environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        return c, _csrf(login)

    def test_cache_only_data_source_is_rejected(self, app_persistent, monkeypatch):
        c, csrf_token = self._login(app_persistent)

        from src.analyzer import Analyzer
        called = {"n": 0}

        def fake_query(self, params):
            called["n"] += 1
            return []

        monkeypatch.setattr(Analyzer, "query_flows", fake_query)

        r = c.post('/api/quarantine/search', json={"mins": 60, "data_source": "cache-only"},
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                   headers={'X-CSRF-Token': csrf_token})

        assert r.status_code == 400
        assert r.json["ok"] is False
        # rejected before query_flows is ever reached — not silently
        # downgraded to hybrid and forwarded.
        assert called["n"] == 0

    def test_live_data_source_is_accepted_and_forwarded(self, app_persistent, monkeypatch):
        c, csrf_token = self._login(app_persistent)

        from src.analyzer import Analyzer
        captured = {}

        def fake_query(self, params):
            captured.update(params)
            self.last_query_stats = {"total_matches": 0, "cap": 500,
                                     "truncated": False, "actual_source": "api"}
            return []

        monkeypatch.setattr(Analyzer, "query_flows", fake_query)

        r = c.post('/api/quarantine/search', json={"mins": 60, "data_source": "live"},
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                   headers={'X-CSRF-Token': csrf_token})

        assert r.status_code == 200
        assert r.json["ok"] is True
        assert captured.get("data_source") == "live"
        assert r.json["actual_source"] == "api"


if __name__ == "__main__":
    unittest.main()
