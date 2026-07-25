"""視窗增量（window delta）：從連續兩次 cache 觀測推導出真正落在規則視窗內的流量。

背景（2026-07-25 真機確認）：本 PCE 把 flow 聚合成日級 bucket，回傳的
``dst_b*`` / ``num_connections`` 是**整個 bucket 的累計值**，不會裁切到查詢
視窗——5 / 30 / 120 分鐘三種視窗查同一批 flow 拿到完全相同的數字。
因此 threshold_window=10 分鐘的規則等於拿數小時的累計量去比 10 分鐘的門檻。

Phase 1（analyzer 的 Bucket-basis guard）偵測到就整條規則不評估。
Phase 2（本模組）改成：ingest 每跑一次就把每筆 flow 當下的三個累計計數器
記進 ``pce_traffic_flow_obs``；規則評估時取「視窗起點之前最近的一筆觀測」當
基準，用 value(now) - value(baseline) 得到真正的視窗增量。推導不出來時
（沒有基準、基準太舊、計數器歸零）才退回 phase 1 的守門。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowObs

# SQLite 綁定參數上限（3.32 以前是 999）——IN (...) 一律分塊，避免在舊
# runtime 上炸掉。
_IN_CHUNK = 400

# 觀測寫入的分塊大小（沿用 ingestor 的 _CHUNK 量級）
_INSERT_CHUNK = 500


def _safe_int(value: Any, default: int = 0) -> int:
    """Best-effort ``int()``（analyzer._safe_int 的鏡射）：PCE 偶爾給出畸形
    數值欄位，一列壞資料不得讓 ingest 或規則評估整批失敗。"""
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def cumulative_metrics(flow: dict) -> tuple[int, int, int]:
    """PCE flow payload 上的三個累計計數器：``(bytes_out, bytes_in, conn_count)``。

    欄位優先序**必須**與 ``analyzer.calculate_volume_mb`` / ``calculate_mbps``
    的 Priority-2（總量）分支、以及規則引擎的連線數取值逐字一致：obs 存的是
    「當時的累計值」，之後要跟 analyzer 從同一組欄位算出的當下值相減。兩邊
    取不同欄位＝差值毫無意義（例如 obs 讀 dst_bi 而 analyzer 讀 dst_tbi，
    後者為 0 時會算出巨大的負增量）。

    ``or`` 鏈（而非 ``in`` 判斷）也是刻意比照 analyzer：值為 0 時往後
    fallback，行為必須完全相同。
    """
    bytes_out = _safe_int(
        flow.get("dst_tbo") or flow.get("tbo") or flow.get("dst_bo") or 0)
    bytes_in = _safe_int(
        flow.get("dst_tbi") or flow.get("tbi") or flow.get("dst_bi") or 0)
    conn = _safe_int(flow.get("num_connections") or flow.get("count", 1))
    return bytes_out, bytes_in, conn


@dataclass(frozen=True)
class FlowObservation:
    """某個 flow_hash 在 observed_at 當下的三個累計計數器。"""
    observed_at: datetime
    bytes_out: int
    bytes_in: int
    conn_count: int


def _as_utc(value: datetime) -> datetime:
    # SQLite 的 DateTime(timezone=True) 讀回來是 naive（tzinfo 被剝除），
    # 其值本身是 UTC wall-clock——補回 tzinfo 才能與 aware 的視窗時間相減。
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class FlowDeltaReader:
    """查詢每個 flow 在指定時間點之前最近一筆觀測（＝視窗增量的基準值）。"""

    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def baselines(
        self, flow_hashes: Sequence[str], at: datetime
    ) -> dict[str, FlowObservation]:
        """回傳 ``{flow_hash: 該 hash 在 at 之前（含）最近的一筆觀測}``。

        沒有任何觀測落在 at 之前的 flow 不會出現在結果裡——呼叫端必須據此
        退回守門，不可以拿更晚的觀測硬湊（那會算出視窗外的量）。
        """
        if not flow_hashes:
            return {}
        out: dict[str, FlowObservation] = {}
        uniq = list(dict.fromkeys(flow_hashes))
        with self._sf() as s:
            for i in range(0, len(uniq), _IN_CHUNK):
                chunk = uniq[i:i + _IN_CHUNK]
                # SQLite 專屬（本 cache 本來就只跑 SQLite：WAL pragma、
                # sqlite_insert upsert 皆然）：SELECT 清單裡出現 max()/min()
                # 時，同一列的裸欄位保證取自命中 max/min 的那一列。等價於
                # 每個 flow_hash 做一次 ORDER BY observed_at DESC LIMIT 1，
                # 但只掃一次索引 ix_obs_hash_observed。
                rows = s.execute(
                    select(
                        PceTrafficFlowObs.flow_hash,
                        func.max(PceTrafficFlowObs.observed_at),
                        PceTrafficFlowObs.bytes_out,
                        PceTrafficFlowObs.bytes_in,
                        PceTrafficFlowObs.conn_count,
                    )
                    .where(
                        PceTrafficFlowObs.flow_hash.in_(chunk),
                        PceTrafficFlowObs.observed_at <= at,
                    )
                    .group_by(PceTrafficFlowObs.flow_hash)
                ).all()
                for fh, observed_at, b_out, b_in, conn in rows:
                    if observed_at is None:
                        continue
                    out[fh] = FlowObservation(
                        observed_at=_as_utc(observed_at),
                        bytes_out=b_out or 0,
                        bytes_in=b_in or 0,
                        conn_count=conn or 0,
                    )
        return out


def build_observations(
    flows: Iterable[tuple[str, dict]], observed_at: datetime
) -> list[dict]:
    """把 ``(flow_hash, payload)`` 轉成 obs 插入列。"""
    rows = []
    for flow_hash, payload in flows:
        b_out, b_in, conn = cumulative_metrics(payload)
        rows.append({
            "flow_hash": flow_hash,
            "observed_at": observed_at,
            "bytes_out": b_out,
            "bytes_in": b_in,
            "conn_count": conn,
        })
    return rows


def insert_observations(session, rows: list[dict]) -> int:
    """把 obs 列寫入（呼叫端提供交易）。回傳寫入列數。"""
    if not rows:
        return 0
    for i in range(0, len(rows), _INSERT_CHUNK):
        session.execute(PceTrafficFlowObs.__table__.insert(), rows[i:i + _INSERT_CHUNK])
    return len(rows)


def prune_flow_observations(session_factory: sessionmaker, cutoff: datetime,
                            batch: int = 20000) -> int:
    """刪除 observed_at 早於 cutoff 的觀測，分批以免撐爆 WAL。

    刻意**不**套用 retention.py 的 archive 守門（`_effective_cutoff`）：
    archiver 匯出的是 pce_traffic_flows_raw / pce_events，obs 表從不進 archive
    ——扣住 obs 不刪保護不到任何 archive 內容，只會讓一張以小時計的工作表
    在 archiver 落後時無界成長（而「不可無界成長」是本表的硬需求）。obs 也
    不含 raw 列以外的 PCE 事實：raw 列保有最新累計值並照常被匯出，obs 只是
    推導視窗增量用的中間量。SIEM 守門同理不適用（沒有任何 dispatch/DLQ
    以 obs 為來源列）。
    """
    total = 0
    while True:
        with session_factory.begin() as s:
            ids = s.execute(
                select(PceTrafficFlowObs.id)
                .where(PceTrafficFlowObs.observed_at < cutoff)
                .limit(batch)
            ).scalars().all()
            if not ids:
                return total
            r = s.execute(
                delete(PceTrafficFlowObs).where(PceTrafficFlowObs.id.in_(ids)))
            total += r.rowcount
        if len(ids) < batch:
            return total
