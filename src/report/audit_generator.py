"""
src/report/audit_generator.py
Orchestrates the generation of the Audit & System Events Report.
"""
import datetime
import logging
import os
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class AuditReportResult:
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    record_count: int = 0
    date_range: tuple = ('', '')
    module_results: dict = field(default_factory=dict)
    dataframe: object = None

class AuditGenerator:
    def __init__(self, config_manager, api_client=None, config_dir: str = 'config'):
        self.cm = config_manager
        self.api = api_client
        self._config_dir = config_dir
        self._report_cfg = self._load_report_config()

    def generate_from_api(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> AuditReportResult:
        if not self.api:
            raise RuntimeError("api_client required for audit generation")

        if not end_date:
            end_date = datetime.datetime.utcnow().isoformat() + "Z"
        if not start_date:
            start_date = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat() + "Z"

        print(f"[Audit Report] Querying PCE API for events ({start_date} to {end_date})…")
        events = self.api.fetch_events(start_time_str=start_date, end_time_str=end_date)
        
        if not events:
            print("[Audit Report] ⚠ No events returned by API.")
            return AuditReportResult(record_count=0)

        df = pd.DataFrame(events)
        # Flatten created_by nested dict to a readable username string
        if 'created_by' in df.columns:
            def _extract_user(v):
                if isinstance(v, dict):
                    u = v.get('user', v)
                    return u.get('username', u.get('name', u.get('href', str(v))))
                return str(v) if v is not None else ''
            df['created_by'] = df['created_by'].apply(_extract_user)
        print(f"[Audit Report] {len(df):,} event records received — analyzing…")
        
        return self._run_pipeline(df, start_date, end_date)

    def _run_pipeline(self, df: pd.DataFrame, start_date: str, end_date: str) -> AuditReportResult:
        from src.report.analysis.audit.audit_mod01_health import audit_system_health
        from src.report.analysis.audit.audit_mod02_users import audit_user_activity
        from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes
        from src.report.analysis.audit.audit_mod00_executive import audit_executive_summary

        results = {}
        _MODS = [
            ('mod01', lambda: audit_system_health(df)),
            ('mod02', lambda: audit_user_activity(df)),
            ('mod03', lambda: audit_policy_changes(df)),
        ]

        for mod_id, fn in _MODS:
            try:
                results[mod_id] = fn()
                print(f"[Audit Report]   {mod_id} ✓", end='  \\r', flush=True)
            except Exception as e:
                logger.warning(f"{mod_id} failed: {e}")
                results[mod_id] = {'error': str(e)}

        results['mod00'] = audit_executive_summary(results, df)
        print(f"[Audit Report] All modules complete             ")

        return AuditReportResult(
            record_count=len(df),
            date_range=(start_date[:10], end_date[:10]),
            module_results=results,
            dataframe=df
        )

    def export(self, result: AuditReportResult, fmt: str = 'html', output_dir: str = 'reports') -> list[str]:
        from src.report.exporters.audit_html_exporter import AuditHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter
        paths = []
        if fmt in ('html', 'all'):
            path = AuditHtmlExporter(
                result.module_results, df=result.dataframe,
                date_range=result.date_range
            ).export(output_dir)
            paths.append(path)
            print(f"[Audit Report] ✅ HTML  saved: {path}")
        if fmt in ('csv', 'all'):
            path = CsvExporter(result.module_results, report_label='Audit').export(output_dir)
            paths.append(path)
            print(f"[Audit Report] ✅ CSV (ZIP) saved: {path}")
        return paths

    def _load_report_config(self) -> dict:
        import yaml
        path = os.path.join(self._config_dir, 'report_config.yaml')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}
