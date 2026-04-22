"""Module 2: Policy Decision Breakdown."""
from __future__ import annotations
import pandas as pd
from src.i18n import t, get_language

def policy_decision_analysis(df: pd.DataFrame, top_n: int = 20) -> dict:
    """
    Breakdown of traffic by policy_decision. Per decision: top app→app flows,
    top ports, managed/unmanaged ratio, inbound/outbound split, per-port coverage.
    """
    if df.empty:
        return {'error': 'No data'}

    total = len(df)
    results = {}

    for decision in ('allowed', 'blocked', 'potentially_blocked', 'unknown'):
        sub = df[df['policy_decision'] == decision]
        if sub.empty:
            results[decision] = {'count': 0}
            continue

        sub = sub.copy()
        sub['flow_pair'] = sub['src_app'].fillna('') + ' → ' + sub['dst_app'].fillna('')

        # Top app→app flows
        top_app_flows = (sub.groupby('flow_pair')['num_connections'].sum()
                         .nlargest(top_n).reset_index()
                         .rename(columns={'flow_pair': 'Flow (src_app→dst_app)',
                                          'num_connections': 'Connections'}))

        # Top ports (by port + proto, flattened so reset_index produces both columns)
        top_ports = _top_ports_table(sub, top_n=top_n)

        # Managed ratio
        managed_count = int(sub['src_managed'].sum())
        unmanaged_count = len(sub) - managed_count

        # Inbound vs outbound split (dst_managed=True → inbound to a VEN)
        inbound_mask = sub['dst_managed'] == True if 'dst_managed' in sub.columns else pd.Series(False, index=sub.index)
        outbound_mask = ~inbound_mask
        inbound_count = int(inbound_mask.sum())
        outbound_count = int(outbound_mask.sum())

        # Per-direction top ports
        top_inbound_ports = (
            _top_ports_table(sub[inbound_mask], top_n=10)
            if inbound_count > 0 else pd.DataFrame()
        )
        top_outbound_ports = (
            _top_ports_table(sub[outbound_mask], top_n=10)
            if outbound_count > 0 else pd.DataFrame()
        )

        results[decision] = {
            'count': len(sub),
            'pct_of_total': round(len(sub) / total * 100, 1) if total > 0 else 0.0,
            'top_app_flows': top_app_flows,
            'top_ports': top_ports,
            'managed_src_count': managed_count,
            'unmanaged_src_count': unmanaged_count,
            'inbound_count': inbound_count,
            'outbound_count': outbound_count,
            'top_inbound_ports': top_inbound_ports,
            'top_outbound_ports': top_outbound_ports,
        }

    # Per-port coverage: for each port, what % of flows are allowed
    port_coverage = _compute_port_coverage(df, top_n=top_n)
    results['port_coverage'] = port_coverage

    # Summary table
    summary = pd.DataFrame([
        {
            'Decision': d,
            'Flows': results[d]['count'],
            '% of Total': results[d].get('pct_of_total', 0.0),
            'Inbound': results[d].get('inbound_count', 0),
            'Outbound': results[d].get('outbound_count', 0),
        }
        for d in ('allowed', 'blocked', 'potentially_blocked', 'unknown')
    ])
    results['summary'] = summary

    # Phase 5: chart_spec for HTML (plotly) + PDF/Excel (matplotlib)
    results['chart_spec'] = {
        'type': 'pie',
        'title': 'Policy Decision Breakdown',
        'data': {
            'labels': [
                'Allowed',
                'Blocked',
                'Potentially Blocked',
            ],
            'values': [
                results.get('allowed', {}).get('count', 0),
                results.get('blocked', {}).get('count', 0),
                results.get('potentially_blocked', {}).get('count', 0),
            ],
        },
        'i18n': {'lang': get_language()},
    }

    return results

def _top_ports_table(sub: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Top N (port [, proto]) by connection count, as an int-typed DataFrame.

    Drops Proto column entirely if the input has no proto dimension (or all
    protos are empty), so downstream tables stay tidy.
    """
    filt = sub[sub['port'] > 0]
    if filt.empty:
        return pd.DataFrame()

    has_proto = 'proto' in filt.columns
    group_keys = ['port', 'proto'] if has_proto else ['port']

    grouped = (
        filt.groupby(group_keys)['num_connections'].sum()
        .nlargest(top_n).reset_index()
    )
    rename_map = {'port': 'Port', 'num_connections': 'Connections'}
    if has_proto:
        rename_map['proto'] = 'Proto'
    grouped = grouped.rename(columns=rename_map)
    grouped['Port'] = grouped['Port'].astype('Int64')
    grouped['Connections'] = grouped['Connections'].astype('Int64')

    if 'Proto' in grouped.columns and grouped['Proto'].astype(str).str.strip().eq('').all():
        grouped = grouped.drop(columns=['Proto'])
    return grouped

def _compute_port_coverage(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """For each high-traffic (port, proto): allowed / blocked / potentially_blocked
    counts and coverage %.

    Notes on semantics:
    - blocked = explicit deny rule matched, OR enforced mode with no allow match
      (firewall actually dropped the traffic)
    - potentially_blocked = no matching rule AND workload in visibility/test mode
      (traffic flowed through; would be dropped if enforcement were on)
    These must stay in separate columns — conflating them hides real policy gaps.
    """
    port_df = df[df['port'] > 0].copy()
    if port_df.empty:
        return pd.DataFrame()

    has_proto = 'proto' in port_df.columns
    group_keys = ['port', 'proto'] if has_proto else ['port']

    grouped = (
        port_df.groupby(group_keys + ['policy_decision'])['num_connections']
        .sum()
        .unstack(fill_value=0)
    )
    allowed = grouped.get('allowed', pd.Series(0, index=grouped.index))
    blocked = grouped.get('blocked', pd.Series(0, index=grouped.index))
    pb = grouped.get('potentially_blocked', pd.Series(0, index=grouped.index))

    total_per_key = grouped.sum(axis=1)
    coverage = (allowed / total_per_key.replace(0, 1) * 100).round(1)

    # grouped.index is a MultiIndex when has_proto — unpack to columns
    if has_proto:
        ports = [idx[0] for idx in grouped.index]
        protos = [idx[1] for idx in grouped.index]
    else:
        ports = list(grouped.index)
        protos = [''] * len(ports)

    result = pd.DataFrame({
        'Port': pd.array(ports, dtype='Int64'),
        'Proto': protos,
        'Total Flows': pd.array(total_per_key.values, dtype='Int64'),
        'Allowed': pd.array(allowed.values, dtype='Int64'),
        'Blocked': pd.array(blocked.values, dtype='Int64'),
        'Potentially Blocked': pd.array(pb.values, dtype='Int64'),
        'Coverage %': coverage.values,
    }).sort_values('Total Flows', ascending=False).head(top_n).reset_index(drop=True)

    # Drop Proto column entirely if every value is empty (keeps output clean
    # when upstream data has no proto dimension).
    if not has_proto or result['Proto'].astype(str).str.strip().eq('').all():
        result = result.drop(columns=['Proto'])

    return result
