"""Job 健康儲存：每個排程 job 的 last_run / last_status 落地 logs/job_health.json。

2026-07-14 archive 事故的根治配套——「應跑未跑」必須可觀測。複用
state_store 的檔案鎖＋原子寫（多 executor 執行緒併發寫同檔）。
寫入節流：同 job 60 秒內的重複 ok 寫入略過（秒級 tick job 防磁碟 churn）；
error 或狀態變化一律寫。
"""
from __future__ import annotations

import datetime
import os

from src.state_store import load_state_file, update_state_file


def _job_health_file() -> str:
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(pkg_dir)
    return os.path.join(root_dir, "logs", "job_health.json")


def _now_z() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_job_health() -> dict:
    return load_state_file(_job_health_file())


def record_job_registered(job_id: str, interval_seconds: int) -> None:
    """排程註冊時種下記錄：讓「從未跑過」立即可見，且不得洗掉既有 last_run。"""
    now = _now_z()

    def _merge(data: dict) -> dict:
        entry = dict(data.get(job_id) or {})
        entry.setdefault("last_status", "registered")
        entry["interval_seconds"] = int(interval_seconds)
        entry["registered_at"] = now
        data[job_id] = entry
        return data

    _safe_update(_merge)


def record_job_run(job_id: str, status: str, detail: str = "", *,
                   interval_seconds: int | None = None,
                   min_write_gap_seconds: int = 60) -> None:
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    if status == "ok":
        # 節流前置檢查（無鎖快速路徑）：距上次同狀態寫入太近就略過
        try:
            prev = load_job_health().get(job_id) or {}
            if prev.get("last_status") == "ok" and prev.get("last_run"):
                last = datetime.datetime.strptime(
                    prev["last_run"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=datetime.timezone.utc)
                if (now_dt - last).total_seconds() < min_write_gap_seconds:
                    return
        except Exception:
            pass

    def _merge(data: dict) -> dict:
        entry = dict(data.get(job_id) or {})
        entry["last_run"] = now
        entry["last_status"] = status
        entry["detail"] = str(detail)[:300]
        if interval_seconds is not None:
            entry["interval_seconds"] = int(interval_seconds)
        data[job_id] = entry
        return data

    _safe_update(_merge)


def _safe_update(merge) -> None:
    """健康記錄是輔助訊號：寫入失敗絕不影響 job 本體，吞掉並靜默。"""
    try:
        os.makedirs(os.path.dirname(_job_health_file()), exist_ok=True)
        update_state_file(_job_health_file(), merge)
    except Exception:
        pass
