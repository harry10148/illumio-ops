from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import i18n
from src import settings as settings_module
import src.cli.menus.traffic as _traffic_module
import src.cli.menus.bandwidth as _bandwidth_module
import src.cli.menus._helpers as _helpers_module


def _prepare_wizard(monkeypatch, answers, raw_inputs=None):
    state = {"action": "value"}
    queue = iter(answers)

    def fake_safe_input(*_args, **_kwargs):
        value, action = next(queue)
        state["action"] = action
        return value

    # raw_inputs 餵給 object picker 的非 TTY 逐類別 prompt（一律空字串=保留 preselected）
    # 與精靈最後的 confirm/儲存暫停 input()——皆走真實 builtins.input，不 stub picker 本身。
    confirms = iter(raw_inputs if raw_inputs is not None else ["", ""])

    monkeypatch.setattr(_traffic_module.os, "system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_bandwidth_module.os, "system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.utils.draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_traffic_module, "safe_input", fake_safe_input)
    monkeypatch.setattr(_bandwidth_module, "safe_input", fake_safe_input)
    monkeypatch.setattr(_helpers_module, "get_last_input_action", lambda: state["action"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(confirms))
    monkeypatch.setattr("src.api_client.ApiClient", lambda _cm: object())


# 4 個物件方向槽（src/dst/ex_src/ex_dst）× 4 類別（label/iplist/workload/ip，見
# object_picker._CAT_ORDER）在非 TTY 降級路徑下各自一個 input()；全空＝保留 preselected。
_ALL_SLOTS_EMPTY = [""] * 16


@pytest.fixture(autouse=True)
def _english_ui():
    previous = i18n.get_language()
    i18n.set_language("en")
    try:
        yield
    finally:
        i18n.set_language(previous)


def test_add_traffic_menu_enter_uses_numeric_defaults(monkeypatch):
    saved = []
    cm = SimpleNamespace(add_or_update_rule=lambda rule: saved.append(rule))
    edit_rule = {
        "id": 99,
        "type": "traffic",
        "name": "Traffic Default",
        "pd": 2,
        "port": 443,
        "proto": 6,
        "src_label": "role=app",
        "dst_label": "role=db",
        "threshold_window": 15,
        "threshold_count": 8,
        "cooldown_minutes": 20,
        "ex_port": 8443,
        "ex_src_label": "env=prod",
        "ex_dst_label": "loc=dc1",
    }
    _prepare_wizard(
        monkeypatch,
        [
            ("", "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
        ],
        raw_inputs=_ALL_SLOTS_EMPTY + ["", ""],
    )

    settings_module.add_traffic_menu(cm, edit_rule=edit_rule)

    assert len(saved) == 1
    rule = saved[0]
    assert rule["name"] == "Traffic Default"
    assert rule["pd"] == 2
    assert rule["port"] == 443
    assert rule["proto"] == 6
    assert rule["threshold_window"] == 15
    assert rule["threshold_count"] == 8
    assert rule["cooldown_minutes"] == 20
    assert rule["ex_port"] == 8443
    # 空輸入=保留 preselected：舊純量 label 遷移為 flat list key
    assert rule["src_labels"] == ["role=app"]
    assert rule["dst_labels"] == ["role=db"]
    assert rule["ex_src_labels"] == ["env=prod"]
    assert rule["ex_dst_labels"] == ["loc=dc1"]
    assert "src_label" not in rule


def test_add_bandwidth_menu_enter_uses_numeric_defaults(monkeypatch):
    saved = []
    cm = SimpleNamespace(add_or_update_rule=lambda rule: saved.append(rule))
    edit_rule = {
        "id": 123,
        "type": "bandwidth",
        "name": "Bandwidth Default",
        "port": 53,
        "proto": 17,
        "src_label": "role=dns",
        "dst_label": "role=client",
        "threshold_count": 12.5,
        "threshold_window": 30,
        "cooldown_minutes": 45,
        "ex_port": 5353,
        "ex_src_label": "env=lab",
        "ex_dst_label": "loc=edge",
    }
    _prepare_wizard(
        monkeypatch,
        [
            ("", "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
            (None, "empty"),
        ],
        raw_inputs=_ALL_SLOTS_EMPTY + ["", ""],
    )

    settings_module.add_bandwidth_volume_menu(cm, edit_rule=edit_rule)

    assert len(saved) == 1
    rule = saved[0]
    assert rule["name"] == "Bandwidth Default"
    assert rule["type"] == "bandwidth"
    assert rule["port"] == 53
    assert rule["proto"] == 17
    assert rule["threshold_count"] == 12.5
    assert rule["threshold_window"] == 30
    assert rule["cooldown_minutes"] == 45
    assert rule["ex_port"] == 5353
    # 空輸入=保留 preselected：舊純量 label 遷移為 flat list key
    assert rule["src_labels"] == ["role=dns"]
    assert rule["dst_labels"] == ["role=client"]
    assert rule["ex_src_labels"] == ["env=lab"]
    assert rule["ex_dst_labels"] == ["loc=edge"]
    assert "src_label" not in rule
