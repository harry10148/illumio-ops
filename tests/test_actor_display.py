"""actor 顯示解析（spec F1）：ams 顯示 All Workloads、未知形狀不印 raw dict。"""
from src.api.labels import LabelResolver
from src.report.analysis.policy_usage.pu_mod02_hit_detail import _resolve_actors


class _FakeClient:
    label_cache = {"/orgs/1/labels/7": "app:web", "/orgs/1/ip_lists/3": "PCI-scope"}


def test_ams_renders_all_workloads_via_labels_layer():
    resolver = LabelResolver(_FakeClient())

    assert resolver.resolve_actor_str([{"actors": "ams"}]) == "All Workloads"
    assert resolver.resolve_actor_str([{"label": {"href": "/orgs/1/labels/7"}}]) == "app:web"

    out = resolver.resolve_actor_str([{"label_group": {"href": "/x/label_groups/9"}}])
    assert "{'" not in out and '{"' not in out
    assert out == "LabelGroup"


def test_unknown_actor_shape_uses_readable_ref_not_raw_dict():
    resolver = LabelResolver(_FakeClient())

    out = resolver.resolve_actor_str([{"mystery": {"href": "/orgs/1/mystery/5"}}])
    assert "{'" not in out and '{"' not in out
    assert out == "mystery:5"

    out_no_href = resolver.resolve_actor_str([{"mystery": "no-href-here"}])
    assert "{'" not in out_no_href and '{"' not in out_no_href
    assert out_no_href == "mystery"


def test_fallback_no_raw_dict():
    out = _resolve_actors(
        [
            {"ip_list": {"href": "/orgs/1/ip_lists/3"}},
            {"actors": "ams"},
            {"mystery": {"href": "/orgs/1/mystery/5"}},
        ],
        api_client=None,
    )
    assert "{'" not in out and '{"' not in out  # 絕不印 raw dict
    assert "All Workloads" in out
    assert "PCI-scope" in out or "ip_lists/3" in out or "ip_list:3" in out
