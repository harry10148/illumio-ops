from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    String, Integer, BigInteger, Text, DateTime, Boolean,
    Index, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PceEvent(Base):
    __tablename__ = "pce_events"

    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    pce_href:      Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    pce_event_id:  Mapped[str]      = mapped_column(String(64), index=True)
    timestamp:     Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type:    Mapped[str]      = mapped_column(String(128), index=True)
    severity:      Mapped[str]      = mapped_column(String(32), index=True)
    status:        Mapped[str]      = mapped_column(String(32))
    pce_fqdn:      Mapped[str]      = mapped_column(String(255))
    raw_json:      Mapped[str]      = mapped_column(Text)
    ingested_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        Index("ix_events_ts_type", "timestamp", "event_type"),
    )


class PceTrafficFlowRaw(Base):
    __tablename__ = "pce_traffic_flows_raw"

    id:             Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    flow_hash:      Mapped[str]      = mapped_column(String(64), unique=True, index=True)
    # first_detected / src_ip / dst_ip / port / action are intentionally NOT
    # indexed: no query filters/sorts by them (reports + top10 read by
    # last_detected range then filter the rest in Python; the aggregator does a
    # full-table GROUP BY). Each index only added write amplification per insert.
    # Add purpose-built (composite) indexes if filters are ever pushed to SQL.
    first_detected: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_detected:  Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    src_ip:         Mapped[str]      = mapped_column(String(45))
    src_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    dst_ip:         Mapped[str]      = mapped_column(String(45))
    dst_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    port:           Mapped[int]      = mapped_column(Integer)
    protocol:       Mapped[str]      = mapped_column(String(8))
    action:         Mapped[str]      = mapped_column(String(32))
    flow_count:     Mapped[int]      = mapped_column(Integer, default=1)
    bytes_in:       Mapped[int]      = mapped_column(BigInteger, default=0)
    bytes_out:      Mapped[int]      = mapped_column(BigInteger, default=0)
    raw_json:       Mapped[str]      = mapped_column(Text)
    ingested_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # ── Report-ready flattened record (Tier-2a) ──────────────────────────────
    # The unified-schema dict (api_parser flatten output) computed ONCE at
    # ingest and stored verbatim as compact JSON, so reports skip the expensive
    # per-row re-flatten (label extraction + bandwidth/volume math). Nullable:
    # rows ingested before this shipped fall back to parsing raw_json. raw_json
    # stays the source of truth.
    report_json:    Mapped[str | None] = mapped_column(Text, nullable=True)


class PceTrafficFlowObs(Base):
    """每次 traffic ingest 對每筆 flow 記下的「當下累計計數器」觀測。

    存在理由：本 PCE 把 flow 聚合成日級 bucket，回傳的 byte/連線數是整個
    bucket 的累計值、不裁切到查詢視窗（見 analyzer 的 Bucket-basis guard）。
    pce_traffic_flows_raw 每個 flow_hash 只留一列、volatile 欄位取 MAX，
    因此只看得到「最新的累計值」，沒有前一次觀測可相減。本表保留連續觀測，
    讓規則引擎能算出 value(t2) - value(t1)＝真正落在視窗內的量。

    刻意不放 raw_json/report_json：本表只是推導視窗增量的工作資料，PCE 的
    權威內容仍在 pce_traffic_flows_raw（也是 archive 匯出的對象）。一列約
    50 bytes，穩態列數 ≈ 活躍 flow 數 × (保留時數 × 每小時 ingest 次數)，
    由 flow_obs_retention_hours 依 observed_at 修剪（見 retention.py 與
    flow_deltas.prune_flow_observations）——不會無界成長。

    刻意不對 pce_traffic_flows_raw.id 建 FK：兩者生命週期不同（raw 以天計、
    obs 以小時計），FK 會讓 raw 的 retention 批次刪除多付 cascade 成本，而
    孤兒 obs 本來就會自己到期。以 flow_hash（而非 row id）為鍵也讓 ingest
    端不必先拿到 upsert 後的 id。
    """
    __tablename__ = "pce_traffic_flow_obs"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    flow_hash:   Mapped[str]      = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 三個計數器分別存：規則型別對應的度量不同（bandwidth/volume 用
    # bytes_out+bytes_in，traffic count 用 conn_count），合併儲存就無法
    # 逐度量求差。欄位取值與 analyzer 的 fallback 鏈一致，見
    # flow_deltas.cumulative_metrics。
    bytes_out:   Mapped[int]      = mapped_column(BigInteger, default=0)
    bytes_in:    Mapped[int]      = mapped_column(BigInteger, default=0)
    conn_count:  Mapped[int]      = mapped_column(Integer, default=0)

    __table_args__ = (
        # 查基準值：WHERE flow_hash IN (...) AND observed_at <= :at
        # GROUP BY flow_hash（見 FlowDeltaReader.baselines）
        Index("ix_obs_hash_observed", "flow_hash", "observed_at"),
        # 修剪：DELETE WHERE observed_at < cutoff
        Index("ix_obs_observed_at", "observed_at"),
    )


class PceTrafficFlowAgg(Base):
    __tablename__ = "pce_traffic_flows_agg"

    id:             Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    bucket_day:     Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    src_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    dst_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    port:           Mapped[int]      = mapped_column(Integer)
    protocol:       Mapped[str]      = mapped_column(String(8))
    action:         Mapped[str]      = mapped_column(String(32), index=True)
    flow_count:     Mapped[int]      = mapped_column(Integer, default=0)
    bytes_total:    Mapped[int]      = mapped_column(BigInteger, default=0)

    __table_args__ = (
        Index(
            "ix_agg_unique",
            "bucket_day", "src_workload", "dst_workload", "port", "protocol", "action",
            unique=True,
        ),
    )


class IngestionCursor(Base):
    """Per-consumer cursor on `ingested_at` for cache subscribers.

    Separate from IngestionWatermark (which tracks the ingestor's own
    position relative to PCE) — this table tracks downstream consumers
    of the cache itself. Multiple consumers (analyzer, future alert
    engines, exporters) can hold independent cursors.
    """
    __tablename__ = "ingestion_cursors"

    consumer:         Mapped[str]           = mapped_column(String(64), primary_key=True)
    source_table:     Mapped[str]           = mapped_column(String(32), primary_key=True)  # "pce_events"|"pce_traffic_flows_raw"
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_row_id:      Mapped[int | None]    = mapped_column(BigInteger, nullable=True)
    updated_at:       Mapped[datetime]      = mapped_column(DateTime(timezone=True))


class IngestionWatermark(Base):
    __tablename__ = "ingestion_watermarks"

    source:         Mapped[str]      = mapped_column(String(32), primary_key=True)
    last_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_href:      Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status:    Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error:     Mapped[str | None] = mapped_column(Text, nullable=True)


class SiemDispatch(Base):
    __tablename__ = "siem_dispatch"

    id:              Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_table:    Mapped[str]      = mapped_column(String(32), index=True)
    source_id:       Mapped[int]      = mapped_column(BigInteger)
    destination:     Mapped[str]      = mapped_column(String(64), index=True)
    status:          Mapped[str]      = mapped_column(String(16), index=True)
    retries:         Mapped[int]      = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_error:      Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at:       Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at:         Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dispatch_pending", "status", "next_attempt_at"),
        Index("ix_dispatch_queued_at", "queued_at"),
        Index("ix_dispatch_sent_at", "sent_at"),
        # Backs the enqueue_new_records anti-join (NOT EXISTS on source rows).
        # The anti-join now also filters on destination, which this index does
        # not cover — SQLite seeks by (source_table, source_id) and checks the
        # destination predicate on the (few) matching dispatch rows per source.
        Index("ix_dispatch_source", "source_table", "source_id"),
    )


class DeadLetter(Base):
    __tablename__ = "dead_letter"

    id:              Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_table:    Mapped[str]      = mapped_column(String(32))
    source_id:       Mapped[int]      = mapped_column(BigInteger)
    destination:     Mapped[str]      = mapped_column(String(64), index=True)
    retries:         Mapped[int]      = mapped_column(Integer)
    last_error:      Mapped[str]      = mapped_column(Text)
    payload_preview: Mapped[str]      = mapped_column(String(512))
    quarantined_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
