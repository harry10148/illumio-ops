"""Each report opens with one sentence computed from its own key numbers (UI redesign spec §6, §8): every type has a
template in both languages, every placeholder is a number the type's builder produces, and a number that could not
be computed makes it say so instead of 0."""
import re
from datetime import UTC

import pytest

from illumio_ops.domain.conclusion import CONCLUSION_KEYS, CONCLUSION_KPIS, conclusion
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


@pytest.mark.parametrize("report_type", [t for t in ReportType if t is not ReportType.CUSTOM])
def test_declared_kpis_exist_in_builder_output(ctx, report_type):  # noqa: F811
    cond = APP_DB if specs()[report_type].requires_app else None
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=report_type, filter=cond), start=START, end=END,
                     lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")
    doc = specs()[report_type].build(inp)
    assert set(CONCLUSION_KPIS[report_type]) <= {k.key for k in doc.kpis}, report_type
    text = conclusion(doc, _tr(Language.EN))
    assert text and "{" not in text and "None" not in text


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
