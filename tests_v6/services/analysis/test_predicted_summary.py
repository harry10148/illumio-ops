"""predicted_summary: the draft recompute counted by destination app and blocking rule, without keeping every row
(P5b-2 Task 5: the readiness report)."""
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.services.analysis import predicted_block
from illumio_ops.services.analysis.predicted_block import predicted_summary
from tests_v6.services.analysis.test_predicted_block import SPEC, TEDT_DENY, fake  # noqa: F401  (fixture)
from tests_v6.services.collect.conftest import configured_ctx


def test_predicted_grouped_by_rule(tmp_path, fake):  # noqa: F811
    s = predicted_summary(configured_ctx(tmp_path), SPEC)
    by_rule = {}
    for g in s.groups:
        by_rule[g.rule_href] = by_rule.get(g.rule_href, 0) + g.flows
    # 8 flows are blocked; 3 of them go into managed hosts (what enforcement blocks; the others go to addresses)
    assert by_rule == {TEDT_DENY: 3} and s.blocked_flows == 3 and s.rules[TEDT_DENY].ruleset_name == "tedt"
    assert s.unsupported is False and s.capped is False


def test_predicted_summary_unsupported(tmp_path, fake, monkeypatch):  # noqa: F811
    def no_draft(client, payload, *, deadline, compute_draft=False, delete_after=True):
        raise PceQueryError("update_rules", 404)
    monkeypatch.setattr(predicted_block, "run_traffic_query", no_draft)
    s = predicted_summary(configured_ctx(tmp_path), SPEC)
    assert s.unsupported is True and s.groups == []
