"""policy_diff report (P5c-3): what provisioning the Draft would change, risky changes first, who changed what."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.policy_diff import Change
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.pce.policy import PendingItem
from illumio_ops.services.analysis.policy_diff import Attribution, PolicyDiff
from illumio_ops.services.reports import policy_diff as report
from illumio_ops.services.reports.registry import (
    BuildInput,
    ReportFailed,
    ReportParams,
    specs,
)
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 30, 1, tzinfo=UTC)
START, END = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC)
D = "/orgs/1/sec_policy/draft"
CHANGES = [
    Change(kind="rule_set", change="modified", ruleset="Quarantine", name="Quarantine", ref="100",
           href=f"{D}/rule_sets/100", field="enabled", draft="False", active="True", risk="high"),
    Change(kind="rule_set", change="added", ruleset="tedt", name="tedt", ref="673", href=f"{D}/rule_sets/673",
           field="*", draft="tedt", active="", rule_count=2),
    Change(kind="rule", change="added", ruleset="Web", name="#9", ref="deny_rules/9",
           href=f"{D}/rule_sets/1/deny_rules/9", field="*", draft="deny", active="", rule_type="deny"),
    Change(kind="ip_list", change="modified", ruleset="", name="Branch", ref="4", href=f"{D}/ip_lists/4",
           field="ip_ranges", draft="10.0.0.0/8", active="10.1.0.0/16", scope_expanded=True, risk="high"),
]


def _diff(**kw):
    base = {"changes": CHANGES, "pending": [], "attribution": {
        f"{D}/rule_sets/100": Attribution(actor="admin@lab", at=datetime(2026, 10, 27, 8, tzinfo=UTC),
                                          event_type="rule_set.update")},
        "other_pending": [PendingItem(kind="firewall_settings", href=f"{D}/firewall_settings", name=None,
                                      update_type="update", updated_at=None)],
        "attribution_limited": False, "computed_at": NOW}
    return PolicyDiff(**{**base, **kw})


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "policy_diff", lambda ctx, **kw: _diff())
    return configured_ctx(tmp_path)


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.POLICY_DIFF].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.POLICY_DIFF), start=START, end=END, lang=lang, tz=UTC,
        now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid):
    return next(b for b in _section(doc, sid).blocks if isinstance(b, TableBlock))


def test_how_to_read_first(ctx):
    assert _build(ctx).sections[0].id == "how"


def test_sections_and_kpis(ctx):
    doc = _build(ctx)
    k = {x.key: x.value for x in doc.kpis}
    assert (k["total"], k["high"], k["rule_sets"], k["rules"], k["objects"], k["other_pending"]) == (4, 2, 2, 1, 1, 1)
    risky = _table(doc, "risk")
    assert len(risky.rows) == 2 and any("admin@lab" in str(c) for c in risky.rows[0])
    assert _table(doc, "rule_sets").rows and _table(doc, "rules").rows and _table(doc, "objects").rows
    assert _table(doc, "other").rows[0][0] == "firewall_settings"
    assert any("Quarantine" in f.title for f in doc.findings)


def test_enabled_values_in_words(ctx):
    row = _table(_build(ctx), "rule_sets").rows
    assert any("Off" in str(c) for r in row for c in r) and not any(c == "False" for r in row for c in r)


def test_added_ruleset_shows_rule_count(ctx):
    rows = _table(_build(ctx), "rule_sets").rows
    assert any("2" in str(c) for r in rows if "tedt" in r for c in r)


def test_no_changes_says_same(ctx, monkeypatch):
    monkeypatch.setattr(report, "policy_diff", lambda ctx, **kw: _diff(changes=[], other_pending=[], attribution={}))
    doc = _build(ctx)
    text = " ".join(p for b in _section(doc, "how").blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert "same as the active policy" in text


def test_fetch_failure_fails_report(ctx, monkeypatch):
    def boom(ctx, **kw):
        raise PceCollectionIncomplete("/sec_policy/active/rule_sets", 0, "HTTP 500")
    monkeypatch.setattr(report, "policy_diff", boom)
    with pytest.raises(ReportFailed) as e:
        _build(ctx)
    assert e.value.key == "rpt_pdf_err_read"


def test_attribution_limited_disclosed(ctx, monkeypatch):
    monkeypatch.setattr(report, "policy_diff", lambda ctx, **kw: _diff(attribution_limited=True))
    assert any("1,000" in q for q in _build(ctx).data_quality)


def test_zh_tw_builds(ctx):
    assert _build(ctx, lang=Language.ZH_TW).title
