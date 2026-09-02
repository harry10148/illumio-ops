"""`report draft-policy` output must be distinguishable from `report security`.

Both commands write a `Illumio_Traffic_Report_SecurityRisk_*` file with the same
cover title and the same `"report_type": "traffic"` sidecar. Before this badge
the only difference was the body content, so an operator holding two files could
not tell which command produced which. Found during the phase 2B Task 7
acceptance run (2026-09-02) on live appliance data.

`compute_draft` cannot stand in for it: any traffic-family profile turns it on
when a ruleset asks for draft decisions, so `report security` carries it too.
"""
from src.i18n import t
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter


def _cover(**kwargs) -> str:
    return SecurityRiskHtmlExporter({}, **kwargs)._build()


def test_draft_policy_report_is_named_on_the_cover():
    for lang in ("en", "zh_TW"):
        html = _cover(draft_policy_report=True, lang=lang)
        assert t("rpt_cover_draft_policy_report", lang=lang) in html


def test_plain_security_report_carries_no_draft_policy_badge():
    for lang in ("en", "zh_TW"):
        html = _cover(lang=lang)
        assert t("rpt_cover_draft_policy_report", lang=lang) not in html


def test_compute_draft_alone_does_not_claim_a_draft_policy_report():
    """The distinguishing badge must not ride on compute_draft.

    A `report security` run against a ruleset that needs draft decisions sets
    compute_draft — it still is not a draft-policy report.
    """
    html = _cover(compute_draft=True, lang="en")
    assert t("rpt_hdr_draft_enabled", lang="en") in html
    assert t("rpt_cover_draft_policy_report", lang="en") not in html
