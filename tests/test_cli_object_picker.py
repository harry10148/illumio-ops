"""測試：CLI 物件選擇器 pick_objects（questionary 兩段式 + TTY/非TTY降級）。"""
from unittest.mock import MagicMock, patch


def _api():
    api = MagicMock()
    api.get_all_labels.return_value = [
        {"key": "app", "value": "erp", "href": "/orgs/1/labels/1"},
        {"key": "env", "value": "prod", "href": "/orgs/1/labels/2"},
    ]
    api.get_ip_lists.return_value = [{"name": "corp-vpn", "href": "/orgs/1/sec_policy/active/ip_lists/7"}]
    api.get_label_groups.return_value = [{"name": "PG-Prod", "href": "/orgs/1/sec_policy/active/label_groups/3"}]
    api.search_workloads.return_value = [{"name": "web01", "hostname": "web01.corp", "href": "/orgs/1/workloads/abc"}]
    return api


def test_pick_labels_via_questionary(monkeypatch):
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        # 第一輪選 Labels 類別、autocomplete 選 app=erp；第二輪選「完成」
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["app=erp"]
        out = op.pick_objects(_api(), cats=("label", "iplist", "workload", "ip"), title="src")
    assert out == {"labels": ["app=erp"]}


def test_pick_iplist_returns_href(monkeypatch):
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        msel.return_value.unsafe_ask.side_effect = ["iplist", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["corp-vpn"]
        out = op.pick_objects(_api(), cats=("label", "iplist"), title="src")
    assert out == {"iplists": ["/orgs/1/sec_policy/active/ip_lists/7"]}


def test_cats_excludes_label_group(monkeypatch):
    # 規則情境：cats 不含 label_group → 類別選單不得出現該項
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel:
        msel.return_value.unsafe_ask.side_effect = ["__done__"]
        op.pick_objects(_api(), cats=("label", "iplist", "workload", "ip"), title="src")
        choices = msel.call_args.kwargs.get("choices") or msel.call_args.args[1]
        assert not any("label_group" == getattr(c, "value", c) for c in choices)


def test_offline_falls_back_to_manual(monkeypatch):
    # 候選載入丟例外 → 該類別降級手動輸入（questionary.text），仍可完成
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    api = _api()
    api.get_all_labels.side_effect = Exception("pce down")
    with patch("questionary.select") as msel, patch("questionary.text") as mtext:
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mtext.return_value.unsafe_ask.side_effect = ["env=dev"]
        out = op.pick_objects(api, cats=("label",), title="src")
    assert out == {"labels": ["env=dev"]}


def test_non_tty_manual_path(monkeypatch):
    # 非 TTY：逐類別 input() comma 拆 list，跳過 questionary
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    inputs = iter(["app=erp, env=prod", "", "", "10.0.0.0/24"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    out = op.pick_objects(_api(), cats=("label", "iplist", "workload", "ip"), title="src")
    assert out == {"labels": ["app=erp", "env=prod"], "ips": ["10.0.0.0/24"]}


def test_invalid_cidr_rejected(monkeypatch):
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    inputs = iter(["", "999.1.1.1, 10.0.0.1"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    out = op.pick_objects(_api(), cats=("label", "ip"), title="src")
    assert out == {"ips": ["10.0.0.1"]}


def test_preselected_backfill(monkeypatch):
    # 編輯回填：preselected 直接帶入結果（非 TTY 空輸入=保留）
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    out = op.pick_objects(_api(), cats=("label", "ip"), title="src",
                          preselected={"labels": ["app=old"], "ips": ["1.2.3.4"]})
    assert out == {"labels": ["app=old"], "ips": ["1.2.3.4"]}
