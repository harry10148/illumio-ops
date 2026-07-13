"""Report-path parity with analyzer's PCE-failure contract.

execute_traffic_query_stream swallows a PCE failure (submit 406, poll
timeout, download error) into an empty yield and records it on
api.last_fetch_error — an intentional contract that the analyzer and ingest
paths already honor (analyzer._raise_if_query_fetch_failed). The report
generator's traffic fetch did NOT check it, so a failed PCE query produced a
silent empty/partial report. These tests pin the report path to the same
fail-loud contract: an api/mixed-source fetch that failed must raise
TrafficQueryError, never return empty as if it were a genuine 0-row result;
a cache-source fetch (no PCE call) must not raise on a stale error.
"""
import datetime
import unittest

from src.exceptions import TrafficQueryError
from src.report.report_generator import ReportGenerator

_START = datetime.datetime(2026, 7, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_END = datetime.datetime(2026, 7, 2, 0, 0, 0, tzinfo=datetime.timezone.utc)


class _FakeApi:
    """Mimics ApiClient's fetch facade + last_fetch_error contract."""

    def __init__(self, last_fetch_error=None, flows=None):
        self.last_fetch_error = last_fetch_error
        self._flows = flows if flows is not None else []

    def fetch_traffic_for_report(self, **kwargs):
        # execute_traffic_query_stream swallows failures into an empty yield.
        return list(self._flows)


class _StaleErrorCache:
    """Cache fully covering the window — the PCE is never called, so a stale
    api.last_fetch_error from an earlier op must not be mistaken for this
    query failing."""

    def cover_state(self, kind, start, end):
        return "full"

    def read_flows_raw(self, start, end, workload_hrefs=None):
        return [{"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 443}]

    def read_flows_agg(self, start, end):
        return None


class TestReportFetchErrorSurface(unittest.TestCase):
    def test_fetch_traffic_raises_on_api_fetch_error(self):
        rg = ReportGenerator(api=_FakeApi(last_fetch_error="submit failed: 406 - bad"),
                             cache_reader=None)
        with self.assertRaises(TrafficQueryError):
            rg._fetch_traffic(_START, _END, use_cache=False)

    def test_fetch_traffic_ok_when_no_error(self):
        rg = ReportGenerator(api=_FakeApi(last_fetch_error=None,
                                          flows=[{"src_ip": "1.1.1.1"}]),
                             cache_reader=None)
        out = rg._fetch_traffic(_START, _END, use_cache=False)
        self.assertEqual(out["source"], "api")
        self.assertEqual(len(out["raw"]), 1)

    def test_fetch_traffic_df_raises_on_api_fetch_error(self):
        rg = ReportGenerator(api=_FakeApi(last_fetch_error="async query poll timeout"),
                             cache_reader=None)
        with self.assertRaises(TrafficQueryError):
            rg._fetch_traffic_df(_START, _END, use_cache=False)

    def test_cache_source_does_not_raise_on_stale_error(self):
        # PCE never called → a stale error must not turn a cache hit into a raise.
        rg = ReportGenerator(api=_FakeApi(last_fetch_error="stale: 406 from a prior op"),
                             cache_reader=_StaleErrorCache())
        out = rg._fetch_traffic(_START, _END, use_cache=True)
        self.assertEqual(out["source"], "cache")
        self.assertEqual(len(out["raw"]), 1)


if __name__ == "__main__":
    unittest.main()
