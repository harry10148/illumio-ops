"""Filter 物件選擇器 suggest 端點藍圖。

GET /api/filter-objects/suggest：輸入時搜尋可用 PCE 物件供 filter pill 選取。
Labels/Label Groups/IP Lists 走跨-request module 快取（filter_object_cache）；
Workloads 即時查（name+hostname 合併去重）；PCE 離線時 workload 降級、快取類照常。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

_CACHED_TYPES = ("label", "label_group", "iplist", "service")
_ALL_TYPES = _CACHED_TYPES + ("workload",)
_MAX_LIMIT = 25


def make_filter_objects_blueprint(cm, csrf, limiter, login_required):
    # login_required：既有 before_request security_check 已全域保護 /api/，
    # 端點無需另外裝飾（與 actions 藍圖同慣例，參數僅為簽章一致性保留）。
    bp = Blueprint("filter_objects", __name__)

    @bp.route('/api/filter-objects/suggest', methods=['GET'])
    @limiter.limit("240 per hour")
    def api_filter_objects_suggest():
        q = (request.args.get('q') or '').strip()
        raw_types = (request.args.get('types') or ','.join(_ALL_TYPES)).split(',')
        types = [t.strip() for t in raw_types if t.strip() in _ALL_TYPES]
        try:
            limit = max(1, min(_MAX_LIMIT, int(request.args.get('limit', 10))))
        except (ValueError, TypeError):
            limit = 10
        if not q or not types:
            return jsonify({"ok": True, "results": {}})

        from src.api_client import ApiClient
        from src.gui.filter_object_cache import search_cached_objects
        cm.load()
        api = ApiClient(cm)

        results = {}
        cached_types = [t for t in types if t in _CACHED_TYPES]
        if cached_types:
            # 快取類：module cache 若已填則離線也可回；填充失敗回空清單、不整體失敗
            try:
                results.update(search_cached_objects(api, q, cached_types, limit))
                # 檢查 PCE 健康狀況，若不通且 cached type 返回空，設置離線錯誤
                status, _ = api.check_health()
                if status != 200:
                    for t in cached_types:
                        if not results[t]["items"]:
                            results[t]["error"] = "pce_unreachable"
            except Exception:
                for t in cached_types:
                    results[t] = {"items": [], "error": "pce_unreachable"}

        if "workload" in types:
            results["workload"] = _search_workloads(api, q, limit)

        return jsonify({"ok": True, "results": results})

    return bp


def _search_workloads(api, q: str, limit: int) -> dict:
    """即時查 workload：name 與 hostname 各查一次、合併去重（by href）。

    ApiClient.search_workloads 失敗時會吞掉例外回傳 []（不 raise），所以無法
    靠 except 分辨「PCE 不通」vs「真的無符合」。因此結果為空時，額外用
    check_health 探測 PCE 連線狀態：非 200 視為 pce_unreachable，200 則是
    真的沒有符合的 workload。
    """
    try:
        seen, items = set(), []
        for param in ("name", "hostname"):
            for w in (api.search_workloads({param: q, "max_results": limit}) or []):
                href = w.get("href")
                if href in seen:
                    continue
                seen.add(href)
                ip = ""
                for iface in (w.get("interfaces") or []):
                    a = iface.get("address", "")
                    if a and "." in a and ":" not in a:  # IPv4 優先顯示
                        ip = a
                        break
                items.append({"name": w.get("name") or w.get("hostname") or href,
                              "hostname": w.get("hostname", ""), "ip": ip, "href": href})
        if not items:
            status, _ = api.check_health()
            if status != 200:
                return {"items": [], "truncated": False, "error": "pce_unreachable"}
        return {"items": items[:limit], "truncated": len(items) > limit, "error": None}
    except Exception:
        return {"items": [], "truncated": False, "error": "pce_unreachable"}
