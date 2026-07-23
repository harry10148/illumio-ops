"""ApiClient — facade composing HTTP core + LabelResolver + AsyncJobManager + TrafficQueryBuilder.

Phase 9 Task 6 refactor: the original 2569-line god class has been decomposed
into three focused domain classes under src/api/. This module now hosts:

  * shared HTTP infrastructure (Session, Retry, _build_auth_header, _request)
  * simple endpoints (check_health, fetch_events, workload / label / ruleset CRUD)
  * cache + state fields owned by the facade (label_cache, _cache_lock,
    ruleset_cache, last_*_diagnostics, _state_file, _async_job_* TTLs, ...)
  * thin delegation wrappers around every public method that moved to a domain
    class — external callers and tests see the same interface as before.

Re-exported symbols (for backward compatibility):

    from src.api_client import ApiClient, EventFetchError, TrafficQuerySpec
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import threading
import time
import urllib.parse
from typing import Any, Iterator, Literal

import orjson
import requests
from cachetools import TTLCache
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.api.async_jobs import AsyncJobManager
from src.api.labels import LabelResolver
from src.api.reports import ReportsApi
from src.api.traffic_query import (
    MAX_TRAFFIC_RESULTS,
    TrafficQueryBuilder,
    TrafficQuerySpec,
    _TRAFFIC_FILTER_CAPABILITIES,
)
from src.exceptions import APIError
from src.href_utils import extract_id as _extract_id
from src.i18n import t
from src.utils import Colors

MAX_RETRIES = 3
_ASYNC_JOB_STATE_KEY = "async_query_jobs"
_QUERY_LOOKUP_CACHE_TTL_SECONDS = 300
# 截斷 async fallback 的 process 級 memo/退避：GUI 路由每請求建新 ApiClient，
# per-instance 狀態擋不住「集合真 >500 時每請求都對 PCE 提交一個 async job」
# 的放大效應（最終 review finding 1）。成功結果 memo 5 分鐘、失敗退避 10 分鐘。
_ASYNC_FALLBACK_MEMO_TTL_SECONDS = 300
_ASYNC_FALLBACK_FAILURE_BACKOFF_SECONDS = 600
_ASYNC_FALLBACK_LOCK = threading.Lock()
_ASYNC_FALLBACK_MEMO: dict[str, tuple[float, list]] = {}
_ASYNC_FALLBACK_FAILED_AT: dict[str, float] = {}
_LABEL_CACHE_TTL_SECONDS = 900  # 15 minutes — Phase 2 Q5 fix
_ASYNC_JOB_CACHE_MAX_AGE_DAYS = 7
_ASYNC_JOB_PRUNE_INTERVAL_SECONDS = 3600


_TLS_VERIFY_DISABLED_WARNED = False


def _warn_tls_verification_disabled_once() -> None:
    """Emit the TLS-verification-disabled warning once per process.

    ApiClient is constructed many times (per request handler, per scheduler
    job, per CLI run); without this gate, the warning floods logs. The
    security reminder still appears once at first construction.
    """
    global _TLS_VERIFY_DISABLED_WARNED
    if _TLS_VERIFY_DISABLED_WARNED:
        return
    _TLS_VERIFY_DISABLED_WARNED = True
    logger.warning(
        "TLS certificate verification is disabled for PCE API — security risk "
        "(this warning is logged once per process)"
    )


class EventFetchError(RuntimeError):
    """Raised when the PCE events API cannot be fetched safely."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ApiClient:
    """Facade over the PCE REST API. Composes three domain classes:

        self._labels  : LabelResolver       — cache + label/IP/service lookups
        self._jobs    : AsyncJobManager     — async query job lifecycle
        self._traffic : TrafficQueryBuilder — traffic payload + execution

    All public methods that moved to a domain class are re-exposed as thin
    delegation wrappers so that ``from src.api_client import ApiClient`` and
    every existing call site continues to work unchanged.
    """

    def __init__(self, config_manager: Any) -> None:
        self.cm = config_manager
        self.api_cfg = self.cm.config["api"]
        self.base_url = f"{self.api_cfg['url']}/api/v2/orgs/{self.api_cfg['org_id']}"
        self._auth_header = self._build_auth_header()
        # 熱路徑修正：rpm 在建構時讀一次快取，_request 不再每次呼叫都重建 ConfigManager。
        # ConfigManager.load() 成功與 ValidationError fallback 兩條路徑都必定設 self.models
        # （config.py:227,244），且 ConfigSchema.pce_cache 有 default_factory——真實
        # ConfigManager 不存在缺 .models 的路徑，直讀即可；測試替身缺 .models 屬於替身
        # 的型別違約，應修測試而非在生產碼留 fallback。
        self._rate_limit_per_minute = int(self.cm.models.pce_cache.rate_limit_per_minute)

        # ── Caches (TTL) + lock — owned by facade so tests can mutate directly ──
        # Use time.time (wall clock) so freezegun can control expiry in tests.
        self._cache_lock = threading.RLock()  # RLock: re-entrant (update_label_cache calls invalidate_*)
        self.label_cache: Any = TTLCache(maxsize=10000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self.ruleset_cache: list[dict[str, Any]] = []
        self.service_ports_cache: Any = TTLCache(maxsize=5000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._label_href_cache: Any = TTLCache(maxsize=10000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._label_group_href_cache: Any = TTLCache(maxsize=1000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._iplist_href_cache: Any = TTLCache(maxsize=5000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)

        # Diagnostics (read via getter / written by domain classes)
        self.last_traffic_query_diagnostics: dict[str, Any] = {}
        self.last_rule_usage_batch_stats: dict[str, Any] = {}
        # Set (and cleared on success) by fetch_events() / the traffic async
        # query submit path whenever a connection-layer failure (DNS/refused/
        # timeout) is swallowed into an empty result — report/GUI consumers
        # keep degrading gracefully to [], but pce_cache ingestors read this to
        # tell "PCE unreachable" apart from "PCE says genuinely 0 rows" (see
        # .superpowers/sdd/watchdog-live-reverify-report.md step 2).
        self.last_fetch_error: str | None = None
        # Task 1 (API layer hardening)：_get_collection 偵測到集合 GET 截斷
        # （X-Total-Count > 實收筆數）時記錄 path，供 Task 2 消費做 async fallback。
        self.last_truncated_collections: list[str] = []

        # State-store paths + async job cache TTL parameters
        self._root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._state_file = os.path.join(self._root_dir, "logs", "state.json")
        self._query_lookup_cache_refreshed_at = 0.0
        self._query_lookup_cache_ttl_seconds = _QUERY_LOOKUP_CACHE_TTL_SECONDS
        self._async_job_cache_max_age_days = _ASYNC_JOB_CACHE_MAX_AGE_DAYS
        self._async_job_prune_interval_seconds = _ASYNC_JOB_PRUNE_INTERVAL_SECONDS
        self._last_async_job_prune_at = 0.0

        # ── HTTP session with connection pool + automatic retry (Phase 2) ──
        self._session = requests.Session()
        _verify_cfg = self.api_cfg.get('verify_ssl', True)
        self._session.verify = _verify_cfg if isinstance(_verify_cfg, str) else bool(_verify_cfg)
        if not self._session.verify:
            _warn_tls_verification_disabled_once()
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._session.headers.update({
            "Authorization": self._auth_header,
            "Accept": "application/json",
        })
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=1.0,
            status_forcelist=[429, 502, 503, 504],
            # POST 排除在自動重試之外：read-timeout 後 urllib3 若自動重送 POST，
            # PCE 可能已經處理了第一次請求（provision/create 類端點會被重複執行）。
            # 429 的補償見 _request（收到回應代表 PCE 尚未實際處理，安全單次重試）。
            allowed_methods=frozenset(["GET", "HEAD", "PUT", "DELETE"]),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        # ── Compose domain classes (must come after state is initialised) ──
        self._labels = LabelResolver(self)
        self._jobs = AsyncJobManager(self)
        self._traffic = TrafficQueryBuilder(self)
        self._reports = ReportsApi(self)

    # ═══════════════════════════════════════════════════════════════════════
    # Resource lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    def close(self) -> None:
        """Release the underlying requests.Session connection pool."""
        if getattr(self, "_session", None) is not None:
            try:
                self._session.close()
            except Exception as exc:
                logger.warning("ApiClient.close() failed: {}", exc)
            finally:
                self._session = None

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> Literal[False]:
        # Returns False — does not suppress exceptions; explicit per H-2 contract test
        self.close()
        return False

    # ═══════════════════════════════════════════════════════════════════════
    # HTTP core (stays on facade — shared infrastructure)
    # ═══════════════════════════════════════════════════════════════════════

    def _build_auth_header(self) -> str:
        credentials = f"{self.api_cfg['key']}:{self.api_cfg['secret']}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        return f"Basic {encoded}"

    def _request(self, url: str, method: str = "GET", data: Any = None, headers: dict[str, str] | None = None, timeout: int = 15, stream: bool = False, rate_limit: bool = False) -> tuple[int, Any]:
        """Core HTTP helper using requests.Session + urllib3 Retry.

        Returns (status_code, response_body_bytes | response_object).
        For stream=True, returns (status_code, raw requests.Response).
        """
        if self._session is None:
            raise RuntimeError("ApiClient is closed; create a new instance")
        if rate_limit:
            from src.pce_cache.rate_limiter import get_rate_limiter
            if not get_rate_limiter(rate_per_minute=self._rate_limit_per_minute).acquire(timeout=30.0):
                from src.exceptions import APIError
                raise APIError("Global rate limiter timeout — PCE 500/min budget exhausted")
        req_headers = {}
        if headers:
            req_headers.update(headers)
        body = None
        if data is not None:
            body = json.dumps(data).encode('utf-8')
            req_headers.setdefault("Content-Type", "application/json")

        try:
            resp = self._session.request(
                method=method,
                url=url,
                data=body,
                headers=req_headers,
                timeout=timeout,
                stream=stream,
            )
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return 0, str(e).encode('utf-8')

        # POST 不在 urllib3 Retry 的 allowed_methods 內（見 __init__ 註解）。
        # 但收到 429 代表 PCE 已回應、尚未實際處理這次請求，此時單次重試是安全的
        # （不會重複 provision/create）。stream=True 目前只用在 GET 下載大檔路徑，
        # 這裡明確排除、不涉入此重試邏輯。
        if method == "POST" and resp.status_code == 429 and not stream:
            retry_after = resp.headers.get("Retry-After")
            try:
                wait_s = float(retry_after) if retry_after is not None else 2.0
            except (TypeError, ValueError):
                wait_s = 2.0
            # 夾限：inf/nan 會使 time.sleep 拋例外（違反本函式不拋的契約），
            # 過大值會同步阻塞 GUI worker 執行緒——上限 30s。
            if not math.isfinite(wait_s):
                wait_s = 2.0
            wait_s = min(max(wait_s, 0.0), 30.0)
            time.sleep(wait_s)
            # 429 即限流訊號：重試須重新取全域 rate limiter 預算；取不到就
            # 放棄重試、回傳原 429（維持本函式不拋的契約）。
            if rate_limit:
                from src.pce_cache.rate_limiter import get_rate_limiter
                if not get_rate_limiter(rate_per_minute=self._rate_limit_per_minute).acquire(timeout=30.0):
                    logger.warning("POST 429 retry skipped: rate limiter budget exhausted")
                    return resp.status_code, resp.content
            try:
                resp = self._session.request(
                    method=method,
                    url=url,
                    data=body,
                    headers=req_headers,
                    timeout=timeout,
                    stream=stream,
                )
            except Exception as e:
                logger.error(f"Connection failed on POST 429 retry: {e}")
                return 0, str(e).encode('utf-8')

        if stream:
            return resp.status_code, resp
        return resp.status_code, resp.content

    def check_health(self) -> tuple[int, str]:
        url = f"{self.api_cfg['url']}/api/v2/health"
        try:
            status, body = self._request(url, timeout=10)
            text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            return status, text
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return 0, str(e)

    # ═══════════════════════════════════════════════════════════════════════
    # Events (stays on facade — not part of any moved domain)
    # ═══════════════════════════════════════════════════════════════════════

    def _build_events_url(self, start_time_str: str, end_time_str: str | None = None,
                          max_results: int = 5000, event_type: str | None = None) -> str:
        params: dict[str, Any] = {
            "timestamp[gte]": start_time_str,
            "max_results": max_results,
        }
        if end_time_str:
            params["timestamp[lte]"] = end_time_str
        url = f"{self.base_url}/events?{urllib.parse.urlencode(params)}"
        if event_type:
            url += f"&event_type[eq][]={urllib.parse.quote(event_type)}"
        return url

    def fetch_events_strict(self, start_time_str: str, end_time_str: str | None = None,
                            max_results: int = 5000, event_type: str | None = None,
                            rate_limit: bool = False) -> list[dict[str, Any]]:
        url = self._build_events_url(start_time_str, end_time_str=end_time_str,
                                     max_results=max_results, event_type=event_type)
        status, body = self._request(url, timeout=30, rate_limit=rate_limit)
        if status != 200:
            err_msg = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            raise EventFetchError(status, err_msg[:1000])

        try:
            data = orjson.loads(body)
        except Exception as exc:
            raise EventFetchError(status, f"Invalid events JSON: {exc}") from exc

        if not isinstance(data, list):
            raise EventFetchError(status, f"Unexpected events payload type: {type(data).__name__}")

        return data

    def fetch_events(self, start_time_str: str, end_time_str: str | None = None, max_results: int = 5000,
                     rate_limit: bool = False) -> list[dict[str, Any]]:
        try:
            events = self.fetch_events_strict(
                start_time_str,
                end_time_str=end_time_str,
                max_results=max_results,
                rate_limit=rate_limit,
            )
            self.last_fetch_error = None
            return events
        except EventFetchError as e:
            self.last_fetch_error = f"{e.status}: {e.message}"
            logger.error(f"Get Events Failed: {e.status} - {e.message}")
            print(f"{Colors.FAIL}{t('api_get_events_failed', status=e.status, error=e.message[:500])}{Colors.ENDC}")
            return []
        except Exception as e:
            self.last_fetch_error = str(e)
            logger.error(f"Fetch Events Error: {e}")
            print(f"{Colors.FAIL}{t('api_fetch_events_error', error=str(e))}{Colors.ENDC}")
            return []

    def get_events(self, max_results: int = 500, since: str | None = None, rate_limit: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        """Sync events pull used by EventsIngestor."""
        return self.fetch_events(
            start_time_str=since or "",
            max_results=max_results,
            rate_limit=rate_limit,
        )

    def get_events_async(self, since: str | None = None, rate_limit: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        """Async bulk events pull via Prefer: respond-async (stub for Phase 13)."""
        return []

    def get_traffic_flows_async(self, max_results: int = 200000, rate_limit: bool = False, since: str | None = None, until: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        """Pull traffic flows for cache ingestion via the async query endpoint."""
        import contextlib, io
        from datetime import datetime, timezone, timedelta
        end_time = until or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if since is None:
            since = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(microsecond=0).isoformat()
        with contextlib.redirect_stdout(io.StringIO()):
            flows = self.fetch_traffic_for_report(
                start_time_str=since, end_time_str=end_time, rate_limit=rate_limit
            ) or []
        # fetch_traffic_for_report has no max_results parameter (native payload
        # always requests MAX_TRAFFIC_RESULTS); enforce the caller's cap here so
        # cache ingestion gets the bound it asked for instead of silently ignoring it.
        if max_results is not None and len(flows) > max_results:
            logger.warning(
                f"get_traffic_flows_async: truncating {len(flows)} flows to max_results={max_results}"
            )
            flows = flows[:max_results]
        return flows

    # ═══════════════════════════════════════════════════════════════════════
    # LabelResolver delegation wrappers
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _normalize_label_filter(label_str: Any) -> str:
        return LabelResolver._normalize_label_filter(label_str)

    @staticmethod
    def _is_ip_literal(value: Any) -> bool:
        return LabelResolver._is_ip_literal(value)

    @staticmethod
    def _is_href(value: Any) -> bool:
        return LabelResolver._is_href(value)

    @staticmethod
    def _normalize_str_list(value: Any) -> list[str]:
        return LabelResolver._normalize_str_list(value)

    @staticmethod
    def _normalize_bool(value: Any) -> bool:
        return LabelResolver._normalize_bool(value)

    @staticmethod
    def _normalize_transmission_values(value: Any) -> list[str]:
        return LabelResolver._normalize_transmission_values(value)

    @staticmethod
    def _parse_port_range_entry(value: Any, default_proto: Any = None) -> dict[str, int] | None:
        return LabelResolver._parse_port_range_entry(value, default_proto=default_proto)

    @staticmethod
    def _dedupe_query_group(items: list[Any]) -> list[Any]:
        return LabelResolver._dedupe_query_group(items)

    def invalidate_query_lookup_cache(self) -> None:
        return self._labels.invalidate_query_lookup_cache()

    def _query_lookup_cache_is_stale(self) -> bool:
        return self._labels._query_lookup_cache_is_stale()

    def _ensure_query_lookup_cache(self, force_refresh: bool = False) -> None:
        return self._labels._ensure_query_lookup_cache(force_refresh=force_refresh)

    def update_label_cache(self, silent: bool = False, force_refresh: bool = True) -> bool:
        return self._labels.update_label_cache(silent=silent, force_refresh=force_refresh)

    def invalidate_labels(self) -> None:
        return self._labels.invalidate_labels()

    def _resolve_actor_filter(self, value: Any) -> dict[str, Any] | None:
        return self._labels._resolve_actor_filter(value)

    def _resolve_label_filter_to_actor(self, label_filter: Any) -> dict[str, Any] | None:
        return self._labels._resolve_label_filter_to_actor(label_filter)

    def _resolve_label_group_filter_to_actor(self, label_group_filter: Any) -> dict[str, Any] | None:
        return self._labels._resolve_label_group_filter_to_actor(label_group_filter)

    def _resolve_ip_filter_to_actor(self, ip_filter: Any) -> dict[str, Any] | None:
        return self._labels._resolve_ip_filter_to_actor(ip_filter)

    def resolve_actor_str(self, actors: list[dict[str, Any]] | None) -> str:
        return self._labels.resolve_actor_str(actors)

    def resolve_service_str(self, services: list[dict[str, Any]] | None) -> str:
        return self._labels.resolve_service_str(services)

    def expand_object_filters_for_df(self, filters: dict) -> dict:
        """iplist/workload filter 展開成 CIDR/IP 清單（df 路徑用）。"""
        return self._labels.expand_object_filters_for_df(filters)

    # ═══════════════════════════════════════════════════════════════════════
    # TrafficQueryBuilder delegation wrappers
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _clone_query_spec(spec: TrafficQuerySpec) -> TrafficQuerySpec:
        return TrafficQueryBuilder._clone_query_spec(spec)

    def get_traffic_query_capability_matrix(self) -> dict[str, dict[str, Any]]:
        return self._traffic.get_traffic_query_capability_matrix()

    def build_traffic_query_spec(self, filters: dict[str, Any] | TrafficQuerySpec | None = None) -> TrafficQuerySpec:
        return self._traffic.build_traffic_query_spec(filters)

    def _build_native_traffic_payload(self, start_time_str: str, end_time_str: str, policy_decisions: list[str], filters: Any = None) -> tuple[dict[str, Any], TrafficQuerySpec]:
        return self._traffic._build_native_traffic_payload(
            start_time_str, end_time_str, policy_decisions, filters=filters
        )

    def _submit_and_stream_async_query(self, payload: dict[str, Any], compute_draft: bool = False, rate_limit: bool = False) -> Iterator[dict[str, Any]]:
        yield from self._traffic._submit_and_stream_async_query(payload, compute_draft=compute_draft, rate_limit=rate_limit)

    def execute_traffic_query_stream(self, start_time_str: str, end_time_str: str, policy_decisions: list[str], filters: Any = None, compute_draft: bool = False, rate_limit: bool = False) -> Iterator[dict[str, Any]]:
        yield from self._traffic.execute_traffic_query_stream(
            start_time_str, end_time_str, policy_decisions, filters=filters, compute_draft=compute_draft,
            rate_limit=rate_limit
        )

    @staticmethod
    def _flow_matches_filters(flow: dict, filters: dict) -> bool:
        return TrafficQueryBuilder._flow_matches_filters(flow, filters)

    def fetch_traffic_for_report(self, start_time_str: str, end_time_str: str, policy_decisions: list[str] | None = None, filters: Any = None, compute_draft: bool = False, rate_limit: bool = False) -> list[dict[str, Any]]:
        return self._traffic.fetch_traffic_for_report(
            start_time_str, end_time_str, policy_decisions=policy_decisions, filters=filters,
            compute_draft=compute_draft, rate_limit=rate_limit
        )

    def get_last_traffic_query_diagnostics(self) -> dict[str, Any]:
        return self._traffic.get_last_traffic_query_diagnostics()

    def get_last_rule_usage_batch_stats(self) -> dict[str, Any]:
        return self._traffic.get_last_rule_usage_batch_stats()

    @staticmethod
    def _sorted_flows_by_port_items(flows_by_port: dict[str, Any] | None, limit: int | None = None) -> list[tuple[str, int]]:
        return TrafficQueryBuilder._sorted_flows_by_port_items(flows_by_port, limit=limit)

    @classmethod
    def _format_flows_by_port(cls, flows_by_port: dict[str, Any] | None, limit: int = 3) -> str:
        return TrafficQueryBuilder._format_flows_by_port(flows_by_port, limit=limit)

    @staticmethod
    def _rule_usage_detail(rule: dict, **extra: Any) -> dict:
        return TrafficQueryBuilder._rule_usage_detail(rule, **extra)

    def _build_query_actors(self, actor_list: list[dict[str, Any]], scope_labels: list[dict[str, Any]] | None = None) -> list[list[dict[str, Any]]]:
        return self._traffic._build_query_actors(actor_list, scope_labels=scope_labels)

    def _build_query_services(self, rule: dict[str, Any]) -> list[dict[str, Any]]:
        return self._traffic._build_query_services(rule)

    def _build_rule_query_payload(self, rule: dict[str, Any], start_date: str, end_date: str) -> dict[str, Any] | None:
        return self._traffic._build_rule_query_payload(rule, start_date, end_date)

    def get_rule_traffic_count(self, rule: dict[str, Any], start_date: str, end_date: str) -> int:
        return self._traffic.get_rule_traffic_count(rule, start_date, end_date)

    def batch_get_rule_traffic_counts(self, rules: list[dict[str, Any]], start_date: str, end_date: str, max_concurrent: int = 10, on_progress: Any = None) -> tuple[set[str], dict[str, int]]:
        return self._traffic.batch_get_rule_traffic_counts(
            rules, start_date, end_date,
            max_concurrent=max_concurrent,
            on_progress=on_progress,
        )

    def export_traffic_query_csv(
        self,
        start_time_str: str,
        end_time_str: str,
        policy_decisions: list[str] | None = None,
        filters: Any = None,
        output_dir: str = "reports",
        filename: str | None = None,
        compute_draft: bool = False,
    ) -> dict[str, Any]:
        return self._traffic.export_traffic_query_csv(
            start_time_str,
            end_time_str,
            policy_decisions=policy_decisions,
            filters=filters,
            output_dir=output_dir,
            filename=filename,
            compute_draft=compute_draft,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # AsyncJobManager delegation wrappers
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _utc_now_iso() -> str:
        return AsyncJobManager._utc_now_iso()

    def _save_async_job_state(self, job_href: str, **fields: Any) -> None:
        return self._jobs._save_async_job_state(job_href, **fields)

    @staticmethod
    def _make_query_signature(payload: dict[str, Any] | None) -> str:
        return AsyncJobManager._make_query_signature(payload)

    @staticmethod
    def _job_timestamp_epoch(job: dict[str, Any]) -> float:
        return AsyncJobManager._job_timestamp_epoch(job)

    def _load_async_job_states(self) -> dict[str, Any]:
        return self._jobs._load_async_job_states()

    def _job_age_seconds(self, job: dict[str, Any]) -> float:
        return self._jobs._job_age_seconds(job)

    def _job_is_stale(self, job: dict[str, Any], max_age_days: float | None = None) -> bool:
        return self._jobs._job_is_stale(job, max_age_days=max_age_days)

    def _maybe_prune_async_job_states(self) -> None:
        return self._jobs._maybe_prune_async_job_states()

    def find_cached_async_summary(self, payload: dict[str, Any], query_type: str = "rule_usage") -> dict[str, Any] | None:
        return self._jobs.find_cached_async_summary(payload, query_type=query_type)

    def find_latest_async_job(self, payload: dict[str, Any], query_type: str = "rule_usage") -> dict[str, Any] | None:
        return self._jobs.find_latest_async_job(payload, query_type=query_type)

    def resume_async_query_job(self, job_href: str, timeout: int = 120, summarize: bool = False, compute_draft: bool = False) -> dict[str, Any]:
        return self._jobs.resume_async_query_job(
            job_href, timeout=timeout, summarize=summarize, compute_draft=compute_draft
        )

    def retry_async_query_job(self, job_href: str) -> str:
        return self._jobs.retry_async_query_job(job_href)

    def prune_async_job_states(self, max_age_days: int = 7, keep_recent_completed: int = 200) -> dict[str, int]:
        return self._jobs.prune_async_job_states(
            max_age_days=max_age_days, keep_recent_completed=keep_recent_completed
        )

    def submit_async_query(self, payload: dict[str, Any], query_type: str = "rule_usage") -> str | None:
        return self._jobs.submit_async_query(payload, query_type=query_type)

    def _wait_for_async_query(self, job_href: str, timeout: int = 120, compute_draft: bool = False) -> dict[str, Any]:
        return self._jobs._wait_for_async_query(job_href, timeout=timeout, compute_draft=compute_draft)

    def poll_async_query(self, job_href: str, timeout: int = 120) -> bool:
        return self._jobs.poll_async_query(job_href, timeout=timeout)

    def iter_async_query_results(self, job_href: str) -> Iterator[dict[str, Any]]:
        yield from self._jobs.iter_async_query_results(job_href)

    def summarize_async_query(self, job_href: str) -> dict[str, Any]:
        return self._jobs.summarize_async_query(job_href)

    def download_async_query(self, job_href: str) -> list[dict[str, Any]]:
        return self._jobs.download_async_query(job_href)

    def download_async_query_csv(self, job_href: str, include_draft_policy: bool = False) -> dict[str, Any]:
        return self._jobs.download_async_query_csv(job_href, include_draft_policy=include_draft_policy)

    # ═══════════════════════════════════════════════════════════════════════
    # Quarantine Feature: Labels and Workloads
    # ═══════════════════════════════════════════════════════════════════════

    def get_labels(self, key: str) -> list:
        try:
            params = urllib.parse.urlencode({"key": key})
            url = f"{self.base_url}/labels?{params}"
            status, body = self._request(url, timeout=10)
            if status != 200:
                logger.error(f"Get Labels Failed: {status}")
                return []
            return orjson.loads(body)
        except Exception as e:
            logger.error(f"Fetch Labels Error: {e}")
            return []

    def get_all_labels(self, raise_on_error: bool = False) -> list[dict[str, Any]]:
        """Get every label across all dimensions (unscoped by key).

        Unlike get_labels(key) which filters one dimension, this returns all
        labels including custom dimensions (e.g. Net=) for the filter-object
        suggest cache. Returns [] on error.

        raise_on_error=True：非 200（含 status 0 連線層失敗）raise APIError，
        供 policy diff/resolver 等消費端區分「PCE 故障」與「合法空 org」。
        預設 False 維持既有呼叫者行為不變。
        """
        org = self.api_cfg['org_id']
        path = f"/orgs/{org}/labels"
        status, data, _total = self._get_collection(path)
        if status == 200 and data:
            return data
        if raise_on_error and status != 200:
            raise APIError(f"get_all_labels failed: HTTP {status} for {path}")
        logger.warning(f"get_all_labels: status={status}, returned empty list")
        return []

    def create_label(self, key: str, value: str) -> dict:
        try:
            url = f"{self.base_url}/labels"
            payload = {"key": key, "value": value}
            status, body = self._request(url, method="POST", data=payload, timeout=10)
            if status == 201:
                return orjson.loads(body)
            logger.error(f"Create Label Failed: {status} - {body.decode(errors='replace')}")
            return {}
        except Exception as e:
            logger.error(f"Create Label Error: {e}")
            return {}

    def check_and_create_quarantine_labels(self) -> dict[str, str]:
        """Ensure Quarantine labels (Mild, Moderate, Severe) exist in the PCE. Returns list of their hrefs."""
        existing_labels = self.get_labels("Quarantine")
        existing_values = {lbl.get("value"): lbl.get("href") for lbl in existing_labels if lbl.get("value")}

        target_levels = ["Mild", "Moderate", "Severe"]
        label_hrefs = {}
        for level in target_levels:
            if level in existing_values:
                label_hrefs[level] = existing_values[level]
            else:
                logger.info(f"Creating missing Quarantine label: {level}")
                new_lbl = self.create_label("Quarantine", level)
                if new_lbl and "href" in new_lbl:
                    label_hrefs[level] = new_lbl["href"]
        return label_hrefs

    def get_workload(self, href: str) -> dict:
        """Fetch a specific workload by its href"""
        try:
            url = f"{self.api_cfg['url']}/api/v2{href}"
            status, body = self._request(url, timeout=10)
            if status == 200:
                return orjson.loads(body)
            logger.error(f"Get Workload Failed: {status} for {href}")
            return {}
        except Exception as e:
            logger.error(f"Get Workload Error: {e}")
            return {}

    def get_workload_risk_details(self, href: str) -> dict:
        """Fetch a workload's ransomware risk details. Returns {} on error.

        GET /api/v2{href}/risk_details — payload is
        ``{"risk_details": {"ransomware": {"details": [...], ...} | null}}``.
        """
        try:
            url = f"{self.api_cfg['url']}/api/v2{href}/risk_details"
            status, body = self._request(url, timeout=10)
            if status == 200:
                return orjson.loads(body)
            logger.error(f"Get Workload Risk Details Failed: {status} for {href}")
            return {}
        except Exception as e:
            logger.error(f"Get Workload Risk Details Error: {e}")
            return {}

    def update_workload_labels(self, href: str, labels: list) -> bool:
        """Update a workload's labels. labels list should contain dicts with 'href' keys."""
        try:
            url = f"{self.api_cfg['url']}/api/v2{href}"
            payload = {"labels": labels}
            status, body = self._request(url, method="PUT", data=payload, timeout=10)
            if status == 204:
                return True
            logger.error(f"Update Workload Labels Failed: {status} - {body.decode(errors='replace')}")
            return False
        except Exception as e:
            logger.error(f"Update Workload Labels Error: {e}")
            return False

    def fetch_managed_workloads(self, max_results: int = 10000,
                                raise_on_error: bool = False) -> list:
        """Fetch all VEN-managed workloads (those with an active VEN agent).

        max_results 參數保留供呼叫端相容，但集合 GET 一律經 _get_collection
        套用 PCE 硬上限 500（帶更大的值本來就無效、還會掩蓋截斷）。

        raise_on_error=True：非 200（含連線層失敗）raise APIError，供 VEN
        summary 等消費端區分「PCE 故障」與「合法空集合」（否則 0/0 會被
        當成真相寫進 dashboard）。預設 False 維持既有呼叫者行為。
        """
        try:
            org = self.api_cfg['org_id']
            status, data, _total = self._get_collection(f"/orgs/{org}/workloads?managed=true", timeout=30)
            if status == 200:
                return data
            logger.error(f"Fetch Managed Workloads Failed: {status}")
            if raise_on_error:
                raise APIError(f"fetch_managed_workloads failed: HTTP {status}")
            return []
        except APIError:
            raise
        except Exception as e:
            logger.error(f"Fetch Managed Workloads Error: {e}")
            if raise_on_error:
                raise APIError(f"fetch_managed_workloads failed: {e}") from e
            return []

    def search_workloads(self, params: dict) -> list:
        """Search workloads matching query params (e.g., name, hostname, ip_address, labels)"""
        try:
            query_str = urllib.parse.urlencode(params, doseq=True)
            url = f"{self.base_url}/workloads?{query_str}"
            status, body = self._request(url, timeout=15)
            if status == 200:
                return orjson.loads(body)
            logger.error(f"Search Workloads Failed: {status}")
            return []
        except Exception as e:
            logger.error(f"Search Workloads Error: {e}")
            return []

    def set_flow_reporting_frequency(self, hrefs: list[str]) -> tuple[int, int]:
        """Increase traffic update rate (a.k.a. flow reporting frequency) for
        the given workload hrefs.

        PCE caps each request at 50 workloads, so we auto-batch.
        Returns (success_count, fail_count) by batch size.
        Effect on PCE is temporary (~10 min); caller must re-issue to sustain.
        """
        if not hrefs:
            return 0, 0
        org = self.api_cfg["org_id"]
        endpoint = f"/orgs/{org}/workloads/set_flow_reporting_frequency"
        success = 0
        fail = 0
        for i in range(0, len(hrefs), 50):
            batch = hrefs[i:i + 50]
            payload = {"workloads": [{"href": h} for h in batch]}
            try:
                status, _ = self._api_post(endpoint, payload, timeout=15)
                if status in (200, 201, 204):
                    success += len(batch)
                else:
                    fail += len(batch)
                    logger.error(
                        f"set_flow_reporting_frequency batch failed: status={status}"
                    )
            except Exception as e:
                fail += len(batch)
                logger.error(f"set_flow_reporting_frequency batch error: {e}")
        return success, fail

    # ═══════════════════════════════════════════════════════════════════════
    # Rule Scheduler Features: RuleSet/Rule management, provisioning, notes
    # ═══════════════════════════════════════════════════════════════════════

    def _api_get(self, endpoint: str, timeout: int = 15) -> tuple[int, Any]:
        """GET a PCE API endpoint. Returns (status_code, parsed_json_or_None)."""
        url = f"{self.api_cfg['url']}/api/v2{endpoint}"
        try:
            status, body = self._request(url, timeout=timeout)
            if status == 200:
                return status, orjson.loads(body)
            if status == 204:
                return status, {}
            return status, None
        except Exception as e:
            logger.error(f"API GET {endpoint}: {e}")
            return 0, None

    def _api_get_with_headers(self, endpoint: str, timeout: int = 15, headers: dict[str, str] | None = None) -> tuple[int, Any, dict]:
        """GET a PCE API endpoint，回傳連 headers 一起（供 _get_collection 讀 X-Total-Count）。

        不透過 _request（其簽名回 (status, body) 丟棄 headers、呼叫點太多不便改），
        直接用 self._session；錯誤處理比照 _request：連線例外回 (0, err_bytes, {})。

        headers：額外請求 headers（Task 2 用來帶 Prefer: respond-async 觸發
        async GET fallback）；預設 None，行為與 Task 1 完全相同。
        """
        if self._session is None:
            raise RuntimeError("ApiClient is closed; create a new instance")
        url = f"{self.api_cfg['url']}/api/v2{endpoint}"
        try:
            resp = self._session.request(method="GET", url=url, timeout=timeout, headers=headers)
        except Exception as e:
            logger.error(f"API GET {endpoint}: {e}")
            return 0, str(e).encode('utf-8'), {}
        if resp.status_code == 200:
            try:
                return resp.status_code, orjson.loads(resp.content), resp.headers
            except Exception as e:
                # body 非合法 JSON：比照 _api_get 的錯誤契約回 (0, None, {})，
                # 避免例外炸穿到沒有 try/except 的 getter 呼叫端
                logger.error(f"API GET {endpoint}: {e}")
                return 0, None, {}
        if resp.status_code == 204:
            return resp.status_code, {}, resp.headers
        return resp.status_code, None, resp.headers

    def _get_collection(self, path: str, *, timeout: int = 15) -> tuple[int, Any, int | None]:
        """同步集合 GET：max_results 一律用 PCE 硬上限 500（帶 10000 沒有意義，
        且會掩蓋截斷）；path 由呼叫者帶好其餘 query string，這裡負責附加 max_results。

        回傳 (status, data, total_count)：total_count 取自 X-Total-Count header
        （無此 header 時 None）。當 total_count > 實收筆數時視為截斷，記錄到
        self.last_truncated_collections 供後續（Task 2）消費。
        """
        sep = "&" if "?" in path else "?"
        status, data, headers = self._api_get_with_headers(f"{path}{sep}max_results=500", timeout=timeout)

        total_count: int | None = None
        if headers:
            for key, val in headers.items():
                if key.lower() == "x-total-count":
                    try:
                        total_count = int(val)
                    except (TypeError, ValueError):
                        total_count = None
                    break

        actual_count = len(data) if isinstance(data, list) else 0
        # 截斷只可能發生在 max_results=500 上限處。帶 query filter 的路徑
        # （如 workloads?managed=true）X-Total-Count 回的是「未過濾」總數
        # （PCE 25.2.40 真機實測：20 列 managed、header 30）——actual < 500
        # 且 total > actual 是 filter 語意差異、不是截斷，觸發 fallback 會
        # 造成假陽性：每次呼叫多打一個 PCE async job、多等 2s、留永久假紀錄。
        if status == 200 and total_count is not None and actual_count >= 500 and total_count > actual_count:
            logger.error(
                "collection GET truncated: {} returned {}/{} objects",
                path, actual_count, total_count,
            )
            # Task 2：截斷時自動改走官方 async GET 流程取回完整集合。async GET
            # 回傳的是套用同一 query filter 的完整結果集，其筆數在帶 filter 的
            # 路徑上可能遠低於未過濾的 X-Total-Count——恢復判準用「比截斷頁拿
            # 到更多」；失敗則維持 Task 1 的截斷資料與 error log 語意
            # （永不比 Task 1 差）。
            fallback_data = self._cached_async_collection_get(path, timeout=timeout)
            if fallback_data is not None and len(fallback_data) > actual_count:
                logger.info(
                    "async GET fallback recovered collection: {} returned {}/{} objects",
                    path, len(fallback_data), total_count,
                )
                # 跨呼叫先失敗後成功：清除先前殘留的截斷紀錄，避免假陽性永久殘留
                if path in self.last_truncated_collections:
                    self.last_truncated_collections.remove(path)
                try:
                    from src.data_integrity import clear_truncation
                    clear_truncation(path)
                except Exception:
                    pass  # 遙測失敗不得影響 API 主路徑
                return status, fallback_data, total_count
            # 去重：同一 path 因排程重複呼叫且反覆截斷失敗時，避免
            # last_truncated_collections 無上限纍積（Task 1 遺留的 append-only 問題）。
            if path not in self.last_truncated_collections:
                self.last_truncated_collections.append(path)
            try:
                from src.data_integrity import record_truncation
                record_truncation(path, actual_count, total_count)
            except Exception:
                pass  # 遙測失敗不得影響 API 主路徑

        return status, data, total_count

    def _cached_async_collection_get(self, path: str, *, timeout: int = 15) -> list[Any] | None:
        """_async_collection_get 的 process 級 memo/退避包裝。

        成功結果按 path memo（TTL 5 分鐘）：每請求新建 ApiClient 的 GUI 路由
        在集合真 >500 時，不會每個請求都對 PCE 提交一個 async job。失敗按
        path 退避（10 分鐘）：fallback 持續失敗時不反覆打 job＋等輪詢，直接
        沿用截斷資料（呼叫端語意不變：回 None 即 fallback 失敗）。
        併發下同 path 可能偶發重複提交（無 single-flight），穩態成本已由
        memo/退避封頂，不值得加鎖等待。
        """
        now = time.monotonic()
        with _ASYNC_FALLBACK_LOCK:
            memo = _ASYNC_FALLBACK_MEMO.get(path)
            if memo and now - memo[0] < _ASYNC_FALLBACK_MEMO_TTL_SECONDS:
                return memo[1]
            failed_at = _ASYNC_FALLBACK_FAILED_AT.get(path)
            if failed_at is not None and now - failed_at < _ASYNC_FALLBACK_FAILURE_BACKOFF_SECONDS:
                logger.debug(
                    "async collection GET fallback suppressed (failure backoff): {}", path
                )
                return None
        data = self._async_collection_get(path, timeout=timeout)
        with _ASYNC_FALLBACK_LOCK:
            if data is not None:
                _ASYNC_FALLBACK_MEMO[path] = (time.monotonic(), data)
                _ASYNC_FALLBACK_FAILED_AT.pop(path, None)
            else:
                _ASYNC_FALLBACK_FAILED_AT[path] = time.monotonic()
        return data

    def _async_collection_get(self, path: str, *, timeout: int = 15) -> list[Any] | None:
        """集合 GET 截斷時的官方 async GET fallback（vendor 已驗證流程）。

        1. 對同一 path 發 GET，headers 帶 ``Prefer: respond-async``，預期
           202 且回應 headers 含 Location（job href）與 Retry-After。
        2. 輪詢 ``GET /api/v2{job_href}``（複用 _api_get_with_headers）直到
           body ``status == "done"``（Jobs API 用 done，不是 completed——
           本專案既有 vendor 事實）；failed 或超過 300s 回 None。輪詢間隔
           從 Retry-After 或 2s 起，夾在 [2, 10] 秒之間。
        3. done 後從 body ``result.href`` 取得 datafile href，下載完整
           JSON 陣列並回傳。

        任何一步失敗都回 None；呼叫端（_get_collection）自行決定 fallback
        失敗時要不要維持截斷資料。
        """
        status, _data, headers = self._api_get_with_headers(
            path, timeout=timeout, headers={"Prefer": "respond-async"}
        )
        if status != 202:
            logger.error(
                "async collection GET fallback: expected 202 (respond-async), got {} for {}",
                status, path,
            )
            return None

        job_href = (headers or {}).get("Location")
        if not job_href:
            logger.error(
                "async collection GET fallback: 202 response missing Location header for {}",
                path,
            )
            return None

        retry_after_raw = (headers or {}).get("Retry-After")
        try:
            poll_interval = float(retry_after_raw) if retry_after_raw else 2.0
        except (TypeError, ValueError):
            poll_interval = 2.0
        poll_interval = min(max(poll_interval, 2.0), 10.0)

        deadline = time.time() + 300
        job_body: dict[str, Any] | None = None
        while time.time() < deadline:
            time.sleep(poll_interval)
            poll_status, poll_data, _poll_headers = self._api_get_with_headers(job_href, timeout=timeout)
            if poll_status != 200 or not isinstance(poll_data, dict):
                continue
            state = poll_data.get("status")
            if state == "done":
                job_body = poll_data
                break
            if state in ("failed", "cancel_requested", "cancelled", "canceled"):
                logger.error(
                    "async collection GET fallback: job {} reported {} for {}",
                    job_href, state, path,
                )
                return None
            # running/queued 等其他狀態繼續輪詢

        if job_body is None:
            logger.error(
                "async collection GET fallback: job {} did not complete within 300s for {}",
                job_href, path,
            )
            return None

        result_href = (job_body.get("result") or {}).get("href")
        if not result_href:
            logger.error(
                "async collection GET fallback: done job {} missing result.href for {}",
                job_href, path,
            )
            return None

        dl_status, dl_data, _dl_headers = self._api_get_with_headers(result_href, timeout=timeout)
        if dl_status != 200 or not isinstance(dl_data, list):
            logger.error(
                "async collection GET fallback: datafile download failed status={} for {}",
                dl_status, path,
            )
            return None

        return dl_data

    def _api_put(self, endpoint: str, payload: dict[str, Any], timeout: int = 15) -> int:
        """PUT a PCE API endpoint. Returns status_code."""
        url = f"{self.api_cfg['url']}/api/v2{endpoint}"
        try:
            status, body = self._request(url, method="PUT", data=payload, timeout=timeout)
            return status
        except Exception as e:
            logger.error(f"API PUT {endpoint}: {e}")
            return 0

    def _api_post(self, endpoint: str, payload: dict[str, Any], timeout: int = 15) -> tuple[int, Any]:
        """POST a PCE API endpoint. Returns (status_code, parsed_json_or_None)."""
        url = f"{self.api_cfg['url']}/api/v2{endpoint}"
        try:
            status, body = self._request(url, method="POST", data=payload, timeout=timeout)
            if status in (200, 201):
                return status, orjson.loads(body) if body else {}
            return status, None
        except Exception as e:
            logger.error(f"API POST {endpoint}: {e}")
            return 0, None

    def get_all_rulesets(self, force_refresh: bool = False,
                         raise_on_error: bool = False) -> list[dict[str, Any]]:
        """Get all rulesets from PCE (cached unless force_refresh).

        raise_on_error=True: any non-200 (incl. status 0 = connection-layer
        failure per _request) raises RuntimeError instead of silently
        returning [] — opt-in for callers that must distinguish fetch failure
        from a legitimately empty org (rule hit count enrich_failed signal,
        real-PCE verified 2026-07-11). Default False keeps the legacy
        empty-list contract for all existing callers.
        """
        if self.ruleset_cache and not force_refresh:
            return self.ruleset_cache
        org = self.api_cfg['org_id']
        status, data, _total = self._get_collection(f"/orgs/{org}/sec_policy/draft/rule_sets")
        if status == 200 and data:
            self.ruleset_cache = data
            return self.ruleset_cache
        if raise_on_error and status != 200:
            raise RuntimeError(f"get_all_rulesets failed: HTTP {status}")
        return []

    def get_active_rulesets(self, raise_on_error: bool = False) -> list[dict[str, Any]]:
        """Get all active (provisioned) rulesets with their rules.

        raise_on_error=True：非 200（含 status 0 連線層失敗）raise APIError，
        供 policy diff/resolver 等消費端區分「PCE 故障」與「合法空 org」。
        預設 False 維持既有呼叫者行為不變。
        """
        org = self.api_cfg['org_id']
        path = f"/orgs/{org}/sec_policy/active/rule_sets"
        status, data, _total = self._get_collection(path)
        if status == 200 and data:
            return data
        if raise_on_error and status != 200:
            raise APIError(f"get_active_rulesets failed: HTTP {status} for {path}")
        logger.warning(f"get_active_rulesets: status={status}, returned empty list")
        return []

    def get_ip_lists(self, pversion: str = "active", raise_on_error: bool = False) -> list[dict[str, Any]]:
        """Get all IP Lists with their ip_ranges/fqdns.

        Default ACTIVE so returned hrefs (/sec_policy/active/ip_lists/...)
        match actor references inside active rulesets; pass pversion="draft"
        for the draft-side inventory (policy diff).

        raise_on_error=True：非 200（含 status 0 連線層失敗）raise APIError。
        預設 False 維持既有呼叫者行為不變。
        """
        if pversion not in ("active", "draft"):
            raise ValueError(f"pversion must be 'active' or 'draft', got {pversion!r}")
        org = self.api_cfg['org_id']
        path = f"/orgs/{org}/sec_policy/{pversion}/ip_lists"
        status, data, _total = self._get_collection(path)
        if status == 200 and data:
            return data
        if raise_on_error and status != 200:
            raise APIError(f"get_ip_lists failed: HTTP {status} for {path}")
        logger.warning(f"get_ip_lists: status={status}, returned empty list")
        return []

    def get_label_groups(self, pversion: str = "active", raise_on_error: bool = False) -> list[dict[str, Any]]:
        """Get all Label Groups with their member labels + sub_groups.

        Default ACTIVE so hrefs align with active-ruleset actor references;
        pass pversion="draft" for the draft-side inventory (policy diff).

        raise_on_error=True：非 200（含 status 0 連線層失敗）raise APIError。
        預設 False 維持既有呼叫者行為不變。
        """
        if pversion not in ("active", "draft"):
            raise ValueError(f"pversion must be 'active' or 'draft', got {pversion!r}")
        org = self.api_cfg['org_id']
        path = f"/orgs/{org}/sec_policy/{pversion}/label_groups"
        status, data, _total = self._get_collection(path)
        if status == 200 and data:
            return data
        if raise_on_error and status != 200:
            raise APIError(f"get_label_groups failed: HTTP {status} for {path}")
        logger.warning(f"get_label_groups: status={status}, returned empty list")
        return []

    def get_services(self, pversion: str = "active", raise_on_error: bool = False) -> list[dict[str, Any]]:
        """Get all Service definitions with their service_ports.

        Default ACTIVE so hrefs align with active-ruleset ingress_services
        references; pass pversion="draft" for the draft-side inventory (policy diff).

        raise_on_error=True：非 200（含 status 0 連線層失敗）raise APIError。
        預設 False 維持既有呼叫者行為不變。
        """
        if pversion not in ("active", "draft"):
            raise ValueError(f"pversion must be 'active' or 'draft', got {pversion!r}")
        org = self.api_cfg['org_id']
        path = f"/orgs/{org}/sec_policy/{pversion}/services"
        status, data, _total = self._get_collection(path)
        if status == 200 and data:
            return data
        if raise_on_error and status != 200:
            raise APIError(f"get_services failed: HTTP {status} for {path}")
        logger.warning(f"get_services: status={status}, returned empty list")
        return []

    def search_rulesets(self, keyword: str) -> list[dict[str, Any]]:
        """Search cached rulesets by keyword."""
        all_rs = self.get_all_rulesets()
        return [rs for rs in all_rs if keyword.lower() in rs.get('name', '').lower()]

    def get_ruleset_by_id(self, rs_id: str | int) -> dict[str, Any] | None:
        """Get a single ruleset by ID."""
        org = self.api_cfg['org_id']
        status, data = self._api_get(f"/orgs/{org}/sec_policy/draft/rule_sets/{rs_id}")
        return data if status == 200 else None

    def provision_changes(self, rs_href: str) -> bool:
        """Dependency-aware provisioning: discovers required dependencies first."""
        org = self.api_cfg['org_id']

        # Step 1: Check dependencies
        dep_payload = {"change_subset": {"rule_sets": [{"href": rs_href}]}}
        dep_status, deps = self._api_post(f"/orgs/{org}/sec_policy/draft/dependencies", dep_payload)

        # Step 2: Build complete change_subset including all dependencies
        final_subset = {"rule_sets": [{"href": rs_href}]}

        if dep_status == 200 and deps:
            for obj_type in ['rule_sets', 'ip_lists', 'services', 'label_groups',
                             'virtual_services', 'firewall_settings', 'enforcement_boundaries',
                             'virtual_servers', 'secure_connect_gateways']:
                dep_items = deps.get(obj_type, [])
                if dep_items:
                    existing = final_subset.get(obj_type, [])
                    existing_hrefs = {item['href'] for item in existing}
                    for item in dep_items:
                        if item.get('href') and item['href'] not in existing_hrefs:
                            existing.append({"href": item['href']})
                    final_subset[obj_type] = existing

        # Step 3: Provision with full dependency set
        payload = {
            "update_description": "Auto-Scheduler: Status/Note Update",
            "change_subset": final_subset
        }
        prov_status, _ = self._api_post(f"/orgs/{org}/sec_policy", payload)
        if prov_status == 201:
            return True
        logger.error(f"Provision failed for RuleSet {_extract_id(rs_href)}: status {prov_status}")
        return False

    def pull_rule_hit_count_report(self, **kwargs: Any) -> str:
        """Delegates to ReportsApi — native Rule Hit Count report pull."""
        return self._reports.pull_rule_hit_count_report(**kwargs)

    def has_draft_changes(self, href: str) -> bool:
        """Check if an item OR its parent RuleSet has pending draft changes."""
        draft_href = href.replace("/active/", "/draft/")
        status, data = self._api_get(draft_href)
        if status == 200 and data and bool(data.get('update_type')):
            return True
        if "/sec_rules/" in draft_href:
            parent_href = draft_href.split("/sec_rules/")[0]
            status_p, data_p = self._api_get(parent_href)
            if status_p == 200 and data_p and bool(data_p.get('update_type')):
                return True
        return False

    def toggle_and_provision(self, href: str, target_enabled: bool, is_ruleset: bool = False) -> bool:
        """Enable/disable a rule or ruleset and provision the change."""
        draft_href = href.replace("/active/", "/draft/")

        if self.has_draft_changes(draft_href):
            logger.warning(f"toggle_and_provision aborted: {_extract_id(href)} has pending draft changes.")
            return False

        put_status = self._api_put(draft_href, {"enabled": target_enabled})
        if put_status != 204:
            logger.error(f"Toggle failed for {_extract_id(href)}: status {put_status}")
            return False
        rs_href = draft_href if is_ruleset else "/".join(draft_href.split("/")[:7])
        return self.provision_changes(rs_href)

    def update_rule_note(self, href: str, schedule_info: str, remove: bool = False) -> bool:
        """Add/update/remove schedule tags in a rule's description field on the PCE."""
        draft_href = href.replace("/active/", "/draft/")
        status, data = self._api_get(draft_href)
        if status != 200 or not data:
            return False

        has_pending_draft = self.has_draft_changes(draft_href)

        current_desc = data.get('description', '') or ''

        # Strip existing schedule tags — 前綴三種都要認：行事曆（recurring，
        # GUI/CLI 共用）、沙漏（CLI one_time）、鬧鐘（GUI one_time，
        # src/gui/routes/rule_scheduler.py）。漏認任何一種＝該來源建立的
        # 註記刪除/到期都清不掉，永久殘留在 PCE description。
        clean_desc = re.sub(r'\s*\[📅[^\]]*\]', '', current_desc)
        clean_desc = re.sub(r'\s*\[⏳[^\]]*\]', '', clean_desc)
        clean_desc = re.sub(r'\s*\[⏰[^\]]*\]', '', clean_desc)
        clean_desc = clean_desc.strip()

        new_desc = clean_desc
        if not remove:
            new_desc = f"{clean_desc}\n{schedule_info}".strip() if clean_desc else schedule_info

        if new_desc == current_desc:
            return True

        put_status = self._api_put(draft_href, {"description": new_desc})
        if put_status == 204:
            if not has_pending_draft:
                rs_href = "/".join(draft_href.split("/")[:7])
                return self.provision_changes(rs_href)
            return True
        return False

    def get_live_item(self, href: str) -> tuple[int, Any]:
        """Try both active and draft paths to find the item."""
        active_href = href.replace("/draft/", "/active/")
        status, data = self._api_get(active_href)
        if status == 200:
            return status, data
        draft_href = href.replace("/active/", "/draft/")
        if draft_href != active_href:
            status, data = self._api_get(draft_href)
            if status == 200:
                return status, data
        return status, data

    def get_provision_state(self, href: str) -> str:
        """Check provision state: 'active' if provisioned, 'draft' if draft-only, 'unknown' on error."""
        active_href = href.replace("/draft/", "/active/")
        url = f"{self.api_cfg['url']}/api/v2{active_href}"
        try:
            status, body = self._request(url, timeout=10)
            if status == 200:
                return 'active'
            return 'draft'
        except Exception as exc:
            logger.debug("Could not determine provision state for {}: {}", href, exc)
            return 'unknown'

    def is_provisioned(self, href: str) -> bool:
        """Check if a rule/ruleset has been provisioned."""
        return self.get_provision_state(href) == 'active'


_HEALTH_BAD_ORDER = ("critical", "error", "degraded", "warning")


def health_status_from_body(text: str) -> str:
    """Extract the PCE health status string from a /api/v2/health body.

    The endpoint returns HTTP 200 whenever it can report at all, so the body
    status is the only truthful health signal. Returns '' when unparseable —
    callers must treat '' as unknown, never as healthy.
    """
    import json as _json
    try:
        data = _json.loads(text)
    except (ValueError, TypeError):
        return ""
    if isinstance(data, dict):
        return str(data.get("status") or "").strip().lower()
    if isinstance(data, list):
        statuses = [
            str(node.get("status") or "").strip().lower()
            for node in data if isinstance(node, dict)
        ]
        statuses = [s for s in statuses if s]
        for bad in _HEALTH_BAD_ORDER:
            if bad in statuses:
                return bad
        return statuses[0] if statuses else ""
    return ""


__all__ = [
    "ApiClient",
    "EventFetchError",
    "TrafficQuerySpec",
    "MAX_TRAFFIC_RESULTS",
    "MAX_RETRIES",
    "health_status_from_body",
]
