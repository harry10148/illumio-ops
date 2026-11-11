"""6.6.0 rule: a report with no optional setting made, and with the analyses not yet run, reads from its title to its
end as computed content. Optional settings only add to it.

For every report type, built on an install that has traffic, hosts and events but no critical assets, no admin groups
and no stored analysis result: the opening sentence is a sentence (not "could not be computed"), no key number is
blank, no section is an empty shell, and each thing that is missing is said once in the data notes."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.conclusion import incomplete
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports import policy_resolver as policy_resolver_report
from illumio_ops.services.reports import policy_usage, ransomware_report
from illumio_ops.services.reports import readiness as readiness_report
from illumio_ops.services.reports.finish import finish, holds_nothing
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from tests.services.collect.conftest import configured_ctx
from tests.services.reports import test_report_i18n as rich
from tests.services.reports.test_lateral_posture import _hosts
from tests.services.reports.test_new_connections import _baseline
from tests.services.reports.test_policy_usage import usage
from tests.services.reports.test_unmanaged import _rollup

NOW, START, END = rich.NOW, rich.START, rich.END


@pytest.fixture(scope="module")
def bare(tmp_path_factory):
    """The i18n fixture's data, without the optional settings and without any analysis result."""
    c = configured_ctx(tmp_path_factory.mktemp("bare"))
    _hosts(c)
    d = datetime(2026, 10, 22, tzinfo=UTC)
    _baseline(c, [("/orgs/1/workloads/a", "/orgs/1/workloads/db", 3389, d, "allowed"),
                  ("ip:10.9.9.9", "/orgs/1/workloads/a", 445, d, "unknown")])
    _rollup(c, [("2026-10-21", "ip:10.5.5.5", "/orgs/1/workloads/a", 445, "allowed", 10),
                ("2026-10-23", "/orgs/1/workloads/a", "ip:8.8.8.8", 53, "allowed", 3)])
    rich._rule_flows(c)
    rich._p5b2_sample(c)
    with c.flows().connect() as conn:
        conn.execute("DELETE FROM analysis_results")  # exposure, ransomware, tamper, focus: none computed yet
        conn.commit()
    assert not c.settings.current().lateral.critical_assets and not c.settings.current().lateral.admin_groups
    mp = pytest.MonkeyPatch()
    mp.setattr(readiness_report, "predicted_summary", lambda ctx, spec, **kw: rich.PredictedSummary(
        groups=[], rules={}, blocked_flows=0, blocked_connections=0, undetermined_flows=0, capped=False,
        computed_at=NOW, unsupported=False, missing_rules=[]))
    mp.setattr(policy_usage, "rule_usage", lambda ctx, **kw: usage())
    rich._rhc_sample(mp)
    rich._pdf_sample(mp)
    mp.setattr(policy_resolver_report, "resolve", lambda ctx, **kw: rich.Resolved(
        rows=[{"ruleset_name": "Web", "rule_href": "/r/1", "action": "allow", "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
               "port": 1433, "protocol": "TCP"}], per_ruleset={"Web": 1}, rule_count=1, rules_capped=0,
        truncated_rulesets=[], rows_omitted=0, not_expanded=[], rules_no_address=0, computed_at=NOW))
    mp.setattr(ransomware_report, "host_ransomware", lambda ctx, href, **kw: rich.HostRansomware.model_construct(
        breakdown=None, allow_rules={}, allow_status={}))
    yield c
    mp.undo()


def _doc(ctx, rt, lang=Language.EN):
    cond = rich.APP_DB if specs()[rt].requires_app else None
    custom_id = rich._custom(ctx) if rt is ReportType.CUSTOM else None
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=rt, filter=cond, custom_id=custom_id), start=START,
                     end=END, lang=lang, tz=UTC, now=NOW, pce_label="pce")
    return finish(specs()[rt].build(inp))


TYPES = list(ReportType)


@pytest.mark.parametrize("rt", TYPES)
def test_the_opening_sentence_is_a_sentence(bare, rt):
    assert not incomplete(_doc(bare, rt)), rt


@pytest.mark.parametrize("rt", TYPES)
def test_no_key_number_is_blank(bare, rt):
    doc = _doc(bare, rt)
    assert [k.key for k in doc.kpis if k.value is None] == []


@pytest.mark.parametrize("rt", TYPES)
def test_no_section_is_an_empty_shell(bare, rt):
    doc = _doc(bare, rt)
    shells = [s.id for s in doc.sections if holds_nothing(s)]
    # a report with nothing at all to show keeps its sections, each saying why it is empty (finish.py)
    assert shells == [] or len(shells) == len(doc.sections)


@pytest.mark.parametrize("rt", TYPES)
def test_each_missing_thing_is_said_once(bare, rt):
    doc = _doc(bare, rt)
    assert len(doc.data_quality) == len(set(doc.data_quality)), "a data note is repeated"


def test_a_section_that_holds_nothing_becomes_a_line_at_the_end():
    """Computed, and 0: the section gives up its panel and is listed, with what its empty table said, in the closing
    section. A report whose every section is empty keeps them (each says why)."""
    from illumio_ops.domain.report import (
        Column,
        ReportDocument,
        Section,
        TableBlock,
        TextBlock,
    )
    col = (Column(key="a", label="A"),)
    full = Section(id="full", title="Full", blocks=(TableBlock(title="t", columns=col, rows=(("x",),), total_rows=1,
                                                               empty_text="-"),))
    none = Section(id="none", title="Disappeared connections", blocks=(TableBlock(
        title="t", columns=col, rows=(), total_rows=0, empty_text="No connection disappeared."),))
    words = Section(id="words", title="Words", blocks=(TextBlock(paragraphs=("said",)),))

    def doc(*sections):
        return ReportDocument(report_type=ReportType.TRAFFIC, lang=Language.EN, title="T", period_start=START,
                              period_end=END, generated_at=NOW, pce_label="pce", kpis=(), findings=(), data_quality=(),
                              sections=sections)
    out = finish(doc(full, none, words))
    assert [s.id for s in out.sections] == ["full", "words", "nothing"]
    assert out.sections[-1].blocks[0].paragraphs == ("Disappeared connections: No connection disappeared.",)
    assert [s.id for s in finish(doc(none)).sections] == ["none"]
    assert [s.id for s in finish(doc(full)).sections] == ["full"]


def test_a_column_blank_on_every_row_is_not_printed():
    """6.6.0 Task 5: lateral posture printed 113 rows with two columns that never held a value."""
    from illumio_ops.domain.report import Column, ReportDocument, Section, TableBlock
    cols = (Column(key="a", label="A"), Column(key="b", label="B"), Column(key="c", label="C"))
    table = TableBlock(title="t", columns=cols, rows=(("x", "", 0), ("y", None, 2)), total_rows=2, empty_text="-")
    blank = TableBlock(title="u", columns=cols[:2], rows=(("", None),), total_rows=1, empty_text="-")
    doc = ReportDocument(report_type=ReportType.TRAFFIC, lang=Language.EN, title="T", period_start=START,
                         period_end=END, generated_at=NOW, pce_label="pce", kpis=(), findings=(), data_quality=(),
                         sections=(Section(id="s", title="S", blocks=(table, blank)),))
    out = finish(doc).sections[0].blocks
    assert [c.key for c in out[0].columns] == ["a", "c"] and out[0].rows == (("x", 0), ("y", 2))  # 0 is a value
    assert out[1] == blank  # nothing left to print: left as it was


def test_a_custom_report_keeps_every_section_it_was_given():
    """The operator chose the sections and the opening sentence counts them: an empty one is not folded away."""
    from illumio_ops.domain.report import Column, ReportDocument, Section, TableBlock
    col = (Column(key="a", label="A"),)
    full = Section(id="s1", title="Full", blocks=(TableBlock(title="t", columns=col, rows=(("x",),), total_rows=1,
                                                             empty_text="-"),))
    none = Section(id="s2", title="None", workbench_link="https://x/investigate?q=1",
                   blocks=(TableBlock(title="t", columns=col, rows=(), total_rows=0, empty_text="Nothing matched."),))
    doc = ReportDocument(report_type=ReportType.CUSTOM, lang=Language.EN, title="T", period_start=START, period_end=END,
                         generated_at=NOW, pce_label="pce", kpis=(), findings=(), data_quality=(), sections=(full, none))
    out = finish(doc)
    assert [s.id for s in out.sections] == ["s1", "s2"] and out.sections[1].workbench_link


OWN_ANALYSIS = [ReportType.LATERAL_POSTURE, ReportType.RANSOMWARE, ReportType.SECURITY_RISK, ReportType.VEN_STATUS]


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    yield from rich.ctx.__wrapped__(tmp_path_factory)


@pytest.mark.parametrize("rt", OWN_ANALYSIS)
def test_what_the_bare_report_leaves_out_has_a_note(bare, full, rt):
    """Gate for the hints: every key number or section the report has with its settings and analyses, and leaves
    out without them, is matched by a data note the full report does not carry."""
    with_all, without = _doc(full, rt), _doc(bare, rt)
    gone = ({k.key for k in with_all.kpis} - {k.key for k in without.kpis}) | (
        {s.id for s in with_all.sections} - {s.id for s in without.sections} - {"nothing"})
    said = set(without.data_quality) - set(with_all.data_quality)
    assert gone, "the two builds do not differ: the fixture no longer exercises the hints"
    assert said, f"{sorted(gone)} left out with no data note"
