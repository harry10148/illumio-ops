"""
src/report/parsers/validators.py
Unified DataFrame schema validation.

Ensures both CSV and API parsers produce DataFrames with the same required
columns and compatible dtypes before analysis modules consume them.
"""
from __future__ import annotations

from loguru import logger
import pandas as pd

# Required columns and their expected dtype categories
REQUIRED_COLUMNS: dict[str, str] = {
    'src_ip':           'object',
    'src_hostname':     'object',
    'src_managed':      'bool',
    'src_app':          'object',
    'src_env':          'object',
    'src_loc':          'object',
    'src_role':         'object',
    'dst_ip':           'object',
    'dst_hostname':     'object',
    'dst_managed':      'bool',
    'dst_app':          'object',
    'dst_env':          'object',
    'dst_loc':          'object',
    'dst_role':         'object',
    'port':             'numeric',
    'proto':            'object',
    'process_name':     'object',
    'user_name':        'object',
    'num_connections':  'numeric',
    'policy_decision':  'object',
    'bytes_total':      'numeric',
    'bandwidth_mbps':   'numeric',
    'data_source':      'object',
}

def validate(df: pd.DataFrame, raise_on_error: bool = False) -> list[str]:
    """
    Validate a Unified DataFrame against the required schema.

    Args:
        df:              DataFrame produced by CSVParser or APIParser.
        raise_on_error:  If True, raise ValueError on the first issue found.

    Returns:
        List of warning/error messages (empty → all OK).
    """
    issues = []

    if df is None or df.empty:
        msg = "DataFrame is empty or None."
        issues.append(msg)
        if raise_on_error:
            raise ValueError(msg)
        return issues

    # Drop duplicate columns before validation
    if df.columns.duplicated().any():
        logger.warning("[Validator] Duplicate columns detected — keeping first occurrence")
        df = df.loc[:, ~df.columns.duplicated()]

    for col, expected_kind in REQUIRED_COLUMNS.items():
        if col not in df.columns:
            issues.append(f"Missing required column: '{col}'")
        else:
            col_data = df[col]
            if isinstance(col_data, pd.DataFrame):
                issues.append(f"Column '{col}' has duplicates — keeping first")
                col_data = col_data.iloc[:, 0]
            dtype = col_data.dtype
            if expected_kind == 'numeric':
                if not pd.api.types.is_numeric_dtype(dtype):
                    issues.append(f"Column '{col}' expected numeric, got {dtype}")
            elif expected_kind == 'bool':
                if not (pd.api.types.is_bool_dtype(dtype) or
                        pd.api.types.is_object_dtype(dtype)):
                    issues.append(f"Column '{col}' expected bool-like, got {dtype}")
            # 'object' (string) columns are flexible — skip dtype check

    if issues:
        for msg in issues:
            logger.warning(f"[Validator] {msg}")
        if raise_on_error:
            raise ValueError(f"DataFrame validation failed: {issues[0]}")
    else:
        logger.debug(f"[Validator] DataFrame OK: {len(df)} rows, {len(df.columns)} cols")

    return issues

def coerce(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attempt to coerce a DataFrame to match the required schema.
    Adds missing columns with sensible defaults rather than raising errors.
    Safe to call after validate() flags warnings.
    """
    df = df.copy()

    # Drop duplicate columns (keep first)
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]

    defaults = {
        'src_ip': '', 'src_hostname': '', 'src_managed': False,
        'src_app': '', 'src_env': '', 'src_loc': '', 'src_role': '',
        'src_enforcement': '', 'src_os_type': '',
        'src_extra_labels': None,
        'dst_ip': '', 'dst_hostname': '', 'dst_managed': False,
        'dst_app': '', 'dst_env': '', 'dst_loc': '', 'dst_role': '',
        'dst_enforcement': '', 'dst_os_type': '', 'dst_fqdn': '',
        'dst_extra_labels': None,
        'port': 0, 'proto': '', 'process_name': '', 'user_name': '',
        'num_connections': 1, 'state': '', 'policy_decision': 'unknown',
        'first_detected': pd.NaT, 'last_detected': pd.NaT,
        'bytes_in': 0, 'bytes_out': 0, 'bytes_total': 0,
        'bandwidth_mbps': 0.0,
        'raw_dst_dbi': 0.0, 'raw_dst_dbo': 0.0,
        'raw_dst_tbi': 0.0, 'raw_dst_tbo': 0.0,
        'raw_ddms': 0.0, 'raw_tdms': 0.0,
        'data_source': 'unknown',
    }

    for col, default in defaults.items():
        if col not in df.columns:
            if default is None:
                df[col] = [{} for _ in range(len(df))]
            else:
                df[col] = default

    # Coerce numeric columns
    for col in ('port', 'num_connections', 'bytes_in', 'bytes_out', 'bytes_total'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    for col in ('bandwidth_mbps', 'raw_dst_dbi', 'raw_dst_dbo',
                'raw_dst_tbi', 'raw_dst_tbo', 'raw_ddms', 'raw_tdms'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    return df
