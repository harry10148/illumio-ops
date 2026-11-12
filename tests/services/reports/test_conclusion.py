"""Each report opens with one sentence computed from its own key numbers (UI redesign spec §6, §8): every type has a
template in both languages, every placeholder is a number the type's builder produces, and a number that could not
be computed makes it say so instead of 0."""
import re
from datetime import UTC

import pytest

from illumio_ops.domain.conclusion import (
    CONCLUSION_KEYS,
    CONCLUSION_KPIS,
    CONCLUSIONS,
    LEAD_KPIS,
    conclusion,
)
from illumio_ops.domain.report import Kpi, ReportDocument
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.i18n import dictionary, translate
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from tests.services.reports.test_report_i18n import (  # noqa: F401 - fixture
    APP_DB,
    END,
    NOW,
    START,
    _custom,
    ctx,
)

PH = re.compile(r"\{(\w+)\}")


def _tr(lang):
    return lambda key, params: translate(lang, key, params)


@pytest.mark.parametrize("lang", list(Language))
def test_every_type_has_template(lang):
    words = dictionary(lang)
    assert set(CONCLUSION_KEYS) == set(ReportType)
    assert all(CONCLUSION_KEYS[t] in words for t in ReportType)
    assert "rpt_conclusion_incomplete" in words


@pytest.mark.parametrize("report_type", list(ReportType))
def test_placeholders_match_declared_kpis(report_type):
    for lang in Language:
        found = set(PH.findall(dictionary(lang)[CONCLUSION_KEYS[report_type]]))
        assert found == set(CONCLUSION_KPIS[report_type]), (report_type, lang)
        for keys, template in CONCLUSIONS[report_type]:  # every sentence form names exactly its own numbers
            assert set(PH.findall(dictionary(lang)[template])) == set(keys), (report_type, template, lang)


def test_a_sentence_form_without_the_missing_number_is_used(monkeypatch):
    """6.6.0 Task 1: a report type has an ordered list of sentence forms; the first whose numbers are all there
    is used, so a number that an unset optional setting leaves out does not turn the sentence into "could not be
    computed". Only when no form applies is the sentence the incomplete one."""
    from illumio_ops.domain import conclusion as mod
    forms = ((("flows", "connections", "sources", "destinations"), "rpt_conclusion_traffic"),
             (("flows", "connections"), "rpt_conclusion_test_short"))
    monkeypatch.setattr(mod, "CONCLUSIONS", {**mod.CONCLUSIONS, ReportType.TRAFFIC: forms})
    used = []

    def tr(key, params):
        used.append((key, params))
        return key
    full = [Kpi(key=k, label=k, value=1, previous=None) for k in ("flows", "connections", "sources", "destinations")]
    assert conclusion(_doc(full), tr) == "rpt_conclusion_traffic"
    assert conclusion(_doc(full[:2]), tr) == "rpt_conclusion_test_short" and used[-1][1] == {"flows": "1", "connections": "1"}
    none = [full[0], Kpi(key="connections", label="Connections", value=None, previous=None, note="why")]
    assert conclusion(_doc(none), tr) == "rpt_conclusion_incomplete"
    assert mod.incomplete(_doc(none)) and not mod.incomplete(_doc(full[:2]))


@pytest.mark.parametrize("report_type", [t for t in ReportType if t is not ReportType.CUSTOM])
def test_declared_kpis_exist_in_builder_output(ctx, report_type):  # noqa: F811
    cond = APP_DB if specs()[report_type].requires_app else None
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=report_type, filter=cond), start=START, end=END,
                     lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")
    doc = specs()[report_type].build(inp)
    assert set(CONCLUSION_KPIS[report_type]) <= {k.key for k in doc.kpis}, report_type
    text = conclusion(doc, _tr(Language.EN))
    assert text and "{" not in text and "None" not in text


@pytest.mark.parametrize("report_type", sorted(LEAD_KPIS))
def test_lead_kpis_exist_in_builder_output(ctx, report_type):  # noqa: F811
    """Stage 3a: the three numbers a report's first page leads with are numbers its builder produces, and after the
    closing step they are the first three."""
    from illumio_ops.services.reports.finish import finish
    cond = APP_DB if specs()[report_type].requires_app else None
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=report_type, filter=cond), start=START, end=END,
                     lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")
    doc = specs()[report_type].build(inp)
    assert set(LEAD_KPIS[report_type]) <= {k.key for k in doc.kpis}, report_type
    done = finish(doc)
    assert tuple(k.key for k in done.kpis[:3]) == LEAD_KPIS[report_type]
    rest = [k.key for k in doc.kpis if k.key not in LEAD_KPIS[report_type]]
    assert [k.key for k in done.kpis[3:]] == rest


def test_custom_counts_sections(ctx):  # noqa: F811
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.CUSTOM, custom_id=_custom(ctx)), start=START,
                     end=END, lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")
    doc = specs()[ReportType.CUSTOM].build(inp)
    assert str(len(doc.sections)) in conclusion(doc, _tr(Language.EN))


def _doc(kpis, report_type=ReportType.TRAFFIC):
    return ReportDocument(report_type=report_type, lang=Language.EN, title="Traffic", period_start=START,
                          period_end=END, generated_at=NOW, pce_label="pce", kpis=tuple(kpis), findings=(),
                          data_quality=(), sections=())


def test_none_kpi_gives_incomplete_sentence():
    doc = _doc([Kpi(key="flows", label="Flow records", value=None, previous=None, note="no traffic kept"),
                Kpi(key="connections", label="Connections", value=5, previous=None),
                Kpi(key="sources", label="Sources", value=1, previous=None),
                Kpi(key="destinations", label="Destinations", value=1, previous=None)])
    text = conclusion(doc, _tr(Language.EN))
    assert "Flow records" in text and "no traffic kept" in text and " 0 " not in text


def test_a_reason_ending_in_a_full_stop_is_not_closed_twice():
    """lab .106 2026-11-03: 「…設定頁以 Label 選定。）。」 — the note's own full stop inside the brackets."""
    note = {Language.ZH_TW: "尚未設定重要資產；請到設定頁選定。", Language.EN: "No critical assets are set; choose them."}
    for lang, end in ((Language.ZH_TW, "選定）。"), (Language.EN, "choose them).")):
        doc = _doc([Kpi(key="flows", label="F", value=None, previous=None, note=note[lang]),
                    Kpi(key="connections", label="C", value=5, previous=None),
                    Kpi(key="sources", label="S", value=1, previous=None),
                    Kpi(key="destinations", label="D", value=1, previous=None)])
        doc = doc.model_copy(update={"lang": lang})
        assert conclusion(doc, _tr(lang)).endswith(end)


def test_percent_and_thousands_formatted():
    doc = _doc([Kpi(key="maturity", label="M", value=62, previous=None),
                Kpi(key="enforced_hosts_pct", label="E", value=45.25, previous=None, unit="percent"),
                Kpi(key="critical_high_findings", label="C", value=1234, previous=None)], ReportType.SECURITY_RISK)
    text = conclusion(doc, _tr(Language.EN))
    assert "45.2%" in text and "1,234" in text and "0.4525" not in text


def test_mail_subject_carries_conclusion_and_caps_200():
    from illumio_ops.services.reports.render_email import SUBJECT_MAX, render_email
    doc = _doc([]).model_copy(update={"conclusion": "x" * 500})
    subject = render_email(doc, tz=UTC).subject
    assert len(subject) <= SUBJECT_MAX and subject.endswith("…")
    short = render_email(_doc([]).model_copy(update={"conclusion": "Seven new connections"}), tz=UTC)
    assert "Seven new connections" in short.subject and "Seven new connections" in short.text



def test_custom_period_in_the_report_zone():
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    tpe = ZoneInfo("Asia/Taipei")
    doc = _doc([], ReportType.CUSTOM).model_copy(update={
        "period_start": dt(2026, 11, 1, tzinfo=tpe), "period_end": dt(2026, 11, 2, tzinfo=tpe)})
    assert "2026-11-01 – 2026-11-01" in conclusion(doc, _tr(Language.EN), tz=tpe)


def test_html_mail_opens_with_the_conclusion():
    from illumio_ops.services.reports.render_email import render_email
    mail = render_email(_doc([]).model_copy(update={"conclusion": "Seven new connections"}), tz=UTC)
    assert mail.html is not None and "Seven new connections" in mail.html


@pytest.mark.parametrize(("lang", "word"), [(Language.ZH_TW, "Draft"), (Language.EN, "draft")])
def test_policy_usage_says_its_rules_are_the_drafts(lang, word):
    """lab .135 2026-11-03: policy usage read "64 rules" beside policy resolver's "0 active rules" — it counts the
    allow rules of the Draft (it recomputes against the Draft), and its sentence and tile have to say so."""
    assert word in translate(lang, CONCLUSION_KEYS[ReportType.POLICY_USAGE], {})
    assert word in translate(lang, "rpt_pu_kpi_rules", {})


@pytest.mark.parametrize("report_type", [ReportType.TRAFFIC, ReportType.NETWORK_INVENTORY, ReportType.APP_SUMMARY,
                                         ReportType.READINESS, ReportType.POLICY_USAGE])
def test_a_sum_of_connection_counts_is_counted_in_times(report_type):
    """lab .106 2026-11-03: traffic's 「連線 9,201,239 條」 (the PCE's per-flow connection counts added up) beside new
    connections' 「新出現的連線 70,223 條」 (distinct source, destination and port) read as the same thing. A sum is
    「次」; a distinct connection stays 「條」."""
    text = dictionary(Language.ZH_TW)[CONCLUSION_KEYS[report_type]]
    assert "次" in text and not re.search(r"連線[^；。]*\{\w+\} 條", text)
    assert "條" in dictionary(Language.ZH_TW)[CONCLUSION_KEYS[ReportType.NEW_CONNECTIONS]]
