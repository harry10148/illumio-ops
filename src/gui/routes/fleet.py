"""VEN 盤點 API（唯讀）——只讀 run_ven_summary 寫下的快照，不碰 PCE。

    GET /api/fleet
    GET /api/fleet/list?bucket=&q=&version=&app=&env=&sort=&dir=&offset=&limit=
    GET /api/fleet/export.csv?<same filters, no paging>

本工具不改 PCE 上的 enforcement mode：盤點只負責呈現現況，推進請在 PCE 進行。

Auth 走 app 層的 before_request；全部都是 GET，沒有 CSRF。
"""
from __future__ import annotations

import csv
import io
from typing import Any, Callable

from flask import Blueprint, Response, jsonify, request

from src.dashboard_store import read_dashboard_summary
from src.gui._helpers import _err
from src.i18n import t
from src.report.analysis.fleet import parse_ven_version

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
    "online": lambda r: bool(r.get("online")),
    "all": lambda r: True,
}

# 這兩個桶依賴快照裡的目標版本，所以不是靜態 predicate。判定與 analyze_fleet
# 的 on_target 完全相同（版本字串相等），清單筆數才會等於摘要上的數字。
_TARGET_BUCKETS = ("needs_upgrade", "on_target")

_SORT_KEYS = ("hostname", "mode", "online", "version", "compat", "hslh", "app", "env", "os")

# enforcement 由寬到嚴；排序照這個順序而不是字母，"full" 才不會排在 "idle" 前面。
_MODE_ORDER = {"idle": 0, "visibility_only": 1, "selective": 2, "full": 3}
_COMPAT_ORDER = {"fail": 0, "warn": 1, "unknown": 2, "pass": 3}


def _sort_value(row: dict, key: str) -> Any:
    v = row.get(key)
    if key == "version":
        return parse_ven_version(v)
    if key == "mode":
        return _MODE_ORDER.get(str(v or ""))
    if key == "compat":
        return _COMPAT_ORDER.get(str(v or ""))
    if key == "online":
        return None if v is None else (1 if v else 0)
    if key == "hslh":
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None
    text = str(v or "").strip().casefold()
    return text or None


def _sorted(rows: list[dict], key: str, desc: bool) -> list[dict]:
    """缺值一律排最後（兩個方向都是）：未知不是最小值。"""
    present = [r for r in rows if _sort_value(r, key) is not None]
    missing = [r for r in rows if _sort_value(r, key) is None]
    present.sort(key=lambda r: (_sort_value(r, key), str(r.get("hostname") or "")), reverse=desc)
    return present + missing


def _matches_query(row: dict, q: str) -> bool:
    hay = " ".join(str(row.get(k) or "") for k in ("hostname", "app", "env", "version", "os"))
    return q in hay.casefold()


def _filter_rows(fleet: dict, args) -> tuple[list[dict] | None, str]:
    """套用 bucket／q／version／app／env 篩選。不合法的參數回 (None, 錯誤字串)。"""
    bucket = args.get("bucket") or "all"
    rows = list(fleet.get("workloads_index") or [])
    if bucket in _TARGET_BUCKETS:
        target = ((fleet.get("versions") or {}).get("target") or "").strip()
        if not target:
            # 沒設目標版本時「待升級」沒有定義；回空清單會被讀成「全部都在目標上」。
            return None, "no target version set"
        want = bucket == "on_target"
        rows = [r for r in rows if (r.get("version") == target) == want]
    else:
        pred = BUCKET_PREDICATES.get(bucket)
        if pred is None:
            # 不合法的桶回 400：空清單會被讀成「這個桶裡沒東西」。
            return None, "invalid bucket"
        rows = [r for r in rows if pred(r)]
    for field in ("version", "app", "env"):
        val = args.get(field)
        if val is not None and val != "":
            rows = [r for r in rows if str(r.get(field) or "") == val]
    q = (args.get("q") or "").strip().casefold()
    if q:
        rows = [r for r in rows if _matches_query(r, q)]
    sort = args.get("sort") or "hostname"
    if sort not in _SORT_KEYS:
        return None, "invalid sort"
    direction = args.get("dir") or "asc"
    if direction not in ("asc", "desc"):
        return None, "invalid sort"
    return _sorted(rows, sort, direction == "desc"), ""


_CSV_PREFIXES = ("=", "+", "-", "@")


def _csv_cell(v: Any) -> Any:
    # 與 csv_exporter._neutralize 同契約：主機名稱與 label 來自 PCE，開頭為
    # = + - @ 的字串在試算表裡會被當公式執行。
    if isinstance(v, str) and v[:1] in _CSV_PREFIXES:
        return "'" + v
    return v


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
        # 「還沒跑過排程」與「沒有任何 VEN」是兩件事：回一份 0 的摘要會讓
        # 看板顯示一個從未存在過的答案。
        available = bool(fleet) and "total" in fleet
        summary = {k: v for k, v in fleet.items() if k != "workloads_index"} if available else {}
        return jsonify({"ok": True, "available": available, "fleet": summary,
                        "next_run_at": _next_run_at()})

    @bp.route("/api/fleet/list")
    @login_required
    def list_fleet():
        try:
            offset = max(0, int(request.args.get("offset", 0)))
            limit = min(_MAX_LIMIT, max(1, int(request.args.get("limit", _DEFAULT_LIMIT))))
        except ValueError:
            return _err("invalid paging", 400)

        fleet = _load_fleet()
        rows, problem = _filter_rows(fleet, request.args)
        if rows is None:
            return _err(problem, 400)
        return jsonify({"ok": True, "bucket": request.args.get("bucket") or "all",
                        "total": len(rows), "rows": rows[offset:offset + limit],
                        "index_truncated": bool(fleet.get("index_truncated"))})

    @bp.route("/api/fleet/export.csv")
    @login_required
    def export_fleet():
        """目前篩選的完整清單（不分頁）。表頭跟著介面語言。"""
        fleet = _load_fleet()
        rows, problem = _filter_rows(fleet, request.args)
        if rows is None:
            return _err(problem, 400)
        lang = (cm.config.get("settings", {}) or {}).get("language", "en") or "en"
        cols = [("hostname", "gui_fleet_col_hostname"), ("mode", "gui_fleet_col_mode"),
                ("online", "gui_fleet_col_online"), ("version", "gui_fleet_col_version"),
                ("compat", "gui_fleet_col_compat"), ("hslh", "gui_fleet_col_hslh"),
                ("app", "gui_fleet_col_app"), ("env", "gui_fleet_col_env"),
                ("os", "gui_fleet_col_os"), ("href", "gui_fleet_col_href")]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([t(key, lang=lang) for _f, key in cols])
        for r in rows:
            w.writerow([_csv_cell("" if r.get(f) is None else r.get(f)) for f, _k in cols])
        # BOM 讓 Excel 以 UTF-8 開啟中文主機名稱與 label。
        return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="ven_inventory.csv"'})

    return bp
