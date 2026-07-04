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
from src.report.trend_store import snapshot_mismatch

_EPHEMERAL_PORT_MIN = 49152   # IANA 動態/私有埠起點；repo 無既有先例，於此定錨
_NOISE_PROTOS = ("ICMP", "ICMPv6")


def _is_noise_signature(sig: str) -> bool:
    """雜訊簽名（spec L2）：ICMP、port 0、ephemeral 高 port。

    簽名格式 src|dst|port|proto（flow_history.build_signatures）。
    解析失敗的畸形簽名視為雜訊（不進 drift 表）。
    """
    parts = sig.split("|", 3)
    if len(parts) != 4:
        return True
    port, proto = parts[2], parts[3]
    if proto in _NOISE_PROTOS:
        return True
    try:
        port_num = int(port)
    except ValueError:
        return True
    return port_num == 0 or port_num >= _EPHEMERAL_PORT_MIN


def _is_unlabeled_pair(sig: str) -> bool:
    """src 段與 dst 段皆為 (unlabeled) 的配對——new/disappeared 兩側對稱收合。"""
    parts = sig.split("|", 3)
    return len(parts) == 4 and parts[0] == UNLABELED and parts[1] == UNLABELED


def _sig_to_row(sig: str) -> dict:
    src, dst, port, proto = sig.split("|", 3)
    return {"Src App": src, "Dst App": dst, "Port": port, "Proto": proto}


def baseline_drift(
    df: pd.DataFrame,
    prev_signatures: set[str] | None,
    prev_generated_at: str | None,
    top_n: int = 20,
    *,
    prev_meta: dict | None = None,
    current_meta: dict | None = None,
) -> dict:
    if prev_signatures is None:
        return {"available": False}

    # 中繼資料一致性檢查——僅在兩期都有 _meta 時進行；舊 baseline 檔無 meta →
    # 完全略過（不附加 comparable/mismatch 鍵），行為與升級前逐字一致。
    mismatch: list[dict] = []
    if prev_meta and current_meta:
        mismatch = snapshot_mismatch(current_meta, {"_meta": prev_meta})

    # 視窗天數差過大 → 拒絕比較：不做差集（效能＋語意——視窗長度差會把整批
    # 上期連線誤判為 disappeared），僅回報不一致並照常在產生端存本期 baseline。
    if any(mis.get("field") == "window" for mis in mismatch):
        return {
            "available": True,
            "comparable": False,
            "mismatch": mismatch,
            "prev_generated_at": prev_generated_at,
        }

    # 過濾在 current 與 prev 兩集合對稱套用後才做差集：若只濾 current，
    # prev 獨有的雜訊簽名（例如舊 baseline 檔裡的 ICMP）會被誤判為 disappeared。
    current = {s for s in build_signatures(df) if not _is_noise_signature(s)}
    prev_filtered = {s for s in prev_signatures if not _is_noise_signature(s)}

    new_sigs_all = sorted(current - prev_filtered)
    gone_sigs_all = sorted(prev_filtered - current)

    # (unlabeled)→(unlabeled) 配對兩側對稱收合，另計數、不進表格母體
    new_unlabeled_collapsed = sum(1 for s in new_sigs_all if _is_unlabeled_pair(s))
    disappeared_unlabeled_collapsed = sum(1 for s in gone_sigs_all if _is_unlabeled_pair(s))
    new_sigs = [s for s in new_sigs_all if not _is_unlabeled_pair(s)]
    gone_sigs = [s for s in gone_sigs_all if not _is_unlabeled_pair(s)]

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

    result = {
        "available": True,
        "prev_generated_at": prev_generated_at,
        "new_count": len(new_sigs),
        "disappeared_count": len(gone_sigs),
        "new_unlabeled_collapsed": new_unlabeled_collapsed,
        "disappeared_unlabeled_collapsed": disappeared_unlabeled_collapsed,
        "new_pairs": pd.DataFrame(new_rows[:top_n]),
        "disappeared_pairs": pd.DataFrame(gone_rows[:top_n]),
    }
    # data_source/profile 不一致仍照常比較，但帶警語欄；僅在做過 meta 比較時
    # 附加 comparable/mismatch，舊檔路徑維持原形狀。
    if prev_meta and current_meta:
        result["comparable"] = True
        result["mismatch"] = mismatch
    return result
