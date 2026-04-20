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
import os
import re
import threading
import time
import urllib.parse

import orjson
import requests
from cachetools import TTLCache
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.api.async_jobs import AsyncJobManager
from src.api.labels import LabelResolver
from src.api.traffic_query import (
    MAX_TRAFFIC_RESULTS,
    TrafficQueryBuilder,
    TrafficQuerySpec,
    _TRAFFIC_FILTER_CAPABILITIES,
)
from src.href_utils import extract_id as _extract_id
from src.i18n import t
from src.utils import Colors

MAX_RETRIES = 3
_ASYNC_JOB_STATE_KEY = "async_query_jobs"
_QUERY_LOOKUP_CACHE_TTL_SECONDS = 300
_LABEL_CACHE_TTL_SECONDS = 900  # 15 minutes — Phase 2 Q5 fix
_ASYNC_JOB_CACHE_MAX_AGE_DAYS = 7
_ASYNC_JOB_PRUNE_INTERVAL_SECONDS = 3600


class EventFetchError(RuntimeError):
    """Raised when the PCE events API cannot be fetched safely."""

    def __init__(self, status: int, message: str):
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

    def __init__(self, config_manager):
        self.cm = config_manager
        self.api_cfg = self.cm.config["api"]
        self.base_url = f"{self.api_cfg['url']}/api/v2/orgs/{self.api_cfg['org_id']}"
        self._auth_header = self._build_auth_header()

        # ── Caches (TTL) + lock — owned by facade so tests can mutate directly ──
        # Use time.time (wall clock) so freezegun can control expiry in tests.
        self._cache_lock = threading.RLock()  # RLock: re-entrant (update_label_cache calls invalidate_*)
        self.label_cache = TTLCache(maxsize=10000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self.ruleset_cache = []
        self.service_ports_cache = TTLCache(maxsize=5000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._label_href_cache = TTLCache(maxsize=10000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._label_group_href_cache = TTLCache(maxsize=1000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)
        self._iplist_href_cache = TTLCache(maxsize=5000, ttl=_LABEL_CACHE_TTL_SECONDS, timer=time.time)

        # Diagnostics (read via getter / written by domain classes)
        self.last_traffic_query_diagnostics = {}
        self.last_rule_usage_batch_stats = {}

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
        self._session.headers.update({
            "Authorization": self._auth_header,
            "Accept": "application/json",
        })
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=1.0,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "HEAD"]),
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

    # ═══════════════════════════════════════════════════════════════════════
    # HTTP core (stays on facade — shared infrastructure)
    # ═══════════════════════════════════════════════════════════════════════

    def _build_auth_header(self):
        credentials = f"{self.api_cfg['key']}:{self.api_cfg['secret']}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        return f"Basic {encoded}"

    def _request(self, url, method="GET", data=None, headers=None, timeout=15, stream=False, rate_limit: bool = False):
        """Core HTTP helper using requests.Session + urllib3 Retry.

        Returns (status_code, response_body_bytes | response_object).
        For stream=True, returns (status_code, raw requests.Response).
        """
        if rate_limit:
            from src.pce_cache.rate_limiter import get_rate_limiter
            rpm = 400
            try:
                from src.config import ConfigManager
                cm = ConfigManager()
                rpm = cm.models.pce_cache.rate_limit_per_minute
            except Exception:
                pass
            if not get_rate_limiter(rate_per_minute=rpm).acquire(timeout=30.0):
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

        if stream:
            return resp.status_code, resp
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

    # ═══════════════════════════════════════════════════════════════════════
    # Events (stays on facade — not part of any moved domain)
    # ═══════════════════════════════════════════════════════════════════════

    def _build_events_url(self, start_time_str, end_time_str=None, max_results=5000):
        params = {
            "timestamp[gte]": start_time_str,
            "max_results": max_results,
        }
        if end_time_str:
            params["timestamp[lte]"] = end_time_str
        return f"{self.base_url}/events?{urllib.parse.urlencode(params)}"

    def fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000):
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

    # ═══════════════════════════════════════════════════════════════════════
    # LabelResolver delegation wrappers
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _normalize_label_filter(label_str):
        return LabelResolver._normalize_label_filter(label_str)

    @staticmethod
    def _is_ip_literal(value):
        return LabelResolver._is_ip_literal(value)

    @staticmethod
    def _is_href(value):
        return LabelResolver._is_href(value)

    @staticmethod
    def _normalize_str_list(value):
        return LabelResolver._normalize_str_list(value)

    @staticmethod
    def _normalize_bool(value):
        return LabelResolver._normalize_bool(value)

    @staticmethod
    def _normalize_transmission_values(value):
        return LabelResolver._normalize_transmission_values(value)

    @staticmethod
    def _parse_port_range_entry(value, default_proto=None):
        return LabelResolver._parse_port_range_entry(value, default_proto=default_proto)

    @staticmethod
    def _dedupe_query_group(items):
        return LabelResolver._dedupe_query_group(items)

    def invalidate_query_lookup_cache(self):
        return self._labels.invalidate_query_lookup_cache()

    def _query_lookup_cache_is_stale(self):
        return self._labels._query_lookup_cache_is_stale()

    def _ensure_query_lookup_cache(self, force_refresh=False):
        return self._labels._ensure_query_lookup_cache(force_refresh=force_refresh)

    def update_label_cache(self, silent=False, force_refresh=True):
        return self._labels.update_label_cache(silent=silent, force_refresh=force_refresh)

    def invalidate_labels(self) -> None:
        return self._labels.invalidate_labels()

    def _resolve_actor_filter(self, value):
        return self._labels._resolve_actor_filter(value)

    def _resolve_label_filter_to_actor(self, label_filter):
        return self._labels._resolve_label_filter_to_actor(label_filter)

    def _resolve_label_group_filter_to_actor(self, label_group_filter):
        return self._labels._resolve_label_group_filter_to_actor(label_group_filter)

    def _resolve_ip_filter_to_actor(self, ip_filter):
        return self._labels._resolve_ip_filter_to_actor(ip_filter)

    def resolve_actor_str(self, actors):
        return self._labels.resolve_actor_str(actors)

    def resolve_service_str(self, services):
        return self._labels.resolve_service_str(services)

    # ═══════════════════════════════════════════════════════════════════════
    # TrafficQueryBuilder delegation wrappers
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _clone_query_spec(spec):
        return TrafficQueryBuilder._clone_query_spec(spec)

    def get_traffic_query_capability_matrix(self):
        return self._traffic.get_traffic_query_capability_matrix()

    def build_traffic_query_spec(self, filters=None):
        return self._traffic.build_traffic_query_spec(filters)

    def _build_native_traffic_payload(self, start_time_str, end_time_str, policy_decisions, filters=None):
        return self._traffic._build_native_traffic_payload(
            start_time_str, end_time_str, policy_decisions, filters=filters
        )

    def _submit_and_stream_async_query(self, payload, compute_draft=False):
        yield from self._traffic._submit_and_stream_async_query(payload, compute_draft=compute_draft)

    def execute_traffic_query_stream(self, start_time_str, end_time_str, policy_decisions, filters=None, compute_draft=False):
        yield from self._traffic.execute_traffic_query_stream(
            start_time_str, end_time_str, policy_decisions, filters=filters, compute_draft=compute_draft
        )

    @staticmethod
    def _flow_matches_filters(flow, filters):
        return TrafficQueryBuilder._flow_matches_filters(flow, filters)

    def fetch_traffic_for_report(self, start_time_str, end_time_str, policy_decisions=None, filters=None):
        return self._traffic.fetch_traffic_for_report(
            start_time_str, end_time_str, policy_decisions=policy_decisions, filters=filters
        )

    def get_last_traffic_query_diagnostics(self):
        return self._traffic.get_last_traffic_query_diagnostics()

    def get_last_rule_usage_batch_stats(self):
        return self._traffic.get_last_rule_usage_batch_stats()

    @staticmethod
    def _sorted_flows_by_port_items(flows_by_port, limit=None):
        return TrafficQueryBuilder._sorted_flows_by_port_items(flows_by_port, limit=limit)

    @classmethod
    def _format_flows_by_port(cls, flows_by_port, limit=3):
        return TrafficQueryBuilder._format_flows_by_port(flows_by_port, limit=limit)

    @staticmethod
    def _rule_usage_detail(rule, **extra):
        return TrafficQueryBuilder._rule_usage_detail(rule, **extra)

    def _build_query_actors(self, actor_list, scope_labels=None):
        return self._traffic._build_query_actors(actor_list, scope_labels=scope_labels)

    def _build_query_services(self, rule):
        return self._traffic._build_query_services(rule)

    def _build_rule_query_payload(self, rule, start_date, end_date):
        return self._traffic._build_rule_query_payload(rule, start_date, end_date)

    def get_rule_traffic_count(self, rule, start_date, end_date):
        return self._traffic.get_rule_traffic_count(rule, start_date, end_date)

    def batch_get_rule_traffic_counts(self, rules, start_date, end_date, max_concurrent=10, on_progress=None):
        return self._traffic.batch_get_rule_traffic_counts(
            rules, start_date, end_date,
            max_concurrent=max_concurrent,
            on_progress=on_progress,
        )

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
    def _utc_now_iso():
        return AsyncJobManager._utc_now_iso()

    def _save_async_job_state(self, job_href, **fields):
        return self._jobs._save_async_job_state(job_href, **fields)

    @staticmethod
    def _make_query_signature(payload):
        return AsyncJobManager._make_query_signature(payload)

    @staticmethod
    def _job_timestamp_epoch(job):
        return AsyncJobManager._job_timestamp_epoch(job)

    def _load_async_job_states(self):
        return self._jobs._load_async_job_states()

    def _job_age_seconds(self, job):
        return self._jobs._job_age_seconds(job)

    def _job_is_stale(self, job, max_age_days=None):
        return self._jobs._job_is_stale(job, max_age_days=max_age_days)

    def _maybe_prune_async_job_states(self):
        return self._jobs._maybe_prune_async_job_states()

    def find_cached_async_summary(self, payload, query_type="rule_usage"):
        return self._jobs.find_cached_async_summary(payload, query_type=query_type)

    def find_latest_async_job(self, payload, query_type="rule_usage"):
        return self._jobs.find_latest_async_job(payload, query_type=query_type)

    def resume_async_query_job(self, job_href, timeout=120, summarize=False, compute_draft=False):
        return self._jobs.resume_async_query_job(
            job_href, timeout=timeout, summarize=summarize, compute_draft=compute_draft
        )

    def retry_async_query_job(self, job_href):
        return self._jobs.retry_async_query_job(job_href)

    def prune_async_job_states(self, max_age_days=7, keep_recent_completed=200):
        return self._jobs.prune_async_job_states(
            max_age_days=max_age_days, keep_recent_completed=keep_recent_completed
        )

    def submit_async_query(self, payload, query_type="rule_usage"):
        return self._jobs.submit_async_query(payload, query_type=query_type)

    def _wait_for_async_query(self, job_href, timeout=120, compute_draft=False):
        return self._jobs._wait_for_async_query(job_href, timeout=timeout, compute_draft=compute_draft)

    def poll_async_query(self, job_href, timeout=120):
        return self._jobs.poll_async_query(job_href, timeout=timeout)

    def iter_async_query_results(self, job_href):
        yield from self._jobs.iter_async_query_results(job_href)

    def summarize_async_query(self, job_href):
        return self._jobs.summarize_async_query(job_href)

    def download_async_query(self, job_href):
        return self._jobs.download_async_query(job_href)

    def download_async_query_csv(self, job_href, include_draft_policy=False):
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

    # ═══════════════════════════════════════════════════════════════════════
    # Rule Scheduler Features: RuleSet/Rule management, provisioning, notes
    # ═══════════════════════════════════════════════════════════════════════

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
        """Get all active (provisioned) rulesets with their rules."""
        org = self.api_cfg['org_id']
        status, data = self._api_get(
            f"/orgs/{org}/sec_policy/active/rule_sets?max_results=10000"
        )
        if status == 200 and data:
            return data
        logger.warning(f"get_active_rulesets: status={status}, returned empty list")
        return []

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
            return True
        return False

    def get_live_item(self, href):
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
            logger.debug("Could not determine provision state for {}: {}", href, exc)
            return 'unknown'

    def is_provisioned(self, href):
        """Check if a rule/ruleset has been provisioned."""
        return self.get_provision_state(href) == 'active'


__all__ = [
    "ApiClient",
    "EventFetchError",
    "TrafficQuerySpec",
    "MAX_TRAFFIC_RESULTS",
    "MAX_RETRIES",
]
