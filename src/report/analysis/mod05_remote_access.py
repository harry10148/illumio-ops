"""Module 5: Remote Access Protocol Analysis (Lateral Movement)."""
from __future__ import annotations
import pandas as pd
from src.i18n import t, get_language

def host_to_host_protocol_analysis(df: pd.DataFrame, report_config: dict, top_n: int = 20) -> dict:
    """
    Analyse lateral movement ports (RDP/SSH/VNC/SMB/WinRM etc.)
    for host-to-host connections and top talker pairs.
    """
    if df.empty:
        return {'error': 'No data'}

    lateral_ports = set(report_config.get('lateral_movement_ports', [3389, 5900, 22, 445, 5985, 5986, 5938, 23]))

    # Port → human-readable service name
    _svc = {3389: 'RDP', 5900: 'VNC', 22: 'SSH', 445: 'SMB',
            5985: 'WinRM-HTTP', 5986: 'WinRM-HTTPS', 5938: 'TeamViewer', 23: 'Telnet'}

    lateral = df[df['port'].isin(lateral_ports)].copy()
    lateral['service'] = lateral['port'].map(_svc).fillna(lateral['port'].astype(str))

    if lateral.empty:
        return {'total_lateral_flows': 0, 'top_talkers': pd.DataFrame(),
                'top_pairs': pd.DataFrame(), 'by_service': pd.DataFrame()}

    # By service
    by_svc = (lateral.groupby('service').agg(
        flows=('num_connections', 'sum'),
        unique_src=('src_ip', 'nunique'),
        unique_dst=('dst_ip', 'nunique'),
    ).reset_index().nlargest(top_n, 'flows')
     .rename(columns={'service': 'Service', 'flows': 'Connections',
                      'unique_src': 'Unique Src', 'unique_dst': 'Unique Dst'}))

    # Top src talkers (most unique destinations)
    top_talkers = (lateral.groupby(['src_ip', 'src_hostname'])['dst_ip'].nunique()
                   .reset_index()
                   .nlargest(top_n, 'dst_ip')
                   .rename(columns={'src_ip': 'Source IP', 'src_hostname': 'Hostname',
                                    'dst_ip': 'Unique Destinations'}))

    # Top host pairs
    lateral['pair'] = lateral['src_ip'] + ' → ' + lateral['dst_ip']
    top_pairs = (lateral.groupby(['pair', 'service'])['num_connections'].sum()
                 .reset_index().nlargest(top_n, 'num_connections')
                 .rename(columns={'pair': 'Host Pair', 'service': 'Service',
                                  'num_connections': 'Connections'}))

    # Top 5 services for chart_spec
    top5_labels = list(by_svc['Service'].head(5)) if not by_svc.empty else []
    top5_values = list(by_svc['Connections'].head(5)) if not by_svc.empty else []

    return {
        'total_lateral_flows': int(lateral['num_connections'].sum()),
        'unique_lateral_src': lateral['src_ip'].nunique(),
        'unique_lateral_dst': lateral['dst_ip'].nunique(),
        'by_service': by_svc,
        'top_talkers': top_talkers,
        'top_pairs': top_pairs,
        # Phase 5: chart_spec
        'chart_spec': {
            'type': 'bar',
            'title': t('rpt_ra_chart_title', default='Top Remote Access Ports'),
            'x_label': 'Service',
            'y_label': t('rpt_col_connections', default='Connections'),
            'data': {
                'labels': top5_labels,
                'values': top5_values,
            },
            'i18n': {'lang': get_language()},
        },
    }
