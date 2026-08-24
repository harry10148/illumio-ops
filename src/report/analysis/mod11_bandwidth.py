"""Module 11: Bandwidth & Data Volume Analysis."""
from __future__ import annotations
import pandas as pd
from src.i18n import t, get_language


def _lower_bound_mask(df: pd.DataFrame) -> pd.Series:
    """True where a row's bandwidth_mbps is calculate_mbps's Priority-3
    lower bound rather than a point value.

    The unified DataFrame doesn't carry calculate_mbps's `note` directly, but
    both parsers already carry the raw counters it prioritizes on: delta
    bytes + ddms for Priority-1 ("(Interval)"), total bytes + tdms for
    Priority-2 ("(Avg)"). Neither pairing present means calculate_mbps fell
    through to Priority-3 (bytes ÷ the flow's own span+1) -- a bound, not a
    point value. Replaying that same priority order here, against columns
    both parsers already produce, avoids a new parser-side column for this
    task's scope.

    A caller-built frame missing these columns entirely (e.g. a minimal test
    fixture) carries no evidence of a point-value path -- default to
    "bound", the direction that only overstates uncertainty, never
    understates it.
    """
    idx = df.index

    def _col(name: str) -> pd.Series:
        if name in df.columns:
            return pd.to_numeric(df[name], errors='coerce').fillna(0.0)
        return pd.Series(0.0, index=idx)

    delta_bytes = _col('raw_dst_dbo') + _col('raw_dst_dbi')
    ddms = _col('raw_ddms')
    total_bytes = _col('raw_dst_tbo') + _col('raw_dst_tbi')
    tdms = _col('raw_tdms')
    is_point = ((delta_bytes > 0) & (ddms > 0)) | ((total_bytes > 0) & (tdms > 0))
    return ~is_point


def bandwidth_analysis(df: pd.DataFrame, top_n: int = 20, *, lang: str = "en") -> dict:
    """
    Volume and bandwidth analysis:
    - Top connections by bytes
    - Top by application, environment, port
    - Data-volume anomalies (high bytes-per-connection ratio)
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

    # Rows with byte data but no computed rate (calculate_mbps's third
    # state, NaN in this column) don't participate in any bandwidth
    # statistic below -- that's correct arithmetic, but the count is
    # reported so the operator knows the statistics didn't cover everyone,
    # not just that they cover whoever happened to have a rate.
    if 'bandwidth_mbps' in has_bytes.columns:
        result['bandwidth_unavailable_count'] = int(has_bytes['bandwidth_mbps'].isna().sum())
    else:
        result['bandwidth_unavailable_count'] = len(has_bytes)
    result['bandwidth_candidate_count'] = len(has_bytes)

    # Top connections by total bytes (include bandwidth_mbps if available)
    _bw_cols = ['src_ip', 'src_hostname', 'dst_ip', 'dst_hostname',
                'port', 'proto', 'bytes_total', 'policy_decision']
    _bw_rename = {'src_ip': 'Src IP', 'src_hostname': 'Src Host',
                  'dst_ip': 'Dst IP', 'dst_hostname': 'Dst Host',
                  'port': 'Port', 'proto': 'Proto',
                  'bytes_total': 'Bytes Total', 'policy_decision': 'Decision'}
    if 'bandwidth_mbps' in has_bytes.columns:
        _measured_label = t('rpt_bw_basis_measured', lang=lang)
        _bound_label = t('rpt_bw_basis_bound', lang=lang)
        _rate_basis = pd.Series(_measured_label, index=has_bytes.index)
        _rate_basis = _rate_basis.mask(_lower_bound_mask(has_bytes), _bound_label)
        _rate_basis = _rate_basis.mask(has_bytes['bandwidth_mbps'].isna(), '—')
        has_bytes['rate_basis'] = _rate_basis
        _bw_cols.insert(-1, 'bandwidth_mbps')
        _bw_rename['bandwidth_mbps'] = 'Bandwidth (Mbps)'
        _bw_cols.insert(-1, 'rate_basis')
        _bw_rename['rate_basis'] = 'Rate Basis'
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
        bound_mask = _lower_bound_mask(has_bw)
        n_bound = int(bound_mask.sum())
        n_point = len(has_bw) - n_bound
        # Every row's true rate is >= what's stored (bound rows can only be
        # understated), so a max/mean/quantile taken over a population that
        # includes any bound row is itself provably >= what's computed here
        # (order statistics preserve pointwise domination) -- the aggregate
        # is a lower bound too, not a point value, whenever any input was.
        result['bandwidth_stats_is_bound'] = n_bound > 0
        result['bandwidth_bound_flow_count'] = n_bound
        result['bandwidth_point_flow_count'] = n_point

        top_bw_rows = has_bw.nlargest(top_n, 'bandwidth_mbps')
        _measured_label = t('rpt_bw_basis_measured', lang=lang)
        _bound_label = t('rpt_bw_basis_bound', lang=lang)
        top_bw_basis = _lower_bound_mask(top_bw_rows).map(
            {True: _bound_label, False: _measured_label})
        top_bw = (top_bw_rows[['src_ip', 'dst_ip', 'port', 'proto', 'bandwidth_mbps', 'bytes_total']]
                  .rename(columns={'src_ip': 'Src IP', 'dst_ip': 'Dst IP',
                                   'port': 'Port', 'proto': 'Proto',
                                   'bandwidth_mbps': 'Bandwidth (Mbps)',
                                   'bytes_total': 'Bytes Total'}))
        top_bw['Rate Basis'] = top_bw_basis.values
        result['top_bandwidth'] = top_bw
        result['max_bandwidth_mbps'] = round(float(has_bw['bandwidth_mbps'].max()), 3)
        result['avg_bandwidth_mbps'] = round(float(has_bw['bandwidth_mbps'].mean()), 3)
        result['p95_bandwidth_mbps'] = round(float(has_bw['bandwidth_mbps'].quantile(0.95)), 3)

    # Volume anomaly: bytes-per-connection ratio (potential exfiltration indicator)
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

    if not top_app_bytes.empty:
        app_labels = top_app_bytes['Source App'].tolist()[:10]
        app_values = [int(v) for v in top_app_bytes['Bytes Total'].tolist()[:10]]
    else:
        app_labels, app_values = [], []
    result['chart_spec'] = {
        'type': 'bar',
        'title': 'Top Apps by Data Volume',
        'title_key': 'rpt_chart_top_apps_by_data_volume',
        'x_label': t('rpt_app', default='Application', lang=lang),
        'x_label_key': 'rpt_chart_axis_app',
        'y_label': t('rpt_bytes_total', default='Bytes', lang=lang),
        'y_label_key': 'rpt_chart_axis_bytes',
        'data': {'labels': app_labels, 'values': app_values},
        'i18n': {'lang': get_language()},
    }

    return result
