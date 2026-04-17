"""Module 1: Traffic Overview — KPI summary statistics."""
from __future__ import annotations
import pandas as pd


def traffic_overview(df: pd.DataFrame) -> dict:
    """
    Returns top-level KPI metrics for the Executive Summary and Overview sheet.
    """
    if df.empty:
        return {'error': 'No data'}

    total_flows = len(df)
    unique_src_ips = df['src_ip'].nunique()
    unique_dst_ips = df['dst_ip'].nunique()
    total_bytes = int(df['bytes_total'].sum())
    total_connections = int(df['num_connections'].sum())

    # Policy coverage: % of flows that are 'allowed'
    allowed = (df['policy_decision'] == 'allowed').sum()
    blocked = (df['policy_decision'] == 'blocked').sum()
    potential = (df['policy_decision'] == 'potentially_blocked').sum()
    unknown = total_flows - allowed - blocked - potential
    coverage_pct = round(allowed / total_flows * 100, 1) if total_flows else 0

    # Managed endpoints
    src_managed_pct = round(df['src_managed'].mean() * 100, 1) if total_flows else 0
    dst_managed_pct = round(df['dst_managed'].mean() * 100, 1) if total_flows else 0

    # Date range
    first = df['first_detected'].min()
    last = df['last_detected'].max()
    date_range = f"{first.date() if pd.notna(first) else 'N/A'} → {last.date() if pd.notna(last) else 'N/A'}"

    # Top ports (by flow count) — group by (port, proto) when available so the
    # table shows e.g. "53 / UDP" rather than a bare port number. Counts and
    # ports stay int-typed so rendered cells are "53" not "53.0".
    _port_df = df[df['port'] > 0]
    if _port_df.empty:
        top_ports = pd.DataFrame()
    else:
        has_proto = 'proto' in _port_df.columns
        group_keys = ['port', 'proto'] if has_proto else ['port']
        top_ports = (
            _port_df.groupby(group_keys).size()
            .nlargest(10).reset_index(name='Flow Count')
            .rename(columns={'port': 'Port', 'proto': 'Proto'})
        )
        top_ports['Port'] = top_ports['Port'].astype('Int64')
        top_ports['Flow Count'] = top_ports['Flow Count'].astype('Int64')
        if 'Proto' in top_ports.columns and top_ports['Proto'].astype(str).str.strip().eq('').all():
            top_ports = top_ports.drop(columns=['Proto'])

    # Top protocols
    top_protos = (df[df['proto'] != '']['proto']
                  .value_counts().head(5)
                  .reset_index()
                  .rename(columns={'proto': 'Protocol', 'count': 'Flow Count'}))

    return {
        'total_flows': total_flows,
        'total_connections': total_connections,
        'unique_src_ips': unique_src_ips,
        'unique_dst_ips': unique_dst_ips,
        'total_bytes': total_bytes,
        'total_mb': round(total_bytes / 1024 / 1024, 2),
        'policy_coverage_pct': coverage_pct,
        'allowed_flows': int(allowed),
        'blocked_flows': int(blocked),
        'potentially_blocked_flows': int(potential),
        'unknown_flows': int(unknown),
        'src_managed_pct': src_managed_pct,
        'dst_managed_pct': dst_managed_pct,
        'date_range': date_range,
        'top_ports': top_ports,
        'top_protocols': top_protos,
    }
