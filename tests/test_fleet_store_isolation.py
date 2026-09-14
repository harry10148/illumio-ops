"""Guard: the autouse fixture keeps every test off the real config/fleet_progressions.json.

2026-09-14：Task 3 的注入實驗讓 apply 真的走通，於是三筆 enforcement 推進
紀錄落進了開發機的產品設定目錄。這支測試存在的理由就是那件事。
"""
from __future__ import annotations

import hashlib
import os

import src.gui.routes.fleet as fleet_routes
from src.config import ROOT_DIR

REAL = os.path.join(ROOT_DIR, "config", "fleet_progressions.json")


def _fingerprint():
    if not os.path.exists(REAL):
        return None
    with open(REAL, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def test_default_path_is_redirected_during_tests(_isolate_fleet_progress_store):
    assert fleet_routes._store_path() == _isolate_fleet_progress_store
    assert not fleet_routes._store_path().startswith(ROOT_DIR)


def test_a_real_put_does_not_touch_the_product_file(tmp_path):
    """實際寫一筆，然後確認產品檔案的指紋沒變。

    斷言的是「產品檔案沒被動到」，不是「fixture 有被呼叫」——後者只是代理
    指標，fixture 存在而沒生效時它照樣綠。
    """
    from src.fleet_progress_store import FleetProgressStore

    before = _fingerprint()
    FleetProgressStore(fleet_routes._store_path()).put("guard", {
        "at": "2026-09-14T00:00:00Z", "user": "isolation-guard",
        "to_mode": "selective", "items": [],
    })
    assert _fingerprint() == before
    assert FleetProgressStore(fleet_routes._store_path()).get("guard") is not None
