"""
src/report/report_generator.py
Unified Report Generation Entry Point (ModeA — no DB).

Usage:
    from src.report.report_generator import ReportGenerator

    gen = ReportGenerator(config_manager, api_client)

    # From PCE API:
    result = gen.generate_from_api()
    paths = gen.export(result, fmt='excel', output_dir='reports/')

    # From CSV:
    result = gen.generate_from_csv('/path/to/traffic.csv')
    paths = gen.export(result, fmt='all', output_dir='reports/')
"""
from __future__ import annotations

import datetime
from loguru import logger
import os
from dataclasses import dataclass, field
from typing import Optional

from src.i18n import t, get_language
from src.report.report_metadata import (
    attack_summary_counts,
    build_attack_summary_brief,
    extract_attack_summary,
)
from src.report.tz_utils import parse_tz as _parse_tz, fmt_tz_now as _fmt_tz_now

# ─── Snapshot helper (module-level) ──────────────────────────────────────────

def _build_snapshot(module_results: dict) -> dict:
    """Serialize module results into a JSON-safe snapshot for the Web UI dashboard."""
    import math
    try:
        import numpy as np
        _has_np = True
    except ImportError:
        _has_np = False

    def _safe_val(v):
        if _has_np:
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, np.floating):
                return None if (np.isnan(v) or np.isinf(v)) else float(v)
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        if isinstance(v, (dict, list)):
            return str(v)
        return v

    def _df_records(df, limit=10):
        if df is None or not hasattr(df, 'empty') or df.empty:
            return []
        return [
            {k: _safe_val(v) for k, v in row.items()}
            for row in df.head(limit).to_dict('records')
        ]

    mod01 = module_results.get('mod01', {})
    mod02 = module_results.get('mod02', {})
    mod03 = module_results.get('mod03', {})
    mod04 = module_results.get('mod04', {})
    mod08 = module_results.get('mod08', {})
    mod11 = module_results.get('mod11', {})
    mod12 = module_results.get('mod12', {})

    # Policy summary from mod02
    policy_summary = []
    if isinstance(mod02, dict) and 'summary' in mod02:
        policy_summary = _df_records(mod02['summary'], limit=10)

    # Top blocked/uncovered app flows (mod02 blocked)
    top_blocked_flows = []
    if isinstance(mod02, dict) and 'blocked' in mod02:
        top_blocked_flows = _df_records(mod02['blocked'].get('top_app_flows'), limit=10)

    return {
        'generated_at': mod12.get('generated_at', ''),
        'kpis':         mod12.get('kpis', []),
        'key_findings': mod12.get('key_findings', []),
        'boundary_breaches': mod12.get('boundary_breaches', []),
        'suspicious_pivot_behavior': mod12.get('suspicious_pivot_behavior', []),
        'blast_radius': mod12.get('blast_radius', []),
        'blind_spots': mod12.get('blind_spots', []),
        'action_matrix': mod12.get('action_matrix', []),
        # mod01 scalars
        'total_flows':          _safe_val(mod01.get('total_flows', 0)),
        'total_connections':    _safe_val(mod01.get('total_connections', 0)),
        'policy_coverage_pct':  _safe_val(mod01.get('policy_coverage_pct', 0)),
        'allowed_flows':        _safe_val(mod01.get('allowed_flows', 0)),
        'blocked_flows':        _safe_val(mod01.get('blocked_flows', 0)),
        'potentially_blocked':  _safe_val(mod01.get('potentially_blocked_flows', 0)),
        'total_mb':             _safe_val(mod01.get('total_mb', 0)),
        'date_range':           mod01.get('date_range', ''),
        # mod01 tables
        'top_ports':      _df_records(mod01.get('top_ports'), limit=10),
        'top_protocols':  _df_records(mod01.get('top_protocols'), limit=5),
        # mod02 tables
        'policy_summary':       policy_summary,
        'top_blocked_flows':    top_blocked_flows,
        # mod03
        'total_uncovered':  _safe_val(mod03.get('total_uncovered', 0)),
        'uncovered_pct':    _safe_val(100 - mod03.get('coverage_pct', 100)),
        'top_uncovered':    _df_records(mod03.get('top_flows'), limit=10),
        # mod04
        'ransomware_risk_total': _safe_val(mod04.get('risk_flows_total', 0)),
        # mod08
        'unique_unmanaged_src': _safe_val(mod08.get('unique_unmanaged_src', 0)),
        'top_unmanaged_src':    _df_records(mod08.get('top_unmanaged_src'), limit=10),
        # mod11
        'bw_data_available': bool(mod11.get('bytes_data_available', False)),
        'total_mb_bw':       _safe_val(mod11.get('total_mb', 0)),
        'top_by_bytes':      _df_records(mod11.get('top_by_bytes'), limit=10),
        'top_bandwidth':     _df_records(mod11.get('top_bandwidth'), limit=10),
    }

# ─── Result container ─────────────────────────────────────────────────────────

@dataclass
class ReportResult:
    """In-memory report result (replaces DB persistence in Mode A)."""
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    data_source: str = ''          # 'csv' or 'api'
    record_count: int = 0
    date_range: tuple = ('', '')
    module_results: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    dataframe: object = None       # pd.DataFrame, optional
    query_context: dict = field(default_factory=dict)

# ─── Generator ───────────────────────────────────────────────────────────────

class ReportGenerator:
    """
    Orchestrates the full report pipeline:
        DataSource → Parser → Validator → RulesEngine → 12 Modules → Export
    """

    def __init__(self, config_manager, api_client=None, config_dir: str = 'config'):
        self.cm = config_manager
        self.api = api_client
        self._config_dir = config_dir
        self._report_cfg = self._load_report_config()

    # ── public ───────────────────────────────────────────────────────────────

    def generate_from_api(self, start_date: Optional[str] = None,
                          end_date: Optional[str] = None,
                          max_results: int = 200_000,
                          filters: Optional[dict] = None) -> ReportResult:
        """Fetch traffic from PCE API and run the full analysis pipeline.

        filters: optional dict with traffic filter keys (src_labels, dst_labels,
                 src_ip, dst_ip, port, proto, ex_src_labels, ex_dst_labels,
                 ex_src_ip, ex_dst_ip, ex_port, policy_decisions).
        """
        if self.api is None:
            raise RuntimeError("api_client is required for generate_from_api()")

        # Default to last 7 days if not provided
        if not end_date:
            end_date = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        if not start_date:
            start_date = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
            ).isoformat().replace("+00:00", "Z")

        logger.info("[ReportGenerator] Starting API-source report generation")
        print(t("rpt_querying_traffic", start=start_date, end=end_date))
        policy_decisions = list((filters or {}).get("policy_decisions") or ["blocked", "potentially_blocked", "allowed"])

        records = self.api.fetch_traffic_for_report(
            start_time_str=start_date, end_time_str=end_date, filters=filters)

        if not records:
            logger.warning("[ReportGenerator] No records returned from API")
            print(t("rpt_no_traffic_data"))
            return ReportResult(
                data_source='api',
                record_count=0,
                query_context={
                    "start_date": start_date,
                    "end_date": end_date,
                    "filters": dict(filters or {}),
                    "policy_decisions": policy_decisions,
                    "query_diagnostics": self.api.get_last_traffic_query_diagnostics() if self.api else {},
                },
            )

        print(t("rpt_records_received", count=f"{len(records):,}"))
        df = self._parse_api(records)
        return self._run_pipeline(
            df,
            source='api',
            query_context={
                "start_date": start_date,
                "end_date": end_date,
                "filters": dict(filters or {}),
                "policy_decisions": policy_decisions,
                "query_diagnostics": self.api.get_last_traffic_query_diagnostics() if self.api else {},
            },
        )

    def generate_from_csv(self, csv_path: str) -> ReportResult:
        """Parse a CSV file from the PCE UI export and run the analysis pipeline."""
        logger.info(f"[ReportGenerator] Starting CSV-source report from: {csv_path}")
        print(t("rpt_parsing_csv", path=csv_path))
        df = self._parse_csv(csv_path)
        return self._run_pipeline(df, source='csv')

    def export(self, result: ReportResult, fmt: str = 'html',
               output_dir: str = 'reports',
               send_email: bool = False,
               reporter=None) -> list[str]:
        """
        Export a ReportResult to one or more files.

        Args:
            result:     output of generate_from_*()
            fmt:        'html' | 'csv' | 'all'
            output_dir: directory to write files into
            send_email: if True, send via reporter.send_report_email()
            reporter:   Reporter instance (required if send_email=True)

        Returns:
            list of file paths written
        """
        from src.report.exporters.html_exporter import HtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter

        paths = []

        if fmt in ('html', 'all', 'all_raw'):
            path = HtmlExporter(result.module_results).export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, self._build_report_metadata(result, file_format="html"))
            print(t("rpt_html_saved", path=path))

        if fmt in ('pdf', 'all'):
            try:
                from src.report.exporters.pdf_exporter import export_pdf
                html_content = HtmlExporter(result.module_results)._build()
                import datetime as _dt
                ts_str = _dt.datetime.now().strftime('%Y-%m-%d_%H%M')
                pdf_path = os.path.join(output_dir, f'Illumio_Traffic_Report_{ts_str}.pdf')
                export_pdf(html_content, pdf_path)
                paths.append(pdf_path)
                print(t("rpt_pdf_saved", path=pdf_path, default=f"PDF saved: {pdf_path}"))
            except Exception as exc:
                logger.warning('PDF export failed (may need GTK3 on Linux): {}', exc)

        if fmt in ('xlsx', 'all'):
            try:
                from src.report.exporters.xlsx_exporter import export_xlsx
                import datetime as _dt
                ts_str = _dt.datetime.now().strftime('%Y-%m-%d_%H%M')
                xlsx_path = os.path.join(output_dir, f'Illumio_Traffic_Report_{ts_str}.xlsx')
                meta = self._build_report_metadata(result, file_format="xlsx")
                xlsx_result = {
                    'record_count': result.record_count,
                    'metadata': {
                        'title': 'Traffic Flow Report',
                        'generated_at': meta.get('generated_at', ''),
                        'start_date': result.date_range[0] if result.date_range else '',
                        'end_date': result.date_range[1] if len(result.date_range) > 1 else '',
                    },
                    'module_results': {},
                }
                for mod_key, mod_data in (result.module_results or {}).items():
                    if not isinstance(mod_data, dict):
                        continue
                    sheet_data = {'summary': '', 'table': []}
                    if 'chart_spec' in mod_data:
                        sheet_data['chart_spec'] = mod_data['chart_spec']
                    xlsx_result['module_results'][mod_key] = sheet_data
                export_xlsx(xlsx_result, xlsx_path)
                paths.append(xlsx_path)
                print(t("rpt_xlsx_saved", path=xlsx_path, default=f"XLSX saved: {xlsx_path}"))
            except Exception as exc:
                logger.warning('XLSX export failed: {}', exc)

        if fmt in ('csv', 'all', 'all_raw'):
            export_data = dict(result.module_results)
            if result.dataframe is not None and not result.dataframe.empty:
                export_data['raw_traffic'] = result.dataframe
            path = CsvExporter(export_data, report_label='Traffic').export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, self._build_report_metadata(result, file_format="csv"))
            print(t("rpt_csv_saved", path=path))

        if fmt in ('raw_csv', 'all_raw'):
            if result.data_source != 'api' or not result.query_context:
                raise ValueError("Raw Explorer CSV export is only supported for API-sourced traffic reports")
            if self.api is None:
                raise RuntimeError("api_client is required for raw Explorer CSV export")
            raw_export = self.api.export_traffic_query_csv(
                start_time_str=result.query_context.get("start_date"),
                end_time_str=result.query_context.get("end_date"),
                policy_decisions=result.query_context.get("policy_decisions"),
                filters=result.query_context.get("filters"),
                output_dir=output_dir,
            )
            paths.append(raw_export["path"])
            self._write_report_metadata(
                raw_export["path"],
                {
                    "report_type": "traffic_raw_csv",
                    "file_format": "raw_csv",
                    "generated_at": result.generated_at.isoformat(),
                    "record_count": int(raw_export.get("row_count", 0) or 0),
                    "date_range": list(result.date_range),
                    "summary": "Raw Explorer CSV export",
                    "query_diagnostics": raw_export.get("query_diagnostics", {}),
                    "policy_decisions": raw_export.get("policy_decisions", []),
                    "filters": raw_export.get("filters", {}),
                    "job_href": raw_export.get("job_href", ""),
                    "compute_draft": raw_export.get("compute_draft", False),
                },
            )
            print(f"Raw Explorer CSV saved: {raw_export['path']}")

        # Save snapshot for Web UI Dashboard directly
        try:
            import json
            snapshot_path = os.path.join(output_dir, 'latest_snapshot.json')
            with open(snapshot_path, 'w', encoding='utf-8') as f:
                json.dump(_build_snapshot(result.module_results), f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[ReportGenerator] Failed to write KPI snapshot: {e}")

        # Trend analysis: archive snapshot and compute deltas
        try:
            from src.report.trend_store import save_snapshot, load_previous, compute_deltas, build_kpi_dict_from_metadata
            meta = self._build_report_metadata(result, file_format="snapshot")
            kpi_dict = build_kpi_dict_from_metadata(meta.get("kpis", []))
            ts = meta.get("generated_at", "")
            prev = load_previous(output_dir, "traffic")
            save_snapshot(output_dir, "traffic", kpi_dict, generated_at=ts)
            if prev:
                result.module_results["_trend_deltas"] = compute_deltas(kpi_dict, prev)
        except Exception as e:
            logger.warning(f"[ReportGenerator] Trend snapshot failed: {e}")

        if send_email and reporter is not None:
            html_path = next((p for p in paths if p.endswith('.html')), None)
            mod12 = result.module_results.get('mod12', {})
            subject = t("rpt_email_traffic_subject") + f" — {datetime.date.today()}"
            html_body = self._build_email_body(mod12)
            try:
                reporter.send_report_email(subject, html_body, attachment_path=html_path)
                print(t("rpt_email_sent"))
            except Exception as e:
                logger.error(f"[ReportGenerator] Email send failed: {e}")
                print(t("rpt_email_failed", error=str(e)))

        return paths

    # ── private — pipeline ───────────────────────────────────────────────────

    def _run_pipeline(self, df, source: str, query_context: Optional[dict] = None) -> ReportResult:
        """Validate → Rules → 12 modules → wrap result."""
        import pandas as pd
        from src.report.parsers.validators import validate, coerce
        from src.report.rules_engine import RulesEngine

        if df is None or (hasattr(df, 'empty') and df.empty):
            logger.warning("[ReportGenerator] Empty DataFrame, skipping analysis")
            return ReportResult(data_source=source, record_count=0)

        issues = validate(df)
        if issues:
            print(t("rpt_schema_warnings", count=len(issues)))
            df = coerce(df)

        record_count = len(df)
        print(t("rpt_running_analysis", count=f"{record_count:,}"))

        # Rules engine
        engine = RulesEngine(self._report_cfg, config_dir=self._config_dir)
        findings = engine.evaluate(df)
        print(t("rpt_rules_findings", count=len(findings)))

        # 15 modules
        results = self._run_modules(df, findings)

        # Override generated_at with configured timezone
        tz_str = self.cm.config.get('settings', {}).get('timezone', 'local')
        try:
            tz = _parse_tz(tz_str)
            results['mod12']['generated_at'] = _fmt_tz_now(tz)
        except Exception:
            pass  # intentional fallback: keep mod12's default generated_at if timezone parsing fails

        # Date range
        first = df['first_detected'].min() if 'first_detected' in df.columns else pd.NaT
        last = df['last_detected'].max() if 'last_detected' in df.columns else pd.NaT
        date_range = (str(first.date()) if pd.notna(first) else '',
                      str(last.date()) if pd.notna(last) else '')

        return ReportResult(
            data_source=source,
            record_count=record_count,
            date_range=date_range,
            module_results=results,
            findings=findings,
            dataframe=df,
            query_context=dict(query_context or {}),
        )

    @staticmethod
    def _write_report_metadata(report_path: str, payload: dict):
        import json

        with open(report_path + ".metadata.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    def _build_report_metadata(self, result: ReportResult, file_format: str) -> dict:
        mod12 = result.module_results.get("mod12", {}) if isinstance(result.module_results, dict) else {}
        attack_summary = extract_attack_summary(result.module_results, top_n=5)
        counts = attack_summary_counts(attack_summary)
        summary = build_attack_summary_brief(counts)
        if not summary:
            summary = f"traffic records {int(getattr(result, 'record_count', 0) or 0)}"
        return {
            "report_type": "traffic",
            "file_format": file_format,
            "generated_at": getattr(result, "generated_at", datetime.datetime.now()).isoformat(),
            "record_count": int(getattr(result, "record_count", 0) or 0),
            "date_range": list(getattr(result, "date_range", ("", "")) or ("", "")),
            "kpis": mod12.get("kpis", []),
            "summary": summary,
            "attack_summary": attack_summary,
            "attack_summary_counts": counts,
        }

    def _run_modules(self, df, findings: list) -> dict:
        """Execute all registered analysis modules via the module registry."""
        from src.report.analysis import get_traffic_modules, get_summary_module

        top_n = self._report_cfg.get('output', {}).get('top_n', 20)
        results: dict = {'findings': findings}
        module_errors: list = []

        for mod_id, fn, adapter in get_traffic_modules():
            try:
                results[mod_id] = adapter(fn, df, self._report_cfg, top_n)
                print(f"[Report]   {mod_id} ✓", end='  \r', flush=True)
            except Exception as e:
                logger.warning(f"[ReportGenerator] {mod_id} failed: {e}")
                results[mod_id] = {'error': str(e)}
                module_errors.append({'module': mod_id, 'error': str(e)})

        # Summary module runs last (depends on all other results)
        try:
            summary_id, summary_fn = get_summary_module()
            results[summary_id] = summary_fn(results)
        except Exception as e:
            logger.error(f"[ReportGenerator] summary module failed: {e}")
            results['mod12'] = {'error': str(e)}
            module_errors.append({'module': 'mod12', 'error': str(e)})

        results['_module_errors'] = module_errors
        print(t("rpt_modules_complete") + "             ")
        return results

    # ── private — parsers ────────────────────────────────────────────────────

    def _parse_csv(self, csv_path: str):
        from src.report.parsers.csv_parser import CSVParser
        return CSVParser().parse(csv_path)

    def _parse_api(self, records: list):
        from src.report.parsers.api_parser import APIParser
        return APIParser().parse(records)

    # ── private — config ─────────────────────────────────────────────────────

    def _load_report_config(self) -> dict:
        path = os.path.join(self._config_dir, 'report_config.yaml')
        if not os.path.exists(path):
            logger.warning(f"[ReportGenerator] report_config.yaml not found at {path}, using defaults")
            return {}
        try:
            import yaml
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            logger.warning("[ReportGenerator] pyyaml not installed — using default report config")
            return {}
        except Exception as e:
            logger.error(f"[ReportGenerator] Failed to load report_config.yaml: {e}")
            return {}

    # ── private — email body ─────────────────────────────────────────────────

    def _build_email_body(self, mod12: dict) -> str:
        """Build a compact HTML email body from the executive summary."""
        kpis = mod12.get('kpis', [])
        findings = mod12.get('key_findings', [])
        boundary_breaches = mod12.get('boundary_breaches', [])
        suspicious_pivot = mod12.get('suspicious_pivot_behavior', [])
        blast_radius = mod12.get('blast_radius', [])
        blind_spots = mod12.get('blind_spots', [])
        action_matrix = mod12.get('action_matrix', [])

        def _sev_bg(sev):
            if sev == 'CRITICAL': return '#BE122F'
            if sev == 'HIGH':     return '#F43F51'
            return '#F97607'

        kpi_rows = ''.join(
            f'<tr>'
            f'<td style="font-weight:600;padding:5px 12px;color:#989A9B;font-size:11px;text-transform:uppercase;letter-spacing:.04em">{k["label"]}</td>'
            f'<td style="padding:5px 12px;font-weight:700;font-size:16px;color:#1A2C32">{k["value"]}</td>'
            f'</tr>'
            for k in kpis
        )
        finding_rows = ''.join(
            f'<tr>'
            f'<td style="color:white;background:{_sev_bg(f.get("severity",""))};padding:4px 10px;font-weight:700;border-radius:4px;white-space:nowrap">'
            f'{f.get("severity","")}</td>'
            f'<td style="padding:4px 10px;color:#313638">{f.get("finding","")}</td>'
            f'<td style="padding:4px 10px;color:#989A9B"><em>{f.get("action","")}</em></td>'
            f'</tr>'
            for f in findings
        )
        attack_rows = []
        _zh = get_language() == "zh_TW"
        for title, items in [
            (t("rpt_email_boundary_breaches"), boundary_breaches),
            (t("rpt_email_suspicious_pivot_behavior"), suspicious_pivot),
            (t("rpt_email_blast_radius"), blast_radius),
            (t("rpt_email_blind_spots"), blind_spots),
        ]:
            if items:
                sample = items[0]
                zh_action = (f'<br><span style="font-size:11px">{sample.get("action_zh","")}</span>' if _zh and sample.get("action_zh") else '')
                attack_rows.append(
                    f'<tr>'
                    f'<td style="padding:4px 10px;font-weight:700;color:#1A2C32">{title}</td>'
                    f'<td style="padding:4px 10px;color:#313638">{sample.get("finding","")}</td>'
                    f'<td style="padding:4px 10px;color:#989A9B"><em>{sample.get("action","")}</em>'
                    + zh_action
                    + '</td>'
                    f'</tr>'
                )
        if action_matrix:
            top_action = action_matrix[0]
            zh_action_cell = (f'<em>{top_action.get("action_zh","")}</em>' if _zh and top_action.get("action_zh") else '')
            attack_rows.append(
                f'<tr>'
                f'<td style="padding:4px 10px;font-weight:700;color:#1A2C32">{t("rpt_email_action_matrix")}</td>'
                f'<td style="padding:4px 10px;color:#313638">{top_action.get("action","")}</td>'
                f'<td style="padding:4px 10px;color:#989A9B">{zh_action_cell}</td>'
                f'</tr>'
            )
        attack_rows_html = "".join(attack_rows)

        return f"""
<html><body style="margin:0;padding:0;background:#F7F4EE;font-family:'Montserrat',Arial,sans-serif;color:#313638;line-height:1.5">
<div style="max-width:700px;margin:0 auto;padding:16px">
  <div style="border-radius:10px;overflow:hidden;border:1px solid #325158">
    <div style="background:#1A2C32;border-left:4px solid #FF5500;padding:18px 20px;color:#fff">
      <div style="font-size:20px;font-weight:700;margin-bottom:4px">{t("rpt_email_traffic_subject")}</div>
      <div style="font-size:12px;color:#989A9B">Generated: {mod12.get('generated_at','')}</div>
    </div>
    <div style="background:#fff;padding:20px">
      <h3 style="color:#1A2C32;font-size:13px;font-weight:600;margin:0 0 8px;border-bottom:2px solid #FF5500;padding-bottom:5px">{t("rpt_email_key_metrics")}</h3>
      <table border="0" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin-bottom:20px">
        {kpi_rows}
      </table>
      <h3 style="color:#1A2C32;font-size:13px;font-weight:600;margin:0 0 8px;border-bottom:2px solid #FF5500;padding-bottom:5px">{t("rpt_email_key_findings")}</h3>
      <table border="0" cellpadding="0" cellspacing="3" style="border-collapse:separate;border-spacing:0 3px;width:100%">
        {finding_rows or f'<tr><td colspan="3" style="padding:8px;color:#989A9B">{t("rpt_email_no_findings")}</td></tr>'}
      </table>
      <h3 style="color:#1A2C32;font-size:13px;font-weight:600;margin:16px 0 8px;border-bottom:2px solid #FF5500;padding-bottom:5px">{t("rpt_email_attack_summary")}</h3>
      <table border="0" cellpadding="0" cellspacing="3" style="border-collapse:separate;border-spacing:0 3px;width:100%">
        {attack_rows_html or f'<tr><td colspan="3" style="padding:8px;color:#989A9B">{t("rpt_email_no_attack_findings")}</td></tr>'}
      </table>
    </div>
    <div style="background:#F7F4EE;padding:12px 20px;border-top:1px solid #E3D8C5;text-align:center;color:#989A9B;font-size:11px">
      {t("rpt_email_footer")}
    </div>
  </div>
</div>
</body></html>"""
