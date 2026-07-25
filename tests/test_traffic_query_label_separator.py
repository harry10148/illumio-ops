"""Client-side label 比對的分隔符慣例：一律切在「先出現」的 ':' 或 '='。

殘項 R1：src/api/labels.py::_normalize_label_filter 與 df_filter._label_mask.split_spec
已採 min-index 慣例，但 TrafficQueryBuilder._flow_matches_filters 內的 _label_match
仍固定先試 ':'。值本身含 ':' 的 label（例如 Loc=TW:TPE）會被切成 key='Loc=TW'，
永遠對不上任何 workload label——報表/dashboard 的 client-side 殘餘比對靜默回空集合。

同時涵蓋 group_label_specs_by_key：它負責「同 key OR、跨 key AND」的分組，必須跟
_label_match 認出同一個 key，否則兩邊對同一條 spec 的維度判定會錯開。
"""
from __future__ import annotations

import unittest

from src.api.traffic_query import TrafficQueryBuilder, group_label_specs_by_key


def _flow_with_src_labels(labels):
    return {
        "src": {
            "ip": "10.0.0.1",
            "workload": {
                "href": "/orgs/1/workloads/w1",
                "name": "w1",
                "labels": [{"key": k, "value": v} for k, v in labels],
            },
        },
        "dst": {"ip": "10.9.9.9"},
        "service": {"port": 443, "proto": 6},
    }


class TestLabelMatchSeparatorIsFirstOccurring(unittest.TestCase):
    def test_value_containing_colon_still_matches(self):
        """迴歸：Loc=TW:TPE 先前被切成 key='Loc=TW'，永不命中。"""
        flow = _flow_with_src_labels([("Loc", "TW:TPE")])
        self.assertTrue(
            TrafficQueryBuilder._flow_matches_filters(flow, {"src_labels": ["Loc=TW:TPE"]}))

    def test_colon_form_with_colon_in_value_matches(self):
        flow = _flow_with_src_labels([("Loc", "TW:TPE")])
        self.assertTrue(
            TrafficQueryBuilder._flow_matches_filters(flow, {"src_labels": ["Loc:TW:TPE"]}))

    def test_value_containing_equals_uses_the_colon_that_came_first(self):
        flow = _flow_with_src_labels([("Role", "a=b")])
        self.assertTrue(
            TrafficQueryBuilder._flow_matches_filters(flow, {"src_labels": ["Role:a=b"]}))

    def test_plain_forms_still_match(self):
        flow = _flow_with_src_labels([("role", "web")])
        for spec in ("role=web", "role:web"):
            with self.subTest(spec=spec):
                self.assertTrue(
                    TrafficQueryBuilder._flow_matches_filters(flow, {"src_labels": [spec]}))

    def test_non_matching_value_is_still_rejected(self):
        """修法不得放寬比對：切對 key 之後值不同仍須不命中。"""
        flow = _flow_with_src_labels([("Loc", "TW:TPE")])
        self.assertFalse(
            TrafficQueryBuilder._flow_matches_filters(flow, {"src_labels": ["Loc=TW:KHH"]}))

    def test_spec_without_separator_never_matches(self):
        flow = _flow_with_src_labels([("Loc", "TW")])
        self.assertFalse(
            TrafficQueryBuilder._flow_matches_filters(flow, {"src_labels": ["nosep"]}))


class TestGroupingAgreesWithMatcherOnTheKey(unittest.TestCase):
    """分組器與比對器必須從同一條 spec 認出同一個維度 key。"""

    def _matcher_key(self, spec: str) -> str:
        text = str(spec)
        idx = min((i for i in (text.find(":"), text.find("=")) if i != -1), default=-1)
        return text[:idx].strip().lower() if idx != -1 else ""

    def test_same_key_for_mixed_separator_specs(self):
        for spec in ("Loc=TW:TPE", "Loc:TW:TPE", "Role:a=b", "role=web", "role:web"):
            with self.subTest(spec=spec):
                grouped = group_label_specs_by_key([spec])
                self.assertEqual(list(grouped), [self._matcher_key(spec)])

    def test_same_dimension_groups_together_as_or(self):
        """同維度的兩條 spec 要落在同一組（OR），任一命中即通過。"""
        grouped = group_label_specs_by_key(["Loc=TW:TPE", "Loc=TW:KHH"])
        self.assertEqual(list(grouped), ["loc"])
        flow = _flow_with_src_labels([("Loc", "TW:KHH")])
        self.assertTrue(TrafficQueryBuilder._flow_matches_filters(
            flow, {"src_labels": ["Loc=TW:TPE", "Loc=TW:KHH"]}))

    def test_different_dimensions_are_anded(self):
        flow = _flow_with_src_labels([("Loc", "TW:TPE")])
        self.assertFalse(TrafficQueryBuilder._flow_matches_filters(
            flow, {"src_labels": ["Loc=TW:TPE", "role=web"]}))


if __name__ == "__main__":
    unittest.main()
