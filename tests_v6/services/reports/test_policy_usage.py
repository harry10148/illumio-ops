"""policy_usage (P5c-1): which rules the period's traffic used and which it did not, from the PCE's draft
recompute; says whether the draft is the active policy (pending changes)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.policy import index_rules
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.policy import PendingItem
from illumio_ops.services.analysis.rule_usage import NoRuleGroup, RuleHits, RuleUsage
from illumio_ops.services.reports import policy_usage
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from tests_v6.services.analysis.test_rule_usage import ALLOW, DENY, IDLE, RULE_SETS
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 28, 1, tzinfo=UTC)
START, END = datetime(2026, 10, 21, tzinfo=UTC), datetime(2026, 10, 28, tzinfo=UTC)
OFF = "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/12"
SETS = [{**RULE_SETS[0], "rules": [*RULE_SETS[0]["rules"],
                                   {"href": OFF, "enabled": False, "consumers": [], "providers": [],
                                    "ingress_services": []}]}, RULE_SETS[1]]


def usage(**kw):
    base = {"rules": index_rules(SETS), "hits": {ALLOW: RuleHits(flows=2, connections=7, top_pairs=[("Web", "DB", 7)]),
                                                 DENY: RuleHits(flows=1, connections=2, top_pairs=[])},
            "no_rule": [NoRuleGroup(src_app="Batch", dst_app="DB", port=1433, proto=6, connections=5)],
            "no_rule_total": 1, "no_rule_connections": 9, "windows": 7, "truncated": [], "unsupported": False, "pending": [], "computed_at": NOW}
    return RuleUsage(**{**base, **kw})


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(policy_usage, "rule_usage", lambda ctx, **kw: usage())
    return configured_ctx(tmp_path)


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.POLICY_USAGE].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.POLICY_USAGE), start=START, end=END, lang=lang, tz=UTC,
        now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid, i=0):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)][i]


def _text(doc, sid):
    return " ".join(p for b in _section(doc, sid).blocks if isinstance(b, TextBlock) for p in b.paragraphs)


def test_how_to_read_first(ctx):
    doc = _build(ctx)
    assert doc.sections[0].id == "how" and "Rule Hit Count" in doc.sections[0].intro


def test_sections_and_kpis(ctx):
    doc = _build(ctx)
    k = {x.key: x.value for x in doc.kpis}
    assert (k["rules"], k["used"], k["unused"], k["disabled"], k["deny_hit"], k["no_rule"]) == (3, 1, 1, 1, 1, 9)
    used = _table(doc, "used")
    assert used.rows[0][0] == "Web" and used.rows[0][3:5] == (2, 7) and "Web → DB" in used.rows[0][5]
    assert [r[0] for r in _table(doc, "unused").rows] == ["Web"] and IDLE.rsplit("/", 1)[-1] in _table(doc, "unused").rows[0][1]
    assert _table(doc, "deny").rows[0][0] == "Guard"
    assert _table(doc, "no_rule").rows[0][:2] == ("Batch", "DB")


def test_no_pending_equals_active(ctx):
    assert "same as the active policy" in _text(_build(ctx), "pending")


def test_pending_changes_said(ctx, monkeypatch):
    item = PendingItem(kind="rule_sets", href="/orgs/1/sec_policy/draft/rule_sets/663", name="G_Deny",
                       update_type="create", updated_at="2026-08-04T02:19:25.504Z")
    monkeypatch.setattr(policy_usage, "rule_usage", lambda ctx, **kw: usage(pending=[item]))
    doc = _build(ctx)
    assert "differs from the active policy" in _text(doc, "pending") and _table(doc, "pending").rows[0][1] == "G_Deny"
    assert any("provision" in f.title.lower() for f in doc.findings)


def test_unused_hedged_when_capped(ctx, monkeypatch):
    monkeypatch.setattr(policy_usage, "rule_usage", lambda ctx, **kw: usage(truncated=[(START, END)]))
    doc = _build(ctx)
    assert _table(doc, "unused").limit_note and "read" in _table(doc, "unused").limit_note


def test_disabled_rules_listed_apart(ctx):
    doc = _build(ctx)
    assert OFF.rsplit("/", 1)[-1] in _table(doc, "disabled").rows[0][1]
    assert all(OFF.rsplit("/", 1)[-1] not in r[1] for r in _table(doc, "unused").rows)


def test_unsupported_says_so(ctx, monkeypatch):
    monkeypatch.setattr(policy_usage, "rule_usage", lambda ctx, **kw: usage(unsupported=True, hits={}, no_rule=[]))
    doc = _build(ctx)
    assert "does not recompute" in _text(doc, "used")
    assert {x.key: x.value for x in doc.kpis}["used"] is None


def test_failure_report_still_built(ctx, monkeypatch):
    def boom(ctx, **kw):
        raise PceQueryError("poll", 500)
    monkeypatch.setattr(policy_usage, "rule_usage", boom)
    doc = _build(ctx)
    assert "could not" in _text(doc, "used").lower() and {x.key: x.value for x in doc.kpis}["rules"] is None


def test_zh_tw_builds(ctx):
    assert _build(ctx, lang=Language.ZH_TW).title
