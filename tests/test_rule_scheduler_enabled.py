"""rule_scheduler.enabled=false 時不得改動 PCE 上的規則。

舊版排程永遠註冊 tick_rule_schedules、執行時也不檢查開關：CLI 把 Rule
Scheduler 切成 OFF 之後，規則仍照排程被啟用／停用並 provision。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def _cm(tmp_path, enabled):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"rule_scheduler": {"enabled": enabled}}), encoding="utf-8")
    cm = MagicMock()
    cm.config_file = str(path)
    cm.config = {"rule_scheduler": {"enabled": True}}   # 記憶體中的舊值
    return cm


def test_tick_skips_when_disabled_on_disk(tmp_path):
    from src.scheduler.jobs import tick_rule_schedules
    cm = _cm(tmp_path, enabled=False)
    with patch("src.rule_scheduler.ScheduleEngine") as engine:
        tick_rule_schedules(cm)
    engine.assert_not_called()


def test_tick_runs_when_enabled(tmp_path):
    from src.scheduler.jobs import tick_rule_schedules
    cm = _cm(tmp_path, enabled=True)
    with patch("src.rule_scheduler.ScheduleEngine") as engine, \
         patch("src.rule_scheduler.ScheduleDB"), \
         patch("src.api_client.ApiClient"):
        engine.return_value.check.return_value = []
        tick_rule_schedules(cm)
    engine.assert_called_once()


def test_enabled_falls_back_to_loaded_config(tmp_path):
    from src.rule_scheduler import rule_scheduler_enabled
    cm = MagicMock()
    cm.config_file = str(tmp_path / "missing.json")
    cm.config = {"rule_scheduler": {"enabled": False}}
    assert rule_scheduler_enabled(cm) is False
