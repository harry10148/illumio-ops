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


def _readable_ref(actor: dict) -> str:
    """未知 actor 形狀的可讀 fallback：型別:href 尾段，絕不印 raw dict（spec F1）。"""
    for key, val in actor.items():
        if isinstance(val, dict) and val.get('href'):
            tail = str(val['href']).rstrip('/').rsplit('/', 1)[-1]
            return f"{key}:{tail}"
    return ", ".join(str(k) for k in actor.keys()) or "Unknown"


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
        text = str(value).strip()
        try:
            ipaddress.ip_address(text)
            return True
        except ValueError:
            pass
        if "/" in text:
            # CIDR block（如 "10.0.0.0/24"）：PCE ip_address native actor 對 Explorer
            # 「IP Address/CIDR Block」類別接受 CIDR 字串，見官方 API guide（
            # analyzer-ip-containment-report.md native 觀察段）。strict=False 允許
            # host bits 已設的寫法（如 "10.0.0.5/24"）。
            try:
                ipaddress.ip_network(text, strict=False)
                return True
            except ValueError:
                return False
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
        from src.port_token import parse_port_token
        return parse_port_token(value, default_proto=default_proto)

    @staticmethod
    def _service_entry_defs(svc):
        """service 物件 → services.include 條目清單（查詢用完整形，含
        windows_services 與純 proto 條目；空 service 回 []）。"""
        defs = []
        for sp in svc.get("service_ports") or []:
            p = sp.get("port")
            proto = sp.get("proto")
            # PCE 特殊物件「All Services」用 {"proto": -1} 表示所有協定、
            # 無服務限制；負值 port/proto 一律正規化為 wildcard 標記條目，
            # 不可把 -1 當成真實 proto/port 值送進 query（語意錯誤）。
            if (p is not None and p < 0) or (proto is not None and proto < 0):
                defs.append({"wildcard": True})
                continue
            if p:
                pd = {"port": p}
                if proto is not None:
                    pd["proto"] = proto
                if sp.get("to_port"):
                    pd["to_port"] = sp["to_port"]
                defs.append(pd)
            elif proto is not None:
                defs.append({"proto": proto})
        for w in svc.get("windows_services") or []:
            if w.get("service_name"):
                defs.append({"windows_service_name": w["service_name"]})
            elif w.get("process_name"):
                defs.append({"process_name": w["process_name"]})
            elif w.get("port"):
                pd = {"port": w["port"]}
                if w.get("proto") is not None:
                    pd["proto"] = w["proto"]
                defs.append(pd)
        return defs

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
            s_labels, d_labels, _t1 = c._get_collection(f"/orgs/{org}/labels")
            s_groups, d_groups, _t2 = c._get_collection(f"/orgs/{org}/sec_policy/draft/label_groups")
            s_iplists, d_iplists, _t3 = c._get_collection(f"/orgs/{org}/sec_policy/draft/ip_lists")
            s_services, d_services, _t4 = c._get_collection(f"/orgs/{org}/sec_policy/draft/services")

            # Write phase: acquire lock once to write all fetched data atomically
            with c._cache_lock:
                if s_labels == 200 and d_labels:
                    for i in d_labels:
                        href = i.get('href')
                        if not href:
                            # 缺 href 的條目無法快取，裸 i['href'] 會 KeyError 觸發
                            # 整包 rollback（見 except 區），silent=True 下無聲失敗。
                            continue
                        label_str = f"{i.get('key')}:{i.get('value')}"
                        c.label_cache[href] = label_str
                        c._label_href_cache[label_str] = href

                if s_groups == 200 and d_groups:
                    for i in d_groups:
                        href = i.get('href')
                        name = i.get('name')
                        if not href or not name:
                            continue
                        val = f"[LabelGroup] {name}"
                        c.label_cache[href] = val
                        c.label_cache[href.replace('/draft/', '/active/')] = val
                        c._label_group_href_cache[name] = href

                if s_iplists == 200 and d_iplists:
                    for i in d_iplists:
                        href = i.get('href')
                        if not href:
                            continue
                        val = f"[IPList] {i.get('name')}"
                        c.label_cache[href] = val
                        c.label_cache[href.replace('/draft/', '/active/')] = val
                        if i.get('name'):
                            c._iplist_href_cache[i['name']] = href

                if s_services == 200 and d_services:
                    for i in d_services:
                        href = i.get('href')
                        if not href:
                            continue
                        name = i.get('name')
                        ports = []
                        for svc in i.get('service_ports', []):
                            p = svc.get('port')
                            if p:
                                proto = "UDP" if svc.get('proto') == 17 else "TCP"
                                top = f"-{svc['to_port']}" if svc.get('to_port') else ""
                                ports.append(f"{proto}/{p}{top}")
                        port_str = f" ({','.join(ports)})" if ports else ""
                        val = f"{name}{port_str}"
                        c.label_cache[href] = val
                        c.label_cache[href.replace('/draft/', '/active/')] = val
                        # 查詢用完整條目（含 windows_services、純 proto；filter
                        # 的 service 展開與 per-rule query 共用）
                        port_defs = LabelResolver._service_entry_defs(i)
                        if port_defs:
                            c.service_ports_cache[href] = port_defs
                            c.service_ports_cache[href.replace('/draft/', '/active/')] = port_defs
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
                # PCE (21.5+) 對 traffic_flows include/exclude 的 ip_address
                # native actor 只接受 plain string；nested {"value": ...} 會
                # 回 406 input_validation_error 且被 stream 層吞掉、靜默回 0
                # 筆（實測 2026-07-04）。
                return {"ip_address": str(value["ip_address"]).strip()}
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
        # CIDR literal (e.g. "10.0.0.0/24") takes precedence over same-named IP List.
        # This is intentional: CIDR-shaped strings are parsed as ip_address actors,
        # per PCE API guide; literal interpretation is more correct than name lookup.
        if self._is_ip_literal(candidate):
            # PCE (21.5+) 對 traffic_flows include/exclude 的 ip_address
            # native actor 只接受 plain string；nested {"value": ...} 會
            # 回 406 input_validation_error 且被 stream 層吞掉、靜默回 0
            # 筆（實測 2026-07-04）。
            return {"ip_address": candidate}
        self._ensure_query_lookup_cache()
        href = c._iplist_href_cache.get(candidate)
        if not href:
            self._ensure_query_lookup_cache(force_refresh=True)
            href = c._iplist_href_cache.get(candidate)
        if href:
            return {"ip_list": {"href": href}}
        return None

    @staticmethod
    def _parse_ip_range(value):
        """IPv4 range 字串 'a.b.c.d-a.b.c.d' → (from, to) IPv4Address tuple，
        from>to 自動對調。無 '-' 或兩側非合法 IPv4 → None（非 range，交由呼叫端
        走既有單一 IP/CIDR/href 解析路徑）。IPv6 range 不支援（對齊既有
        _objfbIsIpLike 只收 IPv4 的既有行為）。"""
        text = str(value).strip()
        if "-" not in text:
            return None
        left, _, right = text.partition("-")
        try:
            frm = ipaddress.IPv4Address(left.strip())
            to = ipaddress.IPv4Address(right.strip())
        except ValueError:
            return None
        if frm > to:
            frm, to = to, frm
        return frm, to

    def _resolve_ip_filter_to_actors(self, ip_filter):
        """IP filter 值 → native actor 清單。

        單一 IP/CIDR/href：委派 `_resolve_ip_filter_to_actor`，回傳 0-1 筆。
        IP range：展開成涵蓋該範圍的最小 CIDR 集合（`summarize_address_range`），
        每個 CIDR 各自一筆——呼叫端（traffic_query 的 src_ip_in/dst_ip_in 等）
        需把清單中每一筆各自放進獨立的 include 組，讓多個 CIDR 之間是 OR
        （PCE traffic query 的 ip_address actor 只吃 literal/CIDR 字串、無
        range 欄位，range 必須在我方展開）。查無/非法回空清單。
        """
        if not ip_filter:
            return []
        ip_range = self._parse_ip_range(ip_filter)
        if ip_range is not None:
            frm, to = ip_range
            return [{"ip_address": str(net)} for net in ipaddress.summarize_address_range(frm, to)]
        actor = self._resolve_ip_filter_to_actor(ip_filter)
        return [actor] if actor is not None else []

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
            if not isinstance(a, dict):
                names.append(str(a))
            elif 'label' in a:
                names.append(c.label_cache.get(a['label']['href'], "Label"))
            elif 'label_group' in a:
                names.append(c.label_cache.get(a['label_group']['href'], "LabelGroup"))
            elif 'ip_list' in a:
                names.append(c.label_cache.get(a['ip_list']['href'], "IPList"))
            elif 'workload' in a:
                names.append(c.label_cache.get(a['workload']['href'], "Workload"))
            elif a.get('actors') == 'ams':
                # 顯示層對應：API payload 的 'ams' 一律呈現 All Workloads（spec F1）
                names.append("All Workloads")
            elif 'actors' in a:
                names.append(str(a.get('actors')))
            else:
                names.append(_readable_ref(a))
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

    def resolve_service_entries(self, value):
        """service href → services.include/exclude 條目清單（filter 的
        services/ex_services key 查詢時展開用）。查無（物件被刪、快取未含）
        回 None，由呼叫端走 unresolved 降級。"""
        c = self._client
        return c.service_ports_cache.get(str(value).strip())

    # ── Cache DataFrame object-filter expansion ─────────────────────────

    def expand_object_filters_for_df(self, filters):
        """iplist/workload 物件 filter → CIDR/IP 清單（cache df 路徑用）。

        df 的統一 schema 沒有 workload href / ip_lists 欄位（api_parser
        flatten 只留 ip/hostname/labels），物件條件必須先展開成 IP 集合
        再交給 df_filter 的 CIDR mask。回傳淺拷貝；展開結果放底線前綴
        內部 key，不進任何儲存格式。
        """
        import ipaddress

        c = self._client
        obj_keys = {
            "_src_object_cidrs": ("src_iplist", "src_iplists", "src_workload", "src_workloads"),
            "_dst_object_cidrs": ("dst_iplist", "dst_iplists", "dst_workload", "dst_workloads"),
            "_ex_src_object_cidrs": ("ex_src_iplist", "ex_src_iplists", "ex_src_workload", "ex_src_workloads"),
            "_ex_dst_object_cidrs": ("ex_dst_iplist", "ex_dst_iplists", "ex_dst_workload", "ex_dst_workloads"),
            "_any_object_cidrs": ("any_iplist", "any_workload"),
            "_ex_any_object_cidrs": ("ex_any_iplist", "ex_any_workload"),
        }
        svc_keys = (("services", "_svc_port_entries"), ("ex_services", "_ex_svc_port_entries"))
        has_svc = any(filters.get(k) for k, _ in svc_keys) if filters else False
        if not filters or (not any(
                filters.get(k) for keys in obj_keys.values() for k in keys) and not has_svc):
            return filters

        def _range_to_cidrs(r, list_name):
            frm = r.get("from_ip")
            to = r.get("to_ip")
            if not frm:
                return []
            if not to or "/" in frm:
                return [frm]
            try:
                return [str(n) for n in ipaddress.summarize_address_range(
                    ipaddress.ip_address(frm), ipaddress.ip_address(to))]
            except ValueError:
                logger.warning("Bad ip_range in {}: {}-{}", list_name, frm, to)
                return []

        def _subtract_cidrs(include, exclude):
            """per-IP List 的 CIDR 集合差（PCE 語意：exclusion 從 inclusion
            扣除）。range 已先化為 CIDR，兩 CIDR 非相離即巢狀，逐一
            address_exclude 即為精確差集。無法解析的 inclusion 字串原樣
            保留（fail-open 保守：寧可 over-include 也不無聲丟 inclusion）。"""
            if not exclude:
                return include
            passthrough, inc_nets, exc_nets = [], [], []
            for s in include:
                try:
                    inc_nets.append(ipaddress.ip_network(str(s).strip(), strict=False))
                except ValueError:
                    passthrough.append(s)
            for s in exclude:
                try:
                    exc_nets.append(ipaddress.ip_network(str(s).strip(), strict=False))
                except ValueError:
                    pass  # 解析不了的 exclusion 忽略（無從扣除）
            for exc in exc_nets:
                remaining = []
                for n in inc_nets:
                    if n.version != exc.version or not n.overlaps(exc):
                        remaining.append(n)
                    elif exc.supernet_of(n):
                        continue  # 整塊被排除
                    else:  # n 真包含 exc → 切分
                        remaining.extend(n.address_exclude(exc))
                inc_nets = remaining
            return passthrough + [str(n) for n in inc_nets]

        def _iplist_cidrs(value):
            """IP List → 有效 CIDR 清單（inclusion 聯集 − exclusion；PCE 語意）。
            修正前 exclusion:true 條目被一併展開成 inclusion，cache df 路徑
            over-include；native（PCE 端自套 exclusion）與 fallback
            （_iplist_hit 比 PCE 標注 membership）本已正確——修這裡即三路一致。

            get_ip_lists 帶 raise_on_error=True：PCE 抓取失敗要讓例外往上炸，
            避免誤把「抓取失敗」當成「IP List 已刪除」而靜默回空 CIDR 集合。
            fetch 成功但名稱/href 找不到匹配才是合法的「查無」，回 [] 但留
            warning log 供除錯。"""
            value = str(value).strip()
            for ipl in (c.get_ip_lists(raise_on_error=True) or []):
                if ipl.get("name") == value or ipl.get("href") == value:
                    include, exclude = [], []
                    for r in ipl.get("ip_ranges", []) or []:
                        bucket = exclude if r.get("exclusion") else include
                        bucket.extend(_range_to_cidrs(r, value))
                    return _subtract_cidrs(include, exclude)
            logger.warning("expand_object_filters_for_df: IP List not found for value {}", value)
            return []

        def _workload_ips(value):
            value = str(value).strip()
            if "/workloads/" not in value:
                return []
            wl = c.get_workload(value) or {}
            ips = [i.get("address") for i in wl.get("interfaces", []) or [] if i.get("address")]
            if wl.get("public_ip"):
                ips.append(wl["public_ip"])
            return ips

        out = dict(filters)
        for dest, keys in obj_keys.items():
            cidrs = []
            for k in keys:
                vals = filters.get(k)
                if not vals:
                    continue
                vals = vals if isinstance(vals, list) else [vals]
                for v in vals:
                    if not v:
                        continue
                    cidrs.extend(_iplist_cidrs(v) if "iplist" in k else _workload_ips(v))
            if cidrs:
                out[dest] = cidrs

        for key, internal in svc_keys:
            vals = filters.get(key)
            if not vals:
                continue
            vals = vals if isinstance(vals, list) else [vals]
            entries = []
            for href in vals:
                for e in (self.resolve_service_entries(href) or []):
                    if "port" in e or "proto" in e or e.get("wildcard"):
                        entries.append(e)
                    else:
                        logger.warning(
                            "Cache path cannot match name-based service entry {}; skipped", e)
            if entries:
                out[internal] = entries
        return out
