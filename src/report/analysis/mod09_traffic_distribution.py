"""Module 9: Traffic Distribution."""
from __future__ import annotations
import pandas as pd

LABEL_KEYS = ('env', 'app', 'role', 'loc')


def traffic_distribution(df: pd.DataFrame, top_n: int = 20) -> dict:
    """
    Multi-dimensional traffic distribution:
    - Per label key (flows per value)
    - Per port/service
    - Role→Role flow patterns
    - Enforcement mode distribution
    """
    if df.empty:
        return {'error': 'No data'}

    result: dict = {}

    # Per label key distribution
    label_dist = {}
    for key in LABEL_KEYS:
        for side in ('src', 'dst'):
            col = f'{side}_{key}'
            if col in df.columns:
                dist = (df[df[col] != ''].groupby(col)['num_connections'].sum()
                        .reset_index().nlargest(top_n, 'num_connections')
                        .rename(columns={col: f'{side.capitalize()} {key.capitalize()}',
                                         'num_connections': 'Connections'}))
                label_dist[f'{side}_{key}'] = dist
    result['label_distribution'] = label_dist

    # Port / service distribution (group by port+proto so TCP/53 vs UDP/53 are distinct)
    _port_keys = ['port', 'proto'] if 'proto' in df.columns else ['port']
    port_dist = (df[df['port'] > 0].groupby(_port_keys).agg(
        connections=('num_connections', 'sum'),
        unique_src=('src_ip', 'nunique'),
        unique_dst=('dst_ip', 'nunique'),
    ).reset_index().nlargest(top_n, 'connections')
    .rename(columns={'port': 'Port', 'proto': 'Proto', 'connections': 'Connections',
                     'unique_src': 'Unique Src', 'unique_dst': 'Unique Dst'}))
    if 'Port' in port_dist.columns:
        port_dist['Port'] = port_dist['Port'].astype('Int64')
    for c in ('Connections', 'Unique Src', 'Unique Dst'):
        if c in port_dist.columns:
            port_dist[c] = port_dist[c].astype('Int64')
    if 'Proto' in port_dist.columns and port_dist['Proto'].astype(str).str.strip().eq('').all():
        port_dist = port_dist.drop(columns=['Proto'])
    result['port_distribution'] = port_dist

    # Role→Role flow patterns (src_role × dst_role)
    role_sub = df[(df['src_role'] != '') & (df['dst_role'] != '')]
    if not role_sub.empty:
        role_matrix = (role_sub.groupby(['src_role', 'dst_role'])['num_connections']
                       .sum().unstack(fill_value=0).reset_index())
        result['role_to_role_matrix'] = role_matrix
    else:
        result['role_to_role_matrix'] = pd.DataFrame()

    # Enforcement mode
    for side in ('src', 'dst'):
        col = f'{side}_enforcement'
        if col in df.columns and df[col].str.strip().ne('').any():
            enf_dist = (df[df[col] != ''].groupby(col).size()
                        .reset_index(name='Flow Count')
                        .rename(columns={col: 'Enforcement Mode'}))
            result[f'{side}_enforcement_dist'] = enf_dist

    # Protocol distribution
    proto_dist = (df[df['proto'] != ''].groupby('proto')['num_connections'].sum()
                  .reset_index().sort_values('num_connections', ascending=False)
                  .rename(columns={'proto': 'Protocol', 'num_connections': 'Connections'}))
    result['proto_distribution'] = proto_dist

    return result
