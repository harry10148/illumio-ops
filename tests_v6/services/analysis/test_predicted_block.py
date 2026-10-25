"""predict_blocks: a draft recompute (async query + update_rules) with the deny rules that block each flow."""
import json
from pathlib import Path

import pytest

from illumio_ops.domain.filter import EndpointFilter, FilterSpec
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.values import SegmentView
from illumio_ops.pce.async_query import AsyncQueryResult, PceQueryError
from illumio_ops.pce.policy import PolicyNames
from illumio_ops.services.analysis import predicted_block
from illumio_ops.services.analysis.predicted_block import predict_blocks
from illumio_ops.services.analysis.segments import run_segment
from illumio_ops.store.flowdb import capabilities
from tests_v6.services.collect.conftest import NOW, configured_ctx, minutes

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "pce"
ROWS = json.loads((FIX / "draft_rows.json").read_text())
RULE_SETS = json.loads((FIX / "rule_sets_draft.json").read_text())
TEDT_DENY = "/orgs/1/sec_policy/draft/rule_sets/673/deny_rules/309"
SPEC = FilterSpec(start=NOW - minutes(60), end=NOW)


@pytest.fixture
def fake(monkeypatch):
    calls = {"queries": [], "rule_sets": 0}

    def query(client, payload, *, deadline, compute_draft=False, delete_after=True):
        calls["queries"].append((payload, compute_draft))
        return AsyncQueryResult(rows=ROWS, matches_count=len(ROWS), flows_count=len(ROWS), capped=False)

    def rule_sets(client, pversion, *, deadline):
        calls["rule_sets"] += 1
        assert pversion == "draft"
        return [rs for rs in RULE_SETS if "673" not in rs["href"]] if calls.get("drop_tedt") else RULE_SETS

    monkeypatch.setattr(predicted_block, "run_traffic_query", query)
    monkeypatch.setattr(predicted_block, "fetch_rule_sets", rule_sets)
    monkeypatch.setattr(predicted_block, "fetch_policy_names",
                        lambda client, pversion, *, deadline: PolicyNames(labels={"/orgs/1/labels/21": ("env", "Server")},
                                                                          names={}))
    return calls


def test_predict_blocks_maps_deny_rule_names(tmp_path, fake):
    ctx = configured_ctx(tmp_path)
    r = predict_blocks(ctx, SPEC)
    assert fake["queries"][0][1] is True  # compute_draft: the recompute is asked for
    blocked = [row for row in r.rows if row.draft_decision == "blocked_by_boundary"]
    assert len(blocked) == 8 and all(row.blocking_rules == [TEDT_DENY] for row in blocked)
    assert r.rules[TEDT_DENY].ruleset_name == "tedt"
    assert [(a.key, a.value) for a in r.rules[TEDT_DENY].consumers] == [("env", "Server")]
    assert r.unsupported is False and r.missing_rules == [] and r.capped is False
    allowed = next(row for row in r.rows if row.draft_decision == "allowed")
    assert allowed.essential_service_rules and allowed.flow.src_ip.startswith("10.0.")


def test_update_rules_404_marks_unsupported(tmp_path, fake, monkeypatch):
    def no_draft(client, payload, *, deadline, compute_draft=False, delete_after=True):
        raise PceQueryError("update_rules", 404)
    monkeypatch.setattr(predicted_block, "run_traffic_query", no_draft)
    ctx = configured_ctx(tmp_path)
    r = predict_blocks(ctx, SPEC)
    assert r.unsupported is True and r.rows == []
    with ctx.flows().connect() as conn:
        assert capabilities.all(conn)["draft_recompute"].state == "unsupported"


def test_other_query_failure_propagates(tmp_path, fake, monkeypatch):
    def boom(client, payload, *, deadline, compute_draft=False, delete_after=True):
        raise PceQueryError("poll", 500)
    monkeypatch.setattr(predicted_block, "run_traffic_query", boom)
    with pytest.raises(PceQueryError):
        predict_blocks(configured_ctx(tmp_path), SPEC)


def test_residual_filter_applied_to_rows(tmp_path, fake):
    one_host = ROWS[0]["dst"]["ip"]
    r = predict_blocks(configured_ctx(tmp_path), SPEC.model_copy(update={"dst": EndpointFilter(ips=(one_host + "/32",))}))
    assert r.rows and {row.flow.dst_ip for row in r.rows} == {one_host}  # a CIDR is not pushed: applied here


def test_missing_rule_href_listed(tmp_path, fake):
    fake["drop_tedt"] = True
    r = predict_blocks(configured_ctx(tmp_path), SPEC)
    assert r.missing_rules == [TEDT_DENY] and TEDT_DENY not in r.rules


def test_predicted_block_segment_dispatch(tmp_path, fake):
    res = run_segment(configured_ctx(tmp_path), FlowSegment(filter=SPEC, view=SegmentView.PREDICTED_BLOCK, limit=5),
                      now=NOW)
    assert res.view is SegmentView.PREDICTED_BLOCK and len(res.predicted.rows) == 5 and res.limit_hit is True
