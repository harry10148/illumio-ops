"""
src/report/ven_status_generator.py
Orchestrates the VEN Status Inventory Report.

Classifies every VEN-managed workload as:
  - Online  : administrative status is 'active' AND last heartbeat <= 1 h ago
  - Offline : suspended/stopped, OR active but heartbeat > 1 h ago (lost connectivity),
              OR no heartbeat information available

Note: PCE's agent.status.status reflects *administrative* state only.
A VEN can remain "active" administratively while being unreachable.
Real connectivity is determined from hours_since_last_heartbeat (PCE-computed)
or by computing age from the last_heartbeat_on timestamp.

Then further buckets offline VENs by when they last sent a heartbeat:
  - Lost in last 24 h
  - Lost in previous 24-48 h window
  - Long-term offline (last heartbeat > 48 h ago or unknown)
"""
import datetime
from loguru import logger
import os
import pandas as pd
from dataclasses import dataclass, field

from src.i18n import t
from src.report.tz_utils import parse_tz, fmt_tz_str as _fmt_tz_str, fmt_ts_local as _fmt_ts_local

_REPORT_DETAIL_LEVEL = "full"

_ONLINE_STATUSES = {'active', 'online'}
# VENs whose last heartbeat is older than this are considered offline,
# even when PCE reports their administrative status as "active".
_ONLINE_HEARTBEAT_THRESHOLD_HOURS = 1.0

@dataclass
class VenStatusResult:
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    record_count: int = 0
    module_results: dict = field(default_factory=dict)
    dataframe: object = None

class VenStatusGenerator:
    def __init__(self, config_manager, api_client=None):
        self.cm = config_manager
        self.api = api_client

    # ── public ───────────────────────────────────────────────────────────────

    def generate(self, detail_level: str = _REPORT_DETAIL_LEVEL, lang: str = "en") -> VenStatusResult:
        if not self.api:
            raise RuntimeError("api_client required for VEN status report")

        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang
        print(t("rpt_ven_fetching"))
        workloads = self.api.fetch_managed_workloads()

        if not workloads:
            print(t("rpt_ven_no_data"))
            return VenStatusResult(record_count=0)

        print(t("rpt_ven_found", count=f"{len(workloads):,}"))
        df = self._build_dataframe(workloads)
        results = self._analyze(df)
        print(t("rpt_ven_analysis_done"))

        return VenStatusResult(
            record_count=len(df),
            module_results=results,
            dataframe=df,
        )

    def export(self, result: VenStatusResult, fmt: str = 'html', output_dir: str = 'reports',
               detail_level: str = _REPORT_DETAIL_LEVEL, lang: str = "en") -> list:
        from src.report.exporters.ven_html_exporter import VenHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter
        os.makedirs(output_dir, exist_ok=True)
        paths = []
        if fmt in ('html', 'all'):
            path = VenHtmlExporter(result.module_results, df=result.dataframe, lang=lang).export(output_dir)
            paths.append(path)
            print(t("rpt_ven_html_saved", path=path))
        if fmt in ('pdf', 'all'):
            try:
                from src.report.exporters.pdf_exporter import export_report_pdf
                import datetime as _dt
                ts_str = _dt.datetime.now().strftime('%Y-%m-%d_%H%M')
                pdf_path = os.path.join(output_dir, f'Illumio_VEN_Report_{ts_str}.pdf')
                export_report_pdf(
                    title="VEN Status Report",
                    output_path=pdf_path,
                    module_results=result.module_results or {},
                    metadata={
                        "generated_at": result.generated_at.isoformat(),
                        "record_count": result.record_count,
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
                xlsx_path = os.path.join(output_dir, f'Illumio_VEN_Report_{ts_str}.xlsx')
                xlsx_result = {
                    'record_count': result.record_count,
                    'metadata': {'title': 'VEN Status Report'},
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
            path = CsvExporter(result.module_results, report_label='VEN_Status').export(output_dir)
            paths.append(path)
            print(t("rpt_ven_csv_saved", path=path))
        return paths

    # ── private ──────────────────────────────────────────────────────────────

    def _build_dataframe(self, workloads: list) -> pd.DataFrame:
        rows = []
        for w in workloads:
            agent = w.get('agent') or {}
            st = agent.get('status') or {}

            # Collect IPv4 interface IPs only (skip IPv6 / link-local)
            ips = [
                iface.get('address', '')
                for iface in w.get('interfaces', [])
                if iface.get('address') and ':' not in iface['address']
            ]
            ip_str = ', '.join(ips) or w.get('public_ip', '')

            # Flatten labels
            labels_str = '; '.join(
                f"{lbl.get('key', '?')}:{lbl.get('value', '?')}"
                for lbl in w.get('labels', [])
                if isinstance(lbl, dict) and lbl.get('key') and lbl.get('value')
            )

            rows.append({
                'hostname':                   w.get('hostname', w.get('name', '')),
                'ip':                         ip_str,
                'labels':                     labels_str,
                # Internal fields used for online/offline determination (not displayed)
                'ven_status':                 st.get('status', ''),
                'hours_since_last_heartbeat': st.get('hours_since_last_heartbeat', None),
                # Display fields
                'policy_sync':               st.get('security_policy_sync_state', ''),
                'last_heartbeat':             st.get('last_heartbeat_on', ''),
                'policy_received':            st.get('security_policy_refresh_at', ''),
                'paired_at':                  st.get('managed_since', ''),
                'ven_version':                st.get('agent_version', ''),
            })

        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=['hostname', 'ip', 'labels',
                     'ven_status', 'hours_since_last_heartbeat',
                     'policy_sync', 'last_heartbeat', 'policy_received',
                     'paired_at', 'ven_version']
        )

    def _parse_tz(self) -> datetime.timezone:
        tz_str = self.cm.config.get('settings', {}).get('timezone', 'local')
        return parse_tz(tz_str)

    def _analyze(self, df: pd.DataFrame) -> dict:
        now = datetime.datetime.now(self._parse_tz())
        cutoff_24h = now - datetime.timedelta(hours=24)
        cutoff_48h = now - datetime.timedelta(hours=48)

        # Columns included in the final display tables (internal-only fields excluded)
        _DISPLAY_COLS = ['hostname', 'ip', 'labels', 'policy_sync',
                         'last_heartbeat', 'policy_received', 'paired_at', 'ven_version']
        _COL_RENAME = {
            'hostname':        'Hostname',
            'ip':              'IP',
            'labels':          'Labels',
            'policy_sync':     'Policy Sync',
            'last_heartbeat':  'Last Heartbeat',
            'policy_received': 'Policy Received',
            'paired_at':       'Paired At',
            'ven_version':     'VEN Version',
        }

        def _parse(ts: str):
            if not ts:
                return None
            try:
                return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception:
                return None  # intentional fallback: return None for unparseable timestamps

        def _bool_mask(series, predicate):
            """Apply predicate safely; always returns a proper boolean Series."""
            if series.empty:
                return pd.Series([], dtype=bool)
            return series.apply(predicate).astype(bool)

        def _clean(d):
            if d.empty:
                return pd.DataFrame(columns=list(_COL_RENAME.values()))
            cols = [c for c in _DISPLAY_COLS if c in d.columns]
            out = d[cols].copy().sort_values('last_heartbeat', ascending=False, na_position='last')
            # Format timestamp columns to human-readable local time
            tz = now.tzinfo
            for ts_col in ('last_heartbeat', 'policy_received', 'paired_at'):
                if ts_col in out.columns:
                    out[ts_col] = out[ts_col].apply(lambda v: _fmt_ts_local(v, tz))
            return out.rename(columns=_COL_RENAME).reset_index(drop=True)

        df = df.copy()
        df['_hb_dt'] = df['last_heartbeat'].apply(_parse)

        # --- Online / Offline determination ---
        # Illumio PCE's agent.status.status reflects *administrative* state.
        # A VEN can show "active" while being unreachable (no heartbeat).
        # Real connectivity is determined by hours_since_last_heartbeat:
        #   - If the field is present and numeric → use it directly.
        #   - Otherwise fall back to computing age from last_heartbeat_on timestamp.
        #   - If neither is available, treat as offline (unknown connectivity).
        def _is_online_row(row) -> bool:
            # Must be in an active administrative state first
            if str(row.get('ven_status', '')).lower() not in _ONLINE_STATUSES:
                return False
            # Try hours_since_last_heartbeat (most reliable — PCE-computed)
            hslh = row.get('hours_since_last_heartbeat')
            if hslh is not None:
                try:
                    return float(hslh) <= _ONLINE_HEARTBEAT_THRESHOLD_HOURS
                except (TypeError, ValueError):
                    pass
            # Fall back to timestamp age
            hb_dt = row.get('_hb_dt')
            if hb_dt is not None:
                age_hours = (now - hb_dt.astimezone(now.tzinfo)).total_seconds() / 3600
                return age_hours <= _ONLINE_HEARTBEAT_THRESHOLD_HOURS
            # No heartbeat info at all → treat as offline
            return False

        is_online = df.apply(_is_online_row, axis=1).astype(bool)
        df_online  = df[is_online].copy()
        df_offline = df[~is_online].copy()

        # Offline VENs bucketed by last-heartbeat time
        mask_today = _bool_mask(df_offline['_hb_dt'],
                                lambda t: t is not None and t >= cutoff_24h)
        mask_yest  = _bool_mask(df_offline['_hb_dt'],
                                lambda t: t is not None and cutoff_48h <= t < cutoff_24h)

        df_lost_today = df_offline[mask_today] if len(mask_today) else df_offline.iloc[0:0]
        df_lost_yest  = df_offline[mask_yest]  if len(mask_yest)  else df_offline.iloc[0:0]

        # KPI labels are resolved by the HTML exporter using report_i18n.STRINGS.
        # Generator only stores the i18n key + value so rendering stays lang-aware.
        kpis = [
            {'i18n_key': 'rpt_ven_kpi_total', 'value': str(len(df))},
            {'i18n_key': 'rpt_ven_kpi_online', 'value': str(len(df_online))},
            {'i18n_key': 'rpt_ven_kpi_offline', 'value': str(len(df_offline))},
            {'i18n_key': 'rpt_ven_kpi_lost_24h', 'value': str(len(df_lost_today))},
            {'i18n_key': 'rpt_ven_kpi_lost_48h', 'value': str(len(df_lost_yest))},
        ]

        # Chart 1: VEN status pie (online vs offline)
        status_chart_spec = None
        total_for_chart = len(df_online) + len(df_offline)
        if total_for_chart > 0:
            status_chart_spec = {
                "type": "pie",
                "title": "VEN Agent Status",
                "data": {
                    "labels": ["Online", "Offline"],
                    "values": [len(df_online), len(df_offline)],
                },
                "i18n": {"lang": "en"},
            }

        # Chart 2: VEN count by OS platform (if os column exists)
        os_chart_spec = None
        os_col = next((c for c in ("os_id", "os_type", "os", "os_platform") if c in df.columns), None)
        if os_col and not df.empty:
            os_counts = df[os_col].fillna("Unknown").astype(str).str.strip().replace("", "Unknown").value_counts()
            if len(os_counts) > 0:
                os_chart_spec = {
                    "type": "bar",
                    "title": "VEN by OS Platform",
                    "x_label": "OS",
                    "y_label": "VEN Count",
                    "data": {
                        "labels": os_counts.index.tolist()[:10],
                        "values": os_counts.values.tolist()[:10],
                    },
                    "i18n": {"lang": "en"},
                }

        return {
            'generated_at':   _fmt_tz_str(now),
            'kpis':           kpis,
            'online':         _clean(df_online),
            'offline':        _clean(df_offline),
            'lost_today':     _clean(df_lost_today),
            'lost_yesterday': _clean(df_lost_yest),
            'status_chart_spec': status_chart_spec,
            'os_chart_spec': os_chart_spec,
        }


def generate_ven_xlsx(workloads_df, out_path: str, top_n: int = 1000) -> str:
    """Generate a VEN status XLSX with workloads bucketed by status and heartbeat age."""
    from datetime import datetime, timedelta, timezone
    from openpyxl import Workbook
    import pandas as pd

    wb = Workbook()
    wb.remove(wb.active)

    now = datetime.now(timezone.utc)

    def _write_sheet(name, df):
        ws = wb.create_sheet(name)
        if df is None or not hasattr(df, "empty") or df.empty:
            ws.append(["Note", "No workloads in this category"])
            return
        ws.append(list(df.columns))
        for _, row in df.head(top_n).iterrows():
            ws.append([str(v) for v in row])

    # Parse heartbeat timestamps
    try:
        hb = pd.to_datetime(workloads_df["last_heartbeat"], utc=True, errors="coerce")
        age_h = (now - hb).dt.total_seconds() / 3600
    except Exception:
        age_h = pd.Series([float("inf")] * len(workloads_df), index=workloads_df.index)

    has_status = "ven_status" in workloads_df.columns

    if has_status:
        is_active = workloads_df["ven_status"] == "active"
        is_offline = workloads_df["ven_status"] == "offline"
    else:
        is_active = pd.Series(True, index=workloads_df.index)
        is_offline = pd.Series(False, index=workloads_df.index)

    online = workloads_df[is_active & (age_h < 24)]
    offline = workloads_df[is_offline]
    lost_lt24 = workloads_df[is_active & (age_h >= 24) & (age_h < 48)]
    lost_24_48 = workloads_df[is_active & (age_h >= 48)]

    _write_sheet("Online", online)
    _write_sheet("Offline", offline)
    _write_sheet("Lost <24h", lost_lt24)
    _write_sheet("Lost 24-48h", lost_24_48)

    wb.save(out_path)
    return out_path
