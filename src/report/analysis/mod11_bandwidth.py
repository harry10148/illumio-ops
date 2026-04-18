"""Module 11: Bandwidth & Data Volume Analysis."""
from __future__ import annotations
import pandas as pd

def bandwidth_analysis(df: pd.DataFrame, top_n: int = 20) -> dict:
    """
    Volume and bandwidth analysis:
    - Top connections by bytes
    - Top by application, environment, port
    - Bandwidth anomalies (high bytes-per-connection ratio)
    """
    if df.empty:
        return {'error': 'No data'}

    has_bytes = df[df['bytes_total'] > 0].copy()
    has_bw = df[df['bandwidth_mbps'] > 0].copy()

    if has_bytes.empty:
        return {
            'bytes_data_available': False,
            'note': 'No byte data available — data source may be API without interval bytes or CSV without byte columns.',
        }

    result: dict = {'bytes_data_available': True}

    # Top connections by total bytes (include bandwidth_mbps if available)
    _bw_cols = ['src_ip', 'src_hostname', 'dst_ip', 'dst_hostname',
                'port', 'proto', 'bytes_total', 'policy_decision']
    _bw_rename = {'src_ip': 'Src IP', 'src_hostname': 'Src Host',
                  'dst_ip': 'Dst IP', 'dst_hostname': 'Dst Host',
                  'port': 'Port', 'proto': 'Proto',
                  'bytes_total': 'Bytes Total', 'policy_decision': 'Decision'}
    if 'bandwidth_mbps' in has_bytes.columns:
        _bw_cols.insert(-1, 'bandwidth_mbps')
        _bw_rename['bandwidth_mbps'] = 'Bandwidth (Mbps)'
    top_by_bytes = (has_bytes.nlargest(top_n, 'bytes_total')[_bw_cols]
                    .rename(columns=_bw_rename))
    result['top_by_bytes'] = top_by_bytes

    # Top by src_app
    top_app_bytes = (has_bytes.groupby('src_app')['bytes_total'].sum()
                     .reset_index().nlargest(top_n, 'bytes_total')
                     .rename(columns={'src_app': 'Source App', 'bytes_total': 'Bytes Total'}))
    result['top_app_bytes'] = top_app_bytes

    # Top by src_env
    top_env_bytes = (has_bytes.groupby('src_env')['bytes_total'].sum()
                     .reset_index().nlargest(top_n, 'bytes_total')
                     .rename(columns={'src_env': 'Source Env', 'bytes_total': 'Bytes Total'}))
    result['top_env_bytes'] = top_env_bytes

    # Top by (port, proto) — int-typed port column
    _port_keys = ['port', 'proto'] if 'proto' in has_bytes.columns else ['port']
    top_port_bytes = (has_bytes[has_bytes['port'] > 0].groupby(_port_keys)['bytes_total'].sum()
                      .reset_index().nlargest(top_n, 'bytes_total')
                      .rename(columns={'port': 'Port', 'proto': 'Proto',
                                       'bytes_total': 'Bytes Total'}))
    if 'Port' in top_port_bytes.columns:
        top_port_bytes['Port'] = top_port_bytes['Port'].astype('Int64')
    if 'Proto' in top_port_bytes.columns and top_port_bytes['Proto'].astype(str).str.strip().eq('').all():
        top_port_bytes = top_port_bytes.drop(columns=['Proto'])
    result['top_port_bytes'] = top_port_bytes

    # Bandwidth stats
    if not has_bw.empty:
        top_bw = (has_bw.nlargest(top_n, 'bandwidth_mbps')
                  [['src_ip', 'dst_ip', 'port', 'proto', 'bandwidth_mbps', 'bytes_total']]
                  .rename(columns={'src_ip': 'Src IP', 'dst_ip': 'Dst IP',
                                   'port': 'Port', 'proto': 'Proto',
                                   'bandwidth_mbps': 'Bandwidth (Mbps)',
                                   'bytes_total': 'Bytes Total'}))
        result['top_bandwidth'] = top_bw
        result['max_bandwidth_mbps'] = round(float(has_bw['bandwidth_mbps'].max()), 3)
        result['avg_bandwidth_mbps'] = round(float(has_bw['bandwidth_mbps'].mean()), 3)
        result['p95_bandwidth_mbps'] = round(float(has_bw['bandwidth_mbps'].quantile(0.95)), 3)

    # Anomaly: bytes-per-connection ratio (potential exfiltration indicator)
    # Only flag rows with > 1 connection to avoid single-connection noise
    has_bytes['bytes_per_conn'] = has_bytes['bytes_total'] / has_bytes['num_connections'].clip(lower=1)
    multi_conn = has_bytes[has_bytes['num_connections'] > 1]
    if not multi_conn.empty:
        p95_bpc = multi_conn['bytes_per_conn'].quantile(0.95)
        result['anomaly_threshold_bytes_per_conn'] = round(float(p95_bpc), 1)
        anomalies = multi_conn[multi_conn['bytes_per_conn'] > p95_bpc]
    else:
        p95_bpc = has_bytes['bytes_per_conn'].quantile(0.95)
        result['anomaly_threshold_bytes_per_conn'] = round(float(p95_bpc), 1)
        anomalies = has_bytes[has_bytes['bytes_per_conn'] > p95_bpc]
    if not anomalies.empty:
        result['byte_ratio_anomalies'] = (
            anomalies.nlargest(top_n, 'bytes_per_conn')
            [['src_ip', 'dst_ip', 'port', 'bytes_total', 'num_connections', 'bytes_per_conn']]
            .rename(columns={'src_ip': 'Src IP', 'dst_ip': 'Dst IP',
                             'port': 'Port', 'bytes_total': 'Total Bytes',
                             'num_connections': 'Connections',
                             'bytes_per_conn': 'Bytes/Conn'})
        )
    result['total_bytes'] = int(has_bytes['bytes_total'].sum())
    result['total_mb'] = round(result['total_bytes'] / 1024 / 1024, 2)

    return result
