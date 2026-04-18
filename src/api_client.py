import json
import orjson
import os
import re
import time
import gzip
import base64
import datetime
import ipaddress
import logging
import threading
import urllib.parse
from dataclasses import dataclass, field
from io import BytesIO
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cachetools import TTLCache
from src.utils import Colors
from src.i18n import t
from src.state_store import load_state_file, update_state_file

logger = logging.getLogger(__name__)

MAX_TRAFFIC_RESULTS = 200000
MAX_RETRIES = 3
_ASYNC_JOB_STATE_KEY = "async_query_jobs"
_QUERY_LOOKUP_CACHE_TTL_SECONDS = 300
_LABEL_CACHE_TTL_SECONDS = 900  # 15 minutes — Phase 2 Q5 fix
_ASYNC_JOB_CACHE_MAX_AGE_DAYS = 7
_ASYNC_JOB_PRUNE_INTERVAL_SECONDS = 3600
_TRAFFIC_FILTER_CAPABILITIES = {
    "src_label": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label href and pushed to sources.include."},
    "src_labels": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label hrefs and pushed to sources.include."},
    "dst_label": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label href and pushed to destinations.include."},
    "dst_labels": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label hrefs and pushed to destinations.include."},
    "src_ip_in": {"execution": "native", "min_pce_version": "21.2", "notes": "Supports IP literal, workload href, or IP list href/name."},
    "src_ip": {"execution": "native", "min_pce_version": "21.2", "notes": "Supports IP literal, workload href, or IP list href/name."},
    "dst_ip_in": {"execution": "native", "min_pce_version": "21.2", "notes": "Supports IP literal, workload href, or IP list href/name."},
    "dst_ip": {"execution": "native", "min_pce_version": "21.2", "notes": "Supports IP literal, workload href, or IP list href/name."},
    "ex_src_label": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label href and pushed to sources.exclude."},
    "ex_src_labels": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label hrefs and pushed to sources.exclude."},
    "ex_dst_label": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label href and pushed to destinations.exclude."},
    "ex_dst_labels": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label hrefs and pushed to destinations.exclude."},
    "ex_src_ip": {"execution": "native", "min_pce_version": "21.2", "notes": "Supports IP literal, workload href, or IP list href/name."},
    "ex_dst_ip": {"execution": "native", "min_pce_version": "21.2", "notes": "Supports IP literal, workload href, or IP list href/name."},
    "port": {"execution": "native", "min_pce_version": "21.2", "notes": "Pushed to services.include."},
    "proto": {"execution": "native", "min_pce_version": "21.2", "notes": "Combined with port or port range in services.include."},
    "ex_port": {"execution": "native", "min_pce_version": "21.2", "notes": "Pushed to services.exclude."},
    "port_range": {"execution": "native", "min_pce_version": "21.2", "notes": "Single port range expression for services.include."},
    "port_ranges": {"execution": "native", "min_pce_version": "21.2", "notes": "Multiple port range expressions for services.include."},
    "ex_port_range": {"execution": "native", "min_pce_version": "21.2", "notes": "Single port range expression for services.exclude."},
    "ex_port_ranges": {"execution": "native", "min_pce_version": "21.2", "notes": "Multiple port range expressions for services.exclude."},
    "process_name": {"execution": "native", "min_pce_version": "21.2", "notes": "Pushed to services.include process_name."},
    "windows_service_name": {"execution": "native", "min_pce_version": "21.2", "notes": "Pushed to services.include windows_service_name."},
    "ex_process_name": {"execution": "native", "min_pce_version": "21.2", "notes": "Pushed to services.exclude process_name."},
    "ex_windows_service_name": {"execution": "native", "min_pce_version": "21.2", "notes": "Pushed to services.exclude windows_service_name."},
    "query_operator": {"execution": "native", "min_pce_version": "21.2", "notes": "Mapped to sources_destinations_query_op."},
    "exclude_workloads_from_ip_list_query": {"execution": "native", "min_pce_version": "21.2", "notes": "Pushed directly into async query payload."},
    "src_ams": {"execution": "native", "min_pce_version": "21.2", "notes": "Adds actors:ams to sources.include."},
    "dst_ams": {"execution": "native", "min_pce_version": "21.2", "notes": "Adds actors:ams to destinations.include."},
    "ex_src_ams": {"execution": "native", "min_pce_version": "21.2", "notes": "Adds actors:ams to sources.exclude."},
    "ex_dst_ams": {"execution": "native", "min_pce_version": "21.2", "notes": "Adds actors:ams to destinations.exclude."},
    "transmission_excludes": {"execution": "native", "min_pce_version": "21.2", "notes": "Mapped to destinations.exclude transmission entries."},
    "ex_transmission": {"execution": "native", "min_pce_version": "21.2", "notes": "Mapped to destinations.exclude transmission entries."},
    "src_include_groups": {"execution": "native", "min_pce_version": "21.2", "notes": "Supports OR-of-AND actor groups on source side."},
    "dst_include_groups": {"execution": "native", "min_pce_version": "21.2", "notes": "Supports OR-of-AND actor groups on destination side."},
    "any_label": {"execution": "fallback", "notes": "Either-side semantics require client-side filtering."},
    "any_ip": {"execution": "fallback", "notes": "Either-side semantics require client-side filtering."},
    "ex_any_label": {"execution": "fallback", "notes": "Either-side exclusion requires client-side filtering."},
    "ex_any_ip": {"execution": "fallback", "notes": "Either-side exclusion requires client-side filtering."},
    "search": {"execution": "report_only", "notes": "Full-text matching is applied after flows are fetched."},
    "sort_by": {"execution": "report_only", "notes": "Sorting is applied after flows are fetched."},
    "draft_policy_decision": {"execution": "report_only", "notes": "Draft policy comparison is applied after query completion."},
    "page": {"execution": "report_only", "notes": "Pagination is applied after flows are fetched."},
    "page_size": {"execution": "report_only", "notes": "Pagination is applied after flows are fetched."},
    "limit": {"execution": "report_only", "notes": "Pagination is applied after flows are fetched."},
    "offset": {"execution": "report_only", "notes": "Pagination is applied after flows are fetched."},
    "src_label_group": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label_group href and pushed to sources.include."},
    "src_label_groups": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label_group hrefs and pushed to sources.include."},
    "dst_label_group": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label_group href and pushed to destinations.include."},
    "dst_label_groups": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label_group hrefs and pushed to destinations.include."},
    "ex_src_label_group": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label_group href and pushed to sources.exclude."},
    "ex_src_label_groups": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label_group hrefs and pushed to sources.exclude."},
    "ex_dst_label_group": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label_group href and pushed to destinations.exclude."},
    "ex_dst_label_groups": {"execution": "native", "min_pce_version": "21.2", "notes": "Resolved to label_group hrefs and pushed to destinations.exclude."},
}


class EventFetchError(RuntimeError):
    """Raised when the PCE events API cannot be fetched safely."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _extract_id(href):
    """Extract the last segment from an Illumio HREF path."""
    return href.split('/')[-1] if href else ""


@dataclass
class TrafficQuerySpec:
    raw_filters: dict = field(default_factory=dict)
    native_filters: dict = field(default_factory=dict)
    fallback_filters: dict = field(default_factory=dict)
    report_only_filters: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)


class ApiClient:
    def __init__(self, config_manager):
        self.cm = config_manager
        self.api_cfg = self.cm.config["api"]
        self.base_url = f"{self.api_cfg['url']}/api/v2/orgs/{self.api_cfg['org_id']}"
        self._auth_header = self._build_auth_header()
        # Caches for rule scheduler features — TTLCache expires stale data after 15 min (Phase 2 Q5 fix)
        # Phase 6: _cache_lock serialises all TTLCache mutations so that APScheduler's
        # ThreadPoolExecutor workers cannot corrupt cache state concurrently.
        # Use time.time (wall clock) so freezegun can control expiry in tests
        self._cache_lock = threading.RLock()  # RLock: re-entrant (update_label_cache calls invalidate_*)
        self.label_cache = TTLCache(maxsize=10000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self.ruleset_cache = []
        self.service_ports_cache = TTLCache(maxsize=5000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._label_href_cache = TTLCache(maxsize=10000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._label_group_href_cache = TTLCache(maxsize=1000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._iplist_href_cache = TTLCache(maxsize=5000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self.last_traffic_query_diagnostics = {}
        self.last_rule_usage_batch_stats = {}
        self._root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._state_file = os.path.join(self._root_dir, "logs", "state.json")
        self._query_lookup_cache_refreshed_at = 0.0
        self._query_lookup_cache_ttl_seconds = _QUERY_LOOKUP_CACHE_TTL_SECONDS
        self._async_job_cache_max_age_days = _ASYNC_JOB_CACHE_MAX_AGE_DAYS
        self._async_job_prune_interval_seconds = _ASYNC_JOB_PRUNE_INTERVAL_SECONDS
        self._last_async_job_prune_at = 0.0

        # ── HTTP session with connection pool + automatic retry (Phase 2) ──
        self._session = requests.Session()
        # verify: bool OR path to CA bundle; matches old ssl_ctx behavior
        _verify_cfg = self.api_cfg.get('verify_ssl', True)
        # Preserve string values (CA bundle path) as-is; otherwise coerce to bool
        self._session.verify = _verify_cfg if isinstance(_verify_cfg, str) else bool(_verify_cfg)
        # Default headers on every request
        self._session.headers.update({
            "Authorization": self._auth_header,
            "Accept": "application/json",
        })
        # Retry policy: 3 tries, exponential backoff, on 429/502/503/504
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=1.0,            # 0s, 1s, 2s (first retry always 0; urllib3: factor * 2^(n-1))
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "HEAD"]),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def _build_auth_header(self):
        credentials = f"{self.api_cfg['key']}:{self.api_cfg['secret']}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        return f"Basic {encoded}"

    def _request(self, url, method="GET", data=None, headers=None, timeout=15, stream=False):
        """
        Core HTTP helper using requests.Session + urllib3 Retry.
        Returns (status_code, response_body_bytes | response_object).
        For stream=True, returns (status_code, raw requests.Response) — caller must close it.
        """
        req_headers = {}
        if headers:
            req_headers.update(headers)
        # Content-Type for JSON body only (bytes body is passed through)
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
            # urllib3/requests has already retried up to MAX_RETRIES;
            # any exception here is terminal. Match legacy shape: (0, error_bytes).
            logger.error(f"Connection failed: {e}")
            return 0, str(e).encode('utf-8')

        if stream:
            return resp.status_code, resp
        # .content buffers entire body; matches old resp.read() semantics.
        return resp.status_code, resp.content

    def check_health(self):
        url = f"{self.api_cfg['url']}/api/v2/health"
        try:
            status, body = self._request(url, timeout=10)
            text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            return status, text
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return 0, str(e)

    def _build_events_url(self, start_time_str, end_time_str=None, max_results=5000):
        params = {
            "timestamp[gte]": start_time_str,
            "max_results": max_results,
        }
        if end_time_str:
            params["timestamp[lte]"] = end_time_str
        return f"{self.base_url}/events?{urllib.parse.urlencode(params)}"

    def fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
        """Fetch PCE events or raise an exception on any fetch/parsing error."""
        url = self._build_events_url(start_time_str, end_time_str=end_time_str, max_results=max_results)
        status, body = self._request(url, timeout=30)
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

    def fetch_events(self, start_time_str, end_time_str=None, max_results=5000):
        try:
            return self.fetch_events_strict(
                start_time_str,
                end_time_str=end_time_str,
                max_results=max_results,
            )
        except EventFetchError as e:
            logger.error(f"Get Events Failed: {e.status} - {e.message}")
            print(f"{Colors.FAIL}{t('api_get_events_failed', status=e.status, error=e.message[:500])}{Colors.ENDC}")
            return []
        except Exception as e:
            logger.error(f"Fetch Events Error: {e}")
            print(f"{Colors.FAIL}{t('api_fetch_events_error', error=str(e))}{Colors.ENDC}")
            return []

    @staticmethod
    def _normalize_label_filter(label_str):
        """Normalize a label filter string to `key:value`, or return empty string."""
        if not label_str:
            return ""
        for sep in (":", "="):
            if sep in str(label_str):
                key, value = str(label_str).split(sep, 1)
                key = key.strip()
                value = value.strip()
                if key and value:
                    return f"{key}:{value}"
        return ""

    @staticmethod
    def _is_ip_literal(value):
        try:
            ipaddress.ip_address(str(value).strip())
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_href(value):
        return isinstance(value, str) and value.startswith("/orgs/")

    def invalidate_query_lookup_cache(self):
        """Clear cached label/service/IP-list/label-group lookups."""
        with self._cache_lock:
            self.label_cache.clear()
            self.service_ports_cache.clear()
            self._label_href_cache.clear()
            self._label_group_href_cache.clear()
            self._iplist_href_cache.clear()
            self._query_lookup_cache_refreshed_at = 0.0

    def _query_lookup_cache_is_stale(self):
        if not self._query_lookup_cache_refreshed_at:
            return not (
                self._label_href_cache
                or self._label_group_href_cache
                or self._iplist_href_cache
                or self.service_ports_cache
            )
        ttl = max(0, int(self._query_lookup_cache_ttl_seconds or 0))
        if ttl == 0:
            return False
        return (time.time() - self._query_lookup_cache_refreshed_at) >= ttl

    def _ensure_query_lookup_cache(self, force_refresh=False):
        """Populate label/service/IP-list lookup caches used by native query building."""
        cache_ready = (
            self._label_href_cache
            and self._label_group_href_cache
            and self._iplist_href_cache
        )
        if cache_ready and not force_refresh and not self._query_lookup_cache_is_stale():
            return
        self.update_label_cache(silent=True, force_refresh=True)
        if not self._label_href_cache:
            for href, display in self.label_cache.items():
                if display and ":" in display and not display.startswith("[IPList] ") and not display.startswith("[LabelGroup] "):
                    self._label_href_cache.setdefault(display, href)
        if not self._label_group_href_cache:
            for href, display in self.label_cache.items():
                if display.startswith("[LabelGroup] "):
                    self._label_group_href_cache.setdefault(display.replace("[LabelGroup] ", "", 1), href)
        if not self._iplist_href_cache:
            for href, display in self.label_cache.items():
                if display.startswith("[IPList] "):
                    self._iplist_href_cache.setdefault(display.replace("[IPList] ", "", 1), href)

    @staticmethod
    def _normalize_str_list(value):
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(v).strip() for v in value if str(v).strip()]
        text = str(value).strip()
        return [text] if text else []

    @staticmethod
    def _normalize_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("1", "true", "yes", "y", "on"):
                return True
            if text in ("0", "false", "no", "n", "off"):
                return False
        return bool(value)

    @staticmethod
    def _normalize_transmission_values(value):
        alias_map = {
            "unicast": "unicast",
            "uni": "unicast",
            "broadcast": "broadcast",
            "bcast": "broadcast",
            "multicast": "multicast",
            "mcast": "multicast",
        }
        normalized = []
        for item in ApiClient._normalize_str_list(value):
            mapped = alias_map.get(item.lower())
            if mapped:
                normalized.append(mapped)
        return normalized

    @staticmethod
    def _parse_port_range_entry(value, default_proto=None):
        proto = default_proto
        if isinstance(value, (list, tuple)):
            if len(value) == 2:
                start, end = value
            elif len(value) == 3:
                start, end, proto = value
            else:
                return None
        else:
            text = str(value).strip()
            if not text:
                return None
            range_part = text
            if "/" in text:
                range_part, proto_part = text.split("/", 1)
                proto = proto_part
            elif ":" in text and text.count(":") == 1 and "-" in text:
                range_part, proto_part = text.split(":", 1)
                proto = proto_part
            if "-" not in range_part:
                return None
            start, end = [part.strip() for part in range_part.split("-", 1)]
        try:
            start = int(start)
            end = int(end)
            if start > end:
                start, end = end, start
            if proto in (None, ""):
                return {"port": start, "to_port": end}
            return {"port": start, "to_port": end, "proto": int(proto)}
        except (TypeError, ValueError):
            return None

    def _resolve_actor_filter(self, value):
        if value is None:
            return None
        if isinstance(value, dict):
            if value.get("actors") == "ams":
                return {"actors": "ams"}
            if value.get("label"):
                return self._resolve_label_filter_to_actor(value.get("label"))
            if value.get("label_group"):
                return self._resolve_label_group_filter_to_actor(value.get("label_group"))
            if value.get("ip"):
                return self._resolve_ip_filter_to_actor(value.get("ip"))
            if value.get("href"):
                return self._resolve_ip_filter_to_actor(value.get("href"))
            if value.get("ip_address"):
                return {"ip_address": {"value": str(value["ip_address"]).strip()}}
            if value.get("workload"):
                href = value["workload"].get("href") if isinstance(value["workload"], dict) else value["workload"]
                if href:
                    return {"workload": {"href": str(href).strip()}}
            if value.get("ip_list"):
                href = value["ip_list"].get("href") if isinstance(value["ip_list"], dict) else value["ip_list"]
                if href:
                    return {"ip_list": {"href": str(href).strip()}}
            return None

        text = str(value).strip()
        if not text:
            return None
        if text.lower() in ("ams", "all_managed", "all-managed"):
            return {"actors": "ams"}
        label_actor = self._resolve_label_filter_to_actor(text)
        if label_actor:
            return label_actor
        return self._resolve_ip_filter_to_actor(text)

    @staticmethod
    def _clone_query_spec(spec):
        return TrafficQuerySpec(
            raw_filters=dict(spec.raw_filters),
            native_filters=dict(spec.native_filters),
            fallback_filters=dict(spec.fallback_filters),
            report_only_filters=dict(spec.report_only_filters),
            diagnostics=dict(spec.diagnostics),
        )

    def get_traffic_query_capability_matrix(self):
        return {key: dict(value) for key, value in _TRAFFIC_FILTER_CAPABILITIES.items()}

    def build_traffic_query_spec(self, filters=None):
        if isinstance(filters, TrafficQuerySpec):
            return self._clone_query_spec(filters)

        raw_filters = dict(filters or {})
        spec = TrafficQuerySpec(raw_filters=dict(raw_filters))
        capability_hits = {}
        for key, value in raw_filters.items():
            capability = _TRAFFIC_FILTER_CAPABILITIES.get(key, {"execution": "fallback", "notes": "No explicit capability entry; falling back to client-side filtering."})
            capability_hits[key] = capability
            execution = capability.get("execution")
            if execution == "report_only":
                spec.report_only_filters[key] = value
            elif execution in ("fallback", "unsupported"):
                spec.fallback_filters[key] = value
            elif execution == "native":
                spec.native_filters[key] = value
            else:
                spec.fallback_filters[key] = value

        spec.diagnostics = {
            "native_filters": dict(spec.native_filters),
            "fallback_filters": dict(spec.fallback_filters),
            "report_only_filters": dict(spec.report_only_filters),
            "capabilities": capability_hits,
        }
        return spec

    def _resolve_label_filter_to_actor(self, label_filter):
        normalized = self._normalize_label_filter(label_filter)
        if not normalized:
            return None
        self._ensure_query_lookup_cache()
        href = self._label_href_cache.get(normalized)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = self._label_href_cache.get(normalized)
        if href:
            return {"label": {"href": href}}
        return None

    def _resolve_label_group_filter_to_actor(self, label_group_filter):
        if not label_group_filter:
            return None
        if isinstance(label_group_filter, dict):
            href = label_group_filter.get("href")
            if href:
                return {"label_group": {"href": str(href).strip()}}
            name = label_group_filter.get("name")
            if name:
                label_group_filter = name
            else:
                return None

        candidate = str(label_group_filter).strip()
        if not candidate:
            return None
        if self._is_href(candidate) and "/label_groups/" in candidate:
            return {"label_group": {"href": candidate}}

        self._ensure_query_lookup_cache()
        href = self._label_group_href_cache.get(candidate)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = self._label_group_href_cache.get(candidate)
        if href:
            return {"label_group": {"href": href}}
        return None

    def _resolve_ip_filter_to_actor(self, ip_filter):
        if not ip_filter:
            return None
        candidate = str(ip_filter).strip()
        if not candidate:
            return None
        if self._is_href(candidate):
            if "/ip_lists/" in candidate:
                return {"ip_list": {"href": candidate}}
            if "/workloads/" in candidate:
                return {"workload": {"href": candidate}}
            return None
        if self._is_ip_literal(candidate):
            return {"ip_address": {"value": candidate}}
        self._ensure_query_lookup_cache()
        href = self._iplist_href_cache.get(candidate)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = self._iplist_href_cache.get(candidate)
        if href:
            return {"ip_list": {"href": href}}
        return None

    @staticmethod
    def _dedupe_query_group(items):
        deduped = []
        seen = set()
        for item in items:
            key = json.dumps(item, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _build_native_traffic_payload(self, start_time_str, end_time_str, policy_decisions, filters=None):
        """
        Build a workloader-style async query payload for general traffic queries.

        Returns:
            (payload, effective_spec)
        """
        spec = self.build_traffic_query_spec(filters)
        native_filters = dict(spec.native_filters)
        payload = {
            "start_date": start_time_str,
            "end_date": end_time_str,
            "policy_decisions": policy_decisions,
            "max_results": MAX_TRAFFIC_RESULTS,
            "query_name": "Traffic_Monitor_Query",
            "sources": {"include": [], "exclude": []},
            "destinations": {"include": [], "exclude": []},
            "services": {"include": [], "exclude": []},
        }
        residual = dict(spec.fallback_filters)
        consumed_native = {}
        unresolved_native = {}

        def _record_consumed(key, value):
            consumed_native[key] = value

        def _record_unresolved(key, value):
            unresolved_native[key] = value
            residual[key] = value

        def _pop_many(keys):
            values = []
            used_keys = []
            for key in keys:
                value = native_filters.get(key)
                if not value:
                    continue
                used_keys.append(key)
                if isinstance(value, list):
                    values.extend([v for v in value if v])
                else:
                    values.append(value)
            return values, used_keys

        def _consume_keys(keys):
            for key in keys:
                native_filters.pop(key, None)

        def _append_ams(side, key):
            if key not in native_filters:
                return
            value = native_filters.get(key)
            if not self._normalize_bool(value):
                _record_unresolved(key, value)
                _consume_keys((key,))
                return
            include_groups = payload[side]["include"]
            if include_groups:
                for group in include_groups:
                    group.append({"actors": "ams"})
            else:
                include_groups.append([{"actors": "ams"}])
            _record_consumed(key, value)
            _consume_keys((key,))

        def _append_actor_groups(side, key):
            groups = native_filters.get(key)
            if not groups:
                return
            if not isinstance(groups, (list, tuple)):
                _record_unresolved(key, groups)
                _consume_keys((key,))
                return

            built_groups = []
            unresolved = False
            for group in groups:
                if not isinstance(group, (list, tuple)) or not group:
                    unresolved = True
                    break
                resolved_group = []
                for entry in group:
                    resolved = self._resolve_actor_filter(entry)
                    if not resolved:
                        unresolved = True
                        break
                    resolved_group.append(resolved)
                if unresolved:
                    break
                built_groups.append(self._dedupe_query_group(resolved_group))

            if unresolved or not built_groups:
                _record_unresolved(key, groups)
                _consume_keys((key,))
                return

            payload[side]["include"].extend(built_groups)
            _record_consumed(key, groups)
            _consume_keys((key,))

        include_specs = [
            (("src_label", "src_labels"), "sources", self._resolve_label_filter_to_actor),
            (("src_label_group", "src_label_groups"), "sources", self._resolve_label_group_filter_to_actor),
            (("dst_label", "dst_labels"), "destinations", self._resolve_label_filter_to_actor),
            (("dst_label_group", "dst_label_groups"), "destinations", self._resolve_label_group_filter_to_actor),
            (("src_ip_in", "src_ip"), "sources", self._resolve_ip_filter_to_actor),
            (("dst_ip_in", "dst_ip"), "destinations", self._resolve_ip_filter_to_actor),
        ]
        exclude_specs = [
            (("ex_src_label", "ex_src_labels"), "sources", self._resolve_label_filter_to_actor),
            (("ex_src_label_group", "ex_src_label_groups"), "sources", self._resolve_label_group_filter_to_actor),
            (("ex_dst_label", "ex_dst_labels"), "destinations", self._resolve_label_filter_to_actor),
            (("ex_dst_label_group", "ex_dst_label_groups"), "destinations", self._resolve_label_group_filter_to_actor),
            (("ex_src_ip",), "sources", self._resolve_ip_filter_to_actor),
            (("ex_dst_ip",), "destinations", self._resolve_ip_filter_to_actor),
        ]

        for keys, side, resolver in include_specs:
            values, used_keys = _pop_many(keys)
            if not values:
                continue
            resolved_items = []
            unresolved = False
            for value in values:
                item = resolver(value)
                if item is None:
                    unresolved = True
                    break
                resolved_items.append(item)
            if unresolved:
                for key in used_keys:
                    _record_unresolved(key, spec.native_filters.get(key))
                _consume_keys(used_keys)
                continue
            payload[side]["include"].append(self._dedupe_query_group(resolved_items))
            for key in used_keys:
                _record_consumed(key, spec.native_filters.get(key))
            _consume_keys(used_keys)

        _append_actor_groups("sources", "src_include_groups")
        _append_actor_groups("destinations", "dst_include_groups")
        _append_ams("sources", "src_ams")
        _append_ams("destinations", "dst_ams")

        for keys, side, resolver in exclude_specs:
            values, used_keys = _pop_many(keys)
            if not values:
                continue
            resolved_items = []
            unresolved = False
            for value in values:
                item = resolver(value)
                if item is None:
                    unresolved = True
                    break
                resolved_items.append(item)
            if unresolved:
                for key in used_keys:
                    _record_unresolved(key, spec.native_filters.get(key))
                _consume_keys(used_keys)
                continue
            payload[side]["exclude"].extend(self._dedupe_query_group(resolved_items))
            for key in used_keys:
                _record_consumed(key, spec.native_filters.get(key))
            _consume_keys(used_keys)

        for key, side in (("ex_src_ams", "sources"), ("ex_dst_ams", "destinations")):
            if key not in native_filters:
                continue
            value = native_filters.get(key)
            if not self._normalize_bool(value):
                _record_unresolved(key, value)
                _consume_keys((key,))
                continue
            payload[side]["exclude"].append({"actors": "ams"})
            _record_consumed(key, value)
            _consume_keys((key,))

        port = native_filters.get("port")
        proto = native_filters.get("proto")
        if port:
            try:
                port_entry = {"port": int(port)}
                if proto not in (None, ""):
                    port_entry["proto"] = int(proto)
                payload["services"]["include"].append(port_entry)
                _record_consumed("port", spec.native_filters.get("port"))
                if "proto" in spec.native_filters:
                    _record_consumed("proto", spec.native_filters.get("proto"))
                _consume_keys(("port", "proto"))
            except (TypeError, ValueError):
                _record_unresolved("port", spec.native_filters.get("port"))
                if "proto" in spec.native_filters:
                    _record_unresolved("proto", spec.native_filters.get("proto"))
                _consume_keys(("port", "proto"))

        ex_port = native_filters.get("ex_port")
        if ex_port:
            try:
                payload["services"]["exclude"].append({"port": int(ex_port)})
                _record_consumed("ex_port", spec.native_filters.get("ex_port"))
                _consume_keys(("ex_port",))
            except (TypeError, ValueError):
                _record_unresolved("ex_port", spec.native_filters.get("ex_port"))
                _consume_keys(("ex_port",))

        default_proto = native_filters.get("proto")
        for key, target in (("port_range", "include"), ("port_ranges", "include"),
                            ("ex_port_range", "exclude"), ("ex_port_ranges", "exclude")):
            if key not in native_filters:
                continue
            values = native_filters.get(key)
            entries = values if isinstance(values, (list, tuple)) and key.endswith("s") else [values]
            parsed_entries = []
            unresolved = False
            for entry in entries:
                parsed = self._parse_port_range_entry(entry, default_proto=default_proto)
                if not parsed:
                    unresolved = True
                    break
                parsed_entries.append(parsed)
            if unresolved:
                _record_unresolved(key, spec.native_filters.get(key))
                _consume_keys((key,))
                continue
            payload["services"][target].extend(parsed_entries)
            _record_consumed(key, spec.native_filters.get(key))
            _consume_keys((key,))

        for key, field, target in (
            ("process_name", "process_name", "include"),
            ("windows_service_name", "windows_service_name", "include"),
            ("ex_process_name", "process_name", "exclude"),
            ("ex_windows_service_name", "windows_service_name", "exclude"),
        ):
            value = native_filters.get(key)
            if value:
                payload["services"][target].append({field: str(value).strip()})
                _record_consumed(key, spec.native_filters.get(key))
                _consume_keys((key,))

        transmission_values = self._normalize_transmission_values(
            native_filters.get("transmission_excludes") or native_filters.get("ex_transmission")
        )
        if transmission_values:
            for value in transmission_values:
                payload["destinations"]["exclude"].append({"transmission": value})
            if "transmission_excludes" in spec.native_filters:
                _record_consumed("transmission_excludes", spec.native_filters.get("transmission_excludes"))
                _consume_keys(("transmission_excludes",))
            if "ex_transmission" in spec.native_filters:
                _record_consumed("ex_transmission", spec.native_filters.get("ex_transmission"))
                _consume_keys(("ex_transmission",))
        else:
            for key in ("transmission_excludes", "ex_transmission"):
                if key in native_filters:
                    _record_unresolved(key, spec.native_filters.get(key))
                    _consume_keys((key,))

        query_op = str(native_filters.get("query_operator", "") or "").strip().lower()
        if query_op in ("and", "or"):
            payload["sources_destinations_query_op"] = query_op
            _record_consumed("query_operator", spec.native_filters.get("query_operator"))
            _consume_keys(("query_operator",))
        elif "query_operator" in native_filters:
            _record_unresolved("query_operator", spec.native_filters.get("query_operator"))
            _consume_keys(("query_operator",))

        if "exclude_workloads_from_ip_list_query" in native_filters:
            payload["exclude_workloads_from_ip_list_query"] = self._normalize_bool(
                native_filters.get("exclude_workloads_from_ip_list_query")
            )
            _record_consumed(
                "exclude_workloads_from_ip_list_query",
                spec.native_filters.get("exclude_workloads_from_ip_list_query"),
            )
            _consume_keys(("exclude_workloads_from_ip_list_query",))

        for key, value in native_filters.items():
            _record_unresolved(key, value)

        effective_spec = TrafficQuerySpec(
            raw_filters=dict(spec.raw_filters),
            native_filters=consumed_native,
            fallback_filters=residual,
            report_only_filters=dict(spec.report_only_filters),
            diagnostics={
                "native_filters": dict(consumed_native),
                "fallback_filters": dict(residual),
                "report_only_filters": dict(spec.report_only_filters),
                "unresolved_native_filters": dict(unresolved_native),
                "native_query_used": bool(
                    payload["sources"]["include"] or payload["sources"]["exclude"] or
                    payload["destinations"]["include"] or payload["destinations"]["exclude"] or
                    payload["services"]["include"] or payload["services"]["exclude"]
                ),
            },
        )
        return payload, effective_spec

    def _submit_and_stream_async_query(self, payload, compute_draft=False):
        """Submit an async query and stream its downloaded results."""
        url = f"{self.base_url}/traffic_flows/async_queries"
        status, body = self._request(url, method="POST", data=payload, timeout=10)
        if status not in (200, 201, 202):
            text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            logger.error(f"API Error {status}: {text}")
            print(t("api_error_status", status=status, text=text))
            return

        result = orjson.loads(body)
        if result.get("status") in ("queued", "pending") and not result.get("href"):
            logger.error(f"Async query accepted but no href returned: {result}")
            return
        job_url = result.get("href")
        print(t('waiting_traffic', default='Waiting for traffic calculation...'), end="", flush=True)

        poll_url = f"{self.api_cfg['url']}/api/v2{job_url}"
        for _ in range(60):
            time.sleep(2)
            poll_status, poll_body = self._request(poll_url, timeout=15)
            if poll_status != 200:
                continue

            state = orjson.loads(poll_body).get("status")
            if state == "completed":
                print(f" {t('done')}")
                logger.info("Traffic query completed.")
                break
            if state == "failed":
                print(f" {t('query_failed', default='Failed.')}")
                logger.error("Traffic query failed.")
                return
            print(".", end="", flush=True)
        else:
            print(f" {t('api_timeout')}")
            logger.error("Traffic query timed out.")
            return

        if compute_draft:
            update_rules_url = f"{self.api_cfg['url']}/api/v2{job_url}/update_rules"
            logger.info(f"Calling update_rules: PUT {update_rules_url}")
            ur_status, ur_body = self._request(update_rules_url, method="PUT", data={}, timeout=30)
            logger.info(f"update_rules response: HTTP {ur_status}")
            if ur_status in (202, 204):
                ur_text = ur_body.decode('utf-8', errors='replace') if isinstance(ur_body, bytes) else str(ur_body)
                logger.info(f"update_rules accepted (HTTP {ur_status}), body: {ur_text[:300]}")
                print(t('waiting_traffic', default='Waiting for traffic calculation...'), end="", flush=True)
                time.sleep(10)
                for attempt in range(30):
                    poll_status, poll_body = self._request(poll_url, timeout=15)
                    if poll_status != 200:
                        time.sleep(2)
                        continue
                    poll_result = orjson.loads(poll_body)
                    state = poll_result.get("status")
                    rules_state = poll_result.get("rules")
                    logger.info(f"update_rules poll [{attempt}]: status={state}, rules={rules_state}")
                    if state == "completed" and (rules_state in (None, "", "completed")):
                        print(f" {t('done')}")
                        logger.info("update_rules computation done.")
                        break
                    print(".", end="", flush=True)
                    time.sleep(2)
                else:
                    logger.warning("update_rules polling timed out, proceeding with available data")
                    print(f" {t('done')}")
            else:
                ur_text = ur_body.decode('utf-8', errors='replace') if isinstance(ur_body, bytes) else str(ur_body)
                logger.warning(f"update_rules returned {ur_status}: {ur_text[:200]}, proceeding without draft policy data")

        dl_url = f"{self.api_cfg['url']}/api/v2{job_url}/download"
        dl_status, dl_body = self._request(dl_url, timeout=60)
        if dl_status != 200:
            logger.error(f"Download failed: {dl_status}")
            return

        buffer = BytesIO(dl_body)
        try:
            with gzip.GzipFile(fileobj=buffer, mode='rb') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        if line == b'[' or line == b']':
                            continue
                        if line.endswith(b','):
                            line = line[:-1]
                        data = orjson.loads(line)
                        if isinstance(data, list):
                            for item in data:
                                yield item
                        else:
                            yield data
                    except json.JSONDecodeError as je:
                        logger.debug(f"Skipping unparseable line: {je}")
        except (gzip.BadGzipFile, OSError):
            buffer.seek(0)
            text_data = buffer.read().decode('utf-8', errors='replace')
            for line in text_data.splitlines():
                if not line.strip():
                    continue
                try:
                    data = orjson.loads(line)
                    if isinstance(data, list):
                        for item in data:
                            yield item
                    else:
                        yield data
                except json.JSONDecodeError as je:
                    logger.debug(f"Skipping unparseable line: {je}")

    def execute_traffic_query_stream(self, start_time_str, end_time_str, policy_decisions, filters=None, compute_draft=False):
        """
        Executes an async traffic query and yields results row by row to save memory.
        filters: optional dict used for native PCE filtering when safely expressible.
                 Unsupported filters remain available for client-side filtering.
        """
        query_spec = self.build_traffic_query_spec(filters)
        f = query_spec.raw_filters
        if f.get("policy_decisions"):
            policy_decisions = f["policy_decisions"]

        print(t('submitting_query', start=start_time_str, end=end_time_str))
        logger.info(f"Submitting traffic query ({start_time_str} to {end_time_str})")
        try:
            payload, effective_spec = self._build_native_traffic_payload(
                start_time_str, end_time_str, policy_decisions, filters=query_spec
            )
            self.last_traffic_query_diagnostics = dict(effective_spec.diagnostics)
            logger.info(
                "Traffic query mode: native=%s native_filters=%s fallback_filters=%s report_only_filters=%s unresolved_native=%s",
                effective_spec.diagnostics.get("native_query_used", False),
                sorted(effective_spec.native_filters.keys()),
                sorted(effective_spec.fallback_filters.keys()),
                sorted(effective_spec.report_only_filters.keys()),
                sorted(effective_spec.diagnostics.get("unresolved_native_filters", {}).keys()),
            )
            yield from self._submit_and_stream_async_query(payload, compute_draft=compute_draft)
        except Exception as e:
            logger.error(f"Query Exception: {e}")
            print(t("api_query_exception", error=str(e)))
            return

    @staticmethod
    def _flow_matches_filters(flow: dict, filters: dict) -> bool:
        """
        Python-side filter applied after PCE download.
        Mirrors the label/IP logic from Analyzer.check_flow_match().
        filters keys: src_labels, dst_labels, src_ip, dst_ip, port, proto,
                      ex_src_labels, ex_dst_labels, ex_src_ip, ex_dst_ip, ex_port,
                      any_label, any_ip, ex_any_label, ex_any_ip.
        Label format: "key:value" or "key=value".
        any_label/any_ip: OR logic — matches if EITHER src or dst satisfies the condition.
        """
        src = flow.get('src', {})
        dst = flow.get('dst', {})
        svc = flow.get('service', {})

        def _label_match(side: dict, label_str: str) -> bool:
            """Return True if the flow side has a label matching 'key:value'."""
            for sep in (':', '='):
                if sep in label_str:
                    fk, fv = label_str.split(sep, 1)
                    fk, fv = fk.strip(), fv.strip()
                    for lbl in side.get('workload', {}).get('labels', []):
                        if lbl.get('key') == fk and lbl.get('value') == fv:
                            return True
                    return False
            return False

        def _ip_match(side: dict, ip_str: str) -> bool:
            if side.get('ip') == ip_str:
                return True
            for ipl in side.get('ip_lists', []):
                if ipl.get('name') == ip_str:
                    return True
            return False

        # ── Include filters (must match if specified) ─────────────────────────
        for lbl in (filters.get('src_labels') or []):
            if lbl and not _label_match(src, lbl):
                return False
        for lbl in (filters.get('dst_labels') or []):
            if lbl and not _label_match(dst, lbl):
                return False
        if filters.get('src_ip') and not _ip_match(src, filters['src_ip']):
            return False
        if filters.get('dst_ip') and not _ip_match(dst, filters['dst_ip']):
            return False

        port_filter = filters.get('port', '')
        if port_filter:
            try:
                flow_port = svc.get('port') or flow.get('dst_port')
                if flow_port is None or int(flow_port) != int(port_filter):
                    return False
            except (ValueError, TypeError):
                pass

        proto_filter = filters.get('proto')
        if proto_filter:
            try:
                flow_proto = svc.get('proto') or flow.get('proto')
                if flow_proto is None or int(flow_proto) != int(proto_filter):
                    return False
            except (ValueError, TypeError):
                pass

        # ── Any-side include filters (src OR dst must match) ─────────────────
        any_label = filters.get('any_label')
        if any_label:
            if not (_label_match(src, any_label) or _label_match(dst, any_label)):
                return False
        any_ip = filters.get('any_ip')
        if any_ip:
            if not (_ip_match(src, any_ip) or _ip_match(dst, any_ip)):
                return False

        # ── Exclude filters (must NOT match) ──────────────────────────────────
        for lbl in (filters.get('ex_src_labels') or []):
            if lbl and _label_match(src, lbl):
                return False
        for lbl in (filters.get('ex_dst_labels') or []):
            if lbl and _label_match(dst, lbl):
                return False
        if filters.get('ex_src_ip') and _ip_match(src, filters['ex_src_ip']):
            return False
        if filters.get('ex_dst_ip') and _ip_match(dst, filters['ex_dst_ip']):
            return False

        ex_port = filters.get('ex_port', '')
        if ex_port:
            try:
                flow_port = svc.get('port') or flow.get('dst_port')
                if flow_port is not None and int(flow_port) == int(ex_port):
                    return False
            except (ValueError, TypeError):
                pass

        # ── Any-side exclude filters (exclude if src OR dst matches) ─────────
        ex_any_label = filters.get('ex_any_label')
        if ex_any_label:
            if _label_match(src, ex_any_label) or _label_match(dst, ex_any_label):
                return False
        ex_any_ip = filters.get('ex_any_ip')
        if ex_any_ip:
            if _ip_match(src, ex_any_ip) or _ip_match(dst, ex_any_ip):
                return False

        return True

    def fetch_traffic_for_report(self, start_time_str, end_time_str,
                                 policy_decisions=None, filters=None):
        """
        Convenience wrapper for report generation.
        Fetches all traffic from PCE then applies Python-side filters.
        Returns: list[dict] — filtered flow records, or empty list on failure.
        """
        if policy_decisions is None:
            policy_decisions = ["blocked", "potentially_blocked", "allowed"]

        query_spec = self.build_traffic_query_spec(filters)
        stream = self.execute_traffic_query_stream(
            start_time_str, end_time_str, policy_decisions, filters=query_spec
        )
        if stream is None:
            return []

        records = list(stream)

        # Apply Python-side filters if specified (PCE API-level filtering is not used
        # because label key/value format is not reliably accepted by the async query API)
        if query_spec.fallback_filters:
            before = len(records)
            records = [r for r in records if self._flow_matches_filters(r, query_spec.fallback_filters)]
            after = len(records)
            if before != after:
                logger.info(f"[ReportFilter] {before} → {after} flows after applying filters")

        return records

    def get_last_traffic_query_diagnostics(self):
        return dict(self.last_traffic_query_diagnostics)

    @staticmethod
    def _utc_now_iso():
        return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    def _save_async_job_state(self, job_href, **fields):
        if not job_href:
            return

        def _merge(existing):
            data = dict(existing)
            jobs = data.setdefault(_ASYNC_JOB_STATE_KEY, {})
            entry = dict(jobs.get(job_href, {}))
            entry.update({k: v for k, v in fields.items() if v is not None})
            entry["job_href"] = job_href
            entry["updated_at"] = fields.get("updated_at") or self._utc_now_iso()
            if "created_at" not in entry:
                entry["created_at"] = entry["updated_at"]
            jobs[job_href] = entry
            return data

        try:
            update_state_file(self._state_file, _merge)
        except Exception as exc:
            logger.debug("Failed to persist async job state for %s: %s", job_href, exc)

    @staticmethod
    def _make_query_signature(payload):
        if not payload:
            return ""
        try:
            return json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _job_timestamp_epoch(job):
        for key in ("updated_at", "created_at", "reused_at"):
            value = job.get(key)
            if not value:
                continue
            try:
                dt = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
            except ValueError:
                continue
        return 0.0

    def _load_async_job_states(self):
        try:
            self._maybe_prune_async_job_states()
            data = load_state_file(self._state_file)
            jobs = data.get(_ASYNC_JOB_STATE_KEY, {})
            return jobs if isinstance(jobs, dict) else {}
        except Exception as exc:
            logger.debug("Failed to load async job states: %s", exc)
            return {}

    def _job_age_seconds(self, job):
        ts = self._job_timestamp_epoch(job)
        return max(0.0, time.time() - ts) if ts else 0.0

    def _job_is_stale(self, job, max_age_days=None):
        age_days = float(max_age_days or self._async_job_cache_max_age_days or 0)
        if age_days <= 0:
            return False
        return self._job_age_seconds(job) > (age_days * 86400)

    def _maybe_prune_async_job_states(self):
        interval = max(0, int(self._async_job_prune_interval_seconds or 0))
        now = time.time()
        if interval and self._last_async_job_prune_at and (now - self._last_async_job_prune_at) < interval:
            return
        self._last_async_job_prune_at = now
        try:
            self.prune_async_job_states(max_age_days=self._async_job_cache_max_age_days)
        except Exception as exc:
            logger.debug("Async job state prune skipped: %s", exc)

    def find_cached_async_summary(self, payload, query_type="rule_usage"):
        signature = self._make_query_signature(payload)
        if not signature:
            return None

        jobs = self._load_async_job_states()
        matches = []
        for job_href, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if job.get("query_type") != query_type:
                continue
            if job.get("query_signature") != signature:
                continue
            if self._job_is_stale(job):
                continue
            if job.get("status") != "completed":
                continue
            if job.get("download_status") != "completed":
                continue
            if "flow_count" not in job:
                continue
            matches.append((job.get("updated_at", ""), job_href, job))

        if not matches:
            return None

        _, job_href, job = max(matches, key=lambda item: item[0])
        return {
            "job_href": job_href,
            "count": int(job.get("flow_count", 0) or 0),
            "flows_by_port": dict(job.get("flows_by_port", {}) or {}),
            "updated_at": job.get("updated_at", ""),
        }

    def find_latest_async_job(self, payload, query_type="rule_usage"):
        signature = self._make_query_signature(payload)
        if not signature:
            return None

        jobs = self._load_async_job_states()
        matches = []
        for job_href, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if job.get("query_type") != query_type:
                continue
            if job.get("query_signature") != signature:
                continue
            if self._job_is_stale(job):
                continue
            matches.append((self._job_timestamp_epoch(job), job_href, job))

        if not matches:
            return None

        _, job_href, job = max(matches, key=lambda item: item[0])
        found = dict(job)
        found["job_href"] = job_href
        return found

    def resume_async_query_job(self, job_href, timeout=120, summarize=False, compute_draft=False):
        poll_result = self._wait_for_async_query(job_href, timeout=timeout, compute_draft=compute_draft)
        result = {
            "job_href": job_href,
            "status": poll_result.get("status"),
            "rules_status": poll_result.get("rules"),
        }
        if result["status"] == "completed" and summarize:
            result.update(self.summarize_async_query(job_href))
        return result

    def retry_async_query_job(self, job_href):
        jobs = self._load_async_job_states()
        job = jobs.get(job_href, {})
        query_body = job.get("query_body")
        query_type = job.get("query_type", "rule_usage")
        if not query_body:
            raise ValueError(f"Async job {job_href} has no query_body for retry")

        new_job_href = self.submit_async_query(query_body, query_type=query_type)
        if not new_job_href:
            raise RuntimeError(f"Failed to resubmit async job {job_href}")

        now = self._utc_now_iso()
        self._save_async_job_state(job_href, retried_at=now, retried_by=new_job_href)
        self._save_async_job_state(new_job_href, retried_from=job_href, retry_submitted_at=now)
        return new_job_href

    def prune_async_job_states(self, max_age_days=7, keep_recent_completed=200):
        cutoff = time.time() - (max_age_days * 86400)

        def _prune(existing):
            data = dict(existing)
            jobs = dict(data.get(_ASYNC_JOB_STATE_KEY, {}) or {})
            completed_jobs = [
                (self._job_timestamp_epoch(job), href)
                for href, job in jobs.items()
                if isinstance(job, dict) and job.get("status") == "completed"
            ]
            completed_jobs.sort(reverse=True)
            keep_completed = {href for _, href in completed_jobs[:keep_recent_completed]}

            pruned = {}
            removed = 0
            for href, job in jobs.items():
                if not isinstance(job, dict):
                    continue
                ts = self._job_timestamp_epoch(job)
                if job.get("status") == "completed" and href in keep_completed:
                    pruned[href] = job
                    continue
                if ts and ts < cutoff:
                    removed += 1
                    continue
                pruned[href] = job

            data[_ASYNC_JOB_STATE_KEY] = pruned
            data["_last_async_prune"] = {
                "removed": removed,
                "updated_at": self._utc_now_iso(),
            }
            return data

        updated = update_state_file(self._state_file, _prune)
        meta = updated.get("_last_async_prune", {})
        return {
            "removed": int(meta.get("removed", 0) or 0),
            "remaining": len(updated.get(_ASYNC_JOB_STATE_KEY, {}) or {}),
        }

    def get_last_rule_usage_batch_stats(self):
        return dict(self.last_rule_usage_batch_stats)

    @staticmethod
    def _sorted_flows_by_port_items(flows_by_port, limit=None):
        items = []
        for key, value in dict(flows_by_port or {}).items():
            try:
                count = int(value or 0)
            except (TypeError, ValueError):
                continue
            items.append((str(key), count))
        items.sort(key=lambda item: (-item[1], item[0]))
        if limit is not None:
            return items[:limit]
        return items

    @classmethod
    def _format_flows_by_port(cls, flows_by_port, limit=3):
        parts = [f"{port_proto} ({count})" for port_proto, count in cls._sorted_flows_by_port_items(flows_by_port, limit=limit)]
        return "; ".join(parts)

    @staticmethod
    def _rule_usage_detail(rule: dict, **extra) -> dict:
        detail = {
            "rule_href": rule.get("href", ""),
            "rule_id": rule.get("_rule_id", ""),
            "rule_no": rule.get("_rule_no", ""),
            "rule_type": rule.get("_rule_type", ""),
            "ruleset_href": rule.get("_ruleset_href", ""),
            "ruleset_name": rule.get("_ruleset_name", ""),
            "description": rule.get("description", "") or "",
        }
        for key, value in extra.items():
            detail[key] = value
        return detail

    # ═══════════════════════════════════════════════════════════════════════════════
    # Quarantine Feature: Labels and Workloads
    # ═══════════════════════════════════════════════════════════════════════════════

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

    def check_and_create_quarantine_labels(self):
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
            # href usually looks like /orgs/1/workloads/xx-yy-zz
            url = f"{self.api_cfg['url']}/api/v2{href}"
            status, body = self._request(url, timeout=10)
            if status == 200:
                return orjson.loads(body)
            logger.error(f"Get Workload Failed: {status} for {href}")
            return {}
        except Exception as e:
            logger.error(f"Get Workload Error: {e}")
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

    def fetch_managed_workloads(self, max_results: int = 10000) -> list:
        """Fetch all VEN-managed workloads (those with an active VEN agent)."""
        try:
            params = urllib.parse.urlencode({'managed': 'true', 'max_results': max_results})
            url = f"{self.base_url}/workloads?{params}"
            status, body = self._request(url, timeout=30)
            if status == 200:
                return orjson.loads(body)
            err_msg = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            logger.error(f"Fetch Managed Workloads Failed: {status} - {err_msg}")
            return []
        except Exception as e:
            logger.error(f"Fetch Managed Workloads Error: {e}")
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

    # ═══════════════════════════════════════════════════════════════════════════════
    # Rule Scheduler Features: RuleSet/Rule management, provisioning, notes
    # ═══════════════════════════════════════════════════════════════════════════════

    def _api_get(self, endpoint, timeout=15):
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

    def _api_put(self, endpoint, payload, timeout=15):
        """PUT a PCE API endpoint. Returns status_code."""
        url = f"{self.api_cfg['url']}/api/v2{endpoint}"
        try:
            status, body = self._request(url, method="PUT", data=payload, timeout=timeout)
            return status
        except Exception as e:
            logger.error(f"API PUT {endpoint}: {e}")
            return 0

    def _api_post(self, endpoint, payload, timeout=15):
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

    def update_label_cache(self, silent=False, force_refresh=True):
        """Cache labels, IP lists, and services for display resolution."""
        org = self.api_cfg['org_id']
        # Snapshot current state without holding the lock (reads are safe here)
        previous_state = (
            dict(self.label_cache),
            dict(self.service_ports_cache),
            dict(self._label_href_cache),
            dict(self._label_group_href_cache),
            dict(self._iplist_href_cache),
            self._query_lookup_cache_refreshed_at,
        )
        try:
            # I/O phase: fetch data from API without holding lock (network latency)
            if force_refresh:
                self.invalidate_query_lookup_cache()  # acquires _cache_lock internally (RLock)
            s_labels, d_labels = self._api_get(f"/orgs/{org}/labels?max_results=10000")
            s_groups, d_groups = self._api_get(f"/orgs/{org}/sec_policy/draft/label_groups?max_results=10000")
            s_iplists, d_iplists = self._api_get(f"/orgs/{org}/sec_policy/draft/ip_lists?max_results=10000")
            s_services, d_services = self._api_get(f"/orgs/{org}/sec_policy/draft/services?max_results=10000")

            # Write phase: acquire lock once to write all fetched data atomically
            with self._cache_lock:
                if s_labels == 200 and d_labels:
                    for i in d_labels:
                        label_str = f"{i.get('key')}:{i.get('value')}"
                        self.label_cache[i['href']] = label_str
                        self._label_href_cache[label_str] = i['href']

                if s_groups == 200 and d_groups:
                    for i in d_groups:
                        name = i.get('name')
                        if not name:
                            continue
                        val = f"[LabelGroup] {name}"
                        self.label_cache[i['href']] = val
                        self.label_cache[i['href'].replace('/draft/', '/active/')] = val
                        self._label_group_href_cache[name] = i['href']

                if s_iplists == 200 and d_iplists:
                    for i in d_iplists:
                        val = f"[IPList] {i.get('name')}"
                        self.label_cache[i['href']] = val
                        self.label_cache[i['href'].replace('/draft/', '/active/')] = val
                        if i.get('name'):
                            self._iplist_href_cache[i['name']] = i['href']

                if s_services == 200 and d_services:
                    for i in d_services:
                        name = i.get('name')
                        ports = []
                        port_defs = []  # raw port/proto dicts for query building
                        for svc in i.get('service_ports', []):
                            p = svc.get('port')
                            if p:
                                proto = "UDP" if svc.get('proto') == 17 else "TCP"
                                top = f"-{svc['to_port']}" if svc.get('to_port') else ""
                                ports.append(f"{proto}/{p}{top}")
                                # Build raw port definition for async queries
                                pd = {"port": p}
                                if svc.get('proto') is not None:
                                    pd["proto"] = svc['proto']
                                if svc.get('to_port'):
                                    pd["to_port"] = svc['to_port']
                                port_defs.append(pd)
                        port_str = f" ({','.join(ports)})" if ports else ""
                        val = f"{name}{port_str}"
                        self.label_cache[i['href']] = val
                        self.label_cache[i['href'].replace('/draft/', '/active/')] = val
                        # Cache resolved port definitions for per-rule queries
                        if port_defs:
                            self.service_ports_cache[i['href']] = port_defs
                            self.service_ports_cache[i['href'].replace('/draft/', '/active/')] = port_defs
                self._query_lookup_cache_refreshed_at = time.time()
        except Exception as e:
            # Restore previous state — update caches in-place to preserve TTLCache instances
            prev_label, prev_svc, prev_href, prev_grp, prev_ip, prev_ts = previous_state
            with self._cache_lock:
                self.label_cache.clear()
                self.label_cache.update(prev_label)
                self.service_ports_cache.clear()
                self.service_ports_cache.update(prev_svc)
                self._label_href_cache.clear()
                self._label_href_cache.update(prev_href)
                self._label_group_href_cache.clear()
                self._label_group_href_cache.update(prev_grp)
                self._iplist_href_cache.clear()
                self._iplist_href_cache.update(prev_ip)
                self._query_lookup_cache_refreshed_at = prev_ts
            if not silent:
                logger.warning(f"Label cache update error: {e}")

    def invalidate_labels(self) -> None:
        """Force the next label lookup to hit the PCE.

        Clears 3 of the 5 TTLCaches: label_cache, _label_href_cache, _label_group_href_cache.
        Deliberately DOES NOT clear service_ports_cache or _iplist_href_cache — those
        are populated by update_label_cache() but their content is keyed by href/name
        rather than label value, so they remain valid when only labels change.

        For a full cache flush (all 5 caches), use invalidate_query_lookup_cache().
        """
        with self._cache_lock:
            self.label_cache.clear()
            self._label_href_cache.clear()
            self._label_group_href_cache.clear()
        logger.debug("Label caches cleared (invalidate_labels)")

    def resolve_actor_str(self, actors):
        """Resolve actor list to human-readable string using label_cache."""
        if not actors:
            return "Any"
        names = []
        for a in actors:
            if 'label' in a:
                names.append(self.label_cache.get(a['label']['href'], "Label"))
            elif 'ip_list' in a:
                names.append(self.label_cache.get(a['ip_list']['href'], "IPList"))
            elif 'actors' in a:
                names.append(str(a.get('actors')))
        return ", ".join(names)

    def resolve_service_str(self, services):
        """Resolve service references to display strings."""
        if not services:
            return "All Services"
        svcs = []
        for s in services:
            if 'port' in s:
                p, proto = s.get('port'), "UDP" if s.get('proto') == 17 else "TCP"
                top = f"-{s['to_port']}" if s.get('to_port') else ""
                svcs.append(f"{proto}/{p}{top}")
            elif 'href' in s:
                svcs.append(self.label_cache.get(s['href'], f"Service({_extract_id(s['href'])})"))
            else:
                svcs.append("RefObj")
        return ", ".join(svcs)

    def get_all_rulesets(self, force_refresh=False):
        """Get all rulesets from PCE (cached unless force_refresh)."""
        if self.ruleset_cache and not force_refresh:
            return self.ruleset_cache
        org = self.api_cfg['org_id']
        status, data = self._api_get(f"/orgs/{org}/sec_policy/draft/rule_sets?max_results=10000")
        if status == 200 and data:
            self.ruleset_cache = data
            return self.ruleset_cache
        return []

    def get_active_rulesets(self):
        """Get all active (provisioned) rulesets with their rules.

        Uses /sec_policy/active/rule_sets to get the live policy state,
        unlike get_all_rulesets() which uses /draft/.
        Returns a list of ruleset dicts, each containing a 'rules' key.
        """
        org = self.api_cfg['org_id']
        status, data = self._api_get(
            f"/orgs/{org}/sec_policy/active/rule_sets?max_results=10000"
        )
        if status == 200 and data:
            return data
        logger.warning(f"get_active_rulesets: status={status}, returned empty list")
        return []

    # ── Per-rule async traffic query helpers (for Policy Usage Report) ──

    def submit_async_query(self, payload, query_type="rule_usage"):
        """Submit an async traffic query and return the job href, or None on failure."""
        url = f"{self.base_url}/traffic_flows/async_queries"
        status, body = self._request(url, method="POST", data=payload, timeout=10)
        if status not in (200, 201, 202):
            text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            logger.debug(f"submit_async_query failed: {status} {text[:200]}")
            return None
        result = orjson.loads(body)
        job_href = result.get("href")
        self._save_async_job_state(
            job_href,
            status=result.get("status", "submitted"),
            query_type=query_type,
            query_name=payload.get("query_name"),
            query_body=payload,
            query_signature=self._make_query_signature(payload),
            result_href=result.get("result"),
        )
        return job_href

    def _wait_for_async_query(self, job_href, timeout=120, compute_draft=False):
        """Poll an async query until completed/failed/timeout and return the last poll result."""
        poll_url = f"{self.api_cfg['url']}/api/v2{job_href}"
        max_polls = timeout // 2
        poll_result = {"status": "pending"}
        for _ in range(max_polls):
            time.sleep(2)
            poll_status, poll_body = self._request(poll_url, timeout=15)
            if poll_status != 200:
                continue
            poll_result = orjson.loads(poll_body)
            state = poll_result.get("status")
            self._save_async_job_state(
                job_href,
                status=state,
                rules_status=poll_result.get("rules"),
                result_href=poll_result.get("result"),
            )
            if state == "completed":
                break
            if state == "failed":
                logger.debug(f"Async query failed: {job_href}")
                return poll_result
        else:
            logger.debug(f"Async query timed out: {job_href}")
            self._save_async_job_state(job_href, status="timeout")
            return {"status": "timeout"}

        if compute_draft:
            update_rules_url = f"{self.api_cfg['url']}/api/v2{job_href}/update_rules"
            ur_status, ur_body = self._request(update_rules_url, method="PUT", data={}, timeout=30)
            if ur_status in (202, 204):
                time.sleep(10)
                for _ in range(max_polls):
                    poll_status, poll_body = self._request(poll_url, timeout=15)
                    if poll_status != 200:
                        time.sleep(2)
                        continue
                    poll_result = orjson.loads(poll_body)
                    state = poll_result.get("status")
                    rules_state = poll_result.get("rules")
                    self._save_async_job_state(
                        job_href,
                        status=state,
                        rules_status=rules_state,
                        result_href=poll_result.get("result"),
                    )
                    if state == "completed" and rules_state in (None, "", "completed"):
                        return poll_result
                    if state == "failed":
                        return poll_result
                    time.sleep(2)
            else:
                ur_text = ur_body.decode('utf-8', errors='replace') if isinstance(ur_body, bytes) else str(ur_body)
                logger.warning(f"update_rules returned {ur_status}: {ur_text[:200]}, proceeding without draft policy data")

        return poll_result

    def poll_async_query(self, job_href, timeout=120):
        """Poll an async query until completed/failed. Returns True if completed."""
        poll_result = self._wait_for_async_query(job_href, timeout=timeout, compute_draft=False)
        return poll_result.get("status") == "completed"

    def iter_async_query_results(self, job_href):
        """Download completed async query results and yield flow dicts one by one."""
        dl_url = f"{self.api_cfg['url']}/api/v2{job_href}/download"
        dl_status, dl_body = self._request(dl_url, timeout=60)
        if dl_status != 200:
            logger.debug(f"download_async_query failed: {dl_status}")
            self._save_async_job_state(job_href, download_status=f"failed:{dl_status}")
            return

        buffer = BytesIO(dl_body)

        def _parse_lines(lines_iter):
            for line in lines_iter:
                line = line.strip() if isinstance(line, str) else line.strip()
                if not line or line in (b'[', b']', '[', ']'):
                    continue
                if isinstance(line, bytes) and line.endswith(b','):
                    line = line[:-1]
                elif isinstance(line, str) and line.endswith(','):
                    line = line[:-1]
                try:
                    data = orjson.loads(line)
                    if isinstance(data, list):
                        for item in data:
                            yield item
                    else:
                        yield data
                except json.JSONDecodeError:
                    pass

        try:
            with gzip.GzipFile(fileobj=buffer, mode='rb') as f:
                for item in _parse_lines(f):
                    yield item
        except (gzip.BadGzipFile, OSError):
            buffer.seek(0)
            text_data = buffer.read().decode('utf-8', errors='replace')
            for item in _parse_lines(text_data.splitlines()):
                yield item

    def summarize_async_query(self, job_href):
        """Stream an async query and return count plus simple service breakdown."""
        count = 0
        flows_by_port = {}
        for flow in self.iter_async_query_results(job_href):
            count += 1
            svc = flow.get("service", {})
            port = svc.get("port") if isinstance(svc, dict) else None
            proto = svc.get("proto") if isinstance(svc, dict) else None
            if port is None:
                port = flow.get("dst_port")
            if proto is None:
                proto = flow.get("proto")

            if port is None and proto is None:
                key = "all"
            else:
                proto_label = proto
                try:
                    proto_int = int(proto)
                    if proto_int == 6:
                        proto_label = "tcp"
                    elif proto_int == 17:
                        proto_label = "udp"
                    elif proto_int == 1:
                        proto_label = "icmp"
                except (TypeError, ValueError):
                    proto_label = str(proto or "").lower() or "any"
                key = f"{port or 'all'}/{proto_label}"
            flows_by_port[key] = flows_by_port.get(key, 0) + 1

        self._save_async_job_state(
            job_href,
            download_status="completed",
            flow_count=count,
            flows_by_port=flows_by_port,
        )
        return {
            "count": count,
            "flows_by_port": flows_by_port,
        }

    def download_async_query(self, job_href):
        """Download completed async query results. Returns list of flow dicts."""
        flows = list(self.iter_async_query_results(job_href) or [])
        self._save_async_job_state(job_href, download_status="completed", flow_count=len(flows))
        return flows

    def download_async_query_csv(self, job_href, include_draft_policy=False):
        """Download completed async query results as raw CSV text."""
        dl_url = f"{self.api_cfg['url']}/api/v2{job_href}/download"
        if include_draft_policy:
            dl_url += "?include_draft_policy_in_csv=true"
        dl_status, dl_body = self._request(dl_url, timeout=60)
        if dl_status != 200:
            self._save_async_job_state(job_href, download_status=f"failed:{dl_status}")
            raise RuntimeError(f"CSV download failed with status {dl_status}")

        text = dl_body.decode("utf-8", errors="replace") if isinstance(dl_body, bytes) else str(dl_body)
        line_count = len([line for line in text.splitlines() if line.strip()])
        row_count = max(0, line_count - 1) if line_count else 0
        self._save_async_job_state(
            job_href,
            download_status="completed",
            download_format="csv",
            csv_row_count=row_count,
        )
        return {
            "text": text,
            "row_count": row_count,
        }

    def export_traffic_query_csv(
        self,
        start_time_str,
        end_time_str,
        policy_decisions=None,
        filters=None,
        output_dir="reports",
        filename=None,
        compute_draft=False,
    ):
        """Export a native-only Explorer traffic query to a raw CSV file."""
        if policy_decisions is None:
            policy_decisions = ["blocked", "potentially_blocked", "allowed"]

        query_spec = self.build_traffic_query_spec(filters)
        if query_spec.fallback_filters or query_spec.report_only_filters:
            unsupported = sorted(set(query_spec.fallback_filters) | set(query_spec.report_only_filters))
            raise ValueError(
                "Raw Explorer CSV export supports only native filters; unsupported filters: "
                + ", ".join(unsupported)
            )

        payload, effective_spec = self._build_native_traffic_payload(
            start_time_str,
            end_time_str,
            policy_decisions,
            filters=query_spec,
        )
        if effective_spec.fallback_filters or effective_spec.report_only_filters:
            unsupported = sorted(set(effective_spec.fallback_filters) | set(effective_spec.report_only_filters))
            raise ValueError(
                "Raw Explorer CSV export could not resolve filters natively: "
                + ", ".join(unsupported)
            )

        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        payload["query_name"] = f"Traffic_Raw_CSV_{ts}"
        job_href = self.submit_async_query(payload, query_type="traffic_raw_csv")
        if not job_href:
            raise RuntimeError("Failed to submit raw Explorer CSV query")

        poll_result = self._wait_for_async_query(job_href, timeout=300, compute_draft=compute_draft)
        status = poll_result.get("status")
        rules_status = poll_result.get("rules")
        if status != "completed":
            raise RuntimeError(f"Traffic CSV query did not complete successfully (status={status})")
        if compute_draft and rules_status not in (None, "", "completed"):
            raise RuntimeError(f"Traffic CSV draft computation did not complete (rules={rules_status})")

        csv_result = self.download_async_query_csv(job_href, include_draft_policy=compute_draft)
        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            filename = f"Illumio_Traffic_Explorer_Raw_{ts}.csv"
        output_path = os.path.join(output_dir, filename)
        with open(output_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(csv_result["text"])

        diagnostics = self.get_last_traffic_query_diagnostics()
        return {
            "path": output_path,
            "row_count": csv_result["row_count"],
            "job_href": job_href,
            "query_diagnostics": diagnostics,
            "policy_decisions": list(policy_decisions),
            "filters": dict(effective_spec.native_filters),
            "compute_draft": bool(compute_draft),
        }

    def _build_query_actors(self, actor_list, scope_labels=None):
        """Convert rule consumers/providers to async query sources/destinations include list.

        Workloader format: sources/destinations.include is a **nested array** —
        each inner array is an AND-group of labels. Multiple inner arrays = OR.

        Labels of the SAME dimension (e.g. multiple role labels) become separate inner
        arrays (OR semantics within dimension). Labels of DIFFERENT dimensions are
        AND-grouped within each inner array. Scope labels are only added for dimensions
        not already covered by the actor labels themselves.

        Args:
            actor_list:   rule's consumers or providers list from PCE API
            scope_labels: list of scope label dicts from the parent ruleset's first scope
                          (e.g. [{"label":{"href":"..."}}, ...])
        """
        import itertools
        from collections import defaultdict

        if not actor_list:
            return []

        def _label_dim(href):
            """Return dimension key (e.g. 'role','env') from label_cache, or unique fallback."""
            raw = self.label_cache.get(href, "")
            if raw and ":" in raw:
                return raw.split(":", 1)[0]
            return f"_unknown_{href}"   # treat unknown labels as independent dimensions

        # Build scope item list with dimensions
        scope_items_with_dim = []   # [(dim, item_dict), ...]
        if scope_labels:
            for sl in scope_labels:
                if "label" in sl:
                    dim = _label_dim(sl["label"].get("href", ""))
                    scope_items_with_dim.append((dim, {"label": sl["label"]}))
                elif "label_group" in sl:
                    scope_items_with_dim.append(("_lgroup", {"label_group": sl["label_group"]}))

        # Classify actor list into dimension-keyed label groups or non-label groups
        label_actors_by_dim = defaultdict(list)   # {dim: [item, ...]}
        non_label_groups = []

        for actor in actor_list:
            if actor.get("actors") == "ams":
                non_label_groups.append([{"actors": "ams"}])
            elif "label" in actor:
                dim = _label_dim(actor["label"].get("href", ""))
                label_actors_by_dim[dim].append({"label": actor["label"]})
            elif "label_group" in actor:
                label_actors_by_dim["_lgroup"].append({"label_group": actor["label_group"]})
            elif "ip_list" in actor:
                non_label_groups.append([{"ip_list": actor["ip_list"]}])
            elif "workload" in actor:
                non_label_groups.append([{"workload": actor["workload"]}])
            else:
                non_label_groups.append([actor])

        result = []

        if label_actors_by_dim:
            consumer_dims = set(label_actors_by_dim.keys())
            # Only include scope labels whose dimension is NOT covered by the actor labels
            scope_to_add = [item for dim, item in scope_items_with_dim
                            if dim not in consumer_dims]

            # Cartesian product across dimensions → each combo is one AND-group (inner array)
            # e.g. role:[A,B], env:[X] → [[env:X,role:A], [env:X,role:B]]
            dim_groups = list(label_actors_by_dim.values())
            for combo in itertools.product(*dim_groups):
                inner = list(scope_to_add) + list(combo)
                result.append(inner)

        elif scope_items_with_dim:
            # Actor list had only non-label entries; still add scope as one group
            result.append([item for _, item in scope_items_with_dim])

        result.extend(non_label_groups)
        return result

    def _build_query_services(self, rule):
        """Convert rule ingress_services to async query services include list.

        Named services (href-based) are resolved to their port/proto definitions
        via service_ports_cache, matching workloader behaviour. The async query
        API requires inline port definitions, not service hrefs.
        """
        services = []
        for svc in rule.get("ingress_services", []):
            if "href" in svc:
                # Resolve named service to port definitions
                resolved = self.service_ports_cache.get(svc["href"], [])
                if resolved:
                    services.extend(resolved)
                else:
                    logger.debug(f"Service href not in cache: {svc['href']}")
            elif "port" in svc:
                entry = {"port": svc["port"]}
                if "proto" in svc:
                    entry["proto"] = svc["proto"]
                if svc.get("to_port"):
                    entry["to_port"] = svc["to_port"]
                services.append(entry)
        return services

    def _build_rule_query_payload(self, rule, start_date, end_date):
        """Build the async query payload dict for a single rule.

        Returns a payload dict ready for submit_async_query(), or None on error.
        """
        try:
            scope_labels = rule.get("_ruleset_scopes", [])
            unscoped_consumers = rule.get("unscoped_consumers", False)
            consumer_scope = [] if unscoped_consumers else scope_labels

            sources_include      = self._build_query_actors(rule.get("consumers", []),
                                                            scope_labels=consumer_scope)
            destinations_include = self._build_query_actors(rule.get("providers", []),
                                                            scope_labels=scope_labels)
            services_include     = self._build_query_services(rule)

            rule_href = rule.get('href', '')
            logger.debug(f"Rule payload {rule_href}: "
                         f"src={json.dumps(sources_include)}, "
                         f"dst={json.dumps(destinations_include)}, "
                         f"svc={json.dumps(services_include)}")
            return {
                "query_name":  f"policy-usage-{rule_href}",
                "start_date":  start_date,
                "end_date":    end_date,
                "policy_decisions": [],
                "max_results": 10000,
                "sources":      {"include": sources_include,      "exclude": []},
                "destinations": {"include": destinations_include, "exclude": []},
                "services":     {"include": services_include,     "exclude": []},
                "exclude_workloads_from_ip_list_query": False,
            }
        except Exception as e:
            logger.warning(f"_build_rule_query_payload error for {rule.get('href')}: {e}")
            return None

    def get_rule_traffic_count(self, rule, start_date, end_date):
        """Query traffic count for a single rule (sequential, for compatibility).

        Returns the number of matching flows, or 0 on any failure.
        """
        try:
            payload = self._build_rule_query_payload(rule, start_date, end_date)
            if payload is None:
                return 0
            cached = self.find_cached_async_summary(payload, query_type="rule_usage")
            if cached:
                return cached["count"]
            job_href = self.submit_async_query(payload)
            if not job_href:
                return 0
            if not self.poll_async_query(job_href, timeout=120):
                return 0
            return self.summarize_async_query(job_href)["count"]
        except Exception as e:
            logger.warning(f"get_rule_traffic_count error for {rule.get('href')}: {e}")
            return 0

    def batch_get_rule_traffic_counts(
        self,
        rules: list,
        start_date: str,
        end_date: str,
        max_concurrent: int = 10,
        on_progress=None,
    ) -> tuple:
        """Submit all rule queries in parallel, poll concurrently, download in parallel.

        Three-phase approach (matches workloader behaviour):
          Phase 1 — Submit all async queries simultaneously.
          Phase 2 — Poll all pending jobs concurrently until every job resolves.
          Phase 3 — Download all completed results simultaneously.

        Args:
            rules:          Flat list of rule dicts (from _build_baseline).
            start_date:     ISO-8601 start date string.
            end_date:       ISO-8601 end date string.
            max_concurrent: Thread pool size (default 10).
            on_progress:    Optional callable(msg: str) for progress updates.

        Returns:
            (hit_hrefs: set, hit_counts: dict[rule_href -> int])
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self._maybe_prune_async_job_states()
        total = len(rules)
        if not total:
            self.last_rule_usage_batch_stats = {
                "total_rules": 0,
                "cached_rules": 0,
                "submitted_rules": 0,
                "completed_jobs": 0,
                "failed_jobs": 0,
                "pending_jobs": 0,
                "downloaded_jobs": 0,
                "hit_rules": 0,
                "unused_rules": 0,
                "flows_by_port_totals": {},
                "top_hit_ports": [],
                "hit_rule_port_details": [],
                "reused_rule_details": [],
                "pending_rule_details": [],
                "failed_rule_details": [],
            }
            return set(), {}

        def _progress(msg):
            if on_progress:
                on_progress(msg)

        hit_hrefs: set = set()
        hit_counts: dict = {}
        cached_hits = 0
        resumed_jobs = 0
        retried_jobs = 0
        pending_rules = []
        reused_rule_details = []
        rule_port_summaries = {}

        for rule in rules:
            payload = self._build_rule_query_payload(rule, start_date, end_date)
            if payload is None:
                continue
            cached = self.find_cached_async_summary(payload, query_type="rule_usage")
            if cached:
                cached_hits += 1
                href = rule.get("href", "")
                count = cached["count"]
                if count > 0:
                    hit_hrefs.add(href)
                    hit_counts[href] = count
                    rule_port_summaries[href] = dict(cached.get("flows_by_port", {}) or {})
                self._save_async_job_state(
                    cached["job_href"],
                    reused_at=self._utc_now_iso(),
                    reused_for=payload.get("query_name"),
                )
                reused_rule_details.append(self._rule_usage_detail(
                    rule,
                    status="reused",
                    query_name=payload.get("query_name", ""),
                    job_href=cached["job_href"],
                    cached_count=count,
                    cached_updated_at=cached.get("updated_at", ""),
                    flows_by_port=dict(cached.get("flows_by_port", {}) or {}),
                    top_hit_ports=self._format_flows_by_port(cached.get("flows_by_port", {})),
                ))
            else:
                existing_job = self.find_latest_async_job(payload, query_type="rule_usage")
                if existing_job:
                    existing_status = existing_job.get("status")
                    existing_download = existing_job.get("download_status", "")
                    if existing_status in {"queued", "pending", "submitted"} and existing_download != "completed":
                        pending_rules.append((rule, payload, existing_job["job_href"]))
                        resumed_jobs += 1
                        continue
                    if existing_status in {"failed", "timeout"}:
                        retry_href = self.retry_async_query_job(existing_job["job_href"])
                        pending_rules.append((rule, payload, retry_href))
                        retried_jobs += 1
                        continue
                pending_rules.append((rule, payload, None))

        if cached_hits:
            _progress(f"Reused {cached_hits}/{total} cached rule summaries...")

        # ── Phase 1: Submit ────────────────────────────────────────────────
        job_map = {}   # {async_job_href: {"rule": rule, "payload": payload}}
        submitted_count = 0

        def _submit(rule_and_payload):
            rule, payload, existing_job_href = rule_and_payload
            if existing_job_href:
                return existing_job_href, rule, payload
            return self.submit_async_query(payload), rule, payload

        with ThreadPoolExecutor(max_workers=max_concurrent) as ex:
            futs = {ex.submit(_submit, item): item[0] for item in pending_rules}
            for fut in as_completed(futs):
                job_href, rule, payload = fut.result()
                submitted_count += 1
                if job_href:
                    job_map[job_href] = {"rule": rule, "payload": payload}
                _progress(f"Submitting {submitted_count}/{len(pending_rules)}...")

        if not job_map:
            flows_by_port_totals = {}
            hit_rule_port_details = []
            for rule in rules:
                href = rule.get("href", "")
                if href not in hit_counts:
                    continue
                port_map = dict(rule_port_summaries.get(href, {}) or {})
                for port_proto, count in port_map.items():
                    try:
                        flows_by_port_totals[port_proto] = flows_by_port_totals.get(port_proto, 0) + int(count or 0)
                    except (TypeError, ValueError):
                        continue
                hit_rule_port_details.append(self._rule_usage_detail(
                    rule,
                    status="hit",
                    hit_count=int(hit_counts.get(href, 0) or 0),
                    flows_by_port=port_map,
                    top_hit_ports=self._format_flows_by_port(port_map),
                ))
            top_hit_ports = [
                {"port_proto": port_proto, "flow_count": count}
                for port_proto, count in self._sorted_flows_by_port_items(flows_by_port_totals, limit=10)
            ]
            self.last_rule_usage_batch_stats = {
                "total_rules": total,
                "cached_rules": cached_hits,
                "submitted_rules": 0,
                "completed_jobs": 0,
                "failed_jobs": 0,
                "pending_jobs": 0,
                "downloaded_jobs": 0,
                "hit_rules": len(hit_hrefs),
                "unused_rules": total - len(hit_hrefs),
                "flows_by_port_totals": flows_by_port_totals,
                "top_hit_ports": top_hit_ports,
                "hit_rule_port_details": hit_rule_port_details,
                "reused_rule_details": reused_rule_details,
                "pending_rule_details": [],
                "failed_rule_details": [],
                "resumed_jobs": resumed_jobs,
                "retried_jobs": retried_jobs,
            }
            logger.info(
                "batch_get_rule_traffic_counts: %s rules -> %s hit, %s unused, all from cache",
                total, len(hit_hrefs), total - len(hit_hrefs)
            )
            return hit_hrefs, hit_counts

        _progress(f"Polling {len(job_map)} jobs (0/{len(job_map)} done)...")

        # ── Phase 2: Poll ──────────────────────────────────────────────────
        pending   = set(job_map.keys())
        completed = set()
        failed = set()
        deadline  = time.time() + 300   # 5-minute hard timeout

        def _poll_one(job_href):
            url = f"{self.api_cfg['url']}/api/v2{job_href}"
            status, body = self._request(url, timeout=15)
            if status != 200:
                return job_href, "pending"
            try:
                poll_result = orjson.loads(body)
                state = poll_result.get("status", "pending")
                self._save_async_job_state(
                    job_href,
                    status=state,
                    rules_status=poll_result.get("rules"),
                    result_href=poll_result.get("result"),
                )
            except Exception as exc:
                logger.warning("Failed to parse async job poll response for %s: %s", job_href, exc)
                state = "pending"
            return job_href, state

        while pending and time.time() < deadline:
            time.sleep(2)
            pending_list = list(pending)
            with ThreadPoolExecutor(max_workers=min(max_concurrent, len(pending_list))) as ex:
                poll_results = list(ex.map(_poll_one, pending_list))

            still_pending = set()
            for job_href, state in poll_results:
                if state == "completed":
                    completed.add(job_href)
                elif state == "failed":
                    logger.debug(f"Async query failed: {job_href}")
                    failed.add(job_href)
                else:
                    still_pending.add(job_href)
            pending = still_pending
            _progress(f"Polling... {len(completed)}/{len(job_map)} done, "
                      f"{len(pending)} pending")

        # ── Phase 3: Download ──────────────────────────────────────────────
        downloaded = 0
        failed_rule_details = []
        pending_rule_details = []

        def _download(job_href):
            summary = self.summarize_async_query(job_href)
            return job_href, summary

        with ThreadPoolExecutor(max_workers=max_concurrent) as ex:
            futs = {ex.submit(_download, jh): jh for jh in completed}
            for fut in as_completed(futs):
                job_href, summary = fut.result()
                job_info = job_map[job_href]
                rule = job_info["rule"]
                downloaded += 1
                count = int(summary.get("count", 0) or 0)
                if count > 0:
                    href = rule.get("href", "")
                    hit_hrefs.add(href)
                    hit_counts[href] = count
                    rule_port_summaries[href] = dict(summary.get("flows_by_port", {}) or {})
                _progress(f"Downloading {downloaded}/{len(completed)}...")

        for job_href in sorted(failed):
            job_info = job_map.get(job_href, {})
            failed_rule_details.append(self._rule_usage_detail(
                job_info.get("rule", {}),
                status="failed",
                job_href=job_href,
                query_name=job_info.get("payload", {}).get("query_name", ""),
            ))

        for job_href in sorted(pending):
            job_info = job_map.get(job_href, {})
            pending_rule_details.append(self._rule_usage_detail(
                job_info.get("rule", {}),
                status="pending",
                job_href=job_href,
                query_name=job_info.get("payload", {}).get("query_name", ""),
            ))

        flows_by_port_totals = {}
        hit_rule_port_details = []
        for rule in rules:
            href = rule.get("href", "")
            if href not in hit_counts:
                continue
            port_map = dict(rule_port_summaries.get(href, {}) or {})
            for port_proto, count in port_map.items():
                try:
                    flows_by_port_totals[port_proto] = flows_by_port_totals.get(port_proto, 0) + int(count or 0)
                except (TypeError, ValueError):
                    continue
            hit_rule_port_details.append(self._rule_usage_detail(
                rule,
                status="hit",
                hit_count=int(hit_counts.get(href, 0) or 0),
                flows_by_port=port_map,
                top_hit_ports=self._format_flows_by_port(port_map),
            ))

        top_hit_ports = [
            {"port_proto": port_proto, "flow_count": count}
            for port_proto, count in self._sorted_flows_by_port_items(flows_by_port_totals, limit=10)
        ]

        logger.info(f"batch_get_rule_traffic_counts: {total} rules → "
                    f"{len(hit_hrefs)} hit, {total - len(hit_hrefs)} unused")
        self.last_rule_usage_batch_stats = {
            "total_rules": total,
            "cached_rules": cached_hits,
            "submitted_rules": len(pending_rules),
            "completed_jobs": len(completed),
            "failed_jobs": len(failed),
            "pending_jobs": len(pending),
            "downloaded_jobs": downloaded,
            "hit_rules": len(hit_hrefs),
            "unused_rules": total - len(hit_hrefs),
            "flows_by_port_totals": flows_by_port_totals,
            "top_hit_ports": top_hit_ports,
            "hit_rule_port_details": hit_rule_port_details,
            "reused_rule_details": reused_rule_details,
            "pending_rule_details": pending_rule_details,
            "failed_rule_details": failed_rule_details,
            "resumed_jobs": resumed_jobs,
            "retried_jobs": retried_jobs,
        }
        return hit_hrefs, hit_counts

    def search_rulesets(self, keyword):
        """Search cached rulesets by keyword."""
        all_rs = self.get_all_rulesets()
        return [rs for rs in all_rs if keyword.lower() in rs.get('name', '').lower()]

    def get_ruleset_by_id(self, rs_id):
        """Get a single ruleset by ID."""
        org = self.api_cfg['org_id']
        status, data = self._api_get(f"/orgs/{org}/sec_policy/draft/rule_sets/{rs_id}")
        return data if status == 200 else None

    def provision_changes(self, rs_href):
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

    def has_draft_changes(self, href):
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

    def toggle_and_provision(self, href, target_enabled, is_ruleset=False):
        """Enable/disable a rule or ruleset and provision the change."""
        draft_href = href.replace("/active/", "/draft/")
        
        # Check if it (or parent) has pending changes
        if self.has_draft_changes(draft_href):
            logger.warning(f"toggle_and_provision aborted: {_extract_id(href)} has pending draft changes.")
            return False

        put_status = self._api_put(draft_href, {"enabled": target_enabled})
        if put_status != 204:
            logger.error(f"Toggle failed for {_extract_id(href)}: status {put_status}")
            return False
        rs_href = draft_href if is_ruleset else "/".join(draft_href.split("/")[:7])
        return self.provision_changes(rs_href)

    def update_rule_note(self, href, schedule_info, remove=False):
        """Add/update/remove schedule tags in a rule's description field on the PCE."""
        draft_href = href.replace("/active/", "/draft/")
        status, data = self._api_get(draft_href)
        if status != 200 or not data:
            return False

        has_pending_draft = self.has_draft_changes(draft_href)

        current_desc = data.get('description', '') or ''

        # Strip existing schedule tags
        clean_desc = re.sub(r'\s*\[📅[^\]]*\]', '', current_desc)
        clean_desc = re.sub(r'\s*\[⏳[^\]]*\]', '', clean_desc)
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
            # Successfully updated rule note but skipped provision due to pending changes
            return True
        return False

    def get_live_item(self, href):
        """Try both active and draft paths to find the item. Returns (status, data) or (0, None)."""
        # Try active first
        active_href = href.replace("/draft/", "/active/")
        status, data = self._api_get(active_href)
        if status == 200:
            return status, data
        # Fallback to draft
        draft_href = href.replace("/active/", "/draft/")
        if draft_href != active_href:
            status, data = self._api_get(draft_href)
            if status == 200:
                return status, data
        return status, data

    def get_provision_state(self, href):
        """Check provision state: 'active' if provisioned, 'draft' if draft-only, 'unknown' on error."""
        active_href = href.replace("/draft/", "/active/")
        url = f"{self.api_cfg['url']}/api/v2{active_href}"
        try:
            status, body = self._request(url, timeout=10)
            if status == 200:
                return 'active'
            return 'draft'
        except Exception as exc:
            logger.debug("Could not determine provision state for %s: %s", href, exc)
            return 'unknown'

    def is_provisioned(self, href):
        """Check if a rule/ruleset has been provisioned."""
        return self.get_provision_state(href) == 'active'
