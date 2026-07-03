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


def invalidate_object_cache() -> None:
    """清空 module 快取（測試用 / 手動失效）。"""
    with _lock:
        _cache.clear()


def _get_or_fill(api, key: str, fetch):
    """TTL 內回快取；過期或未填則呼叫 fetch 全量抓。抓失敗且無舊值回 []。"""
    with _lock:
        if key in _cache:
            return _cache[key]
    data = fetch(api) or []
    with _lock:
        if data:
            _cache[key] = data
            return data
        # 抓到空/失敗：若有殘留舊值（TTL 剛過）回舊值勝於無
        return _cache.get(key, [])


def _ip_list_summary(ipl: dict) -> str:
    """ip_ranges 組成顯示摘要，最多 3 段。"""
    parts = []
    for r in (ipl.get("ip_ranges") or [])[:3]:
        frm = r.get("from_ip", "")
        to = r.get("to_ip")
        parts.append(f"{frm}-{to}" if to else frm)
    more = len(ipl.get("ip_ranges") or []) > 3
    return ", ".join(p for p in parts if p) + (", …" if more else "")


def _match_labels(objs, q, limit):
    ql = q.lower()
    hits = []
    for l in objs:
        key, val = l.get("key", ""), l.get("value", "")
        name = f"{key}={val}"
        if ql in name.lower() or ql in val.lower() or ql in key.lower():
            hits.append({"name": name, "key": key, "value": val, "href": l.get("href")})
    return hits[:limit], len(hits) > limit


def _match_named(objs, q, limit, with_summary=False):
    ql = q.lower()
    hits = []
    for o in objs:
        name = o.get("name", "")
        if ql in name.lower():
            item = {"name": name, "href": o.get("href")}
            if with_summary:
                item["summary"] = _ip_list_summary(o)
            hits.append(item)
    return hits[:limit], len(hits) > limit


def search_cached_objects(api, q: str, types: list[str], limit: int) -> dict[str, Any]:
    """對 cached 三類（label/label_group/iplist）做子字串比對，回分類分組結果。

    只處理 types 中屬 cached 三類者；workload 由端點另行即時查。
    """
    out: dict[str, Any] = {}
    if "label" in types:
        objs = _get_or_fill(api, "labels", lambda a: a.get_all_labels())
        items, trunc = _match_labels(objs, q, limit)
        out["label"] = {"items": items, "truncated": trunc}
    if "iplist" in types:
        objs = _get_or_fill(api, "ip_lists", lambda a: a.get_ip_lists())
        items, trunc = _match_named(objs, q, limit, with_summary=True)
        out["iplist"] = {"items": items, "truncated": trunc}
    if "label_group" in types:
        objs = _get_or_fill(api, "label_groups", lambda a: a.get_label_groups())
        items, trunc = _match_named(objs, q, limit)
        out["label_group"] = {"items": items, "truncated": trunc}
    return out
