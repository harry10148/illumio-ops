from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw, SiemDispatch
from src.pce_cache.traffic_filter import TrafficFilter, TrafficSampler
from src.pce_cache.watermark import WatermarkStore


class TrafficIngestor:
    SOURCE = "traffic"

    def __init__(
        self,
        api,
        session_factory: sessionmaker,
        watermark: WatermarkStore,
        traffic_filter: Optional[TrafficFilter] = None,
        sample_ratio_allowed: int = 1,
        max_results: int = 200000,
        siem_destinations: Optional[list[str]] = None,
    ):
        self._api = api
        self._sf = session_factory
        self._wm = watermark
        self._filter = traffic_filter or TrafficFilter()
        self._sampler = TrafficSampler(ratio_allowed=sample_ratio_allowed)
        self._max_results = max_results
        self._siem_dests = list(siem_destinations or [])

    def run_once(self) -> int:
        since = self._since_cursor()
        try:
            flows = self._api.get_traffic_flows_async(
                max_results=self._max_results,
                rate_limit=True,
                since=since,
            )
        except Exception as exc:
            logger.exception("Traffic ingest failed: {}", exc)
            self._wm.record_error(self.SOURCE, str(exc))
            return 0

        inserted = 0
        watermark_advanced = False
        try:
            inserted = self._insert_batch(flows)
            if flows:
                last = max(_ts(f, "last_detected") for f in flows)
                if last:
                    self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last))
                    watermark_advanced = True
            return inserted
        finally:
            logger.info(
                "Traffic ingest poll: fetched={} inserted={} watermark_advanced={} since={}",
                len(flows), inserted, watermark_advanced, since,
            )

    def _since_cursor(self) -> Optional[str]:
        wm = self._wm.get(self.SOURCE)
        if wm and wm.last_timestamp:
            # Grace window: re-pull 5 minutes back to catch late-arriving flows
            grace = wm.last_timestamp - timedelta(minutes=5)
            return grace.isoformat()
        return None

    def _insert_batch(self, flows: list[dict]) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for flow in flows:
            flat = _flatten_flow(flow)
            if not self._filter.passes(flat):
                continue
            if not self._sampler.keep(flat):
                continue
            fh = _flow_hash(flow)
            src_wl = (flow.get("src") or {}).get("workload") or {}
            dst_wl = (flow.get("dst") or {}).get("workload") or {}
            svc = flow.get("service") or {}
            src_ip = flow.get("src_ip", "") or (flow.get("src") or {}).get("ip", "")
            dst_ip = flow.get("dst_ip", "") or (flow.get("dst") or {}).get("ip", "")
            port = svc.get("port") if svc else flow.get("port", 0)
            protocol = _proto_to_str(svc.get("proto") if svc else flow.get("protocol", "tcp"))
            action = flow.get("action") or flow.get("policy_decision", "unknown")
            flow_count = flow.get("flow_count") or flow.get("num_connections", 1)
            first_raw = _ts(flow, "first_detected")
            last_raw = _ts(flow, "last_detected")
            try:
                with self._sf.begin() as s:
                    row = PceTrafficFlowRaw(
                        flow_hash=fh,
                        first_detected=_parse_iso(first_raw) if first_raw else now,
                        last_detected=_parse_iso(last_raw) if last_raw else now,
                        src_ip=src_ip,
                        src_workload=src_wl.get("href") or flow.get("src_workload"),
                        dst_ip=dst_ip,
                        dst_workload=dst_wl.get("href") or flow.get("dst_workload"),
                        port=port or 0,
                        protocol=protocol,
                        action=action,
                        flow_count=flow_count,
                        bytes_in=flow.get("bytes_in") or flow.get("dst_bi", 0),
                        bytes_out=flow.get("bytes_out") or flow.get("dst_bo", 0),
                        raw_json=orjson.dumps(flow).decode("utf-8"),
                        ingested_at=now,
                    )
                    s.add(row)
                    if self._siem_dests:
                        s.flush()
                        for dest in self._siem_dests:
                            s.add(SiemDispatch(
                                source_table="pce_traffic_flows_raw",
                                source_id=row.id,
                                destination=dest,
                                status="pending",
                                retries=0,
                                queued_at=now,
                            ))
            except IntegrityError:
                continue
            count += 1
        return count


def _flow_hash(flow: dict) -> str:
    src_wl = (flow.get("src") or {}).get("workload") or {}
    dst_wl = (flow.get("dst") or {}).get("workload") or {}
    svc = flow.get("service") or {}
    key = "|".join([
        flow.get("src_ip", "") or src_wl.get("href", ""),
        flow.get("dst_ip", "") or dst_wl.get("href", ""),
        str(svc.get("port", "") or flow.get("port", "")),
        str(svc.get("proto", "") or flow.get("protocol", "")),
        _ts(flow, "first_detected"),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _ts(flow: dict, key: str) -> str:
    """Extract first/last_detected from top-level or nested timestamp_range."""
    return flow.get(key) or (flow.get("timestamp_range") or {}).get(key, "")


def _proto_to_str(proto) -> str:
    if proto is None:
        return "tcp"
    if isinstance(proto, str):
        return proto
    _MAP = {6: "tcp", 17: "udp", 1: "icmp"}
    return _MAP.get(int(proto), str(proto))


def _flatten_flow(flow: dict) -> dict:
    """Return a flat-field view of flow for filter/sampler checks (handles nested PCE API format)."""
    svc = flow.get("service") or {}
    src = flow.get("src") or {}
    return {
        "action": flow.get("action") or flow.get("policy_decision", "unknown"),
        "src_ip": flow.get("src_ip", "") or src.get("ip", ""),
        "port": svc.get("port") if svc else flow.get("port"),
        "protocol": _proto_to_str(svc.get("proto") if svc else flow.get("protocol")),
    }


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
