"""TrafficQueryBuilder — traffic query payload construction + execution.

Extracted from ApiClient in Phase 9 Task 6. Builds workloader-style async
traffic-flow payloads (native filters), executes them via the async query API
(submit / poll / download / stream), applies any fallback Python-side filters,
and exposes per-rule traffic count batch APIs used by the Policy Usage Report.

Delegates to:
  * self._client._labels (LabelResolver) — label/IP/service lookups
  * self._client._jobs   (AsyncJobManager) — async job submit / poll / download
  * self._client._request(...)             — HTTP layer on the facade
"""
from __future__ import annotations

import gzip
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO

import orjson
from loguru import logger

from src.i18n import t

MAX_TRAFFIC_RESULTS = 200000

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


@dataclass
class TrafficQuerySpec:
    raw_filters: dict = field(default_factory=dict)
    native_filters: dict = field(default_factory=dict)
    fallback_filters: dict = field(default_factory=dict)
    report_only_filters: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)


class TrafficQueryBuilder:
    """Owns traffic query payload construction + execution for ApiClient."""

    def __init__(self, client):
        self._client = client

    # ── Spec construction ───────────────────────────────────────────────

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

    # ── Native traffic payload builder ───────────────────────────────────

    def _build_native_traffic_payload(self, start_time_str, end_time_str, policy_decisions, filters=None):
        """Build a workloader-style async query payload for general traffic queries."""
        labels = self._client._labels
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
            if not labels._normalize_bool(value):
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
                    resolved = labels._resolve_actor_filter(entry)
                    if not resolved:
                        unresolved = True
                        break
                    resolved_group.append(resolved)
                if unresolved:
                    break
                built_groups.append(labels._dedupe_query_group(resolved_group))

            if unresolved or not built_groups:
                _record_unresolved(key, groups)
                _consume_keys((key,))
                return

            payload[side]["include"].extend(built_groups)
            _record_consumed(key, groups)
            _consume_keys((key,))

        include_specs = [
            (("src_label", "src_labels"), "sources", labels._resolve_label_filter_to_actor),
            (("src_label_group", "src_label_groups"), "sources", labels._resolve_label_group_filter_to_actor),
            (("dst_label", "dst_labels"), "destinations", labels._resolve_label_filter_to_actor),
            (("dst_label_group", "dst_label_groups"), "destinations", labels._resolve_label_group_filter_to_actor),
            (("src_ip_in", "src_ip"), "sources", labels._resolve_ip_filter_to_actor),
            (("dst_ip_in", "dst_ip"), "destinations", labels._resolve_ip_filter_to_actor),
        ]
        exclude_specs = [
            (("ex_src_label", "ex_src_labels"), "sources", labels._resolve_label_filter_to_actor),
            (("ex_src_label_group", "ex_src_label_groups"), "sources", labels._resolve_label_group_filter_to_actor),
            (("ex_dst_label", "ex_dst_labels"), "destinations", labels._resolve_label_filter_to_actor),
            (("ex_dst_label_group", "ex_dst_label_groups"), "destinations", labels._resolve_label_group_filter_to_actor),
            (("ex_src_ip",), "sources", labels._resolve_ip_filter_to_actor),
            (("ex_dst_ip",), "destinations", labels._resolve_ip_filter_to_actor),
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
            payload[side]["include"].append(labels._dedupe_query_group(resolved_items))
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
            payload[side]["exclude"].extend(labels._dedupe_query_group(resolved_items))
            for key in used_keys:
                _record_consumed(key, spec.native_filters.get(key))
            _consume_keys(used_keys)

        for key, side in (("ex_src_ams", "sources"), ("ex_dst_ams", "destinations")):
            if key not in native_filters:
                continue
            value = native_filters.get(key)
            if not labels._normalize_bool(value):
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
                parsed = labels._parse_port_range_entry(entry, default_proto=default_proto)
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

        for key, field_, target in (
            ("process_name", "process_name", "include"),
            ("windows_service_name", "windows_service_name", "include"),
            ("ex_process_name", "process_name", "exclude"),
            ("ex_windows_service_name", "windows_service_name", "exclude"),
        ):
            value = native_filters.get(key)
            if value:
                payload["services"][target].append({field_: str(value).strip()})
                _record_consumed(key, spec.native_filters.get(key))
                _consume_keys((key,))

        transmission_values = labels._normalize_transmission_values(
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
            payload["exclude_workloads_from_ip_list_query"] = labels._normalize_bool(
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

    # ── Submit+stream flow ───────────────────────────────────────────────

    def _submit_and_stream_async_query(self, payload, compute_draft=False):
        """Submit an async query and stream its downloaded results."""
        c = self._client
        url = f"{c.base_url}/traffic_flows/async_queries"
        status, body = c._request(url, method="POST", data=payload, timeout=10)
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

        poll_url = f"{c.api_cfg['url']}/api/v2{job_url}"
        for _ in range(60):
            time.sleep(2)
            poll_status, poll_body = c._request(poll_url, timeout=15)
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
            update_rules_url = f"{c.api_cfg['url']}/api/v2{job_url}/update_rules"
            logger.info(f"Calling update_rules: PUT {update_rules_url}")
            ur_status, ur_body = c._request(update_rules_url, method="PUT", data={}, timeout=30)
            logger.info(f"update_rules response: HTTP {ur_status}")
            if ur_status in (202, 204):
                ur_text = ur_body.decode('utf-8', errors='replace') if isinstance(ur_body, bytes) else str(ur_body)
                logger.info(f"update_rules accepted (HTTP {ur_status}), body: {ur_text[:300]}")
                print(t('waiting_traffic', default='Waiting for traffic calculation...'), end="", flush=True)
                time.sleep(10)
                for attempt in range(30):
                    poll_status, poll_body = c._request(poll_url, timeout=15)
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

        dl_url = f"{c.api_cfg['url']}/api/v2{job_url}/download"
        dl_status, dl_body = c._request(dl_url, timeout=60)
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
        """Executes an async traffic query and yields results row by row."""
        c = self._client
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
            c.last_traffic_query_diagnostics = dict(effective_spec.diagnostics)
            logger.info(
                "Traffic query mode: native={} native_filters={} fallback_filters={} report_only_filters={} unresolved_native={}",
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

    # ── Python-side filter for report ───────────────────────────────────

    @staticmethod
    def _flow_matches_filters(flow: dict, filters: dict) -> bool:
        """Python-side filter applied after PCE download."""
        src = flow.get('src', {})
        dst = flow.get('dst', {})
        svc = flow.get('service', {})

        def _label_match(side: dict, label_str: str) -> bool:
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

        any_label = filters.get('any_label')
        if any_label:
            if not (_label_match(src, any_label) or _label_match(dst, any_label)):
                return False
        any_ip = filters.get('any_ip')
        if any_ip:
            if not (_ip_match(src, any_ip) or _ip_match(dst, any_ip)):
                return False

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
        """Convenience wrapper for report generation."""
        if policy_decisions is None:
            policy_decisions = ["blocked", "potentially_blocked", "allowed"]

        query_spec = self.build_traffic_query_spec(filters)
        stream = self.execute_traffic_query_stream(
            start_time_str, end_time_str, policy_decisions, filters=query_spec
        )
        if stream is None:
            return []

        records = list(stream)

        if query_spec.fallback_filters:
            before = len(records)
            records = [r for r in records if self._flow_matches_filters(r, query_spec.fallback_filters)]
            after = len(records)
            if before != after:
                logger.info(f"[ReportFilter] {before} → {after} flows after applying filters")

        return records

    def get_last_traffic_query_diagnostics(self):
        return dict(self._client.last_traffic_query_diagnostics)

    # ── Rule usage batch helpers ─────────────────────────────────────────

    def get_last_rule_usage_batch_stats(self):
        return dict(self._client.last_rule_usage_batch_stats)

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

    def _build_query_actors(self, actor_list, scope_labels=None):
        """Convert rule consumers/providers to async query sources/destinations include list."""
        import itertools
        from collections import defaultdict

        c = self._client
        if not actor_list:
            return []

        def _label_dim(href):
            raw = c.label_cache.get(href, "")
            if raw and ":" in raw:
                return raw.split(":", 1)[0]
            return f"_unknown_{href}"

        scope_items_with_dim = []
        if scope_labels:
            for sl in scope_labels:
                if "label" in sl:
                    dim = _label_dim(sl["label"].get("href", ""))
                    scope_items_with_dim.append((dim, {"label": sl["label"]}))
                elif "label_group" in sl:
                    scope_items_with_dim.append(("_lgroup", {"label_group": sl["label_group"]}))

        label_actors_by_dim = defaultdict(list)
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
            scope_to_add = [item for dim, item in scope_items_with_dim
                            if dim not in consumer_dims]
            dim_groups = list(label_actors_by_dim.values())
            for combo in itertools.product(*dim_groups):
                inner = list(scope_to_add) + list(combo)
                result.append(inner)
        elif scope_items_with_dim:
            result.append([item for _, item in scope_items_with_dim])

        result.extend(non_label_groups)
        return result

    def _build_query_services(self, rule):
        """Convert rule ingress_services to async query services include list."""
        c = self._client
        services = []
        for svc in rule.get("ingress_services", []):
            if "href" in svc:
                resolved = c.service_ports_cache.get(svc["href"], [])
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
        """Build the async query payload dict for a single rule."""
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
        """Query traffic count for a single rule (sequential, for compatibility)."""
        jobs = self._client._jobs
        try:
            payload = self._build_rule_query_payload(rule, start_date, end_date)
            if payload is None:
                return 0
            cached = jobs.find_cached_async_summary(payload, query_type="rule_usage")
            if cached:
                return cached["count"]
            job_href = jobs.submit_async_query(payload)
            if not job_href:
                return 0
            if not jobs.poll_async_query(job_href, timeout=120):
                return 0
            return jobs.summarize_async_query(job_href)["count"]
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
        """Submit all rule queries in parallel, poll concurrently, download in parallel."""
        c = self._client
        jobs_mgr = c._jobs

        jobs_mgr._maybe_prune_async_job_states()
        total = len(rules)
        if not total:
            c.last_rule_usage_batch_stats = {
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
            cached = jobs_mgr.find_cached_async_summary(payload, query_type="rule_usage")
            if cached:
                cached_hits += 1
                href = rule.get("href", "")
                count = cached["count"]
                if count > 0:
                    hit_hrefs.add(href)
                    hit_counts[href] = count
                    rule_port_summaries[href] = dict(cached.get("flows_by_port", {}) or {})
                jobs_mgr._save_async_job_state(
                    cached["job_href"],
                    reused_at=jobs_mgr._utc_now_iso(),
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
                existing_job = jobs_mgr.find_latest_async_job(payload, query_type="rule_usage")
                if existing_job:
                    existing_status = existing_job.get("status")
                    existing_download = existing_job.get("download_status", "")
                    if existing_status in {"queued", "pending", "submitted"} and existing_download != "completed":
                        pending_rules.append((rule, payload, existing_job["job_href"]))
                        resumed_jobs += 1
                        continue
                    if existing_status in {"failed", "timeout"}:
                        retry_href = jobs_mgr.retry_async_query_job(existing_job["job_href"])
                        pending_rules.append((rule, payload, retry_href))
                        retried_jobs += 1
                        continue
                pending_rules.append((rule, payload, None))

        if cached_hits:
            _progress(f"Reused {cached_hits}/{total} cached rule summaries...")

        job_map = {}
        submitted_count = 0

        def _submit(rule_and_payload):
            rule, payload, existing_job_href = rule_and_payload
            if existing_job_href:
                return existing_job_href, rule, payload
            return jobs_mgr.submit_async_query(payload), rule, payload

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
            c.last_rule_usage_batch_stats = {
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

        pending = set(job_map.keys())
        completed = set()
        failed = set()
        deadline = time.time() + 300

        def _poll_one(job_href):
            url = f"{c.api_cfg['url']}/api/v2{job_href}"
            status, body = c._request(url, timeout=15)
            if status != 200:
                return job_href, "pending"
            try:
                poll_result = orjson.loads(body)
                state = poll_result.get("status", "pending")
                jobs_mgr._save_async_job_state(
                    job_href,
                    status=state,
                    rules_status=poll_result.get("rules"),
                    result_href=poll_result.get("result"),
                )
            except Exception as exc:
                logger.warning("Failed to parse async job poll response for {}: {}", job_href, exc)
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

        downloaded = 0
        failed_rule_details = []
        pending_rule_details = []

        def _download(job_href):
            summary = jobs_mgr.summarize_async_query(job_href)
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
        c.last_rule_usage_batch_stats = {
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

    # ── Export CSV ───────────────────────────────────────────────────────

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
        c = self._client
        jobs_mgr = c._jobs
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
        job_href = jobs_mgr.submit_async_query(payload, query_type="traffic_raw_csv")
        if not job_href:
            raise RuntimeError("Failed to submit raw Explorer CSV query")

        poll_result = jobs_mgr._wait_for_async_query(job_href, timeout=300, compute_draft=compute_draft)
        status = poll_result.get("status")
        rules_status = poll_result.get("rules")
        if status != "completed":
            raise RuntimeError(f"Traffic CSV query did not complete successfully (status={status})")
        if compute_draft and rules_status not in (None, "", "completed"):
            raise RuntimeError(f"Traffic CSV draft computation did not complete (rules={rules_status})")

        csv_result = jobs_mgr.download_async_query_csv(job_href, include_draft_policy=compute_draft)
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
