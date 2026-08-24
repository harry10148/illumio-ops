"""Compare bandwidth alert thresholds across old and new basis.

Reads a cache DB and, for each ENABLED bandwidth rule, shows:
- Maximum measured bandwidth under the old basis (bytes * 8 / 600s)
- Maximum measured bandwidth under the new basis (bytes * 8 / (span+1)s)
- Whether the rule's trigger state would change
- How many matched flows fell into the new basis's two inconclusive
  states: a lower bound that didn't reach the threshold, and no
  measurement at all (spec appendix §4.4's required columns)

Flows are filtered per rule the same way the live rule engine does --
reusing Analyzer.rule_enabled()/`_match_flow_filters()` rather than
reimplementing port/policy-decision/label/IP matching a second time here
-- so a rule watching only one port doesn't get its verdict from an
unrelated flow on a different port, and a disabled rule isn't compared
at all.

Trigger determination mirrors the engine exactly: the old basis (which
never produced anything but a single point value) fires on a strict '>'
of the threshold; the new basis fires on '>' for a point value and '>='
only for a provable lower bound -- never '>=' for both, which would
claim a trigger the engine will not produce.

What this tool does NOT simulate: the live engine's window-basis
suppression (bucket-basis guard), which needs consecutive cache
observations to derive a per-window delta -- state this offline,
single-snapshot comparison has no access to. Instead, it reports how
many of a rule's matched flows have their OWN aggregation span already
exceeding that rule's threshold_window, as a caveat: the live engine may
derive a delta for those flows (and evaluate normally) or may suppress
the rule entirely for the cycle -- this tool cannot tell which, so a
"trigger changed: NO" for a rule with a nonzero caveat count should be
verified against live behavior, not taken as the final word.

The old formula is hardcoded here verbatim -- not reused from analyzer.py
because it's being retired.

Usage:
    python scripts/bandwidth_basis_diff.py --db /path/to/cache.db
    python scripts/bandwidth_basis_diff.py --db /path/to/cache.db --json

Exit code: 0 on success, 1 on error.
"""
from __future__ import annotations

import argparse
import json as json_module
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analyzer import Analyzer, BOUND_BASIS_NOTE, calculate_mbps, rule_enabled
from src.i18n import t
from src.interfaces import IApiClient, IReporter


@dataclass
class BandwidthComparison:
    """Result for one rule's threshold comparison."""

    rule_id: Any
    rule_name: str
    threshold_mbps: float
    old_max_mbps: float
    new_max_mbps: float
    old_fires: bool
    new_fires: bool
    trigger_state_change: bool
    flows_matched: int
    flows_evaluated_old: int
    flows_evaluated_new: int
    flows_bound_below_threshold: int
    flows_no_measurement: int
    flows_regressed_to_unevaluable: int
    flows_span_exceeds_window: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "threshold_mbps": self.threshold_mbps,
            "old_max_mbps": round(self.old_max_mbps, 2),
            "new_max_mbps": round(self.new_max_mbps, 2),
            "old_fires": self.old_fires,
            "new_fires": self.new_fires,
            "trigger_state_change": self.trigger_state_change,
            "flows_matched": self.flows_matched,
            "flows_evaluated_old": self.flows_evaluated_old,
            "flows_evaluated_new": self.flows_evaluated_new,
            "flows_bound_below_threshold": self.flows_bound_below_threshold,
            "flows_no_measurement": self.flows_no_measurement,
            "flows_regressed_to_unevaluable": self.flows_regressed_to_unevaluable,
            "flows_span_exceeds_window": self.flows_span_exceeds_window,
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


def _flow_span_seconds(flow: dict[str, Any]) -> Optional[float]:
    start = _flow_aggregation_start(flow)
    end = _flow_aggregation_end(flow)
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def calculate_mbps_old_basis(flow: dict[str, Any]) -> Optional[float]:
    """
    OLD BANDWIDTH FORMULA (hardcoded here — not calling analyzer.py).

    Computes bandwidth in Mbps using the pre-span basis:

    Priority 1: delta bytes / ddms → Mbps (Interval)
    Priority 2: total bytes / tdms → Mbps (Avg)
                If no tdms: use interval_sec (default 600) as denominator

    Returns None if no bytes or time reference available. The old basis
    never produced a "lower bound" concept -- every value it returns is
    used as a plain point value by the caller.
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


def _build_matcher() -> Analyzer:
    """A throwaway Analyzer instance used only for its (pure, no-network)
    rule x flow matching methods (check_flow_match / _match_flow_filters) --
    reusing the rule engine's own matcher instead of reimplementing port/
    policy-decision/label/IP filtering a second time here (final-review
    Medium 4). api_client=None is safe: those methods only reach for
    self.api in the services/ex_services object-filter branch, and
    getattr(None, ...) degrades to the same fail-closed behavior the live
    engine already has when no label cache is available -- an existing,
    documented limitation this tool inherits rather than introduces.
    """
    # cast, not # type: ignore: Analyzer's methods used here
    # (check_flow_match/_match_flow_filters) only reach for self.api in a
    # branch that already degrades gracefully via getattr(None, ...) --
    # see the docstring above. The Protocols type api_client/reporter as
    # non-Optional (analyzer.py's own __init__ comment notes this is
    # looser than ideal), so a real None needs an explicit cast to satisfy
    # the annotation without lying about it at runtime.
    return Analyzer(SimpleNamespace(config={}), cast(IApiClient, None), cast(IReporter, None))


class BandwidthBasisDiff:
    """Compare bandwidth thresholds across old and new basis."""

    def __init__(self, rules: list[dict[str, Any]] | None = None):
        """Initialize with optional rule list (for testing)."""
        self.rules = rules or []
        self._matcher = _build_matcher()

    def evaluate(self, db_path: str) -> dict[str, Any]:
        """
        Evaluate all matching flows against all enabled bandwidth rules.

        Opens DB in read-only mode using sqlite3's file: URI.
        Returns dict with:
        - rules_compared: count of ENABLED bandwidth rules
        - rules_skipped_disabled: count of disabled bandwidth rules excluded
        - flows_total / flows_old_basis_evaluable / flows_new_basis_evaluable:
          whole-DB counts, independent of any rule's filters
        - results: list of per-rule comparisons (see BandwidthComparison)
        """
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Cache DB not found: {db_path}")

        # Open in read-only mode using sqlite3's file: URI
        # This ensures we cannot write to the database
        file_uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(file_uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row

        try:
            bandwidth_rules = [r for r in self.rules if r.get("type") == "bandwidth"]
            enabled_rules = [r for r in bandwidth_rules if rule_enabled(r)]
            rules_skipped_disabled = len(bandwidth_rules) - len(enabled_rules)

            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, flow_hash, first_detected, last_detected,
                          bytes_in, bytes_out, raw_json
                   FROM pce_traffic_flows_raw
                   ORDER BY id"""
            )
            flows_data = cursor.fetchall()

            flows_total = len(flows_data)
            flows_old_basis_evaluable = 0
            flows_new_basis_evaluable = 0
            for flow_row in flows_data:
                flow = self._reconstruct_flow(flow_row)
                if calculate_mbps_old_basis(flow) is not None:
                    flows_old_basis_evaluable += 1
                new_mbps, _note, _bytes, _denom = calculate_mbps(flow)
                if new_mbps is not None:
                    flows_new_basis_evaluable += 1

            results = [self._evaluate_rule(rule, flows_data) for rule in enabled_rules]

            return {
                "rules_compared": len(enabled_rules),
                "rules_skipped_disabled": rules_skipped_disabled,
                "flows_total": flows_total,
                "flows_old_basis_evaluable": flows_old_basis_evaluable,
                "flows_new_basis_evaluable": flows_new_basis_evaluable,
                "results": [r.to_dict() for r in results],
            }

        finally:
            conn.close()

    def _reconstruct_flow(self, flow_row: sqlite3.Row) -> dict[str, Any]:
        """Rebuild a flow dict from a DB row -- base fields from the
        indexed columns, overlaid with the original PCE payload (raw_json)
        so the rule matcher sees src/dst/service/policy_decision the same
        way it would on a live flow."""
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

        flow: dict[str, Any] = {
            "first_detected": first_detected,
            "last_detected": last_detected,
            "bytes_in": flow_row["bytes_in"],
            "bytes_out": flow_row["bytes_out"],
        }

        if flow_row["raw_json"]:
            try:
                raw = json_module.loads(flow_row["raw_json"])
                flow.update(raw)
            except (json_module.JSONDecodeError, TypeError):
                pass

        return flow

    def _evaluate_rule(self, rule: dict[str, Any], flows_data: list[sqlite3.Row]) -> BandwidthComparison:
        rule_id = rule.get("id", "unknown")
        rule_name = rule.get("name", f"Rule {rule_id}")
        threshold_mbps = float(rule.get("threshold_count", 0))
        threshold_window_seconds = _safe_float(rule.get("threshold_window", 10)) * 60.0

        old_max = 0.0
        new_max = 0.0
        new_trigger = False
        flows_matched = 0
        flows_evaluated_old = 0
        flows_evaluated_new = 0
        flows_bound_below_threshold = 0
        flows_no_measurement = 0
        flows_regressed = 0
        flows_span_exceeds_window = 0

        for flow_row in flows_data:
            flow = self._reconstruct_flow(flow_row)
            # Same rule x flow matcher the live engine uses (port,
            # src/dst IP/label, policy decision, proto, ...) -- window_start
            # is None because there is no live "now" for a historical,
            # whole-DB comparison; strict_window=False matches this
            # tool's read path, same as query_flows/dashboard's client-side
            # cache filtering.
            if not self._matcher._match_flow_filters(rule, flow, None, strict_window=False):
                continue
            flows_matched += 1

            old_mbps = calculate_mbps_old_basis(flow)
            new_mbps, new_note, _bytes, _denom = calculate_mbps(flow)

            if old_mbps is not None:
                flows_evaluated_old += 1
                old_max = max(old_max, old_mbps)

            if new_mbps is None:
                flows_no_measurement += 1
            else:
                flows_evaluated_new += 1
                new_max = max(new_max, new_mbps)
                if new_note == BOUND_BASIS_NOTE:
                    # Mirrors the engine (analyzer.py's _run_rule_engine):
                    # a lower bound triggers on '>=' since the true rate is
                    # provably >= what was measured.
                    if new_mbps >= threshold_mbps:
                        new_trigger = True
                    else:
                        flows_bound_below_threshold += 1
                elif new_mbps > threshold_mbps:
                    new_trigger = True

            if old_mbps is not None and new_mbps is None:
                # The case a migration tool exists to surface: this flow
                # used to produce a (possibly inflated) old-basis number
                # and now produces nothing at all.
                flows_regressed += 1

            span = _flow_span_seconds(flow)
            if span is not None and span > threshold_window_seconds:
                flows_span_exceeds_window += 1

        # The old basis never produced a bound -- every evaluable value was
        # a plain point value, so "did the max exceed the threshold" is
        # equivalent to "did any flow exceed it" (strict '>', matching
        # the engine's bandwidth comparison operator, unchanged by this
        # branch). The new basis cannot use this shortcut: a bound flow at
        # exactly the threshold fires on '>=' even when a larger point
        # value elsewhere in the population does not reach it, so
        # new_trigger is tracked per-flow above, not derived from new_max.
        old_fires = flows_evaluated_old > 0 and old_max > threshold_mbps
        trigger_state_change = old_fires != new_trigger

        return BandwidthComparison(
            rule_id=rule_id,
            rule_name=rule_name,
            threshold_mbps=threshold_mbps,
            old_max_mbps=old_max,
            new_max_mbps=new_max,
            old_fires=old_fires,
            new_fires=new_trigger,
            trigger_state_change=trigger_state_change,
            flows_matched=flows_matched,
            flows_evaluated_old=flows_evaluated_old,
            flows_evaluated_new=flows_evaluated_new,
            flows_bound_below_threshold=flows_bound_below_threshold,
            flows_no_measurement=flows_no_measurement,
            flows_regressed_to_unevaluable=flows_regressed,
            flows_span_exceeds_window=flows_span_exceeds_window,
        )


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
        # Load rules from config. ConfigManager also resolves settings.language
        # and calls set_language() as a side effect of loading -- every t()
        # call below picks it up without this script threading `lang` through
        # by hand.
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
            print(t(
                "bwdiff_rules_summary",
                default="{compared} enabled bandwidth rule(s) compared "
                        "({skipped} disabled rule(s) skipped)",
                compared=result["rules_compared"],
                skipped=result["rules_skipped_disabled"],
            ))

            total_flows = result["flows_total"]
            old_ev = result["flows_old_basis_evaluable"]
            new_ev = result["flows_new_basis_evaluable"]
            old_pct = (old_ev / total_flows * 100) if total_flows > 0 else 0
            new_pct = (new_ev / total_flows * 100) if total_flows > 0 else 0
            print(t(
                "bwdiff_flows_summary",
                default="Flows in cache: {total:,} total | old-basis evaluable: "
                        "{old:,} ({old_pct:.1f}%) | new-basis evaluable: {new:,} "
                        "({new_pct:.1f}%)",
                total=total_flows, old=old_ev, old_pct=old_pct,
                new=new_ev, new_pct=new_pct,
            ))
            print()

            if result["results"]:
                print(t("bwdiff_table_title", default="Rule Threshold Comparison:"))
                print("-" * 130)
                header = (
                    f"{t('bwdiff_col_rule_id', default='Rule ID'):<12} "
                    f"{t('bwdiff_col_rule_name', default='Rule Name'):<30} "
                    f"{t('bwdiff_col_threshold', default='Threshold'):<12} "
                    f"{t('bwdiff_col_old_max', default='Old Max'):<12} "
                    f"{t('bwdiff_col_new_max', default='New Max'):<12} "
                    f"{t('bwdiff_col_trigger_change', default='Trigger Change'):<16} "
                    f"{t('bwdiff_col_bound_below_threshold', default='Bound<Thr'):<10} "
                    f"{t('bwdiff_col_no_measurement', default='NoMeasure'):<10}"
                )
                print(header)
                print("-" * 130)

                window_caveat_rules = []
                for r in result["results"]:
                    change_str = t("rpt_yes", default="Yes") if r["trigger_state_change"] \
                        else t("rpt_no", default="No")

                    # Truncate long rule IDs (32-char UUIDs) to fit column
                    rule_id_str = str(r["rule_id"])
                    if len(rule_id_str) > 9:
                        rule_id_str = rule_id_str[:6] + "..."

                    print(
                        f"{rule_id_str:<12} {r['rule_name']:<30} "
                        f"{r['threshold_mbps']:<12.2f} "
                        f"{r['old_max_mbps']:<12.2f} {r['new_max_mbps']:<12.2f} "
                        f"{change_str:<16} "
                        f"{r['flows_bound_below_threshold']:<10} "
                        f"{r['flows_no_measurement']:<10}"
                    )
                    if r["flows_span_exceeds_window"]:
                        window_caveat_rules.append((r["rule_name"], r["flows_span_exceeds_window"]))

                print("-" * 130)

                if window_caveat_rules:
                    print()
                    print(t(
                        "bwdiff_window_caveat",
                        default="Caveat -- not simulated above, per rule (matched "
                                "flow count in parentheses): {rules}. Those flows' "
                                "own span already exceeds the rule's "
                                "threshold_window. The live engine may derive a "
                                "per-window delta from cache observations for them, "
                                "or suppress the rule entirely for the cycle -- this "
                                "offline comparison has no cache history to tell "
                                "which. Verify these rules against live behavior "
                                "(or the monitor's own logs/meta-alerts) before "
                                "relying on \"trigger changed: No\" for them.",
                        rules=", ".join(
                            f"{name} ({n})" for name, n in window_caveat_rules
                        ),
                    ))
            else:
                print(t("bwdiff_no_rules", default="No enabled bandwidth rules to compare."))

        return 0

    except FileNotFoundError as e:
        print(t("bwdiff_error_generic", default="Error: {error}", error=str(e)), file=sys.stderr)
        return 1
    except Exception as e:
        print(t("bwdiff_error_generic", default="Error: {error}", error=str(e)), file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
