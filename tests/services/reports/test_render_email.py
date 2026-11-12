"""The report email body (spec §6.5.5; UI redesign spec §9.1: the email is the report's first page — the conclusion,
what to know before the numbers, three numbers, the three things to do — readable without the attachments)."""
import html
import re
from datetime import UTC

import pytest

from illumio_ops.domain.report import Finding, Kpi, Section
from illumio_ops.domain.values import Language, ReportType, Severity
from illumio_ops.services.reports.render_email import render_email
from tests.services.reports.conftest import make_doc
from tests.services.reports.test_render_html import _f, _unevaluated

KPIS = (Kpi(key="a", label="Pivot hosts", value=4, previous=1, better="lower"),
        Kpi(key="b", label="New detections", value=2, previous=None),
        Kpi(key="c", label="Assets", value=None, previous=None, note="no critical assets"),
        Kpi(key="d", label="Cross-env", value=5, previous=5))


def _findings(n):
    return tuple(Finding(severity=Severity.HIGH, title=f"Finding {i}", why=f"Why {i}", action=f"Do {i}")
                 for i in range(n))


def _said(page: str) -> str:
    """The HTML body as a reader sees it: tags gone, entities read, whitespace one space."""
    body = page.split("<body>", 1)[1]
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def test_subject_counts_findings():
    r = render_email(make_doc(findings=_findings(3)), tz=UTC)
    assert "Lateral movement posture" in r.subject and "2026-10-20 – 2026-10-26" in r.subject and "3" in r.subject


def test_three_numbers_each_with_change_direction_and_note():
    r = render_email(make_doc(kpis=KPIS), tz=UTC)
    for text in ("Pivot hosts", "Up 3 from the previous period", "Lower is better", "no critical assets"):
        assert text in r.text and text in r.html
    for part in (r.text, r.html):  # the fourth number is in the report, not in the email
        assert "Cross-env" not in part and "Unchanged" not in part and "No previous period" not in part


def test_the_three_things_to_do_not_every_finding():
    findings = (_f("Open RDP", "enforce", Severity.CRITICAL), _f("Open SMB", "enforce"),
                _f("Cross-env flows", "cross_env_rules"), _f("Wide rule", "narrow_rules", Severity.MEDIUM),
                _f("Unmanaged sources", "unmanaged", Severity.LOW))
    r = render_email(make_doc(findings=findings), tz=UTC)
    for part in (r.text, _said(r.html)):
        assert "What to do first (3)" in part
        assert "Short enforce." in part and "Findings this addresses (2): Open RDP, Open SMB" in part
        assert "Short cross_env_rules." in part and "Short narrow_rules." in part
        assert "1 more to do; see the report." in part
        assert "Short unmanaged." not in part  # the fourth thing is counted, not listed
        assert "why Open RDP" not in part and "do Open RDP" not in part  # no finding is written out
    assert "[Critical] Short enforce." in r.text


def test_the_data_notes_are_not_in_the_email():
    r = render_email(make_doc(data_quality=("Traffic covers the whole period.", "A second note.")), tz=UTC)
    for part in (r.text, r.html):
        assert "Traffic covers the whole period." not in part and "Data notes" not in part


def test_caveats_under_the_conclusion():
    doc = make_doc(kpis=KPIS).model_copy(update={"conclusion": "One thing to do.",
                                                 "caveats": ("Two stretches were not collected.",)})
    r = render_email(doc, tz=UTC)
    for part in (r.text, _said(r.html)):
        places = [part.index(x) for x in ("One thing to do.", "Know this before reading the numbers",
                                          "Two stretches were not collected.", "Pivot hosts")]
        assert places == sorted(places)
    plain = render_email(make_doc(), tz=UTC)
    assert "Know this before" not in plain.text and "Know this before" not in plain.html


def test_zero_findings_sentence():
    r = render_email(make_doc(), tz=UTC)
    assert "Nothing in this report needs action" in r.text and "Nothing in this report needs action" in r.html


@pytest.mark.parametrize("rows,words", [
    ([("L006", "no exposure analysis")], "Rules that could not be evaluated: 1; see “Rules not evaluated”."),
    ([], "This period has no traffic to evaluate the rules on; see “Rules not evaluated”.")])
def test_rules_not_evaluated_are_never_nothing_to_do(rows, words):
    r = render_email(make_doc(sections=(_unevaluated(rows),)), tz=UTC)
    for part in (r.text, _said(r.html)):
        assert words in part and "Nothing in this report needs action" not in part


def test_a_custom_report_has_no_things_to_do():
    doc = make_doc(report_type=ReportType.CUSTOM, kpis=(), sections=(Section(id="s1", title="Saved section"),))
    r = render_email(doc, tz=UTC)
    for part in (r.text, r.html):
        assert "Nothing in this report needs action" not in part and "What to do first" not in part


def test_no_link_without_external_url():
    r = render_email(make_doc(), tz=UTC)
    assert "No GUI address is set" in r.text and "href" not in r.html.split("<body", 1)[1].split("illumio-ops", 1)[0]
    assert "attached report" not in r.text and "attached report" not in r.html  # nothing said to be attached


def test_no_link_points_at_the_attachment_when_there_is_one():
    r = render_email(make_doc(findings=_findings(2)), tz=UTC, attached=True)
    for part in (r.text, r.html):
        assert "No GUI address is set" in part and "The full findings are in the attached report." in part
    linked = render_email(make_doc(findings=_findings(2), gui_link="https://ops.example/reports?id=9"), tz=UTC,
                          attached=True)
    assert "attached report" not in linked.text and "attached report" not in linked.html


def test_no_findings_are_said_to_be_in_the_attachment_when_there_are_none():
    """Not after "nothing needs action", and not for a custom report (it has no rules)."""
    custom = make_doc(report_type=ReportType.CUSTOM, kpis=(), sections=(Section(id="s1", title="Saved section"),))
    for doc in (make_doc(), custom):
        r = render_email(doc, tz=UTC, attached=True)
        for part in (r.text, r.html):
            assert "No GUI address is set" in part and "attached report" not in part


def test_the_note_about_dropped_attachments_stays():
    r = render_email(make_doc(), tz=UTC, note="The files are too large to attach.")
    for part in (r.text, r.html):
        assert "The files are too large to attach." in part and "attached report" not in part


def test_link_with_external_url():
    r = render_email(make_doc(gui_link="https://ops.example/reports?id=9"), tz=UTC)
    assert "https://ops.example/reports?id=9" in r.text and 'href="https://ops.example/reports?id=9"' in r.html


def test_html_escapes_and_uses_shell_colours_only():
    doc = make_doc(
        title="<i>t</i>", kpis=(Kpi(key="a", label="<u>k</u>", value=1, previous=None, note="<s>n</s>"),),
        findings=(_f("<b>x</b>", "enforce", action_short="<em>short</em>"),),
    ).model_copy(update={"conclusion": "<p>c</p>", "caveats": ("<a>cav</a>",)})
    r = render_email(doc, tz=UTC, note="<q>note</q>")
    for raw in ("<b>x</b>", "<i>t</i>", "<u>k</u>", "<s>n</s>", "<em>short</em>", "<p>c</p>", "<a>cav</a>",
                "<q>note</q>"):
        assert raw not in r.html and html.escape(raw) in r.html and raw in r.text
    colours = set(re.findall(r"#[0-9A-Fa-f]{6}", r.html))
    from illumio_ops.services.reports.render_email import TOKENS
    assert colours <= {c.upper() for c in TOKENS.values()} | {c.lower() for c in TOKENS.values()}


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
def test_the_text_and_the_html_say_the_same(lang):
    findings = (_f("Open RDP", "enforce", Severity.CRITICAL), _f("Open SMB", "enforce"),
                _f("Cross-env flows", "cross_env_rules"), _f("Wide rule", "narrow_rules", Severity.MEDIUM),
                _f("Unmanaged sources", "unmanaged", Severity.LOW))
    doc = make_doc(lang=lang, kpis=KPIS, findings=findings, sections=(_unevaluated([("L006", "x")]),)).model_copy(
        update={"conclusion": "One thing to do.", "caveats": ("Two stretches were not collected.",)})
    for kw in ({"attached": True}, {"note": "Too large."}):  # (the document has findings)
        r = render_email(doc, tz=UTC, **kw)
        said = _said(r.html).replace(" ", "")
        # a line of the text is one or more things the HTML sets apart (a number's name, its value, what is under it)
        pieces = [x.strip().replace(" ", "") for line in r.text.splitlines()
                  for x in re.split(r"^- |[:;()]", line) if x.strip()]
        assert len(pieces) > 20 and not [x for x in pieces if x not in said]
        text = r.text.replace(" ", "").replace("\n", "")  # and nothing is in the HTML alone
        shown = [x.replace(" ", "") for x in re.split(r"<[^>]+>", r.html.split("<body>", 1)[1]) if x.strip()]
        alone = [x for x in shown if not all(piece in text for piece in re.split(r"[·:;()]|PCE", html.unescape(x)) if piece)]
        assert not alone, alone


def test_zh_tw_body():
    r = render_email(make_doc(lang=Language.ZH_TW, kpis=KPIS), tz=UTC)
    assert "無上期資料" not in r.text and "［illumio-ops］" in r.subject
    assert "越低越好" in r.text and "本期沒有需要處理的項目。" in r.html


def test_a_report_with_no_key_number_prints_no_heading_over_nothing():
    """6.6.0: a report where nothing was computed (ransomware before its analysis) has its sentence and no "Key
    metrics" heading with nothing under it. (The data notes that say why are in the report, not in the email.)"""
    doc = make_doc(kpis=(), data_quality=("The ransomware analysis has not been computed yet.",)).model_copy(
        update={"conclusion": "No ransomware protection analysis result for this period; the data notes say why."})
    r = render_email(doc, tz=UTC)
    assert "Key metrics" not in r.text and "Key metrics" not in r.html
    for part in (r.text, r.html):
        assert "the data notes say why" in part
    one = render_email(make_doc(kpis=KPIS[:1]), tz=UTC)
    assert "Key metrics" in one.text and "()" not in one.text
