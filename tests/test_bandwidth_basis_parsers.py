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
    one definition, not drift by orders of magnitude as before this task --
    pinned across the whole span range (zero, sub-minute, reversed), not
    just one interior point.
  - calculate_mbps never attaches BOUND_BASIS_NOTE to a non-finite value
    (fix round 1): a malformed byte field must fall through to the
    unavailable state, not a "≥ —" claim with no content.
  - validators.coerce() preserves a NaN bandwidth_mbps as NaN (fix round 2):
    it is a derived value whose absence means "could not be computed", not
    a raw counter whose absence means zero -- must not be fillna(0)'d back
    into a measurement that never happened.
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

    def test_nonfinite_bound_value_cannot_compose_ge_dash(self):
        """Fix round 1: dst_tbo="nan" used to slip past calculate_mbps's
        `total_bytes <= 0` guard (NaN compares False in both directions) and
        come out as (nan, BOUND_BASIS_NOTE, ...) -- which _shape_traffic_row
        then rendered as the content-free "≥ —" composite (bound prefix +
        unavailable dash). calculate_mbps now catches non-finite values at
        the source, so bw_val is None here and neither field is written --
        same as any other "unavailable" flow, not a bound-shaped dash."""
        flow = dict(_flow())
        flow["dst_tbo"] = "nan"
        flow["dst_tbi"] = 0
        bw_val, bw_note, _, _ = self.analyzer.calculate_mbps(flow)
        self.assertIsNone(bw_val)
        row = self.analyzer._shape_traffic_row(
            flow, bw_val=bw_val, bw_note=bw_note, vol_val=0.0, vol_note="(Interval)",
            conn_val=1)
        self.assertNotIn("formatted_bandwidth", row)
        self.assertNotIn("max_bandwidth_mbps", row)


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

    def test_agreement_holds_across_the_span_range_not_just_one_point(self):
        """Fix round 2, Minor 2: the 300s-span test above pins one point on
        the range (confirmed non-coincidental: old span-only denom vs. new
        span+1 denom genuinely diverge there). This extends the same
        cross-parser equality assertion to the edges of the range -- zero
        span, sub-minute span, and reversed timestamps -- so the two
        parsers are pinned to agree everywhere calculate_mbps defines a
        three-state answer, not only in the middle of it."""
        from src.report.parsers.api_parser import flatten_flow_record
        from src.report.parsers.csv_parser import CSVParser

        first = "2026-07-01T00:00:00Z"
        cases = {
            "zero_span": (1_000_000, first, first),
            "one_second_span": (1_000_000, first, "2026-07-01T00:00:01Z"),
            "reversed_timestamps": (1_000_000, "2026-07-01T00:05:00Z", first),
        }
        for name, (total_bytes, flow_first, flow_last) in cases.items():
            with self.subTest(name):
                api_flow = {
                    "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
                    "service": {"port": 443, "proto": 6},
                    "policy_decision": "allowed",
                    "dst_tbo": total_bytes, "dst_tbi": 0,
                    "first_detected": flow_first, "last_detected": flow_last,
                }
                api_bw = flatten_flow_record(api_flow)["bandwidth_mbps"]

                csv_df = pd.DataFrame({
                    "bytes_total": [total_bytes],
                    "first_detected": pd.to_datetime([flow_first], utc=True),
                    "last_detected": pd.to_datetime([flow_last], utc=True),
                })
                csv_bw = CSVParser()._estimate_bandwidth(csv_df).iloc[0]

                if api_bw is None:
                    self.assertTrue(math.isnan(csv_bw),
                                     f"{name}: api unavailable but csv={csv_bw}")
                else:
                    self.assertFalse(math.isnan(csv_bw),
                                      f"{name}: csv NaN but api={api_bw}")
                    self.assertAlmostEqual(api_bw, csv_bw, places=9, msg=name)


class TestValidatorsCoercePreservesUnavailableBandwidth(unittest.TestCase):
    """Fix round 2, Important finding: `validators.coerce()` used to
    silently fillna(0.0) any NaN bandwidth_mbps -- dead code for this
    column before Task 1/3 (the old clip(lower=1)/600s-interval formulas
    were always finite), made reachable by this task's fix. NaN here means
    "the rate could not be computed" (calculate_mbps's unavailable state),
    a different claim from a measured 0 -- must survive coerce() as NaN,
    same as the raw counter columns' 0 is left as a genuine 0 for them."""

    def test_nan_bandwidth_survives_coerce_as_nan(self):
        from src.report.parsers.validators import coerce

        df = pd.DataFrame({
            "bandwidth_mbps": [493.3, float("nan"), 12.5],
        })
        out = coerce(df)
        self.assertAlmostEqual(out["bandwidth_mbps"].iloc[0], 493.3)
        self.assertTrue(math.isnan(out["bandwidth_mbps"].iloc[1]),
                         f"expected NaN to survive coerce(), got {out['bandwidth_mbps'].iloc[1]}")
        self.assertAlmostEqual(out["bandwidth_mbps"].iloc[2], 12.5)

    def test_missing_bandwidth_column_defaults_to_nan_not_a_measured_zero(self):
        from src.report.parsers.validators import coerce

        df = pd.DataFrame({"src_ip": ["10.0.0.1"]})  # bandwidth_mbps absent entirely
        out = coerce(df)
        self.assertTrue(math.isnan(out["bandwidth_mbps"].iloc[0]))

    def test_raw_telemetry_columns_still_default_missing_to_zero(self):
        """The raw_dst_*/raw_ddms/raw_tdms columns are a different kind of
        thing from bandwidth_mbps: they are pass-through PCE counters
        (verbatim ddms/tdms/byte fields, or 0.0 placeholders CSV rows always
        carry since a CSV export never has them at all), not a derived
        result. A missing counter genuinely means "nothing was reported",
        so 0 stays correct for these -- only bandwidth_mbps changes."""
        from src.report.parsers.validators import coerce

        df = pd.DataFrame({
            "raw_dst_dbi": [1.0, float("nan")],
            "raw_ddms": [1000.0, float("nan")],
        })
        out = coerce(df)
        self.assertEqual(out["raw_dst_dbi"].iloc[1], 0.0)
        self.assertEqual(out["raw_ddms"].iloc[1], 0.0)


if __name__ == "__main__":
    unittest.main()
