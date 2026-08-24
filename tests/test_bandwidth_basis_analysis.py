"""tests/test_bandwidth_basis_analysis.py

Task 4 (bandwidth-basis plan): pins the report-statistics-side consequences of
calculate_mbps's three-state contract (point value / provable lower bound /
unavailable, see Task 1-3) reaching mod11_bandwidth.bandwidth_analysis and
rules_engine._b008_bandwidth_anomaly.

The unified DataFrame (src/report/parsers/{api,csv}_parser.py) carries the
computed bandwidth_mbps value but not which basis produced it. Both parsers
already carry the raw counters calculate_mbps itself prioritizes
(raw_dst_dbo/dbi + raw_ddms for Priority-1 "(Interval)", raw_dst_tbo/tbi +
raw_tdms for Priority-2 "(Avg)"); a row is a lower bound (Priority-3) exactly
when neither pairing is present. mod11_bandwidth replays that same priority
order against those columns (see `_lower_bound_mask`) instead of a parser
carrying a new column -- the drift-guard test below pins that replay against
calculate_mbps's own note for the same flow.

Covers:
  - A population mixing point-value and lower-bound rows makes the derived
    max/mean/P95 themselves lower bounds (order-statistics monotonicity: if
    every bound row's true rate could be higher, the true max/mean/quantile
    can only be higher than what was computed over the observed values) --
    `bandwidth_stats_is_bound` must be True, and bound/point counts recorded.
  - A population of only point values does NOT get the bound flag (the
    mirror-image failure: a mask that degenerates to "everything is a bound"
    would pass every positive test above while silently overstating
    uncertainty).
  - `top_bandwidth` marks each row's basis so a bound-derived rate cannot be
    mistaken for a point value of the same magnitude.
  - Rows with no computed rate (NaN) are excluded from every aggregate but
    counted, not silently dropped from the operator's picture.
  - `_lower_bound_mask` agrees with calculate_mbps's own note for the same
    flow (Interval / Avg / bound), and defaults conservatively to "bound"
    when the raw evidence columns are entirely absent (a caller-built
    minimal frame, e.g. test_phase11_chart_coverage.py's fixture) -- treating
    unknown-basis data as a bound only overstates uncertainty, never
    understates it.
  - `_b008_bandwidth_anomaly` still fires (rule_id unchanged) on the same
    synthetic data as before this task -- the naming/copy rewrite must not
    have drifted the computation.
  - Its rule_name/description no longer claim "bandwidth": B008 operates on
    bytes_total's percentile, a volume metric, not a rate.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from src.report.analysis.mod11_bandwidth import bandwidth_analysis, _lower_bound_mask
from src.report.rules_engine import RulesEngine
from src.report.rules import Finding


def _base_row(**overrides) -> dict:
    row = {
        'src_ip': '10.0.0.1', 'src_hostname': 'host-a',
        'dst_ip': '10.0.1.1', 'dst_hostname': 'svc-a',
        'port': 443, 'proto': 'TCP',
        'bytes_total': 100_000,
        'policy_decision': 'allowed',
        'bandwidth_mbps': 10.0,
        'src_app': 'web', 'src_env': 'prod',
        'num_connections': 1,
        'raw_dst_dbo': 0.0, 'raw_dst_dbi': 0.0,
        'raw_dst_tbo': 0.0, 'raw_dst_tbi': 0.0,
        'raw_ddms': 0.0, 'raw_tdms': 0.0,
    }
    row.update(overrides)
    return row


def _point_row_interval(bandwidth_mbps: float, **overrides) -> dict:
    """A row whose bandwidth_mbps came from calculate_mbps's Priority-1
    (delta bytes / ddms) branch -- a point value, not a bound."""
    return _base_row(bandwidth_mbps=bandwidth_mbps,
                      raw_dst_dbo=500.0, raw_dst_dbi=500.0, raw_ddms=80.0,
                      **overrides)


def _point_row_avg(bandwidth_mbps: float, **overrides) -> dict:
    """Priority-2 (total bytes / tdms) branch -- also a point value."""
    return _base_row(bandwidth_mbps=bandwidth_mbps,
                      raw_dst_tbo=200.0, raw_dst_tbi=0.0, raw_tdms=32.0,
                      **overrides)


def _bound_row(bandwidth_mbps: float, **overrides) -> dict:
    """Priority-3: no ddms/tdms evidence at all -- a provable lower bound."""
    return _base_row(bandwidth_mbps=bandwidth_mbps, **overrides)


def _unavailable_row(**overrides) -> dict:
    """bytes present but no computed rate -- calculate_mbps's third state."""
    return _base_row(bandwidth_mbps=float('nan'), **overrides)


class TestMixedBasisAggregateStats:
    def test_stats_flagged_as_bound_when_any_row_is_a_bound(self):
        df = pd.DataFrame([
            _point_row_interval(100.0),
            _point_row_avg(50.0),
            _bound_row(30.0),
            _bound_row(500.0),
            _unavailable_row(),
        ])
        result = bandwidth_analysis(df)

        assert result['bandwidth_stats_is_bound'] is True
        assert result['bandwidth_bound_flow_count'] == 2
        assert result['bandwidth_point_flow_count'] == 2
        # The aggregates themselves are still computed over every row with a
        # rate (bound or point) -- excluding bounds would throw away real
        # information; the fix is labelling, not exclusion.
        assert result['max_bandwidth_mbps'] == pytest.approx(500.0)
        assert result['avg_bandwidth_mbps'] == pytest.approx((100 + 50 + 30 + 500) / 4)

    def test_stats_not_flagged_as_bound_when_all_rows_are_point_values(self):
        """Mirror-image guard: a mask that always says "bound" would pass
        the test above too. Pin the negative case explicitly."""
        df = pd.DataFrame([
            _point_row_interval(100.0),
            _point_row_avg(50.0),
            _point_row_interval(75.0),
        ])
        result = bandwidth_analysis(df)

        assert result['bandwidth_stats_is_bound'] is False
        assert result['bandwidth_bound_flow_count'] == 0
        assert result['bandwidth_point_flow_count'] == 3


class TestTopBandwidthBasisLabelling:
    def test_top_bandwidth_marks_each_rows_basis(self):
        df = pd.DataFrame([
            _point_row_interval(100.0, dst_ip='10.0.1.10'),
            _bound_row(500.0, dst_ip='10.0.1.20'),
        ])
        result = bandwidth_analysis(df)
        top = result['top_bandwidth']

        assert 'Rate Basis' in top.columns
        by_dst = dict(zip(top['Dst IP'], top['Rate Basis']))
        # The two labels must differ -- a bound row's rate cannot render
        # identically to a point-value row's, even sorted next to each other.
        assert by_dst['10.0.1.10'] != by_dst['10.0.1.20']


class TestUnavailableRowsCounted:
    def test_unavailable_rows_excluded_from_stats_but_counted(self):
        df = pd.DataFrame([
            _point_row_interval(100.0),
            _unavailable_row(),
            _unavailable_row(),
        ])
        result = bandwidth_analysis(df)

        # Only the one row with a real rate feeds the aggregate.
        assert result['max_bandwidth_mbps'] == pytest.approx(100.0)
        assert result['bandwidth_unavailable_count'] == 2
        assert result['bandwidth_candidate_count'] == 3

    def test_all_rows_unavailable_still_reports_the_count(self):
        """No bandwidth stats block at all (has_bw empty) must not make the
        unavailable count disappear along with it."""
        df = pd.DataFrame([_unavailable_row(), _unavailable_row()])
        result = bandwidth_analysis(df)

        assert 'max_bandwidth_mbps' not in result
        assert result['bandwidth_unavailable_count'] == 2
        assert result['bandwidth_candidate_count'] == 2


class TestLowerBoundMaskAgreesWithCalculateMbps:
    def test_agrees_with_calculate_mbps_note_across_all_three_states(self):
        """Drift guard: replaying calculate_mbps's priority order against the
        raw counter columns must classify the same flow the same way
        calculate_mbps's own `note` does, for all three of its branches."""
        from src.analyzer import calculate_mbps, BOUND_BASIS_NOTE
        from src.report.parsers.api_parser import flatten_flow_record

        interval_flow = {
            'src': {'ip': '10.0.0.1'}, 'dst': {'ip': '10.0.1.1'},
            'service': {'port': 443, 'proto': 6},
            'dst_dbo': 500, 'dst_dbi': 500, 'ddms': 80,
        }
        avg_flow = {
            'src': {'ip': '10.0.0.2'}, 'dst': {'ip': '10.0.1.2'},
            'service': {'port': 443, 'proto': 6},
            'dst_tbo': 200, 'dst_tbi': 0, 'tdms': 32000,
        }
        bound_flow = {
            'src': {'ip': '10.0.0.3'}, 'dst': {'ip': '10.0.1.3'},
            'service': {'port': 443, 'proto': 6},
            'dst_tbo': 13248009806581, 'dst_tbi': 0,
            'first_detected': '2024-01-01T00:00:00Z',
            'last_detected': '2024-01-03T12:40:48Z',
        }

        rows = [flatten_flow_record(f) for f in (interval_flow, avg_flow, bound_flow)]
        df = pd.DataFrame(rows)
        mask = _lower_bound_mask(df)

        for i, flow in enumerate((interval_flow, avg_flow, bound_flow)):
            _val, note, _b, _d = calculate_mbps(flow)
            expected_is_bound = (note == BOUND_BASIS_NOTE)
            assert bool(mask.iloc[i]) == expected_is_bound, (
                f"row {i} ({flow}): mask says bound={bool(mask.iloc[i])}, "
                f"calculate_mbps note={note!r}"
            )

    def test_defaults_to_bound_when_raw_columns_are_entirely_absent(self):
        """A caller-built frame with no raw_* columns at all (e.g. a minimal
        test fixture) carries no evidence of a point-value path. Default to
        "bound" -- the conservative direction that only overstates
        uncertainty, never understates it."""
        df = pd.DataFrame([{'bandwidth_mbps': 42.0, 'bytes_total': 1000}])
        mask = _lower_bound_mask(df)
        assert bool(mask.iloc[0]) is True


class TestB008RenamedToVolumeAnomaly:
    """B008 computes on bytes_total's percentile, a data-volume metric, not a
    rate over time -- it was never a bandwidth measurement."""

    def _engine(self, lang: str = 'en') -> RulesEngine:
        cfg = {'thresholds': {'high_bytes_percentile': 95}}
        return RulesEngine(cfg, lang=lang)

    def _volume_anomaly_df(self) -> pd.DataFrame:
        rows = [
            {'src_ip': '10.0.0.1', 'dst_ip': '10.0.1.1', 'port': 443,
             'bytes_total': 1_000, 'num_connections': 1}
            for _ in range(19)
        ]
        rows.append({'src_ip': '10.0.0.99', 'dst_ip': '10.0.1.99', 'port': 443,
                      'bytes_total': 50_000_000, 'num_connections': 1})
        return pd.DataFrame(rows)

    def test_still_fires_on_the_same_data_rule_id_unchanged(self):
        """Regression guard for the computation itself: the naming/copy
        rewrite must not have touched what actually triggers the rule."""
        engine = self._engine()
        finding = engine._b008_bandwidth_anomaly(self._volume_anomaly_df())
        assert finding is not None
        assert isinstance(finding, Finding)
        assert finding.rule_id == 'B008'

    def test_rule_name_no_longer_claims_bandwidth(self):
        engine = self._engine()
        finding = engine._b008_bandwidth_anomaly(self._volume_anomaly_df())
        assert finding is not None
        assert 'bandwidth' not in finding.rule_name.lower()
        assert 'Bandwidth' not in finding.rule_name

    def test_no_findings_when_no_outlier_present(self):
        engine = self._engine()
        df = pd.DataFrame([
            {'src_ip': '10.0.0.1', 'dst_ip': '10.0.1.1', 'port': 443,
             'bytes_total': 0, 'num_connections': 1}
        ])
        assert engine._b008_bandwidth_anomaly(df) is None
