"""LabelResolver — label/IP/service lookup + TTL cache management.

Extracted from ApiClient in Phase 9 Task 6. The ApiClient facade continues to own
the TTLCache instances and _cache_lock (RLock) so that existing tests and
external callers accessing `api.label_cache`, `api._label_href_cache`, etc.,
remain unchanged. This class provides the methods that operate on those caches.
"""
from __future__ import annotations

import ipaddress
import json
import time
from loguru import logger


class LabelResolver:
    """Owns label/service/IP-list lookup logic for ApiClient.

    State (TTLCaches + _cache_lock) lives on the ApiClient facade so external
    callers and tests can keep mutating `client.label_cache`, etc. directly.
    """

    def __init__(self, client):
        self._client = client

    # ── Static helpers ───────────────────────────────────────────────────

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
        for item in LabelResolver._normalize_str_list(value):
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

    # ── Cache management ────────────────────────────────────────────────

    def invalidate_query_lookup_cache(self):
        """Clear cached label/service/IP-list/label-group lookups."""
        c = self._client
        with c._cache_lock:
            c.label_cache.clear()
            c.service_ports_cache.clear()
            c._label_href_cache.clear()
            c._label_group_href_cache.clear()
            c._iplist_href_cache.clear()
            c._query_lookup_cache_refreshed_at = 0.0

    def _query_lookup_cache_is_stale(self):
        c = self._client
        if not c._query_lookup_cache_refreshed_at:
            return not (
                c._label_href_cache
                or c._label_group_href_cache
                or c._iplist_href_cache
                or c.service_ports_cache
            )
        ttl = max(0, int(c._query_lookup_cache_ttl_seconds or 0))
        if ttl == 0:
            return False
        return (time.time() - c._query_lookup_cache_refreshed_at) >= ttl

    def _ensure_query_lookup_cache(self, force_refresh=False):
        """Populate label/service/IP-list lookup caches used by native query building."""
        c = self._client
        cache_ready = (
            c._label_href_cache
            and c._label_group_href_cache
            and c._iplist_href_cache
        )
        if cache_ready and not force_refresh and not self._query_lookup_cache_is_stale():
            return
        self._client.update_label_cache(silent=True, force_refresh=True)
        if not c._label_href_cache:
            for href, display in c.label_cache.items():
                if display and ":" in display and not display.startswith("[IPList] ") and not display.startswith("[LabelGroup] "):
                    c._label_href_cache.setdefault(display, href)
        if not c._label_group_href_cache:
            for href, display in c.label_cache.items():
                if display.startswith("[LabelGroup] "):
                    c._label_group_href_cache.setdefault(display.replace("[LabelGroup] ", "", 1), href)
        if not c._iplist_href_cache:
            for href, display in c.label_cache.items():
                if display.startswith("[IPList] "):
                    c._iplist_href_cache.setdefault(display.replace("[IPList] ", "", 1), href)

    def update_label_cache(self, silent=False, force_refresh=True):
        """Cache labels, IP lists, and services for display resolution."""
        c = self._client
        org = c.api_cfg['org_id']
        # Snapshot current state without holding the lock (reads are safe here)
        previous_state = (
            dict(c.label_cache),
            dict(c.service_ports_cache),
            dict(c._label_href_cache),
            dict(c._label_group_href_cache),
            dict(c._iplist_href_cache),
            c._query_lookup_cache_refreshed_at,
        )
        try:
            # I/O phase: fetch data from API without holding lock (network latency)
            if force_refresh:
                self.invalidate_query_lookup_cache()  # acquires _cache_lock internally (RLock)
            s_labels, d_labels = c._api_get(f"/orgs/{org}/labels?max_results=10000")
            s_groups, d_groups = c._api_get(f"/orgs/{org}/sec_policy/draft/label_groups?max_results=10000")
            s_iplists, d_iplists = c._api_get(f"/orgs/{org}/sec_policy/draft/ip_lists?max_results=10000")
            s_services, d_services = c._api_get(f"/orgs/{org}/sec_policy/draft/services?max_results=10000")

            # Write phase: acquire lock once to write all fetched data atomically
            with c._cache_lock:
                if s_labels == 200 and d_labels:
                    for i in d_labels:
                        label_str = f"{i.get('key')}:{i.get('value')}"
                        c.label_cache[i['href']] = label_str
                        c._label_href_cache[label_str] = i['href']

                if s_groups == 200 and d_groups:
                    for i in d_groups:
                        name = i.get('name')
                        if not name:
                            continue
                        val = f"[LabelGroup] {name}"
                        c.label_cache[i['href']] = val
                        c.label_cache[i['href'].replace('/draft/', '/active/')] = val
                        c._label_group_href_cache[name] = i['href']

                if s_iplists == 200 and d_iplists:
                    for i in d_iplists:
                        val = f"[IPList] {i.get('name')}"
                        c.label_cache[i['href']] = val
                        c.label_cache[i['href'].replace('/draft/', '/active/')] = val
                        if i.get('name'):
                            c._iplist_href_cache[i['name']] = i['href']

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
                        c.label_cache[i['href']] = val
                        c.label_cache[i['href'].replace('/draft/', '/active/')] = val
                        # Cache resolved port definitions for per-rule queries
                        if port_defs:
                            c.service_ports_cache[i['href']] = port_defs
                            c.service_ports_cache[i['href'].replace('/draft/', '/active/')] = port_defs
                c._query_lookup_cache_refreshed_at = time.time()
        except Exception as e:
            # Restore previous state — update caches in-place to preserve TTLCache instances
            prev_label, prev_svc, prev_href, prev_grp, prev_ip, prev_ts = previous_state
            with c._cache_lock:
                c.label_cache.clear()
                c.label_cache.update(prev_label)
                c.service_ports_cache.clear()
                c.service_ports_cache.update(prev_svc)
                c._label_href_cache.clear()
                c._label_href_cache.update(prev_href)
                c._label_group_href_cache.clear()
                c._label_group_href_cache.update(prev_grp)
                c._iplist_href_cache.clear()
                c._iplist_href_cache.update(prev_ip)
                c._query_lookup_cache_refreshed_at = prev_ts
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
        c = self._client
        with c._cache_lock:
            c.label_cache.clear()
            c._label_href_cache.clear()
            c._label_group_href_cache.clear()
        logger.debug("Label caches cleared (invalidate_labels)")

    # ── Actor / filter resolution ─────────────────────────────────────────

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

    def _resolve_label_filter_to_actor(self, label_filter):
        c = self._client
        normalized = self._normalize_label_filter(label_filter)
        if not normalized:
            return None
        self._ensure_query_lookup_cache()
        href = c._label_href_cache.get(normalized)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = c._label_href_cache.get(normalized)
        if href:
            return {"label": {"href": href}}
        return None

    def _resolve_label_group_filter_to_actor(self, label_group_filter):
        c = self._client
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
        href = c._label_group_href_cache.get(candidate)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = c._label_group_href_cache.get(candidate)
        if href:
            return {"label_group": {"href": href}}
        return None

    def _resolve_ip_filter_to_actor(self, ip_filter):
        c = self._client
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
        href = c._iplist_href_cache.get(candidate)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = c._iplist_href_cache.get(candidate)
        if href:
            return {"ip_list": {"href": href}}
        return None

    def _resolve_iplist_filter_to_actor(self, iplist_filter):
        """IP List 物件 filter → actor。接受 dict{href|name}、href 字串或名稱。
        刻意不接受 IP literal——那是 src_ip 家族的職責。"""
        c = self._client
        if not iplist_filter:
            return None
        if isinstance(iplist_filter, dict):
            href = iplist_filter.get("href")
            if href and "/ip_lists/" in str(href):
                return {"ip_list": {"href": str(href).strip()}}
            iplist_filter = iplist_filter.get("name") or ""
        candidate = str(iplist_filter).strip()
        if not candidate or self._is_ip_literal(candidate):
            return None
        if self._is_href(candidate):
            if "/ip_lists/" in candidate:
                return {"ip_list": {"href": candidate}}
            return None
        self._ensure_query_lookup_cache()
        href = c._iplist_href_cache.get(candidate)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = c._iplist_href_cache.get(candidate)
        if href:
            return {"ip_list": {"href": href}}
        return None

    def _resolve_workload_filter_to_actor(self, workload_filter):
        """Workload 物件 filter → actor。只接受 href（dict 或字串）；
        名稱搜尋交給 suggest 端點在選取當下轉 href。"""
        if not workload_filter:
            return None
        if isinstance(workload_filter, dict):
            workload_filter = workload_filter.get("href") or ""
        candidate = str(workload_filter).strip()
        if candidate and self._is_href(candidate) and "/workloads/" in candidate:
            return {"workload": {"href": candidate}}
        return None

    # ── Display resolution ──────────────────────────────────────────────

    def resolve_actor_str(self, actors):
        """Resolve actor list to human-readable string using label_cache."""
        c = self._client
        if not actors:
            return "Any"
        names = []
        for a in actors:
            if 'label' in a:
                names.append(c.label_cache.get(a['label']['href'], "Label"))
            elif 'ip_list' in a:
                names.append(c.label_cache.get(a['ip_list']['href'], "IPList"))
            elif 'actors' in a:
                names.append(str(a.get('actors')))
        return ", ".join(names)

    def resolve_service_str(self, services):
        """Resolve service references to display strings."""
        from src.href_utils import extract_id as _extract_id
        c = self._client
        if not services:
            return "All Services"
        svcs = []
        for s in services:
            if 'port' in s:
                p, proto = s.get('port'), "UDP" if s.get('proto') == 17 else "TCP"
                top = f"-{s['to_port']}" if s.get('to_port') else ""
                svcs.append(f"{proto}/{p}{top}")
            elif 'href' in s:
                svcs.append(c.label_cache.get(s['href'], f"Service({_extract_id(s['href'])})"))
            else:
                svcs.append("RefObj")
        return ", ".join(svcs)
