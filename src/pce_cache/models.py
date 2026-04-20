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

    id:             Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    flow_hash:      Mapped[str]      = mapped_column(String(64), unique=True, index=True)
    first_detected: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_detected:  Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    src_ip:         Mapped[str]      = mapped_column(String(45), index=True)
    src_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    dst_ip:         Mapped[str]      = mapped_column(String(45), index=True)
    dst_workload:   Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    port:           Mapped[int]      = mapped_column(Integer, index=True)
    protocol:       Mapped[str]      = mapped_column(String(8))
    action:         Mapped[str]      = mapped_column(String(32), index=True)
    flow_count:     Mapped[int]      = mapped_column(Integer, default=1)
    bytes_in:       Mapped[int]      = mapped_column(BigInteger, default=0)
    bytes_out:      Mapped[int]      = mapped_column(BigInteger, default=0)
    raw_json:       Mapped[str]      = mapped_column(Text)
    ingested_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PceTrafficFlowAgg(Base):
    __tablename__ = "pce_traffic_flows_agg"

    id:             Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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

    id:              Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
    )


class DeadLetter(Base):
    __tablename__ = "dead_letter"

    id:              Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_table:    Mapped[str]      = mapped_column(String(32))
    source_id:       Mapped[int]      = mapped_column(BigInteger)
    destination:     Mapped[str]      = mapped_column(String(64), index=True)
    retries:         Mapped[int]      = mapped_column(Integer)
    last_error:      Mapped[str]      = mapped_column(Text)
    payload_preview: Mapped[str]      = mapped_column(String(512))
    quarantined_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
