"""Filter 物件選擇器 suggest 端點的跨-request 快取層。

ApiClient 每 request 建新實例（短命），其 TTLCache 不跨 request，故
labels/ip_lists/label_groups 這類「變動少、每次輸入都要搜」的物件改用
module 層 TTLCache：首次全量抓、TTL 內子字串比對走快取，PCE 零負擔。
workload 因數量大、變動頻繁，由端點即時查，不進此快取。
"""
from __future__ import annotations

import threading
from typing import Any

from cachetools import TTLCache

_CACHE_TTL_SECONDS = 300
_lock = threading.RLock()
# key: "labels"/"ip_lists"/"label_groups" → 完整物件清單
_cache: TTLCache = TTLCache(maxsize=8, ttl=_CACHE_TTL_SECONDS)
# 不過期的「最後成功值」store，供 TTL 過期後 refetch 失敗時 stale-serving 用。
# 注意：TTLCache 對過期 key 視同不存在，_cache.get() 在過期後永遠拿不到舊值，
# 故 stale-serving 不能依賴 _cache，需另外維護此 dict。
_last_good: dict = {}


def invalidate_object_cache() -> None:
    """清空 module 快取（測試用 / 手動失效）。"""
    with _lock:
        _cache.clear()
        _last_good.clear()


def _get_or_fill(api, key: str, fetch):
    """TTL 內走 _cache；過期後重抓。抓成功同時更新 _cache（TTL 計時）與
    _last_good（不過期）；抓失敗或空結果則回 _last_good（真正的
    stale-serving，而非依賴 TTLCache 對過期 key 的感知，因為過期後
    TTLCache 會直接視為不存在）。皆無舊值時回 []。
    """
    with _lock:
        if key in _cache:
            return _cache[key]
    data = fetch(api) or []
    with _lock:
        if data:
            _cache[key] = data
            _last_good[key] = data
            return data
        # 抓到空/失敗：回最後一次成功值（stale 勝於無）
        return _last_good.get(key, [])


def _ip_list_summary(ipl: dict) -> str:
    """ip_ranges 組成顯示摘要，最多 3 段。"""
    parts = []
    for r in (ipl.get("ip_ranges") or [])[:3]:
        frm = r.get("from_ip", "")
        to = r.get("to_ip")
        parts.append(f"{frm}-{to}" if to else frm)
    more = len(ipl.get("ip_ranges") or []) > 3
    return ", ".join(p for p in parts if p) + (", …" if more else "")


_PROTO_NUM_TO_NAME = {6: "tcp", 17: "udp", 1: "icmp", 58: "icmpv6"}


def _service_summary(svc: dict) -> str:
    """service 條目組顯示摘要，最多 3 段，超出以 … 提示（不無聲截斷）。"""
    parts = []
    for sp in svc.get("service_ports") or []:
        p = sp.get("port")
        raw_proto = sp.get("proto")
        # PCE 特殊物件「All Services」用 {"proto": -1} 表示所有協定、無服務
        # 限制；負值 port/proto 顯示為 "all"，不可把 -1 印成一個協定號。
        if (p is not None and p < 0) or (raw_proto is not None and raw_proto < 0):
            parts.append("all")
            continue
        proto = _PROTO_NUM_TO_NAME.get(raw_proto, str(raw_proto or ""))
        if p:
            top = f"-{sp['to_port']}" if sp.get("to_port") else ""
            parts.append(f"{proto}/{p}{top}" if proto else f"{p}{top}")
        elif raw_proto is not None:
            parts.append(proto)
    for w in svc.get("windows_services") or []:
        n = w.get("service_name") or w.get("process_name")
        if n:
            parts.append(n)
    return ", ".join(parts[:3]) + (", …" if len(parts) > 3 else "")


def _match_labels(objs, q, limit):
    ql = q.lower()
    hits = []
    for l in objs:
        key, val = l.get("key", ""), l.get("value", "")
        name = f"{key}={val}"
        if ql in name.lower() or ql in val.lower() or ql in key.lower():
            hits.append({"name": name, "key": key, "value": val, "href": l.get("href")})
    return hits[:limit], len(hits) > limit


def _match_named(objs, q, limit, summary_fn=None):
    ql = q.lower()
    hits = []
    for o in objs:
        name = o.get("name", "")
        if ql in name.lower():
            item = {"name": name, "href": o.get("href")}
            if summary_fn:
                item["summary"] = summary_fn(o)
            hits.append(item)
    return hits[:limit], len(hits) > limit


_TYPE_FETCHERS = {
    "label": ("labels", lambda a: a.get_all_labels()),
    "iplist": ("ip_lists", lambda a: a.get_ip_lists()),
    "label_group": ("label_groups", lambda a: a.get_label_groups()),
    "service": ("services", lambda a: a.get_services()),
}


def cached_type_totals(api) -> dict[str, int]:
    """各 cached 類別總數（chip 顯示用；快取長度，零 PCE 額外成本）。"""
    return {t: len(_get_or_fill(api, key, fn)) for t, (key, fn) in _TYPE_FETCHERS.items()}


def browse_cached_objects(api, btype: str, offset: int, limit: int) -> dict:
    """單一類別全量瀏覽分頁。label 依 (key, value) 排序並附 groups 統計；
    其他類別依 name 排序。item 形狀與 suggest 一致。"""
    key, fn = _TYPE_FETCHERS[btype]
    objs = _get_or_fill(api, key, fn)
    if btype == "label":
        objs = sorted(objs, key=lambda l: ((l.get("key") or ""), (l.get("value") or "")))
        groups: dict[str, int] = {}
        for l in objs:
            groups[l.get("key") or ""] = groups.get(l.get("key") or "", 0) + 1
        items = [{"name": f"{l.get('key', '')}={l.get('value', '')}",
                  "key": l.get("key"), "value": l.get("value"), "href": l.get("href")}
                 for l in objs[offset:offset + limit]]
        return {"items": items, "total": len(objs), "truncated": offset + limit < len(objs),
                "groups": [{"key": k, "count": n} for k, n in groups.items()]}
    objs = sorted(objs, key=lambda o: o.get("name") or "")
    summary_fn = _ip_list_summary if btype == "iplist" else (_service_summary if btype == "service" else None)
    items = []
    for o in objs[offset:offset + limit]:
        item = {"name": o.get("name", ""), "href": o.get("href")}
        if summary_fn:
            item["summary"] = summary_fn(o)
        items.append(item)
    return {"items": items, "total": len(objs), "truncated": offset + limit < len(objs)}


def search_cached_objects(api, q: str, types: list[str], limit: int) -> dict[str, Any]:
    """對 cached 四類（label/label_group/iplist/service）做子字串比對，回分類分組結果。

    只處理 types 中屬 cached 四類者；workload 由端點另行即時查。
    """
    out: dict[str, Any] = {}
    if "label" in types:
        objs = _get_or_fill(api, "labels", lambda a: a.get_all_labels())
        items, trunc = _match_labels(objs, q, limit)
        out["label"] = {"items": items, "truncated": trunc}
    if "iplist" in types:
        objs = _get_or_fill(api, "ip_lists", lambda a: a.get_ip_lists())
        items, trunc = _match_named(objs, q, limit, summary_fn=_ip_list_summary)
        out["iplist"] = {"items": items, "truncated": trunc}
    if "label_group" in types:
        objs = _get_or_fill(api, "label_groups", lambda a: a.get_label_groups())
        items, trunc = _match_named(objs, q, limit)
        out["label_group"] = {"items": items, "truncated": trunc}
    if "service" in types:
        objs = _get_or_fill(api, "services", lambda a: a.get_services())
        items, trunc = _match_named(objs, q, limit, summary_fn=_service_summary)
        out["service"] = {"items": items, "truncated": trunc}
    return out
