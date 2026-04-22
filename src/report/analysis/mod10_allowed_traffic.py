"""Module 10: Allowed Traffic Analysis."""
from __future__ import annotations
import pandas as pd
from src.i18n import t, get_language

def allowed_traffic(df: pd.DataFrame, top_n: int = 20) -> dict:
    """
    Analyse flows with policy_decision='allowed':
    - Top allowed app→app flows
    - Allowed but unmanaged source (audit flag)
    - Top allowed ports
    """
    if df.empty:
        return {'error': 'No data'}

    allowed = df[df['policy_decision'] == 'allowed'].copy()
    if allowed.empty:
        return {'total_allowed': 0, 'note': 'No allowed flows in dataset'}

    # Top allowed app→app flows
    allowed['flow_pair'] = (allowed['src_app'].fillna('') + ' → ' +
                            allowed['dst_app'].fillna(''))
    top_app_flows = (allowed.groupby('flow_pair')['num_connections'].sum()
                     .reset_index().nlargest(top_n, 'num_connections')
                     .rename(columns={'flow_pair': 'Flow (src_app→dst_app)',
                                      'num_connections': 'Connections'}))

    # Allowed + unmanaged source = potential audit flag
    audit_flags = allowed[allowed['src_managed'] == False].copy()
    _audit_keys = ['src_ip', 'dst_ip', 'port', 'proto'] if 'proto' in audit_flags.columns else ['src_ip', 'dst_ip', 'port']
    if not audit_flags.empty:
        audit_table = (audit_flags.groupby(_audit_keys)['num_connections']
                       .sum().reset_index().nlargest(top_n, 'num_connections')
                       .rename(columns={'src_ip': 'Unmanaged Source',
                                        'dst_ip': 'Destination',
                                        'port': 'Port', 'proto': 'Proto',
                                        'num_connections': 'Connections'}))
        if 'Port' in audit_table.columns:
            audit_table['Port'] = audit_table['Port'].astype('Int64')
        if 'Connections' in audit_table.columns:
            audit_table['Connections'] = audit_table['Connections'].astype('Int64')
        if 'Proto' in audit_table.columns and audit_table['Proto'].astype(str).str.strip().eq('').all():
            audit_table = audit_table.drop(columns=['Proto'])
    else:
        audit_table = pd.DataFrame()

    # Top allowed ports (by port+proto)
    _port_keys = ['port', 'proto'] if 'proto' in allowed.columns else ['port']
    top_ports = (allowed[allowed['port'] > 0].groupby(_port_keys)['num_connections'].sum()
                 .reset_index().nlargest(top_n, 'num_connections')
                 .rename(columns={'port': 'Port', 'proto': 'Proto',
                                  'num_connections': 'Connections'}))
    if 'Port' in top_ports.columns:
        top_ports['Port'] = top_ports['Port'].astype('Int64')
    if 'Connections' in top_ports.columns:
        top_ports['Connections'] = top_ports['Connections'].astype('Int64')
    if 'Proto' in top_ports.columns and top_ports['Proto'].astype(str).str.strip().eq('').all():
        top_ports = top_ports.drop(columns=['Proto'])

    # Phase 5: chart_spec — line chart of top allowed ports by connection count
    if not top_ports.empty:
        port_labels = list(top_ports['Port'].head(10).astype(str))
        port_values = list(top_ports['Connections'].head(10))
    else:
        port_labels, port_values = [], []

    return {
        'total_allowed': len(allowed),
        'top_app_flows': top_app_flows,
        'audit_flags': audit_table,
        'audit_flag_count': len(audit_flags),
        'top_allowed_ports': top_ports,
        'chart_spec': {
            'type': 'line',
            'title': 'Allowed Traffic Timeline',
            'x_label': 'Port',
            'y_label': 'Connections',
            'data': {
                'x': port_labels,
                'y': port_values,
            },
            'i18n': {'lang': get_language()},
        },
    }
