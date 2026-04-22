"""Module 8: Unmanaged Host Analysis."""
from __future__ import annotations
import pandas as pd
from src.i18n import t, get_language

def unmanaged_traffic(df: pd.DataFrame, top_n: int = 20) -> dict:
    """
    Analyse traffic involving unmanaged (non-PCE-managed) hosts.
    Includes per-app and per-port/protocol aggregation for unmanaged flows.
    """
    if df.empty:
        return {'error': 'No data'}

    unmanaged_src = df[df['src_managed'] == False].copy()
    unmanaged_dst = df[df['dst_managed'] == False].copy()
    any_unmanaged = df[(df['src_managed'] == False) | (df['dst_managed'] == False)]

    total_flows = len(df)
    unmanaged_flow_count = len(any_unmanaged)
    unmanaged_pct = round(unmanaged_flow_count / total_flows * 100, 1) if total_flows else 0

    # Top unmanaged source IPs (most active)
    top_unmanaged_src = (unmanaged_src.groupby('src_ip').agg(
        connections=('num_connections', 'sum'),
        unique_dst=('dst_ip', 'nunique'),
        unique_ports=('port', 'nunique'),
        bytes_total=('bytes_total', 'sum'),
    ).reset_index().nlargest(top_n, 'connections')
    .rename(columns={'src_ip': 'Unmanaged Source IP',
                     'connections': 'Connections',
                     'unique_dst': 'Unique Dst',
                     'unique_ports': 'Unique Ports',
                     'bytes_total': 'Bytes'}))

    # Top unmanaged destination IPs
    top_unmanaged_dst = (unmanaged_dst.groupby('dst_ip').agg(
        connections=('num_connections', 'sum'),
        unique_src=('src_ip', 'nunique'),
    ).reset_index().nlargest(top_n, 'connections')
    .rename(columns={'dst_ip': 'Unmanaged Dst IP',
                     'connections': 'Connections',
                     'unique_src': 'Unique Sources'}))

    # Managed hosts most targeted by unmanaged sources
    if not unmanaged_src.empty:
        managed_dst_from_unmanaged = (
            unmanaged_src[unmanaged_src['dst_managed'] == True]
            .groupby(['dst_ip', 'dst_hostname'])['num_connections'].sum()
            .reset_index().nlargest(top_n, 'num_connections')
            .rename(columns={'dst_ip': 'Managed Destination IP',
                             'dst_hostname': 'Hostname',
                             'num_connections': 'Connections from Unmanaged Src'}))
    else:
        managed_dst_from_unmanaged = pd.DataFrame()

    # Per destination app: unmanaged sources reaching each managed app
    per_dst_app = _per_app_unmanaged(unmanaged_src, top_n=top_n)

    # Per port/protocol: which services are most exposed to unmanaged hosts
    per_port_proto = _per_port_proto_unmanaged(unmanaged_src, top_n=top_n)

    # Unmanaged source × port detail (which IPs talking on which ports)
    src_port_detail = _src_port_detail(unmanaged_src, top_n=top_n)

    managed_flow_count = total_flows - unmanaged_flow_count
    return {
        'unmanaged_flow_count': unmanaged_flow_count,
        'unmanaged_pct': unmanaged_pct,
        'unique_unmanaged_src': unmanaged_src['src_ip'].nunique(),
        'unique_unmanaged_dst': unmanaged_dst['dst_ip'].nunique(),
        'top_unmanaged_src': top_unmanaged_src,
        'top_unmanaged_dst': top_unmanaged_dst,
        'managed_hosts_targeted_by_unmanaged': managed_dst_from_unmanaged,
        'per_dst_app': per_dst_app,
        'per_port_proto': per_port_proto,
        'src_port_detail': src_port_detail,
        'chart_spec': {
            'type': 'pie',
            'title': 'Managed vs Unmanaged Flows',
            'data': {
                'labels': [
                    t('rpt_managed', default='Managed'),
                    t('rpt_unmanaged', default='Unmanaged'),
                ],
                'values': [managed_flow_count, unmanaged_flow_count],
            },
            'i18n': {'lang': get_language()},
        },
    }

def _per_app_unmanaged(unmanaged_src: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Which managed destination apps receive the most traffic from unmanaged sources."""
    if unmanaged_src.empty:
        return pd.DataFrame()
    managed_flows = unmanaged_src[unmanaged_src['dst_managed'] == True]
    if managed_flows.empty:
        return pd.DataFrame()
    result = (managed_flows.groupby('dst_app')
              .agg(connections=('num_connections', 'sum'),
                   unique_src_ips=('src_ip', 'nunique'),
                   unique_ports=('port', 'nunique'),
                   unique_decisions=('policy_decision', 'nunique'))
              .reset_index()
              .nlargest(top_n, 'connections')
              .rename(columns={'dst_app': 'Destination App',
                               'connections': 'Connections',
                               'unique_src_ips': 'Unique Unmanaged Sources',
                               'unique_ports': 'Unique Ports',
                               'unique_decisions': 'Decision Types'}))
    return result

def _per_port_proto_unmanaged(unmanaged_src: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Which port/protocol combinations see the most unmanaged source traffic."""
    if unmanaged_src.empty or 'port' not in unmanaged_src.columns:
        return pd.DataFrame()
    active = unmanaged_src[unmanaged_src['port'] > 0].copy()
    if active.empty:
        return pd.DataFrame()

    proto_col = 'proto' if 'proto' in active.columns else None
    if proto_col:
        group_cols = ['port', proto_col]
    else:
        group_cols = ['port']

    result = (active.groupby(group_cols)
              .agg(connections=('num_connections', 'sum'),
                   unique_src=('src_ip', 'nunique'),
                   unique_dst_apps=('dst_app', 'nunique'))
              .reset_index()
              .nlargest(top_n, 'connections'))

    rename_map = {'port': 'Port', 'connections': 'Connections',
                  'unique_src': 'Unique Unmanaged Src', 'unique_dst_apps': 'Dst Apps'}
    if proto_col:
        rename_map[proto_col] = 'Protocol'
        # Map numeric proto to name
        result['Protocol'] = result[proto_col].map({6: 'TCP', 17: 'UDP', 1: 'ICMP'}).fillna(result[proto_col].astype(str))
        result = result.drop(columns=[proto_col])

    result = result.rename(columns=rename_map).reset_index(drop=True)
    return result

def _src_port_detail(unmanaged_src: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Top unmanaged source IP × port combinations — reveals targeted service access patterns."""
    if unmanaged_src.empty:
        return pd.DataFrame()
    active = unmanaged_src[unmanaged_src['port'] > 0]
    if active.empty:
        return pd.DataFrame()
    result = (active.groupby(['src_ip', 'port', 'policy_decision'])
              .agg(connections=('num_connections', 'sum'),
                   unique_dst=('dst_ip', 'nunique'))
              .reset_index()
              .nlargest(top_n, 'connections')
              .rename(columns={'src_ip': 'Source IP', 'port': 'Port',
                               'policy_decision': 'Decision',
                               'connections': 'Connections',
                               'unique_dst': 'Unique Destinations'}))
    return result
