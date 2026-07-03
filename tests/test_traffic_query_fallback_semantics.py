"""client-side fallback 的同 key OR 語意（與 native 路徑對齊）。"""
from src.api.traffic_query import TrafficQueryBuilder


def _flow(src_labels=(), dst_labels=()):
    def side(labels):
        return {"workload": {"labels": [{"key": k, "value": v} for k, v in labels]}}
    return {"src": side(src_labels), "dst": side(dst_labels), "service": {}}


def _match(flow, filters):
    return TrafficQueryBuilder._flow_matches_filters(flow, filters)


def test_same_key_two_values_is_or():
    flow = _flow(src_labels=[("app", "erp")])
    assert _match(flow, {"src_labels": ["app=erp", "app=web"]}) is True


def test_same_key_no_value_matches_rejects():
    flow = _flow(src_labels=[("app", "hr")])
    assert _match(flow, {"src_labels": ["app=erp", "app=web"]}) is False


def test_cross_key_still_and():
    flow = _flow(src_labels=[("app", "erp")])  # 缺 env=prod
    assert _match(flow, {"src_labels": ["app=erp", "env=prod"]}) is False
    flow2 = _flow(src_labels=[("app", "erp"), ("env", "prod")])
    assert _match(flow2, {"src_labels": ["app=erp", "env=prod"]}) is True


def test_dst_side_same_semantics():
    flow = _flow(dst_labels=[("env", "prod")])
    assert _match(flow, {"dst_labels": ["env=prod", "env=dr"]}) is True


def test_unparseable_spec_must_match_individually():
    # 無 key 可解析的字串維持舊語意：該條件必須自行成立（AND）
    flow = _flow(src_labels=[("app", "erp")])
    assert _match(flow, {"src_labels": ["app=erp", "garbage"]}) is False
