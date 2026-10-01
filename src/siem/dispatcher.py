from __future__ import annotations

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    DeadLetter, PceEvent, PceTrafficFlowRaw, SiemDispatch,
)
from src.siem.formatters.base import Formatter
from src.siem.pd import pd_accepted
from src.siem.transports.base import Transport


def _is_permanent_send_error(exc: BaseException) -> bool:
    """重試也不會成功的送出錯誤：直接進 DLQ。

    - HTTP 4xx（408 逾時、429 限流除外）：HEC 回 400（格式錯）、401/403（token
      錯）重送同一筆只會得到同樣結果。
    - EMSGSIZE：UDP 訊息超過 datagram 上限，重送同樣送不出去。
    """
    import errno
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and 400 <= status < 500 and status not in (408, 429):
        return True
    if isinstance(exc, OSError) and exc.errno == errno.EMSGSIZE:
        return True
    return False


def _backoff_seconds(retries: int) -> int:
    return min(2 ** retries * 5, 3600)


def _record_epoch(source_table: str, raw_json: Optional[str]) -> Optional[float]:
    """記錄本身的時間（epoch 秒）：event 取 timestamp、flow 取 last_detected。"""
    if not raw_json:
        return None
    from src.siem.formatters.syslog_header import event_record_time, flow_record_time
    try:
        data = orjson.loads(raw_json)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    dt = event_record_time(data) if source_table == "pce_events" else flow_record_time(data)
    return dt.timestamp() if dt else None


# SQLite 的 SQLITE_LIMIT_VARIABLE_NUMBER 預設為 999；批次標記 sent 時把
# id 清單切成 ≤ 此值一組，避免 batch_size 調高（config 允許到 10000）時
# 觸發 "too many SQL variables"。仍在同一 transaction 內完成（每 tick 一次 commit）。
_SENT_UPDATE_CHUNK = 900


class DestinationDispatcher:
    """Dispatcher for a single SIEM destination."""

    def __init__(
        self,
        name: str,
        session_factory: sessionmaker,
        formatter: Formatter,
        transport: Transport,
        max_retries: int = 10,
        batch_size: int = 100,
        mask_pii: bool = False,
        dlq_max: int = 10000,
    ):
        self._name = name
        self._sf = session_factory
        self._formatter = formatter
        self._transport = transport
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._mask_pii = mask_pii
        self._dlq_max = dlq_max
        self._lock = threading.Lock()

    def close(self) -> None:
        """Release transport resources (connection pool)."""
        if hasattr(self._transport, "close"):
            try:
                self._transport.close()
            except Exception as exc:
                logger.warning("transport close failed for {!r}: {}", self._name, exc)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # tick 內最多處理幾批：時間預算之外的第二道上限，保證迴圈有界。
    _MAX_BATCHES_PER_TICK = 1000

    def tick(self, time_budget_seconds: Optional[float] = None) -> dict:
        """送出待送列。

        time_budget_seconds=None：只處理一批（舊行為）。給了預算就在預算內一批
        接一批送，直到佇列清空、某批因目的地連線失敗而中止，或預算用完——
        舊版每 tick 固定一批（預設每 30 秒 100 筆，約每天 28.8 萬筆），traffic
        一次 ingest 就可能排入 20 萬筆，積壓只會越來越久。

        回傳 {sent, failed, quarantined, batches, aborted, error}；aborted 為
        True 表示目的地連不上（斷路器打開），error 是最後一次的錯誤訊息。
        """
        totals = {"sent": 0, "failed": 0, "quarantined": 0, "batches": 0,
                  "aborted": False, "error": None}
        if not self._lock.acquire(blocking=False):
            return totals
        try:
            deadline = (time.monotonic() + time_budget_seconds
                        if time_budget_seconds is not None else None)
            while totals["batches"] < self._MAX_BATCHES_PER_TICK:
                result = self._process_batch()
                totals["batches"] += 1
                for key in ("sent", "failed", "quarantined"):
                    totals[key] += result[key]
                if result.get("aborted"):
                    totals["aborted"] = True
                    totals["error"] = result.get("error")
                    break
                attempted = result["sent"] + result["failed"] + result["quarantined"]
                if deadline is None or attempted < self._batch_size or attempted == 0:
                    break
                if time.monotonic() >= deadline:
                    break
            return totals
        finally:
            self._lock.release()

    def _process_batch(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        failed = quarantined = 0

        with self._sf() as s:
            rows = s.execute(
                select(SiemDispatch)
                .where(SiemDispatch.destination == self._name)
                .where(SiemDispatch.status == "pending")
                .where(
                    (SiemDispatch.next_attempt_at == None) |  # noqa: E711
                    (SiemDispatch.next_attempt_at <= now)
                )
                .order_by(SiemDispatch.queued_at)
                .limit(self._batch_size)
            ).scalars().all()
            # 單一 session 批次載入本批的 source rows（原本每列各開一個
            # session —— NullPool 下 batch=100 就是 100 條新 SQLite 連線）。
            sources = self._load_sources(s, rows)

        sent_rows: list[tuple[SiemDispatch, str]] = []
        aborted_error: Optional[str] = None
        for dispatch_row in rows:
            payload = self._build_payload(
                dispatch_row, sources.get((dispatch_row.source_table, dispatch_row.source_id))
            )
            if payload is None:
                # Route build failures through the DLQ (not a bare status='failed')
                # so the dropped event stays inspectable and replayable.
                if self._quarantine(dispatch_row, None, "payload_build_failed"):
                    quarantined += 1
                else:
                    failed += 1
                continue
            try:
                self._send(payload, dispatch_row,
                           sources.get((dispatch_row.source_table, dispatch_row.source_id)))
                sent_rows.append((dispatch_row, payload))
            except Exception as exc:
                if _is_permanent_send_error(exc):
                    # 重試也不會成功（HEC 400/403、UDP 訊息超過 datagram 上限）：
                    # 直接進 DLQ，不佔用重試，也不必中止這一批。
                    logger.warning("SIEM dispatch for row {} rejected permanently: {}",
                                   dispatch_row.id, exc)
                    if self._quarantine(dispatch_row, payload, f"permanent: {exc}"):
                        quarantined += 1
                    else:
                        failed += 1
                    continue
                # 斷路器：目的地層級的失敗（連不上、逾時、5xx）會讓同批其餘列
                # 一筆一筆重複等逾時——HEC 每筆最多重試 4 次×10 秒，一批 100 筆
                # 可以卡住整個 job 超過一小時，其他目的地也被拖住，而且這些列
                # 全都被扣重試次數、提早進 DLQ。這裡只記這一筆的失敗，剩下的列
                # 原封不動留在佇列，下個 tick 再試。
                logger.warning("SIEM destination {!r} send failed for row {}: {} — "
                               "aborting this batch", self._name, dispatch_row.id, exc)
                if self._record_failure(dispatch_row, payload, str(exc)):
                    quarantined += 1
                else:
                    failed += 1
                aborted_error = str(exc)
                break

        # 串流型 transport（TCP／TLS）在標記 sent 之前先 graceful close 確認送達：
        # 直接 close() 會因接收 buffer 有未讀資料（TLS session ticket）送出 RST，
        # 對端丟掉這一批的尾段；對端在收尾時 reset 也代表這批不保證送達。
        # 確認失敗就把這批當成送出失敗走重試／DLQ（at-least-once，可能重複）。
        finish_batch = getattr(self._transport, "finish_batch", None)
        if sent_rows and finish_batch is not None:
            try:
                finish_batch()
            except Exception as exc:
                logger.warning(
                    "SIEM destination {!r}: delivery of {} row(s) not confirmed at "
                    "connection close ({}); will retry", self._name, len(sent_rows), exc)
                for dispatch_row, payload in sent_rows:
                    if self._record_failure(dispatch_row, payload, f"delivery_unconfirmed: {exc}"):
                        quarantined += 1
                    else:
                        failed += 1
                sent_rows = []
                aborted_error = aborted_error or f"delivery_unconfirmed: {exc}"
        sent = len(sent_rows)
        sent_ids = [row.id for row, _ in sent_rows]

        # 成功送出的列以單一 transaction 一次標記 sent（原本逐列 commit 是
        # 與 ingest 對撞的主要寫鎖 churn）。若 process 在網路送出後、此
        # commit 前崩潰，那些列下輪會重送 —— 重複交付窗口因此變寬。
        # 這是刻意的 at-least-once 取捨：SIEM 本即 at-least-once，
        # 使用者已同意 eventual。
        if sent_ids:
            sent_at = datetime.now(timezone.utc)
            with self._sf.begin() as s:
                for i in range(0, len(sent_ids), _SENT_UPDATE_CHUNK):
                    chunk = sent_ids[i:i + _SENT_UPDATE_CHUNK]
                    s.execute(
                        update(SiemDispatch)
                        .where(SiemDispatch.id.in_(chunk))
                        .values(status="sent", sent_at=sent_at)
                    )

        return {"sent": sent, "failed": failed, "quarantined": quarantined,
                "aborted": aborted_error is not None, "error": aborted_error}

    def _record_failure(self, row: SiemDispatch, payload: Optional[str], error: str) -> bool:
        """記一次送出失敗：達 max_retries 進 DLQ（回 True），否則排退避重試（回 False）。
        DLQ 已滿時不進 DLQ，留在佇列以最長退避重試（也回 False）。"""
        new_retries = row.retries + 1
        if new_retries >= self._max_retries:
            # DLQ 已滿時 _quarantine 自己會把這一列排成最長退避，不再覆寫。
            return self._quarantine(row, payload, error)
        next_at = datetime.now(timezone.utc) + timedelta(seconds=_backoff_seconds(new_retries))
        with self._sf.begin() as s:
            s.execute(
                update(SiemDispatch)
                .where(SiemDispatch.id == row.id)
                .values(retries=new_retries, next_attempt_at=next_at)
            )
        return False

    _SOURCE_MODELS = {
        "pce_events": PceEvent,
        "pce_traffic_flows_raw": PceTrafficFlowRaw,
    }

    def _load_sources(self, s, rows: list[SiemDispatch]) -> dict[tuple[str, int], str]:
        """依 source_table 分組後對本批 source_id 各發一次 IN 查詢，取回
        raw_json（_build_payload 唯一用到的欄位，column-only select 同時省
        去 report_json 等未用欄位）。缺列的 (source_table, source_id) 不會
        出現在回傳的 dict 中 —— _build_payload 以此判斷缺 source row，維持
        原本『找不到就回 None』的語意。
        """
        ids_by_table: dict[str, list[int]] = {}
        for r in rows:
            ids_by_table.setdefault(r.source_table, []).append(r.source_id)

        loaded: dict[tuple[str, int], str] = {}
        for table_name, ids in ids_by_table.items():
            model = self._SOURCE_MODELS.get(table_name)
            if model is None:
                continue
            for i in range(0, len(ids), _SENT_UPDATE_CHUNK):
                chunk = ids[i:i + _SENT_UPDATE_CHUNK]
                for src_id, raw_json in s.execute(
                    select(model.id, model.raw_json).where(model.id.in_(chunk))
                ):
                    loaded[(table_name, src_id)] = raw_json
        return loaded

    def _send(self, payload: str, row: SiemDispatch, raw_json: Optional[str]) -> None:
        """送出一筆；transport 支援 send_record 時一併帶上記錄本身的時間。"""
        send_record = getattr(self._transport, "send_record", None)
        if send_record is None:
            self._transport.send(payload)
            return
        send_record(payload, event_time=_record_epoch(row.source_table, raw_json))

    def _build_payload(self, row: SiemDispatch, raw_json: Optional[str]) -> Optional[str]:
        if raw_json is None:
            return None
        try:
            data = orjson.loads(raw_json)
            if row.source_table == "pce_events":
                if self._mask_pii:
                    from src.siem.mask import mask_event
                    data = mask_event(data, mask_pii=True)
                return self._formatter.format_event(data)
            elif row.source_table == "pce_traffic_flows_raw":
                if self._mask_pii:
                    from src.siem.mask import mask_flow
                    data = mask_flow(data, mask_pii=True)
                return self._formatter.format_flow(data)
        except Exception as exc:
            logger.exception("Failed to build payload for dispatch row {}: {}", row.id, exc)
        return None

    def _dlq_full(self, s) -> bool:
        if not self._dlq_max or self._dlq_max <= 0:
            return False
        count = s.execute(
            select(func.count(DeadLetter.id)).where(DeadLetter.destination == self._name)
        ).scalar_one()
        return count >= self._dlq_max

    def _quarantine(self, row: SiemDispatch, payload: Optional[str], error: str) -> bool:
        """移入 DLQ。回傳 True 表示已移入；DLQ 已達上限時回 False，該列留在佇列。

        舊版是 ring buffer：滿了就刪最舊的 DLQ 項目，那些記錄從此找不回來，
        補登機制也不會補（它只看 siem_dispatch）。現在 DLQ 滿了就不再收：
        這一列維持 pending、以最長退避（1 小時）重試，資料留在本機不遺失；
        佇列積壓由 siem_pending_warn_rows 告警，操作者清理或重送 DLQ 後恢復。
        """
        now = datetime.now(timezone.utc)
        with self._sf.begin() as s:
            if self._dlq_full(s):
                logger.error(
                    "SIEM DLQ for {!r} is full ({} entries); row {} stays queued "
                    "instead of dropping older dead letters — replay or purge the DLQ",
                    self._name, self._dlq_max, row.id,
                )
                s.execute(
                    update(SiemDispatch)
                    .where(SiemDispatch.id == row.id)
                    .values(retries=row.retries + 1,
                            next_attempt_at=now + timedelta(seconds=_backoff_seconds(99)))
                )
                return False
            s.add(DeadLetter(
                source_table=row.source_table,
                source_id=row.source_id,
                destination=self._name,
                retries=row.retries + 1,
                last_error=error[:4000],
                payload_preview=payload[:512] if payload else "",
                quarantined_at=now,
            ))
            s.execute(
                update(SiemDispatch)
                .where(SiemDispatch.id == row.id)
                .values(status="failed")
            )
        return True


def pce_identity(cm, api) -> tuple[str, str]:
    """(fqdn, version) the cef_pce formatter stamps on every line. Best
    effort: the PCE's own syslog carries its real version, we ask
    /product_version once per dispatcher build and fall back to 'unknown'."""
    from urllib.parse import urlsplit
    url = str(((getattr(cm, "config", None) or {}).get("api") or {}).get("url") or "")
    fqdn = urlsplit(url).hostname or ""
    version = "unknown"
    if api is not None:
        try:
            status, body = api._api_get("/product_version")
            if status == 200 and isinstance(body, dict) and body.get("version"):
                version = str(body["version"])
        except Exception as exc:  # noqa: BLE001 — identity is cosmetic, never blocks dispatch
            logger.warning("product_version lookup failed, cef_pce header will say 'unknown': {}", exc)
    return fqdn, version


def _formatter_for(dest_cfg, *, pce_fqdn: str = "", pce_version: str = "unknown"):
    """Build formatter from SiemDestinationSettings."""
    from src.siem.formatters.cef import CEFFormatter
    from src.siem.formatters.cef_pce import PceNativeCEFFormatter
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    fmt = dest_cfg.format
    if fmt == "cef":
        return CEFFormatter(pce_fqdn=pce_fqdn, pce_version=pce_version)
    if fmt == "syslog_cef":
        return SyslogWrappedFormatter(CEFFormatter(pce_fqdn=pce_fqdn, pce_version=pce_version))
    if fmt == "cef_pce":
        return PceNativeCEFFormatter(pce_fqdn=pce_fqdn, pce_version=pce_version)
    if fmt == "syslog_cef_pce":
        return SyslogWrappedFormatter(PceNativeCEFFormatter(pce_fqdn=pce_fqdn, pce_version=pce_version))
    if fmt == "syslog_json":
        return SyslogWrappedFormatter(NormalizedJSONFormatter())
    return NormalizedJSONFormatter()


_IDENTITY_TTL_S = 3600.0
_identity_cache: dict[str, tuple[float, tuple[str, str]]] = {}


def cached_pce_identity(cm) -> tuple[str, str]:
    """pce_identity() memoised per PCE url for an hour — run_siem_dispatch
    ticks every few seconds and must not hit /product_version each time."""
    import time
    url = str(((getattr(cm, "config", None) or {}).get("api") or {}).get("url") or "")
    hit = _identity_cache.get(url)
    now = time.monotonic()
    if hit and now - hit[0] < _IDENTITY_TTL_S:
        return hit[1]
    from src.api_client import ApiClient
    try:
        with ApiClient(cm) as api:
            ident = pce_identity(cm, api)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cef_pce identity lookup failed: {}", exc)
        ident = pce_identity(cm, None)
    _identity_cache[url] = (now, ident)
    return ident


def _transport_for(dest_cfg):
    """Build transport from SiemDestinationSettings."""
    transport_type = dest_cfg.transport.lower()
    host = dest_cfg.host
    port = dest_cfg.port
    if transport_type == "udp":
        from src.siem.transports.syslog_udp import SyslogUDPTransport
        return SyslogUDPTransport(host, port)
    elif transport_type == "tcp":
        from src.siem.transports.syslog_tcp import SyslogTCPTransport
        return SyslogTCPTransport(host, port)
    elif transport_type == "tls":
        from src.siem.transports.syslog_tls import SyslogTLSTransport
        return SyslogTLSTransport(
            host, port,
            tls_verify=dest_cfg.tls_verify,
            ca_bundle=dest_cfg.tls_ca_bundle,
        )
    elif transport_type == "hec":
        from src.siem.transports.splunk_hec import SplunkHECTransport
        url = f"https://{host}:{port}"
        return SplunkHECTransport(
            url,
            token=dest_cfg.hec_token or "",
            verify_tls=dest_cfg.tls_verify,
        )
    raise ValueError(f"Unknown transport: {transport_type}")


def build_dispatcher(dest_cfg, session_factory, dlq_max_per_dest: int = 10000, *,
                     pce_fqdn: str = "", pce_version: str = "unknown") -> "DestinationDispatcher":
    """Build a DestinationDispatcher from a SiemDestinationSettings instance.

    dlq_max_per_dest 是全域 SiemSettings 欄位（非 per-destination），由呼叫端
    帶入；預設值與 config_models.SiemSettings.dlq_max_per_dest 一致。
    """
    return DestinationDispatcher(
        name=dest_cfg.name,
        session_factory=session_factory,
        formatter=_formatter_for(dest_cfg, pce_fqdn=pce_fqdn, pce_version=pce_version),
        transport=_transport_for(dest_cfg),
        max_retries=dest_cfg.max_retries,
        batch_size=dest_cfg.batch_size,
        mask_pii=bool(getattr(dest_cfg, "mask_pii", False)),
        dlq_max=dlq_max_per_dest,
    )


def enqueue(
    session_factory: sessionmaker,
    source_table: str,
    source_id: int,
    destinations: list[str],
) -> None:
    """Create one siem_dispatch row per destination for a newly-ingested record."""
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        for dest in destinations:
            s.add(SiemDispatch(
                source_table=source_table,
                source_id=source_id,
                destination=dest,
                status="pending",
                retries=0,
                queued_at=now,
            ))


# 補登 insert 的 chunk 大小，比照 repo 既有慣例（ingestor_events/traffic
# 皆用 500）。
_ENQUEUE_CHUNK = 500


def enqueue_new_records(
    session_factory: sessionmaker,
    destinations_by_source_table: dict[str, list[str]],
    dispatch_retention_days: int = 14,
    pd_filters: Optional[dict[str, set[str]]] = None,
) -> int:
    """Safety-net backfill: enqueue any (cache row, destination) pairs that
    ingestors didn't enqueue inline.

    Ingestors enqueue rows in the same transaction as the cache write, so this
    function should normally find nothing. It exists to cover (a) a
    destination being newly added/enabled for a source_type — historical rows
    of that source_type were never enqueued to it, even if the same cache row
    already has dispatch rows for other destinations — (b) crash recovery,
    and (c) operator-driven backfill.

    The scan is bounded to source rows with ingested_at inside the dispatch
    retention horizon (dispatch_retention_days; must match retention.run_once
    dispatch_days, default 14). Retention prunes *sent* dispatch rows after
    that horizon while source rows live longer (events: 90 days), so an
    unbounded scan would misread "dispatch row pruned" as "never enqueued"
    and re-deliver the whole older window as duplicates every tick. Within
    the horizon the bound is loss-free: a sent row's sent_at >= its source's
    ingested_at, so its dispatch row cannot have been pruned yet. Trade-off:
    a newly added destination is only backfilled this window, not the full
    source retention.

    The anti-join is scoped per (source_table, source_id, destination), not
    just per (source_table, source_id): a row already dispatched to
    destination A is still eligible for backfill to newly-enabled destination
    B if it lacks a B row. at-least-once semantics for a given
    (row, destination) pair are unchanged — the anti-join still guards
    against re-enqueuing a pair that already has a dispatch row.

    destinations_by_source_table maps source_table (e.g. "pce_events") to the
    destination names already filtered to that source_table's source_type
    (see scheduler.jobs._enabled_siem_destinations). This mirrors the
    ingest-side filter so, e.g., an audit-only destination is never backfilled
    a traffic row and vice versa.

    Steady-state cost: exactly one scan of each source table's in-horizon
    rows per call (ingested_at is indexed), independent of the number of
    destinations. This runs unconditionally
    every dispatch tick (default 30s), so the candidate scan folds all
    destinations' NOT EXISTS into a single OR'd query (phase 1); only the
    normally-empty candidate set pays a second, indexed per-destination
    resolution (phase 2).

    All new rows are inserted within a single transaction (chunked to respect
    SQLite's bound-parameter cap), not one transaction per row — backfilling a
    large cache on first SIEM enable would otherwise be a per-row fsync storm.

    pd_filters maps a destination name to the set of traffic policy decisions
    it subscribes to (SiemDestinationSettings.traffic_pd); absent or empty =
    every decision. It applies to pce_traffic_flows_raw only and mirrors the
    ingestor's inline gate, so backfill can never queue a row that ingest
    would have skipped.

    Returns count of new dispatch rows created.
    """
    pd_filters = pd_filters or {}
    pairs: list[tuple[str, type]] = [
        ("pce_events", PceEvent),
        ("pce_traffic_flows_raw", PceTrafficFlowRaw),
    ]
    to_enqueue: list[tuple[str, int, str]] = []  # (source_table, source_id, destination)
    horizon = datetime.now(timezone.utc) - timedelta(days=dispatch_retention_days)
    with session_factory() as s:
        for source_table, model in pairs:
            dests = destinations_by_source_table.get(source_table) or []
            if not dests:
                continue

            def _dispatched_to(dest: str):
                # Anti-join 帶 destination 條件：曾為其他 destination enqueue
                # 過的 row，對新啟用的 destination 仍補得到；同一
                # (row, destination) pair 則被擋住。相比舊版「載入全部
                # dispatched id + `id NOT IN (...)`」，correlated NOT EXISTS
                # 也不會撞 SQLite 變數上限。
                return (
                    select(SiemDispatch.id)
                    .where(
                        SiemDispatch.source_table == source_table,
                        SiemDispatch.source_id == model.id,
                        SiemDispatch.destination == dest,
                    )
                    .exists()
                )

            # Phase 1：單次全表掃描找候選 —— 缺「任一」destination dispatch
            # row 的 source rows（全部 destination 的 NOT EXISTS 以 OR 合併）。
            # 正常情況（ingest 已 inline enqueue）回空集合，直接結束。
            # traffic rows carry their policy decision so phase 2 can apply the
            # per-destination pd filter without a second lookup.
            is_traffic = source_table == "pce_traffic_flows_raw"
            action_col = model.action if is_traffic else model.id
            candidate_rows = s.execute(
                select(model.id, action_col)
                .where(model.ingested_at >= horizon)
                .where(or_(*[~_dispatched_to(dest) for dest in dests]))
            ).all()
            if not candidate_rows:
                continue
            candidates = [sid for sid, _ in candidate_rows]
            action_by_id = {sid: act for sid, act in candidate_rows} if is_traffic else {}

            def _accepts(dest: str, sid: int) -> bool:
                if not is_traffic:
                    return True
                return pd_accepted(pd_filters.get(dest), action_by_id.get(sid))

            # Phase 2：僅對候選 id 精確判定缺哪些 (id, destination) pair。
            # 以 chunked `id IN (...)` 走 ix_dispatch_source 索引查既有
            # pair，再於 Python 補集 —— 成本與候選數成正比，與全表無關。
            dest_set = set(dests)
            for i in range(0, len(candidates), _SENT_UPDATE_CHUNK):
                chunk = candidates[i:i + _SENT_UPDATE_CHUNK]
                existing = set(
                    s.execute(
                        select(SiemDispatch.source_id, SiemDispatch.destination)
                        .where(
                            SiemDispatch.source_table == source_table,
                            SiemDispatch.source_id.in_(chunk),
                            SiemDispatch.destination.in_(dest_set),
                        )
                    ).all()
                )
                to_enqueue.extend(
                    (source_table, sid, dest)
                    for sid in chunk
                    for dest in dests
                    if (sid, dest) not in existing and _accepts(dest, sid)
                )

    total = len(to_enqueue)
    if total:
        now = datetime.now(timezone.utc)
        with session_factory.begin() as s:
            for i in range(0, total, _ENQUEUE_CHUNK):
                chunk = to_enqueue[i:i + _ENQUEUE_CHUNK]
                s.add_all([
                    SiemDispatch(
                        source_table=source_table, source_id=source_id,
                        destination=dest, status="pending", retries=0,
                        queued_at=now,
                    )
                    for source_table, source_id, dest in chunk
                ])
                # 逐 chunk flush，使每個 INSERT 陳述式受 chunk 上限約束，
                # 但仍在同一 transaction 內（commit 只有一次）。
                s.flush()
        logger.info(
            "siem safety-net backfill enqueued {} (row, destination) pairs "
            "(ingestors should normally cover this; expected after "
            "destination add/enable or crash recovery)",
            total,
        )
    return total
