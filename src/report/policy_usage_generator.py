"""
src/report/policy_usage_generator.py
Orchestrates the generation of the Policy Usage Report.

Approach (per-rule async query, matching workloader rule-usage):
  1. Fetch draft rulesets → baseline rule list
  2. For each rule, submit an individual async traffic query using the
     rule's consumers→sources, providers→destinations, services→services
  3. Count returned flows per rule to determine hit/unused status
  4. Export HTML / CSV

Also supports importing workloader CSV output via generate_from_csv().
"""
import datetime
import json
from loguru import logger
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from src.i18n import t
from src.report.dashboard_summaries import write_policy_usage_dashboard_summary
from src.report.report_metadata import (
    attack_summary_counts,
    build_attack_summary_brief,
    extract_attack_summary,
)

@dataclass
class PolicyUsageResult:
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    record_count: int = 0          # total rules in baseline
    date_range: tuple = ('', '')
    lookback_days: int = 30
    module_results: dict = field(default_factory=dict)
    dataframe: object = None       # flat rules DataFrame for CSV export
    execution_stats: dict = field(default_factory=dict)

class PolicyUsageGenerator:
    def __init__(self, config_manager, api_client=None, config_dir: str = 'config'):
        self.cm = config_manager
        self.api = api_client
        self._config_dir = config_dir

    # ── Public interface ───────────────────────────────────────────────────────

    def generate_from_api(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> PolicyUsageResult:
        """Fetch draft policies and run per-rule async traffic queries."""
        if not self.api:
            raise RuntimeError("api_client required for policy usage generation")

        if not end_date:
            end_date = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        if not start_date:
            start_date = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
            ).isoformat().replace("+00:00", "Z")

        # Compute lookback days from date range
        try:
            end_dt   = datetime.datetime.fromisoformat(end_date.rstrip("Z"))
            start_dt = datetime.datetime.fromisoformat(start_date.rstrip("Z"))
            lookback_days = max(1, (end_dt - start_dt).days)
        except Exception:
            lookback_days = 30  # intentional fallback: use default if date range cannot be parsed

        # Step 1 — load label/service cache for actor resolution
        print(t("rpt_pu_fetching_rulesets"))
        try:
            self.api.update_label_cache(silent=True)
        except Exception as e:
            logger.warning(f"Label cache update failed (non-fatal): {e}")

        # Step 2 — fetch draft rulesets (matching workloader behaviour)
        rulesets = self.api.get_all_rulesets(force_refresh=True)
        if not rulesets:
            logger.warning("get_all_rulesets() returned empty list")
            return PolicyUsageResult(record_count=0)

        flat_rules, ruleset_map = self._build_baseline(rulesets)
        print(t("rpt_pu_rules_found", count=len(flat_rules)))

        if not flat_rules:
            return PolicyUsageResult(record_count=0)

        # Step 3 — per-rule async traffic queries
        print(t("rpt_pu_fetching_traffic", start=start_date[:10], end=end_date[:10]))
        hit_hrefs, hit_counts, execution_stats = self._extract_hit_data(flat_rules, start_date, end_date)
        print(t("rpt_pu_flows_processed", hit=len(hit_hrefs)))

        # Step 4 — run analysis pipeline
        result = self._run_pipeline(
            flat_rules=flat_rules,
            ruleset_map=ruleset_map,
            hit_hrefs=hit_hrefs,
            hit_counts=hit_counts,
            start_date=start_date,
            end_date=end_date,
            lookback_days=lookback_days,
            execution_stats=execution_stats,
        )
        print(t("rpt_pu_complete"))
        return result

    def generate_from_csv(self, csv_path: str) -> PolicyUsageResult:
        """Import workloader rule-usage CSV and generate the same report.

        Expected CSV columns: ruleset_name, rule_description, rule_href,
        ruleset_href, flows, flows_by_port, src_labels, dst_labels, services,
        rule_enabled, ruleset_enabled, ...
        """
        import pandas as pd

        if not os.path.isfile(csv_path):
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        logger.info(f"Loaded workloader CSV: {len(df)} rows, columns={list(df.columns)}")

        # Build flat_rules and hit_counts from CSV rows
        flat_rules = []
        hit_counts = {}
        ruleset_map = {}

        for _, row in df.iterrows():
            rule_href = str(row.get('rule_href', ''))
            rs_href = str(row.get('ruleset_href', ''))
            rs_name = str(row.get('ruleset_name', ''))
            ruleset_map[rs_href] = rs_name

            rule = {
                'href': rule_href,
                'description': str(row.get('rule_description', '')),
                'enabled': str(row.get('rule_enabled', 'true')).lower() == 'true',
                'created_at': str(row.get('created_at', '')),
                '_ruleset_href': rs_href,
                '_ruleset_name': rs_name,
                # Preserve readable columns from CSV for display
                '_csv_providers': str(row.get('dst_labels', '')),
                '_csv_consumers': str(row.get('src_labels', '')),
                '_csv_services': str(row.get('services', '')),
                '_csv_flows_by_port': str(row.get('flows_by_port', '')),
            }
            flat_rules.append(rule)

            flows = 0
            try:
                flows = int(row.get('flows', 0))
            except (ValueError, TypeError):
                pass
            if flows > 0:
                hit_counts[rule_href] = flows
                rule['_flows_by_port'] = self._parse_flows_by_port(row.get('flows_by_port', ''))

        hit_hrefs = set(hit_counts.keys())
        port_totals = {}
        hit_rule_port_details = []
        for rule in flat_rules:
            href = rule.get('href', '')
            if href not in hit_hrefs:
                continue
            flows_by_port = dict(rule.get('_flows_by_port', {}) or {})
            for port_proto, count in flows_by_port.items():
                port_totals[port_proto] = port_totals.get(port_proto, 0) + int(count or 0)
            hit_rule_port_details.append({
                "rule_href": href,
                "rule_id": rule.get("_rule_id", ""),
                "rule_no": rule.get("_rule_no", ""),
                "ruleset_href": rule.get("_ruleset_href", ""),
                "ruleset_name": rule.get("_ruleset_name", ""),
                "description": rule.get("description", ""),
                "status": "hit",
                "hit_count": int(hit_counts.get(href, 0) or 0),
                "flows_by_port": flows_by_port,
                "top_hit_ports": "; ".join(
                    f"{port_proto} ({count})"
                    for port_proto, count in sorted(flows_by_port.items(), key=lambda item: (-item[1], item[0]))[:3]
                ),
            })

        execution_stats = {
            "cached_rules": 0,
            "submitted_rules": 0,
            "pending_jobs": 0,
            "failed_jobs": 0,
            "completed_jobs": 0,
            "downloaded_jobs": 0,
            "hit_rules": len(hit_hrefs),
            "unused_rules": len(flat_rules) - len(hit_hrefs),
            "flows_by_port_totals": port_totals,
            "top_hit_ports": [
                {"port_proto": port_proto, "flow_count": count}
                for port_proto, count in sorted(port_totals.items(), key=lambda item: (-item[1], item[0]))[:10]
            ],
            "hit_rule_port_details": hit_rule_port_details,
            "reused_rule_details": [],
            "pending_rule_details": [],
            "failed_rule_details": [],
        }

        # Use today as date range (CSV doesn't have this info)
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

        result = self._run_pipeline(
            flat_rules=flat_rules,
            ruleset_map=ruleset_map,
            hit_hrefs=hit_hrefs,
            hit_counts=hit_counts,
            start_date=today,
            end_date=today,
            lookback_days=0,
            execution_stats=execution_stats,
        )
        return result

    def export(
        self,
        result: PolicyUsageResult,
        fmt: str = 'html',
        output_dir: str = 'reports',
    ) -> list[str]:
        from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter

        os.makedirs(output_dir, exist_ok=True)
        paths = []

        if fmt in ('html', 'all'):
            path = PolicyUsageHtmlExporter(
                result.module_results,
                df=result.dataframe,
                date_range=result.date_range,
                lookback_days=result.lookback_days,
            ).export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, result, file_format='html')
            print(t("rpt_pu_html_saved", path=path))

        if fmt in ('pdf', 'all'):
            try:
                from src.report.exporters.pdf_exporter import export_report_pdf
                import datetime as _dt
                ts_str = _dt.datetime.now().strftime('%Y-%m-%d_%H%M')
                pdf_path = os.path.join(output_dir, f'Illumio_PolicyUsage_Report_{ts_str}.pdf')
                export_report_pdf(
                    title="Policy Usage Report",
                    output_path=pdf_path,
                    module_results=result.module_results or {},
                    metadata={
                        "generated_at": result.generated_at.isoformat(),
                        "record_count": result.record_count,
                        "start_date": result.date_range[0] if result.date_range else "",
                        "end_date": result.date_range[1] if len(result.date_range) > 1 else "",
                    },
                )
                paths.append(pdf_path)
                print(t("rpt_pdf_saved", path=pdf_path, default=f"PDF saved: {pdf_path}"))
            except Exception as exc:
                logger.warning('PDF export failed: {}', exc)

        if fmt in ('xlsx', 'all'):
            try:
                from src.report.exporters.xlsx_exporter import export_xlsx
                import datetime as _dt
                ts_str = _dt.datetime.now().strftime('%Y-%m-%d_%H%M')
                xlsx_path = os.path.join(output_dir, f'Illumio_PolicyUsage_Report_{ts_str}.xlsx')
                xlsx_result = {
                    'record_count': result.record_count,
                    'metadata': {'title': 'Policy Usage Report'},
                    'module_results': {
                        k: {'summary': '', 'table': []}
                        for k, v in (result.module_results or {}).items()
                        if isinstance(v, dict)
                    },
                }
                export_xlsx(xlsx_result, xlsx_path)
                paths.append(xlsx_path)
                print(t("rpt_xlsx_saved", path=xlsx_path, default=f"XLSX saved: {xlsx_path}"))
            except Exception as exc:
                logger.warning('XLSX export failed: {}', exc)

        if fmt in ('csv', 'all'):
            mod02 = result.module_results.get('mod02', {})
            mod03 = result.module_results.get('mod03', {})
            export_data = {}
            execution = result.execution_stats or {}
            hit_df = mod02.get('hit_df')
            unused_df = mod03.get('unused_df')
            top_ports_df = mod02.get('top_ports_df')
            if hit_df is not None and not hit_df.empty:
                export_data['hit_rules'] = hit_df
            if unused_df is not None and not unused_df.empty:
                export_data['unused_rules'] = unused_df
            if top_ports_df is not None and not top_ports_df.empty:
                export_data['top_hit_ports'] = top_ports_df
            if result.dataframe is not None and not result.dataframe.empty:
                export_data['raw_rules'] = result.dataframe
            if execution.get('reused_rule_details'):
                export_data['execution_reused_rules'] = execution['reused_rule_details']
            if execution.get('pending_rule_details'):
                export_data['execution_pending_rules'] = execution['pending_rule_details']
            if execution.get('failed_rule_details'):
                export_data['execution_failed_rules'] = execution['failed_rule_details']
            if execution.get('hit_rule_port_details'):
                export_data['hit_rule_port_details'] = execution['hit_rule_port_details']
            if export_data:
                path = CsvExporter(export_data, report_label='Policy_Usage').export(output_dir)
                paths.append(path)
                self._write_report_metadata(path, result, file_format='csv')
                print(t("rpt_pu_csv_saved", path=path))

        try:
            write_policy_usage_dashboard_summary(output_dir, result)
        except Exception as exc:
            logger.warning(f"[PolicyUsageGenerator] Failed to write dashboard summary: {exc}")

        # Trend analysis: archive snapshot and compute deltas
        try:
            from src.report.trend_store import save_snapshot, load_previous, compute_deltas, build_kpi_dict_from_metadata
            meta = self._build_report_metadata(result, file_format="snapshot")
            kpi_dict = build_kpi_dict_from_metadata(meta.get("kpis", []))
            ts = meta.get("generated_at", "")
            prev = load_previous(output_dir, "policy_usage")
            save_snapshot(output_dir, "policy_usage", kpi_dict, generated_at=ts)
            if prev:
                result.module_results["_trend_deltas"] = compute_deltas(kpi_dict, prev)
        except Exception as exc:
            logger.warning(f"[PolicyUsageGenerator] Trend snapshot failed: {exc}")

        return paths

    def _build_report_metadata(self, result: PolicyUsageResult, file_format: str) -> dict:
        mod00 = result.module_results.get('mod00', {}) if isinstance(result.module_results, dict) else {}
        execution = result.execution_stats or mod00.get('execution_stats', {}) or {}
        notes = mod00.get('execution_notes', []) or []
        summary_bits = []
        if execution.get('cached_rules'):
            summary_bits.append(f"cache {execution['cached_rules']}")
        if execution.get('submitted_rules'):
            summary_bits.append(f"new {execution['submitted_rules']}")
        if execution.get('pending_jobs'):
            summary_bits.append(f"pending {execution['pending_jobs']}")
        if execution.get('failed_jobs'):
            summary_bits.append(f"failed {execution['failed_jobs']}")
        attack_summary = extract_attack_summary(result.module_results, top_n=5)
        counts = attack_summary_counts(attack_summary)
        attack_brief = build_attack_summary_brief(counts)
        if attack_brief:
            summary_bits.append(attack_brief)
        return {
            "report_type": "policy_usage",
            "file_format": file_format,
            "generated_at": getattr(result, "generated_at", datetime.datetime.now()).isoformat(),
            "record_count": int(getattr(result, "record_count", 0) or 0),
            "date_range": list(getattr(result, "date_range", ("", "")) or ("", "")),
            "kpis": mod00.get('kpis', []),
            "execution_stats": execution,
            "top_hit_ports": execution.get("top_hit_ports", []),
            "reused_rule_details": execution.get("reused_rule_details", []),
            "pending_rule_details": execution.get("pending_rule_details", []),
            "failed_rule_details": execution.get("failed_rule_details", []),
            "execution_notes": notes,
            "attack_summary": attack_summary,
            "attack_summary_counts": counts,
            "summary": " | ".join(summary_bits),
        }

    def _write_report_metadata(self, report_path: str, result: PolicyUsageResult, file_format: str):
        metadata_path = report_path + ".metadata.json"
        payload = self._build_report_metadata(result, file_format=file_format)
        with open(metadata_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _build_baseline(self, rulesets: list) -> tuple:
        """Flatten all rulesets into a list of rules; build a ruleset_map.

        Each rule dict is augmented with:
        - _ruleset_name, _ruleset_href: for display
        - _ruleset_scopes: first scope array from the parent ruleset (for query building)

        Returns (flat_rules, ruleset_map).
        """
        flat_rules = []
        ruleset_map = {}

        for rs in rulesets:
            rs_href = rs.get('href', '')
            rs_name = rs.get('name', rs_href)
            ruleset_map[rs_href] = rs_name

            # Extract the first scope (most rulesets have exactly one scope)
            scopes = rs.get('scopes', [])
            first_scope = scopes[0] if scopes else []

            rs_id = rs_href.split('/')[-1] if rs_href else ''

            # Collect rules by type; annotate each with _rule_type
            typed_rules = []
            for r in rs.get('sec_rules', []) + rs.get('rules', []):
                typed_rules.append((r, 'Allow'))
            for r in rs.get('deny_rules', []):
                rule_type = 'Override Deny' if r.get('override') else 'Deny'
                typed_rules.append((r, rule_type))

            for rule_no, (rule, rule_type) in enumerate(typed_rules, 1):
                rule_href = rule.get('href', '')
                rule_copy = dict(rule)
                rule_copy['_ruleset_href'] = rs_href
                rule_copy['_ruleset_name'] = rs_name
                rule_copy['_ruleset_scopes'] = first_scope
                rule_copy['_ruleset_id'] = rs_id
                rule_copy['_rule_id'] = rule_href.split('/')[-1] if rule_href else ''
                rule_copy['_rule_no'] = rule_no
                rule_copy['_rule_type'] = rule_type
                flat_rules.append(rule_copy)

        return flat_rules, ruleset_map

    def _extract_hit_data(self, flat_rules: list, start_date: str, end_date: str) -> tuple:
        """Run per-rule async traffic queries using a parallel 3-phase strategy.

        Phase 1 — Submit all queries simultaneously.
        Phase 2 — Poll all pending jobs concurrently.
        Phase 3 — Download all completed results simultaneously.

        Returns (hit_hrefs: set, hit_counts: dict[href->int]).
        """
        def _on_progress(msg):
            print(f"\r  {msg:<70}", end="", flush=True)

        hit_hrefs, hit_counts = self.api.batch_get_rule_traffic_counts(
            flat_rules,
            start_date,
            end_date,
            max_concurrent=10,
            on_progress=_on_progress,
        )
        print()   # newline after progress line
        return hit_hrefs, hit_counts, self.api.get_last_rule_usage_batch_stats()

    @staticmethod
    def _parse_flows_by_port(value) -> dict:
        if isinstance(value, dict):
            parsed = {}
            for key, count in value.items():
                try:
                    parsed[str(key)] = int(count or 0)
                except (TypeError, ValueError):
                    continue
            return parsed

        text = str(value or "").strip()
        if not text:
            return {}

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                parsed = {}
                for key, count in data.items():
                    try:
                        parsed[str(key)] = int(count or 0)
                    except (TypeError, ValueError):
                        continue
                return parsed
        except Exception:
            pass  # intentional fallback: JSON parse failed, fall through to regex-based parsing

        parsed = {}
        for match in re.finditer(r"([^;]+?)\s+\((\d+)\)", text):
            label = " ".join(match.group(1).strip().split())
            label = label.replace(" TCP", "/tcp").replace(" UDP", "/udp").replace(" ICMP", "/icmp")
            parsed[label] = int(match.group(2))
        return parsed

    def _run_pipeline(
        self,
        flat_rules: list,
        ruleset_map: dict,
        hit_hrefs: set,
        hit_counts: dict,
        start_date: str,
        end_date: str,
        lookback_days: int,
        execution_stats: dict | None = None,
    ) -> PolicyUsageResult:
        import pandas as pd
        from src.report.analysis.policy_usage.pu_mod01_overview import pu_overview
        from src.report.analysis.policy_usage.pu_mod02_hit_detail import pu_hit_detail
        from src.report.analysis.policy_usage.pu_mod03_unused_detail import pu_unused_detail
        from src.report.analysis.policy_usage.pu_mod04_deny_effectiveness import pu_deny_effectiveness
        from src.report.analysis.policy_usage.pu_mod00_executive import pu_executive_summary

        results = {}
        results['mod01'] = pu_overview(flat_rules, hit_hrefs)
        results['mod02'] = pu_hit_detail(flat_rules, ruleset_map, hit_counts, execution_stats or {}, self.api)
        results['mod03'] = pu_unused_detail(flat_rules, ruleset_map, hit_hrefs, execution_stats or {}, self.api)
        results['mod04'] = pu_deny_effectiveness(flat_rules, hit_counts, ruleset_map)
        results['meta'] = {'execution_stats': execution_stats or {}}
        results['mod00'] = pu_executive_summary(results, lookback_days)

        # Build flat DataFrame for CSV raw_rules sheet
        try:
            df = pd.DataFrame([
                {
                    'href':         r.get('href', ''),
                    'ruleset':      r.get('_ruleset_name', ''),
                    'description':  r.get('description', ''),
                    'enabled':      r.get('enabled', True),
                    'created_at':   r.get('created_at', ''),
                    'hit':          r.get('href', '') in hit_hrefs,
                    'hit_count':    hit_counts.get(r.get('href', ''), 0),
                }
                for r in flat_rules
            ])
        except Exception:
            df = None  # intentional fallback: DataFrame construction may fail on edge-case data; result still returned without df

        return PolicyUsageResult(
            record_count=len(flat_rules),
            date_range=(start_date[:10], end_date[:10]),
            lookback_days=lookback_days,
            module_results=results,
            dataframe=df,
            execution_stats=execution_stats or {},
        )
