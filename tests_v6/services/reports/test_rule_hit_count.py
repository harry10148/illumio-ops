"""rule_hit_count (P5c-2): the PCE's own count of provisioned rules' hits. Greyed out until Rule Hit Count is on; a
scheduled run finds it off → fails with the reason; zero hits and no record are apart; Draft rules point to
policy_usage."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportStatus, ReportType, RhcState
from illumio_ops.pce.policy import PendingItem, PolicyNames
from illumio_ops.services import rhc
from illumio_ops.services.reports import generate, rule_hit_count
from illumio_ops.services.reports.registry import (
    BuildInput,
    ReportFailed,
    ReportParams,
    specs,
)
from illumio_ops.services.rhc import RhcPull, RhcPullError, RhcRow, RhcStatus
from illumio_ops.store import reports as store
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 30, 1, tzinfo=UTC)
START, END = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC)
A = "/orgs/1/sec_policy/active/rule_sets/1"
RULE_SETS = [{"href": A, "name": "Web", "rules": [
    {"href": f"{A}/sec_rules/10", "enabled": True, "consumers": [], "providers": [], "ingress_services": []},
    {"href": f"{A}/sec_rules/11", "enabled": True, "consumers": [], "providers": [], "ingress_services": []},
    {"href": f"{A}/sec_rules/12", "enabled": True, "consumers": [], "providers": [], "ingress_services": []},
    {"href": f"{A}/sec_rules/13", "enabled": False, "consumers": [], "providers": [], "ingress_services": []}],
    "deny_rules": []}]


def _status(state=RhcState.ENABLED, reason=None):
    return RhcStatus(state=state, pce_report=state is RhcState.ENABLED, ven_scopes=state is RhcState.ENABLED,
                     reason_key=reason, detail=None, write_key=True, saas=False)


def _pull(rows=None, unparsed=0):
    rows = rows if rows is not None else [
        RhcRow(rule_href=f"{A}/sec_rules/10", ruleset_name="Web", description="", hit_count=42,
               last_hit_at="2026-10-29T10:00:00Z"),
        RhcRow(rule_href=f"{A}/sec_rules/11", ruleset_name="Web", description="", hit_count=0, last_hit_at=None)]
    return RhcPull(rows=rows, start=START, end=END, unparsed=unparsed)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(rule_hit_count, "rhc_status", lambda ctx: _status())
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull())
    monkeypatch.setattr(rule_hit_count, "fetch_rule_sets", lambda client, pversion, *, deadline: RULE_SETS)
    monkeypatch.setattr(rule_hit_count, "fetch_policy_names",
                        lambda client, pversion, *, deadline: PolicyNames(labels={}, names={}))
    monkeypatch.setattr(rule_hit_count, "fetch_pending", lambda client, *, deadline: [])
    return configured_ctx(tmp_path)


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.RULE_HIT_COUNT].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.RULE_HIT_COUNT), start=START, end=END, lang=lang, tz=UTC,
        now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _table(doc, sid):
    return next(b for b in _section(doc, sid).blocks if isinstance(b, TableBlock))


def _ids(table):
    return [r[1].split()[0] for r in table.rows]


def test_how_to_read_first(ctx):
    doc = _build(ctx)
    assert doc.sections[0].id == "how" and "policy_usage" not in doc.sections[0].intro  # named in words, not ids


def test_zero_vs_no_record(ctx):
    """Provisioned and 0 hits in the period ≠ no record (provisioned later, or a Draft rule): never shown as 0."""
    doc = _build(ctx)
    assert _ids(_table(doc, "hit")) == ["#10"] and _table(doc, "hit").rows[0][3] == 42
    assert _ids(_table(doc, "zero")) == ["#11"]
    assert _ids(_table(doc, "no_record")) == ["#12"]  # the disabled #13 is not expected to have a record
    k = {x.key: x.value for x in doc.kpis}
    assert (k["rules"], k["hit"], k["zero"], k["no_record"]) == (3, 1, 1, 1)


def test_pending_points_to_policy_usage(ctx, monkeypatch):
    item = PendingItem(kind="rule_sets", href="/orgs/1/sec_policy/draft/rule_sets/7", name="New",
                       update_type="create", updated_at="2026-10-29T00:00:00Z")
    monkeypatch.setattr(rule_hit_count, "fetch_pending", lambda client, *, deadline: [item])
    doc = _build(ctx)
    text = " ".join(p for b in _section(doc, "pending").blocks if isinstance(b, TextBlock) for p in b.paragraphs)
    assert "Policy usage" in text and _table(doc, "pending").rows[0][1] == "New"


def test_unparsed_rows_disclosed(ctx, monkeypatch):
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull(unparsed=3))
    assert any("3" in q for q in _build(ctx).data_quality)


def test_rule_not_in_active_policy_still_listed(ctx, monkeypatch):
    """A rule deleted since keeps its hits under the ruleset name the PCE gave."""
    gone = RhcRow(rule_href=f"{A}/sec_rules/99", ruleset_name="Old", description="", hit_count=5, last_hit_at=None)
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull(rows=[*_pull().rows, gone]))
    rows = _table(_build(ctx), "hit").rows
    assert [r[0] for r in rows] == ["Web", "Old"]


def test_not_enabled_fails_build(ctx, monkeypatch):
    """Checked again when the report runs: a schedule never produces an empty report."""
    monkeypatch.setattr(rule_hit_count, "rhc_status",
                        lambda ctx: _status(RhcState.PARTIAL, "rhc_reason_partial_ven"))
    with pytest.raises(ReportFailed) as e:
        _build(ctx)
    assert e.value.key == "rpt_unavailable_rhc_off"


def test_pull_failure_fails_report(ctx, monkeypatch):
    def refuse(ctx, start, end):
        raise RhcPullError("rhc_err_pull_refused", "HTTP 403")
    monkeypatch.setattr(rule_hit_count, "pull_rhc", refuse)
    with pytest.raises(ReportFailed) as e:
        _build(ctx)
    assert e.value.key == "rhc_err_pull_refused" and e.value.detail == "HTTP 403"


def test_zh_tw_builds(ctx):
    assert _build(ctx, lang=Language.ZH_TW).title


# ── availability (greyed out) and the scheduled run ──────────────────────────

@pytest.mark.parametrize(("state", "key"), [
    (RhcState.ENABLED, None), (RhcState.PARTIAL, "rpt_unavailable_rhc_off"),
    (RhcState.DISABLED, "rpt_unavailable_rhc_off"), (RhcState.UNSUPPORTED, "rpt_unavailable_rhc_unsupported"),
    (RhcState.UNKNOWN, "rpt_unavailable_rhc_unknown")])
def test_not_enabled_greyed(ctx, monkeypatch, state, key):
    monkeypatch.setattr(rhc, "cached_status", lambda ctx: _status(state))
    assert generate.availability(ctx)[ReportType.RULE_HIT_COUNT] == key


def test_scheduled_not_enabled_fails(ctx, monkeypatch):
    monkeypatch.setattr(rhc, "cached_status", lambda ctx: _status())  # on when queued
    rid = generate.enqueue(ctx, ReportParams(report_type=ReportType.RULE_HIT_COUNT), trigger="schedule",
                           schedule_id="s", now=NOW)
    monkeypatch.setattr(rule_hit_count, "rhc_status", lambda ctx: _status(RhcState.DISABLED))  # off by the run
    generate.run_queued(ctx, now=NOW)
    with ctx.db() as conn:
        row = store.get(conn, rid)
    assert row.status is ReportStatus.FAILED and row.error_key == "rpt_unavailable_rhc_off"
    assert not list((ctx.paths.reports_dir / str(rid)).glob("*"))


# ── lab 2026-10-30: the PCE's report also lists Draft-only rules (pending create) under active hrefs, 0, "N/A" ──

def test_zero_row_not_in_active_policy_is_not_zero(ctx, monkeypatch):
    draft_only = RhcRow(rule_href="/orgs/1/sec_policy/active/rule_sets/673/deny_rules/309", ruleset_name="tedt",
                        description="", hit_count=0, last_hit_at=None)
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull(rows=[*_pull().rows, draft_only]))
    doc = _build(ctx)
    assert _ids(_table(doc, "zero")) == ["#11"]
    unprovisioned = [b for b in _section(doc, "no_record").blocks if isinstance(b, TableBlock)][1]
    assert [r[0] for r in unprovisioned.rows] == ["tedt"]
    assert {x.key: x.value for x in doc.kpis}["zero"] == 1


def test_zero_table_shows_last_hit_before_the_period(ctx, monkeypatch):
    old = RhcRow(rule_href=f"{A}/sec_rules/11", ruleset_name="Web", description="", hit_count=0,
                 last_hit_at="2026-06-26T09:09:16Z")
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull(rows=[_pull().rows[0], old]))
    assert "2026-06-26" in _table(_build(ctx), "zero").rows[0][3]


def test_zero_finding_counts_allow_rules_only(ctx, monkeypatch):
    """Lab 2026-10-30: a Deny Rule at 0 means nothing tried the blocked path — not an open path to review."""
    d = "/orgs/1/sec_policy/active/rule_sets/2/deny_rules/5"
    sets = [*RULE_SETS, {"href": "/orgs/1/sec_policy/active/rule_sets/2", "name": "Guard", "rules": [],
                         "deny_rules": [{"href": d, "enabled": True, "consumers": [], "providers": [],
                                         "ingress_services": []}]}]
    monkeypatch.setattr(rule_hit_count, "fetch_rule_sets", lambda client, pversion, *, deadline: sets)
    zero_deny = RhcRow(rule_href=d, ruleset_name="Guard", description="", hit_count=0, last_hit_at=None)
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull(rows=[*_pull().rows, zero_deny]))
    doc = _build(ctx)
    assert len(_table(doc, "zero").rows) == 2
    [f] = [f for f in doc.findings if "0 hits" in f.title]
    assert f.title.startswith("1 ")
