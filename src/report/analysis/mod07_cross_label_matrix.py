"""Module 7: Cross-Label Flow Matrix."""
from __future__ import annotations
import pandas as pd

LABEL_KEYS = ('env', 'app', 'role', 'loc')


def cross_label_flow_matrix(df: pd.DataFrame, top_n: int = 20) -> dict:
    """
    For each label key produce a value×value flow matrix showing same-value vs
    cross-value flows. This is the label-agnostic substitute for 'Cross-Env DB Access'.
    """
    if df.empty:
        return {'error': 'No data'}

    matrices = {}
    for key in LABEL_KEYS:
        src_col = f'src_{key}'
        dst_col = f'dst_{key}'
        if src_col not in df.columns or dst_col not in df.columns:
            continue

        sub = df[(df[src_col] != '') & (df[dst_col] != '')].copy()
        if sub.empty:
            matrices[key] = {'note': f'No label data for key: {key}'}
            continue

        sub['is_cross'] = sub[src_col] != sub[dst_col]
        cross_count = int(sub['is_cross'].sum())
        same_count = len(sub) - cross_count

        # Value × value matrix (connections). Cast to Int64 so cells render "5" not "5.0".
        matrix = (sub.groupby([src_col, dst_col])['num_connections']
                  .sum().unstack(fill_value=0).astype('Int64'))
        # Keep top_n src and dst values
        top_src = sub.groupby(src_col)['num_connections'].sum().nlargest(top_n).index
        top_dst = sub.groupby(dst_col)['num_connections'].sum().nlargest(top_n).index
        matrix = matrix.loc[
            matrix.index.isin(top_src),
            matrix.columns.isin(top_dst)
        ]

        # Top cross-value pairs
        cross_sub = sub[sub['is_cross']]
        top_cross = (cross_sub.groupby([src_col, dst_col])['num_connections']
                     .sum().reset_index().nlargest(top_n, 'num_connections')
                     .rename(columns={src_col: f'Src {key.capitalize()}',
                                      dst_col: f'Dst {key.capitalize()}',
                                      'num_connections': 'Connections'}))
        if 'Connections' in top_cross.columns:
            top_cross['Connections'] = top_cross['Connections'].astype('Int64')

        matrices[key] = {
            'same_value_flows': same_count,
            'cross_value_flows': cross_count,
            'matrix': matrix.reset_index(),
            'top_cross_pairs': top_cross,
        }

    return {'matrices': matrices}
