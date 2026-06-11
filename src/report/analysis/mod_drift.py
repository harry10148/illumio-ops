# src/report/analysis/mod_drift.py
"""Baseline drift — app-to-app connection pairs new/disappeared vs previous run.

PURE function: signature comparison only, no I/O. The previous-period
signature set is loaded by report_generator.export() via flow_history and
passed in. The App Group Summary concept ("has the connection baseline
changed?") applied at whole-estate level.
"""
from __future__ import annotations

import pandas as pd

from src.report.flow_history import UNLABELED, build_signatures


def _sig_to_row(sig: str) -> dict:
    src, dst, port, proto = sig.split("|", 3)
    return {"Src App": src, "Dst App": dst, "Port": port, "Proto": proto}


def baseline_drift(
    df: pd.DataFrame,
    prev_signatures: set[str] | None,
    prev_generated_at: str | None,
    top_n: int = 20,
) -> dict:
    if prev_signatures is None:
        return {"available": False}

    current = build_signatures(df)
    new_sigs = sorted(current - prev_signatures)
    gone_sigs = sorted(prev_signatures - current)

    # 新連線帶上本期連線數，按量排序讓分析師先看大的
    conn_by_sig: dict[str, int] = {}
    if df is not None and not df.empty:
        work = df.copy()
        work["_sig"] = (
            work["src_app"].fillna("").astype(str).replace("", UNLABELED) + "|"
            + work["dst_app"].fillna("").astype(str).replace("", UNLABELED) + "|"
            + work["port"].fillna(0).astype(int).astype(str) + "|"
            + work["proto"].fillna("").astype(str)
        )
        conn_by_sig = work.groupby("_sig")["num_connections"].sum().to_dict()

    new_rows = [dict(_sig_to_row(s), Connections=int(conn_by_sig.get(s, 0))) for s in new_sigs]
    new_rows.sort(key=lambda r: r["Connections"], reverse=True)
    gone_rows = [_sig_to_row(s) for s in gone_sigs]

    return {
        "available": True,
        "prev_generated_at": prev_generated_at,
        "new_count": len(new_sigs),
        "disappeared_count": len(gone_sigs),
        "new_pairs": pd.DataFrame(new_rows[:top_n]),
        "disappeared_pairs": pd.DataFrame(gone_rows[:top_n]),
    }
