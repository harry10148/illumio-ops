"""Rule Hit Count as a chapter of the policy usage report (UI redesign spec §9.2, stage 3b; a report of its own until
then, P5c-2): the PCE's own count of provisioned rules' hits. Zero hits and no record are apart. Without the counts
— Rule Hit Count off, half on, not on this PCE, its state unreadable, the PCE refusing or not answering — the report
is made all the same and the chapter is the reason in words; the PCE is asked to produce its report only when Rule
Hit Count is on (producing one writes to the PCE)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.conclusion import CONCLUSIONS, conclusion
from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType, RhcState
from illumio_ops.i18n import translate
from illumio_ops.pce.client import PceTransportError
from illumio_ops.pce.policy import PolicyNames
from illumio_ops.services.reports import policy_usage, rule_hit_count
from illumio_ops.services.reports.finish import finish
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.rhc import RhcPull, RhcPullError, RhcRow, RhcStatus
from tests.services.collect.conftest import configured_ctx
from tests.services.reports.test_policy_usage import usage

NOW = datetime(2026, 10, 30, 1, tzinfo=UTC)
START, END = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC)
A = "/orgs/1/sec_policy/active/rule_sets/1"
RULE_SETS = [{"href": A, "name": "Web", "rules": [
    {"href": f"{A}/sec_rules/10", "enabled": True, "consumers": [], "providers": [], "ingress_services": []},
    {"href": f"{A}/sec_rules/11", "enabled": True, "consumers": [], "providers": [], "ingress_services": []},
    {"href": f"{A}/sec_rules/12", "enabled": True, "consumers": [], "providers": [], "ingress_services": []},
    {"href": f"{A}/sec_rules/13", "enabled": False, "consumers": [], "providers": [], "ingress_services": []}],
    "deny_rules": []}]
OWN = (3, 1, 1, 1, 1, 9)  # the report's own six numbers for test_policy_usage.usage(): the hit counts never move them
OWN_KEYS = ("rules", "used", "unused", "disabled", "deny_hit", "no_rule")
HITS = ("rhc_hit", "rhc_zero", "rhc_no_record")


def _status(state=RhcState.ENABLED, reason=None, *, saas=False):
    return RhcStatus(state=state, pce_report=state is RhcState.ENABLED, ven_scopes=state is RhcState.ENABLED,
                     reason_key=reason, detail=None, write_key=True, saas=saas)


def _pull(rows=None, unparsed=0):
    rows = rows if rows is not None else [
        RhcRow(rule_href=f"{A}/sec_rules/10", ruleset_name="Web", description="", hit_count=42,
               last_hit_at="2026-10-29T10:00:00Z"),
        RhcRow(rule_href=f"{A}/sec_rules/11", ruleset_name="Web", description="", hit_count=0, last_hit_at=None)]
    return RhcPull(rows=rows, start=START, end=END, unparsed=unparsed)


class Spy:
    """Counts the calls that reach the PCE for hit counts: producing its report (a write), and the active rules."""

    def __init__(self, monkeypatch, *, pull=None):
        self.pulls = self.rule_reads = 0
        self._pull = pull or (lambda: _pull())
        monkeypatch.setattr(rule_hit_count, "pull_rhc", self.pull_rhc)
        monkeypatch.setattr(rule_hit_count, "fetch_rule_sets", self.fetch_rule_sets)

    def pull_rhc(self, ctx, start, end):
        self.pulls += 1
        return self._pull()

    def fetch_rule_sets(self, client, pversion, *, deadline):
        self.rule_reads += 1
        assert pversion == "active"
        return RULE_SETS


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(policy_usage, "rule_usage", lambda ctx, **kw: usage())
    monkeypatch.setattr(rule_hit_count, "rhc_status", lambda ctx: _status())
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull())
    monkeypatch.setattr(rule_hit_count, "fetch_rule_sets", lambda client, pversion, *, deadline: RULE_SETS)
    monkeypatch.setattr(rule_hit_count, "fetch_policy_names",
                        lambda client, pversion, *, deadline: PolicyNames(labels={}, names={}))
    return configured_ctx(tmp_path)


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.POLICY_USAGE].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.POLICY_USAGE), start=START, end=END, lang=lang, tz=UTC,
        now=NOW, pce_label="pce"))


def _chapter(doc):
    return next(s for s in doc.sections if s.id == "rhc")


def _tables(doc):
    return [b for b in _chapter(doc).blocks if isinstance(b, TableBlock)]


def _table(doc, which):
    """One of the chapter's tables, by the place the old report's sections had."""
    return _tables(doc)[("hit", "zero", "no_record", "unprovisioned").index(which)]


def _ids(table):
    return [r[1].split()[0] for r in table.rows]


def _numbers(doc, keys):
    by = {k.key: k.value for k in doc.kpis}
    return tuple(by[k] for k in keys)


def _sentence(doc):
    done = finish(doc)
    return conclusion(done, lambda key, params: translate(done.lang, key, params), tz=UTC)


# ── with the counts ──────────────────────────────────────────────────────────

def test_the_chapter_follows_the_unused_rules(ctx):
    doc = _build(ctx)
    assert [s.id for s in doc.sections] == ["how", "pending", "used", "unused", "rhc", "disabled", "deny", "no_rule"]
    assert _chapter(doc).title == "Hits on the rules in force"
    assert _chapter(_build(ctx, Language.ZH_TW)).title == "已生效規則的實際命中"


def test_the_three_tables_hold_the_rows_the_old_report_had(ctx):
    """Written down from build_rule_hit_count's output for this same fake data, before that builder was removed."""
    doc = _build(ctx)
    hit, zero, no_record = _tables(doc)
    assert ([c.key for c in hit.columns], hit.rows) == (
        ["ruleset", "rule", "type", "hits", "last", "scope"],
        (("Web", "#10", "Allow", 42, "2026-10-29 10:00", "any → any：any"),))
    assert ([c.key for c in zero.columns], zero.rows) == (
        ["ruleset", "rule", "type", "last", "scope"], (("Web", "#11", "Allow", "never", "any → any：any"),))
    assert ([c.key for c in no_record.columns], no_record.rows) == (
        ["ruleset", "rule", "type", "scope"], (("Web", "#12", "Allow", "any → any：any"),))
    assert [t.title for t in (hit, zero, no_record)] == [
        "Rules hit in the period", "Rules recorded with 0 hits", "Provisioned, no record"]
    zh = _tables(_build(ctx, Language.ZH_TW))
    assert [t.rows for t in zh] == [(("Web", "#10", "允許規則", 42, "2026-10-29 10:00", "不限 → 不限：不限"),),
                                    (("Web", "#11", "允許規則", "從未", "不限 → 不限：不限"),),
                                    (("Web", "#12", "允許規則", "不限 → 不限：不限"),)]


def test_the_other_sample_keeps_its_rows_too(ctx, monkeypatch):
    """The sample every report type is built from (test_report_i18n): a rule deleted since, an Override Deny."""
    from tests.services.reports import test_report_i18n as rich
    rich._rhc_sample(monkeypatch)
    doc = _build(ctx)
    assert [t.rows for t in _tables(doc)] == [
        (("Web", "#1", "Allow", 9, "2026-10-26 10:00", "any → any：any"), ("Old", "#9", "—", 1, "—", "—")),
        (("Web", "#2", "Allow", "never", "any → any：any"),),
        (("Web", "#4", "Override Deny", "any → any：any"), ("Web", "#3", "Allow", "any → any：any"))]
    assert _numbers(doc, HITS) == (2, 1, 2)  # what the old report's hit, zero and no_record were
    assert [q for q in doc.data_quality if "Rule Hit Count" in q or "counted rule" in q or "could not be read" in q] == [
        ("The hit counts in “Hits on the rules in force” come from the PCE's Rule Hit Count report, counted by the "
         "VENs; the PCE keeps them 90 days."),
        "1 row(s) of the PCE's report had a hit count that could not be read; they are left out, not counted as 0.",
        ("1 counted rule(s) are no longer in the provisioned policy (deleted or changed since); they are listed under "
         "the ruleset name the PCE reported.")]


def test_the_three_numbers_count_the_rows_of_the_three_tables(ctx):
    """Provisioned and 0 hits in the period ≠ no record (provisioned later, or a Draft rule): never shown as 0."""
    doc = _build(ctx)
    assert _numbers(doc, HITS) == tuple(t.total_rows for t in _tables(doc)) == (1, 1, 1)
    assert _numbers(doc, OWN_KEYS) == OWN
    assert [k.key for k in doc.kpis] == [*OWN_KEYS, *HITS]
    by = {k.key: k for k in doc.kpis}
    assert all(by[k].note is None and by[k].previous is None for k in HITS)
    assert (by["rhc_hit"].label, by["rhc_hit"].better, by["rhc_zero"].better, by["rhc_no_record"].better) == (
        "Rules in force: hit in the period", "higher", "lower", "neutral")


@pytest.mark.parametrize("lang", list(Language))
def test_with_the_counts_the_sentence_says_how_many_were_hit(ctx, lang):
    doc = _build(ctx, lang)
    keys, template = CONCLUSIONS[ReportType.POLICY_USAGE][0]
    assert template == "rpt_conclusion_policy_usage_hits" and {"rhc_hit", "rhc_zero"} < set(keys)
    by = {k.key: str(k.value) for k in doc.kpis}
    assert _sentence(doc) == translate(lang, template, {k: by[k] for k in keys})


def test_the_terms_of_the_counts_are_in_how_the_report_is_worked_out(ctx):
    how = next(s for s in _build(ctx).sections if s.id == "how")
    said = [p for b in how.blocks if isinstance(b, TextBlock) for p in b.paragraphs]
    assert said[-1].startswith("Hit: a connection the rule decided") and "No record is not the same as 0." in said[-1]
    assert "Rule Hit Count" in how.intro


def test_the_intro_of_the_last_table_names_the_table_it_means(ctx):
    """The old report said "the second table": here it is one of four, named by its title."""
    for lang, title in ((Language.EN, "Listed, no count"), (Language.ZH_TW, "有列出、沒有計數")):
        said = [p for b in _chapter(_build(ctx, lang)).blocks if isinstance(b, TextBlock) for p in b.paragraphs]
        assert any(title in p for p in said) and not any("second table" in p or "第二個表" in p for p in said)


def test_unparsed_rows_disclosed(ctx, monkeypatch):
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull(unparsed=3))
    assert any("3" in q and "could not be read" in q for q in _build(ctx).data_quality)


def test_the_notes_say_where_the_counts_come_from(ctx):
    notes = _build(ctx).data_quality
    assert any("Rule Hit Count report" in q and "Hits on the rules in force" in q for q in notes)
    assert not any("has no data" in q for q in notes)


def test_rule_not_in_active_policy_still_listed(ctx, monkeypatch):
    """A rule deleted since keeps its hits under the ruleset name the PCE gave."""
    gone = RhcRow(rule_href=f"{A}/sec_rules/99", ruleset_name="Old", description="", hit_count=5, last_hit_at=None)
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull(rows=[*_pull().rows, gone]))
    doc = _build(ctx)
    assert _table(doc, "hit").rows == (("Web", "#10", "Allow", 42, "2026-10-29 10:00", "any → any：any"),
                                      ("Old", "#99", "—", 5, "—", "—"))
    assert any("1 counted rule(s) are no longer in the provisioned policy" in q for q in doc.data_quality)


# ── lab 2026-10-30: the PCE's report also lists Draft-only rules (pending create) under active hrefs, 0, "N/A" ──

def test_zero_row_not_in_active_policy_is_not_zero(ctx, monkeypatch):
    draft_only = RhcRow(rule_href="/orgs/1/sec_policy/active/rule_sets/673/deny_rules/309", ruleset_name="tedt",
                        description="", hit_count=0, last_hit_at=None)
    monkeypatch.setattr(rule_hit_count, "pull_rhc", lambda ctx, start, end: _pull(rows=[*_pull().rows, draft_only]))
    doc = _build(ctx)
    assert _ids(_table(doc, "zero")) == ["#11"]
    unprovisioned = _table(doc, "unprovisioned")
    assert unprovisioned.title == "Listed, no count" and unprovisioned.rows == (("tedt", "#309"),)
    # the no-record number counts what its table lists; a Draft-only row is in the table after it (lab .106
    # 2026-11-03: the sentence read "2 rules: 0 hit, 2 with 0 hits, 2 with no record")
    assert _numbers(doc, HITS) == (1, 1, 1)


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
    # the same thing to do as the report's own unused rules: one code, one sentence, so the first page names it once
    assert f.action_code == "unused_rules"
    assert f.action_short == "Confirm with their owners whether the rules no traffic used are still needed."
    assert [x.action_code for x in doc.findings] == ["unused_rules", "unused_rules"]


def test_rule_provisioned_after_the_period_is_not_zero(ctx, monkeypatch):
    """Review #2: a rule created after the period ends is listed by the PCE with 0 — it had no count then."""
    later = [{**RULE_SETS[0], "rules": [*RULE_SETS[0]["rules"][:1],
                                        {**RULE_SETS[0]["rules"][1], "created_at": "2026-10-30T01:00:00Z"},
                                        *RULE_SETS[0]["rules"][2:]]}]
    monkeypatch.setattr(rule_hit_count, "fetch_rule_sets", lambda client, pversion, *, deadline: later)
    doc = _build(ctx)
    assert _ids(_table(doc, "zero")) == []
    assert _ids(_table(doc, "unprovisioned")) == ["#11"]


def test_rule_text_leaves_out_the_schedule_note(ctx, monkeypatch):
    # 2026-11-10 report review: a scheduled rule read "#10 web [📅 Recurring: ...]" - the note illumio-ops writes
    # into the PCE description to mark its own schedule is not part of what the rule is called. The PCE's own CSV
    # carries the same description for a rule no longer in the policy: tests/services/test_rhc.py.
    note = "[📅 Recurring: mon 09:00-17:00 (Asia/Taipei) enable]"
    sets = [{**RULE_SETS[0], "rules": [{**r, "description": f"web {note}"} for r in RULE_SETS[0]["rules"]]}]
    monkeypatch.setattr(rule_hit_count, "fetch_rule_sets", lambda client, pversion, *, deadline: sets)
    doc = _build(ctx)
    texts = [r[1] for which in ("hit", "zero", "no_record") for r in _table(doc, which).rows]
    assert sorted(texts) == ["#10 web", "#11 web", "#12 web"]


def test_the_counts_do_not_wait_for_the_draft_recompute(ctx, monkeypatch):
    """The two halves fail apart: with no recompute the six numbers are blank and the hit counts are still there."""
    def boom(ctx, **kw):
        from illumio_ops.pce.async_query import PceQueryError
        raise PceQueryError("poll", 500)
    monkeypatch.setattr(policy_usage, "rule_usage", boom)
    doc = _build(ctx)
    assert _numbers(doc, OWN_KEYS) == (None,) * 6 and _numbers(doc, HITS) == (1, 1, 1)
    assert len(_tables(doc)) == 3


# ── without the counts: the report is made, the chapter says why ─────────────

def _refused(ctx, start, end):
    raise RhcPullError("rhc_err_pull_refused", "HTTP 403")


def _unreachable(ctx, start, end):
    raise PceTransportError("/reports", "timeout")


# case -> (the state read, what producing the PCE's report does, the chapter's paragraphs as (key, params))
WITHOUT = {
    "off": (_status(RhcState.DISABLED), None, [("rpt_unavailable_rhc_off", {})]),
    "half on": (_status(RhcState.PARTIAL, "rhc_reason_partial_ven"), None,
                [("rpt_unavailable_rhc_off", {}), ("rhc_reason_partial_ven", {})]),
    "off on SaaS": (_status(RhcState.DISABLED, saas=True), None,
                    [("rpt_unavailable_rhc_off", {}), ("rhc_saas_note", {})]),
    "not on this PCE": (_status(RhcState.UNSUPPORTED, "rhc_reason_unsupported"), None,
                        [("rpt_unavailable_rhc_unsupported", {})]),
    "state unknown": (_status(RhcState.UNKNOWN, "rhc_reason_needs_write_key"), None,
                      [("rpt_unavailable_rhc_unknown", {}), ("rhc_reason_needs_write_key", {})]),
    "refused (403)": (_status(), _refused, [("rhc_err_pull_refused", {}), ("rpt_rhc_detail", {"detail": "HTTP 403"})]),
    "PCE unreachable": (_status(), _unreachable, [("rpt_rhc_failed", {
        "error": "PceTransportError: PCE request /reports failed: timeout"})]),
}


@pytest.mark.parametrize("lang", list(Language))
@pytest.mark.parametrize("case", list(WITHOUT))
def test_without_the_counts_the_report_is_made_and_the_chapter_says_why(ctx, monkeypatch, case, lang):
    status, pull, said = WITHOUT[case]
    monkeypatch.setattr(rule_hit_count, "rhc_status", lambda ctx: status)
    if pull is not None:
        monkeypatch.setattr(rule_hit_count, "pull_rhc", pull)
    doc = _build(ctx, lang)
    paragraphs = tuple(translate(lang, key, params) for key, params in said)
    chapter = _chapter(doc)
    assert chapter.blocks == (TextBlock(paragraphs=paragraphs),)  # one paragraph block: no table, not an empty one
    assert all(p.strip() and "{" not in p and not p.startswith(("rpt_", "rhc_")) for p in paragraphs)
    by = {k.key: k for k in doc.kpis}
    assert [(by[k].value, by[k].note) for k in HITS] == [(None, paragraphs[0])] * 3
    assert _numbers(doc, OWN_KEYS) == OWN
    # the sentence it had before the chapter joined it, and nothing of the hit counts
    keys, template = CONCLUSIONS[ReportType.POLICY_USAGE][1]
    assert template == "rpt_conclusion_policy_usage"
    assert _sentence(doc) == translate(lang, template, {k: str(by[k].value) for k in keys})
    assert translate(lang, "rpt_rhc_quality_none", {"chapter": chapter.title, "reason": paragraphs[0]}) \
        in doc.data_quality
    assert not any(f.title == translate(lang, "rpt_rhc_finding_zero", {"n": "1"}) for f in doc.findings)
    how = next(s for s in doc.sections if s.id == "how")
    assert translate(lang, "rpt_rhc_how_terms", {}) not in [p for b in how.blocks for p in b.paragraphs]
    assert [s.id for s in doc.sections] == ["how", "pending", "used", "unused", "rhc", "disabled", "deny", "no_rule"]


@pytest.mark.parametrize("state", [s for s in RhcState if s is not RhcState.ENABLED])
def test_the_pce_is_not_asked_for_its_report_unless_rule_hit_count_is_on(ctx, monkeypatch, state):
    """Producing the PCE's report is a write (POST /reports): never while Rule Hit Count is not known to be on."""
    spy = Spy(monkeypatch)
    monkeypatch.setattr(rule_hit_count, "rhc_status", lambda ctx: _status(state))
    assert _numbers(_build(ctx), HITS) == (None, None, None)
    assert (spy.pulls, spy.rule_reads) == (0, 0)


def test_the_pce_is_asked_once_when_rule_hit_count_is_on(ctx, monkeypatch):
    spy = Spy(monkeypatch)
    assert _numbers(_build(ctx), HITS) == (1, 1, 1)
    assert (spy.pulls, spy.rule_reads) == (1, 1)


def test_a_failed_read_of_the_active_rules_is_said_like_an_unreachable_pce(ctx, monkeypatch):
    def boom(client, pversion, *, deadline):
        raise PceTransportError("/sec_policy/active/rule_sets", "refused")
    monkeypatch.setattr(rule_hit_count, "fetch_rule_sets", boom)
    doc = _build(ctx)
    [text] = _chapter(doc).blocks
    assert text.paragraphs == (("The hit counts and the rules in force could not be read from the PCE "
                                "(PceTransportError: PCE request /sec_policy/active/rule_sets failed: refused)."),)
    assert _numbers(doc, HITS) == (None, None, None) and _numbers(doc, OWN_KEYS) == OWN
