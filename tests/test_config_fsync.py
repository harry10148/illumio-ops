"""ConfigManager.save()/_write_alerts_file() 斷電保護：寫暫存檔後必須先
fsync 再 os.replace（比照 src/state_store.py 既有做法），異常時清掉孤兒暫存檔。
"""
import json
import os

import pytest


def _make_cm(tmp_path):
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "rules": [{"id": 1, "type": "event", "name": "r1", "filter_value": "x"}],
    }), encoding="utf-8")
    return ConfigManager(config_file=str(cfg))


def test_save_calls_fsync_before_replace(tmp_path, monkeypatch):
    cm = _make_cm(tmp_path)

    fsync_calls = []
    real_fsync = os.fsync

    def tracking_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracking_fsync)
    cm.save()

    # config.json 與 alerts.json 各一次 mkstemp+write，兩者都必須 fsync 過。
    assert len(fsync_calls) >= 2, f"expected fsync for both config.json and alerts.json, saw {fsync_calls}"


def test_save_unlinks_tmp_file_on_write_error(tmp_path, monkeypatch):
    """json.dump 失敗（模擬寫入中斷）時，config.json 的暫存檔不得留在磁碟上。"""
    cm = _make_cm(tmp_path)
    config_dir = tmp_path

    def boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "fsync", boom)

    # save() 現在會把 IOError/OSError 往外拋（fail-loud，讓 GUI 不會誤報成功）；
    # 但拋出前必須先清掉孤兒暫存檔。
    with pytest.raises(OSError):
        cm.save()

    leftover = [f for f in os.listdir(config_dir) if f.endswith(".tmp")]
    assert leftover == [], f"orphan tmp file(s) left behind: {leftover}"


def test_save_still_writes_valid_config_and_alerts(tmp_path):
    """sanity：加入 fsync 後兩個檔案內容仍正確落地。"""
    cm = _make_cm(tmp_path)
    cm.save()

    with open(cm.config_file, encoding="utf-8") as f:
        data = json.load(f)
    assert data["api"]["url"] == "https://pce.test"
    assert "rules" not in data

    with open(cm.alerts_file, encoding="utf-8") as f:
        alerts = json.load(f)
    assert alerts["rules"][0]["filter_value"] == "x"
