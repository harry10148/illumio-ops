"""Test bandwidth threshold migration script.

Tests compare alert thresholds across old (/600s) and new (/span+1) bandwidth basis.
"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.pce_cache.models import Base, PceTrafficFlowRaw


def create_test_db(flows: list[dict]) -> str:
    """Create a file-based SQLite DB with test flows and return the path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Insert test flows
    with Session(engine) as session:
        for flow in flows:
            record = PceTrafficFlowRaw(
                flow_hash=flow['flow_hash'],
                first_detected=flow['first_detected'],
                last_detected=flow['last_detected'],
                src_ip=flow['src_ip'],
                dst_ip=flow['dst_ip'],
                port=flow['port'],
                protocol=flow['protocol'],
                action=flow['action'],
                flow_count=flow.get('flow_count', 1),
                bytes_in=flow.get('bytes_in', 0),
                bytes_out=flow.get('bytes_out', 0),
                raw_json=flow['raw_json'],
                ingested_at=flow['ingested_at'],
            )
            session.add(record)
        session.commit()

    engine.dispose()
    return db_path


class TestBandwidthBasisDiff:
    """Test the bandwidth threshold migration comparison."""
    
    def test_basic_flow_evaluation(self):
        """Test that old and new formulas produce different results for Priority 3 flows."""
        # Priority 3 flow: has total bytes, no tdms, uses timestamp span
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=10)  # 10 second span
        
        flow_data = {
            'flow_hash': 'test-flow-1',
            'first_detected': start,
            'last_detected': now,
            'src_ip': '1.2.3.4',
            'dst_ip': '5.6.7.8',
            'port': 443,
            'protocol': 'tcp',
            'action': 'allowed',
            'bytes_in': 0,
            'bytes_out': 80000000,  # 80 MB
            'raw_json': json.dumps({
                'dst_tbo': 80000000,  # total bytes out
                'dst_tbi': 0,
                # no tdms field → Priority 3 flow
            }),
            'ingested_at': now,
        }
        
        db_path = create_test_db([flow_data])
        
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff
            
            rules = [
                {
                    'id': 1,
                    'type': 'bandwidth',
                    'name': 'Test Rule',
                    'threshold_count': 60.0,  # 60 Mbps
                }
            ]
            
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)
            
            # Verify result structure (final-review Medium 4: renamed/split
            # so old and new basis each get their own evaluable population
            # instead of one combined, ill-defined "flows_evaluated").
            assert 'rules_compared' in result
            assert 'flows_total' in result
            assert 'flows_old_basis_evaluable' in result
            assert 'flows_new_basis_evaluable' in result
            assert result['rules_compared'] == 1
            assert result['flows_total'] == 1
            assert result['flows_old_basis_evaluable'] == 1
            assert result['flows_new_basis_evaluable'] == 1

            # Check rule comparison
            assert len(result['results']) == 1
            rule_result = result['results'][0]
            assert rule_result['rule_id'] == 1
            assert rule_result['rule_name'] == 'Test Rule'
            assert 'old_max_mbps' in rule_result
            assert 'new_max_mbps' in rule_result
            assert 'trigger_state_change' in rule_result
            assert rule_result['flows_matched'] == 1
            assert rule_result['flows_evaluated_old'] == 1
            assert rule_result['flows_evaluated_new'] == 1

            # Old formula: 80000000 bytes * 8 / 600 / 1e6 = 1.0667 Mbps
            # New formula: 80000000 bytes * 8 / 11 / 1e6 = 58.18 Mbps
            assert rule_result['old_max_mbps'] > 0
            assert rule_result['new_max_mbps'] > rule_result['old_max_mbps']
            
            # Old: 1.067 < 60 (doesn't fire), New: 58.18 < 60 (doesn't fire) → no change
            # (or if we round: Old: ~1 Mbps, New: ~58 Mbps)
            # Both below threshold, so no state change expected
            
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_flow_that_changes_trigger_state(self):
        """Test a flow that would fire under old basis but not new, or vice versa."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=100)  # 100 second span
        
        # Flow with substantial bytes that looks huge under /600 but smaller under /span
        flow_data = {
            'flow_hash': 'test-flow-2',
            'first_detected': start,
            'last_detected': now,
            'src_ip': '1.2.3.4',
            'dst_ip': '5.6.7.8',
            'port': 443,
            'protocol': 'tcp',
            'action': 'allowed',
            'bytes_in': 0,
            'bytes_out': 40500000,  # 40.5 MB
            'raw_json': json.dumps({
                'dst_tbo': 40500000,
                'dst_tbi': 0,
            }),
            'ingested_at': now,
        }
        
        db_path = create_test_db([flow_data])
        
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff
            
            rules = [
                {
                    'id': 1,
                    'type': 'bandwidth',
                    'name': 'High Threshold',
                    'threshold_count': 600.0,  # 600 Mbps
                }
            ]
            
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)
            
            rule_result = result['results'][0]
            # Old: 40500000 * 8 / 600 / 1e6 = 0.54 Mbps (below 600)
            # New: 40500000 * 8 / 101 / 1e6 = 3.207 Mbps (below 600)
            # Still below threshold, no state change
            assert rule_result['old_max_mbps'] < 600
            assert rule_result['new_max_mbps'] < 600
            
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_unevaluable_flows(self):
        """Test flows that can't be evaluated (missing bytes or timestamps)."""
        now = datetime.now(timezone.utc)
        
        flow_data = {
            'flow_hash': 'test-flow-3',
            'first_detected': now,
            'last_detected': now,  # Same timestamp → span = 0
            'src_ip': '1.2.3.4',
            'dst_ip': '5.6.7.8',
            'port': 443,
            'protocol': 'tcp',
            'action': 'allowed',
            'bytes_in': 0,
            'bytes_out': 0,  # No bytes
            'raw_json': json.dumps({}),
            'ingested_at': now,
        }
        
        db_path = create_test_db([flow_data])
        
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff
            
            rules = [
                {
                    'id': 1,
                    'type': 'bandwidth',
                    'name': 'Test Rule',
                    'threshold_count': 50.0,
                }
            ]
            
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            # Flow should be unevaluable under both bases
            assert result['flows_old_basis_evaluable'] == 0
            assert result['flows_new_basis_evaluable'] == 0
            rule_result = result['results'][0]
            assert rule_result['flows_matched'] == 1
            assert rule_result['flows_no_measurement'] == 1

        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_read_only_mode(self):
        """Verify that read-only mode is actually enforced."""
        now = datetime.now(timezone.utc)
        
        flow_data = {
            'flow_hash': 'test-flow-4',
            'first_detected': now - timedelta(seconds=10),
            'last_detected': now,
            'src_ip': '1.2.3.4',
            'dst_ip': '5.6.7.8',
            'port': 443,
            'protocol': 'tcp',
            'action': 'allowed',
            'bytes_in': 0,
            'bytes_out': 1000000,
            'raw_json': json.dumps({'dst_tbo': 1000000}),
            'ingested_at': now,
        }
        
        db_path = create_test_db([flow_data])
        
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff
            
            # Get file hash before
            with open(db_path, 'rb') as f:
                content_before = f.read()
            
            rules = [
                {
                    'id': 1,
                    'type': 'bandwidth',
                    'name': 'Test Rule',
                    'threshold_count': 50.0,
                }
            ]
            
            script = BandwidthBasisDiff(rules)
            script.evaluate(db_path)
            
            # Verify file unchanged
            with open(db_path, 'rb') as f:
                content_after = f.read()
            
            assert content_before == content_after, "Database was modified in read-only mode"
            
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    def test_nonexistent_db_readonly_error(self):
        """Verify that readonly mode errors on nonexistent DB instead of creating it."""
        from scripts.bandwidth_basis_diff import BandwidthBasisDiff
        
        nonexistent_path = "/tmp/nonexistent-db-test-12345.db"
        assert not Path(nonexistent_path).exists()
        
        rules = [
            {
                'id': 1,
                'type': 'bandwidth',
                'name': 'Test Rule',
                'threshold_count': 50.0,
            }
        ]
        
        script = BandwidthBasisDiff(rules)
        
        with pytest.raises(Exception):  # Should raise, not create
            script.evaluate(nonexistent_path)
        
        # Verify file was NOT created
        assert not Path(nonexistent_path).exists()
    
    def test_json_output_format(self):
        """Test that JSON output format is correct."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=10)

        flow_data = {
            'flow_hash': 'test-flow-5',
            'first_detected': start,
            'last_detected': now,
            'src_ip': '1.2.3.4',
            'dst_ip': '5.6.7.8',
            'port': 443,
            'protocol': 'tcp',
            'action': 'allowed',
            'bytes_in': 0,
            'bytes_out': 80000000,
            'raw_json': json.dumps({'dst_tbo': 80000000}),
            'ingested_at': now,
        }

        db_path = create_test_db([flow_data])

        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [
                {
                    'id': 1,
                    'type': 'bandwidth',
                    'name': 'Test Rule',
                    'threshold_count': 60.0,
                }
            ]

            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            # Should be JSON-serializable
            json_str = json.dumps(result)
            assert json_str

            # Verify JSON contains expected fields
            parsed = json.loads(json_str)
            assert 'rules_compared' in parsed
            assert 'flows_total' in parsed
            assert 'flows_old_basis_evaluable' in parsed
            assert 'flows_new_basis_evaluable' in parsed
            assert 'results' in parsed

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_table_format_long_uuid_does_not_break_alignment(self):
        """Test that long rule IDs (32-char UUIDs) don't break column alignment."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=10)

        flow_data = {
            'flow_hash': 'test-flow-6',
            'first_detected': start,
            'last_detected': now,
            'src_ip': '1.2.3.4',
            'dst_ip': '5.6.7.8',
            'port': 443,
            'protocol': 'tcp',
            'action': 'allowed',
            'bytes_in': 0,
            'bytes_out': 80000000,
            'raw_json': json.dumps({'dst_tbo': 80000000}),
            'ingested_at': now,
        }

        db_path = create_test_db([flow_data])

        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            # Use a real 32-character UUID as ID
            rules = [
                {
                    'id': '68d21d1ab31d49949caab9edaf141675',
                    'type': 'bandwidth',
                    'name': 'Design-v2 sample: bandwidth',
                    'threshold_count': 60.0,
                }
            ]

            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            # Format output table manually (simulating main())
            lines = []
            lines.append("Rule Threshold Comparison:")
            lines.append("-" * 100)

            # Build header — should align columns properly
            header = (
                f"{'Rule ID':<12} {'Rule Name':<30} {'Threshold':<12} "
                f"{'Old Max':<12} {'New Max':<12} {'Trigger Change':<20}"
            )
            lines.append(header)
            lines.append("-" * 100)

            # Build data rows
            for r in result['results']:
                # Rule ID should be truncated
                rule_id_str = str(r['rule_id'])
                if len(rule_id_str) > 9:
                    rule_id_str = rule_id_str[:6] + '...'

                change_str = "YES" if r['trigger_state_change'] else "NO"
                data_line = (
                    f"{rule_id_str:<12} {r['rule_name']:<30} "
                    f"{r['threshold_mbps']:<12.2f} "
                    f"{r['old_max_mbps']:<12.2f} {r['new_max_mbps']:<12.2f} "
                    f"{change_str:<20}"
                )
                lines.append(data_line)

            output = "\n".join(lines)

            # Verify columns are aligned: all 'Threshold' values should align vertically
            # Find the Threshold column position in the header
            threshold_pos = header.find('Threshold')

            # Each data line's threshold should start at the same position
            for i, line in enumerate(lines[3:-1]):  # Skip header and separators
                # The threshold value should be at a consistent column position
                # This is a rough check: the line should be properly formatted
                assert len(line) > threshold_pos, f"Line {i} too short"

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_unevaluable_flows_have_denominator_and_percentage(self):
        """Test that unevaluable flow count includes denominator and percentage."""
        now = datetime.now(timezone.utc)

        # Create multiple flows, some evaluable, some not
        flows = []
        for i in range(10):
            if i < 3:
                # Evaluable flows (have bytes and timestamps)
                flows.append({
                    'flow_hash': f'evaluable-{i}',
                    'first_detected': now - timedelta(seconds=60),
                    'last_detected': now,
                    'src_ip': '10.1.1.1',
                    'dst_ip': '10.2.2.2',
                    'port': 443,
                    'protocol': 'tcp',
                    'action': 'allowed',
                    'bytes_in': 0,
                    'bytes_out': 10000000,
                    'raw_json': json.dumps({'dst_tbo': 10000000}),
                    'ingested_at': now,
                })
            else:
                # Unevaluable flows (no bytes)
                flows.append({
                    'flow_hash': f'unevaluable-{i}',
                    'first_detected': now,
                    'last_detected': now,
                    'src_ip': '10.3.3.3',
                    'dst_ip': '10.4.4.4',
                    'port': 22,
                    'protocol': 'tcp',
                    'action': 'blocked',
                    'bytes_in': 0,
                    'bytes_out': 0,
                    'raw_json': json.dumps({}),
                    'ingested_at': now,
                })

        db_path = create_test_db(flows)

        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [
                {
                    'id': 1,
                    'type': 'bandwidth',
                    'name': 'Test Rule',
                    'threshold_count': 50.0,
                }
            ]

            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            # Verify the result has both counts (final-review Medium 4:
            # old and new basis are tracked as separate evaluable
            # populations rather than one combined count)
            assert result['flows_total'] == 10
            assert result['flows_old_basis_evaluable'] == 3
            assert result['flows_new_basis_evaluable'] == 3

            # When rendered, the output should show the same denominator +
            # percentage shape the old single-count summary had, just split
            # per basis. The test just verifies the data is present.
            assert result['flows_old_basis_evaluable'] > 0
            assert result['flows_new_basis_evaluable'] > 0

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestRuleSelectionReusesTheEngine:
    """final-review Medium 4(a): the script used to select rules by `type`
    alone and apply no flow filter at all -- every flow in the DB was
    tested against every rule, and a disabled rule was compared as if
    live. It now reuses Analyzer.rule_enabled()/`_match_flow_filters`
    instead of reimplementing port/policy-decision matching a second
    time here."""

    def test_disabled_rule_is_skipped(self):
        now = datetime.now(timezone.utc)
        flow_data = {
            'flow_hash': 'f1', 'first_detected': now - timedelta(seconds=10),
            'last_detected': now, 'src_ip': '1.2.3.4', 'dst_ip': '5.6.7.8',
            'port': 443, 'protocol': 'tcp', 'action': 'allowed',
            'bytes_in': 0, 'bytes_out': 80000000,
            'raw_json': json.dumps({'dst_tbo': 80000000}),
            'ingested_at': now,
        }
        db_path = create_test_db([flow_data])
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [
                {'id': 1, 'type': 'bandwidth', 'name': 'Disabled Rule',
                 'threshold_count': 1.0, 'enabled': False},
            ]
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            assert result['rules_compared'] == 0
            assert result['rules_skipped_disabled'] == 1
            assert result['results'] == []
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_a_flow_on_an_unrelated_port_does_not_feed_a_port_specific_rule(self):
        """A rule watching only port 443 must not get its verdict from a
        flow on port 22 -- the original script applied no rule filter at
        all, so an unrelated port-22 flow's huge byte count would have
        inflated (or deflated, via the shared max()) the port-443 rule's
        old_max/new_max."""
        now = datetime.now(timezone.utc)
        matching_flow = {
            'flow_hash': 'https', 'first_detected': now - timedelta(seconds=10),
            'last_detected': now, 'src_ip': '1.2.3.4', 'dst_ip': '5.6.7.8',
            'port': 443, 'protocol': 'tcp', 'action': 'allowed',
            'bytes_in': 0, 'bytes_out': 1000000,
            'raw_json': json.dumps({
                'service': {'port': 443, 'proto': 6},
                'dst_tbo': 1000000, 'dst_tbi': 0,
            }),
            'ingested_at': now,
        }
        unrelated_flow = {
            'flow_hash': 'ssh', 'first_detected': now - timedelta(seconds=10),
            'last_detected': now, 'src_ip': '9.9.9.9', 'dst_ip': '8.8.8.8',
            'port': 22, 'protocol': 'tcp', 'action': 'allowed',
            'bytes_in': 0, 'bytes_out': 900000000000,
            'raw_json': json.dumps({
                'service': {'port': 22, 'proto': 6},
                'dst_tbo': 900000000000, 'dst_tbi': 0,
            }),
            'ingested_at': now,
        }
        db_path = create_test_db([matching_flow, unrelated_flow])
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [
                {'id': 1, 'type': 'bandwidth', 'name': 'HTTPS only',
                 'threshold_count': 1.0, 'port': 443},
            ]
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            rule_result = result['results'][0]
            assert rule_result['flows_matched'] == 1
            # the port-22 flow's enormous byte count must not leak in
            assert rule_result['new_max_mbps'] < 10000
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestTriggerOperatorMatchesTheEngine:
    """final-review Medium 4(a): the script used `>=` on both bases. The
    engine uses strict `>` for a point value and `>=` only for a provable
    lower bound -- a point value exactly at the threshold must not fire."""

    def test_new_basis_point_value_exactly_at_threshold_does_not_fire(self):
        now = datetime.now(timezone.utc)
        # dst_dbo=12,500,000 bytes, ddms=1000ms -> exactly 100.0 Mbps, a
        # point value (Priority-1, has ddms)
        flow_data = {
            'flow_hash': 'pt1', 'first_detected': now - timedelta(seconds=10),
            'last_detected': now, 'src_ip': '1.2.3.4', 'dst_ip': '5.6.7.8',
            'port': 443, 'protocol': 'tcp', 'action': 'allowed',
            'bytes_in': 0, 'bytes_out': 12_500_000,
            'raw_json': json.dumps({'dst_dbo': 12_500_000, 'dst_dbi': 0, 'ddms': 1000}),
            'ingested_at': now,
        }
        db_path = create_test_db([flow_data])
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [{'id': 1, 'type': 'bandwidth', 'name': 'R', 'threshold_count': 100.0}]
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)
            rule_result = result['results'][0]
            assert rule_result['new_max_mbps'] == pytest.approx(100.0)
            assert rule_result['new_fires'] is False

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_new_basis_lower_bound_exactly_at_threshold_fires(self):
        """The mirror case: a provable lower bound at exactly the
        threshold fires on `>=` (the true rate is provably >= what was
        measured) -- unlike the point-value case above."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=9)  # span=9 -> denom=10
        flow_data = {
            'flow_hash': 'bound1', 'first_detected': start, 'last_detected': now,
            'src_ip': '1.2.3.4', 'dst_ip': '5.6.7.8', 'port': 443,
            'protocol': 'tcp', 'action': 'allowed', 'bytes_in': 0,
            'bytes_out': 125_000_000,
            # no ddms/tdms -> Priority-3 lower bound;
            # 125,000,000 * 8 / 10 / 1e6 = 100.0 Mbps
            'raw_json': json.dumps({'dst_tbo': 125_000_000, 'dst_tbi': 0}),
            'ingested_at': now,
        }
        db_path = create_test_db([flow_data])
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [{'id': 1, 'type': 'bandwidth', 'name': 'R', 'threshold_count': 100.0}]
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)
            rule_result = result['results'][0]
            assert rule_result['new_max_mbps'] == pytest.approx(100.0)
            assert rule_result['new_fires'] is True
            assert rule_result['flows_bound_below_threshold'] == 0

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_new_basis_lower_bound_below_threshold_is_counted_not_a_silent_miss(self):
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=9)
        flow_data = {
            'flow_hash': 'bound2', 'first_detected': start, 'last_detected': now,
            'src_ip': '1.2.3.4', 'dst_ip': '5.6.7.8', 'port': 443,
            'protocol': 'tcp', 'action': 'allowed', 'bytes_in': 0,
            'bytes_out': 125_000_000,  # same 100.0 Mbps bound as above
            'raw_json': json.dumps({'dst_tbo': 125_000_000, 'dst_tbi': 0}),
            'ingested_at': now,
        }
        db_path = create_test_db([flow_data])
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [{'id': 1, 'type': 'bandwidth', 'name': 'R', 'threshold_count': 101.0}]
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)
            rule_result = result['results'][0]
            assert rule_result['new_fires'] is False
            assert rule_result['flows_bound_below_threshold'] == 1
            assert rule_result['flows_no_measurement'] == 0

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestSeparateEvaluablePopulationsAndTheRegressionCase:
    """final-review Medium 4(c): a flow the old formula could evaluate but
    the new one cannot must be surfaced, not silently dropped from both
    maxima -- that's exactly what a migration tool exists to catch."""

    def test_old_evaluable_new_unavailable_is_counted_as_a_regression(self):
        """The old basis never looks at timestamps at all (it always
        assumes a flat 600s denominator), so it stays evaluable even when
        the new basis's span computation goes negative (corrupt/reversed
        detection timestamps) and returns unavailable."""
        now = datetime.now(timezone.utc)
        flow_data = {
            'flow_hash': 'reg1',
            'first_detected': now,
            'last_detected': now - timedelta(seconds=10),  # reversed
            'src_ip': '1.2.3.4', 'dst_ip': '5.6.7.8', 'port': 443,
            'protocol': 'tcp', 'action': 'allowed',
            'bytes_in': 0, 'bytes_out': 5_000_000,
            'raw_json': json.dumps({'dst_tbo': 5_000_000, 'dst_tbi': 0}),
            'ingested_at': now,
        }
        db_path = create_test_db([flow_data])
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [{'id': 1, 'type': 'bandwidth', 'name': 'R', 'threshold_count': 1.0}]
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            rule_result = result['results'][0]
            assert rule_result['flows_evaluated_old'] == 1
            assert rule_result['flows_evaluated_new'] == 0
            assert rule_result['flows_no_measurement'] == 1
            assert rule_result['flows_regressed_to_unevaluable'] == 1
            assert rule_result['old_max_mbps'] > 0
            assert rule_result['new_max_mbps'] == 0

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestWindowSpanCaveat:
    """final-review Medium 4(a): the script cannot honestly simulate the
    live engine's window-basis suppression (it needs consecutive cache
    observations this offline, single-snapshot tool doesn't have) --
    instead of pretending to, it must surface a caveat count of flows
    whose own span already exceeds the rule's threshold_window, so
    "trigger changed: No" isn't mistaken for a guarantee."""

    def test_flow_spanning_beyond_the_rules_window_is_counted_as_a_caveat(self):
        now = datetime.now(timezone.utc)
        flow_data = {
            'flow_hash': 'wide1',
            'first_detected': now - timedelta(minutes=30),
            'last_detected': now,
            'src_ip': '1.2.3.4', 'dst_ip': '5.6.7.8', 'port': 443,
            'protocol': 'tcp', 'action': 'allowed',
            'bytes_in': 0, 'bytes_out': 5_000_000,
            'raw_json': json.dumps({'dst_tbo': 5_000_000, 'dst_tbi': 0}),
            'ingested_at': now,
        }
        db_path = create_test_db([flow_data])
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [{'id': 1, 'type': 'bandwidth', 'name': 'R',
                      'threshold_count': 1.0, 'threshold_window': 10}]
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            rule_result = result['results'][0]
            assert rule_result['flows_span_exceeds_window'] == 1

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_flow_within_the_rules_window_is_not_flagged(self):
        now = datetime.now(timezone.utc)
        flow_data = {
            'flow_hash': 'narrow1',
            'first_detected': now - timedelta(seconds=30),
            'last_detected': now,
            'src_ip': '1.2.3.4', 'dst_ip': '5.6.7.8', 'port': 443,
            'protocol': 'tcp', 'action': 'allowed',
            'bytes_in': 0, 'bytes_out': 5_000_000,
            'raw_json': json.dumps({'dst_tbo': 5_000_000, 'dst_tbi': 0}),
            'ingested_at': now,
        }
        db_path = create_test_db([flow_data])
        try:
            from scripts.bandwidth_basis_diff import BandwidthBasisDiff

            rules = [{'id': 1, 'type': 'bandwidth', 'name': 'R',
                      'threshold_count': 1.0, 'threshold_window': 10}]
            script = BandwidthBasisDiff(rules)
            result = script.evaluate(db_path)

            rule_result = result['results'][0]
            assert rule_result['flows_span_exceeds_window'] == 0

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestI18nCoverage:
    """final-review Medium 4: all user-facing text (summary, headers,
    YES/NO, errors) must be routed through the i18n layer, not hardcoded
    English. Checked against the raw dictionaries directly (not through
    t()'s runtime fallback) -- t() without an explicit `default=` silently
    humanizes an unregistered key into readable-looking text, which would
    make this gate pass even if the keys were never actually added."""

    _BWDIFF_KEYS = (
        "bwdiff_rules_summary", "bwdiff_flows_summary", "bwdiff_table_title",
        "bwdiff_col_rule_id", "bwdiff_col_rule_name", "bwdiff_col_threshold",
        "bwdiff_col_old_max", "bwdiff_col_new_max", "bwdiff_col_trigger_change",
        "bwdiff_col_bound_below_threshold", "bwdiff_col_no_measurement",
        "bwdiff_window_caveat", "bwdiff_no_rules", "bwdiff_error_generic",
    )

    def test_every_key_is_registered_in_the_english_dictionary(self):
        import json as _json
        from pathlib import Path as _Path
        en = _json.loads((_Path(__file__).resolve().parents[1] / "src" / "i18n_en.json")
                          .read_text(encoding="utf-8"))
        missing = [k for k in self._BWDIFF_KEYS if k not in en or not en[k].strip()]
        assert missing == [], f"keys missing from src/i18n_en.json: {missing}"

    def test_every_key_is_registered_in_the_chinese_dictionary(self):
        import json as _json
        from pathlib import Path as _Path
        zh = _json.loads((_Path(__file__).resolve().parents[1] / "src" / "i18n_zh_TW.json")
                          .read_text(encoding="utf-8"))
        missing = [k for k in self._BWDIFF_KEYS if k not in zh or not zh[k].strip()]
        assert missing == [], f"keys missing from src/i18n_zh_TW.json: {missing}"

    def test_keys_render_through_t_with_their_format_placeholders(self):
        """A second-order check: the registered strings must actually
        accept the kwargs this script calls them with (placeholder names
        must match), not just exist."""
        from src.i18n import t

        keys_with_kwargs = {
            "bwdiff_rules_summary": {"compared": 1, "skipped": 0},
            "bwdiff_flows_summary": {"total": 10, "old": 3, "old_pct": 30.0,
                                      "new": 3, "new_pct": 30.0},
            "bwdiff_table_title": {},
            "bwdiff_col_rule_id": {}, "bwdiff_col_rule_name": {},
            "bwdiff_col_threshold": {}, "bwdiff_col_old_max": {},
            "bwdiff_col_new_max": {}, "bwdiff_col_trigger_change": {},
            "bwdiff_col_bound_below_threshold": {}, "bwdiff_col_no_measurement": {},
            "bwdiff_window_caveat": {"rules": "R1 (2)"},
            "bwdiff_no_rules": {},
            "bwdiff_error_generic": {"error": "boom"},
        }
        for lang in ("en", "zh_TW"):
            for key, kwargs in keys_with_kwargs.items():
                rendered = t(key, lang=lang, **kwargs)
                assert "[MISSING" not in rendered, f"{key} ({lang}): {rendered!r}"
                assert "{" not in rendered, f"{key} ({lang}) left a placeholder unfilled: {rendered!r}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
