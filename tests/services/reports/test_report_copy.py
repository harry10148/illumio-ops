"""Wording rules every report shares: no internal field names, no reference to the product's own history."""
import re

import pytest

from illumio_ops.domain.report import HTML_ROW_CAP
from illumio_ops.domain.values import Language
from illumio_ops.i18n import dictionary
from illumio_ops.services.reports.common import (
    host_key,
    host_keys,
    mode_word,
    rule_label,
)


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
def test_report_text_names_no_internal_field_and_no_earlier_version(lang):
    # 2026-11-10 report review: "沿用自 5.x" and "num_connections" reached the reader.
    bad = {k: v for k, v in dictionary(lang).items()
           if k.startswith("rpt_") and re.search(r"5\.x|num_connections", v)}
    assert bad == {}


def test_rule_without_a_description_is_named_as_a_rule_not_a_bare_number():
    # "tedt: 309" read as an unexplained code; the number is the rule's id on the PCE.
    assert rule_label(Language.EN, "tedt", "web to db", "/orgs/1/sec_policy/draft/rule_sets/3/sec_rules/309") == "tedt: web to db"
    assert rule_label(Language.EN, "tedt", None, "/orgs/1/sec_policy/draft/rule_sets/3/sec_rules/309") == "tedt: rule 309 (no description)"
    assert rule_label(Language.ZH_TW, "tedt", None, "/orgs/1/sec_policy/draft/rule_sets/3/sec_rules/309") == "tedt：規則 309（未填說明）"


def test_the_lateral_actions_use_the_report_s_own_words():
    # The report's title and numbers say 樞紐 (pivot), and blocking between environments is one thing to do
    # wherever it is said (rpt_action_cross_env).
    zh, en = dictionary(Language.ZH_TW), dictionary(Language.EN)
    assert zh["rpt_act_lat_pivot_host"] == "收斂樞紐主機的管理 port 連線。" and "樞紐" in zh["rpt_lat_kpi_pivots"]
    assert "pivot hosts" in en["rpt_act_lat_pivot_host"] and en["rpt_lat_kpi_pivots"] == "Pivot hosts"
    assert zh["rpt_act_lat_cross_env"] == "除非有明確需求，擋下跨環境的管理 port 連線。"
    assert en["rpt_act_lat_cross_env"] == "Block management-port connections between environments unless there is a documented need."


DECISION_TERMS = {
    "term_decision_allowed": ("有規則允許（Allowed）", "Allowed (a rule allows it)"),
    "term_decision_potentially_blocked": ("開始擋之後會被擋（Potentially Blocked）",
                                          "Potentially Blocked (blocked once enforcement starts)"),
    "term_decision_blocked": ("已被擋下（Blocked）", "Blocked"),
}
# Where a decision is a name (a number's name, a chapter, a table, a state): plain words with the PCE's own in
# brackets, in both languages. A sentence keeps the PCE's word as it is.
DECISION_NAMES = {
    "rpt_sec_kpi_allowed_pct": "Allowed", "rpt_sec_kpi_pb_flows": "Potentially Blocked",
    "rpt_sec_kpi_blocked_flows": "Blocked", "rpt_sec_sec_pb": "Potentially Blocked",
    "rpt_sec_tbl_pb": "Potentially Blocked", "wb_pred_pb_by_boundary": "Potentially Blocked",
    "wb_pred_pb_by_override_deny": "Potentially Blocked", "wb_pred_blocked_by_boundary": "Blocked",
    "wb_pred_blocked_by_override_deny": "Blocked", "wb_pred_allowed_across_boundary": "Allowed",
    **{key: pce for key, pce in zip(DECISION_TERMS, ("Allowed", "Potentially Blocked", "Blocked"), strict=True)},
}


def test_a_decision_is_named_in_plain_words_with_the_pce_word_beside():
    zh, en = dictionary(Language.ZH_TW), dictionary(Language.EN)
    assert {k: (zh[k], en[k]) for k in DECISION_TERMS} == DECISION_TERMS
    assert zh["rpt_sec_kpi_pb_flows"] == "開始擋之後會被擋的流量（Potentially Blocked）"
    for key, pce in DECISION_NAMES.items():
        assert f"（{pce}" in zh[key] and zh[key] != pce, key  # the PCE's word in brackets, after the plain words
        assert pce in en[key], key
    assert zh["decision_unknown"] == en["decision_unknown"] == "Unknown"  # stage 3b's


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
def test_no_page_keeps_its_own_word_for_a_decision_or_a_mode(lang):
    gone = [k for k in dictionary(lang) if k.startswith("rpt_col_mode_")
            or k in ("lat_state_allowed", "lat_state_potentially_blocked")]
    assert gone == []


def test_a_mode_is_said_in_plain_words_with_the_pce_word_beside():
    said = {(lang, mode): mode_word(lang, mode) for lang in Language
            for mode in ("idle", "visibility_only", "selective", "full")}
    assert said == {
        (Language.EN, "idle"): "Not blocking yet (Idle)",
        (Language.EN, "visibility_only"): "Recording only (Visibility Only)",
        (Language.EN, "selective"): "Blocking some (Selective)",
        (Language.EN, "full"): "Blocking everything (Full)",
        (Language.ZH_TW, "idle"): "還沒開始擋（Idle）",
        (Language.ZH_TW, "visibility_only"): "只記錄、不擋（Visibility Only）",
        (Language.ZH_TW, "selective"): "只擋部分（Selective）",
        (Language.ZH_TW, "full"): "全部都擋（Full）",
    }
    assert mode_word(Language.EN, "something_new") == "something_new"  # a mode this table does not know: as it is


def test_host_keys_are_held_for_the_rows_the_html_prints():
    keys = [f"/orgs/1/workloads/{i}" for i in range(HTML_ROW_CAP + 5)]
    got = host_keys(src=keys, dst=iter(["ip:10.0.0.1", None]))
    assert got == {"src": tuple(keys[:HTML_ROW_CAP]), "dst": ("ip:10.0.0.1", None)}


def test_a_key_that_is_not_a_host_is_no_host_key():
    hosts = {"/orgs/1/kubernetes_workloads/k": object()}
    assert host_key(hosts, "/orgs/1/workloads/a") == "/orgs/1/workloads/a" and host_key(hosts, "ip:10.0.0.1") == "ip:10.0.0.1"
    assert host_key(hosts, "/orgs/1/kubernetes_workloads/k") == "/orgs/1/kubernetes_workloads/k"
    assert host_key(hosts, "svc-backup") is None and host_key(hosts, "") is None and host_key(hosts, None) is None
