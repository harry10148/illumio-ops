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
from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter
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

    def test_agrees_with_calculate_mbps_note_for_the_short_alias_field_names(self):
        """LOW 8 (final-review): calculate_mbps accepts alias numerator
        fields -- `dbo`/`dbi` for delta bytes, `tbo`/`tbi`/`dst_bo` for
        total bytes -- as fallbacks when the canonical `dst_*` names are
        absent. api_parser.flatten_flow_record's raw_dst_* columns used to
        capture only the canonical names, so a flow using an alias computed
        a real point value via calculate_mbps but _lower_bound_mask (reading
        only raw_dst_dbo/dbi/tbo/tbi) saw all-zero raw counters and
        misclassified it as a bound. Direction was conservative (overstates
        uncertainty, never understates it) but still a mismatch this task's
        own drift-guard exists to catch."""
        from src.analyzer import calculate_mbps, BOUND_BASIS_NOTE
        from src.report.parsers.api_parser import flatten_flow_record

        alias_interval_flow = {
            'src': {'ip': '10.0.0.4'}, 'dst': {'ip': '10.0.1.4'},
            'service': {'port': 443, 'proto': 6},
            'dbo': 500, 'dbi': 500, 'ddms': 80,
        }
        alias_avg_flow = {
            'src': {'ip': '10.0.0.5'}, 'dst': {'ip': '10.0.1.5'},
            'service': {'port': 443, 'proto': 6},
            'dst_bo': 200, 'dst_bi': 0, 'tdms': 32000,
        }

        rows = [flatten_flow_record(f) for f in (alias_interval_flow, alias_avg_flow)]
        df = pd.DataFrame(rows)
        mask = _lower_bound_mask(df)

        for i, flow in enumerate((alias_interval_flow, alias_avg_flow)):
            _val, note, _b, _d = calculate_mbps(flow)
            assert note != BOUND_BASIS_NOTE, f"fixture row {i} must be a point value"
            assert bool(mask.iloc[i]) is False, (
                f"row {i} ({flow}): mask says bound=True but calculate_mbps "
                f"computed a point value via the alias field"
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


def _traffic_report_results(mod11: dict) -> dict:
    """Minimal results dict TrafficFlowsHtmlExporter needs to build without
    crashing -- mirrors tests/test_traffic_flows_html_exporter.py's _results()
    helper, customized to inject the mod11 dict under test."""
    df = pd.DataFrame([{"Port": 443, "Protocol": "TCP", "Flow Count": 10}])
    return {
        "findings": [],
        "mod01": {"total_flows": 10, "total_connections": 100,
                  "unique_src_ips": 2, "unique_dst_ips": 3,
                  "allowed_flows": 4, "blocked_flows": 1,
                  "potentially_blocked_flows": 5, "unknown_flows": 0,
                  "total_bytes": 0, "total_mb": 1.0,
                  "policy_coverage_pct": 40.0,
                  "src_managed_pct": 100.0, "dst_managed_pct": 50.0,
                  "date_range": "2026-04-27 ~ 2026-05-04",
                  "top_ports": df, "top_protocols": df},
        "mod02": {"summary": df, "chart_spec": None},
        "mod08": {"unmanaged_flow_count": 3, "unmanaged_pct": 30.0,
                  "unique_unmanaged_src": 1, "unique_unmanaged_dst": 1,
                  "top_unmanaged_src": df},
        "mod09": {"label_distribution": {"src_app": df, "dst_app": df,
                                         "src_env": df, "dst_env": df,
                                         "src_role": df, "dst_role": df},
                  "port_distribution": df, "proto_distribution": df},
        "mod11": mod11,
        "mod12": {"generated_at": "2026-07-02 12:00:00", "kpis": [],
                  "findings_summary": {}, "total_findings": 0,
                  "key_findings": [], "findings": [],
                  "boundary_breaches": [], "suspicious_pivot_behavior": [],
                  "blast_radius": [], "blind_spots": [], "action_matrix": []},
    }


class TestMod11HtmlRendersTheBoundLabel:
    """The analysis-module fields are only honest if the rendered HTML
    actually shows them -- `bandwidth_analysis()` labelling a statistic as a
    bound and the exporter silently dropping that label on the floor is the
    same class of lie this task exists to close, one layer further down."""

    def _export_html(self, tmp_path, mod11: dict) -> str:
        results = _traffic_report_results(mod11)
        exp = TrafficFlowsHtmlExporter(results, data_source="api", lang="en")
        path = exp.export(str(tmp_path))
        return open(path, encoding="utf-8").read()

    def test_bound_stats_get_the_ge_prefix_and_both_notes(self, tmp_path):
        df = pd.DataFrame([{"Port": 443, "Protocol": "TCP", "Flow Count": 10}])
        mod11 = {
            "bytes_data_available": True, "total_bytes": 1000, "total_mb": 1.0,
            "top_by_bytes": df, "top_bandwidth": df,
            "max_bandwidth_mbps": 500.0, "avg_bandwidth_mbps": 170.0,
            "p95_bandwidth_mbps": 480.0,
            "bandwidth_stats_is_bound": True,
            "bandwidth_bound_flow_count": 2, "bandwidth_point_flow_count": 2,
            "bandwidth_unavailable_count": 2, "bandwidth_candidate_count": 5,
        }
        html = self._export_html(tmp_path, mod11)

        assert "≥ 500.00 Mbps" in html
        assert "≥ 170.00 Mbps" in html
        assert "≥ 480.00 Mbps" in html
        # The explanatory notes must both be present, not just the glyph.
        assert "lower bound" in html.lower()
        assert "2 of 5" in html

    def test_point_only_stats_get_no_ge_prefix(self, tmp_path):
        df = pd.DataFrame([{"Port": 443, "Protocol": "TCP", "Flow Count": 10}])
        mod11 = {
            "bytes_data_available": True, "total_bytes": 1000, "total_mb": 1.0,
            "top_by_bytes": df, "top_bandwidth": df,
            "max_bandwidth_mbps": 100.0, "avg_bandwidth_mbps": 75.0,
            "p95_bandwidth_mbps": 95.0,
            "bandwidth_stats_is_bound": False,
            "bandwidth_bound_flow_count": 0, "bandwidth_point_flow_count": 3,
            "bandwidth_unavailable_count": 0, "bandwidth_candidate_count": 3,
        }
        html = self._export_html(tmp_path, mod11)

        assert "≥ 100.00 Mbps" not in html
        assert "100.00 Mbps" in html
        assert "lower bound" not in html.lower()
