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


def test_preselected_not_aliased(monkeypatch):
    # Finding 1：preselected 的內層 list 不得被就地修改（呼叫端物件與精靈取消後皆不受污染）
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    preselected = {"labels": ["app=old"]}
    with patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["app=erp"]
        out = op.pick_objects(_api(), cats=("label",), title="src", preselected=preselected)
    assert preselected == {"labels": ["app=old"]}  # 呼叫端原物件逐位不變
    assert out["labels"] == ["app=old", "app=erp"]
    assert out["labels"] is not preselected["labels"]  # 回傳 list 非同一物件


def test_empty_candidates_shows_no_candidates_message(monkeypatch, capsys):
    # Finding 2：候選載入成功但回 [] 時，不得誤報 offline，須顯示專屬的 no_candidates 訊息
    from src.cli import object_picker as op
    from src.i18n import t as i18n_t
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    api = _api()
    api.get_all_labels.return_value = []
    with patch("questionary.select") as msel, patch("questionary.text") as mtext:
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mtext.return_value.unsafe_ask.side_effect = ["env=dev"]
        op.pick_objects(api, cats=("label",), title="src")
    out = capsys.readouterr().out
    assert i18n_t("cli_pick_no_candidates", lang=None, cat="label") in out
    assert i18n_t("cli_pick_offline_hint", lang=None, cat="label") not in out


def test_label_key_filter_restricts_candidates_to_dimension(monkeypatch):
    # label_key_filter 僅過濾 label 候選 dimension（env-only），供 pce_cache_cli 的
    # workload_label_env 槽使用——候選只列 key == "env" 的 label。
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["env=prod"]
        out = op.pick_objects(_api(), cats=("label",), title="src", label_key_filter="env")
    choices = mauto.call_args.kwargs.get("choices") or mauto.call_args.args[1]
    assert choices == ["env=prod"]  # app=erp 已被 dimension 過濾掉
    assert out == {"labels": ["env=prod"]}


def test_label_key_filter_default_none_keeps_all_dimensions(monkeypatch):
    # 預設 None＝現行為，既有呼叫端（規則精靈等）不受影響
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["app=erp"]
        out = op.pick_objects(_api(), cats=("label",), title="src")
    choices = mauto.call_args.kwargs.get("choices") or mauto.call_args.args[1]
    assert set(choices) == {"app=erp", "env=prod"}
    assert out == {"labels": ["app=erp"]}


def test_label_key_filter_ignored_on_non_tty_path(monkeypatch):
    # 非 TTY 路徑不載入候選、不受 label_key_filter 影響——只驗證參數不炸、行為不變
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    inputs = iter(["env=prod, app=erp"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    out = op.pick_objects(_api(), cats=("label",), title="src", label_key_filter="env")
    assert out == {"labels": ["env=prod", "app=erp"]}


def test_tty_clear_category_option(monkeypatch):
    # Finding 3：類別選單在已有選值時附加「清空」選項，選了就整類移除
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    preselected = {"labels": ["app=old"]}
    with patch("questionary.select") as msel:
        msel.return_value.unsafe_ask.side_effect = [f"{op._CLEAR_PREFIX}label", "__done__"]
        out = op.pick_objects(_api(), cats=("label",), title="src", preselected=preselected)
    assert out == {}


# --- Task 12: service/port 類別 ---

def test_cat_order_has_service_and_port():
    from src.cli.object_picker import _CAT_ORDER
    assert "service" in _CAT_ORDER and "port" in _CAT_ORDER


def test_load_candidates_service():
    from src.cli.object_picker import _load_candidates
    api = MagicMock()
    api.get_services.return_value = [
        {"name": "Web", "href": "/s/1", "service_ports": [{"port": 80, "proto": 6}]}]
    cands = _load_candidates(api, "service")
    assert cands == [("Web (tcp/80)", "/s/1")]


def test_picked_to_service_filters():
    from src.cli.object_picker import picked_to_service_filters
    picked = {"services": ["/s/1"], "ports": ["443/tcp"]}
    assert picked_to_service_filters(picked) == {"services": ["/s/1"], "ports": ["443/tcp"]}
    assert picked_to_service_filters(picked, exclude=True) == {
        "ex_services": ["/s/1"], "ex_ports": ["443/tcp"]}


def test_legacy_service_to_preselected_scalar_port():
    from src.cli.object_picker import legacy_service_to_preselected
    rule = {"port": 443, "proto": 6}
    assert legacy_service_to_preselected(rule) == {"ports": ["443/tcp"]}
    assert legacy_service_to_preselected({"ex_port": 22}, exclude=True) == {"ports": ["22"]}
    assert legacy_service_to_preselected({"services": ["/s/1"], "ports": ["80"]}) == {
        "services": ["/s/1"], "ports": ["80"]}


def test_pick_service_via_questionary(monkeypatch):
    # service 類別走 TTY autocomplete，值為 href
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    api = _api()
    api.get_services.return_value = [
        {"name": "Web", "href": "/s/1", "service_ports": [{"port": 80, "proto": 6}]}]
    with patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        msel.return_value.unsafe_ask.side_effect = ["service", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["Web (tcp/80)"]
        out = op.pick_objects(api, cats=("service", "port"), title="t")
    assert out == {"services": ["/s/1"]}


def test_pick_port_manual_tty(monkeypatch):
    # port 類別走手動輸入（同 ip 類別），非法 token 被過濾
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel, patch("questionary.text") as mtext:
        msel.return_value.unsafe_ask.side_effect = ["port", "__done__"]
        mtext.return_value.unsafe_ask.side_effect = ["80, notaport, 443/tcp"]
        out = op.pick_objects(_api(), cats=("service", "port"), title="t")
    assert out == {"ports": ["80", "443/tcp"]}


def test_non_tty_port_validation(monkeypatch):
    # 非 TTY input() 降級路徑：非法 token 被過濾
    import src.cli.object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    inputs = iter(["80, notaport, 443/tcp", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    out = op.pick_objects(MagicMock(), cats=("port", "service"), title="t")
    assert out == {"ports": ["80", "443/tcp"]}
