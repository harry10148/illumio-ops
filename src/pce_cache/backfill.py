from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import orjson
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent, PceTrafficFlowRaw


@dataclass
class BackfillResult:
    total_rows: int
    inserted: int
    duplicates: int
    elapsed_seconds: float


class BackfillRunner:
    def __init__(self, api, session_factory: sessionmaker, rate_limit_per_minute: int = 400):
        self._api = api
        self._sf = session_factory

    def run_events(self, since: datetime, until: datetime) -> BackfillResult:
        """Fetch events via API and write to pce_events. Does NOT advance watermark."""
        t0 = time.monotonic()
        since_str = since.isoformat().replace("+00:00", "Z")
        events = self._api.get_events(since=since_str)
        inserted, dups = self._insert_events(events)
        return BackfillResult(
            total_rows=len(events),
            inserted=inserted,
            duplicates=dups,
            elapsed_seconds=time.monotonic() - t0,
        )

    def run_traffic(self, since: datetime, until: datetime, filters: dict | None = None) -> BackfillResult:
        """Fetch traffic via API and write to pce_traffic_flows_raw. Does NOT advance watermark."""
        t0 = time.monotonic()
        since_str = since.isoformat().replace("+00:00", "Z")
        until_str = until.isoformat().replace("+00:00", "Z")
        flows = self._api.fetch_traffic_for_report(start_time_str=since_str, end_time_str=until_str)
        inserted, dups = self._insert_traffic(flows or [])
        return BackfillResult(
            total_rows=len(flows or []),
            inserted=inserted,
            duplicates=dups,
            elapsed_seconds=time.monotonic() - t0,
        )

    def _insert_events(self, events: list[dict]) -> tuple[int, int]:
        inserted = dups = 0
        now = datetime.now(timezone.utc)
        for ev in events:
            try:
                with self._sf.begin() as s:
                    ts_raw = ev.get("timestamp", "")
                    ts = _parse_iso(ts_raw) if ts_raw else now
                    s.add(PceEvent(
                        pce_href=ev.get("href", ""),
                        pce_event_id=ev.get("uuid", ev.get("href", ""))[-64:],
                        timestamp=ts,
                        event_type=ev.get("event_type", "unknown"),
                        severity=ev.get("severity", "info"),
                        status=ev.get("status", "success"),
                        pce_fqdn=ev.get("pce_fqdn", ""),
                        raw_json=orjson.dumps(ev).decode("utf-8"),
                        ingested_at=now,
                    ))
                inserted += 1
            except IntegrityError:
                dups += 1
        return inserted, dups

    def _insert_traffic(self, flows: list[dict]) -> tuple[int, int]:
        inserted = dups = 0
        now = datetime.now(timezone.utc)
        for fl in flows:
            try:
                with self._sf.begin() as s:
                    ts_range = fl.get("timestamp_range") or {}
                    last_detected_raw = fl.get("last_detected") or ts_range.get("last_detected", "")
                    last_detected = _parse_iso(last_detected_raw) if last_detected_raw else now
                    first_detected_raw = fl.get("first_detected") or ts_range.get("first_detected", "")
                    first_detected = _parse_iso(first_detected_raw) if first_detected_raw else now
                    src_wl = (fl.get("src") or {}).get("workload") or {}
                    dst_wl = (fl.get("dst") or {}).get("workload") or {}
                    svc = fl.get("service") or {}
                    src_ip = fl.get("src_ip", "") or (fl.get("src") or {}).get("ip", "")
                    dst_ip = fl.get("dst_ip", "") or (fl.get("dst") or {}).get("ip", "")
                    port = svc.get("port") if svc else fl.get("port", 0)
                    protocol = _proto_to_str(svc.get("proto") if svc else fl.get("protocol", "tcp"))
                    action = fl.get("action") or fl.get("policy_decision", "unknown")
                    flow_count = fl.get("flow_count") or fl.get("num_connections", 1)
                    s.add(PceTrafficFlowRaw(
                        flow_hash=_backfill_flow_hash(fl),
                        src_ip=src_ip,
                        src_workload=src_wl.get("href") or fl.get("src_workload"),
                        dst_ip=dst_ip,
                        dst_workload=dst_wl.get("href") or fl.get("dst_workload"),
                        port=port or 0,
                        protocol=protocol,
                        action=action,
                        flow_count=flow_count,
                        bytes_in=fl.get("bytes_in") or fl.get("dst_bi", 0),
                        bytes_out=fl.get("bytes_out") or fl.get("dst_bo", 0),
                        first_detected=first_detected,
                        last_detected=last_detected,
                        raw_json=orjson.dumps(fl).decode("utf-8"),
                        ingested_at=now,
                    ))
                inserted += 1
            except IntegrityError:
                dups += 1
        return inserted, dups


def _backfill_flow_hash(flow: dict) -> str:
    """Compute flow_hash from available fields (handles both flat and nested PCE API shapes)."""
    src_wl = (flow.get("src") or {}).get("workload") or {}
    dst_wl = (flow.get("dst") or {}).get("workload") or {}
    svc = flow.get("service") or {}
    ts_range = flow.get("timestamp_range") or {}
    first_detected = flow.get("first_detected") or ts_range.get("first_detected", "")
    key = "|".join([
        flow.get("src_ip", "") or (flow.get("src") or {}).get("ip", "") or src_wl.get("href", ""),
        flow.get("dst_ip", "") or (flow.get("dst") or {}).get("ip", "") or dst_wl.get("href", ""),
        str(svc.get("port", "") or flow.get("port", "")),
        str(svc.get("proto", "") or flow.get("protocol", "")),
        first_detected,
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _proto_to_str(proto) -> str:
    """Convert protocol number or string to string label."""
    if proto is None:
        return "tcp"
    if isinstance(proto, str):
        return proto
    # IANA protocol numbers: 6=TCP, 17=UDP, 1=ICMP
    _MAP = {6: "tcp", 17: "udp", 1: "icmp"}
    return _MAP.get(int(proto), str(proto))


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
