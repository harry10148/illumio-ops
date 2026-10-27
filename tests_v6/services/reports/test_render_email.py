"""The report email body (P5a Task 6, spec §6.5.5: the body is the summary, readable without the attachments)."""
from datetime import UTC

from illumio_ops.domain.report import Finding, Kpi
from illumio_ops.domain.values import Language, Severity
from illumio_ops.services.reports.render_email import render_email
from tests_v6.services.reports.conftest import make_doc

KPIS = (Kpi(key="a", label="Pivot hosts", value=4, previous=1), Kpi(key="b", label="New detections", value=2,
                                                                    previous=None),
        Kpi(key="c", label="Assets", value=None, previous=None, note="no critical assets"),
        Kpi(key="d", label="Cross-env", value=5, previous=5))


def _findings(n):
    return tuple(Finding(severity=Severity.HIGH, title=f"Finding {i}", why=f"Why {i}", action=f"Do {i}")
                 for i in range(n))


def test_subject_counts_findings():
    r = render_email(make_doc(findings=_findings(3)), tz=UTC)
    assert "Lateral movement posture" in r.subject and "2026-10-20 – 2026-10-26" in r.subject and "3" in r.subject


def test_four_kpis_with_previous_or_none():
    r = render_email(make_doc(kpis=KPIS), tz=UTC)
    for text in ("Pivot hosts", "▲ 3", "No previous period", "no critical assets", "Unchanged"):
        assert text in r.text and text in r.html


def test_findings_with_why_and_action():
    r = render_email(make_doc(findings=_findings(2)), tz=UTC)
    assert "Why 1" in r.text and "Do 1" in r.html


def test_zero_findings_sentence():
    r = render_email(make_doc(), tz=UTC)
    assert "Nothing in this report needs action" in r.text


def test_no_link_without_external_url():
    r = render_email(make_doc(), tz=UTC)
    assert "No GUI address is set" in r.text and "href" not in r.html.split("<body", 1)[1].split("illumio-ops", 1)[0]


def test_link_with_external_url():
    r = render_email(make_doc(gui_link="https://ops.example/reports?id=9"), tz=UTC)
    assert "https://ops.example/reports?id=9" in r.text and 'href="https://ops.example/reports?id=9"' in r.html


def test_html_escapes_and_uses_shell_colours_only():
    r = render_email(make_doc(findings=(Finding(severity=Severity.HIGH, title="<b>x</b>", why="w", action="a"),)),
                     tz=UTC)
    assert "<b>x</b>" not in r.html and "&lt;b&gt;" in r.html
    import re
    colours = set(re.findall(r"#[0-9A-Fa-f]{6}", r.html))
    from illumio_ops.services.reports.render_email import TOKENS
    assert colours <= {c.upper() for c in TOKENS.values()} | {c.lower() for c in TOKENS.values()}


def test_zh_tw_body():
    r = render_email(make_doc(lang=Language.ZH_TW, kpis=KPIS), tz=UTC)
    assert "無上期資料" in r.text and "［illumio-ops］" in r.subject
