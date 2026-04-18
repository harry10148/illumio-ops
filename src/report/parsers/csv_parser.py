"""
src/report/parsers/csv_parser.py
CSV (PCE UI Export) → Unified DataFrame

Reads a CSV exported from the Illumio PCE UI and converts it into the
Unified DataFrame schema used by all 12 analysis modules.
"""
from __future__ import annotations

import os
import re
from loguru import logger
import pandas as pd

# ─── PCE CSV column mapping ─────────────────────────────────────────────────

_COLUMN_MAP = {
    # Source endpoint
    "Source IP":                "src_ip",
    "Source Hostname":          "src_hostname",
    "Source Name":              "src_hostname",
    "Source Application":       "src_app",
    "Source Environment":       "src_env",
    "Source Location":          "src_loc",
    "Source Role":              "src_role",
    "Source Managed":           "src_managed",
    # Destination endpoint
    "Destination IP":           "dst_ip",
    "Destination Hostname":     "dst_hostname",
    "Destination Name":         "dst_hostname",
    "Destination Application":  "dst_app",
    "Destination Environment":  "dst_env",
    "Destination Location":     "dst_loc",
    "Destination Role":         "dst_role",
    "Destination FQDN":         "dst_fqdn",
    "Destination Managed":      "dst_managed",
    # Connection info
    "Port":                     "port",
    "Protocol":                 "proto",
    "Process":                  "process_name",
    "User":                     "user_name",
    "Connections":              "num_connections",
    "State":                    "state",
    "Policy Decision":          "policy_decision",
    # Timestamps
    "First Detected":           "first_detected",
    "Last Detected":            "last_detected",
    # Bytes
    "Bytes In":                 "bytes_in_raw",
    "Bytes Out":                "bytes_out_raw",
    "Bytes":                    "bytes_total_raw",
}

_PROTO_MAP = {
    "TCP": "TCP", "UDP": "UDP", "ICMP": "ICMP",
    "6": "TCP", "17": "UDP", "1": "ICMP",
}

_POLICY_DECISION_MAP = {
    "allowed": "allowed", "Allowed": "allowed",
    "blocked": "blocked", "Blocked": "blocked",
    "potentially_blocked": "potentially_blocked",
    "Potentially Blocked": "potentially_blocked",
    "unknown": "unknown", "Unknown": "unknown",
}

# ─── Byte-string → int helper ────────────────────────────────────────────────

_UNIT_FACTORS = {
    'b': 1,
    'kb': 1_024,
    'mb': 1_024 ** 2,
    'gb': 1_024 ** 3,
    'tb': 1_024 ** 4,
}

def _parse_bytes_string(s) -> int:
    """Parse a PCE byte-string ('1.2 MB', '3.5 GB') to integer bytes."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return 0
    s = str(s).strip()
    if not s or s in ('-', 'N/A', 'n/a', ''):
        return 0
    m = re.match(r'([\d,.]+)\s*([A-Za-z]*)', s)
    if not m:
        return 0
    try:
        num = float(m.group(1).replace(',', ''))
    except ValueError:
        return 0
    unit = m.group(2).lower() if m.group(2) else 'b'
    factor = _UNIT_FACTORS.get(unit, 1)
    return int(num * factor)

# ─── Boolean normaliser ───────────────────────────────────────────────────────

def _parse_bool(val, default=None) -> bool | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    s = str(val).strip().lower()
    if s in ('true', 'yes', '1', 'managed'):
        return True
    if s in ('false', 'no', '0', 'unmanaged'):
        return False
    return default

# ─── CSV Parser ──────────────────────────────────────────────────────────────

class CSVParser:
    """
    Parse a PCE UI traffic export CSV into a Unified DataFrame.

    Usage:
        parser = CSVParser()
        df = parser.parse('/path/to/traffic.csv')
    """

    # Guaranteed label keys — must always be present (can be empty string)
    LABEL_KEYS = ('app', 'env', 'loc', 'role')

    def __init__(self):
        self._col_map = _COLUMN_MAP
        self._proto_map = _PROTO_MAP
        self._pd_map = _POLICY_DECISION_MAP

    # ── public API ───────────────────────────────────────────────────────────

    def parse(self, csv_path: str) -> pd.DataFrame:
        """Read CSV file and return Unified DataFrame."""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        logger.info(f"[CSVParser] Reading {csv_path}")
        raw = pd.read_csv(csv_path, dtype=str)
        logger.info(f"[CSVParser] {len(raw)} rows, {len(raw.columns)} columns")

        df = self._rename_columns(raw)
        df = self._apply_types(df)
        df['data_source'] = 'csv'

        logger.info(f"[CSVParser] Parsed {len(df)} flows")
        return df

    # ── private ──────────────────────────────────────────────────────────────

    def _rename_columns(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Map raw CSV headers → unified schema names.  Extra label columns
        become src_extra_labels / dst_extra_labels dicts per row."""
        rename = {}
        seen_targets: set = set()
        for col in raw.columns:
            target = self._col_map.get(col)
            if target and target not in seen_targets:
                rename[col] = target
                seen_targets.add(target)
            elif target and target in seen_targets:
                logger.debug(f"[CSVParser] Skipping duplicate mapping: '{col}' → '{target}'")
        df = raw.rename(columns=rename)

        # Drop any remaining duplicate columns (keep first)
        df = df.loc[:, ~df.columns.duplicated()]

        mapped = len(rename)
        unmapped = [c for c in raw.columns if c not in rename]
        logger.info(f"[CSVParser] Mapped {mapped}/{len(raw.columns)} columns; "
                     f"unmapped: {unmapped[:10]}{'...' if len(unmapped) > 10 else ''}")

        # Detect extra label columns not in the standard mapping
        src_extras, dst_extras = self._detect_extra_labels(raw.columns)
        if src_extras or dst_extras:
            df['src_extra_labels'] = df.apply(
                lambda r: {k: (r.get(k) or '') for k in src_extras if k in r}, axis=1)
            df['dst_extra_labels'] = df.apply(
                lambda r: {k: (r.get(k) or '') for k in dst_extras if k in r}, axis=1)
        else:
            df['src_extra_labels'] = [{} for _ in range(len(df))]
            df['dst_extra_labels'] = [{} for _ in range(len(df))]

        return df

    def _detect_extra_labels(self, columns):
        """Return column names that look like extra src/dst label columns."""
        known = set(self._col_map.values())
        src_extra, dst_extra = [], []
        for col in columns:
            lc = col.lower()
            if col in self._col_map:
                continue
            if lc.startswith('source ') and col not in known:
                src_extra.append(col)
            elif lc.startswith('destination ') and col not in known:
                dst_extra.append(col)
        return src_extra, dst_extra

    def _apply_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """Parse bytes, booleans, timestamps, normalise strings."""
        # Guarantee the 8 label columns exist (empty string if absent)
        for side in ('src', 'dst'):
            for key in self.LABEL_KEYS:
                col = f'{side}_{key}'
                if col not in df.columns:
                    df[col] = ''
                else:
                    df[col] = df[col].fillna('')

        # Hostnames / IPs
        for col in ('src_ip', 'src_hostname', 'dst_ip', 'dst_hostname', 'dst_fqdn'):
            if col not in df.columns:
                df[col] = ''
            else:
                df[col] = df[col].fillna('')

        # Managed flags
        for col in ('src_managed', 'dst_managed'):
            if col in df.columns:
                df[col] = df[col].apply(lambda v: _parse_bool(v, default=False))
            else:
                df[col] = False

        # Port
        if 'port' in df.columns:
            df['port'] = pd.to_numeric(df['port'], errors='coerce').fillna(0).astype(int)
        else:
            df['port'] = 0

        # Protocol normalise
        if 'proto' in df.columns:
            df['proto'] = df['proto'].fillna('').apply(
                lambda v: self._proto_map.get(str(v).strip(), str(v).strip().upper()))
        else:
            df['proto'] = ''

        # Process / User
        for col in ('process_name', 'user_name'):
            if col not in df.columns:
                df[col] = ''
            else:
                df[col] = df[col].fillna('')

        # Connections count
        if 'num_connections' in df.columns:
            df['num_connections'] = pd.to_numeric(df['num_connections'], errors='coerce').fillna(1).astype(int)
        else:
            df['num_connections'] = 1

        # Policy decision
        if 'policy_decision' in df.columns:
            df['policy_decision'] = df['policy_decision'].fillna('unknown').apply(
                lambda v: self._pd_map.get(str(v).strip(), str(v).strip().lower()))
        else:
            df['policy_decision'] = 'unknown'

        # Timestamps
        for col in ('first_detected', 'last_detected'):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
            else:
                df[col] = pd.NaT

        # Bytes — parse string → int
        for raw_col, target_col in (
            ('bytes_in_raw', 'bytes_in'),
            ('bytes_out_raw', 'bytes_out'),
            ('bytes_total_raw', 'bytes_total_csv'),
        ):
            if raw_col in df.columns:
                df[target_col] = df[raw_col].apply(_parse_bytes_string)
            else:
                df[target_col] = 0

        # Compute bytes_total if not directly available
        if 'bytes_total' not in df.columns:
            if 'bytes_total_csv' in df.columns and df['bytes_total_csv'].sum() > 0:
                df['bytes_total'] = df['bytes_total_csv']
            else:
                df['bytes_total'] = df.get('bytes_in', 0) + df.get('bytes_out', 0)

        # Bandwidth estimate from CSV (no ddms available — use timestamp diff)
        df['bandwidth_mbps'] = self._estimate_bandwidth(df)

        # Placeholder raw API fields (not available in CSV)
        for col in ('raw_dst_dbi', 'raw_dst_dbo', 'raw_dst_tbi', 'raw_dst_tbo',
                    'raw_ddms', 'raw_tdms'):
            df[col] = 0.0

        # Enforcement mode / OS type (not always in CSV)
        for col in ('src_enforcement', 'dst_enforcement', 'src_os_type', 'dst_os_type'):
            if col not in df.columns:
                df[col] = ''
            else:
                df[col] = df[col].fillna('')

        # State
        if 'state' not in df.columns:
            df['state'] = ''
        else:
            df['state'] = df['state'].fillna('')

        return df

    def _estimate_bandwidth(self, df: pd.DataFrame) -> pd.Series:
        """Estimate bandwidth from timestamp delta when ddms is not available."""
        if 'first_detected' not in df.columns or 'last_detected' not in df.columns:
            return pd.Series([0.0] * len(df))
        delta_sec = (df['last_detected'] - df['first_detected']).dt.total_seconds().fillna(0)
        # Clamp minimum to 1 second to avoid division by zero
        delta_sec = delta_sec.clip(lower=1)
        bytes_total = df.get('bytes_total', pd.Series([0] * len(df)))
        return (bytes_total * 8.0) / delta_sec / 1_000_000.0  # → Mbps
