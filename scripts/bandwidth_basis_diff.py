"""Compare bandwidth alert thresholds across old and new basis.

Reads a cache DB and for each configured bandwidth rule, shows:
- Maximum measured bandwidth under old basis (bytes * 8 / 600s)
- Maximum measured bandwidth under new basis (bytes * 8 / (span+1)s)
- Whether the rule's trigger state would change

The old formula is hardcoded here verbatim — not reused from analyzer.py
because it's being retired.

Usage:
    python scripts/bandwidth_basis_diff.py --db /path/to/cache.db
    python scripts/bandwidth_basis_diff.py --db /path/to/cache.db --json

Exit code: 0 on success, 1 on error.
"""
from __future__ import annotations

import argparse
import json as json_module
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analyzer import calculate_mbps, BOUND_BASIS_NOTE
from src.pce_cache.models import Base, PceTrafficFlowRaw


@dataclass
class BandwidthComparison:
    """Result for one rule's threshold comparison."""

    rule_id: Any
    rule_name: str
    threshold_mbps: float
    old_max_mbps: float
    new_max_mbps: float
    trigger_state_old: bool
    trigger_state_new: bool
    trigger_state_change: bool
    flows_evaluated: int = 0
    flows_unevaluable: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "threshold_mbps": self.threshold_mbps,
            "old_max_mbps": round(self.old_max_mbps, 2),
            "new_max_mbps": round(self.new_max_mbps, 2),
            "old_fires": self.trigger_state_old,
            "new_fires": self.trigger_state_new,
            "trigger_state_change": self.trigger_state_change,
            "flows_evaluated": self.flows_evaluated,
            "flows_unevaluable": self.flows_unevaluable,
        }


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value to float safely."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _flow_aggregation_end(flow: dict[str, Any]) -> Optional[datetime]:
    """Get flow aggregation end time (last_detected)."""
    ts = flow.get("last_detected")
    if not ts:
        tr = flow.get("timestamp_range")
        ts = tr.get("last_detected") if isinstance(tr, dict) else None

    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
    return None


def _flow_aggregation_start(flow: dict[str, Any]) -> Optional[datetime]:
    """Get flow aggregation start time (first_detected)."""
    ts = flow.get("first_detected")
    if not ts:
        tr = flow.get("timestamp_range")
        ts = tr.get("first_detected") if isinstance(tr, dict) else None

    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
    return None


def calculate_mbps_old_basis(flow: dict[str, Any]) -> Optional[float]:
    """
    OLD BANDWIDTH FORMULA (hardcoded here — not calling analyzer.py).

    Computes bandwidth in Mbps using the pre-span basis:

    Priority 1: delta bytes / ddms → Mbps (Interval)
    Priority 2: total bytes / tdms → Mbps (Avg)
                If no tdms: use interval_sec (default 600) as denominator

    Returns None if no bytes or time reference available.
    """
    # Priority 1: delta interval
    delta_bytes = _safe_float(flow.get("dst_dbo") or flow.get("dbo") or 0) + \
                  _safe_float(flow.get("dst_dbi") or flow.get("dbi") or 0)
    ddms = _safe_float(flow.get("ddms") or 0)

    if delta_bytes > 0 and ddms > 0:
        if ddms < 1000:
            ddms = 1000.0
        val = (delta_bytes * 8.0) / (ddms / 1000.0) / 1000000.0
        return val

    # Priority 2: total bytes
    tbo = _safe_float(flow.get("dst_tbo") or flow.get("tbo") or flow.get("dst_bo") or 0)
    tbi = _safe_float(flow.get("dst_tbi") or flow.get("tbi") or flow.get("dst_bi") or 0)
    total_bytes = tbo + tbi
    tdms = _safe_float(flow.get("tdms") or 0)

    if tdms <= 0:
        # No tdms: use interval_sec (default 600 seconds)
        interval_sec = _safe_float(flow.get("interval_sec", 600))
        tdms = interval_sec * 1000.0
    elif tdms < 1000:
        # Microsecond resolution — clamp to 1 second minimum
        tdms = 1000.0

    if total_bytes > 0 and tdms > 0:
        val = (total_bytes * 8.0) / (tdms / 1000.0) / 1000000.0
        return val

    return None


class BandwidthBasisDiff:
    """Compare bandwidth thresholds across old and new basis."""

    def __init__(self, rules: list[dict[str, Any]] | None = None):
        """Initialize with optional rule list (for testing)."""
        self.rules = rules or []

    def evaluate(self, db_path: str) -> dict[str, Any]:
        """
        Evaluate all flows against all bandwidth rules.

        Opens DB in read-only mode using sqlite3's file: URI.
        Returns dict with:
        - rules_compared: count of bandwidth rules
        - flows_evaluated: count of flows that could be evaluated
        - flows_unevaluable: count of flows without usable data
        - results: list of per-rule comparisons
        """
        # Verify DB file exists before trying to open
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Cache DB not found: {db_path}")

        # Open in read-only mode using sqlite3's file: URI
        # This ensures we cannot write to the database
        file_uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(file_uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row

        try:
            # Filter to bandwidth rules only
            bandwidth_rules = [
                r for r in self.rules if r.get("type") == "bandwidth"
            ]

            results = []
            total_evaluated = 0
            total_unevaluable = 0

            # Fetch all flows from cache
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, flow_hash, first_detected, last_detected,
                          bytes_in, bytes_out, raw_json
                   FROM pce_traffic_flows_raw
                   ORDER BY id"""
            )
            flows_data = cursor.fetchall()

            for rule in bandwidth_rules:
                rule_id = rule.get("id", "unknown")
                rule_name = rule.get("name", f"Rule {rule_id}")
                threshold_mbps = float(rule.get("threshold_count", 0))

                old_max = 0.0
                new_max = 0.0
                evaluated_count = 0
                unevaluable_count = 0

                for flow_row in flows_data:
                    # Reconstruct flow dict from DB row
                    # Parse timestamps
                    first_detected = flow_row["first_detected"]
                    if isinstance(first_detected, str):
                        try:
                            first_detected = datetime.fromisoformat(
                                first_detected.replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            first_detected = None

                    last_detected = flow_row["last_detected"]
                    if isinstance(last_detected, str):
                        try:
                            last_detected = datetime.fromisoformat(
                                last_detected.replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            last_detected = None

                    flow = {
                        "first_detected": first_detected,
                        "last_detected": last_detected,
                        "bytes_in": flow_row["bytes_in"],
                        "bytes_out": flow_row["bytes_out"],
                    }

                    # Parse raw_json if present
                    if flow_row["raw_json"]:
                        try:
                            raw = json_module.loads(flow_row["raw_json"])
                            flow.update(raw)
                        except (json_module.JSONDecodeError, TypeError):
                            pass

                    # Calculate old basis
                    old_mbps = calculate_mbps_old_basis(flow)

                    # Calculate new basis
                    new_mbps, new_note, _, _ = calculate_mbps(flow)

                    if old_mbps is not None and new_mbps is not None:
                        old_max = max(old_max, old_mbps)
                        new_max = max(new_max, new_mbps)
                        evaluated_count += 1
                    else:
                        unevaluable_count += 1

                total_evaluated = max(total_evaluated, evaluated_count)
                total_unevaluable = max(total_unevaluable, unevaluable_count)

                # Determine trigger states (>= threshold fires)
                trigger_state_old = old_max >= threshold_mbps
                trigger_state_new = new_max >= threshold_mbps
                trigger_state_change = trigger_state_old != trigger_state_new

                comparison = BandwidthComparison(
                    rule_id=rule_id,
                    rule_name=rule_name,
                    threshold_mbps=threshold_mbps,
                    old_max_mbps=old_max,
                    new_max_mbps=new_max,
                    trigger_state_old=trigger_state_old,
                    trigger_state_new=trigger_state_new,
                    trigger_state_change=trigger_state_change,
                    flows_evaluated=evaluated_count,
                    flows_unevaluable=unevaluable_count,
                )

                results.append(comparison)

            return {
                "rules_compared": len(bandwidth_rules),
                "flows_evaluated": total_evaluated,
                "flows_unevaluable": total_unevaluable,
                "results": [r.to_dict() for r in results],
            }

        finally:
            conn.close()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to cache database (opened read-only)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable table",
    )

    args = parser.parse_args()

    try:
        # Load rules from config
        from src.config import ConfigManager

        cm = ConfigManager()
        rules = cm.config.get("rules", [])

        # Evaluate
        script = BandwidthBasisDiff(rules)
        result = script.evaluate(args.db)

        # Output
        if args.json:
            print(json_module.dumps(result, indent=2))
        else:
            # Human-readable table
            print(f"Rules compared: {result['rules_compared']}")

            # Show flows with denominator and percentage
            total_flows = result['flows_evaluated'] + result['flows_unevaluable']
            eval_pct = (result['flows_evaluated'] / total_flows * 100) if total_flows > 0 else 0
            uneval_pct = (result['flows_unevaluable'] / total_flows * 100) if total_flows > 0 else 0

            print(
                f"Flows: {total_flows:,} total | "
                f"{result['flows_evaluated']:,} evaluated ({eval_pct:.1f}%) | "
                f"{result['flows_unevaluable']:,} unevaluable ({uneval_pct:.1f}%)"
            )
            print()

            if result["results"]:
                print("Rule Threshold Comparison:")
                print("-" * 100)
                print(
                    f"{'Rule ID':<12} {'Rule Name':<30} {'Threshold':<12} "
                    f"{'Old Max':<12} {'New Max':<12} {'Trigger Change':<20}"
                )
                print("-" * 100)

                for r in result["results"]:
                    change_str = "YES" if r["trigger_state_change"] else "NO"

                    # Truncate long rule IDs (32-char UUIDs) to fit column
                    rule_id_str = str(r['rule_id'])
                    if len(rule_id_str) > 9:
                        rule_id_str = rule_id_str[:6] + "..."

                    print(
                        f"{rule_id_str:<12} {r['rule_name']:<30} "
                        f"{r['threshold_mbps']:<12.2f} "
                        f"{r['old_max_mbps']:<12.2f} {r['new_max_mbps']:<12.2f} "
                        f"{change_str:<20}"
                    )

                print("-" * 100)

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
