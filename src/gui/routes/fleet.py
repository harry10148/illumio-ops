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

import datetime
import os
import uuid

from flask import Blueprint, jsonify, request
from loguru import logger

from src.dashboard_store import read_dashboard_summary
from src.fleet_progress_store import FleetProgressStore
from src.gui._helpers import _err, _is_workload_href
from src.report.analysis.fleet import PIPELINE_BUCKETS, VALID_PROGRESSIONS


def _store_path() -> str:
    """紀錄檔位置。獨立成函式，測試才有一個乾淨的替換點。"""
    return os.path.join("config", "fleet_progressions.json")


def _current_user() -> str:
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            return str(current_user.get_id())
    except Exception:
        pass
    return "?"


def _audit_action(action: str, **fields) -> None:
    """審計 log——best-effort，絕不阻斷主操作（比照 routes/actions.py）。"""
    try:
        from src.module_log import ModuleLog
        parts = " ".join(f"{k}={v}" for k, v in fields.items())
        ModuleLog.get("actions").info(f"{action}: user={_current_user()} {parts}")
    except Exception:
        pass

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


# 推進只准往前，且只准動 enforcement_mode 一個欄位。這兩件事在這裡是 white-list
# 而非檢查清單：新增一個 PCE 模式時預設是「不可推進」。
_PROGRESS_TARGETS = ("visibility_only", "selective", "full")


def classify_targets(index_rows: list[dict], to_mode: str, cap: int,
                     *, requested: list[str] | None = None
                     ) -> tuple[list[dict], list[dict], list[dict]]:
    """把候選分成 eligible／deferred／skipped，每個 skipped 都帶一個理由。

    preview 與 apply 呼叫的是同一支：預覽看到的與真正被改的必須出自同一個
    定義，兩份各寫一次遲早會在某個版本分岔。

    - deferred：合法但目前離線。PCE 接受寫入，VEN 下次 heartbeat 才套用，
      所以它不是「不能推」而是「推了要等」。歸進 skipped 會讓操作者以為
      這台有問題。
    - skipped 的理由：unknown_href / not_managed / already_target /
      invalid_transition / over_cap。沒有理由的 skipped 清單等於沒有清單。
    """
    by_href = {str(r.get("href") or ""): r for r in index_rows or []}
    if requested is None:
        rows = list(index_rows or [])
        missing: list[str] = []
    else:
        rows = [by_href[h] for h in requested if h in by_href]
        missing = [h for h in requested if h not in by_href]

    eligible: list[dict] = []
    deferred: list[dict] = []
    skipped: list[dict] = [{"href": h, "hostname": "", "reason": "unknown_href"}
                           for h in missing]

    for r in rows:
        href = str(r.get("href") or "")
        host = str(r.get("hostname") or "")
        mode = str(r.get("mode") or "")
        brief = {"href": href, "hostname": host, "from": mode, "to": to_mode}
        if not mode:
            skipped.append({"href": href, "hostname": host, "reason": "not_managed"})
        elif mode == to_mode:
            skipped.append({"href": href, "hostname": host, "reason": "already_target"})
        elif to_mode not in VALID_PROGRESSIONS.get(mode, set()):
            skipped.append({"href": href, "hostname": host, "reason": "invalid_transition"})
        elif r.get("online"):
            eligible.append(brief)
        else:
            deferred.append(brief)

    # cap 是「這一批要寫幾筆 PCE」，離線的一樣會被寫，所以兩者合計後才截。
    eligible.sort(key=lambda r: r["hostname"])
    deferred.sort(key=lambda r: r["hostname"])
    combined = sorted(eligible + deferred, key=lambda r: r["hostname"])
    cap = max(0, int(cap))
    if len(combined) > cap:
        kept = {r["href"] for r in combined[:cap]}
        for r in combined[cap:]:
            # 被 cap 掉的必須出現在 skipped：默默消失的那幾台是最危險的
            # 那種「成功」。
            skipped.append({"href": r["href"], "hostname": r["hostname"],
                            "reason": "over_cap"})
        eligible = [r for r in eligible if r["href"] in kept]
        deferred = [r for r in deferred if r["href"] in kept]
    return eligible, deferred, skipped


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

    def _index_rows() -> list[dict]:
        return _load_fleet().get("workloads_index") or []

    def _cap() -> int:
        raw = (cm.config.get("settings", {}) or {}).get("fleet_max_batch") or 200
        try:
            return min(1000, max(1, int(raw)))
        except (TypeError, ValueError):
            return 200

    def _targets(payload: dict):
        """把 {hrefs} 或 {bucket} 解析成候選列，並回 (rows, requested, err)。"""
        hrefs, bucket = payload.get("hrefs"), payload.get("bucket")
        # 兩個都給時該用哪個沒有正確答案，所以不猜。
        if bool(hrefs) == bool(bucket):
            return None, None, _err("give exactly one of hrefs or bucket", 400)
        rows = _index_rows()
        if bucket:
            pred = BUCKET_PREDICATES.get(str(bucket))
            if pred is None:
                return None, None, _err("invalid bucket", 400)
            return [r for r in rows if pred(r)], None, None
        clean = [str(h).strip() for h in hrefs if _is_workload_href(str(h))]
        if not clean:
            return None, None, _err("no valid workload href", 400)
        return rows, clean, None

    @bp.route("/api/fleet/progress/preview", methods=["POST"])
    @limiter.limit("10 per minute")
    @login_required
    def preview_progress():
        payload = request.get_json(silent=True) or {}
        to_mode = str(payload.get("to_mode") or "")
        if to_mode not in _PROGRESS_TARGETS:
            return _err("invalid to_mode", 400)
        rows, requested, err = _targets(payload)
        if err is not None:
            return err
        cap = _cap()
        eligible, deferred, skipped = classify_targets(rows, to_mode, cap, requested=requested)
        return jsonify({"ok": True, "to_mode": to_mode, "eligible": eligible,
                        "deferred": deferred, "skipped": skipped, "cap": cap,
                        "truncated": any(s["reason"] == "over_cap" for s in skipped)})

    @bp.route("/api/fleet/progress/apply", methods=["POST"])
    @limiter.limit("10 per minute")
    @login_required
    def apply_progress():
        payload = request.get_json(silent=True) or {}
        to_mode = str(payload.get("to_mode") or "")
        if to_mode not in _PROGRESS_TARGETS:
            return _err("invalid to_mode", 400)
        raw = payload.get("hrefs")
        if not isinstance(raw, list) or not raw:
            return _err("hrefs required", 400)
        requested = [str(h).strip() for h in raw if _is_workload_href(str(h))]
        if len(requested) != len(raw):
            return _err("invalid workload href", 400)

        # 伺服端重跑分類：preview 的結果不可信（畫面可能過期，也可能被改過）。
        eligible, deferred, skipped = classify_targets(
            _index_rows(), to_mode, _cap(), requested=requested)
        if skipped:
            # 一筆不合格就整批拒絕。部分套用是最難收拾的結果：操作者不知道
            # 哪幾台動了。
            return jsonify({"ok": False, "skipped": skipped}), 400

        targets = eligible + deferred
        deferred_hrefs = {r["href"] for r in deferred}
        from src.api_client import ApiClient
        with ApiClient(cm) as api:
            results = api.bulk_update_workloads(
                [{"href": r["href"], "enforcement_mode": to_mode} for r in targets])
        by_href = {r.get("href"): r for r in results}

        applied, failed, items = [], [], []
        for r in targets:
            res = by_href.get(r["href"]) or {"status": "error", "http": 0,
                                             "errors": ["no answer for this href"]}
            row = {"href": r["href"], "hostname": r["hostname"], "from": r["from"],
                   "to": to_mode, "deferred": r["href"] in deferred_hrefs}
            if res.get("status") == "updated":
                applied.append(row)
            else:
                failed.append({**row, "http": res.get("http"),
                               "error": str(res.get("errors") or "")[:300]})
            items.append({"href": r["href"], "hostname": r["hostname"],
                          "previous_mode": r["from"], "new_mode": to_mode,
                          "deferred": row["deferred"], "status": res.get("status"),
                          "http": res.get("http"), "errors": res.get("errors") or []})

        record_id = uuid.uuid4().hex
        try:
            FleetProgressStore(_store_path()).put(record_id, {
                "at": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "user": _current_user(), "to_mode": to_mode, "items": items,
            })
        except Exception:
            logger.exception("fleet progression record failed to persist")
        _audit_action("fleet_progress", to_mode=to_mode, applied=len(applied),
                      failed=len(failed), record_id=record_id)
        return jsonify({"ok": True, "applied": applied, "failed": failed,
                        "record_id": record_id,
                        # PCE 收下 ≠ VEN 套用了：政策在受影響的 VEN 下次
                        # heartbeat 才生效，期間 PCE 顯示 Syncing。
                        "pending_heartbeat": True})

    @bp.route("/api/fleet/progress/records")
    @login_required
    def progress_records():
        try:
            limit = min(100, max(1, int(request.args.get("limit", 20))))
        except ValueError:
            return _err("invalid limit", 400)
        try:
            records = FleetProgressStore(_store_path()).recent(limit)
        except Exception:
            logger.exception("fleet progression records unreadable")
            return _err("records unreadable", 500)
        return jsonify({"ok": True, "records": records})

    return bp
