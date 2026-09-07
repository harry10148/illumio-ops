"""規則的 `pd` 值只有一種語意：PCE 的 policy_decision 序數。

`Analyzer.check_flow_match` 是這個語意的**定義處**——它從 flow 自己的
`policy_decision` 字串推導出 flow 的 pd，再跟規則的 pd 比對。所有寫入或顯示
規則 pd 的地方（CLI 精靈、CLI 規則清單、GUI 抽屜、dashboard 查詢）都必須用
同一套數字，否則規則會靜默地監看另一種流量。

這個檔案的斷言全部對準**目的**：「操作者在選單挑了寫著 X 的那一項，規則就
要命中 X 那種流量」。把 `pd_sel == 2 → target_pd == 1` 這種對照表再抄一次不
算守門——那只是把同一張表寫兩遍，表本身錯了照樣綠。

成因：2026-09-08 追查「traffic 規則永遠不觸發」時發現 CLI 精靈把
Potentially Blocked 存成 0（引擎讀作 allowed）、Allowed 存成 1（引擎讀作
potentially_blocked）。CLI 的顯示端跟著同一套錯誤慣例，所以從 CLI 進、從
CLI 看，謊言前後一致，沒有人會發現。
"""
from unittest.mock import MagicMock

import pytest

from src.analyzer import Analyzer, PD_DECISION
from src.cli.menus.traffic import PD_MENU_CHOICES, pd_for_menu_choice, menu_choice_for_pd
from src.cli.menus.manage_rules import PD_RULE_LABEL_KEYS

# 選單項目編號 → 那一項的字面寫著哪一種 policy_decision。
# 「全部」不對應單一 decision，另外測。
_MENU_ITEM_DECISION = {1: "blocked", 2: "potentially_blocked", 3: "allowed"}
_ALL_DECISIONS = ("blocked", "potentially_blocked", "allowed")


@pytest.fixture
def analyzer():
    api = MagicMock()
    api.last_fetch_error = None
    return Analyzer(MagicMock(), api, MagicMock())


def _flow(decision):
    return {"timestamp": "2026-09-08T00:00:00Z", "policy_decision": decision}


@pytest.mark.parametrize("menu_item, decision", sorted(_MENU_ITEM_DECISION.items()))
def test_a_rule_authored_from_the_menu_matches_the_traffic_that_item_names(
        analyzer, menu_item, decision):
    """選單第 N 項寫著哪一種流量，存出來的規則就只能命中那一種。"""
    rule = {"type": "traffic", "pd": pd_for_menu_choice(menu_item)}
    for candidate in _ALL_DECISIONS:
        matched = analyzer.check_flow_match(rule, _flow(candidate), None)
        assert matched is (candidate == decision), (
            f"選單第 {menu_item} 項（{decision}）存成 pd="
            f"{pd_for_menu_choice(menu_item)}，卻對 {candidate} 的流量回傳 "
            f"{matched}")


def test_the_all_menu_item_matches_every_decision(analyzer):
    rule = {"type": "traffic", "pd": pd_for_menu_choice(4)}
    for candidate in _ALL_DECISIONS:
        assert analyzer.check_flow_match(rule, _flow(candidate), None), candidate


def test_the_menu_round_trips_so_editing_a_rule_preselects_what_was_chosen():
    """編輯既有規則時，反向對照必須把同一項標成預設值。"""
    for item, _key, _pd in PD_MENU_CHOICES:
        assert menu_choice_for_pd(pd_for_menu_choice(item)) == item


def test_the_rule_list_labels_a_pd_value_with_the_traffic_it_actually_matches(analyzer):
    """CLI 規則清單顯示的判定名稱，必須是規則真正會命中的那一種流量。

    顯示端跟著寫入端一起錯過一次（2026-07-24 的修復把清單對齊了有 bug 的
    精靈，而不是對齊引擎），所以這條不比對 CLI 內部的對照表，而是回頭問
    引擎。"""
    label_key_for_decision = {
        "blocked": "pd_label_blocked",
        "potentially_blocked": "pd_label_potential",
        "allowed": "pd_label_allowed",
    }
    for pd_val, label_key in PD_RULE_LABEL_KEYS.items():
        if pd_val == -1:
            assert label_key == "pd_label_all"
            continue
        rule = {"type": "traffic", "pd": pd_val}
        matched = [d for d in _ALL_DECISIONS
                   if analyzer.check_flow_match(rule, _flow(d), None)]
        assert len(matched) == 1, f"pd={pd_val} 命中了 {matched}"
        assert label_key == label_key_for_decision[matched[0]], (
            f"清單把 pd={pd_val} 顯示成 {label_key}，但引擎拿它去比對的是 "
            f"{matched[0]}")


@pytest.mark.parametrize("pd_val, decision", sorted(PD_DECISION.items()))
def test_the_named_ordinal_table_agrees_with_what_the_engine_matches(
        analyzer, pd_val, decision):
    """`PD_DECISION` 是給人看的那份慣例；它必須跟引擎的實際行為一致，
    否則它就只是一段會說謊的註解。"""
    rule = {"type": "traffic", "pd": pd_val}
    for candidate in _ALL_DECISIONS:
        assert analyzer.check_flow_match(rule, _flow(candidate), None) is (
            candidate == decision)
