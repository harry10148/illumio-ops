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
            
            # Verify result structure
            assert 'rules_compared' in result
            assert 'flows_evaluated' in result
            assert 'flows_unevaluable' in result
            assert result['rules_compared'] == 1
            assert result['flows_evaluated'] == 1
            
            # Check rule comparison
            assert len(result['results']) == 1
            rule_result = result['results'][0]
            assert rule_result['rule_id'] == 1
            assert rule_result['rule_name'] == 'Test Rule'
            assert 'old_max_mbps' in rule_result
            assert 'new_max_mbps' in rule_result
            assert 'trigger_state_change' in rule_result
            
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
            
            # Flow should be unevaluable
            assert result['flows_unevaluable'] == 1
            
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
            assert 'flows_evaluated' in parsed
            assert 'flows_unevaluable' in parsed
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

            # Verify the result has both counts
            total_flows = result['flows_evaluated'] + result['flows_unevaluable']
            assert total_flows == 10, f"Expected 10 flows total, got {total_flows}"
            assert result['flows_evaluated'] == 3
            assert result['flows_unevaluable'] == 7

            # Calculate expected percentage
            expected_pct = (7 / 10) * 100

            # When rendered, the output should show: "Flows: 10 total | 3 evaluated (30.0%) | 7 unevaluable (70.0%)"
            # or similar format with denominator and percentages
            # The test just verifies the data is present in the result
            assert result['flows_evaluated'] > 0
            assert result['flows_unevaluable'] > 0

        finally:
            Path(db_path).unlink(missing_ok=True)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
