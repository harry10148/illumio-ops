"""VEN 推進紀錄：每一次 apply 落一筆，含 previous_mode 以便還原。

儲存形狀與併發保護照抄 `src/rule_scheduler.py` 的 `ScheduleDB`——同一支
file_lock、同一種 mkstemp + os.replace 原子寫、同一種 corrupt 隔離。刻意不
另創一套：那個類別的每一條註解都是某次事故換來的（共用 tmp 檔名讓兩個寫入
者交錯、讀取失敗被誤判成內容壞掉而把檔案 rename 走）。

預設路徑 `config/fleet_progressions.json`。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from loguru import logger

from src.file_lock import file_lock

_DEFAULT_PATH = os.path.join("config", "fleet_progressions.json")


class FleetProgressStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or _DEFAULT_PATH
        self.lock_path = os.path.abspath(self.db_path) + ".lock"

    # ── 讀 ──────────────────────────────────────────────────────────────
    def _load_unlocked(self) -> dict:
        if not os.path.exists(self.db_path):
            return {}
        try:
            with open(self.db_path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as e:
            # 讀取失敗 ≠ 內容壞掉：位元組根本沒被讀進來。比照 ScheduleDB
            # fail closed，絕不隔離檔案——那會讓所有紀錄永久消失。
            logger.error(f"FleetProgressStore read failed ({e}); file left untouched")
            raise
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError(f"root must be dict, got {type(data).__name__}")
            return data
        except (json.JSONDecodeError, ValueError) as e:
            corrupt = f"{self.db_path}.corrupt.{int(time.time())}"
            try:
                os.rename(self.db_path, corrupt)
            except OSError as rename_err:
                logger.error(f"FleetProgressStore corrupt; quarantine failed: {rename_err}")
            else:
                logger.error(f"FleetProgressStore corrupt; quarantined to {corrupt}: {e}")
            raise ValueError(f"FleetProgressStore corrupt: {e}") from e

    def get(self, record_id: str) -> dict | None:
        with file_lock(self.lock_path):
            return self._load_unlocked().get(record_id)

    def recent(self, limit: int = 20) -> list[dict]:
        """新到舊。每筆帶回自己的 `id`，呼叫端才有東西可以指回來。"""
        with file_lock(self.lock_path):
            data = self._load_unlocked()
        rows = [{**rec, "id": rid} for rid, rec in data.items() if isinstance(rec, dict)]
        rows.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
        return rows[:max(0, int(limit))]

    # ── 寫 ──────────────────────────────────────────────────────────────
    def put(self, record_id: str, record: dict) -> None:
        """鎖內重讀再寫：兩個 apply 同時落地時，後者不得蓋掉前者那筆。"""
        with file_lock(self.lock_path):
            data = self._load_unlocked()
            data[str(record_id)] = record
            db_dir = os.path.dirname(os.path.abspath(self.db_path)) or "."
            os.makedirs(db_dir, exist_ok=True)
            # mkstemp 而非固定的 "<db>.tmp"：共用檔名會讓兩個寫入者交錯，
            # 交錯後的輸出被 os.replace 裝進正式路徑，下次讀就是 corrupt。
            fd, tmp_path = tempfile.mkstemp(dir=db_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, self.db_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise  # 原子寫失敗必須浮上來，沒有 fallback
