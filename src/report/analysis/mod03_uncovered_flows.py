"""Module 3: Uncovered Flows — Policy Coverage Gaps."""
from __future__ import annotations
import pandas as pd

_REC_MAP = {
    'intra_app': "Intra-app flow: add an intra-scope rule to allow traffic within the same application.",
    'unmanaged_source': "Unmanaged source host: onboard to PCE or apply explicit deny / allow rule.",
    'cross_app': "Cross-app flow: add a rule-set entry for this src_app → dst_app communication.",
}

def uncovered_flows(df: pd.DataFrame, top_n: int = 20) -> dict:
    """
    Three-tier coverage analysis:
      - Enforced Coverage: flows explicitly allowed by active policy rules.
      - Staged Coverage: flows that would be blocked (potentially_blocked) —
        rules exist but workloads are still in test/visibility mode.
      - True Gap: blocked + unknown — no matching allow rule or not evaluated.

    Also produces top uncovered flows, structural recommendations, per-port gap
    ranking, and inbound/outbound coverage split.
    """
    if df.empty:
        return {'error': 'No data'}

    total = len(df)
    decisions = df['policy_decision'].str.lower()
    n_allowed = int((decisions == 'allowed').sum())
    n_pb = int((decisions == 'potentially_blocked').sum())
    n_blocked = int((decisions == 'blocked').sum())
    n_unknown = total - n_allowed - n_pb - n_blocked

    enforced_coverage_pct = round(n_allowed / total * 100, 1) if total else 0.0
    staged_coverage_pct = round(n_pb / total * 100, 1) if total else 0.0
    true_gap_pct = round((n_blocked + n_unknown) / total * 100, 1) if total else 0.0
    # Legacy field: overall coverage (allowed only)
    coverage_pct = enforced_coverage_pct

    uncovered = df[decisions != 'allowed'].copy()
    total_uncovered = len(uncovered)

    if uncovered.empty:
        return {
            'total_uncovered': 0,
            'coverage_pct': 100.0,
            'enforced_coverage_pct': 100.0,
            'staged_coverage_pct': 0.0,
            'true_gap_pct': 0.0,
            'n_allowed': n_allowed,
            'n_potentially_blocked': 0,
            'n_blocked': 0,
            'n_unknown': 0,
            'inbound_coverage_pct': 100.0,
            'outbound_coverage_pct': 100.0,
            'top_flows': pd.DataFrame(),
            'by_recommendation': pd.DataFrame(),
            'uncovered_ports': pd.DataFrame(),
            'uncovered_services': pd.DataFrame(),
        }

    # Inbound/outbound coverage split
    if 'dst_managed' in df.columns:
        inbound_df = df[df['dst_managed'] == True]
        outbound_df = df[df['dst_managed'] != True]
        inbound_unc = inbound_df[inbound_df['policy_decision'] != 'allowed']
        outbound_unc = outbound_df[outbound_df['policy_decision'] != 'allowed']
        inbound_cov = round((len(inbound_df) - len(inbound_unc)) / max(len(inbound_df), 1) * 100, 1)
        outbound_cov = round((len(outbound_df) - len(outbound_unc)) / max(len(outbound_df), 1) * 100, 1)
    else:
        inbound_cov = outbound_cov = None

    # Build flow key
    uncovered['flow_key'] = (
        uncovered['src_app'].fillna('').astype(str) + ' → ' +
        uncovered['dst_app'].fillna('').astype(str) + ':' +
        uncovered['port'].astype(str)
    )

    # Classify each flow
    def _classify(row):
        if not row['src_managed']:
            return 'unmanaged_source'
        if row['src_app'] == row['dst_app'] and row['src_app'] != '':
            return 'intra_app'
        return 'cross_app'

    uncovered['recommendation_type'] = uncovered.apply(_classify, axis=1)
    uncovered['recommendation'] = uncovered['recommendation_type'].map(_REC_MAP)

    top_flows = (uncovered.groupby(['flow_key', 'policy_decision', 'recommendation'])
                 .agg(connections=('num_connections', 'sum'),
                      unique_src=('src_ip', 'nunique'),
                      unique_dst=('dst_ip', 'nunique'))
                 .reset_index()
                 .nlargest(top_n, 'connections')
                 .rename(columns={'flow_key': 'Flow', 'policy_decision': 'Decision',
                                  'connections': 'Connections'}))

    by_rec = (uncovered.groupby('recommendation_type').size()
              .reset_index(name='Count')
              .rename(columns={'recommendation_type': 'Category'}))
    by_rec['Recommendation'] = by_rec['Category'].map(_REC_MAP)

    # Per-port gap ranking: ports with most uncovered flows
    uncovered_ports = _port_gap_ranking(df, uncovered, top_n=top_n)

    # Uncovered services: app+port combinations most in need of policy
    uncovered_services = _service_gap_ranking(uncovered, top_n=top_n)

    return {
        'total_uncovered': total_uncovered,
        'coverage_pct': coverage_pct,
        'enforced_coverage_pct': enforced_coverage_pct,
        'staged_coverage_pct': staged_coverage_pct,
        'true_gap_pct': true_gap_pct,
        'n_allowed': n_allowed,
        'n_potentially_blocked': n_pb,
        'n_blocked': n_blocked,
        'n_unknown': n_unknown,
        'inbound_coverage_pct': inbound_cov,
        'outbound_coverage_pct': outbound_cov,
        'top_flows': top_flows,
        'by_recommendation': by_rec,
        'uncovered_ports': uncovered_ports,
        'uncovered_services': uncovered_services,
    }

def _port_gap_ranking(df: pd.DataFrame, uncovered: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Ranks (port, proto) by number of uncovered flows; shows total vs uncovered and gap %."""
    has_proto = 'proto' in df.columns
    keys = ['port', 'proto'] if has_proto else ['port']

    port_total = df[df['port'] > 0].groupby(keys)['num_connections'].sum()
    port_unc = uncovered[uncovered['port'] > 0].groupby(keys)['num_connections'].sum()

    result = pd.DataFrame({'Total': port_total, 'Uncovered': port_unc}).fillna(0)
    result['Gap %'] = (result['Uncovered'] / result['Total'].replace(0, 1) * 100).round(1)
    result = (result[result['Uncovered'] > 0]
              .sort_values('Uncovered', ascending=False)
              .head(top_n)
              .reset_index()
              .rename(columns={'port': 'Port', 'proto': 'Proto',
                               'Total': 'Total Flows', 'Uncovered': 'Uncovered Flows'}))
    if 'Port' in result.columns:
        result['Port'] = result['Port'].astype('Int64')
    for c in ('Total Flows', 'Uncovered Flows'):
        if c in result.columns:
            result[c] = result[c].astype('Int64')
    if 'Proto' in result.columns and result['Proto'].astype(str).str.strip().eq('').all():
        result = result.drop(columns=['Proto'])
    return result

def _service_gap_ranking(uncovered: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Top (dst_app, port, proto) combinations with uncovered flows — surfaces missing policy rules."""
    if uncovered.empty:
        return pd.DataFrame()
    has_proto = 'proto' in uncovered.columns
    keys = ['dst_app', 'port', 'proto', 'policy_decision'] if has_proto else ['dst_app', 'port', 'policy_decision']
    rename = {'dst_app': 'Destination App', 'port': 'Port', 'proto': 'Proto',
              'policy_decision': 'Decision', 'connections': 'Connections',
              'unique_src_apps': 'Unique Source Apps'}
    svc = (uncovered[uncovered['port'] > 0]
           .groupby(keys)
           .agg(connections=('num_connections', 'sum'),
                unique_src_apps=('src_app', 'nunique'))
           .reset_index()
           .nlargest(top_n, 'connections')
           .rename(columns=rename))
    if 'Port' in svc.columns:
        svc['Port'] = svc['Port'].astype('Int64')
    for c in ('Connections', 'Unique Source Apps'):
        if c in svc.columns:
            svc[c] = svc[c].astype('Int64')
    if 'Proto' in svc.columns and svc['Proto'].astype(str).str.strip().eq('').all():
        svc = svc.drop(columns=['Proto'])
    return svc
