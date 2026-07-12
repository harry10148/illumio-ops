"""
src/report/parsers/api_parser.py
PCE API JSON flow records → Unified DataFrame

Converts the list of flow records returned by
api_client.fetch_traffic_for_report() into the same Unified DataFrame schema
used by all 12 analysis modules.

Reuses calculate_mbps() and calculate_volume_mb() from src.analyzer so
bandwidth and volume logic matches the monitoring engine exactly.
"""
from __future__ import annotations

from loguru import logger
import pandas as pd

# ─── Protocol mapping ─────────────────────────────────────────────────────────

_PROTO_MAP = {6: 'TCP', 17: 'UDP', 1: 'ICMP', 58: 'ICMPv6'}

# ─── Guaranteed label keys ───────────────────────────────────────────────────

LABEL_KEYS = ('app', 'env', 'loc', 'role')


def _extract_labels(labels: list) -> dict:
    """Extract label key→value from PCE label list.
    PCE label format: [{"key": "role", "value": "web", "href": "..."}, ...]
    """
    result = {}
    for lbl in labels or []:
        k = lbl.get('key', '')
        v = lbl.get('value', '')
        if k:
            result[k] = v
    return result


def flatten_flow_record(r: dict) -> dict:
    """Flatten one PCE flow record into the unified-schema row dict.

    Module-level + pure so the cache ingestor can precompute and store this
    verbatim (report_json) and reports can rebuild their DataFrame without
    re-running this per row. Single source of truth for the flatten mapping.
    """
    from src.analyzer import calculate_mbps, calculate_volume_mb

    src = r.get('src') or {}
    dst = r.get('dst') or {}
    svc = r.get('service') or {}
    src_wl = src.get('workload') or {}
    dst_wl = dst.get('workload') or {}

    src_labels = _extract_labels(src_wl.get('labels', []))
    dst_labels = _extract_labels(dst_wl.get('labels', []))

    mbps, _, _, _ = calculate_mbps(r)
    vol_mb, _ = calculate_volume_mb(r)
    bytes_total = int(vol_mb * 1024 * 1024)

    def _f(key): return float(r.get(key) or 0)

    row = {
        'src_ip':           src.get('ip', ''),
        'src_hostname':     src_wl.get('hostname', src.get('ip', '')),
        'src_managed':      bool(src_wl),
        'src_enforcement':  src_wl.get('enforcement_mode', ''),
        'src_os_type':      src_wl.get('os_type', ''),
        'src_app':          src_labels.get('app', ''),
        'src_env':          src_labels.get('env', ''),
        'src_loc':          src_labels.get('loc', ''),
        'src_role':         src_labels.get('role', ''),
        'src_extra_labels': {k: v for k, v in src_labels.items() if k not in LABEL_KEYS},
        'dst_ip':           dst.get('ip', ''),
        'dst_hostname':     dst_wl.get('hostname', dst.get('ip', '')),
        'dst_managed':      bool(dst_wl),
        'dst_enforcement':  dst_wl.get('enforcement_mode', ''),
        'dst_os_type':      dst_wl.get('os_type', ''),
        'dst_fqdn':         dst.get('fqdn', ''),
        'dst_app':          dst_labels.get('app', ''),
        'dst_env':          dst_labels.get('env', ''),
        'dst_loc':          dst_labels.get('loc', ''),
        'dst_role':         dst_labels.get('role', ''),
        'dst_extra_labels': {k: v for k, v in dst_labels.items() if k not in LABEL_KEYS},
        'port':             svc.get('port', 0) or 0,
        'proto':            _PROTO_MAP.get(int(svc.get('proto', 0) or 0), str(svc.get('proto', ''))),
        'process_name':     svc.get('process_name', '') or '',
        'windows_service_name': svc.get('windows_service_name', '') or '',
        'user_name':        svc.get('user_name', '') or '',
        'num_connections':  int(r.get('num_connections', 1) or 1),
        'state':            r.get('state', '') or '',
        'policy_decision':  r.get('policy_decision', 'unknown') or 'unknown',
        'first_detected':   r.get('first_detected'),
        'last_detected':    r.get('last_detected'),
        'bytes_in':     int(_f('dst_dbi') or _f('dst_tbi')),
        'bytes_out':    int(_f('dst_dbo') or _f('dst_tbo')),
        'bytes_total':  bytes_total,
        'bandwidth_mbps': mbps,
        'raw_dst_dbi': _f('dst_dbi'),
        'raw_dst_dbo': _f('dst_dbo'),
        'raw_dst_tbi': _f('dst_tbi'),
        'raw_dst_tbo': _f('dst_tbo'),
        'raw_ddms':    _f('ddms'),
        'raw_tdms':    _f('tdms'),
    }

    # Draft policy decision is a genuine PCE field that only appears on flow
    # records when the async traffic query ran with compute_draft (the PCE
    # update_rules pass). Carry it through verbatim so the unified df gains a
    # 'draft_policy_decision' column ONLY for draft-PD runs; for ordinary runs
    # the key is absent and the column is omitted, so the R01–R05 draft rules
    # and mod_draft_* modules correctly no-op instead of fabricating data.
    draft_pd = r.get('draft_policy_decision')
    if draft_pd:
        row['draft_policy_decision'] = draft_pd

    return row


def build_unified_df(rows: list[dict], data_source: str) -> pd.DataFrame:
    """Assemble flattened rows into the unified DataFrame (dates coerced).

    Shared by APIParser (live) and CacheReader.read_flows_df (cached) so both
    produce an identical frame regardless of source.
    """
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in ('first_detected', 'last_detected'):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    df['data_source'] = data_source
    return df


# ─── API Parser ──────────────────────────────────────────────────────────────

class APIParser:
    """
    Parse PCE API traffic flow records into a Unified DataFrame.

    Usage:
        parser = APIParser()
        df = parser.parse(flow_records)   # flow_records = list[dict] from API
    """

    def parse(self, records: list[dict]) -> pd.DataFrame:
        """Convert API flow records to Unified DataFrame."""
        if not records:
            logger.warning("[APIParser] No records to parse.")
            return pd.DataFrame()

        logger.info(f"[APIParser] Parsing {len(records)} flow records")
        df = build_unified_df([flatten_flow_record(r) for r in records], 'api')
        logger.info(f"[APIParser] Produced DataFrame: {len(df)} rows × {len(df.columns)} cols")
        return df

    # ── private ──────────────────────────────────────────────────────────────

    def _flatten(self, r: dict) -> dict:
        """Back-compat thin wrapper around the module-level flatten."""
        row = flatten_flow_record(r)
        for col in ('first_detected', 'last_detected'):
            row[col] = pd.to_datetime(row[col], errors='coerce')
        return row
