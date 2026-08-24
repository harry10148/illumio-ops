"""tests/test_bandwidth_basis_parsers.py

Task 3 (bandwidth-basis plan): pins the display/parser-side consequences of
calculate_mbps's three-state return (Task 1) -- point value, provable lower
bound (BOUND_BASIS_NOTE), or unavailable (val is None).

Covers:
  - _shape_traffic_row omits max_bandwidth_mbps/formatted_bandwidth when
    bw_val is None (pre-existing 2F-1 behavior; pinned here so this task, or
    a later one, cannot quietly regress it).
  - _shape_traffic_row marks a lower-bound row with a distinguishing prefix
    so it cannot be mistaken for a point value of the same magnitude.
  - format_unit renders None (and NaN) as "--" instead of "0.00 Mbps"/"nan Mbps",
    matching the convention _fmt_bw already established in html_exporter.py.
  - csv_parser._estimate_bandwidth uses the same span+1 lower-bound formula
    as calculate_mbps, and NaN for an unusable measurement, instead of the
    old clip(lower=1) which silently invented a rate.
  - Cross-parser agreement: the same flow, parsed through api_parser and
    csv_parser, yields the same bandwidth_mbps -- the two parsers must share
    one definition, not drift by orders of magnitude as before this task.
"""
from __future__ import annotations

import math
import unittest
from unittest.mock import MagicMock

import pandas as pd

from src.analyzer import Analyzer, BOUND_BASIS_NOTE
from src.cli._render import format_unit

DASH = "—"  # em dash, same glyph _fmt_bw (html_exporter.py) already uses
GE = "≥"    # >=


def _analyzer() -> Analyzer:
    mock_cm = MagicMock()
    mock_api = MagicMock()
    mock_api.last_fetch_error = None
    mock_rep = MagicMock()
    return Analyzer(mock_cm, mock_api, mock_rep)


def _flow():
    return {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "allowed",
        "timestamp_range": {"first_detected": "2026-07-01T00:00:00Z",
                             "last_detected": "2026-07-01T00:00:10Z"},
    }


class TestShapeTrafficRowBandwidthDisplay(unittest.TestCase):
    def setUp(self):
        self.analyzer = _analyzer()

    def test_omits_bandwidth_fields_when_val_is_none(self):
        # Pins the pre-existing (2F-1) behavior: bw_val is None -> neither
        # key is written at all, not 0, not a dash string.
        row = self.analyzer._shape_traffic_row(
            _flow(), bw_val=None, bw_note="", vol_val=0.0, vol_note="(Interval)",
            conn_val=1)
        self.assertNotIn("max_bandwidth_mbps", row)
        self.assertNotIn("formatted_bandwidth", row)

    def test_lower_bound_row_is_marked_as_a_bound(self):
        row = self.analyzer._shape_traffic_row(
            _flow(), bw_val=493.30, bw_note=BOUND_BASIS_NOTE,
            vol_val=1.0, vol_note="(Interval)", conn_val=1)
        self.assertTrue(row["formatted_bandwidth"].startswith(GE))
        self.assertIn("493.30", row["formatted_bandwidth"])

    def test_lower_bound_distinguishable_from_point_value_of_same_magnitude(self):
        bound_row = self.analyzer._shape_traffic_row(
            _flow(), bw_val=493.30, bw_note=BOUND_BASIS_NOTE,
            vol_val=1.0, vol_note="(Interval)", conn_val=1)
        point_row = self.analyzer._shape_traffic_row(
            _flow(), bw_val=493.30, bw_note="(Interval)",
            vol_val=1.0, vol_note="(Interval)", conn_val=1)
        self.assertNotEqual(bound_row["formatted_bandwidth"], point_row["formatted_bandwidth"])


class TestFormatUnitUnavailable(unittest.TestCase):
    def test_none_bandwidth_is_dash(self):
        self.assertEqual(format_unit(None, "bandwidth"), DASH)

    def test_nan_bandwidth_is_dash(self):
        self.assertEqual(format_unit(float("nan"), "bandwidth"), DASH)

    def test_zero_bandwidth_still_renders_as_a_measured_zero(self):
        # 0 is a real measurement, distinct from "no rate available" --
        # must not collapse into the dash too.
        self.assertEqual(format_unit(0, "bandwidth"), "0.00 Mbps")


class TestCSVParserBandwidthFormula(unittest.TestCase):
    def _df(self, bytes_total, first, last):
        return pd.DataFrame({
            "bytes_total": [bytes_total],
            "first_detected": pd.to_datetime([first], utc=True),
            "last_detected": pd.to_datetime([last], utc=True),
        })

    def test_span_plus_one_denominator(self):
        from src.report.parsers.csv_parser import CSVParser
        df = self._df(1_000_000, "2026-07-01T00:00:00Z", "2026-07-01T00:05:00Z")
        result = CSVParser()._estimate_bandwidth(df)
        expected = (1_000_000 * 8.0) / (300.0 + 1.0) / 1_000_000.0
        self.assertAlmostEqual(result.iloc[0], expected, places=6)

    def test_missing_timestamp_columns_yields_nan_not_zero(self):
        from src.report.parsers.csv_parser import CSVParser
        df = pd.DataFrame({"bytes_total": [1_000_000]})  # no timestamp columns at all
        result = CSVParser()._estimate_bandwidth(df)
        self.assertTrue(math.isnan(result.iloc[0]))

    def test_unparsable_timestamp_yields_nan(self):
        from src.report.parsers.csv_parser import CSVParser
        df = self._df(1_000_000, None, "2026-07-01T00:05:00Z")
        result = CSVParser()._estimate_bandwidth(df)
        self.assertTrue(math.isnan(result.iloc[0]))

    def test_zero_bytes_yields_nan_not_a_measured_zero(self):
        from src.report.parsers.csv_parser import CSVParser
        df = self._df(0, "2026-07-01T00:00:00Z", "2026-07-01T00:05:00Z")
        result = CSVParser()._estimate_bandwidth(df)
        self.assertTrue(math.isnan(result.iloc[0]))

    def test_reversed_timestamps_yields_nan_not_a_negative_rate(self):
        from src.report.parsers.csv_parser import CSVParser
        df = self._df(1_000_000, "2026-07-01T00:05:00Z", "2026-07-01T00:00:00Z")
        result = CSVParser()._estimate_bandwidth(df)
        self.assertTrue(math.isnan(result.iloc[0]))


class TestCrossParserBandwidthAgreement(unittest.TestCase):
    """The point of Task 3: the same flow must yield the same bandwidth_mbps
    regardless of whether it arrived as a PCE API JSON record or a PCE UI
    CSV export. Before this task the two formulas disagreed by orders of
    magnitude for the same underlying data."""

    def test_same_flow_same_bandwidth_across_both_parsers(self):
        from src.report.parsers.api_parser import flatten_flow_record
        from src.report.parsers.csv_parser import CSVParser

        first, last = "2026-07-01T00:00:00Z", "2026-07-01T00:05:00Z"
        total_bytes = 1_000_000

        api_flow = {
            "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
            "service": {"port": 443, "proto": 6},
            "policy_decision": "allowed",
            "dst_tbo": total_bytes, "dst_tbi": 0,
            "first_detected": first, "last_detected": last,
        }
        api_row = flatten_flow_record(api_flow)

        csv_df = pd.DataFrame({
            "bytes_total": [total_bytes],
            "first_detected": pd.to_datetime([first]),
            "last_detected": pd.to_datetime([last]),
        })
        csv_bw = CSVParser()._estimate_bandwidth(csv_df).iloc[0]

        self.assertIsNotNone(api_row["bandwidth_mbps"])
        self.assertAlmostEqual(api_row["bandwidth_mbps"], csv_bw, places=9)

    def test_zero_bytes_agrees_as_unavailable_on_both_sides(self):
        from src.report.parsers.api_parser import flatten_flow_record
        from src.report.parsers.csv_parser import CSVParser

        first, last = "2026-07-01T00:00:00Z", "2026-07-01T00:05:00Z"
        api_flow = {
            "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
            "service": {"port": 443, "proto": 6},
            "policy_decision": "allowed",
            "dst_tbo": 0, "dst_tbi": 0,
            "first_detected": first, "last_detected": last,
        }
        api_row = flatten_flow_record(api_flow)
        self.assertIsNone(api_row["bandwidth_mbps"])

        csv_df = pd.DataFrame({
            "bytes_total": [0],
            "first_detected": pd.to_datetime([first]),
            "last_detected": pd.to_datetime([last]),
        })
        csv_bw = CSVParser()._estimate_bandwidth(csv_df).iloc[0]
        self.assertTrue(math.isnan(csv_bw))


if __name__ == "__main__":
    unittest.main()
