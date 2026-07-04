from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src import i18n
from src import settings as settings_module


def _make_cm():
    removed = []
    cm = SimpleNamespace(
        config={
            "rules": [
                {"name": "Event Rule", "type": "event", "threshold_count": 1, "threshold_window": 10},
                {"name": "Traffic Rule", "type": "traffic", "threshold_count": 5, "threshold_window": 10},
                {"name": "Bandwidth Rule", "type": "bandwidth", "threshold_count": 10.0, "threshold_window": 30},
            ]
        }
    )

    def remove_rules_by_index(indices):
        removed.append(indices)

    cm.remove_rules_by_index = remove_rules_by_index
    return cm, removed


def _prepare_menu(monkeypatch, answers):
    inputs = iter(answers)
    monkeypatch.setattr(settings_module.os, "system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.utils.draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.utils.draw_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(inputs))


@pytest.fixture(autouse=True)
def _english_ui():
    previous = i18n.get_language()
    i18n.set_language("en")
    try:
        yield
    finally:
        i18n.set_language(previous)


def test_manage_rules_menu_help_command_shows_examples(monkeypatch, capsys):
    cm, _removed = _make_cm()
    _prepare_menu(monkeypatch, ["?", "0"])

    settings_module.manage_rules_menu(cm)

    output = capsys.readouterr().out
    assert "Commands: m <index>" in output
    assert "d <index1,index2>" in output


def test_manage_rules_menu_delete_command_accepts_multiple_indices(monkeypatch, capsys):
    cm, removed = _make_cm()
    _prepare_menu(monkeypatch, ["d 1, 2", "", "0"])

    settings_module.manage_rules_menu(cm)

    assert removed == [[1, 2]]
    assert "Done." in capsys.readouterr().out


def test_manage_rules_menu_modify_command_routes_by_rule_type(monkeypatch, capsys):
    cm, removed = _make_cm()
    calls = []
    _prepare_menu(monkeypatch, ["m 1", "", "0"])

    monkeypatch.setattr(settings_module, "add_event_menu", lambda *_args, **_kwargs: calls.append("event"))
    monkeypatch.setattr(settings_module, "add_system_health_menu", lambda *_args, **_kwargs: calls.append("system"))
    monkeypatch.setattr(settings_module, "add_traffic_menu", lambda *_args, **_kwargs: calls.append("traffic"))
    monkeypatch.setattr(settings_module, "add_bandwidth_volume_menu", lambda *_args, **_kwargs: calls.append("bandwidth"))

    settings_module.manage_rules_menu(cm)

    assert removed == []
    assert calls == ["traffic"]
    assert "Modifying rule: Traffic Rule" in capsys.readouterr().out


def test_manage_rules_menu_rejects_invalid_format(monkeypatch, capsys):
    cm, removed = _make_cm()
    _prepare_menu(monkeypatch, ["bad", "", "0"])

    settings_module.manage_rules_menu(cm)

    assert removed == []
    assert "Invalid format. Use m <index> or d <index>[,index...]." in capsys.readouterr().out


def test_manage_rules_menu_rejects_multi_index_modify(monkeypatch, capsys):
    cm, removed = _make_cm()
    _prepare_menu(monkeypatch, ["m 1,2", "", "0"])

    settings_module.manage_rules_menu(cm)

    assert removed == []
    assert "Modify accepts exactly one index." in capsys.readouterr().out


def test_manage_rules_menu_cancelled_modify_keeps_rule(monkeypatch):
    cm, removed = _make_cm()
    original_rule = dict(cm.config["rules"][1])
    _prepare_menu(monkeypatch, ["m 1", "", "0"])

    monkeypatch.setattr(settings_module, "add_event_menu", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(settings_module, "add_system_health_menu", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(settings_module, "add_traffic_menu", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(settings_module, "add_bandwidth_volume_menu", lambda *_args, **_kwargs: None)

    settings_module.manage_rules_menu(cm)

    assert removed == []
    assert cm.config["rules"][1] == original_rule


# ─── Phase 5 Task 2：traffic/bandwidth 精靈接 object picker、flat filter key ──
#
# 以下測試沿真實鏈（不 stub picker 本身）：只 monkeypatch builtins.input、
# os.system、draw_panel、src.api_client.ApiClient（非 TTY 降級路徑不觸碰 api，
# 佔位物件即可）。每個物件方向槽（src/dst/ex_src/ex_dst）在非 TTY 降級路徑下，
# 依 object_picker._CAT_ORDER 交集 cats=(label, iplist, workload, ip) 各問一次，
# 順序固定為 label → iplist → workload → ip。


def _fake_cm_for_wizard():
    cm = SimpleNamespace(config={"rules": []})
    cm.add_or_update_rule = lambda rule: cm.config["rules"].append(rule)
    return cm


def _prepare_wizard_real_chain(monkeypatch, raw_inputs):
    inputs = iter(raw_inputs)
    monkeypatch.setattr("os.system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.cli.menus.traffic.draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.cli.menus.bandwidth.draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.api_client.ApiClient", lambda _cm: object())
    # 環境的 stdin/stdout isatty() 判定不可控（CI/pty 皆可能）；本測試針對非 TTY 降級
    # 路徑的真實鏈驗證，故明確釘住 _interactive_ok，避免受執行環境影響。
    monkeypatch.setattr("src.cli.object_picker._interactive_ok", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(inputs))


def test_traffic_wizard_saves_flat_object_keys(monkeypatch):
    cm = _fake_cm_for_wizard()
    _prepare_wizard_real_chain(
        monkeypatch,
        [
            "Flat Rule",             # name
            "3",                     # pd_sel -> Allowed
            "443",                   # port_in
            "",                      # proto_in -> default (both)
            "app=erp, app=web", "", "", "10.0.0.1",  # src: label/iplist/workload/ip
            "", "", "", "",          # dst: all empty
            "10",                    # win_in
            "5",                     # cnt_in
            "10",                    # cd_in
            "8080",                  # ex_port_in
            "", "", "", "",          # ex_src: all empty
            "", "", "", "",          # ex_dst: all empty
            "",                      # confirm
            "",                      # rule saved pause
        ],
    )

    settings_module.add_traffic_menu(cm)

    assert len(cm.config["rules"]) == 1
    rule = cm.config["rules"][-1]
    assert rule["src_labels"] == ["app=erp", "app=web"]
    assert rule["src_ip_in"] == ["10.0.0.1"]
    assert "src_label" not in rule
    assert "dst_label" not in rule
    assert "dst_labels" not in rule


def test_traffic_wizard_edit_legacy_rule_migrates_keys(monkeypatch):
    cm = _fake_cm_for_wizard()
    edit_rule = {
        "id": 42,
        "type": "traffic",
        "name": "Legacy Rule",
        "pd": -1,
        "port": 0,
        "src_label": "app=old",
        "src_ip_in": "1.2.3.4",
        "threshold_window": 10,
        "threshold_count": 5,
        "cooldown_minutes": 10,
        "ex_port": 0,
    }
    _prepare_wizard_real_chain(
        monkeypatch,
        [
            "",                      # name -> keep
            "",                      # pd_sel -> default
            "",                      # port_in -> default (0, falsy -> no proto prompt)
            "", "", "", "",          # src: all empty -> keep preselected
            "", "", "", "",          # dst: all empty
            "",                      # win_in -> default
            "",                      # cnt_in -> default
            "",                      # cd_in -> default
            "",                      # ex_port_in -> default
            "", "", "", "",          # ex_src: all empty
            "", "", "", "",          # ex_dst: all empty
            "",                      # confirm
            "",                      # rule saved pause
        ],
    )

    settings_module.add_traffic_menu(cm, edit_rule=edit_rule)

    assert len(cm.config["rules"]) == 1
    rule = cm.config["rules"][-1]
    assert rule["src_labels"] == ["app=old"]
    assert rule["src_ip_in"] == ["1.2.3.4"]
    assert "src_label" not in rule


def test_bandwidth_wizard_saves_flat_object_keys(monkeypatch):
    cm = _fake_cm_for_wizard()
    _prepare_wizard_real_chain(
        monkeypatch,
        [
            "BW Flat Rule",          # name
            "1",                     # m_sel -> bandwidth
            "443",                   # port_in
            "",                      # proto_in -> default (both)
            "app=erp, app=web", "", "", "10.0.0.1",  # src: label/iplist/workload/ip
            "", "", "", "",          # dst: all empty
            "100",                   # th_in
            "10",                    # win_in
            "10",                    # cd_in
            "8080",                  # ex_port_in
            "", "", "", "",          # ex_src: all empty
            "", "", "", "",          # ex_dst: all empty
            "",                      # confirm
            "",                      # rule saved pause
        ],
    )

    settings_module.add_bandwidth_volume_menu(cm)

    assert len(cm.config["rules"]) == 1
    rule = cm.config["rules"][-1]
    assert rule["src_labels"] == ["app=erp", "app=web"]
    assert rule["src_ip_in"] == ["10.0.0.1"]
    assert "src_label" not in rule
    assert "dst_label" not in rule
    assert "dst_labels" not in rule


def test_bandwidth_wizard_edit_legacy_rule_migrates_keys(monkeypatch):
    cm = _fake_cm_for_wizard()
    edit_rule = {
        "id": 7,
        "type": "bandwidth",
        "name": "Legacy BW Rule",
        "port": 0,
        "src_label": "app=old",
        "src_ip_in": "1.2.3.4",
        "threshold_count": 50.0,
        "threshold_window": 10,
        "cooldown_minutes": 10,
        "ex_port": 0,
    }
    _prepare_wizard_real_chain(
        monkeypatch,
        [
            "",                      # name -> keep
            "",                      # m_sel -> default (bandwidth)
            "",                      # port_in -> default (0, falsy -> no proto prompt)
            "", "", "", "",          # src: all empty -> keep preselected
            "", "", "", "",          # dst: all empty
            "",                      # th_in -> default
            "",                      # win_in -> default
            "",                      # cd_in -> default
            "",                      # ex_port_in -> default
            "", "", "", "",          # ex_src: all empty
            "", "", "", "",          # ex_dst: all empty
            "",                      # confirm
            "",                      # rule saved pause
        ],
    )

    settings_module.add_bandwidth_volume_menu(cm, edit_rule=edit_rule)

    assert len(cm.config["rules"]) == 1
    rule = cm.config["rules"][-1]
    assert rule["src_labels"] == ["app=old"]
    assert rule["src_ip_in"] == ["1.2.3.4"]
    assert "src_label" not in rule


# ─── Phase 5 final-review 修補：CLI 精靈編輯不得靜默丟棄 GUI 產的 any_*/ex_any_* ──
#
# GUI FilterBar 可產生 any_label/ex_any_workload 等 8 個 either-side filter key，
# CLI 精靈的 picker 無對應槽位可編輯，故編輯時應原樣保留這些 key（而非隨
# new_rule 從零重建而消失）。以下兩測試釘住 traffic/bandwidth 精靈：帶
# any_label/ex_any_workload 的 GUI 形規則、全空輸入空跑編輯後，兩 key 仍在
# 且值不變。


def test_traffic_wizard_preserves_any_filters_on_edit(monkeypatch):
    cm = _fake_cm_for_wizard()
    edit_rule = {
        "id": 99,
        "type": "traffic",
        "name": "GUI Rule",
        "pd": -1,
        "port": 0,
        "any_label": "app=erp",
        "ex_any_workload": "10.0.0.5",
        "threshold_window": 10,
        "threshold_count": 5,
        "cooldown_minutes": 10,
        "ex_port": 0,
    }
    _prepare_wizard_real_chain(
        monkeypatch,
        [
            "",                      # name -> keep
            "",                      # pd_sel -> default
            "",                      # port_in -> default (0, falsy -> no proto prompt)
            "", "", "", "",          # src: all empty -> keep preselected
            "", "", "", "",          # dst: all empty
            "",                      # win_in -> default
            "",                      # cnt_in -> default
            "",                      # cd_in -> default
            "",                      # ex_port_in -> default
            "", "", "", "",          # ex_src: all empty
            "", "", "", "",          # ex_dst: all empty
            "",                      # confirm
            "",                      # rule saved pause
        ],
    )

    settings_module.add_traffic_menu(cm, edit_rule=edit_rule)

    assert len(cm.config["rules"]) == 1
    rule = cm.config["rules"][-1]
    assert rule["any_label"] == "app=erp"
    assert rule["ex_any_workload"] == "10.0.0.5"


def test_bandwidth_wizard_preserves_any_filters_on_edit(monkeypatch):
    cm = _fake_cm_for_wizard()
    edit_rule = {
        "id": 100,
        "type": "bandwidth",
        "name": "GUI BW Rule",
        "port": 0,
        "any_label": "app=erp",
        "ex_any_workload": "10.0.0.5",
        "threshold_count": 50.0,
        "threshold_window": 10,
        "cooldown_minutes": 10,
        "ex_port": 0,
    }
    _prepare_wizard_real_chain(
        monkeypatch,
        [
            "",                      # name -> keep
            "",                      # m_sel -> default (bandwidth)
            "",                      # port_in -> default (0, falsy -> no proto prompt)
            "", "", "", "",          # src: all empty -> keep preselected
            "", "", "", "",          # dst: all empty
            "",                      # th_in -> default
            "",                      # win_in -> default
            "",                      # cd_in -> default
            "",                      # ex_port_in -> default
            "", "", "", "",          # ex_src: all empty
            "", "", "", "",          # ex_dst: all empty
            "",                      # confirm
            "",                      # rule saved pause
        ],
    )

    settings_module.add_bandwidth_volume_menu(cm, edit_rule=edit_rule)

    assert len(cm.config["rules"]) == 1
    rule = cm.config["rules"][-1]
    assert rule["any_label"] == "app=erp"
    assert rule["ex_any_workload"] == "10.0.0.5"


# ─── Task 2 review fix：TTY 下 pick_objects 遇 Ctrl-C 須優雅回選單、不存檔 ──
#
# 舊碼用 safe_input(allow_cancel=True) 時，KeyboardInterrupt 在 _render.py 內被接住
# 回 None，精靈原地 return。改用 pick_objects 後，其 TTY 路徑的
# questionary.*.unsafe_ask() 沒有本地 except，KeyboardInterrupt 會穿透精靈、
# manage_rules_menu，直達 main.py 頂層 handler，讓整個 CLI 應用結束。
# 以下測試釘住 TTY 路徑（monkeypatch _interactive_ok -> True）並讓
# questionary.select().unsafe_ask() 拋出 KeyboardInterrupt，驗證精靈優雅
# return（無新規則寫入 cm.config["rules"]），不再穿透。


def _prepare_wizard_tty_chain(monkeypatch, raw_inputs):
    inputs = iter(raw_inputs)
    monkeypatch.setattr("os.system", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.cli.menus.traffic.draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.cli.menus.bandwidth.draw_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.api_client.ApiClient", lambda _cm: object())
    # 這裡要走 pick_objects 的 TTY questionary 路徑（與非 TTY 降級路徑相反）
    monkeypatch.setattr("src.cli.object_picker._interactive_ok", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(inputs))


def test_traffic_wizard_ctrl_c_during_object_picking_returns_to_menu(monkeypatch):
    cm = _fake_cm_for_wizard()
    _prepare_wizard_tty_chain(
        monkeypatch,
        [
            "Flat Rule",  # name
            "3",          # pd_sel -> Allowed
            "443",        # port_in
            "",           # proto_in -> default (both)
        ],
    )

    with patch("questionary.select") as msel:
        msel.return_value.unsafe_ask.side_effect = KeyboardInterrupt
        settings_module.add_traffic_menu(cm)

    assert cm.config["rules"] == []


def test_bandwidth_wizard_ctrl_c_during_object_picking_returns_to_menu(monkeypatch):
    cm = _fake_cm_for_wizard()
    _prepare_wizard_tty_chain(
        monkeypatch,
        [
            "BW Flat Rule",  # name
            "1",             # m_sel -> bandwidth
            "443",           # port_in
            "",              # proto_in -> default (both)
        ],
    )

    with patch("questionary.select") as msel:
        msel.return_value.unsafe_ask.side_effect = KeyboardInterrupt
        settings_module.add_bandwidth_volume_menu(cm)

    assert cm.config["rules"] == []
