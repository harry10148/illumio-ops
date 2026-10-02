"""Row positions of the flows that touch each app(env) key.

mod13/mod14 used to select a key's flows with a full-frame boolean mask
(`(src_key == key) | (dst_key == key)`) inside a loop over every key: rows ×
keys work. At ~4,000 app|env keys that was 50 s (mod13) and 73 s (mod14) at
100k flows and several minutes at 500k (measured 2026-10). Grouping once gives
the same rows in the same order, so callers get an identical sub-frame.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_EMPTY = np.empty(0, dtype=np.intp)


def rows_by_key(frame: pd.DataFrame, src_col: str = "src_key",
                dst_col: str = "dst_key") -> dict[str, np.ndarray]:
    """{key: sorted positions of rows whose src or dst key is *key*}.

    `frame.iloc[positions]` equals `frame[(frame[src_col] == key) |
    (frame[dst_col] == key)]`, including row order and index.
    """
    src = frame.groupby(src_col, sort=False).indices if len(frame) else {}
    dst = frame.groupby(dst_col, sort=False).indices if len(frame) else {}
    out: dict[str, np.ndarray] = {}
    for key in set(src) | set(dst):
        a = src.get(key, _EMPTY)
        b = dst.get(key, _EMPTY)
        out[key] = np.union1d(a, b) if len(a) and len(b) else np.sort(a if len(a) else b)
    return out
