"""Wording rules every report shares: no internal field names, no reference to the product's own history."""
import re

import pytest

from illumio_ops.domain.values import Language
from illumio_ops.i18n import dictionary
from illumio_ops.services.reports.common import rule_label


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
