"""VEN 車隊 API（唯讀）——只讀 run_ven_summary 寫下的快照，不碰 PCE。

    GET /api/fleet
    GET /api/fleet/list?bucket=&offset=&limit=

寫入 PCE 的那一半（preview／apply）在 Task 3，會用這裡的 `BUCKET_PREDICATES`
挑出同一批對象：預覽看到的與真正被改的必須是同一個定義，兩份各寫一次就會
在某個版本分岔。

Auth 走 app 層的 before_request；這兩支都是 GET，沒有 CSRF。
"""
from __future__ import annotations

from typing import Callable

from flask import Blueprint, jsonify, request

from src.dashboard_store import read_dashboard_summary
from src.gui._helpers import _err
from src.report.analysis.fleet import PIPELINE_BUCKETS

_MAX_LIMIT = 500
_DEFAULT_LIMIT = 100

# heartbeat 的分桶門檻與 analyze_fleet 相同；這裡是對已經算好的 index 列
# 重新分桶，所以門檻必須一致，否則摘要說 3 台過期、清單只列得出 2 台。
_HEARTBEAT_FRESH_H = 24.0
_HEARTBEAT_STALE_H = 48.0


def _mode_is(mode: str) -> Callable[[dict], bool]:
    return lambda r: r.get("mode") == mode


def _idle_compat(state: str) -> Callable[[dict], bool]:
    return lambda r: r.get("mode") == "idle" and r.get("compat") == state


def _hslh_between(lo: float | None, hi: float | None) -> Callable[[dict], bool]:
    def _pred(r: dict) -> bool:
        v = r.get("hslh")
        if v is None:
            return False
        try:
            v = float(v)
        except (TypeError, ValueError):
            return False
        return (lo is None or v > lo) and (hi is None or v <= hi)
    return _pred


BUCKET_PREDICATES: dict[str, Callable[[dict], bool]] = {
    "idle_compat_pass": _idle_compat("pass"),
    "idle_compat_warn": _idle_compat("warn"),
    "idle_compat_fail": _idle_compat("fail"),
    "idle_compat_unknown": _idle_compat("unknown"),
    # visibility_ready 在 index 列上分不出來（policy_received 沒進 index），
    # 所以這兩桶列的是整個 visibility_only；摘要的 count 仍是精確的。
    "visibility_ready": _mode_is("visibility_only"),
    "visibility_not_ready": _mode_is("visibility_only"),
    "selective": _mode_is("selective"),
    "full": _mode_is("full"),
    "fresh": _hslh_between(None, _HEARTBEAT_FRESH_H),
    "stale_24h": _hslh_between(_HEARTBEAT_FRESH_H, _HEARTBEAT_STALE_H),
    "stale_48h": _hslh_between(_HEARTBEAT_STALE_H, None),
    "no_heartbeat": lambda r: r.get("hslh") is None,
    "unlabeled": lambda r: not (r.get("app") or r.get("env")),
    "offline": lambda r: not r.get("online"),
}


def _next_run_at(job_id: str = "ven_summary") -> str | None:
    """由 last_run + interval_seconds 推導。

    APScheduler 的 `next_run_time` 活在排程行程的記憶體裡，沒有落地到
    `job_health.json`（那裡只有 last_run / last_status / interval_seconds）。
    推導值在 job 卡住時會落在過去——那本身就是有用的訊號，比留白好。
    兩個輸入缺一即 None，不猜。
    """
    import datetime as dt

    from src import job_health
    try:
        entry = (job_health.load_job_health() or {}).get(job_id) or {}
    except Exception:
        return None
    last, interval = entry.get("last_run"), entry.get("interval_seconds")
    if not last or not interval:
        return None
    try:
        stamp = dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc)
        return (stamp + dt.timedelta(seconds=int(interval))).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None


def _load_fleet() -> dict:
    try:
        return (read_dashboard_summary() or {}).get("fleet") or {}
    except Exception:
        return {}


def make_fleet_blueprint(cm, csrf, limiter, login_required) -> Blueprint:
    bp = Blueprint("fleet_api", __name__)

    @bp.route("/api/fleet")
    @login_required
    def get_fleet():
        fleet = _load_fleet()
        # 「還沒跑過排程」與「車隊是空的」是兩件事：回一份 0 的摘要會讓
        # 看板顯示一個從未存在過的答案。
        available = bool(fleet) and "total" in fleet
        summary = {k: v for k, v in fleet.items() if k != "workloads_index"} if available else {}
        return jsonify({"ok": True, "available": available, "fleet": summary,
                        "next_run_at": _next_run_at()})

    @bp.route("/api/fleet/list")
    @login_required
    def list_fleet():
        bucket = request.args.get("bucket") or ""
        pred = BUCKET_PREDICATES.get(bucket)
        if pred is None:
            # 不合法的桶回 400：空清單會被讀成「這個桶裡沒東西」。
            return _err("invalid bucket", 400)
        try:
            offset = max(0, int(request.args.get("offset", 0)))
            limit = min(_MAX_LIMIT, max(1, int(request.args.get("limit", _DEFAULT_LIMIT))))
        except ValueError:
            return _err("invalid paging", 400)

        fleet = _load_fleet()
        rows = [r for r in (fleet.get("workloads_index") or []) if pred(r)]
        return jsonify({"ok": True, "bucket": bucket, "total": len(rows),
                        "rows": rows[offset:offset + limit],
                        "index_truncated": bool(fleet.get("index_truncated"))})

    return bp
