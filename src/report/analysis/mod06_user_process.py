"""Module 6: User & Process Activity Analysis."""
from __future__ import annotations
import pandas as pd

def user_process_analysis(df: pd.DataFrame, top_n: int = 20) -> dict:
    """
    Analyse flows that have user_name or process_name data.
    Returns 'no data' message when PCE has no process/user collection.
    """
    if df.empty:
        return {'error': 'No data'}

    has_user = df[df['user_name'].str.strip() != ''].copy()
    has_proc = df[df['process_name'].str.strip() != ''].copy()

    user_available = not has_user.empty
    proc_available = not has_proc.empty

    result: dict = {
        'user_data_available': user_available,
        'process_data_available': proc_available,
        'note': None,
    }

    if not user_available and not proc_available:
        result['note'] = 'User and process data not available — PCE process visibility not enabled or data source is CSV without these columns.'
        return result

    # Top users by unique destinations
    if user_available:
        top_users = (has_user.groupby('user_name').agg(
            unique_dst=('dst_ip', 'nunique'),
            total_connections=('num_connections', 'sum'),
            unique_ports=('port', 'nunique'),
        ).reset_index().nlargest(top_n, 'total_connections')
        .rename(columns={'user_name': 'User Name', 'unique_dst': 'Unique Destinations',
                         'total_connections': 'Connections', 'unique_ports': 'Unique Ports'}))
        result['top_users'] = top_users

        # User → dst_app matrix (top users × top dst apps)
        pivot_data = (has_user.groupby(['user_name', 'dst_app'])['num_connections']
                      .sum().unstack(fill_value=0))
        # Keep top_n users and top_n dst_apps
        top_user_list = has_user.groupby('user_name')['num_connections'].sum().nlargest(top_n).index
        top_app_list = has_user.groupby('dst_app')['num_connections'].sum().nlargest(top_n).index
        pivot_data = pivot_data.loc[
            pivot_data.index.isin(top_user_list),
            pivot_data.columns.isin(top_app_list)
        ]
        # unstack(fill_value=0) preserves int if the source is int, but be explicit
        # so reports don't accidentally render "5.0 connections".
        pivot_data = pivot_data.astype('Int64')
        result['user_dst_matrix'] = pivot_data.reset_index()

    # Top processes
    if proc_available:
        top_procs = (has_proc.groupby('process_name').agg(
            unique_dst=('dst_ip', 'nunique'),
            total_connections=('num_connections', 'sum'),
        ).reset_index().nlargest(top_n, 'total_connections')
        .rename(columns={'process_name': 'Process', 'unique_dst': 'Unique Destinations',
                         'total_connections': 'Connections'}))
        result['top_processes'] = top_procs

    return result
