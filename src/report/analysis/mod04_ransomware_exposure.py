"""Module 4: Ransomware Exposure Analysis."""
from __future__ import annotations
import pandas as pd

_RISK_COLORS = {'critical': 'CRITICAL', 'high': 'HIGH',
                'medium': 'MEDIUM', 'low': 'LOW'}

def ransomware_exposure(df: pd.DataFrame, report_config: dict, top_n: int = 20) -> dict:
    """
    Four-part ransomware exposure analysis based on Illumio Ransomware Protection
    port classification (20 high-risk ports across 4 levels).
    """
    if df.empty:
        return {'error': 'No data'}

    # Build port → level mapping
    port_to_level: dict[int, dict] = {}
    for level, entries in report_config.get('ransomware_risk_ports', {}).items():
        for entry in entries:
            ports = entry.get('ports', [])
            if isinstance(ports, int):
                ports = [ports]
            for p in ports:
                port_to_level[p] = {
                    'level': level,
                    'service': entry.get('service', ''),
                    'control': entry.get('control', ''),
                }

    if not port_to_level:
        return {'error': 'No ransomware risk port configuration found'}

    # Tag each flow
    df2 = df.copy()
    df2['risk_level'] = df2['port'].map(lambda p: port_to_level.get(p, {}).get('level', ''))
    df2['risk_service'] = df2['port'].map(lambda p: port_to_level.get(p, {}).get('service', ''))
    risk_df = df2[df2['risk_level'] != ''].copy()

    # Part A: Risk summary by level
    part_a = (risk_df.groupby('risk_level').agg(
        flows=('port', 'count'),
        unique_ports=('port', 'nunique'),
        unique_hosts=('dst_ip', 'nunique'),
    ).reset_index().rename(columns={'risk_level': 'Risk Level', 'flows': 'Flows',
                                    'unique_ports': 'Unique Ports',
                                    'unique_hosts': 'Unique Dst Hosts'}))
    # Sort critical → high → medium → low
    order = ['critical', 'high', 'medium', 'low']
    part_a['_order'] = part_a['Risk Level'].map({v: i for i, v in enumerate(order)})
    part_a = part_a.sort_values('_order').drop(columns='_order')

    # Part B: Per-port detail
    part_b_rows = []
    for port, meta in sorted(port_to_level.items()):
        sub = risk_df[risk_df['port'] == port]
        if sub.empty:
            continue
        pd_counts = sub['policy_decision'].value_counts().to_dict()
        part_b_rows.append({
            'Port': port,
            'Service': meta['service'],
            'Risk Level': meta['level'].upper(),
            'Control': meta['control'],
            'Total Flows': len(sub),
            'Allowed': pd_counts.get('allowed', 0),
            'Blocked': pd_counts.get('blocked', 0),
            'Potentially Blocked': pd_counts.get('potentially_blocked', 0),
            'Unique Src IPs': sub['src_ip'].nunique(),
            'Unique Dst IPs': sub['dst_ip'].nunique(),
        })
    part_b = pd.DataFrame(part_b_rows)

    # Part C: Exposure by policy decision
    part_c = (risk_df.groupby('policy_decision').agg(
        flows=('port', 'count'),
    ).reset_index().rename(columns={'policy_decision': 'Decision', 'flows': 'Flows'}))

    # Part D: Host exposure ranking (dst hosts exposed to the most risk ports)
    part_d = (risk_df.groupby('dst_ip')
              .agg(unique_risk_ports=('port', 'nunique'),
                   total_flows=('port', 'count'),
                   risk_services=('risk_service', lambda x: ', '.join(sorted(set(x)))))
              .reset_index()
              .nlargest(top_n, 'unique_risk_ports')
              .rename(columns={'dst_ip': 'Destination IP',
                               'unique_risk_ports': 'Unique Risk Ports',
                               'total_flows': 'Total Flows',
                               'risk_services': 'Exposed Services'}))

    # Part E: Investigation targets — hosts with ALLOWED traffic on critical/high ports
    allowed_high = risk_df[
        (risk_df['policy_decision'] == 'allowed') &
        (risk_df['risk_level'].isin(['critical', 'high']))
    ].copy()
    if not allowed_high.empty:
        part_e = (allowed_high.groupby('dst_ip')
                  .agg(
                      risk_level=('risk_level', lambda x: '/'.join(
                          sorted(set(x), key=lambda v: order.index(v) if v in order else 99))),
                      exposed_ports=('port', lambda x: ', '.join(str(p) for p in sorted(set(x)))),
                      services=('risk_service', lambda x: ', '.join(sorted(set(x)))),
                      src_count=('src_ip', 'nunique'),
                      allowed_flows=('port', 'count'),
                  )
                  .reset_index()
                  .nlargest(top_n, 'allowed_flows')
                  .rename(columns={
                      'dst_ip': 'Target IP',
                      'risk_level': 'Risk Level',
                      'exposed_ports': 'Exposed Ports',
                      'services': 'Services',
                      'src_count': 'Unique Sources',
                      'allowed_flows': 'Allowed Flows',
                  }))
    else:
        part_e = pd.DataFrame()

    return {
        'risk_flows_total': len(risk_df),
        'part_a_summary': part_a,
        'part_b_per_port': part_b,
        'part_c_by_decision': part_c,
        'part_d_host_exposure': part_d,
        'part_e_investigation': part_e,
    }
