"""資料完整性儲存：集合 GET 截斷且 async fallback 未恢復時落地
logs/data_integrity.json，供 Integrations overview 呈現（原
last_truncated_collections 是 process 內 write-only 遙測，無人消費）。

鏡射 job_health.py 模式：state_store 檔案鎖＋原子寫；記錄失敗絕不影響
API 主路徑（_safe_update 靜默）。
"""
from __future__ import annotations

import datetime
import os

from src.state_store import load_state_file, update_state_file


def _data_integrity_file() -> str:
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(pkg_dir)
    return os.path.join(root_dir, "logs", "data_integrity.json")


def _now_z() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_data_integrity() -> dict:
    return load_state_file(_data_integrity_file())


def record_truncation(path: str, got: int, total: int) -> None:
    """記錄一次「截斷且 fallback 失敗」：同 path 覆寫（保留最新事實）。"""
    now = _now_z()

    def _merge(data: dict) -> dict:
        data[path] = {"last_seen": now, "got": int(got), "total": int(total)}
        return data

    _safe_update(_merge)


def clear_truncation(path: str) -> None:
    """fallback 恢復（或後續呼叫未再截斷）時移除紀錄。"""

    def _merge(data: dict) -> dict:
        data.pop(path, None)
        return data

    _safe_update(_merge)


def _safe_update(merge) -> None:
    """完整性紀錄是輔助訊號：寫入失敗絕不影響 API 呼叫本體。"""
    try:
        os.makedirs(os.path.dirname(_data_integrity_file()), exist_ok=True)
        update_state_file(_data_integrity_file(), merge)
    except Exception:
        pass
