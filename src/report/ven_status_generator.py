"""
src/report/ven_status_generator.py
Orchestrates the VEN Status Inventory Report.

Classifies every VEN-managed workload as:
  - Online  : agent status is 'active'
  - Offline : everything else

Then further buckets offline VENs by when they last sent a heartbeat:
  - Lost in last 24 h
  - Lost in previous 24-48 h window
  - Long-term offline (last heartbeat > 48 h ago or unknown)
"""
import datetime
import logging
import os
import pandas as pd
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _fmt_tz_str(dt: datetime.datetime) -> str:
    """Format a timezone-aware datetime as '2026-03-26 16:30:00 (UTC+08:00)'."""
    offset_s = dt.strftime('%z')
    sign = offset_s[0]; hh = offset_s[1:3]; mm = offset_s[3:5]
    tz_label = f"UTC{sign}{hh}:{mm}" if mm != '00' else f"UTC{sign}{hh}"
    return dt.strftime('%Y-%m-%d %H:%M:%S') + f' ({tz_label})'

_ONLINE_STATUSES = {'active', 'online'}


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

    def generate(self) -> VenStatusResult:
        if not self.api:
            raise RuntimeError("api_client required for VEN status report")

        print("[VEN Report] Fetching managed workloads from PCE…")
        workloads = self.api.fetch_managed_workloads()

        if not workloads:
            print("[VEN Report] ⚠ No managed workloads returned.")
            return VenStatusResult(record_count=0)

        print(f"[VEN Report] {len(workloads):,} VENs found — analyzing…")
        df = self._build_dataframe(workloads)
        results = self._analyze(df)
        print("[VEN Report] Analysis complete.")

        return VenStatusResult(
            record_count=len(df),
            module_results=results,
            dataframe=df,
        )

    def export(self, result: VenStatusResult, fmt: str = 'html', output_dir: str = 'reports') -> list:
        from src.report.exporters.ven_html_exporter import VenHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter
        os.makedirs(output_dir, exist_ok=True)
        paths = []
        if fmt in ('html', 'all'):
            path = VenHtmlExporter(result.module_results, df=result.dataframe).export(output_dir)
            paths.append(path)
            print(f"[VEN Report] ✅ HTML  saved: {path}")
        if fmt in ('csv', 'all'):
            path = CsvExporter(result.module_results, report_label='VEN_Status').export(output_dir)
            paths.append(path)
            print(f"[VEN Report] ✅ CSV (ZIP) saved: {path}")
        return paths

    # ── private ──────────────────────────────────────────────────────────────

    def _build_dataframe(self, workloads: list) -> pd.DataFrame:
        rows = []
        for w in workloads:
            agent = w.get('agent') or {}
            st = agent.get('status') or {}

            # Collect interface IPs
            ips = [iface.get('address', '') for iface in w.get('interfaces', []) if iface.get('address')]
            ip_str = ', '.join(ips) or w.get('public_ip', '')

            # Flatten labels
            labels_str = '; '.join(
                f"{lbl.get('key', '?')}:{lbl.get('value', '?')}"
                for lbl in w.get('labels', [])
                if isinstance(lbl, dict) and lbl.get('key') and lbl.get('value')
            )

            rows.append({
                'hostname':         w.get('hostname', w.get('name', '')),
                'name':             w.get('name', ''),
                'ip':               ip_str,
                'labels':           labels_str,
                'ven_status':       st.get('status', ''),
                'last_heartbeat':   st.get('last_heartbeat_on', ''),
                'policy_received':  st.get('security_policy_refresh_at', ''),
                'paired_at':        st.get('managed_since', ''),
                'ven_version':      st.get('agent_version', ''),
                'pce_fqdn':         st.get('active_pce_fqdn', ''),
            })

        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=['hostname', 'name', 'ip', 'labels', 'ven_status',
                     'last_heartbeat', 'policy_received', 'paired_at',
                     'ven_version', 'pce_fqdn']
        )

    def _parse_tz(self) -> datetime.timezone:
        tz_str = self.cm.config.get('settings', {}).get('timezone', 'local')
        try:
            if not tz_str or tz_str == 'local':
                offset = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
                return datetime.timezone(offset)
            if tz_str == 'UTC':
                return datetime.timezone.utc
            if tz_str.startswith('UTC+') or tz_str.startswith('UTC-'):
                sign = 1 if tz_str[3] == '+' else -1
                total_minutes = int(sign * float(tz_str[4:]) * 60)
                return datetime.timezone(datetime.timedelta(minutes=total_minutes))
        except Exception:
            pass
        return datetime.timezone.utc

    def _analyze(self, df: pd.DataFrame) -> dict:
        now = datetime.datetime.now(self._parse_tz())
        cutoff_24h = now - datetime.timedelta(hours=24)
        cutoff_48h = now - datetime.timedelta(hours=48)

        _COLS = ['hostname', 'name', 'ip', 'labels',
                 'ven_status', 'last_heartbeat', 'policy_received',
                 'paired_at', 'ven_version']

        def _parse(ts: str):
            if not ts:
                return None
            try:
                return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception:
                return None

        def _bool_mask(series, predicate):
            """Apply predicate safely; always returns a proper boolean Series."""
            if series.empty:
                return pd.Series([], dtype=bool)
            return series.apply(predicate).astype(bool)

        def _clean(d):
            if d.empty:
                return pd.DataFrame(columns=_COLS)
            # Only select columns that exist (guard against unexpected API shapes)
            cols = [c for c in _COLS if c in d.columns]
            return d[cols].sort_values('last_heartbeat', ascending=False).reset_index(drop=True)

        df = df.copy()
        df['_hb_dt'] = df['last_heartbeat'].apply(_parse)

        is_online = df['ven_status'].astype(str).str.lower().isin(_ONLINE_STATUSES)
        df_online  = df[is_online].copy()
        df_offline = df[~is_online].copy()

        # Offline VENs bucketed by last-heartbeat time
        mask_today = _bool_mask(df_offline['_hb_dt'],
                                lambda t: t is not None and t >= cutoff_24h)
        mask_yest  = _bool_mask(df_offline['_hb_dt'],
                                lambda t: t is not None and cutoff_48h <= t < cutoff_24h)

        df_lost_today = df_offline[mask_today] if len(mask_today) else df_offline.iloc[0:0]
        df_lost_yest  = df_offline[mask_yest]  if len(mask_yest)  else df_offline.iloc[0:0]

        kpis = [
            {'label': 'Total VENs',                    'value': str(len(df))},
            {'label': 'Online',                         'value': str(len(df_online))},
            {'label': 'Offline',                        'value': str(len(df_offline))},
            {'label': 'Lost Connection (Last 24h)',     'value': str(len(df_lost_today))},
            {'label': 'Lost Connection (24-48h ago)',   'value': str(len(df_lost_yest))},
        ]

        return {
            'generated_at':   _fmt_tz_str(now),
            'kpis':           kpis,
            'online':         _clean(df_online),
            'offline':        _clean(df_offline),
            'lost_today':     _clean(df_lost_today),
            'lost_yesterday': _clean(df_lost_yest),
        }
