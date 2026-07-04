import builtins
import json
import os
from unittest.mock import patch

import pytest

from src.config import ConfigManager


@pytest.fixture
def cm(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({}))
    return ConfigManager(config_file=str(p))


def _seq(values):
    it = iter(values)
    return lambda _p="": next(it)


def test_menu_back_exits(cm, capsys):
    from src.pce_cache_cli import manage_pce_cache_menu
    with patch.object(builtins, "input", _seq(["0"])):
        manage_pce_cache_menu(cm)
    assert "PCE Cache Menu" in capsys.readouterr().out


def test_menu_edit_settings_persists(cm):
    """Option 2, accept defaults except events_retention_days=60."""
    from src.pce_cache_cli import manage_pce_cache_menu
    # Sequence: choose 2 → 9 prompts (enabled, db_path, events_retention_days,
    # traffic_raw_retention_days, traffic_agg_retention_days,
    # events_poll_interval_seconds, traffic_poll_interval_seconds,
    # rate_limit_per_minute, async_threshold_events) → then "0" to exit
    inputs = ["2", "", "", "60", "", "", "", "", "", "", "0"]
    with patch.object(builtins, "input", _seq(inputs)):
        manage_pce_cache_menu(cm)
    # Reload from disk to verify persistence
    cm2 = ConfigManager(config_file=cm.config_file)
    assert cm2.config.get("pce_cache", {}).get("events_retention_days") == 60


def test_menu_retention_passes_archive_enabled(tmp_path):
    """選項 6（Run retention now）必須把設定的 archive_enabled 傳給
    RetentionWorker.run_once，否則客戶啟用 archive 後這個入口會靜默刪除未 archive 的列。"""
    from src.pce_cache_cli import manage_pce_cache_menu
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "pce_cache": {
            "db_path": str(tmp_path / "cache.sqlite"),
            "archive_enabled": True,
        },
    }))
    cm = ConfigManager(config_file=str(p))
    with patch.object(builtins, "input", _seq(["6", "0"])), \
         patch("src.pce_cache.retention.RetentionWorker") as MockWorker:
        MockWorker.return_value.run_once.return_value = {}
        manage_pce_cache_menu(cm)
    _, kwargs = MockWorker.return_value.run_once.call_args
    assert kwargs.get("archive_enabled") is True


def test_traffic_filter_env_and_ips_via_picker(cm):
    """選項 3（Edit traffic filter）：workload_label_env / exclude_src_ips 兩 key 改走
    object picker（非 TTY 真實鏈：走 pick_objects 的 input() 降級，不 stub picker）。
    env 槽存 bare value（與既有 config 格式一致，picker 內部以 "env=value" 候選格式
    往返，存檔前剝除 "env=" 前綴）；ips 槽直接存 picker 選中的字串。
    actions/protocols 兩 key 維持原 input，此處留空＝保留預設。"""
    from src.pce_cache_cli import manage_pce_cache_menu
    inputs = ["3", "", "", "Production", "10.0.0.5", "", "0"]
    with patch.object(builtins, "input", _seq(inputs)), \
         patch("src.api_client.ApiClient") as MockApiClient:
        MockApiClient.return_value.get_all_labels.return_value = [
            {"key": "env", "value": "Production", "href": "/orgs/1/labels/1"},
        ]
        manage_pce_cache_menu(cm)
    cm2 = ConfigManager(config_file=cm.config_file)
    tf = cm2.config.get("pce_cache", {}).get("traffic_filter", {})
    assert tf.get("workload_label_env") == ["Production"]
    assert tf.get("exclude_src_ips") == ["10.0.0.5"]
    # 確認真的走了 picker（會建構 ApiClient），而非沿用舊版純 input() 迴圈
    # 注：非 TTY 降級路徑不載入候選（見 object_picker._pick_non_tty），故不斷言 get_all_labels 被呼叫
    MockApiClient.assert_called_once()


def test_traffic_filter_pick_or_cancel_returns_none_on_keyboard_interrupt(monkeypatch):
    """Ctrl-C 防護：_pick_or_cancel 接住 pick_objects 拋出的 KeyboardInterrupt，
    回傳 None（呼叫端據此保留該 key 原值，不中斷整個選單）。"""
    from unittest.mock import MagicMock
    from src.pce_cache_cli import _pick_or_cancel

    def _raise(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("src.pce_cache_cli.pick_objects", _raise)
    assert _pick_or_cancel(MagicMock(), cats=("label",), title="x") is None


def test_menu_invalid_choice(cm, capsys):
    from src.pce_cache_cli import manage_pce_cache_menu
    with patch.object(builtins, "input", _seq(["99", "0"])):
        manage_pce_cache_menu(cm)
    out = capsys.readouterr().out.lower()
    assert "invalid" in out or "please" in out
